import client from "./client";

export interface ReportKind {
  kind: string;
  label: string;
  desc: string;
}

export const reportApi = {
  list: () => client.get("/v1/reports") as unknown as Promise<{ reports: ReportKind[] }>,
  /** 直接下载需带鉴权：window.open 无法加 Header，用 query token（后端已支持） */
  downloadUrl: (kind: string): string => {
    const token = localStorage.getItem("flowpulse_token") || "";
    const suffix = token ? `?token=${encodeURIComponent(token)}` : "";
    return `/api/v1/reports/${kind}.xlsx${suffix}`;
  },
};
