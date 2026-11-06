import { useState, type MutableRefObject } from 'react';
import { api } from '../services/api';
import type { RegionResult, TwoPinResult } from './regionTypes';

type Props = { shotId: string; source: string; libraryId?: number | null; a: RegionResult; b: RegionResult;
  end: number; disabled: boolean; setWorking: (on: boolean) => void; onExpired: () => void;
  pending: MutableRefObject<Promise<void>> };

const statusText: Record<string, string> = {
  complete: '双点跟踪完成', pin_lost: '至少一个图案已失去跟踪', no_samples: '没有共同确认的位置',
  overlapping_boxes: 'A 与 B 的选框重叠', geometry_changed: '两次跟踪画幅不一致',
  anchor_mismatch: '两点首帧或初始中心不一致', time_mismatch: '两点采样时间不一致', time_gap: '采样中断',
  baseline_too_short: '两点距离太近，请重新选框并拉开距离', degenerate: '两点靠得过近，无法继续测量转角',
  angle_jump: '相邻采样点之间转角过大，方向无法确认',
};

export function regionError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  const body = /^HTTP \d+: ([\s\S]*)$/.exec(message)?.[1];
  if (body) {
    try { const data = JSON.parse(body); if (typeof data.detail === 'string') return data.detail; }
    catch { /* Non-JSON response. */ }
  }
  return message;
}

function validResult(result: TwoPinResult, a: RegionResult['track'], b: RegionResult['track'], end: number) {
  const track = result.track;
  if (!result.track_id || !track || !Array.isArray(track.samples) || track.frame_width !== a.frame_width ||
      track.frame_height !== a.frame_height || !Object.prototype.hasOwnProperty.call(statusText, track.status) ||
      track.samples.length > Math.min(a.samples.length, b.samples.length)) return false;
  const initial = [track.initial_distance_px, track.initial_vector_x_px, track.initial_vector_y_px];
  if (track.samples.length ? (!initial.every(Number.isFinite) || (track.initial_distance_px ?? 0) <= 0)
                           : !initial.every(v => v === null)) return false;
  if (!track.samples.every((s, i) =>
    [s.source_time, s.position_x_px, s.position_y_px, s.pin_b_x_px, s.pin_b_y_px, s.rotation_deg, s.scale_percent].every(Number.isFinite) &&
    Math.abs(s.source_time-a.samples[i].source_time) <= 1e-9 && Math.abs(s.source_time-b.samples[i].source_time) <= 1e-9 &&
    s.position_x_px === a.samples[i].center_x_px && s.position_y_px === a.samples[i].center_y_px &&
    s.pin_b_x_px === b.samples[i].center_x_px && s.pin_b_y_px === b.samples[i].center_y_px &&
    s.scale_percent > 0 && s.source_time < end)) return false;
  if (track.status === 'complete') return track.stop_time === null && track.samples.length > 0;
  if (track.stop_time == null) return track.stop_time === null && !track.samples.length;
  const last = track.samples[track.samples.length-1];
  return Number.isFinite(track.stop_time) && track.stop_time < end &&
    (last ? track.stop_time > last.source_time : track.stop_time >= a.samples[0].source_time);
}

export function TwoPinControls({shotId, source, libraryId, a, b, end, disabled, setWorking, onExpired, pending}: Props) {
  const [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState<TwoPinResult | null>(null);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState('');
  const [path, setPath] = useState('');
  function handleError(e: unknown) {
    if (e instanceof Error && /^HTTP 404:/.test(e.message)) onExpired();
    else setError(regionError(e));
  }
  async function measure() {
    if (!confirmed || disabled || a.track_id === b.track_id) return;
    setWorking(true); setResult(null); setError(''); setPath('');
    try {
      await pending.current;
      const value = await api.trackTwoPins(shotId, source, a.track_id, b.track_id, libraryId);
      if (!validResult(value, a.track, b.track, end)) throw Error('双点结果与当前输入不一致，请重新跟踪。');
      setResult(value); setIndex(Math.max(0, value.track.samples.length-1));
    } catch (e) { handleError(e); }
    finally { setWorking(false); }
  }
  async function exportScript() {
    if (disabled || !confirmed || !result || result.track.samples.length < 2) return;
    setWorking(true); setError(''); setPath('');
    try {
      await pending.current;
      setPath((await api.exportTwoPinAe(shotId, result.track_id, source, libraryId)).path);
    } catch (e) { handleError(e); }
    finally { setWorking(false); }
  }
  const track = result?.track;
  const s = track?.samples[index];
  return <section className="roi-pair" aria-label="双点测量">
    <label className="roi-plane-consent"><input type="checkbox" checked={confirmed} disabled={disabled}
      onChange={e => { setConfirmed(e.target.checked); setResult(null); setPath(''); setError(''); }}/>
      我确认 A、B 属于同一刚性平面图案</label>
    <button type="button" disabled={disabled || !confirmed || a.track_id === b.track_id}
      onClick={() => void measure()}>计算双点变换</button>
    {track && <div role="status">
      <strong>{statusText[track.status]}</strong>
      <p>{track.samples.length} 个共同确认的位置{track.initial_distance_px != null && ` · 初始点距 ${track.initial_distance_px.toFixed(1)} 像素`}。
        {track.stop_time != null && ` 首次停止：源片 ${track.stop_time.toFixed(4)} 秒。`}</p>
      {s && <><label>双点采样时间<select value={index} onChange={e => setIndex(Number(e.target.value))}>
        {track.samples.map((point, i) => <option key={point.source_time} value={i}>{point.source_time.toFixed(4)} 秒</option>)}
      </select></label>
      <p>A 的位置 X {s.position_x_px.toFixed(2)}，Y {s.position_y_px.toFixed(2)} 像素 · 转角 {s.rotation_deg.toFixed(2)}°（正值顺时针） · 等比缩放 {s.scale_percent.toFixed(2)}%</p></>}
      {track.samples.length >= 2 && <><p>转角按相邻实测点计算，采样之间的整圈转动无法计数。</p>
        <button type="button" onClick={() => void exportScript()} disabled={disabled}>导出双点 AE 空对象 JSX</button></>}
    </div>}
    {error && <p role="alert">{error}</p>}
    {path && <p role="status">双点脚本已导出至 <code>{path}</code>。</p>}
  </section>;
}
