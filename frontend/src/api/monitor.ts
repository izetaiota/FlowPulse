import client from "./client";

export interface XhsMonitor {
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

export interface XhsContent {
  id: number;
  monitor_id: number | null;
  monitor_name: string;
  note_id: string;
  title: string;
  author: string;
  author_id: string;
  url: string;
  cover: string;
  note_type: string;
  liked_count: string;
  notified: boolean;
  first_seen_at: string;
}

export interface MonitorScanResult {
  result: { ok: boolean; message: string; new_count: number; notified: boolean };
  monitor: XhsMonitor;
}

export const monitorApi = {
  list: () =>
    client.get("/v1/xhs/monitoring/monitors") as unknown as Promise<{ monitors: XhsMonitor[] }>,
  create: (payload: {
    kind: "creator" | "keyword";
    target: string;
    name?: string;
    interval_minutes?: number;
    include_keywords?: string;
    exclude_keywords?: string;
    backfill_count?: number;
  }) =>
    client.post("/v1/xhs/monitoring/monitors", payload) as unknown as Promise<XhsMonitor>,
  update: (id: number, payload: Partial<Pick<XhsMonitor, "name" | "interval_minutes" | "include_keywords" | "exclude_keywords" | "status">>) =>
    client.patch(`/v1/xhs/monitoring/monitors/${id}`, payload) as unknown as Promise<XhsMonitor>,
  remove: (id: number) =>
    client.delete(`/v1/xhs/monitoring/monitors/${id}`) as unknown as Promise<{ deleted: boolean }>,
  scan: (id: number) =>
    client.post(`/v1/xhs/monitoring/monitors/${id}/scan`) as unknown as Promise<MonitorScanResult>,
  contents: (params: { monitor_id?: number; page?: number; page_size?: number }) =>
    client.get("/v1/xhs/monitoring/contents", { params }) as unknown as Promise<{
      contents: XhsContent[];
      total: number;
      page: number;
      page_size: number;
    }>,
  status: () =>
    client.get("/v1/xhs/monitoring/status") as unknown as Promise<{
      enabled: boolean;
      task_alive: boolean;
      tick_seconds: number;
      monitors: number;
      active_monitors: number;
      due_now: number;
    }>,
};
