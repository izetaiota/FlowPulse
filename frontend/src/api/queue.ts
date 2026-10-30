import client from "./client";

export interface QueueItem {
  source: "douyin" | "xhs";
  kind: string;
  id: string;
  title: string;
  status: string;
  message: string;
  created_at: string;
  updated_at: string;
  retryable: boolean;
}

export const queueApi = {
  list: (source?: string) =>
    client.get("/v1/queue", { params: source ? { source } : {} }) as unknown as Promise<{
      items: QueueItem[];
    }>,
  retry: (source: string, id: string) =>
    client.post(`/v1/queue/${source}/${id}/retry`) as unknown as Promise<{
      source: string;
      id: string;
      status: string;
      message: string;
    }>,
};
