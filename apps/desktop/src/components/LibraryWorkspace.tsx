import { AnalysisFields } from '../i18n/AnalysisFields';
import { labelValue } from '../i18n/labels';
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type LibraryProject, type LibraryShot, type LibraryShotDetail, type Tag } from "../services/api";
import "./LibraryView.css";
import { CutRhythmView } from "./RhythmPanel";
import { MotionTrajectoryView } from './MotionTrajectoryView';
import { AnimationPlanView } from './AnimationPlanView';

const PAGE_SIZE = 48;
const message = (err: unknown) => err instanceof Error ? err.message : String(err);
const optionalNumber = (value: string) => value === "" ? null : Number(value);
type LibraryPlayback = { mode: "shot" | "source" | "frame"; time: number };

function applyPlayback(player: HTMLVideoElement, request: LibraryPlayback) {
  player.currentTime = request.time;
  if (request.mode === "frame") player.pause();
  else void player.play().catch(() => {});
}

export function LibraryView({ onLoadProject, busy = false, onLoadingChange }: {
  onLoadProject?: () => Promise<void> | void;
  busy?: boolean;
  onLoadingChange?: (busy: boolean) => void;
}) {
  const [projects, setProjects] = useState<LibraryProject[]>([]);
  const [source, setSource] = useState("");
  const [shots, setShots] = useState<LibraryShot[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [query, setQuery] = useState("");
  const [motion, setMotion] = useState("");
  const [motionTypes, setMotionTypes] = useState<string[]>([]);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [hasText, setHasText] = useState("");
  const [minDuration, setMinDuration] = useState("");
  const [maxDuration, setMaxDuration] = useState("");
  const [minConfidence, setMinConfidence] = useState("");
  const [maxConfidence, setMaxConfidence] = useState("");
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [detail, setDetail] = useState<LibraryShotDetail | null>(null);
  const [tagName, setTagName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [playback, setPlayback] = useState<LibraryPlayback | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const detailRequest = useRef(0);
  const tagMutation = useRef(false);
  const [savingTags, setSavingTags] = useState(false);
  const refreshMetadata = useCallback(async () => {
    try {
      const [p, t] = await Promise.all([api.listLibraryProjects(), api.listTags()]);
      setProjects(p.projects); setTags(t.tags);
    } catch (err) { setError(message(err)); }
  }, []);
  useEffect(() => { void refreshMetadata(); }, [refreshMetadata, refresh]);
  useEffect(() => { setOffset(0); }, [query, motion, source, selectedTags, hasText, minDuration, maxDuration, minConfidence, maxConfidence]);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const data = await api.searchLibrary({ query: query.trim(), motion_types: motion ? [motion] : [],
          project_id: optionalNumber(source), has_text: hasText === "" ? null : hasText === "yes",
          min_duration: optionalNumber(minDuration), max_duration: optionalNumber(maxDuration),
          min_confidence: optionalNumber(minConfidence), max_confidence: optionalNumber(maxConfidence),
          tags: selectedTags, limit: PAGE_SIZE, offset });
        if (!cancelled) { setShots(data.shots); setMotionTypes(data.motion_types); setError(""); }
      } catch (err) { if (!cancelled) { setError(message(err)); setShots([]); } }
      finally { if (!cancelled) setLoading(false); }
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query, motion, source, selectedTags, hasText, minDuration, maxDuration, minConfidence, maxConfidence, offset, refresh]);
  async function inspect(id: number) {
    const request = ++detailRequest.current;
    setPlayback(null); setNotice(""); setDetail(null);
    try { const data = await api.getLibraryShot(id); if (request === detailRequest.current) setDetail(data); }
    catch (err) { if (request === detailRequest.current) setError(message(err)); }
  }
  async function loadProject(id: number) {
    if (busy) return;
    onLoadingChange?.(true);
    try { await api.loadLibraryProject(id); await onLoadProject?.(); }
    catch (err) { setError(message(err)); }
    finally { onLoadingChange?.(false); }
  }
  async function deleteProject(id: number) {
    if (!confirm("删除此 参考库项目和分析记录？源视频和帧文件会保留。")) return;
    try {
      await api.deleteLibraryProject(id);
      if (detail?.project_id === id) setDetail(null);
      if (source === String(id)) setSource("");
      setRefresh(r => r + 1);
    } catch (err) { setError(message(err)); }
  }
  async function updateTags(names: string[]) {
    if (!detail || tagMutation.current) return;
    const selected = detail;
    const request = detailRequest.current;
    tagMutation.current = true; setSavingTags(true);
    try {
      const updated = await api.setLibraryShotTags(selected.id, names);
      if (request === detailRequest.current) { setDetail(updated); setTagName(""); }
      setRefresh(r => r + 1);
    } catch (err) { if (request === detailRequest.current) setError(message(err)); }
    finally { tagMutation.current = false; setSavingTags(false); }
  }
  async function createTag() {
    if (!tagName.trim() || tagMutation.current) return;
    const name = tagName.trim();
    const selected = detail;
    const request = detailRequest.current;
    tagMutation.current = true; setSavingTags(true);
    try {
      await api.createTag(name);
      if (selected) {
        const updated = await api.setLibraryShotTags(selected.id, [...selected.manual_tags, name]);
        if (request === detailRequest.current) setDetail(updated);
      }
      if (request === detailRequest.current) setTagName("");
      setRefresh(r => r + 1);
    } catch (err) { if (request === detailRequest.current) setError(message(err)); }
    finally { tagMutation.current = false; setSavingTags(false); }
  }
  async function exportRecipe() {
    if (!detail) return;
    try {
      const exported = await api.exportLibraryRecipe(detail.id);
      setNotice(`制作建议已导出: ${exported.path}`);
    } catch (err) { setError(message(err)); }
  }
  function openVideo(mode: LibraryPlayback["mode"], time = mode === "shot" ? detail?.start_time ?? 0 : 0) {
    const request = { mode, time };
    setPlayback(request);
    if (video.current && video.current.readyState >= 1) applyPlayback(video.current, request);
  }
  return <section className="library-view">
    <h2>参考库</h2>
    <div className="library-search card"><input aria-label="关键词" className="search-input" value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索镜头、运动、OCR 文字…" /><button onClick={() => setRefresh(r => r + 1)}>搜索</button><span role="status">{loading ? "搜索中…" : `${shots.length} 个镜头`}</span></div>
    {error && <div role="alert" className="error-box">{error}</div>}
    <div className="library-layout">
      <aside className="library-sidebar card">
        <h3>筛选</h3>
        <label>Source Video<select aria-label="Source Video" value={source} onChange={e => setSource(e.target.value)}><option value="">全部来源</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label>Motion<select aria-label="Motion" value={motion} onChange={e => setMotion(e.target.value)}><option value="">全部运动</option>{motionTypes.map(t => <option key={t}>{t}</option>)}</select></label>
        <label>Typography<select aria-label="Typography" value={hasText} onChange={e => setHasText(e.target.value)}><option value="">全部</option><option value="yes">有文字</option><option value="no">无文字</option></select></label>
        <fieldset><legend>Duration (s)</legend><input aria-label="最短时长" type="number" min="0" step="0.1" placeholder="最短" value={minDuration} onChange={e => setMinDuration(e.target.value)} /><input aria-label="最长时长" type="number" min="0" step="0.1" placeholder="最长" value={maxDuration} onChange={e => setMaxDuration(e.target.value)} /></fieldset>
        <fieldset><legend>Motion Confidence (0–1)</legend><input aria-label="最低置信度" type="number" min="0" max="1" step="0.05" placeholder="最低" value={minConfidence} onChange={e => setMinConfidence(e.target.value)} /><input aria-label="最高置信度" type="number" min="0" max="1" step="0.05" placeholder="最高" value={maxConfidence} onChange={e => setMaxConfidence(e.target.value)} /></fieldset>
        <h3>标签（全部匹配）</h3>
        <div className="filter-group">{tags.map(t => <span key={t.id}><button className={selectedTags.includes(t.name) ? "active" : ""} onClick={() => setSelectedTags(prev => prev.includes(t.name) ? prev.filter(n => n !== t.name) : [...prev, t.name])}>{t.name}</button><button aria-label={`删除标签 ${t.name}`} onClick={async () => {
          if (!confirm(`删除标签 ${t.name} 及其关联？自动标签会在重新分析时生成。`)) return;
          try { await api.deleteTag(t.id); setSelectedTags(prev => prev.filter(n => n !== t.name)); setRefresh(r => r + 1); if (detail) await inspect(detail.id); } catch (err) { setError(message(err)); }
        }}>×</button></span>)}</div>
        <h3>来源项目</h3><ul className="project-list">{projects.map(p => <li key={p.id}><button className="project-button" onClick={() => setSource(String(p.id))}><strong>{p.name}</strong><span>{p.video_filename}</span></button><button aria-label={`删除项目 ${p.name}`} className="delete-button" onClick={() => deleteProject(p.id)}>×</button></li>)}</ul>
      </aside>
      <div className="library-main"><div className="shot-grid">
        {shots.length === 0 && !loading && <p className="empty">没有匹配的镜头</p>}
        {shots.map(s => <button key={s.id} className={`shot-card ${detail?.id === s.id ? "selected" : ""}`} onClick={() => inspect(s.id)}><div className="shot-card-header"><strong>{s.shot_id}</strong><span>{s.duration.toFixed(2)}s</span></div>{s.thumbnail_path && <img src={api.libraryThumbnailUrl(s.id)} alt={`${s.shot_id} 缩略图`} loading="lazy" />}<div className="shot-card-meta"><span>{labelValue('motion',s.motion_type)} · {s.motion_confidence.toFixed(2)}</span>{s.has_text && <span className="badge">文字</span>}</div><div className="shot-card-tags">{s.tags.map(t => <span key={t} className="tag-chip">{t}</span>)}</div></button>)}
      </div><nav aria-label="搜索分页" className="library-pagination"><button disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>上一页</button><span>第 {Math.floor(offset / PAGE_SIZE) + 1} 页</span><button disabled={shots.length < PAGE_SIZE || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>下一页</button></nav></div>
      <aside className="library-inspector card"><h3>镜头详情</h3>
        {!detail ? <p className="empty">选择一个镜头 查看详情</p> : <>
          <h4>{detail.shot_id} · {detail.start_time.toFixed(3)}–{detail.end_time.toFixed(3)}s</h4><p>{detail.source.video_filename}</p>
          <div className="inspector-actions"><button onClick={() => openVideo("shot")}>播放镜头</button><button onClick={() => openVideo("source")}>打开源视频</button><button onClick={async () => { try { await navigator.clipboard.writeText(`${detail.source.video_filename} ${detail.start_time.toFixed(3)}s–${detail.end_time.toFixed(3)}s`); setNotice("时间码 已复制"); } catch (err) { setError(message(err)); } }}>复制时间码</button><button onClick={exportRecipe}>导出制作建议</button><button disabled={busy} onClick={() => loadProject(detail.project_id)}>载入分析工作区</button></div>
          {playback && <video key={detail.id} ref={video} controls src={api.librarySourceUrl(detail.id)}
            onLoadedMetadata={e => applyPlayback(e.currentTarget, playback)}
            onTimeUpdate={e => { if (playback.mode === "shot" && e.currentTarget.currentTime >= detail.end_time) e.currentTarget.pause(); }}
            onError={() => setError("源视频无法打开。请检查文件是否已移动、被替换，或编码是否受支持。")} />}
          {notice && <p role="status">{notice}</p>}
          <h4>自动标签</h4><div className="shot-card-tags">{detail.automatic_tags.map(t => <span key={t} className="tag-chip">{t}</span>)}</div>
          <h4>手动标签</h4><div className="shot-card-tags">{detail.manual_tags.map(t => <button key={t} disabled={savingTags} onClick={() => updateTags(detail.manual_tags.filter(n => n !== t))}>{t} ×</button>)}</div>
          <div className="tag-editor"><input aria-label="新增手动标签" disabled={savingTags} value={tagName} onChange={e => setTagName(e.target.value)} placeholder="新增手动标签" onKeyDown={e => { if (e.key === "Enter") void createTag(); }} /><button disabled={savingTags} onClick={createTag}>添加</button></div>
          <h4>切镜节奏</h4><CutRhythmView rhythm={detail.rhythm} />
          <h4>画面观察</h4>{(detail.provider_versions.vision as {provider?:string}|undefined)?.provider==='disabled'&&<p className='muted'>基础分析已省略视觉、OCR 和排版语义模型</p>}<AnalysisFields value={detail.observations}/>
          <details open><summary>运动分析</summary><MotionTrajectoryView measured={detail.measured_motion} shotStart={detail.start_time} shotEnd={detail.end_time}/><AnalysisFields value={{semantic:detail.motion,measured:detail.measured_motion,summary:detail.motion_summary}}/></details>
          <details open><summary>文字与排版分析</summary>{detail.typography_tracks.map(t => <div key={t.track_id}><strong>{t.canonical_text}</strong><p>{labelValue('motion',t.movement)} / {labelValue('appearance',t.appearance)} · {t.frame_count} 帧</p><p>{labelValue('role',t.typography_analysis?.role)} · {labelValue('style',t.typography_analysis?.style_family)} · {labelValue('color',t.typography_analysis?.dominant_color)}</p><p>画面观察: {t.typography_analysis?.observations.join("; ") || "暂无"}</p><p>AE 实现推测: {t.typography_analysis?.ae_hypothesis.join("; ") || "暂无"}</p></div>)}</details>
          <details><summary>AE 实现推测（实现推测）</summary><AnalysisFields value={detail.ae_hypothesis}/></details><details><summary>AE 制作建议</summary><p>根据成片推测，仅供制作参考</p><AnimationPlanView key={detail.id} plan={detail.ae_recipe?.animation_plan} geometry={detail.measured_motion} onSeekSource={time => openVideo("frame", time)} onExportAe={padded => api.exportLibraryAe(detail.id,padded)}/><AnalysisFields value={detail.ae_recipe}/></details><details><summary>源素材技术信息</summary><pre>{JSON.stringify({ source: detail.source, analysis_version: detail.analysis_version, pipeline_version: detail.pipeline_version, providers: detail.provider_versions }, null, 2)}</pre></details>
        </>}
        {!detail && <div className="tag-editor"><input aria-label="创建标签" disabled={savingTags} value={tagName} onChange={e => setTagName(e.target.value)} placeholder="创建标签" /><button disabled={savingTags} onClick={createTag}>创建</button></div>}
      </aside>
    </div>
  </section>;
}
