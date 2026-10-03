import { fetch as tauriFetch } from "@tauri-apps/plugin-http";
import { isTauri } from "@tauri-apps/api/core";

const fetch = isTauri() ? tauriFetch : window.fetch.bind(window);

import { apiEndpoint } from './runtime';
import type { FramePosition, SelectionRecord, SelectionRequest } from '../selection/selection';
const apiBase=()=>`${apiEndpoint}/api/v1`;

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

export interface Observation {
  subject_type?: string;
  subject_position?: string;
  background_type?: string;
  depth_layers?: number | null;
}

export interface Motion {
  type?: string;
  strength?: number;
  confidence?: number;
  description?: string;
}

export interface Typography {
  has_text?: boolean;
  position?: string;
  style?: string;
}

export interface NormalizedBBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TextRegion {
  id: string;
  text: string;
  normalized_text: string;
  language: string;
  confidence: number;
  bbox_normalized: NormalizedBBox;
  center_x: number;
  center_y: number;
  width_ratio: number;
  height_ratio: number;
  orientation: string;
  frame_timestamp: number;
}

export interface TypographyAnalysis {
  role: string;
  style_family: string;
  weight: string;
  tracking: string;
  alignment: string;
  orientation: string;
  dominant_color: string;
  contrast_level: string;
  visual_emphasis: string;
  motion_style: string;
  confidence: number;
  observations: string[];
  ae_hypothesis: string[];
}

export interface TextTrack {
  track_id: string;
  canonical_text: string;
  language: string;
  start_time: number;
  end_time: number;
  duration: number;
  average_confidence: number;
  average_bbox: NormalizedBBox;
  frame_count: number;
  movement: string;
  appearance: string;
  observed_notes: string[];
  ae_hypothesis: string[];
  color_observation?: {
    dominant_color: string;
    contrast_level: string;
    notes: string;
  };
  typography_analysis?: TypographyAnalysis | null;
}

export interface TypographyRecipe {
  text: string;
  role: string;
  start_time: number;
  end_time: number;
  duration: number;
  position: string;
  alignment: string;
  style_family: string;
  weight: string;
  tracking: string;
  motion: string;
  appearance: string;
  estimated_size: string;
  suggested_animation: Record<string, unknown>;
  notes: string;
}

export interface VisualEffect {
  type?: string;
  confidence?: number;
}

export interface AEHypothesis {
  possible_method?: string;
  possible_effect?: string;
  possible_transition?: string;
  notes?: string;
}

export interface MeasuredMotion {
  status?: string;
  method?: string;
  message?: string;
  sample_count?: number;
  valid_pair_count?: number;
  total_pair_count?: number;
  translation_x_px?: number;
  translation_y_px?: number;
  translation_x_ratio?: number;
  translation_y_ratio?: number;
  scale_ratio?: number;
  scale_change_percent?: number;
  rotation_deg?: number;
  motion_strength?: string;
  stability?: number;
  shake_score?: number;
  confidence?: number;
  cv_analysis_ms?: number;
}

export interface MotionSummary {
  semantic_type?: string;
  semantic_confidence?: number;
  measured_type?: string;
  measured_confidence?: number;
  fused_type?: string;
  fused_confidence?: number;
  conflict?: boolean;
  measured_status?: string;
}

export interface AERecipe {
  layers?: Array<{ role: string; suggestion: string }>;
  camera?: { type?: string; strength?: number; confidence?: number };
  transform?: Record<string, unknown>;
  measured_motion?: {
    status?: string;
    scale_change_percent?: number;
    translation_x_ratio?: number;
    translation_y_ratio?: number;
    rotation_deg?: number;
    motion_strength?: string;
    confidence?: number;
    notes?: string[];
  };
  typography?: TypographyRecipe[];
  effects?: string[];
  difficulty?: Record<string, string | number | boolean>;
  hypothesis?: AEHypothesis;
}

export interface Shot {
  provider_versions?:Record<string,unknown>;
  shot_id: string;
  library_id?: number | null;
  analysis_version?: string;
  time: TimeRange;
  frames: string[];
  observations: Observation;
  motion: Motion;
  measured_motion: MeasuredMotion;
  motion_summary: MotionSummary;
  typography: Typography;
  visual_effects: VisualEffect[];
  ae_hypothesis: AEHypothesis;
  ae_recipe: AERecipe;
  text_regions: TextRegion[];
  typography_tracks: TextTrack[];
  analysis_error?: string;
  rhythm?: CutRhythm;
}

export interface CutRhythm {
  status: "not_analyzed" | "not_cut" | "ok" | "no_beats" | "unavailable";
  cut_time: number | null;
  nearest_beat: number | null;
  delta_ms: number | null;
  beat_sync: boolean | null;
  nearest_onset: number | null;
  onset_delta_ms: number | null;
  tolerance_ms: number;
  message?: string;
}

export interface AudioAnalysis {
  status: "pending" | "ok" | "no_audio" | "silent" | "insufficient" | "error";
  message: string;
  tempo_bpm: number | null;
  beat_times: number[];
  onset_times: number[];
  beat_regularity: number;
  waveform: Array<{ time: number; rms: number }>;
  duration: number;
  cache_hit: boolean;
}

export interface RhythmSummary {
  cut_count: number;
  measured_cut_count: number;
  synced_cut_count: number;
  sync_ratio: number | null;
  median_abs_delta_ms: number | null;
  tolerance_ms: number;
  excluded_shot_count?: number;
}

export interface StageProgress {
  status: "pending" | "running" | "completed" | "error" | "skipped";
  progress: number;
  completed: number;
  total: number;
  failed: number;
  message: string;
}

export interface AnalysisProgress {
  status: string;
  stage: string;
  overall_progress: number;
  message: string;
  current_shot: number | null;
  total_shots: number | null;
  started_at: number | null;
  completed_at: number | null;
  eta_seconds: number | null;
  error: { stage?: string; message?: string; shot?: string } | null;
  stages: Record<string, StageProgress>;
}

export interface ProjectStatus {
  status: string;
  message: string;
  video: VideoInfo | null;
  video_path: string | null;
  shot_count: number;
  progress: AnalysisProgress;
  library_warning?: string;
  library_project_id?: number | null;
  audio?: AudioAnalysis;
  rhythm_summary?: RhythmSummary;
}

export interface LibraryProject {
  id: number;
  name: string;
  video_filename: string;
  video_duration: number;
  analysis_status: string;
  updated_at: string;
}

export interface LibraryShot {
  id: number;
  project_id: number;
  shot_id: string;
  start_time: number;
  end_time: number;
  duration: number;
  thumbnail_path: string | null;
  motion_type: string;
  has_text: boolean;
  tags: string[];
  motion_confidence: number;
  scene_type: string;
}

export interface LibraryShotDetail extends LibraryShot {
  observations: Record<string, unknown>;
  motion: Record<string, unknown>;
  measured_motion: Record<string, unknown>;
  motion_summary: Record<string, unknown>;
  typography: Record<string, unknown>;
  typography_tracks: TextTrack[];
  ae_hypothesis: Record<string, unknown>;
  ae_recipe: AERecipe;
  manual_tags: string[];
  automatic_tags: string[];
  analysis_version: string;
  pipeline_version: string;
  provider_versions: Record<string, unknown>;
  rhythm?: CutRhythm;
  source: LibraryProject & { video_path: string; video_hash: string; name: string };
}

export interface Tag {
  id: number;
  name: string;
  color: string;
}

export interface FilterRequest {
  query?: string;
  motion_types?: string[];
  has_text?: boolean | null;
  min_duration?: number | null;
  max_duration?: number | null;
  tags?: string[];
  limit?: number;
  offset?: number;
  min_confidence?: number | null;
  max_confidence?: number | null;
  project_id?: number | null;
}

async function mutate(path: string, method: "PUT" | "DELETE", body?: unknown) {
  const response = await fetch(`${apiBase()}${path}`, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
  return response.json();
}

async function post(path: string, body?: unknown) {
  const options: RequestInit = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  };
  if (body !== undefined) {
    options.body = JSON.stringify(body);
  }
  const res = await fetch(`${apiBase()}${path}`, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

async function get(path: string) {
  const res = await fetch(`${apiBase()}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export function getFrameUrl(shotId: string, frameName: string, libraryId?: number | null): string {
  const name = frameName.replace(/\\/g, "/").split("/").pop() || frameName;
  const query = libraryId == null ? "" : `?library_id=${libraryId}`;
  return `${apiBase()}/shots/${encodeURIComponent(shotId)}/frame/${encodeURIComponent(name)}${query}`;
}

export const api = {
  framePosition:(pid:number,time:number,pts?:number,direction:'current'|'previous'|'next'='current')=>get(`/projects/${pid}/frame-position?time=${time}&direction=${direction}${pts==null?'':`&pts=${pts}`}`) as Promise<FramePosition>,
  previewUrl:(value:string)=>`${apiEndpoint}${value}`,
  submitSelection:(pid:number,request:SelectionRequest)=>post(`/projects/${pid}/selection-analyses`,request) as Promise<{record_id:string}>,
  selectionRecords:(pid:number,offset=0)=>get(`/projects/${pid}/selection-analyses?limit=20&offset=${offset}`) as Promise<{items:SelectionRecord[];total:number}>,
  selectionRecord:(id:string)=>get(`/selection-analyses/${encodeURIComponent(id)}`) as Promise<SelectionRecord>,
  verifySelectionSource:(id:string)=>get(`/selection-analyses/${encodeURIComponent(id)}/source-check`) as Promise<{source_available:boolean}>,
  selectionAssetUrl:(id:string,name:string)=>`${apiBase()}/selection-analyses/${encodeURIComponent(id)}/assets/${name.split('/').map(encodeURIComponent).join('/')}`,
  exportSelection:(id:string,format:'json'|'markdown')=>post(`/selection-analyses/${encodeURIComponent(id)}/export`,{format}) as Promise<{path:string}>,
  importVideo: (path: string) => post("/video/import", { path }),
  analyzeVideo: (mode:'full'|'basic'='full') => post("/video/analyze",{mode}),
  analyzeAudio: (force = false) => post("/video/analyze-audio", { force }),
  videoSourceUrl: (identity: string) => `${apiBase()}/video/source?identity=${encodeURIComponent(identity)}`,
  projectStatus: () => get("/project/status") as Promise<ProjectStatus>,
  listShots: () => get("/shots") as Promise<{ shots: Shot[] }>,
  getShot: (id: string) => get(`/shots/${id}`) as Promise<Shot>,
  getFrameUrl,
  exportJson: () => post("/export/json"),
  exportMarkdown: () => post("/export/markdown"),
  listLibraryProjects: () => get("/library/projects") as Promise<{ projects: LibraryProject[] }>,
  getLibraryProject: (id: number) => get(`/library/projects/${id}`) as Promise<{ project: LibraryProject; shots: LibraryShot[] }>,
  loadLibraryProject: (id: number) => post(`/library/projects/${id}/load`) as Promise<{ status: string; shot_count: number }>,
  deleteLibraryProject: (id: number) => mutate(`/library/projects/${id}`, "DELETE"),
  saveToLibrary: () => post("/library/save"),
  getLibraryShot: (id: number) => get(`/library/shots/${id}`) as Promise<LibraryShotDetail>,
  libraryThumbnailUrl: (id: number) => `${apiBase()}/library/shots/${id}/thumbnail`,
  librarySourceUrl: (id: number) => `${apiBase()}/library/shots/${id}/source`,
  getLibraryRecipe: (id: number) => get(`/library/shots/${id}/recipe`) as Promise<AERecipe>,
  exportLibraryRecipe: (id: number) => post(`/library/shots/${id}/export/recipe`) as Promise<{ path: string }>,
  setLibraryShotTags: (id: number, tags: string[]) => mutate(`/library/shots/${id}/tags`, "PUT", { tags }) as Promise<LibraryShotDetail>,
  deleteTag: (id: number) => mutate(`/tags/${id}`, "DELETE"),
  listTags: () => get("/tags") as Promise<{ tags: Tag[] }>,
  createTag: (name: string, color: string = "#3b82f6") => post("/tags", { name, color }),
  getSettings:()=>get('/settings') as Promise<UserSettings>,
  putSettings:(value:UserSettings)=>mutate('/settings','PUT',value) as Promise<UserSettings>,
  modelRecommendations:()=>get('/models/recommendations') as Promise<ModelCatalog>,
  modelStatus:()=>get('/models/status') as Promise<ModelStatus>,
  listProjects:()=>get('/projects') as Promise<{projects:ManagedProject[]}>,
  saveProject:()=>post('/project/save') as Promise<{project_id:number}>,
  renameProject:(id:number,name:string)=>mutate(`/projects/${id}/name`,'PUT',{name}),
  relinkProject:(id:number,path:string)=>post(`/projects/${id}/relink`,{path}),
  getSession:()=>get('/session') as Promise<SessionState>,
  putSession:(value:SessionState)=>mutate('/session','PUT',value),
  importLegacyLibrary:(source_db:string,source_root:string)=>post('/projects/import-legacy',{source_db,source_root}),
  setShotTags: (shotId: string, tags: string[]) => post(`/shots/${shotId}/tags`, { tags }),
  searchLibrary: (filters: FilterRequest) => post("/search", filters) as Promise<{ shots: LibraryShot[]; motion_types: string[] }>,
};

export interface UserSettings{schema_version:number;ollama_url:string;qwen_model_id:string;ocr_models:{language:string;detection_dir:string;recognition_dir:string;orientation_dir:string|null}[];beat_sync_tolerance_ms:number}
export interface ModelCatalog{recommendations:{id:string;profile:string;use:string;official_url:string;artifact_size_bytes:number|null;validation_status:string}[];hardware:{ram_bytes?:number|null;gpu_name?:string|null;vram_bytes?:number|null}}
export interface DiscoveredOCRModel{label:string;languages:string[];detection_dir:string;recognition_dir:string}
export interface ModelStatus{connected:boolean;message:string;models:{id:string;size:number|null;vision:boolean;error:string}[];ocr:{available:boolean;engine_installed:boolean;configured:boolean;discovered_models:DiscoveredOCRModel[];errors:string[]}}
export interface ManagedProject{id:number;name:string;internal_name:string;video_filename:string;updated_at:string;shot_count:number;source_available:boolean}
export interface SessionState{project_id:number|null;shot_library_id:number|null;shot_id:string|null}
