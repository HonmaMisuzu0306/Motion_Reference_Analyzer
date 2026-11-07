import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { AnimationPlanView } from './AnimationPlanView';

const curve = (points: {time: number; value: number}[] = [{time: .125, value: 0}, {time: .375, value: 8}, {time: 1.875, value: 0}]) => ({
  property: 'position_x', unit: '画面宽度（%）', basis: '连续全局运动测量',
  interpolation: 'linear', sample_count: Math.max(8, points.length), keyframe_count: points.length, tolerance: .1, points,
});
const plan = (patch: Record<string, unknown> = {}) => ({ evidence_source: 'measured', source_start: 12,
  source_end: 14, duration: 2, coverage_start: 12.125, coverage_end: 13.875,
  curves: [curve()], keyframes: [{property: 'position_x', unit: '画面宽度（%）', start_time: .125, end_time: 1.875, from: 0, to: 0}],
  notes: ['AE 前提：二维预合成、中心锚点。'], ...patch,
});

test('shows a returning move and real source coverage without reducing it to equal endpoints', async () => {
  const {container} = render(<AnimationPlanView plan={plan()}/>);
  expect(screen.getByText('测量建议')).toBeTruthy();
  expect(screen.getByText('实际采样覆盖：12.125–13.875 秒（源视频）')).toBeTruthy();
  expect(screen.getByText('关键帧时间为镜头局部秒；0.000 秒对应源视频 12.000 秒。')).toBeTruthy();
  expect(screen.getByText('变化范围：0.00–8.00 画面宽度（%）')).toBeTruthy();
  expect(screen.getByText(/起点 0.00 → 终点 0.00/)).toBeTruthy();
  const points = container.querySelector('polyline')!.getAttribute('points')!.split(' ').map(point => point.split(',').map(Number));
  expect(points[0][1]).toBe(points[2][1]);
  expect(points[1][1]).toBeLessThan(points[0][1]);
  expect((points[1][0] - points[0][0]) / (points[2][0] - points[0][0])).toBeCloseTo(.25 / 1.75);
  expect(screen.queryByRole('table')).toBeNull();
  await userEvent.click(screen.getByRole('button', {name: '查看水平位置关键帧列表'}));
  const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1).map(row => within(row).getAllByRole('cell').map(cell => cell.textContent));
  expect(rows).toEqual([['0.125', '0'], ['0.375', '8'], ['1.875', '0']]);
  expect(screen.getAllByRole('article')).toHaveLength(1);
  expect(screen.getByText('采样点重建容差：0.10 画面宽度（%），不代表跟踪精度。')).toBeTruthy();
});

test('long keyframe lists remain collapsed and expose every actual point through pagination', async () => {
  const points = Array.from({length: 43}, (_, index) => ({time: index / 25 + .000001, value: index === 42 ? 3.123456789 : index}));
  render(<AnimationPlanView plan={plan({curves: [curve(points)]})}/>);
  expect(screen.queryByRole('table')).toBeNull();
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', {name: '查看水平位置关键帧列表'}));
  expect(screen.getAllByRole('row')).toHaveLength(21);
  expect(screen.getByText('1–20 / 43')).toBeTruthy();
  expect(screen.getByRole('button', {name: '水平位置关键帧上一页'}).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('cell', {name: '0.000001'})).toBeTruthy();
  await user.click(screen.getByRole('button', {name: '水平位置关键帧下一页'}));
  await user.click(screen.getByRole('button', {name: '水平位置关键帧下一页'}));
  expect(screen.getByText('41–43 / 43')).toBeTruthy();
  expect(screen.getAllByRole('row')).toHaveLength(4);
  expect(screen.getByRole('cell', {name: '3.123456789'})).toBeTruthy();
  expect(screen.getByRole('button', {name: '水平位置关键帧下一页'}).hasAttribute('disabled')).toBe(true);
  await user.click(screen.getByRole('button', {name: '收起水平位置关键帧列表'}));
  expect(screen.queryByRole('table')).toBeNull();
});

test('legacy semantic endpoint plans retain units and state that intermediate motion is unknown', async () => {
  render(<AnimationPlanView plan={plan({evidence_source: 'semantic', curves: undefined, coverage_start: null, coverage_end: null,
    keyframes: [{property: 'global_scale', unit: '缩放（%）', basis: 'AI 方向判断', start_time: 0, end_time: 2, from: 100, to: 110}]})} onExportAe={vi.fn()}/>);
  expect(screen.getByText('AI 试作假设')).toBeTruthy();
  expect(screen.getByText('以下幅度是 AI 试作值，尚未被视频测量验证。')).toBeTruthy();
  expect(screen.getByText(/端点试作方案：未保存完整运动曲线/)).toBeTruthy();
  expect(screen.getByText('变化范围：100.00–110.00 缩放（%）')).toBeTruthy();
  expect(screen.queryByRole('img')).toBeNull();
  expect(screen.queryByRole('button', {name: '导出 AE 试作脚本'})).toBeNull();
  await userEvent.click(screen.getByRole('button', {name: '查看整体缩放关键帧列表'}));
  expect(screen.getByRole('cell', {name: '110'})).toBeTruthy();
});

test('malformed curves are not converted to misleading endpoint ramps or invalid SVG', () => {
  const bad = [curve([{time: 0, value: 0}, {time: 1, value: Number.NaN}]),
    curve([{time: 1, value: 3}, {time: .5, value: 4}]), curve([{time: 0, value: 0}, {time: 5, value: 2}]),
    curve([{time: 0, value: 0}, {time: Number.POSITIVE_INFINITY, value: 1}]), null];
  const {container} = render(<AnimationPlanView plan={plan({curves: bad, coverage_start: Number.NaN})} onExportAe={vi.fn()}/>);
  expect(screen.getByText(/5 个属性的关键帧数据无效或时间乱序/)).toBeTruthy();
  expect(screen.getByText(/暂无可用的数值关键帧/)).toBeTruthy();
  expect(screen.queryByRole('img')).toBeNull();
  expect(screen.queryByRole('button', {name: '导出 AE 试作脚本'})).toBeNull();
  expect(container.innerHTML).not.toMatch(/NaN|Infinity/);
});

test('an invalid curves container never falls back to the saved endpoints', () => {
  render(<AnimationPlanView plan={plan({curves: {points: []}})}/>);
  expect(screen.getByText(/1 个属性的关键帧数据无效/)).toBeTruthy();
  expect(screen.queryByRole('article')).toBeNull();
});

test('single points and extreme finite values do not produce a false continuous line or invalid coordinates', () => {
  const {container, rerender} = render(<AnimationPlanView plan={plan({curves: [curve([{time: 0, value: 0}])]})} onExportAe={vi.fn()}/>);
  expect(screen.getByText('仅有单点，不能表示连续运动。')).toBeTruthy();
  expect(container.querySelector('polyline')).toBeNull();
  expect(container.querySelector('circle')).toBeTruthy();
  expect(screen.queryByRole('button', {name: '导出 AE 试作脚本'})).toBeNull();
  rerender(<AnimationPlanView plan={plan({curves: [curve([{time: 0, value: -Number.MAX_VALUE}, {time: 1, value: Number.MAX_VALUE}])]})}/>);
  expect(container.querySelector('polyline')!.getAttribute('points')).not.toMatch(/NaN|Infinity/);
});

test('missing and insufficient historical plans have safe empty states', () => {
  const {container, rerender} = render(<AnimationPlanView/>);
  expect(container.textContent).toBe('');
  rerender(<AnimationPlanView plan={plan({evidence_source: 'insufficient', curves: [], keyframes: [], source_start: null, source_end: null})}/>);
  expect(screen.getByText('证据不足')).toBeTruthy();
  expect(screen.getByText(/源视频起点未记录/)).toBeTruthy();
  expect(screen.getByText(/暂无可用的数值关键帧/)).toBeTruthy();
});

test('export prevents duplicate clicks and reports the saved path', async () => {
  let finish!: (value: {path: string; message: string}) => void;
  const onExportAe = vi.fn(() => new Promise<{path: string; message: string}>(resolve => { finish = resolve; }));
  render(<AnimationPlanView plan={plan()} onExportAe={onExportAe}/>);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', {name: '导出 AE 试作脚本'}));
  const busy = screen.getByRole('button', {name: '正在导出…'});
  expect(busy.hasAttribute('disabled')).toBe(true);
  await user.click(busy);
  expect(onExportAe).toHaveBeenCalledTimes(1);
  await act(async () => finish({path: 'E:\\exports\\motion.jsx', message: '试作脚本已保存'}));
  expect(screen.getByRole('status').textContent).toContain('E:\\exports\\motion.jsx');
  expect(screen.getByRole('status').textContent).toContain('试作脚本已保存');
  expect(screen.getByRole('button', {name: '导出 AE 试作脚本'}).hasAttribute('disabled')).toBe(false);
});

test('export failures preserve the backend reason and allow a retry', async () => {
  const onExportAe = vi.fn().mockRejectedValueOnce(new Error('HTTP 409: {"detail":"需要连续可靠的测量曲线"}')).mockResolvedValueOnce({path: 'E:\\retry.jsx'});
  render(<AnimationPlanView plan={plan()} onExportAe={onExportAe}/>);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', {name: '导出 AE 试作脚本'}));
  expect(screen.getByRole('alert').textContent).toBe('导出失败：需要连续可靠的测量曲线');
  await user.click(screen.getByRole('button', {name: '导出 AE 试作脚本'}));
  expect(screen.queryByRole('alert')).toBeNull();
  expect(screen.getByRole('status').textContent).toContain('E:\\retry.jsx');
});

test('opens the source preview at a measured turn using the shot offset', async () => {
  const seek = vi.fn();
  const {rerender} = render(<AnimationPlanView plan={plan()} onSeekSource={seek}/>);
  await userEvent.click(screen.getByRole('button', {name: '查看水平位置关键帧列表'}));
  await userEvent.click(screen.getByRole('button', {name: '查看原片：水平位置，镜头内 0.375 秒'}));
  expect(seek).toHaveBeenCalledWith(12.375);
  rerender(<AnimationPlanView plan={plan({source_start: null})} onSeekSource={seek}/>);
  expect(screen.queryByRole('button', {name: /查看原片/})).toBeNull();
});

const padding = {left_px: 41, right_px: 7, top_px: 0, bottom_px: 18, width_px: 369, height_px: 198};

test('measured padding gives a corrected original center and a separate export choice', async () => {
  const onExportAe = vi.fn().mockResolvedValue({path: 'padded.jsx'});
  render(<AnimationPlanView plan={plan({artwork_padding: padding})} onExportAe={onExportAe}/>);
  expect(screen.getByText(/369 × 198/)).toBeTruthy();
  expect(screen.getByText(/Anchor Point.*201.5, 90/)).toBeTruthy();
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', {name: '导出留边 AE 试作脚本'}));
  await user.click(screen.getByRole('button', {name: '导出 AE 试作脚本'}));
  expect(onExportAe.mock.calls).toEqual([[true], [false]]);
});

test.each([
  undefined, {...padding, right_px: -1}, {...padding, left_px: true}, {...padding, top_px: .5},
  {...padding, width_px: 30001}, {...padding, height_px: 18}, {...padding, width_px: undefined},
  {left_px: 0, right_px: 0, top_px: 0, bottom_px: 0, width_px: 320, height_px: 180},
])('old or unusable padding leaves the original export available', value => {
  render(<AnimationPlanView plan={plan({artwork_padding: value})} onExportAe={vi.fn()}/>);
  expect(screen.queryByLabelText('素材留边建议')).toBeNull();
  expect(screen.queryByRole('button', {name: '导出留边 AE 试作脚本'})).toBeNull();
  expect(screen.getByRole('button', {name: '导出 AE 试作脚本'})).toBeTruthy();
});

test('shows the historical coverage limitation before opening notes or exporting', () => {
  const notice = '这条旧轨迹未记录每个帧对的跟踪点分布。请重新分析后再按全局运动试作。';
  render(<AnimationPlanView plan={plan({evidence_notice:notice})} onExportAe={vi.fn()}/>);
  expect(screen.getByText(notice).closest('details')).toBeNull();
  expect(screen.getByRole('button', {name:'导出 AE 试作脚本'})).toBeTruthy();
});
