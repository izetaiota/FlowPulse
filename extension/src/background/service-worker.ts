import { api, loadSettings, saveSettings } from "./api-client";
import type { ExtensionRequest, ExtensionResponse } from "../shared/messages";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
const ACTIVE_TASKS_KEY = "activeTaskIds";
const SYNC_ALARM = "sync-active-tasks";

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  await chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
  await ensureSyncAlarm();
});

chrome.runtime.onStartup.addListener(ensureSyncAlarm);

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== SYNC_ALARM) return;
  await syncActiveTasks();
});

chrome.runtime.onMessage.addListener(
  (request: ExtensionRequest, sender, sendResponse: (response: ExtensionResponse<unknown>) => void) => {
    if (sender.id !== chrome.runtime.id) {
      sendResponse({ ok: false, error: { status: 403, message: "拒绝外部消息" } });
      return false;
    }

    handleRequest(request)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((error: unknown) => {
        const status =
          typeof error === "object" && error !== null && "status" in error
            ? Number(error.status)
            : 0;
        const message = error instanceof Error ? error.message : "未知错误";
        sendResponse({ ok: false, error: { status, message } });
      });
    return true;
  }
);

async function handleRequest(request: ExtensionRequest): Promise<unknown> {
  switch (request.type) {
    case "connection.check":
      return api.capabilities();
    case "settings.get":
      return loadSettings();
    case "settings.save":
      return saveSettings(request.payload);
    case "tab.captureCurrent": {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      return { url: tab?.url ?? "", title: tab?.title ?? "" };
    }
    case "task.create": {
      const task = await api.createTask(request.payload);
      if (!TERMINAL_STATUSES.has(task.status)) {
        await rememberActiveTask(task.id);
      }
      return task;
    }
    case "task.get": {
      const task = await api.getTask(request.payload.taskId);
      if (TERMINAL_STATUSES.has(task.status)) {
        await forgetActiveTask(task.id);
      }
      return task;
    }
    case "task.list":
      return api.listTasks(request.payload?.limit, request.payload?.cursor);
    case "task.result":
      return api.getResult(request.payload.taskId);
    case "task.retry": {
      const task = await api.retryTask(request.payload.taskId);
      await rememberActiveTask(task.id);
      return task;
    }
    case "artifact.read":
      return api.readArtifact(request.payload.taskId, request.payload.name);
    case "xhs.grabCookie": {
      const jar = await grabXhsCookie(request.payload.platform);
      const names = [...jar.keys()];
      const missing = ["a1", "web_session"].filter((name) => !jar.get(name));
      if (missing.length) {
        const detail = names.length
          ? `缺少必要 Cookie：${missing.join("、")}。已读取到 ${names.length} 个：${names.slice(0, 20).join(", ")}。请打开并停留在一个已登录的小红书网页标签（如 www.xiaohongshu.com）后重试。`
          : "未读取到任何 Cookie。请先打开并登录 www.xiaohongshu.com，再在 chrome://extensions 重新加载本扩展以授予权限。";
        throw Object.assign(new Error(detail), { status: 400 });
      }
      const cookieString = [...jar].map(([name, value]) => `${name}=${value}`).join("; ");
      return api.xhsLoginCookie(cookieString, request.payload.platform);
    }
    case "xhs.loginStatus":
      return api.xhsLoginStatus(request.payload.platform);
    case "xhs.qrcodeStart":
      return api.xhsQrcodeStart(request.payload.platform);
    case "xhs.qrcodePoll":
      return api.xhsQrcodePoll(request.payload.sessionId);
    case "xhs.search":
      return api.xhsSearch(request.payload.query, request.payload.requireNum);
    case "xhs.noteDetail":
      return api.xhsNoteDetail(request.payload.url);
    case "xhs.userNotes":
      return api.xhsUserNotes(request.payload.userUrl);
    case "xhs.createJob":
      return api.xhsCreateJob(request.payload);
    case "xhs.listJobs":
      return api.xhsListJobs();
    case "xhs.getJob":
      return api.xhsGetJob(request.payload.jobId);
  }
}

const XHS_COOKIE_URL: Record<string, string> = {
  pc: "https://www.xiaohongshu.com/",
  creator: "https://creator.xiaohongshu.com/"
};

// Building a complete XHS cookie jar needs two complementary sources:
//   1. chrome.cookies.getAll — returns HttpOnly cookies (e.g. web_session)
//      that page JavaScript can never see.
//   2. document.cookie from a live xiaohongshu tab — returns the JS-set,
//      non-HttpOnly cookies (a1, webId, gid, ...) which, in practice, the
//      cookie store query may omit here.
// Merging both yields the full jar the site actually uses.
async function grabXhsCookie(platform: string): Promise<Map<string, string>> {
  const url = XHS_COOKIE_URL[platform] ?? XHS_COOKIE_URL.pc;
  const [byDomain, byUrl, fromTab] = await Promise.all([
    chrome.cookies.getAll({ domain: "xiaohongshu.com" }),
    chrome.cookies.getAll({ url }),
    readTabDocumentCookie()
  ]);
  const jar = new Map<string, string>();
  // JS cookies first, then let the authoritative cookie store override.
  for (const [name, value] of fromTab) jar.set(name, value);
  for (const cookie of byDomain) jar.set(cookie.name, cookie.value);
  for (const cookie of byUrl) jar.set(cookie.name, cookie.value);
  return jar;
}

async function readTabDocumentCookie(): Promise<Map<string, string>> {
  const jar = new Map<string, string>();
  const tabs = await chrome.tabs.query({ url: ["*://*.xiaohongshu.com/*"] });
  const tab = tabs.find((item) => item.id != null);
  if (!tab?.id) return jar;
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => document.cookie
    });
    const raw = typeof result?.result === "string" ? result.result : "";
    for (const part of raw.split("; ")) {
      const index = part.indexOf("=");
      if (index > 0) jar.set(part.slice(0, index), part.slice(index + 1));
    }
  } catch {
    // Tab may be discarded or not scriptable; fall back to chrome.cookies only.
  }
  return jar;
}

async function ensureSyncAlarm(): Promise<void> {
  const alarm = await chrome.alarms.get(SYNC_ALARM);
  if (!alarm) {
    await chrome.alarms.create(SYNC_ALARM, { periodInMinutes: 0.5 });
  }
}

async function activeTaskIds(): Promise<string[]> {
  const stored = await chrome.storage.local.get(ACTIVE_TASKS_KEY);
  return Array.isArray(stored[ACTIVE_TASKS_KEY]) ? stored[ACTIVE_TASKS_KEY] : [];
}

async function rememberActiveTask(taskId: string): Promise<void> {
  const ids = new Set(await activeTaskIds());
  ids.add(taskId);
  await chrome.storage.local.set({ [ACTIVE_TASKS_KEY]: [...ids] });
}

async function forgetActiveTask(taskId: string): Promise<void> {
  const ids = (await activeTaskIds()).filter((id) => id !== taskId);
  await chrome.storage.local.set({ [ACTIVE_TASKS_KEY]: ids });
}

async function syncActiveTasks(): Promise<void> {
  const ids = await activeTaskIds();
  const tasks = await Promise.allSettled(ids.map((id) => api.getTask(id)));
  const active = tasks.flatMap((item, index) => {
    if (item.status === "rejected") {
      return [ids[index]];
    }
    return TERMINAL_STATUSES.has(item.value.status) ? [] : [item.value.id];
  });
  await chrome.storage.local.set({ [ACTIVE_TASKS_KEY]: active });
}
