import client from "./client";

export interface XhsLoginStatus {
  platform: string;
  logged_in: boolean;
  user_id: string | null;
  message: string;
}

export interface XhsQrcodeStart {
  session_id: string;
  platform: string;
  qr_url: string;
  qr_image_base64: string;
}

export interface XhsQrcodePoll {
  session_id: string;
  platform: string;
  status: "waiting" | "scanned" | "confirmed" | "expired" | "error";
  message: string;
  logged_in: boolean;
}

export interface XhsDataResponse<T = unknown> {
  success: boolean;
  message: string;
  data: T;
}

export interface XhsJob {
  id: string;
  type: string;
  status: "pending" | "running" | "completed" | "failed";
  message: string;
  error: string | null;
  note_count: number;
  artifacts: string[];
  created_at: string;
  updated_at: string;
}

const get = <T>(url: string, params?: Record<string, unknown>) =>
  client.get(url, { params }) as unknown as Promise<T>;
const post = <T>(url: string, body?: unknown) =>
  client.post(url, body) as unknown as Promise<T>;

export const xhsApi = {
  loginStatus: (platform = "pc") => get<XhsLoginStatus>("/v1/xhs/login/status", { platform }),
  qrcodeStart: (platform = "pc") => post<XhsQrcodeStart>("/v1/xhs/login/qrcode", { platform }),
  qrcodePoll: (sessionId: string) => get<XhsQrcodePoll>(`/v1/xhs/login/qrcode/${sessionId}`),
  phoneSend: (phone: string, zone = "86", platform = "pc") =>
    post<{ session_id: string; message: string }>("/v1/xhs/login/phone/code", { phone, zone, platform }),
  phoneVerify: (sessionId: string, code: string) =>
    post<XhsLoginStatus>("/v1/xhs/login/phone/verify", { session_id: sessionId, code }),
  loginCookie: (cookies: string, platform = "pc") =>
    post<XhsLoginStatus>("/v1/xhs/login/cookie", { cookies, platform }),

  search: (query: string, requireNum = 20) =>
    post<XhsDataResponse>("/v1/xhs/search", { query, require_num: requireNum }),
  noteDetail: (url: string) => post<XhsDataResponse>("/v1/xhs/notes/detail", { url }),
  noteComments: (url: string) => post<XhsDataResponse>("/v1/xhs/notes/comments", { url }),
  userNotes: (userUrl: string) => post<XhsDataResponse>("/v1/xhs/users/notes", { user_url: userUrl }),

  listJobs: () => get<XhsJob[]>("/v1/xhs/jobs"),
  createSearchJob: (query: string, requireNum = 20) =>
    post<XhsJob>("/v1/xhs/jobs", { type: "search", query, require_num: requireNum }),
  createUserJob: (userUrl: string) =>
    post<XhsJob>("/v1/xhs/jobs", { type: "user", user_url: userUrl }),
};
