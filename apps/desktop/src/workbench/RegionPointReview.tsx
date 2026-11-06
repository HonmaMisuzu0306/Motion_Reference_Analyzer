import { memo, useEffect, useMemo, useState, type MutableRefObject } from 'react';
import { api } from '../services/api';
import { isRegionFrame, type RegionFrame, type RegionResult } from './regionTypes';
import { summarizeRegionTiming } from './regionTiming';

type Sample = RegionResult['track']['samples'][number];
type ReviewProps = {
  shotId: string; libraryId?: number | null; source: string; anchor: RegionFrame;
  result: RegionResult; end: number; disabled: boolean; pending: MutableRefObject<Promise<void>>;
};

function Picture({frame, sample}: {frame: RegionFrame; sample?: Sample}) {
  const [imageState, setImageState] = useState<'loading' | 'ready' | 'error'>('loading');
  return <>
    <div className="roi-picture roi-review-picture" style={{aspectRatio: `${frame.frame_width} / ${frame.frame_height}`,
      width: `min(100%, ${48 * frame.frame_width / frame.frame_height}vh)`}}>
      <img src={frame.image_data_url} alt={sample ? '采样点对应的源视频画面' : '首个未确认位置对应的源视频画面'}
        onLoad={() => setImageState('ready')} onError={() => setImageState('error')}/>
      {imageState === 'ready' && sample && <span role="img" aria-label="实测中心" className="roi-center"
        style={{left:`${100 * sample.center_x_px / frame.frame_width}%`, top:`${100 * sample.center_y_px / frame.frame_height}%`}}/>}
    </div>
    {imageState === 'error' && <p role="alert">复核图无法显示，请重新取帧。</p>}
    <p>源片 {frame.source_time.toFixed(6)} 秒 · {sample
      ? `实测中心 X ${sample.center_x_px.toFixed(2)}，Y ${sample.center_y_px.toFixed(2)} 像素`
      : '此帧未确认图案位置。'}</p>
  </>;
}

export const RegionPointReview = memo(function RegionPointReview({shotId, libraryId, source, anchor, result, end, disabled, pending}: ReviewProps) {
  const [index, setIndex] = useState<number | null>(null);
  const [retry, setRetry] = useState(0);
  const [reply, setReply] = useState<{time: number; image?: RegionFrame; error?: string} | null>(null);
  const {samples, stop_time: stop} = result.track;
  const timing = useMemo(() => summarizeRegionTiming(samples, anchor.frame_width, anchor.frame_height),
    [samples, anchor.frame_width, anchor.frame_height]);
  const last = samples[samples.length - 1];
  const canReviewStop = stop != null && Number.isFinite(stop) && stop >= anchor.source_time &&
    stop < end && result.track.status !== 'complete' && (!last || stop > last.source_time);
  const sample = index == null ? undefined : samples[index];
  const time = index == null ? null : sample?.source_time ?? (canReviewStop ? stop : null);
  const anchorMatches = time != null && anchor.source_time === time;
  useEffect(() => {
    if (time == null || anchorMatches) return;
    let cancelled = false;
    // The backend verifies and decodes one source at a time. Skip superseded clicks
    // before decoding, and discard an already running request if selection changes.
    pending.current = pending.current.then(async () => {
      if (cancelled) return;
      try {
        const image = await api.regionFrame(shotId, source, time, libraryId);
        if (!isRegionFrame(image, source) || Math.abs(image.source_time - time) > 1e-9 ||
            image.frame_width !== anchor.frame_width || image.frame_height !== anchor.frame_height) {
          throw Error('返回的帧与选定的时间或画幅不符，请重新读取。');
        }
        if (!cancelled) setReply({time, image});
      } catch (e) {
        if (!cancelled) setReply({time, error: e instanceof Error ? e.message : String(e)});
      }
    });
    return () => { cancelled = true; };
  }, [time, retry, anchorMatches, anchor.frame_width, anchor.frame_height, shotId, source, libraryId, pending]);

  if (!samples.length && !canReviewStop) return null;
  const ready = anchorMatches ? anchor : reply?.time === time ? reply?.image : undefined;
  const error = !anchorMatches && reply?.time === time ? reply?.error : null;
  function select(next: number | null) {
    if (index !== next) { setReply(null); setIndex(next); }
  }
  return <section className="roi-review" aria-label="轨迹逐点复核">
    <button type="button" aria-expanded={index != null} disabled={disabled} onClick={() => select(index == null ? 0 : null)}>
      {index == null ? '逐点复核原片' : '收起逐点复核'}</button>
    {index != null && <>
      <p><strong>{sample ? '采样点复核图' : '首个未确认帧'}</strong></p>
      <label>复核源时间<select value={index} disabled={disabled} onChange={e => select(Number(e.target.value))}>
        {samples.map((s,i) => <option key={s.source_time} value={i}>{i+1} / {samples.length} · {s.source_time.toFixed(6)} 秒</option>)}
        {canReviewStop && <option value={samples.length}>首次未确认 · {stop.toFixed(6)} 秒</option>}
      </select></label>
      <button type="button" disabled={disabled || index === 0} onClick={() => select(index-1)}>上一采样点</button>
      <button type="button" disabled={disabled || index >= samples.length-1} onClick={() => select(index+1)}>下一采样点</button>
      {canReviewStop && <button type="button" disabled={disabled || !sample} onClick={() => select(samples.length)}>查看首个未确认帧</button>}
      {timing && <div className="roi-timing">
        <p>离初始中心最远 {timing.excursionPx.toFixed(1)} 像素。
          <button type="button" disabled={disabled} onClick={() => select(timing.farthestIndex)}>查看最大偏移点</button></p>
        <p>最快采样区间 {samples[timing.fastestStartIndex].source_time.toFixed(4)}–{samples[timing.fastestEndIndex].source_time.toFixed(4)} 秒，
          采样路径的区间平均速度为 {timing.fastestPxPerSec.toFixed(1)} 像素/秒。可对照这段画面调整 AE 的位置关键帧间距。</p>
        <button type="button" disabled={disabled} onClick={() => select(timing.fastestStartIndex)}>查看最快区间起点</button>
        <button type="button" disabled={disabled} onClick={() => select(timing.fastestEndIndex)}>查看最快区间终点</button>
        <details><summary>速度区间如何比较</summary><p>从每个采样点向前取达到 0.1 秒的最短区间，将沿途各采样点间的距离相加，再除以实际时长。整条轨迹短于 0.1 秒时使用全段。</p></details>
      </div>}
      {ready ? <Picture key={time} frame={ready} sample={sample}/> : error ? <p role="alert">{error}
        <button type="button" disabled={disabled} onClick={() => { setReply(null); setRetry(n => n + 1); }}>重新读取</button></p>
        : <p role="status">正在读取源片 {time?.toFixed(6)} 秒…</p>}
    </>}
  </section>;
});
