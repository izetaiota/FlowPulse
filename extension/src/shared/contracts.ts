export type TaskStatus =
  | "pending"
  | "resolving"
  | "downloading"
  | "extracting_audio"
  | "transcribing"
  | "rendering"
  | "completed"
  | "failed"
  | "cancelled";

export interface Artifact {
  name: string;
  media_type: string;
  size: number;
}

export interface TranscribeRequest {
  input: string;
  engine: "auto" | "mock" | "whisper" | "sensevoice" | "tingwu" | "openai";
  formats: Array<"json" | "srt" | "markdown">;
  keep_video: boolean;
  client_request_id?: string;
  context?: {
    client: "chrome-extension";
    client_version: string;
    page_url?: string;
    page_title?: string;
    captured_at: string;
  };
}

export interface TaskRecord {
  id: string;
  request: TranscribeRequest;
  status: TaskStatus;
  progress: number;
  message: string;
  error: string | null;
  artifacts: Artifact[];
  created_at: string;
  updated_at: string;
}

export interface TaskListItem {
  id: string;
  input: string;
  title: string;
  author: string | null;
  source_url: string | null;
  cover_url: string | null;
  status: TaskStatus;
  progress: number;
  message: string;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskPage {
  items: TaskListItem[];
  next_cursor: string | null;
}

export interface Capabilities {
  api_version: string;
  service_version: string;
  engines: Record<string, boolean>;
  formats: string[];
  exporters: string[];
  limits: Record<string, number>;
}

export interface TaskResult {
  schema_version: number;
  task_id: string;
  source: {
    aweme_id: string | null;
    source_url: string;
    resolved_url: string;
    media_url: string;
    title: string;
    author: string | null;
    cover_url: string | null;
    duration_ms: number | null;
  };
  transcript: {
    engine: string;
    language: string | null;
    text: string;
    segments: Array<{
      start_ms: number;
      end_ms: number;
      text: string;
    }>;
  };
  artifacts: Artifact[];
}

export interface ExtensionSettings {
  apiBaseUrl: string;
  token: string;
  preferredEngine: TranscribeRequest["engine"];
}

export interface ApiError {
  status: number;
  message: string;
}

export type XhsPlatform = "pc" | "creator";

export interface XhsLoginStatus {
  platform: XhsPlatform;
  logged_in: boolean;
  user_id: string | null;
  message: string;
}

export interface XhsDataResponse {
  success: boolean;
  message: string;
  data: unknown;
}

export interface XhsQrcodeStart {
  session_id: string;
  platform: XhsPlatform;
  qr_url: string;
  qr_image_base64: string;
}

export interface XhsQrcodePoll {
  session_id: string;
  platform: XhsPlatform;
  status: "waiting" | "scanned" | "confirmed" | "expired" | "error";
  message: string;
  logged_in: boolean;
}

/** The only API origin the extension is allowed to talk to (see manifest). */
export const XHS_API_BASE = "http://127.0.0.1:8000";

export type XhsJobType = "notes" | "user" | "search";
export type XhsSaveChoice = "all" | "media" | "media-image" | "media-video" | "excel";

export interface XhsCreateJobRequest {
  type: XhsJobType;
  save_choice: XhsSaveChoice;
  excel_name?: string;
  notes?: string[];
  user_url?: string;
  query?: string;
  require_num?: number;
}

export interface XhsJobRecord {
  id: string;
  type: XhsJobType;
  status: "pending" | "running" | "completed" | "failed";
  message: string;
  error: string | null;
  note_count: number;
  artifacts: string[];
  created_at: string;
  updated_at: string;
}

export interface ArtifactContent {
  name: string;
  mediaType: string;
  content: string;
}
