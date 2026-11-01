import client from "./client";

// ---- 抖音账号（T3.1） ----

export interface DouyinAccountStatus {
  configured: boolean;
  logged_in_guess: boolean;
  storage_state_available: boolean;
  engine: string;
  account_id: number | null;
}

export interface QrLoginState {
  session_id: string;
  state: string; // waiting | logged_in | expired | failed | cancelled | unknown
  message: string;
}

export const douyinAccountApi = {
  status: () =>
    client.get("/v1/douyin/account/status") as unknown as Promise<DouyinAccountStatus>,
  importCookie: (cookie: string) =>
    client.post("/v1/douyin/account/cookie", { cookie }) as unknown as Promise<{
      account_id: number;
      configured: boolean;
    }>,
  clear: () => client.delete("/v1/douyin/account") as unknown as Promise<{ deleted: boolean }>,
  qrStart: () => client.post("/v1/douyin/account/qr-login") as unknown as Promise<QrLoginState>,
  qrPoll: (sessionId: string) =>
    client.get(`/v1/douyin/account/qr-login/${sessionId}`) as unknown as Promise<QrLoginState>,
  qrCancel: (sessionId: string) =>
    client.delete(`/v1/douyin/account/qr-login/${sessionId}`) as unknown as Promise<{
      cancelled: boolean;
    }>,
};

// ---- 抖音作品监控（T3.3，结构同小红书监控） ----

export interface DouyinMonitor {
  id: number;
  kind: "creator" | "keyword";
  target: string;
  name: string;
  interval_minutes: number;
  include_keywords: string;
  exclude_keywords: string;
  backfill_count: number;
  status: "active" | "paused";
  last_scan_at: string | null;
  last_scan_status: "never" | "ok" | "error";
  last_error: string;
  content_count: number;
}

export interface DouyinContent {
  id: number;
  monitor_id: number | null;
  monitor_name: string;
  aweme_id: string;
  title: string;
  author: string;
  author_id: string;
  url: string;
  cover: string;
  media_type: string;
  liked_count: string;
  create_time: number;
  notified: boolean;
  first_seen_at: string;
}

export const douyinMonitorApi = {
  list: () =>
    client.get("/v1/douyin/monitoring/monitors") as unknown as Promise<{
      monitors: DouyinMonitor[];
    }>,
  create: (payload: {
    kind: "creator" | "keyword";
    target: string;
    name?: string;
    interval_minutes?: number;
    include_keywords?: string;
    exclude_keywords?: string;
    backfill_count?: number;
  }) =>
    client.post("/v1/douyin/monitoring/monitors", payload) as unknown as Promise<DouyinMonitor>,
  update: (
    id: number,
    payload: Partial<
      Pick<DouyinMonitor, "name" | "interval_minutes" | "include_keywords" | "exclude_keywords" | "status">
    >,
  ) =>
    client.patch(`/v1/douyin/monitoring/monitors/${id}`, payload) as unknown as Promise<DouyinMonitor>,
  remove: (id: number) =>
    client.delete(`/v1/douyin/monitoring/monitors/${id}`) as unknown as Promise<{ deleted: boolean }>,
  scan: (id: number) =>
    client.post(`/v1/douyin/monitoring/monitors/${id}/scan`) as unknown as Promise<{
      result: { ok: boolean; message: string; new_count: number; notified: boolean };
      monitor: DouyinMonitor;
    }>,
  contents: (params: { monitor_id?: number; page?: number; page_size?: number }) =>
    client.get("/v1/douyin/monitoring/contents", { params }) as unknown as Promise<{
      contents: DouyinContent[];
      total: number;
    }>,
  status: () => client.get("/v1/douyin/monitoring/status") as unknown as Promise<Record<string, unknown>>,
};

// ---- 抖音私信（T4.4 前端接入） ----

export interface DouyinDmConversation {
  conv_id: string;
  peer_uid: string;
  peer_sec_uid: string;
  last_text: string;
  last_time: number;
  conv_short_id: string;
  ticket: string;
}

export interface DouyinDmMessage {
  conv_id: string;
  server_msg_id: string;
  msg_type: number;
  sender_uid: string;
  text: string;
  create_time: number;
}

export const douyinDmApi = {
  conversations: () =>
    client.get("/v1/douyin/dm/conversations") as unknown as Promise<{
      ok: boolean;
      conversations: DouyinDmConversation[];
      message: string;
    }>,
  messages: (convId: string, convShortId: string) =>
    client.get(`/v1/douyin/dm/conversations/${convId}/messages`, {
      params: { conv_short_id: convShortId },
    }) as unknown as Promise<{
      ok: boolean;
      messages: DouyinDmMessage[];
      self_uid: string;
    }>,
};
