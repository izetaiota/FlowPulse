import client from "./client";

export interface DownloadTask {
  id: string;
  url: string;
  source: "douyin" | "bilibili" | "xhs" | "other";
  title: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  message: string;
  error: string | null;
  filename: string;
  file_size: number;
  created_at: string;
  updated_at: string;
}

export interface MediaEntry {
  name: string;
  is_dir: boolean;
  size: number;
  mtime: number;
  previewable: boolean;
  path: string;
}

export const downloadApi = {
  submit: (text: string) =>
    client.post("/v1/downloads", { text }) as unknown as Promise<{ tasks: DownloadTask[] }>,
  list: () =>
    client.get("/v1/downloads") as unknown as Promise<{ tasks: DownloadTask[] }>,
  retry: (id: string) =>
    client.post(`/v1/downloads/${id}/retry`) as unknown as Promise<DownloadTask>,
  remove: (id: string) =>
    client.delete(`/v1/downloads/${id}`) as unknown as Promise<{ deleted: boolean }>,
  listFiles: (root: string, path: string = "") =>
    client.get("/v1/downloads/files/list", { params: { root, path } }) as unknown as Promise<{
      root: string;
      path: string;
      entries: MediaEntry[];
    }>,
  fileUrl: (root: string, path: string) =>
    `/api/v1/downloads/files/content?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`,
  removeFile: (root: string, path: string) =>
    client.delete("/v1/downloads/files/content", { params: { root, path } }) as unknown as Promise<{
      deleted: boolean;
    }>,
};
