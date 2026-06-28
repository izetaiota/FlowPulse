import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";

import type {
  Capabilities,
  ExtensionSettings,
  TaskListItem,
  TaskRecord,
  TaskResult,
  TranscribeRequest
} from "../shared/contracts";
import { sendExtensionMessage } from "../shared/messages";

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

export function App() {
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [pageTitle, setPageTitle] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
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
  const historyQuery = useQuery({
    queryKey: ["tasks"],
    queryFn: () => sendExtensionMessage({ type: "task.list", payload: { limit: 50 } })
  });
  const taskQuery = useQuery({
    queryKey: ["task", taskId],
    enabled: Boolean(taskId),
    queryFn: () =>
      sendExtensionMessage({ type: "task.get", payload: { taskId: taskId! } }),
    refetchInterval: (query) => {
      const task = query.state.data as TaskRecord | undefined;
      return task && TERMINAL.has(task.status) ? false : 2_000;
    }
  });
  const resultQuery = useQuery({
    queryKey: ["result", taskId],
    enabled: taskQuery.data?.status === "completed",
    queryFn: () =>
      sendExtensionMessage({ type: "task.result", payload: { taskId: taskId! } })
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
      engine: settingsQuery.data?.preferredEngine ?? "auto",
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

  const connected = connectionQuery.isSuccess;
  const selectedEngine = settingsQuery.data?.preferredEngine ?? "auto";
  const engineReady = isEngineReady(selectedEngine, connectionQuery.data);
  const taskGroups = useMemo(
    () => groupTasks(historyQuery.data?.items ?? []).slice(0, 8),
    [historyQuery.data?.items]
  );

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">DOUYIN TRANSCRIBE</p>
          <h1>内容整理台</h1>
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
            <span>{ENGINE_LABELS[selectedEngine]}</span>
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
    </main>
  );
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
