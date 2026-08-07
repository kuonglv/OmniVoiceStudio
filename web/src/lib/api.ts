/**
 * Typed client for the OmniVoice Studio API.
 *
 * In production the UI is served by the same FastAPI process, so the base URL
 * is "" (same origin) and the app works at whatever hostname RunPod hands out.
 * During `pnpm dev` the UI is on :3000 and the API on :8000, hence the env var.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");

const TOKEN_KEY = "ovs_token";

export function getToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
  /** True when the token is missing or wrong, so callers can prompt for it. */
  get isAuth() {
    return this.status === 401;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // Let the browser set the multipart boundary itself.
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/**
 * URL for a media/download endpoint. `<audio src>` and `<a download>` cannot
 * send an Authorization header, so the token rides in the query string —
 * the backend accepts it there for exactly this reason.
 */
export function mediaUrl(path: string, params: Record<string, string> = {}): string {
  const token = getToken();
  const qs = new URLSearchParams(params);
  if (token) qs.set("token", token);
  const query = qs.toString();
  return `${API_BASE}${path}${query ? `?${query}` : ""}`;
}

export function wsUrl(path: string): string {
  const base = API_BASE || (typeof window !== "undefined" ? window.location.origin : "");
  const url = new URL(`${base}${path}`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const token = getToken();
  if (token) url.searchParams.set("token", token);
  return url.toString();
}

// -- types ------------------------------------------------------------------

export interface ReferenceVoice {
  id: string;
  label: string;
  description: string;
  ref_text: string;
  language: string;
  duration: number | null;
  origin: string;
  created_at: string;
  audio: string;
  used_by: number;
}

export interface VoiceMeta {
  library_root: string;
  audio_exts: string[];
  default_language: string;
  ideal_max_seconds: number;
}

export interface SynthesisParams {
  voice: string;
  ref_audio?: string | null;
  ref_text?: string | null;
  language?: string | null;
  speed: number;
  num_step: number;
  guidance_scale: number;
  audio_chunk_duration: number;
  audio_chunk_threshold: number;
  max_chars_per_chunk: number;
  model_id?: string | null;
  device?: string | null;
}

export interface AsrParams {
  model?: string | null;
  output_format: string;
  max_line_count: number;
  max_line_width: number;
  language?: string | null;
  initial_prompt?: string | null;
  word_timestamps: boolean;
}

export interface ScriptItem {
  name: string;
  text: string;
}

export interface GenerateAccepted {
  job_id: string;
  output_dir: string;
  items: number;
}

export type JobStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";

export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  progress: number;
  params: Record<string, unknown>;
  result: {
    output_dir?: string;
    ok?: number;
    failed?: number;
    items?: Array<Record<string, unknown>>;
  } | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface JobLog {
  id: number;
  ts: string;
  stream: string;
  line: string;
}

export interface OutputFile {
  name: string;
  size: number;
  kind: "audio" | "subtitle" | "text" | "other";
}

export interface OutputSet {
  job_id: string;
  created_at: string | null;
  status: string | null;
  files: OutputFile[];
  total_size: number;
}

export interface Health {
  ok: boolean;
  version: string;
  torch: string | null;
  cuda_available: boolean;
  gpu_name: string | null;
  vram_total_gb?: number | null;
  omnivoice_installed: boolean;
  model_loaded: boolean;
  auth_required: boolean;
}

export interface SystemInfo {
  data_dir: string;
  voices_dir: string;
  outputs_dir: string;
  db_path: string;
  disk: { total_gb?: number; free_gb?: number };
  voices: number;
  whisper_available: boolean;
  defaults: { model_id: string; device: string; whisper_model: string };
}

// -- calls ------------------------------------------------------------------

export const api = {
  health: () => request<Health>("/api/health"),
  system: () => request<SystemInfo>("/api/system"),
  unloadModel: () => request<{ released: number }>("/api/system/unload", { method: "POST" }),

  // voices
  listVoices: () => request<ReferenceVoice[]>("/api/voices"),
  voiceMeta: () => request<VoiceMeta>("/api/voices/meta"),
  createVoice: (form: FormData) =>
    request<ReferenceVoice>("/api/voices", { method: "POST", body: form }),
  replaceClip: (id: string, form: FormData) =>
    request<ReferenceVoice>(`/api/voices/${id}/clip`, { method: "POST", body: form }),
  updateVoice: (id: string, patch: Partial<Pick<ReferenceVoice, "label" | "description" | "ref_text" | "language">>) =>
    request<ReferenceVoice>(`/api/voices/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  renameVoice: (id: string, body: { new_id?: string; label?: string }) =>
    request<ReferenceVoice>(`/api/voices/${id}/rename`, { method: "POST", body: JSON.stringify(body) }),
  deleteVoice: (id: string) => request<void>(`/api/voices/${id}`, { method: "DELETE" }),
  exportSeed: () => request<{ exported: number }>("/api/voices/export-seed", { method: "POST" }),
  voiceAudioUrl: (id: string) => mediaUrl(`/api/voices/${id}/audio`),

  // generation
  generate: (body: {
    items: ScriptItem[];
    make_srt: boolean;
    synthesis: SynthesisParams;
    asr: AsrParams;
  }) => request<GenerateAccepted>("/api/generate", { method: "POST", body: JSON.stringify(body) }),
  generateUpload: (form: FormData) =>
    request<GenerateAccepted>("/api/generate/upload", { method: "POST", body: form }),

  // jobs
  listJobs: (limit = 50) => request<Job[]>(`/api/jobs?limit=${limit}`),
  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),
  getJobLogs: (id: string) => request<JobLog[]>(`/api/jobs/${id}/logs`),
  cancelJob: (id: string) => request<{ cancelled: boolean; note: string }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  deleteJob: (id: string, withOutput = false) =>
    request<void>(`/api/jobs/${id}?with_output=${withOutput}`, { method: "DELETE" }),

  // outputs
  listOutputs: () => request<OutputSet[]>("/api/outputs"),
  getOutput: (jobId: string) => request<OutputSet>(`/api/outputs/${jobId}`),
  deleteOutput: (jobId: string) => request<void>(`/api/outputs/${jobId}`, { method: "DELETE" }),
  fileUrl: (jobId: string, name: string, download = false) =>
    mediaUrl(`/api/outputs/${jobId}/file/${encodeURIComponent(name)}`, download ? { download: "true" } : {}),
  zipUrl: (jobId: string) => mediaUrl(`/api/outputs/${jobId}/zip`),
};
