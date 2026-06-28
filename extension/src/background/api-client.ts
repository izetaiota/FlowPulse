import type {
  ArtifactContent,
  Capabilities,
  ExtensionSettings,
  TaskPage,
  TaskRecord,
  TaskResult,
  TranscribeRequest
} from "../shared/contracts";

export const DEFAULT_SETTINGS: ExtensionSettings = {
  apiBaseUrl: "http://127.0.0.1:8000",
  token: "",
  preferredEngine: "auto"
};

export async function loadSettings(): Promise<ExtensionSettings> {
  const stored = await chrome.storage.local.get("settings");
  return { ...DEFAULT_SETTINGS, ...(stored.settings ?? {}) };
}

export async function saveSettings(settings: ExtensionSettings): Promise<ExtensionSettings> {
  const normalized = {
    ...settings,
    apiBaseUrl: normalizeApiBaseUrl(settings.apiBaseUrl)
  };
  await chrome.storage.local.set({ settings: normalized });
  return normalized;
}

function normalizeApiBaseUrl(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || url.port !== "8000") {
    throw new Error("当前版本仅允许 http://127.0.0.1:8000");
  }
  return url.origin;
}

async function apiResponse(path: string, init?: RequestInit): Promise<Response> {
  const settings = await loadSettings();
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  headers.set("X-Client-Version", chrome.runtime.getManifest().version);
  if (init?.body) {
    headers.set("Content-Type", "application/json");
  }
  if (settings.token) {
    headers.set("Authorization", `Bearer ${settings.token}`);
  }

  const response = await fetch(`${normalizeApiBaseUrl(settings.apiBaseUrl)}${path}`, {
    ...init,
    headers
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw Object.assign(new Error(body?.detail ?? `请求失败 (${response.status})`), {
      status: response.status
    });
  }
  return response;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  return (await apiResponse(path, init)).json() as Promise<T>;
}

export const api = {
  capabilities: () => apiFetch<Capabilities>("/api/v1/capabilities"),
  createTask: (request: TranscribeRequest) =>
    apiFetch<TaskRecord>("/api/v1/tasks/transcribe", {
      method: "POST",
      body: JSON.stringify(request)
    }),
  getTask: (taskId: string) => apiFetch<TaskRecord>(`/api/v1/tasks/${taskId}`),
  retryTask: (taskId: string) =>
    apiFetch<TaskRecord>(`/api/v1/tasks/${taskId}/retry`, { method: "POST" }),
  listTasks: (limit = 20, cursor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set("cursor", cursor);
    return apiFetch<TaskPage>(`/api/v1/tasks?${params}`);
  },
  getResult: (taskId: string) => apiFetch<TaskResult>(`/api/v1/tasks/${taskId}/result`),
  readArtifact: async (taskId: string, name: string): Promise<ArtifactContent> => {
    const response = await apiResponse(
      `/api/v1/tasks/${taskId}/artifacts/${encodeURIComponent(name)}`
    );
    return {
      name,
      mediaType: response.headers.get("content-type")?.split(";")[0] ?? "text/plain",
      content: await response.text()
    };
  }
};
