import { useId, useMemo, useState } from 'react';
import './AeMotionPreview.css';

type Key = { time: number; value: number };
type InputCurve = { property: string; unit: string; points: readonly Key[]; interpolation?: string; legacy: boolean };
type Props = {
  curves: readonly InputCurve[]; frameWidth?: number; frameHeight?: number;
  coverageStart: number; coverageEnd: number; sourceStart: number; onSeekSource?: (time: number) => void;
};

const units: Record<string, string> = {
  position_x: '画面宽度（%）', position_y: '画面高度（%）', global_scale: '缩放（%）', rotation: '角度（°）',
};

// Same static artwork as the exported CONTENT composition (fractions of the original picture).
const marks = [
  { x: .35, y: .5, width: .18, height: .24, fill: '#2e9ef0' },
  { x: .65, y: .35, width: .08, height: .12, fill: '#f7b838' },
  { x: .65, y: .65, width: .08, height: .12, fill: '#e85270' },
];

function validatedChannels(curves: readonly InputCurve[], start: number, end: number, width?: number, height?: number) {
  if (!validDimension(width) || !validDimension(height)) return null;
  const channels = new Map<string, readonly Key[]>();
  for (const curve of curves) {
    if (!Object.prototype.hasOwnProperty.call(units, curve.property) || curve.unit !== units[curve.property] || curve.legacy ||
        curve.interpolation !== 'linear' || channels.has(curve.property) || curve.points.length < 2) return null;
    const keys = curve.points;
    if (keys[0].time !== start || keys[keys.length - 1].time !== end) return null;
    if (keys.some((key, i) => !Number.isFinite(key.time) || !Number.isFinite(key.value) ||
        (i > 0 && key.time <= keys[i - 1].time) || (curve.property === 'global_scale' && key.value <= 0))) return null;
    const extent = curve.property === 'position_x' ? width : curve.property === 'position_y' ? height : Math.max(width, height);
    if (keys.some(({value}) => !Number.isFinite(Math.fround(curve.property === 'rotation'
      ? value : Math.abs(value) / 100 * extent + extent)))) return null;
    channels.set(curve.property, keys);
  }
  return channels.size ? channels : null;
}

function valueAt(keys: readonly Key[] | undefined, t: number, fallback: number) {
  if (!keys) return fallback;
  let lo = 0, hi = keys.length - 1;
  while (hi - lo > 1) {
    const mid = Math.floor((lo + hi) / 2);
    if (keys[mid].time <= t) lo = mid;
    else hi = mid;
  }
  const a = keys[lo], b = keys[hi];
  const fraction = (t - a.time) / (b.time - a.time);
  return a.value * (1 - fraction) + b.value * fraction;
}

function validDimension(value?: number): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 4 && value <= 30000;
}

export function AeMotionPreview({ curves, frameWidth, frameHeight, coverageStart, coverageEnd, sourceStart, onSeekSource }: Props) {
  const [selected, setSelected] = useState<number | null>(null);
  const clipId = useId();
  const channels = useMemo(() => validatedChannels(curves, coverageStart, coverageEnd, frameWidth, frameHeight), [curves, coverageStart, coverageEnd, frameWidth, frameHeight]);
  const keyTimes = useMemo(() => {
    const times = new Set<number>();
    channels?.forEach(keys => keys.forEach(key => times.add(key.time)));
    return Array.from(times).sort((a, b) => a - b);
  }, [channels]);
  if (!channels || !validDimension(frameWidth) || !validDimension(frameHeight) ||
      !Number.isFinite(sourceStart) || sourceStart < 0 || !Number.isFinite(coverageStart) ||
      coverageStart < 0 || !Number.isFinite(sourceStart + coverageEnd) || coverageEnd <= coverageStart) return null;

  const time = Math.max(coverageStart, Math.min(coverageEnd, selected ?? coverageStart));
  const cx = frameWidth / 2, cy = frameHeight / 2;
  const x = cx + valueAt(channels.get('position_x'), time, 0) / 100 * frameWidth;
  const y = cy + valueAt(channels.get('position_y'), time, 0) / 100 * frameHeight;
  const scale = valueAt(channels.get('global_scale'), time, 100) / 100;
  const rotation = valueAt(channels.get('rotation'), time, 0);
  if (![x, y, rotation, scale * Math.max(frameWidth, frameHeight)].every(n => Number.isFinite(Math.fround(n)))) return null;

  const transform = `translate(${x} ${y}) rotate(${rotation}) scale(${scale}) translate(${-cx} ${-cy})`;
  const sourceTime = sourceStart + time;
  return <section className="ae-motion-preview" aria-label="试作运动预览">
    <h5>试作运动预览</h5>
    <p>拖动时间查看校准标记的位置、缩放与旋转。标记使用导出脚本的线性关键帧。</p>
    <svg role="img" aria-label="AE 校准标记预览" viewBox={`0 0 ${frameWidth} ${frameHeight}`} width={frameWidth} height={frameHeight}>
      <defs><clipPath id={clipId}><rect width={frameWidth} height={frameHeight}/></clipPath></defs>
      <g clipPath={`url(#${clipId})`}><g data-motion-layer="" transform={transform} clipPath={`url(#${clipId})`}>
        {marks.map(mark => {
          const w = Math.max(4, Math.round(frameWidth * mark.width)), h = Math.max(4, Math.round(frameHeight * mark.height));
          return <rect key={mark.fill} x={frameWidth * mark.x - w / 2} y={frameHeight * mark.y - h / 2}
            width={w} height={h} fill={mark.fill}/>;
        })}
      </g></g>
    </svg>
    <label>预览时间（镜头内秒）
      <input type="range" aria-label="预览时间（镜头内秒）" aria-valuetext={`${time.toFixed(3)} 秒`}
        min={coverageStart} max={coverageEnd} step="any" value={time}
        onKeyDown={event => {
          const delta = (coverageEnd - coverageStart) * (event.shiftKey ? .1 : .01);
          const next: Record<string, number> = {
            ArrowLeft: time - delta, ArrowDown: time - delta, ArrowRight: time + delta, ArrowUp: time + delta,
            Home: coverageStart, End: coverageEnd,
          };
          if (!(event.key in next)) return;
          event.preventDefault();
          setSelected(Math.min(coverageEnd, Math.max(coverageStart, next[event.key])));
        }}
        onChange={event => { const t = event.currentTarget.valueAsNumber; if (Number.isFinite(t)) setSelected(t); }}/>
    </label>
    <div className="ae-motion-preview-steps">
      <button type="button" disabled={time <= coverageStart} onClick={() => {
        for (let i = keyTimes.length - 1; i >= 0; i--) {
          if (keyTimes[i] < time) { setSelected(keyTimes[i]); break; }
        }
      }}>上一个关键帧</button>
      <button type="button" disabled={time >= coverageEnd} onClick={() => {
        const next = keyTimes.find(key => key > time);
        if (next !== undefined) setSelected(next);
      }}>下一个关键帧</button>
    </div>
    <p className="ae-motion-preview-clock">实测覆盖 {coverageStart.toFixed(3)}–{coverageEnd.toFixed(3)} 秒 · 当前 {time.toFixed(3)} 秒</p>
    {onSeekSource && <button type="button" onClick={() => onSeekSource(sourceTime)}>查看原片 {sourceTime.toFixed(3)} 秒</button>}
  </section>;
}
