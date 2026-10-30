import client from "./client";

export interface WereadCredential {
  configured: boolean;
  masked_cookie?: string;
  saved_at?: string;
  last_validated_at?: string | null;
  valid?: boolean | null;
  last_error?: string;
}

export interface WereadSubscription {
  book_id: string;
  name: string;
  avatar: string;
  added_at: string;
  last_sync_at: string | null;
  last_sync_status: string;
  last_error: string;
  article_count: number;
  rss_title: string;
  rss_description: string;
  rss_full_text: boolean | null;
  rss_max_items: number;
  strip_keywords: string;
  notify_new: boolean;
  sync_interval_minutes: number;
}

export interface WereadArticle {
  review_id: string;
  book_id: string;
  title: string;
  link: string;
  cover: string;
  digest: string;
  publish_time: number;
  created_at: string;
}

export interface CredentialValidateResult {
  valid: boolean;
  message: string;
  book_count: number;
}

export interface SyncSummary {
  started_at: string;
  finished_at: string;
  subscriptions: number;
  ok_count: number;
  error_count: number;
  new_articles: number;
}

export interface SchedulerStatus {
  enabled: boolean;
  interval_minutes: number;
  running: boolean;
  last_run_at: string | null;
  last_result: { ok_count?: number; error_count?: number; new_articles?: number; error?: string } | null;
  task_alive: boolean;
}

export interface WereadArticleContent {
  review_id: string;
  book_id: string;
  title: string;
  content_html: string;
  publish_time: number;
  fetched_at: string;
}

export interface QrLoginStatus {
  state: "idle" | "pending" | "validating" | "success" | "failed" | "cancelled";
  message: string;
  page_url: string;
  started_at: string | null;
}

export interface CookieRefreshStatus {
  enabled: boolean;
  interval_hours: number;
  running: boolean;
  last_run_at: string | null;
  last_result: {
    ok?: boolean;
    reason?: string;
    message?: string;
    changed?: boolean;
    valid?: boolean;
  } | null;
  task_alive: boolean;
}

export interface CookieRefreshResult {
  ok: boolean;
  reason: string;
  message: string;
  changed?: boolean;
  valid?: boolean;
}

const get = <T>(url: string, params?: Record<string, unknown>) =>
  client.get(url, { params }) as unknown as Promise<T>;
const post = <T>(url: string, body?: unknown) =>
  client.post(url, body) as unknown as Promise<T>;
const del = <T>(url: string) => client.delete(url) as unknown as Promise<T>;
const put = <T>(url: string, body?: unknown) =>
  client.put(url, body) as unknown as Promise<T>;

export interface SubscriptionUpdatePayload {
  name: string;
  rss_title: string;
  rss_description: string;
  rss_full_text: boolean | null;
  rss_max_items: number;
  strip_keywords: string;
  notify_new: boolean;
  sync_interval_minutes: number;
}

export const wereadApi = {
  getCredential: () => get<WereadCredential>("/weread/credential"),
  saveCredential: (cookie: string) =>
    post<CredentialValidateResult>("/weread/credential", { cookie }),
  validateCredential: () => post<CredentialValidateResult>("/weread/credential/validate"),
  deleteCredential: () => del<{ deleted: boolean }>("/weread/credential"),
  startQrLogin: () => post<QrLoginStatus>("/weread/credential/qr-login"),
  getQrLoginStatus: () => get<QrLoginStatus>("/weread/credential/qr-login"),
  cancelQrLogin: () => del<QrLoginStatus>("/weread/credential/qr-login"),
  refreshCookie: () => post<CookieRefreshResult>("/weread/credential/refresh"),
  getCookieRefreshStatus: () => get<CookieRefreshStatus>("/weread/credential/refresh"),

  listSubscriptions: () => get<WereadSubscription[]>("/weread/subscriptions"),
  addSubscription: (input: string) =>
    post<WereadSubscription>("/weread/subscriptions", { input }),
  deleteSubscription: (bookId: string) =>
    del<{ deleted: boolean }>(`/weread/subscriptions/${bookId}`),
  updateSubscription: (bookId: string, payload: SubscriptionUpdatePayload) =>
    put<WereadSubscription>(`/weread/subscriptions/${bookId}`, payload),
  listArticles: (bookId: string, limit = 20, cursor?: string) =>
    get<{ book_id: string; count: number; next_cursor: string | null; items: WereadArticle[] }>(
      `/weread/subscriptions/${bookId}/articles`,
      { limit, ...(cursor ? { cursor } : {}) },
    ),
  getArticleContent: (bookId: string, reviewId: string) =>
    get<WereadArticleContent>(`/weread/articles/${bookId}/${reviewId}/content`),
  syncAll: () => post<SyncSummary>("/weread/sync"),
  syncOne: (bookId: string) =>
    post<{ status: string; new_articles: number; total_articles: number; message: string }>(
      `/weread/subscriptions/${bookId}/sync`,
    ),

  getSchedulerStatus: () => get<SchedulerStatus>("/weread/scheduler"),
};
