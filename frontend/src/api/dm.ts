import client from "./client";

export interface DmConversation {
  conv_id: string;
  peer_uid: string;
  peer_nickname: string;
  peer_avatar: string;
  last_text: string;
  last_time: number;
  unread_count: number;
  group_chat: boolean;
}

export interface DmMessage {
  server_msg_id: string;
  sender_uid: string;
  direction: "in" | "out";
  text: string;
  msg_type: string;
  create_time: number;
}

export interface DmRule {
  id: number;
  name: string;
  keywords: string;
  reply_template: string;
  enabled: boolean;
}

export interface DmDraft {
  id: number;
  conv_id: string;
  peer_nickname: string;
  last_text: string;
  rule_name: string;
  suggested_reply: string;
  status: "pending" | "approved" | "rejected";
  created_at: string;
}

export const dmApi = {
  conversations: (pages = 1) =>
    client.get("/v1/xhs/dm/conversations", { params: { pages } }) as unknown as Promise<{
      ok: boolean;
      message: string;
      conversations: DmConversation[];
      drafts_created: number;
    }>,
  messages: (convId: string, peerUid: string) =>
    client.get(`/v1/xhs/dm/conversations/${convId}/messages`, {
      params: { peer_uid: peerUid },
    }) as unknown as Promise<{ ok: boolean; message: string; messages: DmMessage[] }>,
  listRules: () => client.get("/v1/xhs/dm/rules") as unknown as Promise<{ rules: DmRule[] }>,
  createRule: (payload: { name: string; keywords: string; reply_template: string }) =>
    client.post("/v1/xhs/dm/rules", payload) as unknown as Promise<DmRule>,
  updateRule: (id: number, payload: Partial<DmRule>) =>
    client.patch(`/v1/xhs/dm/rules/${id}`, payload) as unknown as Promise<DmRule>,
  removeRule: (id: number) =>
    client.delete(`/v1/xhs/dm/rules/${id}`) as unknown as Promise<{ deleted: boolean }>,
  listDrafts: (status?: string) =>
    client.get("/v1/xhs/dm/drafts", { params: status ? { status } : {} }) as unknown as Promise<{
      drafts: DmDraft[];
    }>,
  reviewDraft: (id: number, decision: "approved" | "rejected") =>
    client.post(`/v1/xhs/dm/drafts/${id}/review`, null, { params: { decision } }) as unknown as Promise<DmDraft>,
};
