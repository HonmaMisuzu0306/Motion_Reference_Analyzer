import { fetch } from "@tauri-apps/plugin-http";

const API_BASE = "http://127.0.0.1:8000/api/v1";

export interface VideoInfo {
  filename: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  codec: string;
  bitrate: number;
  has_audio: boolean;
}

export interface TimeRange {
  start: number;
  end: number;
  duration: number;
}

export interface Shot {
  shot_id: string;
  time: TimeRange;
  frames: string[];
  observations: Record<string, unknown>;
  motion: Record<string, unknown>;
  typography: Record<string, unknown>;
  visual_effects: unknown[];
  ae_hypothesis: Record<string, unknown>;
  ae_recipe: Record<string, unknown>;
}

export interface ProjectStatus {
  status: string;
  message: string;
  video: VideoInfo | null;
  video_path: string | null;
  shot_count: number;
}

async function post(path: string, body?: unknown) {
  const options: RequestInit = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  };
  if (body !== undefined) {
    options.body = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

async function get(path: string) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export function getFrameUrl(shotId: string, frameName: string): string {
  return `${API_BASE}/shots/${encodeURIComponent(shotId)}/frame/${encodeURIComponent(frameName)}`;
}

export const api = {
  importVideo: (path: string) => post("/video/import", { path }),
  analyzeVideo: () => post("/video/analyze"),
  projectStatus: () => get("/project/status") as Promise<ProjectStatus>,
  listShots: () => get("/shots") as Promise<{ shots: Shot[] }>,
  getShot: (id: string) => get(`/shots/${id}`) as Promise<Shot>,
  getFrameUrl,
  exportJson: () => post("/export/json"),
  exportMarkdown: () => post("/export/markdown"),
};
