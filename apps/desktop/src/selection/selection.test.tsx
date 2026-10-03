import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SelectionControls } from './SelectionControls';
import { rangeError } from './selection';
import { api } from '../services/api';
import { SelectionDetail } from './SelectionDetail';
import type { SelectionRecord } from './selection';

describe('局部分析选择', () => {
 it('分析当前帧一次点击定位并提交同一准确帧',async()=>{
  const frame={source_hash:'hash',stream_index:0,pts:24,time_base_num:1,time_base_den:24,video_origin:0,requested_time:1.03,actual_time:1};
  const locate=vi.spyOn(api,'framePosition').mockResolvedValue({frame,preview_token:'token',preview_url:'/preview'});
  const capture=vi.fn().mockResolvedValue(1.03),submit=vi.fn().mockResolvedValue(undefined);
  render(<SelectionControls duration={20} source="video" playhead={0} selected={null} busy={false} ensureProject={async()=>1} captureTime={capture} onSubmit={submit} onPlay={()=>{}}/>);
  fireEvent.click(screen.getByRole('button',{name:'分析当前帧'}));
  await waitFor(()=>expect(submit).toHaveBeenCalledWith({kind:'frame',frame,preview_token:'token'}));
  expect(capture).toHaveBeenCalledTimes(1);expect(locate).toHaveBeenCalledTimes(1);locate.mockRestore();
 });
 it('部分完成记录可导出、跳到源时间，并重新分析为新记录',async()=>{
  const record:SelectionRecord={id:'old',project_id:1,created_at:new Date().toISOString(),kind:'frame',status:'completed_with_warnings',request:{kind:'frame',preview_token:'old',frame:{source_hash:'hash',stream_index:0,pts:30,time_base_num:1,time_base_den:24,video_origin:0,requested_time:1.25,actual_time:1.25}},result:{schema_version:1,kind:'frame',source_hash:'hash',warnings:['OCR失败'],time:{actual_time:1.25,pts:30},frame:{image:'frame.png',observations:{},typography:{},visual_effects:[],ae_hypothesis:{},ae_recipe:{},text_regions:[],analysis_error:''}},warnings:['OCR失败'],progress:{},error:'',source_available:true};
  const retry=vi.fn().mockResolvedValue(undefined),seek=vi.fn().mockResolvedValue(undefined);
  render(<SelectionDetail record={record} onPlay={()=>{}} onClose={()=>{}} onRetry={retry} onSeek={seek} busy={false}/>);
  expect(screen.getByRole('button',{name:'导出局部 JSON'})).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:/跳到源时间/}));await waitFor(()=>expect(seek).toHaveBeenCalledWith(1.25));
  fireEvent.click(screen.getByRole('button',{name:'重新分析为新记录'}));await waitFor(()=>expect(retry).toHaveBeenCalledWith(record));
 });
 it('入出点使用源时间，分析不替换已有镜头', async () => {
  const submit = vi.fn().mockResolvedValue(undefined);
  render(<SelectionControls duration={20} source="video" playhead={10} selected={null} busy={false}
   ensureProject={async()=>1} captureTime={async()=>10} onSubmit={submit} onPlay={()=>{}}/>);
  fireEvent.click(screen.getByRole('button',{name:'设为入点'}));
  fireEvent.change(screen.getByLabelText('出点（秒）'),{target:{value:'13.5'}});
  fireEvent.click(screen.getByRole('button',{name:'分析片段'}));
  await waitFor(()=>expect(submit).toHaveBeenCalledWith({kind:'clip',start:10,end:13.5}));
  expect((screen.getByLabelText('入点（秒）') as HTMLInputElement).value).toBe('10');
 });
 it('拒绝反向、超过时长和超过一分钟的范围',()=>{
  expect(rangeError(10,9,20)).toBeTruthy();
  expect(rangeError(0,21,20)).toBeTruthy();
  expect(rangeError(0,61,70)).toBeTruthy();
  expect(rangeError(10,13.5,20)).toBe('');
 });
 it('忙碌期间禁用提交',()=>{
  render(<SelectionControls duration={20} source="video" playhead={0} selected={null} busy
   ensureProject={async()=>1} captureTime={async()=>0} onSubmit={async()=>{}} onPlay={()=>{}}/>);
  expect((screen.getByRole('button',{name:'分析片段'}) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole('button',{name:'分析单帧'}) as HTMLButtonElement).disabled).toBe(true);
 });
});
