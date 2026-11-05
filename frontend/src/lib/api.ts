export type VoiceSpec = { provider: string; voice: string; rate: string; pitch: string };

export type Shot = {
  n: number;
  text: string;
  who: string;
  camera: string;
  highlight: string[];
  scene: string;
  chars: string[];
  min_dur?: number | null;
  sfx?: string | null;
  has_image: boolean;
  image_version: number | null;
  phrases: string[];
};

export type Issue = { level: "error" | "warn"; shot: number | null; message: string };

export type Project = {
  id: string;
  title: string;
  logline: string;
  voices: Record<string, VoiceSpec>;
  characters: Record<string, string>;
  cameras: string[];
  shots: Shot[];
  issues: Issue[];
  settings: { model: string; char_refs: Record<string, string>; shot_refs: Record<string, string[]> };
};

export type ProjectSummary = { id: string; title: string; logline: string; shots: number; images: number };

export type Settings = {
  image_price_usd: number;
  daily_cap_usd: number;
  spent_today_usd: number;
  keys: { azure: boolean; gemini: boolean };
};

export type Job = {
  id: string;
  kind: string;
  project: string;
  state: "queued" | "running" | "done" | "failed";
  progress: number;
  log: string[];
  result: string | null;
  error: string | null;
};

export type FaceStatus = "ok" | "drift?" | "small" | "no face";
export type FaceCheck = {
  shot: number;
  status: FaceStatus;
  expected: string[];
  faces: { character: string | null; closest: string; similarity: number; small: boolean }[];
};
export type FaceCheckResult = { threshold: number; checks: FaceCheck[] };

export type RenderFile = { name: string; bytes: number; created: number };
export type BgmStyle = { name: string; label: string };
export type VoiceChoice = { name: string; gender: string; note: string };

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(describe(detail) || `HTTP ${status}`);
  }
}

export function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const d = detail as { message?: string; msg?: string; estimated_usd?: number };
    if (Array.isArray(detail)) return detail.map((x) => describe(x)).join("; ");
    return d.message ?? d.msg ?? JSON.stringify(detail);
  }
  return "";
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, {
    cache: "no-store",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) {
    let detail: unknown = null;
    try {
      detail = (await r.json()).detail;
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(r.status, detail);
  }
  return (await r.json()) as T;
}

const body = (data: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(data) });

export const api = {
  health: () => req<{ ok: boolean }>("/api/health"),
  settings: () => req<Settings>("/api/settings"),
  projects: () => req<ProjectSummary[]>("/api/projects"),
  project: (id: string) => req<Project>(`/api/projects/${id}`),
  patchShot: (id: string, n: number, patch: Partial<Pick<Shot, "text" | "who" | "camera" | "highlight" | "scene">>) =>
    req<Shot>(`/api/projects/${id}/shots/${n}`, { method: "PATCH", body: JSON.stringify(patch) }),
  setVoice: (id: string, who: string, v: { voice: string; rate: string; pitch: string }) =>
    req<VoiceSpec>(`/api/projects/${id}/voices/${who}`, { method: "PUT", body: JSON.stringify(v) }),
  preview: (text: string) => req<{ phrases: string[] }>("/api/subtitles/preview", body({ text })),
  voices: () => req<VoiceChoice[]>("/api/voices"),
  regenerate: (id: string, n: number) =>
    req<Job & { estimated_usd: number }>(`/api/projects/${id}/shots/${n}/regenerate`, body({ confirm: true })),
  bgmStyles: () => req<BgmStyle[]>("/api/bgm-styles"),
  render: (id: string, only?: number[], bgmStyle?: string) =>
    req<Job>(`/api/projects/${id}/render`, body({ only: only ?? null, ...(bgmStyle ? { bgm_style: bgmStyle } : {}) })),
  faceCheck: (id: string) => req<FaceCheckResult>(`/api/projects/${id}/face-check`, { method: "POST", body: "{}" }),
  job: (jobId: string) => req<Job>(`/api/jobs/${jobId}`),
  renders: (id: string) => req<RenderFile[]>(`/api/projects/${id}/renders`),
};

export const imageUrl = (id: string, n: number, version: number | null, w?: number) =>
  `/api/projects/${id}/images/${n}?${w ? `w=${w}&` : ""}v=${version ?? 0}`;

export async function fetchVoiceSample(voice: string, rate: string): Promise<string> {
  const r = await fetch(`/api/voices/sample?voice=${encodeURIComponent(voice)}&rate=${encodeURIComponent(rate)}`);
  if (!r.ok) {
    let detail: unknown = null;
    try {
      detail = (await r.json()).detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, detail);
  }
  return URL.createObjectURL(await r.blob());
}

export const CAMERA_LABELS: Record<string, string> = {
  push_in: "천천히 다가감",
  pull_out: "천천히 멀어짐",
  pan_right: "오른쪽으로 이동",
  handheld: "느린 흔들림",
  static: "거의 고정",
};
