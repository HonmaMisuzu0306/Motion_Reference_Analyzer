import type { MeasuredMotion } from '../services/api';
import { labelValue, formatTrackingScore, TRACKING_SCORE_NOTE, NET_MOTION_NOTE } from '../i18n/labels';

function number(value: number | undefined, digits: number, suffix = '', factor = 1, signed = false) {
  if (value == null) return '暂无';
  const scaled = value * factor;
  if (!Number.isFinite(scaled)) return '不可用';
  return `${signed && scaled > 0 ? '+' : ''}${scaled.toFixed(digits)}${suffix}`;
}

export function MotionMeasurementSummary({ measured }: { measured: MeasuredMotion }) {
  return <>
    <p>整体缩放: {number(measured.scale_change_percent, 1, '%', 1, true)}</p>
    <p>净水平位移: {number(measured.translation_x_ratio, 2, '%', 100, true)} ({number(measured.translation_x_px, 1, 'px')})</p>
    <p>净垂直位移: {number(measured.translation_y_ratio, 2, '%', 100, true)} ({number(measured.translation_y_px, 1, 'px')})</p>
    <p className="muted">{NET_MOTION_NOTE}</p>
    <p>旋转: {number(measured.rotation_deg, 2, '°')}</p>
    <p>运动强度: {labelValue('strength', measured.motion_strength)}</p>
    <p>稳定度: {number(measured.stability, 0, '%', 100)}</p>
    {typeof measured.shake_score === 'number' && measured.shake_score > .1 && <p>抖动强度: {number(measured.shake_score, 0, '%', 100)}</p>}
    <p>跟踪评分: {formatTrackingScore(measured.confidence)}</p>
    <p className="muted">{TRACKING_SCORE_NOTE}</p>
    <p className="meta">基于 {measured.valid_pair_count ?? 0}/{measured.total_pair_count ?? 0} 有效帧对 (CV: {measured.cv_analysis_ms ?? 0}ms)</p>
  </>;
}
