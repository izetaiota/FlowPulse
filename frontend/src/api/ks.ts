import client from "./client";

// ---- 快手账号（T5.1） ----

export interface KsAccountStatus {
  configured: boolean;
  logged_in_guess: boolean;
  engine: string;
  account_id: number | null;
}

export const ksAccountApi = {
  status: () => client.get("/v1/ks/account/status") as unknown as Promise<KsAccountStatus>,
  importCookie: (cookie: string) =>
    client.post("/v1/ks/account/cookie", { cookie }) as unknown as Promise<{
      account_id: number;
      configured: boolean;
    }>,
  clear: () => client.delete("/v1/ks/account") as unknown as Promise<{ deleted: boolean }>,
  qrStart: () =>
    client.post("/v1/ks/account/qr-login") as unknown as Promise<{
      session_id: string;
      state: string;
      message: string;
    }>,
  qrPoll: (sessionId: string) =>
    client.get(`/v1/ks/account/qr-login/${sessionId}`) as unknown as Promise<{
      state: string;
      message: string;
    }>,
  qrCancel: (sessionId: string) =>
    client.delete(`/v1/ks/account/qr-login/${sessionId}`) as unknown as Promise<{
      cancelled: boolean;
    }>,
};

// ---- 快手作品监控（结构同抖音监控） ----

export interface KsMonitor {
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

export const ksMonitorApi = {
  list: () =>
    client.get("/v1/ks/monitoring/monitors") as unknown as Promise<{ monitors: KsMonitor[] }>,
  create: (payload: {
    kind: "creator" | "keyword";
    target: string;
    name?: string;
    interval_minutes?: number;
    include_keywords?: string;
    exclude_keywords?: string;
    backfill_count?: number;
  }) => client.post("/v1/ks/monitoring/monitors", payload) as unknown as Promise<KsMonitor>,
  update: (
    id: number,
    payload: Partial<Pick<KsMonitor, "name" | "interval_minutes" | "include_keywords" | "exclude_keywords" | "status">>,
  ) => client.patch(`/v1/ks/monitoring/monitors/${id}`, payload) as unknown as Promise<KsMonitor>,
  remove: (id: number) =>
    client.delete(`/v1/ks/monitoring/monitors/${id}`) as unknown as Promise<{ deleted: boolean }>,
  scan: (id: number) =>
    client.post(`/v1/ks/monitoring/monitors/${id}/scan`) as unknown as Promise<{
      result: { ok: boolean; message: string; new_count: number; notified: boolean };
      monitor: KsMonitor;
    }>,
  contents: (params: { monitor_id?: number; page?: number; page_size?: number }) =>
    client.get("/v1/ks/monitoring/contents", { params }) as unknown as Promise<{
      contents: Array<Record<string, unknown>>;
      total: number;
    }>,
};
