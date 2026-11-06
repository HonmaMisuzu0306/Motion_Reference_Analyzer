import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { api } from '../services/api';
import { RegionTracker } from './RegionTracker';

const source = 'a'.repeat(64);
const props = {source, shotId: 'shot/A', start: 10, end: 30, playhead: 12.11};
const frame = {source_id: source, source_time: 12.1, frame_width: 360, frame_height: 640, image_data_url: 'data:image/jpeg;base64,AA=='};
const result = {track_id: 'saved-track', track: {status: 'no_match', stop_time: 12.5, frame_width: 360, frame_height: 640,
  samples: [{source_time: 12.1, center_x_px: 92, center_y_px: 408}, {source_time: 12.35, center_x_px: 95, center_y_px: 413}]}};
afterEach(() => vi.restoreAllMocks());
async function showFrame() {
  fireEvent.click(screen.getByText('框选图案并跟踪'));
  fireEvent.click(screen.getByText('读取定帧图'));
  const image = await screen.findByAltText('框选所用的源视频定帧');
  expect((screen.getByText('跟踪此区域') as HTMLButtonElement).disabled).toBe(true);
  fireEvent.load(image);
}

test('keyboard box uses the displayed frame PTS; partial results export by server ID', async () => {
  vi.spyOn(api, 'regionFrame').mockResolvedValue(frame);
  vi.spyOn(api, 'trackRegion').mockResolvedValue(result);
  vi.spyOn(api, 'exportRegionAe').mockResolvedValue({path: 'region.jsx'});
  render(<RegionTracker {...props} libraryId={14}/>);
  await showFrame();
  expect(api.regionFrame).toHaveBeenCalledWith('shot/A', source, 12.11, 14);
  fireEvent.change(screen.getByLabelText('左边位置（%）'), {target: {value: '15.25'}});
  fireEvent.change(screen.getByLabelText('跟踪至源时间（秒）'), {target: {value: '14.3'}});
  fireEvent.click(screen.getByText('跟踪此区域'));
  expect(await screen.findByText('图案已不可辨认')).toBeTruthy();
  expect(screen.getByText(/12.1000 至 12.3500 秒.*12.5000 秒/)).toBeTruthy();
  expect(api.trackRegion).toHaveBeenCalledWith('shot/A', {identity: source, anchor_time: 12.1, end_time: 14.3,
    box: {x: .1525, y: .25, width: .5, height: .5}}, 14);
  fireEvent.click(screen.getByText('导出 AE 空对象 JSX'));
  expect(await screen.findByText('region.jsx')).toBeTruthy();
  expect(api.exportRegionAe).toHaveBeenCalledWith('shot/A', 'saved-track', source, 14);
  fireEvent.change(screen.getByLabelText('框宽（%）'), {target: {value: '90'}});
  expect((screen.getByText('跟踪此区域') as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByText('导出 AE 空对象 JSX')).toBeNull();
});

test('dragging backwards on a scaled portrait produces normalized frame coordinates', async () => {
  vi.spyOn(api, 'regionFrame').mockResolvedValue(frame);
  vi.spyOn(api, 'trackRegion').mockResolvedValue(result);
  render(<RegionTracker {...props}/>);
  await showFrame();
  const picture = screen.getByLabelText('区域跟踪定帧图');
  vi.spyOn(picture, 'getBoundingClientRect').mockReturnValue(new DOMRect(40, 70, 180, 320));
  Object.defineProperty(picture, 'setPointerCapture', {value: vi.fn()});
  function pointer(type: string, x: number, y: number) {
    const event = new MouseEvent(type, {bubbles:true, clientX:x, clientY:y, button:0});
    Object.defineProperty(event, 'pointerId', {value:1});
    fireEvent(picture, event);
  }
  pointer('pointerdown', 175, 310);
  pointer('pointerup', 62.5, 150);
  fireEvent.click(screen.getByText('跟踪此区域'));
  expect(await screen.findByText('图案已不可辨认')).toBeTruthy();
  expect(api.trackRegion).toHaveBeenCalledWith('shot/A', expect.objectContaining({box:{x:.125,y:.25,width:.625,height:.5}}), undefined);
});

test('switching sources with the same shot number ignores the old request', async () => {
  let finish!: (value: typeof frame) => void;
  vi.spyOn(api, 'regionFrame').mockReturnValue(new Promise(resolve => {finish = resolve;}));
  const {rerender} = render(<RegionTracker {...props}/>);
  fireEvent.click(screen.getByText('框选图案并跟踪'));
  fireEvent.click(screen.getByText('读取定帧图'));
  rerender(<RegionTracker {...props} source={'b'.repeat(64)}/>);
  fireEvent.click(screen.getByText('框选图案并跟踪'));
  await act(async () => finish(frame));
  expect(screen.queryByAltText('框选所用的源视频定帧')).toBeNull();
});

test('a stale source frame or pre-hash project cannot be tracked', async () => {
  vi.spyOn(api, 'regionFrame').mockResolvedValue({...frame, source_id: 'wrong'});
  const {rerender} = render(<RegionTracker {...props}/>);
  fireEvent.click(screen.getByText('框选图案并跟踪'));
  fireEvent.click(screen.getByText('读取定帧图'));
  expect(await screen.findByRole('alert')).toBeTruthy();
  expect(screen.queryByAltText('框选所用的源视频定帧')).toBeNull();
  rerender(<RegionTracker {...props} source="legacy.mp4"/>);
  expect(screen.queryByText('框选图案并跟踪')).toBeNull();
});

test('another library entry with the same shot, source and times starts with its own selection', async () => {
  vi.spyOn(api, 'regionFrame').mockResolvedValue(frame);
  const view = render(<RegionTracker {...props} libraryId={17}/>);
  await showFrame();
  fireEvent.change(screen.getByLabelText('框宽（%）'), {target: {value: '39'}});
  view.rerender(<RegionTracker {...props} libraryId={19}/>);
  expect(screen.queryByAltText('框选所用的源视频定帧')).toBeNull();
  await showFrame();
  expect(api.regionFrame).toHaveBeenLastCalledWith(props.shotId, source, 12.11, 19);
  expect((screen.getByLabelText('框宽（%）') as HTMLInputElement).value).toBe('50');
});
