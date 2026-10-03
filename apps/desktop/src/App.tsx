import { AnalysisFields } from './i18n/AnalysisFields';
import { initializeRuntime,pollBackend,type BackendStatus } from './services/runtime';
import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  api,
  type AudioAnalysis,
  type AnalysisProgress,
  type NormalizedBBox,
  type ProjectStatus,
  type RhythmSummary,
  type Shot,
  type StageProgress,
  type TextTrack,
  type VideoInfo,
} from "./services/api";
import { LibraryView } from "./components/LibraryView";
import { CutRhythmView } from "./components/RhythmPanel";
import "./App.css";
import { Workbench } from './workbench/Workbench';
import { MraMark, Icon } from './design/icons';
import { labelValue, displayRecipeText } from './i18n/labels';
import { ProjectsPage } from './management/ProjectsPage';
import { ModelsPage } from './management/ModelsPage';
import { SettingsPage } from './management/SettingsPage';
import './management/management.css';
import { useSelectionRecords } from './selection/SelectionRecords';
import type { SelectionRequest } from './selection/selection';

type AnalysisStatus = ProjectStatus["status"];

function shotKey(shot: Shot): string {
  return shot.library_id == null ? shot.shot_id : `${shot.shot_id}:${shot.library_id}`;
}

const STATUS_LABELS: Record<string, string> = {
  idle: "空闲",
  imported: "已导入视频",
  processing: "分析中",
  preparing: "准备分析",
  scene_detect: "正在分镜",
  extract_frames: "正在提取代表帧",
  audio_analysis: "正在音频节奏分析",
  vision_analysis: "正在 AI 视觉分析",
  cv_analysis: "正在 CV 运动测量",
  cv_motion_analysis: "正在 CV 运动测量",
  recipe_generation: "正在生成 AE 制作建议",
  generating_recipe: "正在生成 AE 制作建议",
  saving: "正在保存结果",
  done: "分析完成",
  completed_with_warnings: "分析完成（含警告）",
  error: "发生错误",
};

const STAGE_ORDER = [
  "preparing",
  "scene_detect",
  "extract_frames",
  "audio_analysis",
  "vision_analysis",
  "cv_analysis",
  "ocr_analysis",
  "typography_analysis",
  "recipe_generation",
  "saving",
];

const STAGE_LABELS: Record<string, string> = {
  preparing: "准备",
  scene_detect: "镜头检测",
  extract_frames: "代表帧提取",
  audio_analysis: "音频节奏分析",
  vision_analysis: "AI 视觉分析",
  cv_analysis: "CV 运动分析",
  ocr_analysis: "OCR 文字识别",
  typography_analysis: "文字与排版分析",
  recipe_generation: "AE 制作建议",
  saving: "保存结果",
};

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0");
  const s = (seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function _positionLabel(bbox: NormalizedBBox | undefined): string {
  if (!bbox) return "unknown";
  const cx = bbox.x + bbox.width / 2;
  const cy = bbox.y + bbox.height / 2;
  const h = cx < 0.35 ? "left" : cx > 0.65 ? "right" : "center";
  const v = cy < 0.35 ? "top" : cy > 0.65 ? "bottom" : "center";
  if (v === "center") return h;
  if (h === "center") return v;
  return `${v}_${h}`;
}

function TypographyRecipeView({
  recipe,
  shot,
}: {
  recipe: TextTrack;
  shot: Shot;
}) {
  const analysis = recipe.typography_analysis;
  const aeRecipe = shot.ae_recipe?.typography?.find(
    (t) => t.text === recipe.canonical_text
  );

  return (
    <div className="typography-recipe">
      {analysis && (
        <>
          <p>
            <strong>用途：</strong> {labelValue("value", analysis.role)}
          </p>
          <p>
            <strong>风格：</strong> {labelValue("value", analysis.style_family)} / {labelValue("value", analysis.weight)} /{" "}
            {labelValue("value", analysis.tracking)}
          </p>
          <p>
            <strong>颜色：</strong> {labelValue("value", analysis.dominant_color)} (
            {labelValue("value", analysis.contrast_level)} 对比度)
          </p>
          <p>
            <strong>画面观察：</strong>
          </p>
          <ul>
            {analysis.observations.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
          <p>
            <strong>AE 实现推测：</strong>
          </p>
          <ul>
            {analysis.ae_hypothesis.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        </>
      )}
      {aeRecipe && (
        <>
          <p>
            <strong>建议动画：</strong>
          </p>
          <AnalysisFields value={aeRecipe.suggested_animation}/>
          <p className="recipe-note">{aeRecipe.notes}</p>
        </>
      )}
    </div>
  );
}
function useElapsed(progress: AnalysisProgress | null): number {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const update = () => {
      if (!progress?.started_at) {
        setElapsed(0);
        return;
      }
      const startMs = progress.started_at * 1000;
      const endMs = progress.completed_at ? progress.completed_at * 1000 : Date.now();
      setElapsed(Math.max(0, Math.floor((endMs - startMs) / 1000)));
    };

    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [progress]);

  return elapsed;
}

function StageIcon({ status }: { status: StageProgress["status"] }) {
  if (status === "completed") return <span className="stage-icon completed">✓</span>;
  if (status === "running") return <span className="stage-icon running" />;
  if (status === "error") return <span className="stage-icon error">!</span>;
  return <span className="stage-icon pending">○</span>;
}

function ProgressPanel({
  progress,
  elapsed,
}: {
  progress: AnalysisProgress;
  elapsed: number;
}) {
  const isDone = progress.status === "done" || progress.status === "completed_with_warnings";
  const isError = progress.status === "error";

  return (
    <section className="progress-panel card">
      <div className="progress-header">
        <strong>{STATUS_LABELS[progress.status] || progress.status}</strong>
        <span>{Math.round(progress.overall_progress * 100)}%</span>
      </div>

      <div className="progress-bar">
        <div
          className="progress-bar-fill"
          style={{ width: `${Math.max(0, Math.min(1, progress.overall_progress)) * 100}%` }}
        />
      </div>

      <div className="progress-meta">
        <span>已用时 {formatElapsed(elapsed)}</span>
        {!isDone && !isError && (
          <span>
            {progress.eta_seconds != null
              ? `预计剩余 ${formatElapsed(Math.ceil(progress.eta_seconds))}`
              : "正在估算…"}
          </span>
        )}
      </div>

      {progress.message && !isDone && (
        <p className="progress-message">{progress.message}</p>
      )}

      {isError && progress.error && (
        <div className="progress-error">
          <p>
            <strong>阶段:</strong> {progress.error.stage || "unknown"}
          </p>
          {progress.error.shot && (
            <p>
              <strong>镜头：</strong> {progress.error.shot}
            </p>
          )}
          <p>
            <strong>错误:</strong> {progress.error.message || "未知错误"}
          </p>
        </div>
      )}

      {!isDone && !isError && (
        <ul className="stage-list">
          {STAGE_ORDER.map((key) => {
            const stage = progress.stages[key];
            if (!stage) return null;
            return (
              <li key={key} className={`stage-item ${stage.status}`}>
                <StageIcon status={stage.status} />
                <span className="stage-name">{STAGE_LABELS[key] || key}</span>
                {stage.status === "running" && stage.total > 0 && (
                  <span className="stage-count">
                    {stage.completed + stage.failed}/{stage.total}
                  </span>
                )}
                {stage.status === "error" && stage.failed > 0 && (
                  <span className="stage-count warn">{stage.failed} 失败</span>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {isDone && (
        <div className="progress-summary">
          <p>
            ✓ 分析完成 · {progress.total_shots ?? 0} 个镜头 · 总耗时 {formatElapsed(elapsed)}
          </p>
        </div>
      )}
    </section>
  );
}

function App() {
  const restoring=useRef(true);
  const [backend,setBackend]=useState<BackendStatus>({status:'starting',endpoint:null,owned:false,instance_id:'',message:'正在启动本地分析服务…'});
  const [bootAttempt,setBootAttempt]=useState(0);
  const [video, setVideo] = useState<VideoInfo | null>(null);
  const [audio, setAudio] = useState<AudioAnalysis>();
  const [rhythmSummary, setRhythmSummary] = useState<RhythmSummary>();
  const [videoSource, setVideoSource] = useState("");
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [statusMessage, setStatusMessage] = useState("");
  const [progress, setProgress] = useState<AnalysisProgress | null>(null);
  const [shots, setShots] = useState<Shot[]>([]);
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [projectId,setProjectId]=useState<number|null>(null);
  const [selectionSubmitting,setSelectionSubmitting]=useState(false);
  const selections=useSelectionRecords(projectId);
  const busy=loading||selectionSubmitting||selections.busy;
  const [error, setError] = useState<string>("");
  const [libraryWarning, setLibraryWarning] = useState("");
  const [libraryNotice, setLibraryNotice] = useState("");
  const [view, setView] = useState<"analysis" | "library" | "projects" | "models" | "settings">("projects");

  const elapsed = useElapsed(progress);

  const selectedShot = useMemo(
    () => shots.find((s) => shotKey(s) === selectedShotId) || null,
    [shots, selectedShotId],
  );

  const refreshStatus = useCallback(async () => {
    try {
      const service=await pollBackend();
      if(service?.status==='error'){setBackend(service);return}
      const data = await api.projectStatus();
      setStatus(data.status);
      setStatusMessage(data.message || "");
      setVideo(data.video);
      setAudio(data.audio);
      setRhythmSummary(data.rhythm_summary);
      setVideoSource(data.video_path || "");
      setProjectId(data.library_project_id??null);
      setProgress(data.progress);
      setLibraryWarning(data.library_warning || "");
      setError(previous => previous.startsWith("无法连接后端:") ? "" : previous);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(`无法连接后端: ${message}`);
    }
  }, []);

  useEffect(() => {
    restoring.current=true;
    let cancelled=false;let timer:ReturnType<typeof setInterval>|undefined;
    void (async()=>{
      const state=await initializeRuntime(bootAttempt>0);
      if(cancelled)return;setBackend(state);if(state.status!=='ready')return;
      try{
        const session=await api.getSession();if(cancelled)return;
        if(session.project_id)await api.loadLibraryProject(session.project_id);
        const data=await api.listShots();if(cancelled)return;setShots(data.shots);
        const selected=data.shots.find(shot=>session.shot_library_id!=null?shot.library_id===session.shot_library_id:shot.shot_id===session.shot_id)??data.shots[0];
        setSelectedShotId(selected?shotKey(selected):null);
      }catch(err){if(!cancelled)setError(`上次项目未恢复：${String(err)}`)}
      restoring.current=false;
      if(cancelled)return;await refreshStatus();timer=setInterval(refreshStatus,1000);
    })().catch(err=>{if(!cancelled)setBackend({status:'error',endpoint:null,owned:false,instance_id:'',message:String(err)})});
    return ()=>{cancelled=true;if(timer)clearInterval(timer)};
  }, [refreshStatus,bootAttempt]);

  async function importVideo() {
    setError("");
    setSelectedShotId(null);
    try {
      const selected = await invoke<string | null>("select_video");
      if (!selected) return;

      setLoading(true);
      const data = await api.importVideo(selected);
      if (data.status === "ok") {
        setVideo(data.video as VideoInfo);
        setProjectId(null);
        setAudio(undefined); setRhythmSummary(undefined); setVideoSource(selected);
        setShots([]);
        setSelectedShotId(null);
        setStatus("imported");
        setView("analysis");
      } else {
        throw new Error(JSON.stringify(data));
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function analyzeVideo(mode:'full'|'basic'='full') {
    setError("");
    setLoading(true);

    try {
      const data = await api.analyzeVideo(mode);

      if (data.status === "ok") {
        const shotsResponse = await api.listShots();
        const shotsData = shotsResponse.shots;

        setShots(shotsData);
        setStatus("done");

        if (shotsData.length > 0) {
          setSelectedShotId(shotKey(shotsData[0]));
        }
      } else {
        throw new Error(JSON.stringify(data));
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus("error");
    } finally {
      setLoading(false);
    }
  }

  async function ensureSelectionProject(){
    if(projectId!=null)return projectId;
    const saved=await api.saveProject();setProjectId(saved.project_id);
    await api.putSession({project_id:saved.project_id,shot_library_id:selectedShot?.library_id??null,shot_id:selectedShot?.shot_id??null});
    return saved.project_id;
  }
  async function submitSelection(request:SelectionRequest){
    setSelectionSubmitting(true);
    try{const pid=await ensureSelectionProject();const value=await api.submitSelection(pid,request);await selections.created(value.record_id)}
    finally{setSelectionSubmitting(false)}
  }

  async function exportJson() {
    setError("");
    try {
      const data = await api.exportJson();
      alert(`JSON 已导出: ${data.path}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function analyzeAudio() {
    setError(""); setLoading(true);
    try {
      await api.analyzeAudio(true);
      const data = await api.listShots();
      setShots(data.shots);
      await refreshStatus();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally { setLoading(false); }
  }

  async function exportMarkdown() {
    setError("");
    try {
      const data = await api.exportMarkdown();
      alert(`Markdown 已导出: ${data.path}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function refreshShots() {
    try {
      const shotsResponse = await api.listShots();
      setShots(shotsResponse.shots);
      if (shotsResponse.shots.length > 0) setSelectedShotId(shotKey(shotsResponse.shots[0]));
      await refreshStatus();
      setView("analysis");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(()=>{
    if(selectedShot&&!busy&&!restoring.current&&backend.status==='ready')void api.projectStatus().then(data=>{
      if(data.library_project_id)return api.putSession({project_id:data.library_project_id,shot_library_id:selectedShot.library_id??null,shot_id:selectedShot.shot_id});
    }).catch(()=>{});
  },[selectedShotId,busy]);

  const showProgressPanel = progress != null && progress.status !== "idle" && status !== "idle" && status !== "imported";

  if(backend.status!=='ready')return <main className="container"><header className="header"><MraMark/><h1>MRA</h1></header><section className="management-page"><h2>{backend.status==='starting'?'正在启动':'分析服务未启动'}</h2><p role="status">{backend.message}</p>{backend.status==='error'&&<><button onClick={()=>setBootAttempt(n=>n+1)}>重试启动</button><button onClick={()=>void invoke<string>('backend_log_path').then(path=>setError(`日志位置：${path}`))}>查看日志位置</button><p>{error}</p></>}</section></main>;
  return (
    <main className="container">
      <header className="header">
        <MraMark/><h1>MRA</h1>
        <p>参考视频镜头分析与 AE 拆解工具</p>
      </header>

      <section className="toolbar">
        <button onClick={()=>setView('projects')} className={view==='projects'?'active':''}><Icon name="project"/>项目</button>
        <button onClick={() => setView("analysis")} className={view === "analysis" ? "active" : ""}>
          分析
        </button>
        <button onClick={() => setView("library")} className={view === "library" ? "active" : ""}>
          参考库
        </button>
        <button onClick={()=>setView('models')} className={view==='models'?'active':''}><Icon name="models"/>模型</button>
        <button onClick={()=>setView('settings')} className={view==='settings'?'active':''}><Icon name="settings"/>设置</button>
        <div className="toolbar-spacer" />
        <button onClick={importVideo} disabled={busy}>
          <Icon name="import"/>导入视频
        </button>
        <button onClick={()=>analyzeVideo('full')} disabled={busy || !video}>
          <Icon name="analyze"/>分析视频
        </button>
        <button onClick={()=>analyzeVideo('basic')} disabled={busy||!video}>基础分析</button>
        <button onClick={exportJson} disabled={shots.length === 0}>
          导出 JSON
        </button>
        <button onClick={exportMarkdown} disabled={shots.length === 0}>
          导出 Markdown
        </button>
        <button disabled={busy || !video} onClick={async () => {
          try { await api.saveProject(); setLibraryNotice("已保存到 参考库"); await refreshStatus(); }
          catch (err) { setError(err instanceof Error ? err.message : String(err)); }
        }}>{libraryWarning ? "重试保存" : "保存到参考库"}</button>
      </section>

      {view==='projects'&&<ProjectsPage busy={busy} onProjectLoaded={refreshShots} onImport={()=>{setView('analysis');void importVideo()}}/>}
      {view==='models'&&<ModelsPage busy={busy}/>}
      {view==='settings'&&<SettingsPage busy={busy}/>}
      {view === "library" && <LibraryView onLoadProject={refreshShots} busy={busy} onLoadingChange={setLoading} />}

      {view === "analysis" && <>
      {libraryWarning && <div role="alert" className="error-box">{libraryWarning}</div>}
      {libraryNotice && <p role="status">{libraryNotice}</p>}

      {showProgressPanel && <ProgressPanel progress={progress} elapsed={elapsed} />}

      {!showProgressPanel && loading && (
        <div className="loading">
          <span className="spinner" />
          <span>处理中... {STATUS_LABELS[status] || status}</span>
        </div>
      )}

      {error && (
        <div className="error-box">
          <strong>错误</strong>
          <pre>{error}</pre>
        </div>
      )}

      <section className="status-bar">{STATUS_LABELS[status] || status}{statusMessage && ` · ${statusMessage}`}</section>
      <Workbench key={videoSource} video={video} source={videoSource} shots={shots} selected={selectedShot} audio={audio} summary={rhythmSummary} busy={busy} selections={selections} ensureProject={ensureSelectionProject} onSelectionSubmit={submitSelection}
        onSelect={shot=>setSelectedShotId(shotKey(shot))} onAnalyze={analyzeAudio}
        detail={selectedShot?<ShotDetail shot={selectedShot}/>:<p className="muted">选择镜头查看画面、运动、文字和制作建议</p>}/>
      </>}
    </main>
  );
}

function ShotDetail({ shot }: { shot: Shot }) {
  const [overlay,setOverlay]=useState(false);
  const skipped=(shot.provider_versions?.vision as {provider?:string}|undefined)?.provider==='disabled';
  const motion = shot.motion || {};
  const measured = shot.measured_motion || {};
  const summary = shot.motion_summary || {};
  const observations = shot.observations || {};
  const typography = shot.typography || {};
  const visualEffects = shot.visual_effects || [];
  const hypothesis = shot.ae_hypothesis || {};
  const recipe = shot.ae_recipe || {};
  const difficulty = recipe.difficulty as Record<string, string> | undefined;

  return (
    <>
      <h2>
        {shot.shot_id}
        <span className="shot-time">
          {shot.time.start.toFixed(2)}s - {shot.time.end.toFixed(2)}s
          （持续 {shot.time.duration.toFixed(2)}s）
        </span>
      </h2>

      {shot.analysis_error && (
        <section className="detail-section warning">
          <h3>分析警告</h3>
          <p>{shot.analysis_error}</p>
        </section>
      )}

      <section className="detail-section"><h3>切镜节奏</h3><CutRhythmView rhythm={shot.rhythm} /></section>

      <section className="detail-section">
        <h3>代表帧</h3><div><a href={api.getFrameUrl(shot.shot_id,'contact.jpg',shot.library_id)} target='_blank' rel='noreferrer'>查看联系表</a>{shot.typography_tracks.length>0&&<label><input type='checkbox' checked={overlay} onChange={e=>setOverlay(e.target.checked)}/>文字轨迹平均范围</label>}</div>{overlay&&<p className='muted'>区域为文字轨迹平均范围，非当前帧精确检测</p>}
        <div className="frame-strip">
          {shot.frames.map((frame) => (
            <span className='ocr-overlay' key={frame}><img
              src={api.getFrameUrl(shot.shot_id, frame, shot.library_id)}
              alt={`${shot.shot_id} 代表帧`}
              loading="lazy"
            />{overlay&&<svg viewBox='0 0 100 100' preserveAspectRatio='none'>{shot.typography_tracks.map(track=><rect key={track.track_id} x={track.average_bbox.x*100} y={track.average_bbox.y*100} width={track.average_bbox.width*100} height={track.average_bbox.height*100} fill='none' stroke='#79d1a5' strokeWidth='.8'/>)}</svg>}</span>
          ))}
        </div>
      </section>

      <section className="detail-section">
        <h3>画面观察</h3>{(shot.provider_versions?.vision as {provider?:string}|undefined)?.provider==='disabled'&&<p className='muted'>基础分析已省略视觉模型，仅提供分镜、运动测量和音频节奏</p>}
        <p>主体: {labelValue("value", observations.subject_type)}</p>
        <p>主体位置: {labelValue("value", observations.subject_position)}</p>
        <p>背景类型: {labelValue("value", observations.background_type)}</p>
        {typeof observations.depth_layers === "number" && (
          <p>空间层数: {observations.depth_layers}</p>
        )}
      </section>

      <section className="detail-section">
        <h3>AI 运动解读</h3>
        <p>类型: {labelValue("value", motion.type)}</p>
        {typeof motion.strength === "number" && <p>强度: {motion.strength.toFixed(2)}</p>}
        {typeof motion.confidence === "number" && <p>置信度: {motion.confidence.toFixed(2)}</p>}
        {motion.description && <p>描述: {motion.description}</p>}
      </section>

      <section className="detail-section">
        <h3>运动测量</h3>
        {measured.status === "ok" ? (
          <>
            <p>
              整体缩放: {(measured.scale_change_percent ?? 0) > 0 ? "+" : ""}
              {(measured.scale_change_percent ?? 0).toFixed(1)}%
            </p>
            <p>
              水平位移: {(measured.translation_x_ratio ?? 0) > 0 ? "+" : ""}
              {((measured.translation_x_ratio ?? 0) * 100).toFixed(2)}%
              {" "}({measured.translation_x_px?.toFixed(1) ?? 0}px)
            </p>
            <p>
              垂直位移: {(measured.translation_y_ratio ?? 0) > 0 ? "+" : ""}
              {((measured.translation_y_ratio ?? 0) * 100).toFixed(2)}%
              {" "}({measured.translation_y_px?.toFixed(1) ?? 0}px)
            </p>
            <p>旋转: {(measured.rotation_deg ?? 0).toFixed(2)}°</p>
            <p>运动强度: {labelValue('strength',measured.motion_strength)}</p>
            <p>稳定度: {((measured.stability ?? 0) * 100).toFixed(0)}%</p>
            {typeof measured.shake_score === "number" && measured.shake_score > 0.1 && (
              <p>抖动强度: {(measured.shake_score * 100).toFixed(0)}%</p>
            )}
            <p>置信度: {((measured.confidence ?? 0) * 100).toFixed(0)}%</p>
            <p className="meta">
              基于 {measured.valid_pair_count ?? 0}/{measured.total_pair_count ?? 0} 有效帧对
              {" "}(CV: {measured.cv_analysis_ms ?? 0}ms)
            </p>
          </>
        ) : (
          <>
            <p>状态: {labelValue("value", measured.status)}</p>
            {measured.message && <p>{measured.message}</p>}
            <p className="meta">
              {skipped?'此镜头特征点不足，基础分析无法估计其运动':'此镜头无法提供可靠测量，AI运动解读可作为参考'}
            </p>
          </>
        )}
      </section>

      {summary.conflict && (
        <section className="detail-section conflict">
          <h3>综合运动 提示</h3>
          <p>
            AI 判断为 <strong>{labelValue('motion',summary.semantic_type)}</strong>，但 CV 测量倾向于{" "}
            <strong>{labelValue('motion',summary.measured_type)}</strong>。
          </p>
          <p>存在冲突，已保留两者供后续判断。</p>
        </section>
      )}

      <section className="detail-section">
        <h3>文字与排版</h3>
        {shot.typography_tracks && shot.typography_tracks.length > 0 ? (
          <div className="typography-list">
            {shot.typography_tracks.map((track, idx) => (
              <div key={track.track_id || idx} className="typography-track">
                <h4>文字轨迹 {String(idx + 1).padStart(2, "0")}</h4>
                <p className="typography-text">
                  {track.canonical_text || "（无文字）"}
                </p>
                <p>语言: {labelValue("value", track.language)}</p>
                <p>
                  时间: {track.start_time.toFixed(2)}s → {track.end_time.toFixed(2)}s
                  {" "}({track.duration.toFixed(2)}s)
                </p>
                <p>位置: {labelValue('position',_positionLabel(track.average_bbox))}</p>
                {track.typography_analysis && (
                  <>
                    <p>
                      样式: {labelValue('style_family',track.typography_analysis.style_family)} /{" "}
                      {labelValue('weight',track.typography_analysis.weight)}
                    </p>
                    <p>字距: {labelValue('tracking',track.typography_analysis.tracking)}</p>
                    <p>对齐: {labelValue('alignment',track.typography_analysis.alignment)}</p>
                    <p>运动: {labelValue("value", track.movement)}</p>
                    <p>
                      置信度: {(track.average_confidence * 100).toFixed(0)}%
                    </p>
                  </>
                )}
                <details className="typography-details">
                  <summary>查看 AE 制作建议</summary>
                  <TypographyRecipeView recipe={track} shot={shot} />
                </details>
              </div>
            ))}
          </div>
        ) : typography.has_text ? (
          <>
            <p>检测到文字（Vision 观察）</p>
            <p>位置: {labelValue("value", typography.position)}</p>
            <p>样式: {labelValue("value", typography.style)}</p>
          </>
        ) : (
          <p>{(shot.provider_versions?.vision as {provider?:string}|undefined)?.provider==='disabled'?'基础分析已省略视觉、OCR 和排版语义；未执行文字识别':'未检测到文字'}</p>
        )}
      </section>

      <section className="detail-section">
        <h3>视觉效果</h3>
        {visualEffects.length > 0 ? (
          <ul>
            {visualEffects.map((effect, idx) => (
              <li key={idx}>
                {labelValue("value", effect.type)}
                {typeof effect.confidence === "number" && ` (置信度 ${effect.confidence.toFixed(2)})`}
              </li>
            ))}
          </ul>
        ) : (
          <p>{skipped?'基础分析未执行视觉效果识别':'未检测到明显视觉效果'}</p>
        )}
      </section>

      <section className="detail-section">
        <h3>AE 实现推测</h3>
        <p>可能方法: {displayRecipeText(hypothesis.possible_method)}</p>
        <p>可能效果: {displayRecipeText(hypothesis.possible_effect)}</p>
        <p>可能转场: {displayRecipeText(hypothesis.possible_transition)}</p>
        {hypothesis.notes && <p>备注: {hypothesis.notes}</p>}
      </section>

      <section className="detail-section">
        <h3>AE 制作建议</h3>
        {recipe.layers && recipe.layers.length > 0 && (
          <>
            <h4>分层建议</h4>
            <ul>
              {recipe.layers.map((layer, idx) => (
                <li key={idx}>
                  {labelValue("value", layer.role)}: {displayRecipeText(layer.suggestion)}
                </li>
              ))}
            </ul>
          </>
        )}
        {recipe.camera && recipe.camera.type !== "static" && (
          <p>
            相机运动: {labelValue("value", recipe.camera.type)}
            {typeof recipe.camera.strength === "number" && `（强度 ${recipe.camera.strength.toFixed(2)}）`}
            {typeof recipe.camera.confidence === "number" && `（置信度 ${recipe.camera.confidence.toFixed(2)}）`}
          </p>
        )}
        {recipe.transform && Object.keys(recipe.transform).length > 0 && (
          <>
            <h4>变换参考</h4>
            <ul>
              {Object.entries(recipe.transform).map(([key, value]) => (
                <li key={key}>
                  {labelValue("value", key)}: {"from" in (value as Record<string, unknown>) && `从 ${(value as Record<string, unknown>).from} `}
                  {"to" in (value as Record<string, unknown>) && `到 ${(value as Record<string, unknown>).to}`}
                </li>
              ))}
            </ul>
          </>
        )}
        {recipe.measured_motion && recipe.measured_motion.notes && recipe.measured_motion.notes.length > 0 && (
          <>
            <h4>测量备注</h4>
            <ul>
              {recipe.measured_motion.notes.map((note, idx) => (
                <li key={idx}>{displayRecipeText(note)}</li>
              ))}
            </ul>
          </>
        )}
        {recipe.effects && recipe.effects.length > 0 && (
          <p>可能效果: {recipe.effects.map(displayRecipeText).join("、")}</p>
        )}
        {difficulty && <p>难度: {labelValue('difficulty',difficulty.ae)}</p>}
      </section>
    </>
  );
}

export default App;
