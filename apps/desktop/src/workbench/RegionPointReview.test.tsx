import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { api } from '../services/api';
import { RegionTracker } from './RegionTracker';
import type { RegionFrame, RegionResult } from './regionTypes';

const source = 'c'.repeat(64);
const props = {shotId: 'S/1', source, libraryId: 7, start: 2, end: 5, playhead: 2.1};
const frame: RegionFrame = {source_id: source, source_time: 2.08, frame_width: 600, frame_height: 900,
  image_data_url: 'data:image/jpeg;base64,AAAA'};
const points = [{source_time: 2.08, center_x_px: 150, center_y_px: 450},
  {source_time: 2.20175, center_x_px: 300, center_y_px: 360},
  {source_time: 2.423, center_x_px: 294, center_y_px: 400}];
const result: RegionResult = {track_id: 'R1', track: {status:'ambiguous', stop_time:2.559,
  frame_width:600, frame_height:900, samples:points}};
afterEach(() => vi.restoreAllMocks());
async function inspect(analysis: RegionResult = result) {
  vi.spyOn(api, 'trackRegion').mockResolvedValue(analysis);
  const view = render(<RegionTracker {...props}/>);
  fireEvent.click(screen.getByText('框选图案并跟踪'));
  fireEvent.click(screen.getByText('读取定帧图'));
  fireEvent.load(await screen.findByAltText('框选所用的源视频定帧'));
  fireEvent.click(screen.getByText('跟踪此区域'));
  fireEvent.click(await screen.findByText('逐点复核原片'));
  fireEvent.load(await screen.findByAltText(analysis.track.samples.length
    ? '采样点对应的源视频画面' : '首个未确认位置对应的源视频画面'));
  return view;
}

test('source PTS drive portrait crosshairs, and an unconfirmed frame has no position', async () => {
  const get = vi.spyOn(api, 'regionFrame').mockResolvedValueOnce(frame)
    .mockImplementation(async (_shot, _source, time) => ({...frame, source_time:time}));
  await inspect();
  expect(get).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('img',{name:'实测中心'}).style.left).toBe('25%');
  fireEvent.click(screen.getByText('下一采样点'));
  const image = await screen.findByAltText('采样点对应的源视频画面');
  expect(screen.queryByRole('img',{name:'实测中心'})).toBeNull();
  fireEvent.load(image);
  expect(screen.getByRole('img',{name:'实测中心'}).style.top).toBe('40%');
  expect(get).toHaveBeenLastCalledWith('S/1', source, 2.20175, 7);
  fireEvent.click(screen.getByText('查看首个未确认帧'));
  fireEvent.load(await screen.findByAltText('首个未确认位置对应的源视频画面'));
  expect(get).toHaveBeenLastCalledWith('S/1', source, 2.559, 7);
  expect(screen.queryByRole('img',{name:'实测中心'})).toBeNull();
  expect(screen.getByText(/此帧未确认图案位置/)).toBeTruthy();
  expect((screen.getByLabelText('跟踪至源时间（秒）') as HTMLInputElement).value).toBe('5');
  expect(screen.getByText('导出 AE 空对象 JSX')).toBeTruthy();
});

test('quick navigation skips queued targets and ignores the in-flight reply after a box edit', async () => {
  let finish!: (f: RegionFrame) => void;
  const get = vi.spyOn(api,'regionFrame').mockResolvedValueOnce(frame)
    .mockImplementationOnce(() => new Promise(resolve => {finish = resolve;}))
    .mockImplementation(async (_shot, _source, time) => ({...frame, source_time:time}));
  await inspect();
  fireEvent.click(screen.getByText('下一采样点'));
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByText('下一采样点'));
  fireEvent.click(screen.getByText('查看首个未确认帧'));
  expect(get).toHaveBeenCalledTimes(2);
  await act(async () => { finish({...frame, source_time:2.20175}); });
  expect(await screen.findByAltText('首个未确认位置对应的源视频画面')).toBeTruthy();
  expect(get.mock.calls.map(args=>args[2])).toEqual([2.1, 2.20175, 2.559]);
  get.mockImplementationOnce(() => new Promise(resolve => {finish=resolve;}));
  fireEvent.click(screen.getByText('上一采样点'));
  await waitFor(() => expect(get).toHaveBeenCalledTimes(4));
  fireEvent.change(screen.getByLabelText('框高（%）'), {target:{value:'46'}});
  await act(async () => {finish({...frame, source_time:2.423});});
  expect(screen.queryByLabelText('轨迹逐点复核')).toBeNull();
  expect(screen.queryByRole('img',{name:'实测中心'})).toBeNull();
});

test('a nearby but different returned PTS cannot show measured coordinates', async () => {
  vi.spyOn(api,'regionFrame').mockResolvedValueOnce(frame).mockResolvedValue({...frame,source_time:2.201});
  await inspect();
  fireEvent.click(screen.getByText('下一采样点'));
  expect(await screen.findByText(/返回的帧与选定的时间或画幅不符/)).toBeTruthy();
  expect(screen.queryByAltText('采样点对应的源视频画面')).toBeNull();
  expect(screen.queryByRole('img',{name:'实测中心'})).toBeNull();
});

test('if the initial box lacks texture, the actual rejected frame has no measured center', async () => {
  const get = vi.spyOn(api,'regionFrame').mockResolvedValue(frame);
  await inspect({...result, track: {...result.track, status:'insufficient_texture', stop_time:frame.source_time, samples:[]}});
  expect(screen.getByText(/此帧未确认图案位置/)).toBeTruthy();
  expect(screen.queryByRole('img', {name:'实测中心'})).toBeNull();
  expect(screen.queryByText('导出 AE 空对象 JSX')).toBeNull();
  expect(get).toHaveBeenCalledTimes(1);
});

test('timing cues jump to actual nonuniform samples, including the fastest interval endpoints', async () => {
  const get = vi.spyOn(api, 'regionFrame').mockResolvedValueOnce(frame)
    .mockImplementation(async (_shot, _source, time) => ({...frame, source_time:time}));
  await inspect();
  fireEvent.click(screen.getByText('查看最大偏移点'));
  fireEvent.load(await screen.findByAltText('采样点对应的源视频画面'));
  expect(get).toHaveBeenLastCalledWith('S/1', source, 2.20175, 7);
  fireEvent.click(screen.getByText('查看最快区间终点'));
  expect(screen.getByRole('img',{name:'实测中心'})).toBeTruthy();
  fireEvent.click(screen.getByText('查看最快区间起点'));
  fireEvent.load(await screen.findByAltText('采样点对应的源视频画面'));
  expect(screen.getByText(/实测中心 X 150.00，Y 450.00/)).toBeTruthy();
  expect(get).toHaveBeenCalledTimes(2);
});
