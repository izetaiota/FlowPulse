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
  }
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
