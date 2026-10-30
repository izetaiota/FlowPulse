import client from "./client";

export interface NotifyChannel {
  id?: number;
  name: string;
  url: string;
  enabled: boolean;
  /** env = 环境变量渠道（只读），db = 页面管理 */
  source: "env" | "db";
}

export interface NotifyLog {
  channel: string;
  kind: string;
  title: string;
  ok: boolean;
  detail: string;
  created_at: string;
}

export const notifyApi = {
  listChannels: () =>
    client.get("/notify/channels") as unknown as Promise<{ channels: NotifyChannel[] }>,
  saveChannels: (channels: { name: string; url: string; enabled: boolean }[]) =>
    client.put("/notify/channels", { channels }) as unknown as Promise<{
      channels: NotifyChannel[];
    }>,
  sendTest: () =>
    client.post("/notify/test") as unknown as Promise<{ sent: boolean }>,
  listLogs: (limit = 30) =>
    client.get("/notify/logs", { params: { limit } }) as unknown as Promise<{
      logs: NotifyLog[];
    }>,
};
