import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";

import type {
  Capabilities,
  ExtensionSettings,
  TaskListItem,
  TaskRecord,
  TaskResult,
  TranscribeRequest,
  XhsJobRecord,
  XhsJobType,
  XhsPlatform,
  XhsQrcodeStart,
  XhsSaveChoice
} from "../shared/contracts";
import { XHS_API_BASE } from "../shared/contracts";
import { sendExtensionMessage } from "../shared/messages";

const XHS_JOB_TERMINAL = new Set(["completed", "failed"]);
const XHS_JOB_STATUS: Record<string, string> = {
  pending: "等待中",
  running: "抓取中",
  completed: "已完成",
  failed: "失败"
};
const XHS_JOB_TYPE_LABELS: Record<XhsJobType, string> = {
  notes: "笔记链接",
  user: "用户主页",
  search: "关键词搜索"
};
const XHS_SAVE_LABELS: Record<XhsSaveChoice, string> = {
  all: "全部（媒体+Excel）",
  media: "媒体（图+视频）",
  "media-image": "仅图片",
  "media-video": "仅视频",
  excel: "仅 Excel"
};

const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const STATUS_LABELS: Record<string, string> = {
  pending: "等待处理",
  resolving: "解析链接",
  downloading: "下载视频",
  extracting_audio: "提取音频",
  transcribing: "语音转写",
  rendering: "整理产物",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消"
};
const ENGINE_LABELS: Record<TranscribeRequest["engine"], string> = {
  auto: "自动选择",
  whisper: "Whisper",
  sensevoice: "SenseVoice",
  tingwu: "阿里听悟",
  openai: "OpenAI-compatible",
  mock: "Mock 测试"
};
const ENGINES = Object.keys(ENGINE_LABELS) as TranscribeRequest["engine"][];

type Tab = "douyin" | "xhs";

export function App() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("douyin");
  const [showSettings, setShowSettings] = useState(false);

  const settingsQuery = useQuery({
    queryKey: ["settings"],
    queryFn: () => sendExtensionMessage({ type: "settings.get" })
  });
  const connectionQuery = useQuery({
    queryKey: ["connection"],
    queryFn: () => sendExtensionMessage({ type: "connection.check" }),
    retry: false
  });

  const connected = connectionQuery.isSuccess;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">METACORPUS</p>
          <h1>元语助手</h1>
          <p className="tagline">抖音小红书元数据解析 · AI 语料提取</p>
        </div>
        <button className="icon-button" onClick={() => setShowSettings((value) => !value)}>
          {showSettings ? "关闭" : "设置"}
        </button>
      </header>

      <div className={`connection ${connected ? "connected" : "offline"}`}>
        <span className="status-dot" />
        {connected
          ? `服务已连接 · ${connectionQuery.data.service_version}`
          : "本地服务未连接"}
      </div>

      <nav className="tab-bar">
        <button
          className={`tab-button ${tab === "douyin" ? "active" : ""}`}
          onClick={() => setTab("douyin")}
        >
          抖音转写
        </button>
        <button
          className={`tab-button ${tab === "xhs" ? "active" : ""}`}
          onClick={() => setTab("xhs")}
        >
          小红书
        </button>
      </nav>

      {showSettings && settingsQuery.data ? (
        <SettingsPanel
          initial={settingsQuery.data}
          capabilities={connectionQuery.data}
          onSaved={() => {
            setShowSettings(false);
            void queryClient.invalidateQueries({ queryKey: ["settings"] });
            void queryClient.invalidateQueries({ queryKey: ["connection"] });
          }}
        />
      ) : null}

      {tab === "douyin" ? (
        <DouyinPanel
          connected={connected}
          capabilities={connectionQuery.data}
          preferredEngine={settingsQuery.data?.preferredEngine ?? "auto"}
        />
      ) : (
        <XhsPanel connected={connected} />
      )}
    </main>
  );
}

function DouyinPanel({
  connected,
  capabilities,
  preferredEngine
}: {
  connected: boolean;
  capabilities: Capabilities | undefined;
  preferredEngine: TranscribeRequest["engine"];
}) {
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [pageTitle, setPageTitle] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);

  const historyQuery = useQuery({
    queryKey: ["tasks"],
    queryFn: () => sendExtensionMessage({ type: "task.list", payload: { limit: 50 } })
  });
  const taskQuery = useQuery({
    queryKey: ["task", taskId],
    enabled: Boolean(taskId),
    queryFn: () => sendExtensionMessage({ type: "task.get", payload: { taskId: taskId! } }),
    refetchInterval: (query) => {
      const task = query.state.data as TaskRecord | undefined;
      return task && TERMINAL.has(task.status) ? false : 2_000;
    }
  });
  const resultQuery = useQuery({
    queryKey: ["result", taskId],
    enabled: taskQuery.data?.status === "completed",
    queryFn: () => sendExtensionMessage({ type: "task.result", payload: { taskId: taskId! } })
  });

  useEffect(() => {
    sendExtensionMessage({ type: "tab.captureCurrent" })
      .then((tab) => {
        if (/douyin\.com/i.test(tab.url)) setInput(tab.url);
        setPageTitle(tab.title);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (taskQuery.data && TERMINAL.has(taskQuery.data.status)) {
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  }, [queryClient, taskQuery.data]);

  const createTask = useMutation({
    mutationFn: (request: TranscribeRequest) =>
      sendExtensionMessage({ type: "task.create", payload: request }),
    onSuccess: (task) => {
      setTaskId(task.id);
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });
  const retryTask = useMutation({
    mutationFn: (id: string) =>
      sendExtensionMessage({ type: "task.retry", payload: { taskId: id } }),
    onSuccess: (task) => {
      setTaskId(task.id);
      queryClient.setQueryData(["task", task.id], task);
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    }
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = input.trim();
    if (!value) return;
    createTask.mutate({
      input: value,
      engine: preferredEngine,
      formats: ["json", "srt", "markdown"],
      keep_video: false,
      client_request_id: crypto.randomUUID(),
      context: {
        client: "chrome-extension",
        client_version: chrome.runtime.getManifest().version,
        page_url: /^https?:\/\//.test(value) ? value : undefined,
        page_title: pageTitle || undefined,
        captured_at: new Date().toISOString()
      }
    });
  }

  const engineReady = isEngineReady(preferredEngine, capabilities);
  const taskGroups = useMemo(
    () => groupTasks(historyQuery.data?.items ?? []).slice(0, 8),
    [historyQuery.data?.items]
  );

  return (
    <>
      <section className="card capture-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">NEW CAPTURE</p>
            <h2>采集一条内容</h2>
          </div>
          <span className="step-number">01</span>
        </div>
        <form onSubmit={submit}>
          <label htmlFor="input">抖音链接或分享文案</label>
          <textarea
            id="input"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="粘贴分享文案，或在抖音页面直接打开扩展"
            rows={4}
          />
          <div className="form-footer">
            <span>{ENGINE_LABELS[preferredEngine]}</span>
            <button
              className="primary-button"
              disabled={!connected || !engineReady || !input.trim() || createTask.isPending}
            >
              {createTask.isPending ? "正在创建…" : "开始整理"}
            </button>
          </div>
          {connected && !engineReady ? (
            <p className="warning-text">
              当前引擎不可用，请在设置中选择已配置的引擎；界面测试可选择 Mock。
            </p>
          ) : null}
          {createTask.error ? <p className="error-text">{createTask.error.message}</p> : null}
        </form>
      </section>

      {taskQuery.data ? (
        <TaskPanel
          task={taskQuery.data}
          result={resultQuery.data}
          retrying={retryTask.isPending}
          onRetry={() => retryTask.mutate(taskQuery.data.id)}
        />
      ) : null}

      <section className="history-section">
        <div className="section-heading compact">
          <div>
            <p className="eyebrow">RECENT</p>
            <h2>最近任务</h2>
          </div>
          <button
            className="text-button"
            onClick={() => void historyQuery.refetch()}
            disabled={historyQuery.isFetching}
          >
            刷新
          </button>
        </div>
        <div className="task-list">
          {taskGroups.map((group) => (
            <button
              className={`task-row ${taskId === group.task.id ? "selected" : ""}`}
              key={group.key}
              onClick={() => setTaskId(group.task.id)}
            >
              <div>
                <strong title={group.task.title}>{shortInput(group.task.title)}</strong>
                <span>
                  {group.task.author ? `${group.task.author} · ` : ""}
                  {new Date(group.task.created_at).toLocaleString("zh-CN")}
                  {group.attempts > 1 ? ` · ${group.attempts} 次尝试` : ""}
                  {group.failures > 0 ? ` · ${group.failures} 次失败` : ""}
                </span>
              </div>
              <span className={`status-chip status-${group.task.status}`}>
                {STATUS_LABELS[group.task.status] ?? group.task.status}
              </span>
            </button>
          ))}
          {taskGroups.length === 0 ? (
            <p className="empty-state">还没有任务，从上面采集第一条内容。</p>
          ) : null}
        </div>
      </section>
    </>
  );
}

function XhsPanel({ connected }: { connected: boolean }) {
  const queryClient = useQueryClient();
  const platform: XhsPlatform = "pc";
  const [qr, setQr] = useState<XhsQrcodeStart | null>(null);
  const [query, setQuery] = useState("");
  const [noteUrl, setNoteUrl] = useState("");

  const statusQuery = useQuery({
    queryKey: ["xhs.status", platform],
    enabled: connected,
    queryFn: () => sendExtensionMessage({ type: "xhs.loginStatus", payload: { platform } })
  });
  const loggedIn = statusQuery.data?.logged_in ?? false;

  const grabCookie = useMutation({
    mutationFn: () => sendExtensionMessage({ type: "xhs.grabCookie", payload: { platform } }),
    onSuccess: () => {
      setQr(null);
      void queryClient.invalidateQueries({ queryKey: ["xhs.status", platform] });
    }
  });
  const startQr = useMutation({
    mutationFn: () => sendExtensionMessage({ type: "xhs.qrcodeStart", payload: { platform } }),
    onSuccess: (data) => setQr(data)
  });

  const qrPoll = useQuery({
    queryKey: ["xhs.qrpoll", qr?.session_id],
    enabled: Boolean(qr?.session_id),
    refetchInterval: (q) => {
      const data = q.state.data;
      if (data && (data.logged_in || data.status === "expired" || data.status === "error")) {
        return false;
      }
      return 2_500;
    },
    queryFn: () => sendExtensionMessage({ type: "xhs.qrcodePoll", payload: { sessionId: qr!.session_id } })
  });

  useEffect(() => {
    if (qrPoll.data?.logged_in) {
      setQr(null);
      void queryClient.invalidateQueries({ queryKey: ["xhs.status", platform] });
    }
  }, [qrPoll.data?.logged_in, queryClient]);

  const search = useMutation({
    mutationFn: (value: string) =>
      sendExtensionMessage({ type: "xhs.search", payload: { query: value, requireNum: 20 } })
  });
  const noteDetail = useMutation({
    mutationFn: (url: string) => sendExtensionMessage({ type: "xhs.noteDetail", payload: { url } })
  });

  const searchItems = useMemo(() => normalizeSearch(search.data?.data), [search.data]);
  const note = noteDetail.data?.success ? (noteDetail.data.data as XhsNote) : null;

  return (
    <>
      <section className="card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">XIAOHONGSHU</p>
            <h2>登录小红书</h2>
          </div>
          <span className={`status-chip ${loggedIn ? "status-completed" : "status-failed"}`}>
            {loggedIn ? "已登录" : "未登录"}
          </span>
        </div>

        {loggedIn ? (
          <p className="task-message">
            当前账号：{statusQuery.data?.user_id ?? "已登录"}
          </p>
        ) : (
          <p className="task-message">
            在浏览器登录小红书后，点击下方按钮直接读取登录态（含 HttpOnly 的 web_session）。
          </p>
        )}

        <div className="xhs-actions">
          <button
            className="primary-button"
            disabled={!connected || grabCookie.isPending}
            onClick={() => grabCookie.mutate()}
          >
            {grabCookie.isPending ? "读取中…" : "一键获取 Cookie 登录"}
          </button>
          <button
            className="secondary-button"
            disabled={!connected || startQr.isPending}
            onClick={() => startQr.mutate()}
          >
            {startQr.isPending ? "生成中…" : "扫码登录"}
          </button>
        </div>
        {grabCookie.error ? <p className="error-text">{grabCookie.error.message}</p> : null}
        {grabCookie.data && !grabCookie.data.logged_in ? (
          <p className="error-text">{grabCookie.data.message}</p>
        ) : null}
        {startQr.error ? <p className="error-text">{startQr.error.message}</p> : null}
        {!loggedIn ? (
          <p className="hint-text">
            两种方式均可：可直接「一键获取 Cookie 登录」，或点「扫码登录」用 App 扫码。
          </p>
        ) : null}

        {qr ? (
          <div className="qr-box">
            <img src={`data:image/png;base64,${qr.qr_image_base64}`} alt="小红书登录二维码" />
            <p className="task-message">
              {qrPoll.data ? qrStatusLabel(qrPoll.data.status) : "请使用小红书 App 扫码"}
            </p>
            {qrPoll.data?.message ? <p className="hint-text">{qrPoll.data.message}</p> : null}
          </div>
        ) : null}
      </section>

      <section className="card">
        <div className="section-heading compact">
          <div>
            <p className="eyebrow">SEARCH</p>
            <h2>搜索笔记</h2>
          </div>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (query.trim()) search.mutate(query.trim());
          }}
        >
          <div className="inline-form">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="输入关键词，如 榴莲"
            />
            <button className="primary-button" disabled={!loggedIn || search.isPending || !query.trim()}>
              {search.isPending ? "搜索中…" : "搜索"}
            </button>
          </div>
        </form>
        {!loggedIn ? <p className="hint-text">请先登录后再搜索。</p> : null}
        {search.error ? <p className="error-text">{search.error.message}</p> : null}
        {search.data && !search.data.success ? (
          <p className="error-text">{search.data.message}</p>
        ) : null}
        <div className="xhs-result-list">
          {searchItems.map((item) => (
            <a
              key={item.id}
              className="xhs-result"
              href={item.url}
              target="_blank"
              rel="noreferrer"
            >
              <strong>{item.title}</strong>
              <span>{item.author}</span>
            </a>
          ))}
        </div>
      </section>

      <section className="card">
        <div className="section-heading compact">
          <div>
            <p className="eyebrow">NOTE</p>
            <h2>笔记详情</h2>
          </div>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (noteUrl.trim()) noteDetail.mutate(noteUrl.trim());
          }}
        >
          <div className="inline-form">
            <input
              value={noteUrl}
              onChange={(event) => setNoteUrl(event.target.value)}
              placeholder="粘贴笔记链接"
            />
            <button
              className="primary-button"
              disabled={!loggedIn || noteDetail.isPending || !noteUrl.trim()}
            >
              {noteDetail.isPending ? "获取中…" : "获取"}
            </button>
          </div>
        </form>
        {noteDetail.error ? <p className="error-text">{noteDetail.error.message}</p> : null}
        {noteDetail.data && !noteDetail.data.success ? (
          <p className="error-text">{noteDetail.data.message}</p>
        ) : null}
        {note ? (
          <article className="xhs-note">
            <strong>{note.title}</strong>
            <div className="result-meta">
              <span>{note.nickname}</span>
              <span>{note.note_type}</span>
              <span>赞 {note.liked_count}</span>
            </div>
            {note.desc ? <p className="xhs-desc">{note.desc}</p> : null}
            {note.video_addr ? (
              <a className="text-button" href={note.video_addr} target="_blank" rel="noreferrer">
                打开视频地址
              </a>
            ) : null}
            {note.image_list?.length ? (
              <p className="hint-text">图片 {note.image_list.length} 张</p>
            ) : null}
          </article>
        ) : null}
      </section>

      <XhsJobsSection loggedIn={loggedIn} />
    </>
  );
}

function XhsJobsSection({ loggedIn }: { loggedIn: boolean }) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<XhsJobType>("search");
  const [saveChoice, setSaveChoice] = useState<XhsSaveChoice>("all");
  const [excelName, setExcelName] = useState("");
  const [notes, setNotes] = useState("");
  const [userUrl, setUserUrl] = useState("");
  const [query, setQuery] = useState("");
  const [requireNum, setRequireNum] = useState(20);

  const jobsQuery = useQuery({
    queryKey: ["xhs.jobs"],
    enabled: loggedIn,
    queryFn: () => sendExtensionMessage({ type: "xhs.listJobs" }),
    refetchInterval: (q) => {
      const jobs = (q.state.data as XhsJobRecord[] | undefined) ?? [];
      return jobs.some((job) => !XHS_JOB_TERMINAL.has(job.status)) ? 2_500 : false;
    }
  });

  const createJob = useMutation({
    mutationFn: () => {
      const payload = {
        type,
        save_choice: saveChoice,
        excel_name: excelName.trim() || undefined,
        notes: type === "notes" ? splitLines(notes) : undefined,
        user_url: type === "user" ? userUrl.trim() : undefined,
        query: type === "search" ? query.trim() : undefined,
        require_num: type === "search" ? requireNum : undefined
      };
      return sendExtensionMessage({ type: "xhs.createJob", payload });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["xhs.jobs"] })
  });

  const canSubmit =
    loggedIn &&
    !createJob.isPending &&
    ((type === "notes" && splitLines(notes).length > 0) ||
      (type === "user" && userUrl.trim()) ||
      (type === "search" && query.trim()));

  return (
    <section className="card">
      <div className="section-heading compact">
        <div>
          <p className="eyebrow">DOWNLOAD</p>
          <h2>下载 / 导出任务</h2>
        </div>
      </div>

      <label htmlFor="job-type">任务类型</label>
      <select id="job-type" value={type} onChange={(e) => setType(e.target.value as XhsJobType)}>
        {(Object.keys(XHS_JOB_TYPE_LABELS) as XhsJobType[]).map((value) => (
          <option key={value} value={value}>
            {XHS_JOB_TYPE_LABELS[value]}
          </option>
        ))}
      </select>

      {type === "notes" ? (
        <>
          <label htmlFor="job-notes">笔记链接（每行一个）</label>
          <textarea
            id="job-notes"
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="https://www.xiaohongshu.com/explore/..."
          />
        </>
      ) : null}
      {type === "user" ? (
        <>
          <label htmlFor="job-user">用户主页链接</label>
          <input
            id="job-user"
            value={userUrl}
            onChange={(e) => setUserUrl(e.target.value)}
            placeholder="https://www.xiaohongshu.com/user/profile/..."
          />
        </>
      ) : null}
      {type === "search" ? (
        <>
          <label htmlFor="job-query">关键词</label>
          <div className="inline-form">
            <input
              id="job-query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="如 榴莲"
            />
            <input
              className="num-input"
              type="number"
              min={1}
              max={200}
              value={requireNum}
              onChange={(e) => setRequireNum(Number(e.target.value) || 1)}
            />
          </div>
        </>
      ) : null}

      <label htmlFor="job-save">保存方式</label>
      <select
        id="job-save"
        value={saveChoice}
        onChange={(e) => setSaveChoice(e.target.value as XhsSaveChoice)}
      >
        {(Object.keys(XHS_SAVE_LABELS) as XhsSaveChoice[]).map((value) => (
          <option key={value} value={value}>
            {XHS_SAVE_LABELS[value]}
          </option>
        ))}
      </select>

      {saveChoice === "all" || saveChoice === "excel" ? (
        <>
          <label htmlFor="job-excel">Excel 文件名（可选）</label>
          <input
            id="job-excel"
            value={excelName}
            onChange={(e) => setExcelName(e.target.value)}
            placeholder="留空则用任务 ID"
          />
        </>
      ) : null}

      <button
        className="primary-button full-button"
        disabled={!canSubmit}
        onClick={() => createJob.mutate()}
      >
        {createJob.isPending ? "创建中…" : "创建任务"}
      </button>
      {!loggedIn ? <p className="hint-text">请先登录后再创建任务。</p> : null}
      {createJob.error ? <p className="error-text">{createJob.error.message}</p> : null}

      <div className="xhs-result-list">
        {(jobsQuery.data ?? []).slice(0, 10).map((job) => (
          <XhsJobRow key={job.id} job={job} />
        ))}
        {loggedIn && (jobsQuery.data?.length ?? 0) === 0 ? (
          <p className="empty-state">还没有下载任务。</p>
        ) : null}
      </div>
    </section>
  );
}

function XhsJobRow({ job }: { job: XhsJobRecord }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="xhs-job">
      <button className="xhs-job-head" onClick={() => setOpen((value) => !value)}>
        <div>
          <strong>
            {XHS_JOB_TYPE_LABELS[job.type]} · {job.note_count} 篇
          </strong>
          <span>{new Date(job.created_at).toLocaleString("zh-CN")}</span>
        </div>
        <span className={`status-chip status-${job.status}`}>
          {XHS_JOB_STATUS[job.status] ?? job.status}
        </span>
      </button>
      {job.error ? <p className="error-text">{job.error}</p> : null}
      {open && job.artifacts.length ? (
        <div className="xhs-artifacts">
          {job.artifacts.map((path) => (
            <a
              key={path}
              className="text-button"
              href={artifactUrl(job.id, path)}
              target="_blank"
              rel="noreferrer"
            >
              {path}
            </a>
          ))}
        </div>
      ) : null}
      {open && !job.artifacts.length ? <p className="hint-text">暂无产物文件。</p> : null}
    </div>
  );
}

function artifactUrl(jobId: string, path: string): string {
  const encoded = path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return `${XHS_API_BASE}/api/v1/xhs/jobs/${jobId}/artifacts/${encoded}`;
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

interface XhsNote {
  title: string;
  nickname: string;
  note_type: string;
  desc: string;
  liked_count: string | number;
  video_addr: string | null;
  image_list?: string[];
}

interface SearchItem {
  id: string;
  title: string;
  author: string;
  url: string;
}

function normalizeSearch(data: unknown): SearchItem[] {
  if (!Array.isArray(data)) return [];
  return data
    .filter((item) => item && typeof item === "object")
    .map((raw) => {
      const item = raw as Record<string, any>;
      const card = (item.note_card ?? {}) as Record<string, any>;
      const id = String(item.id ?? card.note_id ?? "");
      const token = item.xsec_token ? `?xsec_token=${item.xsec_token}` : "";
      return {
        id,
        title: String(card.display_title || card.title || "无标题"),
        author: String(card.user?.nickname ?? card.user?.nick_name ?? ""),
        url: id ? `https://www.xiaohongshu.com/explore/${id}${token}` : "#"
      };
    })
    .filter((item) => item.id);
}

function qrStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    waiting: "请使用小红书 App 扫码",
    scanned: "已扫码，请在手机确认",
    confirmed: "登录成功",
    expired: "二维码已过期，请重新生成",
    error: "登录失败，请重试"
  };
  return labels[status] ?? status;
}

function TaskPanel({
  task,
  result,
  retrying,
  onRetry
}: {
  task: TaskRecord;
  result: TaskResult | undefined;
  retrying: boolean;
  onRetry: () => void;
}) {
  const artifactDownload = useMutation({
    mutationFn: (name: string) =>
      sendExtensionMessage({
        type: "artifact.read",
        payload: { taskId: task.id, name }
      }),
    onSuccess: (artifact) => {
      const url = URL.createObjectURL(
        new Blob([artifact.content], { type: artifact.mediaType })
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = artifact.name;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
    }
  });

  async function copyText() {
    if (result) await navigator.clipboard.writeText(result.transcript.text);
  }

  return (
    <section className="card result-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">PROCESSING</p>
          <h2>{result?.source.title ?? STATUS_LABELS[task.status] ?? task.status}</h2>
        </div>
        <strong className="progress-value">{task.progress}%</strong>
      </div>
      <div className="progress-track">
        <span style={{ width: `${task.progress}%` }} />
      </div>
      <p className="task-message">{task.message}</p>
      {task.error ? <p className="error-text">{task.error}</p> : null}
      {task.status === "failed" ? (
        <button className="secondary-button retry-button" onClick={onRetry} disabled={retrying}>
          {retrying ? "正在重试…" : "重新执行"}
        </button>
      ) : null}
      {result ? (
        <>
          <div className="result-meta">
            <span>{result.source.author || "未知作者"}</span>
            <span>{result.transcript.engine}</span>
            <span>{result.transcript.segments.length} 个片段</span>
          </div>
          <article className="transcript">{result.transcript.text}</article>
          <button className="secondary-button" onClick={copyText}>
            复制全文
          </button>
          <div className="artifact-section">
            <p className="artifact-title">下载产物</p>
            <div className="artifact-actions">
              {result.artifacts.filter(isTextArtifact).map((artifact) => (
                <button
                  key={artifact.name}
                  className="artifact-button"
                  disabled={artifactDownload.isPending}
                  onClick={() => artifactDownload.mutate(artifact.name)}
                >
                  {artifactLabel(artifact.name)}
                  <span>{formatBytes(artifact.size)}</span>
                </button>
              ))}
            </div>
            {artifactDownload.error ? (
              <p className="error-text">{artifactDownload.error.message}</p>
            ) : null}
          </div>
        </>
      ) : null}
    </section>
  );
}

function SettingsPanel({
  initial,
  capabilities,
  onSaved
}: {
  initial: ExtensionSettings;
  capabilities: Capabilities | undefined;
  onSaved: () => void;
}) {
  const [settings, setSettings] = useState(initial);
  const save = useMutation({
    mutationFn: () =>
      sendExtensionMessage({ type: "settings.save", payload: settings }),
    onSuccess: onSaved
  });

  return (
    <section className="card settings-card">
      <h2>连接设置</h2>
      <label htmlFor="api-url">本地 API</label>
      <input
        id="api-url"
        value={settings.apiBaseUrl}
        onChange={(event) => setSettings({ ...settings, apiBaseUrl: event.target.value })}
      />
      <label htmlFor="token">配对 Token（后续启用）</label>
      <input
        id="token"
        type="password"
        value={settings.token}
        onChange={(event) => setSettings({ ...settings, token: event.target.value })}
      />
      <label htmlFor="engine">默认引擎</label>
      <select
        id="engine"
        value={settings.preferredEngine}
        onChange={(event) =>
          setSettings({
            ...settings,
            preferredEngine: event.target.value as ExtensionSettings["preferredEngine"]
          })
        }
      >
        {ENGINES.map((engine) => {
          const available = isEngineReady(engine, capabilities);
          return (
            <option key={engine} value={engine} disabled={!available}>
              {ENGINE_LABELS[engine]}
              {available ? "" : " · 未配置"}
            </option>
          );
        })}
      </select>
      <button className="primary-button" onClick={() => save.mutate()} disabled={save.isPending}>
        保存设置
      </button>
      {save.error ? <p className="error-text">{save.error.message}</p> : null}
    </section>
  );
}

function shortInput(value: string): string {
  return value.length > 42 ? `${value.slice(0, 42)}…` : value;
}

interface TaskGroup {
  key: string;
  task: TaskListItem;
  attempts: number;
  failures: number;
}

function groupTasks(tasks: TaskListItem[]): TaskGroup[] {
  const groups = new Map<string, TaskGroup>();
  for (const task of tasks) {
    const key = taskKey(task);
    const group = groups.get(key);
    if (group) {
      group.attempts += 1;
      if (task.status === "failed") group.failures += 1;
    } else {
      groups.set(key, {
        key,
        task,
        attempts: 1,
        failures: task.status === "failed" ? 1 : 0
      });
    }
  }
  return [...groups.values()];
}

function taskKey(task: TaskListItem): string {
  const source = task.source_url ?? task.input.match(/https?:\/\/[^\s]+/)?.[0];
  return source ? source.toLowerCase().replace(/[.,，。!！/]+$/, "") : task.id;
}

function isEngineReady(
  engine: TranscribeRequest["engine"],
  capabilities: Capabilities | undefined
): boolean {
  if (!capabilities) return false;
  if (engine === "auto") {
    return Object.entries(capabilities.engines).some(
      ([name, available]) => name !== "mock" && available
    );
  }
  return capabilities.engines[engine] === true;
}

function isTextArtifact(artifact: TaskResult["artifacts"][number]): boolean {
  return (
    artifact.media_type.startsWith("text/") ||
    artifact.media_type === "application/json" ||
    artifact.media_type === "application/x-subrip"
  );
}

function artifactLabel(name: string): string {
  const labels: Record<string, string> = {
    "source.json": "来源 JSON",
    "transcript.json": "转写 JSON",
    "transcript.srt": "SRT 字幕",
    "notes.md": "Markdown"
  };
  return labels[name] ?? name;
}

function formatBytes(size: number): string {
  return size < 1024 ? `${size} B` : `${(size / 1024).toFixed(1)} KB`;
}
