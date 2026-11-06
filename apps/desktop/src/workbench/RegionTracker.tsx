import { useRef, useState, type PointerEvent } from 'react';
import { api } from '../services/api';
import { isRegionFrame, type RegionBox, type RegionFrame, type RegionResult } from './regionTypes';
import { RegionPointReview } from './RegionPointReview';
import { regionError, TwoPinControls } from './TwoPinControls';
import './regionTracker.css';

type Props = { shotId: string; libraryId?: number | null; source: string; start: number; end: number; playhead: number };
type Point = {x: number; y: number};
const defaultBox = {x: .25, y: .25, width: .5, height: .5};
const labels = {x: '左边位置', y: '顶部位置', width: '框宽', height: '框高'} as const;
const reasons: Record<string, string> = {
  complete: '已跟踪到选区末端', no_frames: '范围内没有可用帧', anchor_mismatch: '首帧与框选画面不匹配',
  box_too_small: '选框太小', insufficient_texture: '框内缺少可辨认的纹理', no_match: '图案已不可辨认',
  ambiguous: '画面出现多个相似图案', abrupt_change: '位置变化过大', geometry_changed: '画幅发生变化', time_gap: '采样时间中断',
};

function BoxOverlay({box, pin}: {box: RegionBox; pin?: 'A' | 'B'}) {
  return <span className={`roi-box${pin ? ' roi-box-'+pin : ''}`} data-pin={pin}
    aria-label={pin ? `标记 ${pin} 的初始框` : undefined}
    style={{left:`${box.x * 100}%`, top:`${box.y * 100}%`, width:`${box.width * 100}%`, height:`${box.height * 100}%`}}/>;
}

function point(event: PointerEvent<HTMLDivElement>): Point | null {
  const rect = event.currentTarget.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const unit = (value: number) => Math.max(0, Math.min(1, value));
  return {x: unit((event.clientX - rect.left) / rect.width), y: unit((event.clientY - rect.top) / rect.height)};
}

function RegionForm({shotId, libraryId, source, start, end, playhead}: Props) {
  const initialTime = playhead >= start && playhead < end ? playhead : start;
  const [time, setTime] = useState(String(initialTime));
  const [until, setUntil] = useState(String(Math.min(end, initialTime + 5)));
  const [frame, setFrame] = useState<RegionFrame | null>(null);
  const [box, setBox] = useState<RegionBox>(defaultBox);
  const [result, setResult] = useState<RegionResult | null>(null);
  const [pinA, setPinA] = useState<{box: RegionBox; result: RegionResult} | null>(null);
  const [error, setError] = useState(''), [path, setPath] = useState('');
  const [busy, setBusy] = useState<'' | 'frame' | 'track' | 'export' | 'pair'>('');
  const [loaded, setLoaded] = useState(false);
  const drag = useRef<{pointer: number; origin: Point; before: RegionBox} | null>(null);
  const pendingReview = useRef(Promise.resolve());
  const validTime = time.trim() !== '' && Number(time) >= start && Number(time) < end;
  const validEnd = frame && until.trim() !== '' && Number(until) > frame.source_time &&
    Number(until) <= end && Number(until) - frame.source_time <= 30;
  const validBox = Object.values(box).every(Number.isFinite) && box.x >= 0 && box.y >= 0 &&
    box.width > 0 && box.height > 0 && box.x + box.width <= 1 + 1e-12 && box.y + box.height <= 1 + 1e-12;

  function resetResult() { setResult(null); setPath(''); setError(''); }
  function changeTime(value: string) { setTime(value); setFrame(null); setLoaded(false); resetResult(); }
  function changeBox(value: RegionBox) { setBox(value); resetResult(); }
  function pinFirst() {
    if (!result || result.track.samples.length < 2 || busy) return;
    setPinA({box, result});
    changeBox({...box, width: 0, height: 0});
  }
  function restoreFirst() {
    if (!pinA || busy) return;
    setBox(pinA.box); setResult(pinA.result); setPinA(null); setError(''); setPath('');
  }
  function expired() {
    if (pinA) setBox(pinA.box);
    setPinA(null); resetResult(); setError('跟踪记录已失效，请重新计算 A 和 B。');
  }
  const distinctB = !pinA ||
    Math.min(box.x + box.width, pinA.box.x + pinA.box.width) - Math.max(box.x, pinA.box.x) <= 1e-12 ||
    Math.min(box.y + box.height, pinA.box.y + pinA.box.height) - Math.max(box.y, pinA.box.y) <= 1e-12;
  async function freeze() {
    if (busy || pinA || !validTime) return;
    setBusy('frame'); resetResult(); setFrame(null); setLoaded(false);
    try {
      await pendingReview.current;
      const image = await api.regionFrame(shotId, source, Number(time), libraryId);
      if (!isRegionFrame(image, source) || image.source_time < start || image.source_time >= end)
        throw Error('返回的画面与当前镜头不匹配，请重新取帧');
      setFrame(image); setBox(defaultBox);
      setUntil(String(Math.min(end, image.source_time + 5)));
    } catch (e) { setError(regionError(e)); }
    finally { setBusy(''); }
  }
  function dragBox(event: PointerEvent<HTMLDivElement>) {
    const active = drag.current;
    if (!active || event.pointerId !== active.pointer) return;
    const p = point(event); if (!p) return;
    const {x, y} = active.origin;
    changeBox({x: Math.min(x, p.x), y: Math.min(y, p.y), width: Math.abs(x - p.x), height: Math.abs(y - p.y)});
  }
  async function run() {
    if (!frame || !loaded || !validEnd || !validBox || !distinctB || busy) return;
    setBusy('track'); resetResult();
    try {
      await pendingReview.current;
      const value = await api.trackRegion(shotId, {identity: source, anchor_time: frame.source_time, end_time: Number(until), box}, libraryId);
      if (value.track.frame_width !== frame.frame_width || value.track.frame_height !== frame.frame_height) {
        if (value.track.samples.length) throw Error('跟踪结果与框选画幅不一致，请重新取帧');
      }
      if (value.track.samples.some((sample, i, list) =>
        !Number.isFinite(sample.source_time) || (i === 0 ? Math.abs(sample.source_time - frame.source_time) > 1e-9 : sample.source_time <= list[i-1].source_time) ||
        sample.source_time >= Number(until) || !Number.isFinite(sample.center_x_px) || !Number.isFinite(sample.center_y_px))) {
        throw Error('跟踪结果与当前时间范围不一致，请重新取帧');
      }
      setResult(value);
    } catch (e) { setError(regionError(e)); }
    finally { setBusy(''); }
  }
  async function exportNull(single: RegionResult) {
    if (!single || busy || single.track.samples.length < 2) return;
    setBusy('export'); setPath(''); setError('');
    try { await pendingReview.current; setPath((await api.exportRegionAe(shotId, single.track_id, source, libraryId)).path); }
    catch (e) {
      if (pinA && e instanceof Error && /^HTTP 404:/.test(e.message)) expired();
      else setError(regionError(e));
    }
    finally { setBusy(''); }
  }
  const samples = result?.track.samples ?? [];
  return <div className="roi-form">
    <p>在定帧图上框住一个清晰图案，逐帧对照它的中心位置。可把确认的轨迹导出为 AE 的二维空对象。</p>
    <label>定帧源时间（秒）<input type="number" min={start} max={end} step="any" value={time} disabled={!!busy || !!pinA} onChange={e => changeTime(e.target.value)}/></label>
    <button disabled={!!busy || !!pinA || playhead < start || playhead >= end} onClick={() => changeTime(String(playhead))}>使用播放头时间</button>
    <button disabled={!!busy || !!pinA || !validTime} onClick={() => void freeze()}>{busy === 'frame' ? '正在取帧…' : '读取定帧图'}</button>
    {frame && <>
      <p>初始框选图 · 源片 {frame.source_time.toFixed(4)} 秒 · {frame.frame_width} × {frame.frame_height}。拖动框选，或用下方百分比输入框调整。</p>
      {pinA && <div className="roi-pinned"><strong>A 已固定</strong> · 在同一图案上另框一个清晰细节作为 B。尽量拉开两点距离。
        <p><button type="button" disabled={!!busy} onClick={restoreFirst}>返回 A 单框</button>
          <button type="button" disabled={!!busy} onClick={() => void exportNull(pinA.result)}>导出 A 的位置 JSX</button></p>
      </div>}
      <div className="roi-picture" aria-label="区域跟踪定帧图" style={{aspectRatio: `${frame.frame_width} / ${frame.frame_height}`,
        width: `min(100%, ${48 * frame.frame_width / frame.frame_height}vh)`}}
        onPointerDown={e => {
          if (busy || !loaded || e.button !== 0 || drag.current) return;
          const p = point(e); if (!p) return;
          e.currentTarget.setPointerCapture(e.pointerId); drag.current = {pointer: e.pointerId, origin: p, before: box};
        }}
        onPointerMove={dragBox}
        onPointerUp={e => { if (drag.current?.pointer === e.pointerId) { dragBox(e); drag.current = null; } }}
        onLostPointerCapture={e => { if (drag.current?.pointer === e.pointerId) { setBox(drag.current.before); drag.current = null; } }}>
        <img src={frame.image_data_url} alt="框选所用的源视频定帧" draggable={false} onLoad={() => setLoaded(true)}
          onError={() => { setLoaded(false); setError('定帧图无法显示，请重新取帧'); }}/>
        {pinA && <BoxOverlay box={pinA.box} pin="A"/>}
        {validBox && <BoxOverlay box={box} pin={pinA ? 'B' : undefined}/>}
        {samples.length > 1 && <svg aria-label="已确认的图案中心轨迹" viewBox={`0 0 ${frame.frame_width} ${frame.frame_height}`}><polyline
          points={samples.map(s => `${s.center_x_px},${s.center_y_px}`).join(' ')} fill="none" stroke="#ffd447" strokeWidth="2.5" vectorEffect="non-scaling-stroke"/></svg>}
      </div>
      <fieldset disabled={!!busy || !loaded}><legend>区域位置（占画幅百分比）</legend>
        {(Object.keys(labels) as (keyof RegionBox)[]).map(k => <label key={k}>{labels[k]}（%）<input type="number" min="0" max="100" step="any"
          value={Number.isFinite(box[k]) ? Number((box[k] * 100).toFixed(6)) : ''} onChange={e => changeBox({...box, [k]: e.target.valueAsNumber / 100})}/></label>)}
      </fieldset>
      <label>跟踪至源时间（秒）<input type="number" step="any" value={until} disabled={!!busy || !!pinA} onChange={e => { setUntil(e.target.value); resetResult(); }}/></label>
      {!validBox && <p>选框需要有宽度和高度，并完整落在画幅内。</p>}
      {!validEnd && <p>结束时间须在定帧之后、当前镜头内，最多跟踪 30 秒。</p>}
      {pinA && validBox && !distinctB && <p>B 的框与 A 重叠，请改选旁边的另一处细节。</p>}
      <button disabled={!!busy || !loaded || !validBox || !validEnd || !distinctB} onClick={() => void run()}>{busy === 'track' ? '正在跟踪…' : pinA ? '跟踪 B 区域' : '跟踪此区域'}</button>
    </>}
    {result && <div role="status"><strong>{reasons[result.track.status] ?? '跟踪结束'}</strong>
      <p>{samples.length ? `已确认 ${samples.length} 个位置：源片 ${samples[0].source_time.toFixed(4)} 至 ${samples[samples.length-1].source_time.toFixed(4)} 秒。` : '没有已确认的位置。'}
        {result.track.stop_time != null && ` 首次未确认位置：${result.track.stop_time.toFixed(4)} 秒。`}</p>
      {samples.length >= 2 && <button disabled={!!busy} onClick={() => void exportNull(result)}>{busy === 'export' ? '正在导出…' : pinA ? '导出 B 的位置 JSX' : '导出 AE 空对象 JSX'}</button>}
      {!pinA && samples.length >= 2 && <button type="button" disabled={!!busy} onClick={pinFirst}>设为 A，添加第二点</button>}
    </div>}
    {result && frame && <RegionPointReview key={result.track_id} shotId={shotId} libraryId={libraryId} source={source}
      anchor={frame} result={result} end={Number(until)} disabled={!!busy} pending={pendingReview}/>}
    {pinA && result && samples.length >= 2 && <TwoPinControls key={JSON.stringify([pinA.result.track_id, result.track_id])}
      shotId={shotId} source={source} libraryId={libraryId} a={pinA.result} b={result} end={Number(until)} disabled={!!busy}
      setWorking={on => setBusy(on ? 'pair' : '')} pending={pendingReview} onExpired={expired}/>}
    {error && <p role="alert">{error}</p>}{path && <p role="status">已导出至 <code>{path}</code>。在 AE 中运行后，会新建含位置关键帧的独立合成。</p>}
  </div>;
}

function RegionTool(props: Props) {
  const [open, setOpen] = useState(false);
  return <section className="detail-section"><h3>区域位置跟踪</h3>
    {!/^[a-f\d]{64}$/i.test(props.source) ? <p>缺少可核对的素材标识，请重新导入原视频后跟踪。</p>
      : <><button aria-expanded={open} onClick={() => setOpen(!open)}>{open ? '收起区域跟踪' : '框选图案并跟踪'}</button>
        {open && <RegionForm {...props}/>}</>}
  </section>;
}

export function RegionTracker(props: Props) {
  return <RegionTool key={JSON.stringify([props.source, props.shotId, props.libraryId, props.start, props.end])} {...props}/>;
}
