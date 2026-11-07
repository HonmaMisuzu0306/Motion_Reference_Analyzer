import { useId, useMemo, useState } from 'react';
import { AeMotionPreview } from './AeMotionPreview';
import './AnimationPlanView.css';

type Point = { time: number; value: number };
type Curve = { property: string; unit: string; basis: string; points: Point[]; legacy: boolean;
  interpolation?: string; tolerance?: number; sampleCount?: number };
type ExportResult = { path: string; message?: string };
type Props = { plan?: unknown; geometry?: {frame_width?: number; frame_height?: number}; onSeekSource?: (time: number) => void; onExportAe?: (padded?: boolean) => Promise<ExportResult> };
const PAGE_SIZE = 20;
const properties: Record<string, string> = { position_x: '水平位置', position_y: '垂直位置',
  global_scale: '整体缩放', character_scale: '主体缩放', rotation: '旋转' };
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const nonempty = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;
const format = (value: number, digits = 2) => Math.abs(value) >= 1e6 ? value.toExponential(2) : value.toFixed(digits);
const propertyName = (property: string) => properties[property] ?? `未识别属性（${property}）`;

function exportFailure(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const body = /^HTTP \d{3}: ([\s\S]*)$/.exec(message)?.[1];
  if (body) {
    try {
      const payload: unknown = JSON.parse(body);
      if (record(payload) && nonempty(payload.detail)) return payload.detail;
    } catch { /* Keep the original message when the server did not return JSON. */ }
  }
  return message;
}

function readCurve(value: unknown, legacy: boolean, duration?: number): Curve | null {
  if (!record(value) || !nonempty(value.property)) return null;
  const raw = legacy ? [{ time: value.start_time, value: value.from }, { time: value.end_time, value: value.to }] : value.points;
  if (!Array.isArray(raw) || !raw.length) return null;
  const points: Point[] = [];
  for (const point of raw) {
    if (!record(point) || !finite(point.time) || point.time < 0 || !finite(point.value) ||
        (duration !== undefined && point.time > duration) ||
        (points.length > 0 && point.time <= points[points.length - 1].time)) return null;
    points.push({ time: point.time, value: point.value });
  }
  return { property: value.property, unit: nonempty(value.unit) ? value.unit : '单位未记录',
    basis: nonempty(value.basis) ? value.basis : '依据未记录', points, legacy,
    interpolation: typeof value.interpolation === 'string' ? value.interpolation : undefined,
    tolerance: finite(value.tolerance) && value.tolerance > 0 ? value.tolerance : undefined,
    sampleCount: finite(value.sample_count) && Number.isInteger(value.sample_count) && value.sample_count >= points.length ? value.sample_count : undefined };
}

function artworkPaddingGuide(value: unknown) {
  if (!record(value)) return null;
  const pixels = (n: unknown): n is number => finite(n) && Number.isInteger(n) && n >= 0 && n <= 30000;
  const { left_px: left, right_px: right, top_px: top, bottom_px: bottom, width_px: width, height_px: height } = value;
  if (!pixels(left) || !pixels(right) || !pixels(top) || !pixels(bottom) || !pixels(width) || !pixels(height)) return null;
  const originalWidth = width - left - right, originalHeight = height - top - bottom;
  if (originalWidth < 4 || originalHeight < 4 || left + right + top + bottom === 0) return null;
  return <aside aria-label="素材留边建议" className="animation-curve">
    <strong>素材留边建议</strong>
    <p>按实测帧估算，左补 {left}、右补 {right}、上补 {top}、下补 {bottom} 像素。请回看帧间运动，检查是否露边。</p>
    <p>使用留边脚本时，CONTENT 尺寸和锚点均已设置。请替换为下述尺寸的静态图稿，并将原画面对齐到留边位置。</p>
    <p>手动修改原尺寸模板时，CONTENT 预合成会裁掉画布外的素材。将素材和 CONTENT 都扩到 {width} × {height} 像素，在新边缘补足画面，
      并将原画面的左上角放在 ({left}, {top})。</p>
    <p>在外层 MOTION 合成中选中 CONTENT 图层，把锚点（Anchor Point）设为 ({left + originalWidth / 2}, {top + originalHeight / 2})，
      对齐原画面中心。保留已有的位置（Position）和缩放（Scale）关键帧。</p>
  </aside>;
}

function CurveCard({ curve, onSeek }: { curve: Curve; onSeek?: (localTime: number) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [page, setPage] = useState(0);
  const tableId = useId();
  const { points, unit } = curve;
  const first = points[0], last = points[points.length - 1];
  const {min, max, line, singlePointY} = useMemo(() => {
    const min = points.reduce((n, point) => Math.min(n, point.value), Infinity);
    const max = points.reduce((n, point) => Math.max(n, point.value), -Infinity);
    const magnitude = Math.max(Math.abs(min), Math.abs(max), 1);
    const low = min / magnitude, high = max / magnitude;
    const x = (time: number) => last.time > first.time ? 14 + (time - first.time) / (last.time - first.time) * 332 : 180;
    const y = (value: number) => high > low ? 68 - (value / magnitude - low) / (high - low) * 52 : 42;
    const line = points.length > 1 ? points.map(point =>
      `${x(point.time).toFixed(2)},${y(point.value).toFixed(2)}`).join(' ') : '';
    return {min, max, line, singlePointY: y(first.value)};
  }, [points, first, last]);
  const offset = Math.min(page * PAGE_SIZE, Math.floor((points.length - 1) / PAGE_SIZE) * PAGE_SIZE);
  const label = propertyName(curve.property);
  return <article className="animation-curve" aria-label={`${label}关键帧`}>
    <div className="animation-plan-header"><strong>{label}</strong><span className="muted">{points.length} 个关键帧</span></div>
    <p className="animation-curve-range">变化范围：{format(min)}–{format(max)} {unit}</p>
    <p className="muted">起点 {format(first.value)} → 终点 {format(last.value)} · {format(first.time, 3)}–{format(last.time, 3)} 秒</p>
    {!curve.legacy && <svg viewBox="0 0 360 95" role="img" aria-label={`${label}关键帧曲线；横轴为镜头局部秒，纵轴为${unit}`}>
      <title>{label}变化范围 {format(min)}–{format(max)} {unit}；展开列表查看各点的实际时间与数值</title>
      <line className="animation-curve-axis" x1="14" x2="346" y1="68" y2="68"/>
      {points.length > 1 ? <polyline className="animation-curve-line"
        points={line}/>
        : <circle className="animation-curve-point" cx={180} cy={singlePointY} r="3"/>}
      <text x="14" y="88">{format(first.time, 3)} 秒</text>
      <text x="346" y="88" textAnchor="end">{format(last.time, 3)} 秒</text>
    </svg>}
    {points.length === 1 && <p className="animation-plan-notice">仅有单点，不能表示连续运动。</p>}
    <p className="muted">依据：{curve.basis}{!curve.legacy && ` · 插值：${curve.interpolation === 'linear' ? '线性' : '未记录'}`}</p>
    {!curve.legacy && curve.sampleCount !== undefined && <p className="muted">从 {curve.sampleCount} 个采样点保留 {points.length} 个关键帧。</p>}
    {!curve.legacy && curve.tolerance !== undefined && <p className="muted">采样点重建容差：{format(curve.tolerance)} {unit}，不代表跟踪精度。</p>}
    <button type="button" className="animation-curve-toggle" aria-expanded={expanded} aria-controls={tableId}
      onClick={() => setExpanded(!expanded)}>{expanded ? '收起' : '查看'}{label}关键帧列表</button>
    {expanded && <div id={tableId} className="animation-curve-table">
      <table><caption>{label} · 时间为镜头局部秒</caption><thead><tr><th scope="col">时间（秒）</th><th scope="col">数值 · {unit}</th></tr></thead>
        <tbody>{points.slice(offset, offset + PAGE_SIZE).map(point => <tr key={point.time}><td>{onSeek
          ? <button type="button" aria-label={`查看原片：${label}，镜头内 ${point.time} 秒`} onClick={() => onSeek(point.time)}>{String(point.time)}</button>
          : String(point.time)}</td><td>{String(point.value)}</td></tr>)}</tbody></table>
      {points.length > PAGE_SIZE && <div className="animation-curve-pages">
        <button type="button" disabled={offset === 0} aria-label={`${label}关键帧上一页`} onClick={() => setPage(Math.max(0, page - 1))}>上一页</button>
        <span aria-live="polite">{offset + 1}–{Math.min(offset + PAGE_SIZE, points.length)} / {points.length}</span>
        <button type="button" disabled={offset + PAGE_SIZE >= points.length} aria-label={`${label}关键帧下一页`} onClick={() => setPage(page + 1)}>下一页</button>
      </div>}
    </div>}
  </article>;
}

function readPlanCurves(input: unknown) {
  const plan = record(input) ? input : {};
  const start = finite(plan.source_start) && plan.source_start >= 0 ? plan.source_start : undefined;
  const end = finite(plan.source_end) && start !== undefined && plan.source_end > start ? plan.source_end : undefined;
  const duration = start !== undefined && end !== undefined ? end - start :
    finite(plan.duration) && plan.duration > 0 ? plan.duration : undefined;
  const coverage = finite(plan.coverage_start) && finite(plan.coverage_end) && plan.coverage_start >= 0 &&
    plan.coverage_end >= plan.coverage_start && (start === undefined || plan.coverage_start >= start) &&
    (end === undefined || plan.coverage_end <= end);
  // A present but corrupt curve must not silently become a straight endpoint ramp.
  const hasCurves = Array.isArray(plan.curves) ? plan.curves.length > 0 : plan.curves != null;
  const raw = hasCurves ? plan.curves : plan.keyframes;
  const parsed = Array.isArray(raw) ? raw.map(value => readCurve(value, !hasCurves, duration)) : [];
  const curves = parsed.filter((curve): curve is Curve => curve !== null);
  const invalid = parsed.length - curves.length + (raw != null && !Array.isArray(raw) ? 1 : 0);
  return {start, end, coverage, hasCurves, curves, invalid};
}

export function AnimationPlanView({ plan, geometry, onExportAe, onSeekSource }: Props) {
  const [exporting, setExporting] = useState<'standard' | 'padded' | null>(null);
  const [exportError, setExportError] = useState('');
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const data = useMemo(() => readPlanCurves(plan), [plan]);
  if (plan === undefined || plan === null) return null;
  if (!record(plan)) return <p className="animation-plan-notice">此记录的关键帧方案格式不可用，请重新分析。</p>;
  const {start, end, coverage, hasCurves, curves, invalid} = data;
  const source = plan.evidence_source;
  const sourceLabel = source === 'measured' ? '测量建议' : source === 'semantic' ? 'AI 试作假设' : source === 'insufficient' ? '证据不足' : '来源未记录';
  const notes = Array.isArray(plan.notes) ? plan.notes.filter(nonempty) : [];
  const measuredCurves = source === 'measured' && hasCurves && invalid === 0 && curves.length > 0 && curves.every(curve => curve.points.length > 1);
  const canExport = onExportAe && measuredCurves;
  const paddingGuide = source === 'measured' && hasCurves && invalid === 0 && curves.length > 0
    ? artworkPaddingGuide(plan.artwork_padding) : null;
  async function exportAe(padded = false) {
    if (!onExportAe || exporting || (padded && !paddingGuide)) return;
    setExporting(padded ? 'padded' : 'standard'); setExportError(''); setExportResult(null);
    try { setExportResult(await onExportAe(padded)); }
    catch (error) { setExportError(exportFailure(error)); }
    finally { setExporting(null); }
  }
  return <section className="animation-plan" aria-label="关键帧试作方案">
    <div className="animation-plan-header"><h4>关键帧试作方案</h4><span className="animation-plan-source">{sourceLabel}</span></div>
    {source === 'semantic' && <p className="animation-plan-notice">以下幅度是 AI 试作值，尚未被视频测量验证。</p>}
    {nonempty(plan.evidence_notice)
      ? <p className="animation-plan-notice">{plan.evidence_notice}</p>
      : source === 'measured' && <p className="muted">全局运动的复现起点，仍需对照原片调整。</p>}
    {start !== undefined && end !== undefined && <p>源视频镜头：{format(start, 3)}–{format(end, 3)} 秒</p>}
    <p className="muted">关键帧时间为镜头局部秒{start !== undefined ? `；0.000 秒对应源视频 ${format(start, 3)} 秒。` : '；源视频起点未记录。'}</p>
    {coverage ? <p>实际采样覆盖：{format(plan.coverage_start as number, 3)}–{format(plan.coverage_end as number, 3)} 秒（源视频）</p>
      : <p className="muted">实际采样覆盖时间未记录或无效。</p>}
    {!hasCurves && curves.length > 0 && <p className="animation-plan-notice">端点试作方案：未保存完整运动曲线，首尾相同也不能排除中途往返。</p>}
    {invalid > 0 && <p className="animation-plan-notice">{invalid} 个属性的关键帧数据无效或时间乱序，未绘制或替换为端点直线。</p>}
    {!curves.length && <p>暂无可用的数值关键帧。请结合下方说明检查原片或重新分析。</p>}
    {curves.map((curve, index) => <CurveCard key={`${curve.property}-${index}-${curve.points[0].time}-${curve.points.length}`} curve={curve}
      onSeek={onSeekSource && source === 'measured' && !curve.legacy && start !== undefined && end !== undefined && coverage &&
        curve.points[0].time >= (plan.coverage_start as number) - start &&
        curve.points[curve.points.length - 1].time <= (plan.coverage_end as number) - start &&
        curve.points[curve.points.length - 1].time < end - start
        ? localTime => onSeekSource(start + localTime) : undefined}/>)}
    {measuredCurves && geometry && start !== undefined && end !== undefined && coverage &&
      (plan.coverage_end as number) < end &&
      <AeMotionPreview curves={curves} frameWidth={geometry.frame_width} frameHeight={geometry.frame_height}
        coverageStart={(plan.coverage_start as number) - start} coverageEnd={(plan.coverage_end as number) - start}
        sourceStart={start} onSeekSource={onSeekSource}/>}
    {paddingGuide}
    {notes.length > 0 && <details className="animation-plan-notes"><summary>操作前提与说明（{notes.length}）</summary><ul>{notes.map((note, index) => <li key={index}>{note}</li>)}</ul></details>}
    {canExport && <div className="animation-plan-export">
      <button type="button" disabled={!!exporting} onClick={() => void exportAe()}>{exporting === 'standard' ? '正在导出…' : '导出 AE 试作脚本'}</button>
      {paddingGuide && <button type="button" disabled={!!exporting} onClick={() => void exportAe(true)}>{exporting === 'padded' ? '正在导出留边脚本…' : '导出留边 AE 试作脚本'}</button>}
      <p className="muted">脚本在 AE 中新建试作合成，用标记图层预览运动。请按方案前提替换为自己的画面。</p>
    </div>}
    {exportError && <p className="animation-plan-notice" role="alert">导出失败：{exportError}</p>}
    {exportResult && <div className="animation-plan-export-result" role="status"><p>{exportResult.message || 'AE 试作脚本已导出'}</p><p>保存位置：<code>{exportResult.path}</code></p></div>}
  </section>;
}
