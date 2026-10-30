import client from "./client";

export interface ChannelsStatus {
  configured: boolean;
  storage_state_available: boolean;
  nickname: string;
  works_count: number;
  engine: string;
}

export interface ChannelsProfile {
  nickname: string;
  username: string;
  avatar: string;
}

export interface ChannelsWork {
  object_id: string;
  title: string;
  create_time: number;
  cover: string;
  media_type: "video" | "images";
  liked_count: string;
  comment_count: number;
  forward_count: number;
  media_note: string;
}

export const channelsApi = {
  status: () => client.get("/v1/channels/status") as unknown as Promise<ChannelsStatus>,
  qrStart: () =>
    client.post("/v1/channels/qr-login") as unknown as Promise<{
      session_id: string;
      state: string;
      message: string;
    }>,
  qrPoll: (sessionId: string) =>
    client.get(`/v1/channels/qr-login/${sessionId}`) as unknown as Promise<{
      state: string;
      message: string;
    }>,
  qrCancel: (sessionId: string) =>
    client.delete(`/v1/channels/qr-login/${sessionId}`) as unknown as Promise<{
      cancelled: boolean;
    }>,
  clear: () =>
    client.delete("/v1/channels/account") as unknown as Promise<{ deleted: boolean }>,
  refresh: () =>
    client.post("/v1/channels/refresh") as unknown as Promise<{
      ok: boolean;
      nickname?: string;
      works_count?: number;
      error?: string;
    }>,
  profile: () =>
    client.get("/v1/channels/profile") as unknown as Promise<{ profile: ChannelsProfile | null }>,
  works: () =>
    client.get("/v1/channels/works") as unknown as Promise<{ works: ChannelsWork[] }>,
};
