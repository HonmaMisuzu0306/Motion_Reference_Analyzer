import { globalTotalsUnavailable } from '../i18n/labels';
import { useState } from 'react';
import type { MeasuredMotion, MotionSample } from '../services/api';
import './MotionTrajectoryView.css';

const metrics = {
  translation_x_ratio: { label: '水平位移', unit: '画面宽度（%）', factor: 100, baseline: 0 },
  translation_y_ratio: { label: '垂直位移', unit: '画面高度（%）', factor: 100, baseline: 0 },
  scale_ratio: { label: '缩放', unit: '缩放（%）', factor: 100, baseline: 100 },
  rotation_deg: { label: '旋转', unit: '角度（°）', factor: 1, baseline: 0 },
};
type Metric = keyof typeof metrics;
type Point = { time: number; value: number; segment: number; origin: number };
type Props = { measured?: MeasuredMotion | null; shotStart?: number; shotEnd?: number };
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const format = (value: number, digits = 2) => Math.abs(value) >= 1e6 ? value.toExponential(0) : value.toFixed(digits);

function segments(samples: MotionSample[], metric: Metric, shotStart?: number, shotEnd?: number) {
  const lines: Point[][] = [];
  let active: Point[] | null = null;
  let previousTime = -Infinity;
  let omitted = 0;
  for (const sample of samples) {
    const value = sample && sample[metric] * metrics[metric].factor;
    if (!sample || !finite(sample.source_time) || sample.source_time < 0 ||
        !finite(sample.segment_id) || !Number.isInteger(sample.segment_id) || sample.segment_id < 0 ||
        !finite(sample.segment_start_time) || sample.segment_start_time < 0 ||
        sample.segment_start_time > sample.source_time || !finite(sample[metric]) || !finite(value) ||
        (metric === 'scale_ratio' && sample.scale_ratio <= 0) || sample.source_time <= previousTime ||
        (finite(shotStart) && sample.source_time < shotStart) ||
        (finite(shotEnd) && sample.source_time > shotEnd)) {
      active = null;
      omitted++;
      continue;
    }
    if (!active || active[0].segment !== sample.segment_id || active[0].origin !== sample.segment_start_time) {
      active = [];
      lines.push(active);
    }
    active.push({time: sample.source_time, value, segment: sample.segment_id, origin: sample.segment_start_time});
    previousTime = sample.source_time;
  }
  return {lines, omitted};
}

export function MotionTrajectoryView({measured, shotStart, shotEnd}: Props) {
  const [metric, setMetric] = useState<Metric>('translation_x_ratio');
  const raw = Array.isArray(measured?.trajectory) ? measured.trajectory : [];
  if (!raw.length) return <div className="motion-trajectory motion-trajectory-empty">
    <h4>运动轨迹</h4>
    <p className="muted">{measured && globalTotalsUnavailable(measured)
      ? '未获得可绘制的全局轨迹。'
      : '此记录未保存可绘制的运动轨迹。可重新分析以获取采样轨迹。'}</p>
  </div>;

  const {lines, omitted} = segments(raw, metric, shotStart, shotEnd);
  const points = lines.flat();
  const meta = metrics[metric];
  const partial = measured?.trajectory_status === 'partial' || measured?.status === 'incomplete_tracking' || lines.length > 1 || omitted > 0;
  const first = points[0]?.time ?? 0;
  const last = points[points.length - 1]?.time ?? first;
  const min = points.reduce((current, point) => Math.min(current, point.value), Infinity);
  const max = points.reduce((current, point) => Math.max(current, point.value), -Infinity);
  const domainMin = Math.min(min, meta.baseline);
  const domainMax = Math.max(max, meta.baseline);
  // Normalize first so extremely large legacy values cannot overflow SVG coordinates.
  const magnitude = Math.max(Math.abs(domainMin), Math.abs(domainMax), 1);
  const low = domainMin / magnitude, high = domainMax / magnitude;
  const x = (time: number) => last > first ? 66 + (time - first) / (last - first) * 314 : 223;
  const y = (value: number) => high > low ? 160 - (value / magnitude - low) / (high - low) * 124 : 98;
  const ticks = high > low ? [domainMin, (low + (high - low) / 2) * magnitude, domainMax] : [domainMin];
  const hasRange = finite(shotStart) && finite(shotEnd) && shotStart >= 0 && shotEnd > shotStart;

  return <section className="motion-trajectory" aria-label="运动轨迹">
    <div className="motion-trajectory-header"><h4>运动轨迹</h4><span className="muted">{partial ? '部分跟踪' : '采样连续'}</span></div>
    <div className="motion-trajectory-controls" role="group" aria-label="轨迹指标">
      {(Object.keys(metrics) as Metric[]).map(key => <button key={key} type="button" aria-pressed={metric === key}
        onClick={() => setMetric(key)}>{metrics[key].label}</button>)}
    </div>
    {points.length ? <>
      <p className="motion-trajectory-summary" aria-live="polite">变化范围：{format(min)}–{format(max)} {meta.unit}</p>
      <svg viewBox="0 0 400 205" role="img" aria-label={`${meta.label}轨迹；横轴为源视频时间（秒），纵轴为${meta.unit}`}>
        <title>{meta.label}随源视频时间的变化，各跟踪段独立绘制</title>
        <text className="motion-trajectory-axis-title" x="66" y="18">{meta.unit}</text>
        {ticks.map((tick, index) => <g key={index}><line className="motion-trajectory-grid" x1="66" x2="380" y1={y(tick)} y2={y(tick)}/>
          <text x="58" y={y(tick) + 4} textAnchor="end">{format(tick)}</text></g>)}
        {lines.map((line, index) => line.length > 1 ? <polyline key={index} className="motion-trajectory-line"
          aria-label={`跟踪段 ${index + 1}`} points={line.map(point => `${x(point.time).toFixed(2)},${y(point.value).toFixed(2)}`).join(' ')}>
          <title>段 {index + 1}：{format(line[0].time, 3)}–{format(line[line.length - 1].time, 3)} 秒；每段独立参考</title>
        </polyline> : <circle key={index} className="motion-trajectory-point" cx={x(line[0].time)} cy={y(line[0].value)} r="3.5">
          <title>单点：{format(line[0].time, 3)} 秒，{format(line[0].value)} {meta.unit}</title>
        </circle>)}
        <text x={x(first)} y="179" textAnchor={last > first ? 'start' : 'middle'}>{format(first, 3)}</text>
        {last > first && <text x={x(last)} y="179" textAnchor="end">{format(last, 3)}</text>}
        <text x="223" y="198" textAnchor="middle">源视频时间（秒）</text>
      </svg>
      <p className="muted">采样范围 {format(first, 3)}–{format(last, 3)} 秒 · {points.length} 个有效点 · {lines.length} 段</p>
      {hasRange && <p className="muted">镜头范围 {format(shotStart, 3)}–{format(shotEnd, 3)} 秒；曲线仅覆盖实际采样时间。</p>}
      {points.length === 1 && <p className="motion-trajectory-notice">仅有 1 个有效采样点，不能判断运动变化。</p>}
    </> : <p className="motion-trajectory-notice">没有有效的轨迹数值，无法绘图。请重新分析该镜头。</p>}
    {partial && <p className="motion-trajectory-notice">跟踪存在间断：每段以该段首帧为参考，缺口不连接，不同段不能拼成完整累计运动。</p>}
    {omitted > 0 && <p className="muted">已忽略 {omitted} 个无效、越界或乱序采样点，未跨越这些点连线。</p>}
    <p className="muted">平移参考：{measured?.translation_reference === 'frame_center' ? '画面中心' : '旧版画面左上角'}。缩放以各段首帧的 100% 为基准。</p>
  </section>;
}
