import client from "./client";

export interface TiktokAccountStatus {
  configured: boolean;
  logged_in_guess: boolean;
  note: string;
}

export interface TiktokMonitor {
  id: number;
  kind: "keyword";
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

export const tiktokApi = {
  accountStatus: () =>
    client.get("/v1/tiktok/account/status") as unknown as Promise<TiktokAccountStatus>,
  importCookie: (cookie: string) =>
    client.post("/v1/tiktok/account/cookie", { cookie }) as unknown as Promise<{
      account_id: number;
      configured: boolean;
    }>,
  clearAccount: () =>
    client.delete("/v1/tiktok/account") as unknown as Promise<{ deleted: boolean }>,
  list: () =>
    client.get("/v1/tiktok/monitoring/monitors") as unknown as Promise<{ monitors: TiktokMonitor[] }>,
  create: (payload: {
    kind: "keyword" | "creator";  // UI 对 TikTok 强制 keyword，后端 ^keyword$ 兜底
    target: string;
    name?: string;
    interval_minutes?: number;
    include_keywords?: string;
    exclude_keywords?: string;
    backfill_count?: number;
  }) =>
    client.post("/v1/tiktok/monitoring/monitors", payload) as unknown as Promise<TiktokMonitor>,
  update: (id: number, payload: Partial<Pick<TiktokMonitor, "name" | "interval_minutes" | "include_keywords" | "exclude_keywords" | "status">>) =>
    client.patch(`/v1/tiktok/monitoring/monitors/${id}`, payload) as unknown as Promise<TiktokMonitor>,
  remove: (id: number) =>
    client.delete(`/v1/tiktok/monitoring/monitors/${id}`) as unknown as Promise<{ deleted: boolean }>,
  scan: (id: number) =>
    client.post(`/v1/tiktok/monitoring/monitors/${id}/scan`) as unknown as Promise<{
      result: { ok: boolean; message: string; new_count: number; notified: boolean };
      monitor: TiktokMonitor;
    }>,
  contents: (params: { monitor_id?: number; page?: number; page_size?: number }) =>
    client.get("/v1/tiktok/monitoring/contents", { params }) as unknown as Promise<{
      contents: Array<Record<string, unknown>>;
      total: number;
    }>,
};
