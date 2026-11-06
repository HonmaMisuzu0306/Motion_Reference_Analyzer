import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { api } from '../services/api';
import { RegionTracker } from './RegionTracker';
import type { RegionResult, TwoPinResult } from './regionTypes';

const source = 'a'.repeat(64);
const props = {source, shotId:'shot/1', libraryId:19, start:2, end:3, playhead:2};
const frame = {source_id:source, source_time:2, frame_width:360, frame_height:640, image_data_url:'data:image/jpeg;base64,AA=='};
function single(id: string, x: number): RegionResult {
  return {track_id:id, track:{status:'complete', stop_time:null, frame_width:360, frame_height:640,
    samples:[{source_time:2, center_x_px:x, center_y_px:320}, {source_time:2.125, center_x_px:x+4, center_y_px:321}]}};
}
const a = single('a-id', 180), b = single('b-id',306);
const pair: TwoPinResult = {track_id:'paired-id',track:{status:'angle_jump', stop_time:2.25,
  frame_width:360,frame_height:640,initial_distance_px:126,initial_vector_x_px:126,initial_vector_y_px:0,
  pin_a_status:'complete',pin_b_status:'complete',samples:a.track.samples.map((s,i)=>({
    source_time:s.source_time, position_x_px:s.center_x_px,position_y_px:s.center_y_px,
    pin_b_x_px:b.track.samples[i].center_x_px,pin_b_y_px:b.track.samples[i].center_y_px,rotation_deg:0,scale_percent:100}))}};
afterEach(()=>vi.restoreAllMocks());

async function twoRegions() {
  vi.spyOn(api,'regionFrame').mockResolvedValue(frame);
  vi.spyOn(api,'trackRegion').mockResolvedValueOnce(a).mockResolvedValue(b);
  const view = render(<RegionTracker {...props}/>);
  fireEvent.click(screen.getByText('框选图案并跟踪'));
  fireEvent.click(screen.getByText('读取定帧图'));
  fireEvent.load(await screen.findByAltText('框选所用的源视频定帧'));
  fireEvent.click(screen.getByText('跟踪此区域'));
  fireEvent.click(await screen.findByText('设为 A，添加第二点'));
  expect((screen.getByLabelText('定帧源时间（秒）') as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByLabelText('跟踪至源时间（秒）') as HTMLInputElement).disabled).toBe(true);
  const percent = (name: string, value: string) => fireEvent.change(screen.getByLabelText(name+'（%）'),{target:{value}});
  percent('框宽','10'); percent('框高','50');
  expect((screen.getByText('跟踪 B 区域') as HTMLButtonElement).disabled).toBe(true);
  percent('左边位置','80');
  expect(screen.getByLabelText('标记 A 的初始框')).toBeTruthy();
  expect(screen.getByLabelText('标记 B 的初始框')).toBeTruthy();
  fireEvent.click(screen.getByText('跟踪 B 区域'));
  const consent = await screen.findByRole('checkbox',{name:'我确认 A、B 属于同一刚性平面图案'});
  return {view, consent};
}

test('combining two scoped server ids needs explicit confirmation and exports only the paired id',async()=>{
  vi.spyOn(api,'trackTwoPins').mockResolvedValue(pair);
  vi.spyOn(api,'exportTwoPinAe').mockResolvedValue({path:'motion-pair.jsx'});
  vi.spyOn(api,'exportRegionAe').mockResolvedValue({path:'A-position.jsx'});
  const {consent}=await twoRegions();
  const measure=screen.getByText('计算双点变换') as HTMLButtonElement;
  expect(measure.disabled).toBe(true);
  fireEvent.click(measure);
  expect(api.trackTwoPins).not.toHaveBeenCalled();
  fireEvent.click(consent);fireEvent.click(measure);
  expect(await screen.findByText(/首次停止：源片 2.2500/)).toBeTruthy();
  expect(api.trackTwoPins).toHaveBeenCalledWith('shot/1',source,'a-id','b-id',19);
  expect(screen.getByText(/A 的位置 X 184.00，Y 321.00/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('双点采样时间'),{target:{value:'0'}});
  expect(screen.getByText(/A 的位置 X 180.00，Y 320.00/)).toBeTruthy();
  fireEvent.click(screen.getByText('导出双点 AE 空对象 JSX'));
  expect(await screen.findByText('motion-pair.jsx')).toBeTruthy();
  expect(api.exportTwoPinAe).toHaveBeenCalledWith('shot/1','paired-id',source,19);
  fireEvent.click(consent);
  expect(screen.queryByText('导出双点 AE 空对象 JSX')).toBeNull();
  fireEvent.click(screen.getByText('导出 A 的位置 JSX'));
  expect(await screen.findByText('A-position.jsx')).toBeTruthy();
  expect(api.exportRegionAe).toHaveBeenCalledWith('shot/1','a-id',source,19);
  fireEvent.click(screen.getByText('返回 A 单框'));
  expect(screen.getByText('逐点复核原片')).toBeTruthy();
  expect((screen.getByLabelText('左边位置（%）') as HTMLInputElement).value).toBe('25');
});

test('editing B discards consent and a previously computed pair; another shot cannot use A',async()=>{
  vi.spyOn(api,'trackTwoPins').mockResolvedValue(pair);
  const {view,consent}=await twoRegions();
  fireEvent.click(consent);fireEvent.click(screen.getByText('计算双点变换'));
  await screen.findByText('导出双点 AE 空对象 JSX');
  fireEvent.change(screen.getByLabelText('框宽（%）'),{target:{value:'11'}});
  expect(screen.queryByText('导出双点 AE 空对象 JSX')).toBeNull();
  fireEvent.click(screen.getByText('跟踪 B 区域'));
  expect((await screen.findByRole('checkbox') as HTMLInputElement).checked).toBe(false);
  view.rerender(<RegionTracker {...props} libraryId={21}/>);
  expect(screen.queryByText('A 已固定')).toBeNull();
  expect(screen.queryByText('导出 A 的位置 JSX')).toBeNull();
});

test('empty or single-point prefixes give the stop reason and never offer a paired export',async()=>{
  const empty: TwoPinResult = {...pair,track:{...pair.track,status:'baseline_too_short',stop_time:2,samples:[],
    initial_distance_px:null,initial_vector_x_px:null,initial_vector_y_px:null}};
  vi.spyOn(api,'trackTwoPins').mockResolvedValueOnce(empty).mockResolvedValueOnce({...pair,track:{
    ...pair.track,status:'degenerate',stop_time:2.125,samples:pair.track.samples.slice(0,1)}});
  const {consent}=await twoRegions();fireEvent.click(consent);
  fireEvent.click(screen.getByText('计算双点变换'));
  expect(await screen.findByText('两点距离太近，请重新选框并拉开距离')).toBeTruthy();
  expect(screen.queryByText('导出双点 AE 空对象 JSX')).toBeNull();
  fireEvent.click(screen.getByText('计算双点变换'));
  expect(await screen.findByText('两点靠得过近，无法继续测量转角')).toBeTruthy();
  expect(screen.queryByText('导出双点 AE 空对象 JSX')).toBeNull();
});

test('an expired server record clears both pins and stale pairs', async()=>{
  vi.spyOn(api,'trackTwoPins').mockRejectedValue(Error('HTTP 404: {"detail":"expired"}'));
  const {consent}=await twoRegions();fireEvent.click(consent);fireEvent.click(screen.getByText('计算双点变换'));
  expect((await screen.findByRole('alert')).textContent).toContain('请重新计算 A 和 B');
  expect(screen.queryByText('A 已固定')).toBeNull();
  expect(screen.queryByText('导出 B 的位置 JSX')).toBeNull();
  expect((screen.getByText('跟踪此区域') as HTMLButtonElement).disabled).toBe(false);
});

test('pair calculation waits for the in-flight B review read before starting another working-shot operation', async()=>{
  vi.spyOn(api,'trackTwoPins').mockResolvedValue(pair);
  const {consent}=await twoRegions();
  let finish!:()=>void;
  vi.mocked(api.regionFrame).mockImplementationOnce(()=>new Promise(resolve=>{
    finish=()=>resolve({...frame, source_time:2.125});
  }));
  fireEvent.click(screen.getByText('逐点复核原片'));
  fireEvent.click(screen.getByText('下一采样点'));
  await waitFor(()=>expect(api.regionFrame).toHaveBeenCalledWith('shot/1',source,2.125,19));
  fireEvent.click(consent);fireEvent.click(screen.getByText('计算双点变换'));
  expect(api.trackTwoPins).not.toHaveBeenCalled();
  expect((screen.getByText('返回 A 单框') as HTMLButtonElement).disabled).toBe(true);
  await act(async()=>finish());
  expect(await screen.findByText('导出双点 AE 空对象 JSX')).toBeTruthy();
});

test('coordinates from a different B track cannot become an exportable result', async()=>{
  vi.spyOn(api,'trackTwoPins').mockResolvedValue({...pair,track:{...pair.track,
    samples:pair.track.samples.map(s=>({...s,pin_b_x_px:s.pin_b_x_px+1}))}});
  const {consent}=await twoRegions();
  fireEvent.click(consent);fireEvent.click(screen.getByText('计算双点变换'));
  expect((await screen.findByRole('alert')).textContent).toContain('双点结果与当前输入不一致');
  expect(screen.queryByText('导出双点 AE 空对象 JSX')).toBeNull();
});
