import client from "./client";

export interface PublishTask {
  id: number;
  title: string;
  desc: string;
  topics: string;
  media_paths: string[];
  media_type: "video" | "images";
  visibility: "public" | "friends" | "private";
  allow_save: boolean;
  status: "draft" | "pending" | "publishing" | "done" | "failed" | "canceled";
  scheduled_at: string | null;
  result_url: string;
  error: string;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PublishMediaFile {
  path: string;
  name: string;
  size: number;
}

export const publishApi = {
  list: () => client.get("/v1/douyin/publish") as unknown as Promise<{ tasks: PublishTask[] }>,
  mediaFiles: () =>
    client.get("/v1/douyin/publish/media-files") as unknown as Promise<{
      files: PublishMediaFile[];
    }>,
  create: (payload: {
    title: string;
    desc: string;
    topics: string;
    media_paths: string[];
    visibility: string;
    allow_save: boolean;
  }) => client.post("/v1/douyin/publish", payload) as unknown as Promise<PublishTask>,
  submit: (id: number) =>
    client.post(`/v1/douyin/publish/${id}/submit`) as unknown as Promise<PublishTask>,
  cancel: (id: number) =>
    client.post(`/v1/douyin/publish/${id}/cancel`) as unknown as Promise<PublishTask>,
  remove: (id: number) =>
    client.delete(`/v1/douyin/publish/${id}`) as unknown as Promise<{ deleted: boolean }>,
};
