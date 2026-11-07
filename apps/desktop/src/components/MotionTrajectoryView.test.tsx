import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';
import type { MeasuredMotion, MotionSample } from '../services/api';
import { MotionTrajectoryView } from './MotionTrajectoryView';

function sample(source_time: number, patch: Partial<MotionSample> = {}): MotionSample {
  return {source_time, segment_id: 0, segment_start_time: 10, translation_x_ratio: 0,
    translation_y_ratio: 0, scale_ratio: 1, rotation_deg: 0, ...patch};
}
function measured(trajectory: MotionSample[]): MeasuredMotion {
  return {status: 'ok', trajectory_status: 'complete', translation_reference: 'frame_center', trajectory};
}

test('a returning pan retains its excursion and actual sample timing', () => {
  const {container} = render(<MotionTrajectoryView shotStart={10} shotEnd={12.5} measured={measured([
    sample(10), sample(10.25, {translation_x_ratio: .1}), sample(12),
  ])}/>);
  expect(screen.getByText('变化范围：0.00–10.00 画面宽度（%）')).toBeTruthy();
  expect(screen.getByRole('img', {name: /横轴为源视频时间（秒）/})).toBeTruthy();
  const points = container.querySelector('polyline')!.getAttribute('points')!.split(' ').map(p => p.split(',').map(Number));
  expect(points[0][1]).toBe(points[2][1]);
  expect(points[1][1]).toBeLessThan(points[0][1]);
  // The peak occurs 0.25s into a 2s sampled span, not at the middle sample index.
  expect((points[1][0] - points[0][0]) / (points[2][0] - points[0][0])).toBeCloseTo(.125);
  expect(screen.getByText(/采样范围 10.000–12.000 秒 · 3 个有效点 · 1 段/)).toBeTruthy();
  expect(screen.getByText(/镜头范围 10.000–12.500 秒/)).toBeTruthy();
});

test('metric controls display height percentages, scale baseline and rotation degrees', async () => {
  render(<MotionTrajectoryView measured={measured([
    sample(10), sample(11, {translation_y_ratio: -.05, scale_ratio: 1.1, rotation_deg: -3}),
  ])}/>);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', {name: '垂直位移'}));
  expect(screen.getByText('变化范围：-5.00–0.00 画面高度（%）')).toBeTruthy();
  await user.click(screen.getByRole('button', {name: '缩放'}));
  expect(screen.getByText('变化范围：100.00–110.00 缩放（%）')).toBeTruthy();
  expect(screen.getByRole('button', {name: '缩放'}).getAttribute('aria-pressed')).toBe('true');
  await user.click(screen.getByRole('button', {name: '旋转'}));
  expect(screen.getByText('变化范围：-3.00–0.00 角度（°）')).toBeTruthy();
});

test('separate tracking segments never draw across their missing interval', () => {
  const motion = measured([
    sample(10), sample(11, {translation_x_ratio: .03}),
    sample(13, {segment_id: 1, segment_start_time: 13}),
    sample(14, {segment_id: 1, segment_start_time: 13, translation_x_ratio: -.02}),
  ]);
  motion.status = 'incomplete_tracking';
  motion.trajectory_status = 'partial';
  const {container} = render(<MotionTrajectoryView measured={motion}/>);
  const paths = Array.from(container.querySelectorAll('polyline'));
  expect(paths).toHaveLength(2);
  expect(paths.every(path => path.getAttribute('points')!.split(' ').length === 2)).toBe(true);
  const xEnds = paths.map(path => path.getAttribute('points')!.split(' ').map(point => Number(point.split(',')[0])));
  expect(xEnds[0][1]).toBeLessThan(xEnds[1][0]);
  expect(screen.getByText(/每段以该段首帧为参考，缺口不连接/)).toBeTruthy();
  expect(screen.getByText(/4 个有效点 · 2 段/)).toBeTruthy();
});

test('invalid values break a curve instead of joining the surrounding samples', () => {
  const {container} = render(<MotionTrajectoryView measured={measured([
    sample(10), sample(11, {translation_x_ratio: Number.NaN}), sample(12, {translation_x_ratio: .1}),
  ])}/>);
  expect(container.querySelectorAll('polyline')).toHaveLength(0);
  expect(container.querySelectorAll('circle')).toHaveLength(2);
  expect(screen.getByText(/已忽略 1 个无效、越界或乱序采样点/)).toBeTruthy();
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
});

test('out of order and out of shot samples are excluded without bridging', () => {
  const {container} = render(<MotionTrajectoryView shotStart={10} shotEnd={12} measured={measured([
    sample(10), sample(9, {segment_start_time: 9}), sample(11), sample(13),
  ])}/>);
  expect(container.querySelectorAll('polyline')).toHaveLength(0);
  expect(screen.getByText(/已忽略 2 个无效、越界或乱序采样点/)).toBeTruthy();
  expect(screen.getByText(/采样范围 10.000–11.000 秒/)).toBeTruthy();
});

test('single samples do not claim that movement can be determined', () => {
  const {container} = render(<MotionTrajectoryView measured={measured([sample(10.5)])}/>);
  expect(screen.getByText('仅有 1 个有效采样点，不能判断运动变化。')).toBeTruthy();
  expect(container.querySelectorAll('polyline')).toHaveLength(0);
  expect(container.querySelectorAll('circle')).toHaveLength(1);
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
});

test('legacy measurements without trajectories keep an explicit recovery path', () => {
  render(<MotionTrajectoryView measured={{status: 'ok', translation_x_px: 20}}/>);
  expect(screen.getByText(/此记录未保存可绘制的运动轨迹/)).toBeTruthy();
  expect(screen.queryByRole('img')).toBeNull();
});

test('entirely malformed trajectories cannot produce invalid SVG', () => {
  const {container} = render(<MotionTrajectoryView measured={measured([
    null as unknown as MotionSample,
    sample(Number.POSITIVE_INFINITY), sample(10, {translation_x_ratio: Number.MAX_VALUE}),
  ])}/>);
  expect(screen.getByText(/没有有效的轨迹数值/)).toBeTruthy();
  expect(screen.queryByRole('img')).toBeNull();
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
});
