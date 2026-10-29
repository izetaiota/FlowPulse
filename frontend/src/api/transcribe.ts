import client from "./client";

export interface TranscribeTask {
  id: string;
  input: string;
  title: string;
  author: string | null;
  source_url: string | null;
  cover_url: string | null;
  status: string;
  progress: number;
  message: string;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskPage {
  items: TranscribeTask[];
  next_cursor: string | null;
}

export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

export interface TaskResult {
  task_id: string;
  source: { title?: string; author?: string; source_url?: string };
  transcript: { language?: string; duration?: number; segments: TranscriptSegment[] };
  artifacts: { name: string; media_type: string; size: number }[];
}

const get = <T>(url: string, params?: Record<string, unknown>) =>
  client.get(url, { params }) as unknown as Promise<T>;
const post = <T>(url: string, body?: unknown) =>
  client.post(url, body) as unknown as Promise<T>;

export const transcribeApi = {
  create: (input: string) => post<TranscribeTask>("/v1/tasks/transcribe", { input }),
  list: (limit = 20, cursor?: string) =>
    get<TaskPage>("/v1/tasks", { limit, ...(cursor ? { cursor } : {}) }),
  get: (id: string) => get<TranscribeTask>(`/v1/tasks/${id}`),
  retry: (id: string) => post<TranscribeTask>(`/v1/tasks/${id}/retry`),
  result: (id: string) => get<TaskResult>(`/v1/tasks/${id}/result`),
};

/** 产物下载链接（带 token 查询参数，鉴权模式下可直接下载） */
export function artifactUrl(taskId: string, name: string): string {
  const token = localStorage.getItem("flowpulse_token") || "";
  const base = import.meta.env.VITE_API_BASE_URL || "/api";
  return `${base}/v1/tasks/${taskId}/artifacts/${encodeURIComponent(name)}?token=${encodeURIComponent(token)}`;
}
