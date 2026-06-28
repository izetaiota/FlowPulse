import type {
  ArtifactContent,
  Capabilities,
  ExtensionSettings,
  TaskPage,
  TaskRecord,
  TaskResult,
  TranscribeRequest
} from "./contracts";

export type ExtensionRequest =
  | { type: "connection.check" }
  | { type: "settings.get" }
  | { type: "settings.save"; payload: ExtensionSettings }
  | { type: "tab.captureCurrent" }
  | { type: "task.create"; payload: TranscribeRequest }
  | { type: "task.get"; payload: { taskId: string } }
  | { type: "task.list"; payload?: { limit?: number; cursor?: string } }
  | { type: "task.result"; payload: { taskId: string } }
  | { type: "task.retry"; payload: { taskId: string } }
  | { type: "artifact.read"; payload: { taskId: string; name: string } };

export interface ResponseMap {
  "connection.check": Capabilities;
  "settings.get": ExtensionSettings;
  "settings.save": ExtensionSettings;
  "tab.captureCurrent": { url: string; title: string };
  "task.create": TaskRecord;
  "task.get": TaskRecord;
  "task.list": TaskPage;
  "task.result": TaskResult;
  "task.retry": TaskRecord;
  "artifact.read": ArtifactContent;
}

export type ExtensionResponse<T> =
  | { ok: true; data: T }
  | { ok: false; error: { status: number; message: string } };

export async function sendExtensionMessage<K extends keyof ResponseMap>(
  request: Extract<ExtensionRequest, { type: K }>
): Promise<ResponseMap[K]> {
  const response = (await chrome.runtime.sendMessage(request)) as ExtensionResponse<ResponseMap[K]>;
  if (!response.ok) {
    throw new Error(response.error.message);
  }
  return response.data;
}
