import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { AnalysisFields } from './AnalysisFields';

test('shows measured keyframe units, source time and evidence in Chinese', () => {
  render(<AnalysisFields value={{
    evidence_source: 'measured', source_start: 12,
    keyframes: [{property: 'position_x', from: 0, to: 5, unit: '画面宽度（%）', basis: '全局运动测量近似'}],
  }}/>);
  for (const label of ['参数来源', '运动测量', '源视频入点（秒）', '水平位置', '画面宽度（%）', '全局运动测量近似']) {
    expect(screen.getByText(label)).toBeTruthy();
  }
});

test('keeps semantic trial values distinct from measured parameters', () => {
  render(<AnalysisFields value={{evidence_source: 'semantic', notes: ['试作值，未被视频测量验证']}}/>);
  expect(screen.getByText('AI解读')).toBeTruthy();
  expect(screen.getByText('试作值，未被视频测量验证')).toBeTruthy();
});

test('raw trajectory and frame pair arrays stay hidden while useful labels remain', () => {
  render(<AnalysisFields value={{trajectory: [{message: 'raw trajectory sentinel'}],
    pairs: [{message: 'raw pair sentinel'}], trajectory_status: 'partial',
    translation_reference: 'frame_center', frame_width: 1920}}/>);
  expect(screen.queryByText('raw trajectory sentinel')).toBeNull();
  expect(screen.queryByText('raw pair sentinel')).toBeNull();
  expect(screen.getByText('部分跟踪')).toBeTruthy();
  expect(screen.getByText('画面中心')).toBeTruthy();
  expect(screen.getByText('画面宽度（像素）')).toBeTruthy();
});

test('specialized animation plans and curves are not duplicated as raw arrays', () => {
  render(<AnalysisFields value={{animation_plan: {keyframes: [{basis: 'hidden endpoint'}]},
    curves: [{points: [{value: 'hidden curve'}]}], transform: {basis: 'visible transform'}}}/>);
  expect(screen.queryByText('hidden endpoint')).toBeNull();
  expect(screen.queryByText('hidden curve')).toBeNull();
  expect(screen.getByText('visible transform')).toBeTruthy();
});

test('transform endpoint summaries keep units without long floating point tails', () => {
  render(<AnalysisFields value={{transform: {position_x: {from: 0, to: 3.094567310830234, unit: '画面宽度（%）'}}}}/>);
  expect(screen.getByText('3.09')).toBeTruthy();
  expect(screen.getByText('画面宽度（%）')).toBeTruthy();
});

test('returning transform summaries expose their full range in addition to the net endpoint', () => {
  render(<AnalysisFields value={{transform: {position_x: {from: 0, to: .02,
    min_value: 0, max_value: 20.0123456, unit: '画面宽度（%）'}}}}/>);
  expect(screen.getByText('0.02')).toBeTruthy();
  expect(screen.getByText('范围')).toBeTruthy();
  expect(screen.getByText('0–20.01 画面宽度（%）')).toBeTruthy();
  expect(screen.queryByText('min_value')).toBeNull();
  expect(screen.queryByText('max_value')).toBeNull();
});

test('legacy transform endpoints do not imply an unrecorded intermediate range', () => {
  render(<AnalysisFields value={{transform: {position_x: {from: 0, to: 0, unit: '像素'}}}}/>);
  expect(screen.queryByText('范围')).toBeNull();
  expect(screen.getByText('像素')).toBeTruthy();
});

test('measured scores use /100 without relabeling semantic confidence', () => {
  render(<AnalysisFields value={{semantic: {confidence: .8}, measured: {confidence: 1, translation_x_ratio: .0002}}}/>);
  expect(screen.getByText('置信度')).toBeTruthy();
  expect(screen.getByText('0.8')).toBeTruthy();
  expect(screen.getByText('跟踪评分')).toBeTruthy();
  expect(screen.getByText('100/100')).toBeTruthy();
  expect(screen.getByText('净水平位移比例')).toBeTruthy();
  expect(screen.getByText(/不代表测量准确率/)).toBeTruthy();
});


test('shows the retained sampling target when recorded and omits unknown legacy rates', () => {
  const {rerender} = render(<AnalysisFields kind="measured" value={{sampling_target_fps: 16}}/>);
  expect(screen.getByText('目标采样率')).toBeTruthy();
  expect(screen.getByText('16 帧/秒')).toBeTruthy();
  rerender(<AnalysisFields kind="measured" value={{sampling_target_fps: null}}/>);
  expect(screen.queryByText('目标采样率')).toBeNull();
});

test('localized observations do not display default zeros as measured camera motion', () => {
  render(<AnalysisFields kind="measured" value={{status:'localized_support',translation_x_px:0,rotation_deg:0,
    spatially_limited_pair_count:8,total_pair_count:8}}/>);
  expect(screen.getByText('跟踪点集中在局部')).toBeTruthy();
  expect(screen.getByText('仅局部支持的帧对')).toBeTruthy();
  expect(screen.queryByText('净水平位移（像素）')).toBeNull();
  expect(screen.queryByText('旋转（度）')).toBeNull();
});

test.each(['mixed_support','incomplete_tracking','insufficient_features'])('keeps %s diagnostics without a zero whole-shot rotation', status=>{
  render(<AnalysisFields value={{measured_motion:{status,rotation_deg:0,trajectory_status:'partial',valid_pair_count:2}}}/>);
  expect(screen.getByText('有效帧对')).toBeTruthy();
  expect(screen.queryByText('旋转（度）')).toBeNull();
  expect(screen.queryByText(/净变化只表示/)).toBeNull();
});
