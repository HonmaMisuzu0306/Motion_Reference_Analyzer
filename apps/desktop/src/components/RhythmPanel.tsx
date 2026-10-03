import { useEffect, useRef, useState } from "react";
import { api, type AudioAnalysis, type CutRhythm, type RhythmSummary, type Shot } from "../services/api";
import "./RhythmPanel.css";

const audioLabels: Record<AudioAnalysis["status"], string> = {
  pending: "尚未分析音频", ok: "节奏分析完成", no_audio: "视频无音轨",
  silent: "静音音轨", insufficient: "节拍不足", error: "音频分析失败",
};

export function CutRhythmView({ rhythm }: { rhythm?: CutRhythm }) {
  if (!rhythm || rhythm.status === "not_analyzed") return <p>尚未分析切镜节奏。</p>;
  if (rhythm.status === "not_cut") return <p>首镜头起点，不计为切镜。</p>;
  return <div className="cut-rhythm">
    {rhythm.message && <p className="rhythm-error">{rhythm.message}</p>}
    <p><strong>切镜时间：</strong>{rhythm.cut_time?.toFixed(3)}s</p>
    {rhythm.delta_ms == null ? <p>没有可用节拍，无法判断同步。</p> : <>
      <p><strong>最近节拍：</strong>{rhythm.nearest_beat?.toFixed(3)}s</p>
      <p><strong>切镜偏差：</strong>{rhythm.delta_ms >= 0 ? "+" : ""}{rhythm.delta_ms.toFixed(1)}ms
        <span className={`rhythm-badge ${rhythm.beat_sync ? "sync" : "off"}`}>{rhythm.beat_sync ? "同步" : "偏离节拍"}</span></p>
      <p>正值表示晚于节拍，负值表示早于节拍；容差 ±{rhythm.tolerance_ms}ms。</p>
    </>}
    {rhythm.nearest_onset != null && <p>最近瞬态：{rhythm.nearest_onset.toFixed(3)}s（{rhythm.onset_delta_ms?.toFixed(1)}ms）</p>}
  </div>;
}

export function RhythmPanel({ audio, summary, shots, selected, duration, source, busy, onAnalyze, onSelect, hidePlayer=false, externalPlayhead }: {
  audio?: AudioAnalysis; summary?: RhythmSummary; shots: Shot[]; selected: Shot | null;
  duration: number; source: string; busy: boolean; onAnalyze: () => void; onSelect: (shot: Shot) => void;
  hidePlayer?: boolean; externalPlayhead?: number;
}) {
  const [windowStart, setWindowStart] = useState(0);
  const [span, setSpan] = useState(30);
  const [playhead, setPlayhead] = useState(0);
  const [playbackError, setPlaybackError] = useState("");
  const player = useRef<HTMLVideoElement>(null);
  const selectedStart = selected?.time.start ?? 0;
  const total = Math.max(duration, audio?.duration ?? 0, .001);
  const start = Math.max(0, Math.min(windowStart, Math.max(0, total - Math.min(span, total))));
  const end = Math.min(total, start + span);
  const width = 1000;
  const x = (t: number) => (t - start) / (end - start) * width;
  const visible = (t: number) => t >= start && t <= end;
  const points = audio?.waveform.filter(p => visible(p.time)) ?? [];
  const maxRms = Math.max(.0001, ...(audio?.waveform.map(p => p.rms) ?? []));
  const wavePath = points.map((p, i) => `${i ? "L" : "M"}${x(p.time).toFixed(2)},${(42 - p.rms / maxRms * 30).toFixed(2)}`).join(" ");
  const visibleShots = shots.filter(s => s.time.start < end && s.time.end > start);

  useEffect(() => {
    setWindowStart(0); setPlayhead(0); setPlaybackError("");
  }, [source]);
  useEffect(() => {
    setWindowStart(Math.floor(selectedStart / span) * span);
    if (player.current && player.current.readyState >= 1) {
      player.current.pause(); player.current.currentTime = selectedStart;
    }
  }, [selectedStart, span]);

  return <section className="rhythm-panel card" aria-label="音频节奏分析">
    <div className="rhythm-header"><h2>音频节奏</h2>
      <button disabled={busy} onClick={onAnalyze}>{audio?.status === "error" ? "重试音频分析" : "重新分析音频"}</button>
    </div>
    <p role="status">{audioLabels[audio?.status ?? "pending"]}{audio?.cache_hit ? " · 已使用缓存" : ""}</p>
    {audio?.message && <p className={audio.status === "error" ? "rhythm-error" : "rhythm-note"}>{audio.message}</p>}
    {!!summary?.excluded_shot_count && <p role="alert" className="rhythm-error">{summary.excluded_shot_count} 条旧镜头的时间原点未经确认，未参与节奏统计；请重新分析视频。</p>}
    <div className="rhythm-stats">
      <div><strong>{audio?.tempo_bpm?.toFixed(1) ?? "—"}</strong><span>BPM（估计）</span></div>
      <div><strong>{audio?.beat_times.length ?? 0} / {audio?.onset_times.length ?? 0}</strong><span>节拍 / 瞬态</span></div>
      <div><strong>{summary?.sync_ratio == null ? "—" : `${(summary.sync_ratio * 100).toFixed(0)}%`}</strong><span>切镜同步率 · ±{summary?.tolerance_ms ?? 80}ms</span></div>
      <div><strong>{summary?.synced_cut_count ?? 0} / {summary?.measured_cut_count ?? 0}</strong><span>同步 / 可判断 · 共{summary?.cut_count ?? 0}次切镜</span></div>
    </div>
    <div className="rhythm-controls">
      <label>窗口开始（秒）<input aria-label="节奏窗口开始" type="number" min="0" max={total} step="1" value={start} onChange={e => setWindowStart(Number(e.target.value) || 0)} /></label>
      <label>窗口长度<select aria-label="节奏窗口长度" value={span} onChange={e => setSpan(Number(e.target.value))}><option value={30}>30秒</option><option value={60}>60秒</option><option value={Math.max(120, total)}>完整视频</option></select></label>
      <span>{start.toFixed(2)}–{end.toFixed(2)}s</span>
    </div>
    <svg preserveAspectRatio="none" viewBox="0 0 1000 120" role="img" aria-label="音量包络、节拍与瞬态时间轴" className="rhythm-timeline">
      <rect width="1000" height="120" fill="#1b1b1b" />
      <path d={wavePath} fill="none" stroke="#9cabbf" strokeWidth="1.5" />
      <line x1="0" x2="1000" y1="47" y2="47" stroke="#dce4ee" />
      {audio?.beat_times.filter(visible).map(t => <line key={`beat${t}`} x1={x(t)} x2={x(t)} y1="51" y2="78" stroke="#086fbd" strokeWidth="2"><title>节拍 {t.toFixed(3)}s</title></line>)}
      {audio?.onset_times.filter(visible).map(t => <line key={`onset${t}`} x1={x(t)} x2={x(t)} y1="85" y2="106" stroke="#8755b7" strokeWidth="1.5"><title>瞬态 {t.toFixed(3)}s</title></line>)}
      {visible(externalPlayhead??playhead) && <line x1={x(externalPlayhead??playhead)} x2={x(externalPlayhead??playhead)} y1="0" y2="120" stroke="#eea870" strokeWidth="2" />}
    </svg>
    <div className="rhythm-cuts" aria-label="镜头时间轴">
      {visibleShots.map(s => <button key={`${s.shot_id}:${s.library_id ?? ""}`} className={s.rhythm?.beat_sync === true ? "sync" : s.rhythm?.beat_sync === false ? "off" : "unknown"}
        style={{ left: `${Math.max(0, x(s.time.start)) / 10}%`, width: `${Math.max(.1, (x(Math.min(s.time.end, end)) - x(Math.max(s.time.start, start))) / 10)}%` }}
        aria-label={`选择 ${s.shot_id}，${s.time.start.toFixed(3)}秒`} title={`${s.shot_id} · ${s.time.start.toFixed(3)}s · ${s.rhythm?.delta_ms == null ? "不可判断" : `${s.rhythm.delta_ms}ms`}`}
        onClick={() => {
          if (player.current && player.current.readyState >= 1) {
            player.current.pause(); player.current.currentTime = s.time.start;
          }
          setPlayhead(s.time.start); onSelect(s);
        }}>{s.shot_id}</button>)}
    </div>
    <p className="rhythm-legend"><span>蓝：估计节拍</span><span>紫：瞬态</span><span>绿：切镜同步</span><span>橙：偏离节拍</span><span>灰：不可判断 / 首镜头</span></p>
    <p className="rhythm-note">点击镜头查看偏差并定位视频。同步仅表示时间接近，不代表作者意图；瞬态不替代节拍。</p>
    {!hidePlayer && <video key={source} ref={player} controls preload="metadata" src={api.videoSourceUrl(source)}
      onLoadedMetadata={e => { e.currentTarget.currentTime = selectedStart; }}
      onTimeUpdate={e => setPlayhead(e.currentTarget.currentTime)}
      onError={() => setPlaybackError("视频无法播放，请检查源文件或浏览器对编码的支持。节奏结果仍可查看。")} />}
    {playbackError && <p role="alert" className="rhythm-error">{playbackError}</p>}
  </section>;
}
