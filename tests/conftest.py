"""测试公共配置。

隔离规约（见 docs/CREATORHUB_FEATURE_MIGRATION_PLAN.md §5）：
1. src 布局下把 src 加入 sys.path（免可编辑安装）；
2. 【外网哨兵】autouse 拦截一切真实 httpx 外网请求——未 mock 的外部调用直接失败，
   定位"测试反复打真实平台接口"这类问题（respx assert_all_mocked 默认行为）；
3. 【浏览器哨兵】autouse 禁止测试启动真实浏览器（weread 扫码/续期、抖音/快手/视频号
   引擎层）——需要真浏览器的冒烟测试用 @pytest.mark.real_browser 标记显式豁免。
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _block_external_http():
    """全量拦截 httpx 真实外网请求；TestClient 的 testserver 传输不受影响。"""
    import respx

    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture(autouse=True)
def _block_real_browser(request):
    """禁止测试拉起真实浏览器；显式标记 real_browser 的用例豁免。"""
    marker = request.node.get_closest_marker("real_browser")
    if marker:
        yield
        return

    from flowpulse.modules.browser import engine as browser_engine
    from flowpulse.modules.weread import qrlogin as weread_qrlogin

    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "测试不允许启动真实浏览器：请 mock 浏览器边界，"
            "或给用例加 @pytest.mark.real_browser 显式豁免"
        )

    original_engine = browser_engine.launch_persistent_context
    original_weread_capture = weread_qrlogin.WereadQrLoginManager.capture_cookie_headless
    original_weread_start = weread_qrlogin.WereadQrLoginManager.start
    browser_engine.launch_persistent_context = _forbidden
    weread_qrlogin.WereadQrLoginManager.capture_cookie_headless = _forbidden
    weread_qrlogin.WereadQrLoginManager.start = _forbidden
    try:
        yield
    finally:
        browser_engine.launch_persistent_context = original_engine
        weread_qrlogin.WereadQrLoginManager.capture_cookie_headless = original_weread_capture
        weread_qrlogin.WereadQrLoginManager.start = original_weread_start
