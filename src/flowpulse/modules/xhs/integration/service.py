from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from flowpulse.modules.xhs.apis.xhs_creator_apis import XHS_Creator_Apis
from flowpulse.modules.xhs.apis.xhs_pc_apis import XHS_Apis
from flowpulse.modules.xhs.apis.xhs_pugongying_apis import PuGongYingAPI
from flowpulse.modules.xhs.apis.xhs_qianfan_apis import QianFanAPI
from flowpulse.modules.xhs.integration.login_drivers import make_driver
from flowpulse.modules.xhs.integration.models import (
    CreateJobRequest,
    JobRecord,
    JobStatus,
    JobType,
    LoginStatus,
)
from flowpulse.modules.xhs.integration.store import CookieStore, JobRepository, LoginSessionRegistry
from flowpulse.modules.xhs.spider.spider import Data_Spider
from flowpulse.modules.xhs.xhs_utils.cookie_util import trans_cookies
from flowpulse.modules.xhs.xhs_utils.data_util import handle_note_info
from flowpulse.modules.xhs.xhs_utils.xhs_creator import XHSCreatorAuth
from flowpulse.modules.xhs.xhs_utils.xhs_pc import XHSPcAuth


class XhsService:
    """Async facade over the synchronous XHS spider.

    All blocking curl_cffi / Node-signing calls run in worker threads; a
    per-platform lock serialises access to a cached authenticated api object
    because a curl_cffi Session is not concurrency safe.

    Interactive login (qrcode / phone) is stateful and multi-step. Its
    curl_cffi Session must be created and used from a single OS thread for the
    whole flow — the same way the original Spider_XHS ``qrcode_login`` runs
    synchronously on one thread. Hopping the session across ``to_thread`` pool
    threads changes libcurl's per-handle connection/TLS state and gets the
    final session-exchange call soft-rejected by XHS risk control. Each login
    session therefore owns a dedicated single-thread executor.
    """

    def __init__(self, data_dir: Path, proxy: str | None = None, credential_key: str = ""):
        self.data_dir = data_dir
        self.cookies = CookieStore(data_dir, credential_key)
        self.jobs = JobRepository(data_dir)
        self.sessions = LoginSessionRegistry()
        # curl_cffi expects a proxies mapping; None means direct connection.
        self._proxies = {"http": proxy, "https": proxy} if proxy else None
        self._pc_api: XHS_Apis | None = None
        self._creator_api: XHS_Creator_Apis | None = None
        self._locks = {"pc": threading.Lock(), "creator": threading.Lock()}
        self._running: set[asyncio.Task] = set()

    # --- auth -----------------------------------------------------------

    def _build_pc_api(self) -> XHS_Apis:
        if self._pc_api is not None:
            return self._pc_api
        cookie = self.cookies.get("pc")
        if not cookie:
            raise RuntimeError("尚未登录 PC 平台，请先调用登录接口")
        auth = XHSPcAuth.from_cookie(cookie, proxies=self._proxies)
        api = XHS_Apis(auth)
        api.bootstrap(proxies=self._proxies)
        self._pc_api = api
        return api

    def _build_creator_api(self) -> XHS_Creator_Apis:
        if self._creator_api is not None:
            return self._creator_api
        cookie = self.cookies.get("creator")
        if not cookie:
            raise RuntimeError("尚未登录 Creator 平台，请先调用登录接口")
        auth = XHSCreatorAuth.from_cookie(cookie, proxies=self._proxies)
        api = XHS_Creator_Apis(auth)
        api.bootstrap(proxies=self._proxies)
        self._creator_api = api
        return api

    def _invalidate(self, platform: str) -> None:
        if platform == "pc":
            self._pc_api = None
        elif platform == "creator":
            self._creator_api = None

    def set_cookie(self, platform: str, cookie: str) -> None:
        self.cookies.set(platform, cookie)
        self._invalidate(platform)

    # --- login: cookie --------------------------------------------------

    async def login_cookie(self, platform: str, cookie: str) -> LoginStatus:
        def work() -> LoginStatus:
            self.set_cookie(platform, cookie)
            return self._status_sync(platform)

        return await asyncio.to_thread(work)

    def _status_sync(self, platform: str) -> LoginStatus:
        cookie = self.cookies.get(platform)
        if not cookie:
            return LoginStatus(platform=platform, logged_in=False, message="未登录")
        try:
            if platform == "pc":
                with self._locks["pc"]:
                    api = self._build_pc_api()
                    user_id = getattr(api.auth, "user_id", None)
            else:
                with self._locks["creator"]:
                    api = self._build_creator_api()
                    user_id = getattr(api.auth, "user_id", None)
            return LoginStatus(
                platform=platform, logged_in=True, user_id=user_id, message="已登录"
            )
        except Exception as exc:
            self._invalidate(platform)
            return LoginStatus(platform=platform, logged_in=False, message=str(exc))

    async def login_status(self, platform: str) -> LoginStatus:
        return await asyncio.to_thread(self._status_sync, platform)

    # --- login: qrcode --------------------------------------------------

    @staticmethod
    async def _run_on(executor: ThreadPoolExecutor, fn):
        """Run a blocking callable on a specific single-thread executor."""
        return await asyncio.get_running_loop().run_in_executor(executor, fn)

    def _close_session(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session and session.get("executor"):
            session["executor"].shutdown(wait=False)
        self.sessions.drop(session_id)

    async def qrcode_start(self, platform: str) -> tuple[str, str | None]:
        """Return (session_id, qr_url). qr_url is None if already logged in."""
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xhs-login")

        # The driver (and its curl_cffi Session) must be created on the executor
        # thread so the whole login lives on one thread.
        def work() -> tuple[object, str | None]:
            driver = make_driver(platform, self._proxies)
            return driver, driver.start_qrcode()

        driver, qr_url = await self._run_on(executor, work)
        if qr_url is None and getattr(driver, "ready_cookie", None):
            self.set_cookie(platform, driver.ready_cookie)
            executor.shutdown(wait=False)
            return "", None
        session_id = uuid4().hex
        self.sessions.put(
            session_id, {"driver": driver, "platform": platform, "executor": executor}
        )
        return session_id, qr_url

    async def qrcode_poll(self, session_id: str) -> tuple[str, str, bool]:
        session = self.sessions.get(session_id)
        if not session:
            return "error", "登录会话不存在或已过期", False

        def work() -> tuple[str, str, bool]:
            driver = session["driver"]
            try:
                status, message, cookie = driver.poll_qrcode()
            except Exception as exc:
                # Keep the session alive so the client can retry a transient
                # failure during the confirm step instead of restarting login.
                return "waiting", f"轮询失败，可重试: {exc}", False
            if cookie:
                self.set_cookie(session["platform"], cookie)
                return "confirmed", message, True
            return status, message, False

        status, message, logged_in = await self._run_on(session["executor"], work)
        if logged_in or status in ("expired", "error"):
            self._close_session(session_id)
        return status, message, logged_in

    # --- login: phone ---------------------------------------------------

    async def phone_send(self, platform: str, phone: str, zone: str = "86") -> tuple[str, str]:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xhs-login")

        def work() -> tuple[object, object]:
            driver = make_driver(platform, self._proxies)
            return driver, driver.start_phone(phone, zone)

        driver, ready = await self._run_on(executor, work)
        if ready and getattr(driver, "ready_cookie", None):
            self.set_cookie(platform, driver.ready_cookie)
            executor.shutdown(wait=False)
            return "", "检测到可复用会话，已直接登录"
        session_id = uuid4().hex
        self.sessions.put(
            session_id, {"driver": driver, "platform": platform, "executor": executor}
        )
        return session_id, "验证码已发送"

    async def phone_verify(self, session_id: str, code: str) -> LoginStatus:
        session = self.sessions.get(session_id)
        if not session:
            raise RuntimeError("登录会话不存在或已过期")

        def work() -> str:
            return session["driver"].verify_phone(code)

        try:
            cookie = await self._run_on(session["executor"], work)
            self.set_cookie(session["platform"], cookie)
            return self._status_sync(session["platform"])
        finally:
            self._close_session(session_id)

    # --- data (quick, synchronous under the hood) -----------------------

    @staticmethod
    def _guard(fn):
        """Run a data call, converting exceptions into a (False, msg, None) tuple."""
        try:
            return fn()
        except Exception as exc:
            return False, str(exc), None

    async def note_detail(self, url: str):
        def work():
            with self._locks["pc"]:
                api = self._build_pc_api()
                ok, msg, res = api.get_note_info(url)
                if not ok:
                    return ok, msg, None
                note = res["data"]["items"][0]
                note["url"] = url
                return ok, msg, handle_note_info(note)

        return await asyncio.to_thread(self._guard, work)

    async def user_notes(self, user_url: str):
        def work():
            with self._locks["pc"]:
                api = self._build_pc_api()
                return api.get_user_all_notes(user_url)

        return await asyncio.to_thread(self._guard, work)

    async def search(self, req):
        def work():
            with self._locks["pc"]:
                api = self._build_pc_api()
                return api.search_some_note(
                    req.query,
                    req.require_num,
                    req.sort_type_choice,
                    req.note_type,
                    req.note_time,
                    req.note_range,
                    req.pos_distance,
                    req.geo or "",
                )

        return await asyncio.to_thread(self._guard, work)

    async def comments(self, url: str):
        def work():
            with self._locks["pc"]:
                api = self._build_pc_api()
                return api.get_note_all_comment(url)

        return await asyncio.to_thread(self._guard, work)

    async def creator_posted_notes(self):
        def work():
            with self._locks["creator"]:
                api = self._build_creator_api()
                return api.get_all_posted_notes()

        return await asyncio.to_thread(self._guard, work)

    # --- PC read-only extras --------------------------------------------

    async def user_info(self, user_id: str):
        def work():
            with self._locks["pc"]:
                return self._build_pc_api().get_user_info(user_id)

        return await asyncio.to_thread(self._guard, work)

    async def user_like_notes(self, user_url: str):
        def work():
            with self._locks["pc"]:
                return self._build_pc_api().get_user_all_like_note_info(user_url)

        return await asyncio.to_thread(self._guard, work)

    async def user_collect_notes(self, user_url: str):
        def work():
            with self._locks["pc"]:
                return self._build_pc_api().get_user_all_collect_note_info(user_url)

        return await asyncio.to_thread(self._guard, work)

    async def search_users(self, query: str, require_num: int):
        def work():
            with self._locks["pc"]:
                return self._build_pc_api().search_some_user(query, require_num)

        return await asyncio.to_thread(self._guard, work)

    async def homefeed(self, category: str, require_num: int):
        def work():
            with self._locks["pc"]:
                return self._build_pc_api().get_homefeed_recommend_by_num(category, require_num)

        return await asyncio.to_thread(self._guard, work)

    async def homefeed_channels(self):
        def work():
            with self._locks["pc"]:
                return self._build_pc_api().get_homefeed_all_channel()

        return await asyncio.to_thread(self._guard, work)

    async def search_keyword(self, word: str):
        def work():
            with self._locks["pc"]:
                return self._build_pc_api().get_search_keyword(word)

        return await asyncio.to_thread(self._guard, work)

    async def unread_message(self):
        def work():
            with self._locks["pc"]:
                return self._build_pc_api().get_unread_message()

        return await asyncio.to_thread(self._guard, work)

    async def mentions(self):
        def work():
            with self._locks["pc"]:
                return self._build_pc_api().get_all_metions()

        return await asyncio.to_thread(self._guard, work)

    async def likes_and_collects(self):
        def work():
            with self._locks["pc"]:
                return self._build_pc_api().get_all_likesAndcollects()

        return await asyncio.to_thread(self._guard, work)

    async def new_connections(self):
        def work():
            with self._locks["pc"]:
                return self._build_pc_api().get_all_new_connections()

        return await asyncio.to_thread(self._guard, work)

    async def no_water_video(self, note_id: str):
        return await asyncio.to_thread(
            self._guard, lambda: XHS_Apis.get_note_no_water_video(note_id)
        )

    async def no_water_image(self, img_url: str):
        return await asyncio.to_thread(
            self._guard, lambda: XHS_Apis.get_note_no_water_img(img_url)
        )

    # --- Creator read + publish -----------------------------------------

    async def creator_user_info(self):
        def work():
            with self._locks["creator"]:
                return self._build_creator_api().get_user_info()

        return await asyncio.to_thread(self._guard, work)

    async def creator_topic(self, keyword: str):
        def work():
            with self._locks["creator"]:
                return self._build_creator_api().get_topic(keyword)

        return await asyncio.to_thread(self._guard, work)

    async def creator_location(self, keyword: str):
        def work():
            with self._locks["creator"]:
                return self._build_creator_api().get_location_info(keyword)

        return await asyncio.to_thread(self._guard, work)

    async def creator_upload_media(self, path: str, media_type: str):
        def work():
            with self._locks["creator"]:
                return self._build_creator_api().upload_media(path, media_type)

        return await asyncio.to_thread(self._guard, work)

    async def creator_post_note(self, note_info: dict):
        def work():
            with self._locks["creator"]:
                return self._build_creator_api().post_note(note_info)

        return await asyncio.to_thread(self._guard, work)

    # --- PuGongYing (蒲公英) / QianFan (千帆) ---------------------------

    def _cookies_dict(self, cookies: str | None) -> dict:
        raw = cookies or self.cookies.get("pc")
        if not raw:
            raise RuntimeError("缺少 cookies：请传入 cookies 或先登录 PC 平台")
        return trans_cookies(raw)

    async def pgy_categories(self, cookies: str | None):
        def work():
            return True, "成功", PuGongYingAPI().get_all_categories(self._cookies_dict(cookies))

        return await asyncio.to_thread(self._guard, work)

    async def pgy_users(self, num: int, content_tag: str | None, cookies: str | None):
        def work():
            ck = self._cookies_dict(cookies)
            return True, "成功", PuGongYingAPI().get_some_user(num, ck, content_tag)

        return await asyncio.to_thread(self._guard, work)

    async def pgy_user_detail(self, user_id: str, cookies: str | None):
        def work():
            ck = self._cookies_dict(cookies)
            api = PuGongYingAPI()
            return True, "成功", {
                "summary": api.get_user_detail(user_id, ck),
                "fans": api.get_user_fans_detail(user_id, ck),
                "notes": api.get_user_notes_detail(user_id, ck),
            }

        return await asyncio.to_thread(self._guard, work)

    async def qianfan_categories(self, cookies: str | None):
        def work():
            return True, "成功", QianFanAPI().get_all_categories(self._cookies_dict(cookies))

        return await asyncio.to_thread(self._guard, work)

    async def qianfan_users(self, choice: str, num: int, cookies: str | None):
        def work():
            ck = self._cookies_dict(cookies)
            api = QianFanAPI()
            categories = api.get_all_categories(ck)
            return True, "成功", api.get_some_user(choice, categories, num, ck)

        return await asyncio.to_thread(self._guard, work)

    async def qianfan_user_detail(self, user_id: str, cookies: str | None):
        def work():
            ck = self._cookies_dict(cookies)
            api = QianFanAPI()
            return True, "成功", {
                "overview": api.get_user_detail(user_id, ck),
                "cooperation": api.get_user_cooperation(user_id, ck),
                "shop": api.get_user_shop(user_id, ck),
                "item": api.get_user_item(user_id, ck),
                "fans": api.get_user_fans(user_id, ck),
            }

        return await asyncio.to_thread(self._guard, work)

    # --- async download / export jobs -----------------------------------

    def create_job(self, request: CreateJobRequest) -> JobRecord:
        record = JobRecord(id=uuid4().hex, type=request.type, request=request)
        self.jobs.save(record)
        task = asyncio.create_task(self._run_job(record.id))
        self._running.add(task)
        task.add_done_callback(self._running.discard)
        return record

    async def _run_job(self, job_id: str) -> None:
        record = self.jobs.get(job_id)
        if not record:
            return
        record.status = JobStatus.RUNNING
        record.message = "开始抓取"
        self.jobs.save(record)
        try:
            await asyncio.to_thread(self._execute_job_sync, record)
            record.status = JobStatus.COMPLETED
            record.message = "完成"
        except Exception as exc:
            record.status = JobStatus.FAILED
            record.error = str(exc)
            record.message = "失败"
        self.jobs.save(record)

    def _execute_job_sync(self, record: JobRecord) -> None:
        req = record.request
        job_dir = self.jobs.job_dir(record.id)
        base_path = {
            "media": str(job_dir / "media"),
            "excel": str(job_dir / "excel"),
        }
        Path(base_path["media"]).mkdir(parents=True, exist_ok=True)
        Path(base_path["excel"]).mkdir(parents=True, exist_ok=True)
        excel_name = req.excel_name or record.id

        with self._locks["pc"]:
            api = self._build_pc_api()
            spider = Data_Spider(api.auth)
            spider.xhs_apis = api  # reuse the bootstrapped, authenticated api

            if req.type == JobType.NOTES:
                spider.spider_some_note(req.notes, base_path, req.save_choice, excel_name)
                record.note_count = len(req.notes)
            elif req.type == JobType.USER:
                note_list, ok, msg = spider.spider_user_all_note(
                    req.user_url, base_path, req.save_choice, excel_name
                )
                if not ok:
                    raise RuntimeError(str(msg))
                record.note_count = len(note_list)
            elif req.type == JobType.SEARCH:
                note_list, ok, msg = spider.spider_some_search_note(
                    req.query,
                    req.require_num,
                    base_path,
                    req.save_choice,
                    req.sort_type_choice,
                    req.note_type,
                    req.note_time,
                    req.note_range,
                    req.pos_distance,
                    geo=req.geo,
                    excel_name=excel_name,
                )
                if not ok:
                    raise RuntimeError(str(msg))
                record.note_count = len(note_list)

        record.artifacts = [
            str(path.relative_to(job_dir)).replace("\\", "/")
            for path in sorted(job_dir.rglob("*"))
            if path.is_file() and path.name != "job.json"
        ]
