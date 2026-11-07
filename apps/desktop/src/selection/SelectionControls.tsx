import { useEffect, useRef, useState } from 'react';
import { api, type Shot } from '../services/api';
import { rangeError, type FramePosition, type SelectionRequest } from './selection';
import './selection.css';
import type { CaptureTime } from '../workbench/PreviewPanel';

export function SelectionControls({duration,source,playhead,selected,busy,ensureProject,captureTime,onSubmit,onPlay}:{
 duration:number;source:string;playhead:number;selected:Shot|null;busy:boolean;ensureProject:()=>Promise<number>;
 captureTime:()=>Promise<CaptureTime>;onSubmit:(request:SelectionRequest)=>Promise<void>;onPlay:(start:number,end:number)=>void;
}){
 const [start,setStart]=useState(0),[end,setEnd]=useState(Math.min(duration,5));
 const [frameTime,setFrameTime]=useState(0),[position,setPosition]=useState<FramePosition|null>(null);
 const [working,setWorking]=useState(false),[error,setError]=useState('');const generation=useRef(0);
 useEffect(()=>{generation.current++;setStart(0);setEnd(Math.min(duration,5));setFrameTime(0);setPosition(null);setError('')},[source,duration]);
 const disabled=busy||working||!source;
 const invalid=rangeError(start,end,duration);
 async function locate(time:number,direction:'current'|'previous'|'next'='current'){
  const revision=++generation.current;setWorking(true);setError('');
  try{
   if(!Number.isFinite(time)||time<0||time>duration)throw new Error('帧时间超出视频范围');
   const pid=await ensureProject();const data=await api.framePosition(pid,time,direction==='current'?undefined:position?.frame.pts,direction);
   if(revision!==generation.current)return;
   setPosition(data);setFrameTime(data.frame.actual_time);
  }catch(err){if(revision===generation.current){setPosition(null);setError(String(err))}}
  finally{setWorking(false)}
 }
 async function submit(request:SelectionRequest){setWorking(true);setError('');try{await onSubmit(request)}catch(err){setError(String(err))}finally{setWorking(false)}}
 async function currentFrame(analyze=false){
  const revision=++generation.current;setWorking(true);setError('');
  try{const time=await captureTime();const pid=await ensureProject();
   const data=typeof time==='number'?await api.framePosition(pid,time):await api.framePosition(pid,time.presentedTime,undefined,'presented');
   if(revision!==generation.current)return;setPosition(data);setFrameTime(data.frame.actual_time);
   if(analyze)await onSubmit({kind:'frame',frame:data.frame,preview_token:data.preview_token});
  }catch(err){if(revision===generation.current)setError(String(err))}finally{setWorking(false)}
 }
 return <section className="selection-controls" aria-label="单帧与片段选择">
  <div className="selection-row"><strong>单帧</strong>
   <button className="primary" disabled={disabled} onClick={()=>void currentFrame(true)}>分析当前帧</button>
   <button disabled={disabled} onClick={()=>void currentFrame()}>取当前帧</button>
   <label>时间（秒）<input aria-label="单帧时间（秒）" type="number" min={0} max={duration} step="0.001" value={Number.isNaN(frameTime)?'':frameTime} disabled={disabled} onChange={e=>{setFrameTime(e.target.value===''?NaN:Number(e.target.value));setPosition(null)}}/></label>
   <button disabled={disabled} onClick={()=>void locate(frameTime)}>定位帧</button>
   <button disabled={disabled||!position} onClick={()=>void locate(frameTime,'previous')}>上一帧</button>
   <button disabled={disabled||!position} onClick={()=>void locate(frameTime,'next')}>下一帧</button>
   <button className="primary" disabled={disabled||!position} onClick={()=>position&&void submit({kind:'frame',frame:position.frame,preview_token:position.preview_token})}>分析单帧</button>
  </div>
  {position&&<div className="selection-frame"><img alt="待分析准确单帧" src={api.previewUrl(position.preview_url)}/><span>实际帧 {position.frame.actual_time.toFixed(6)} 秒 · PTS {position.frame.pts}<br/>仅分析静态构图、文字、色彩和效果</span></div>}
  <div className="selection-row"><strong>片段</strong>
   <button disabled={disabled} onClick={()=>setStart(playhead)}>设为入点</button>
   <label>入点（秒）<input aria-label="入点（秒）" type="number" min={0} max={duration} step="0.001" value={Number.isNaN(start)?'':start} disabled={disabled} onChange={e=>setStart(e.target.value===''?NaN:Number(e.target.value))}/></label>
   <button disabled={disabled} onClick={()=>setEnd(playhead)}>设为出点</button>
   <label>出点（秒）<input aria-label="出点（秒）" type="number" min={0} max={duration} step="0.001" value={Number.isNaN(end)?'':end} disabled={disabled} onChange={e=>setEnd(e.target.value===''?NaN:Number(e.target.value))}/></label>
   <button disabled={disabled||!selected} onClick={()=>{if(selected){setStart(selected.time.start);setEnd(selected.time.end)}}}>使用当前镜头</button>
   <button disabled={disabled||!!invalid} onClick={()=>onPlay(start,end)}>播放选区</button>
   <button className="primary" disabled={disabled||!!invalid} onClick={()=>void submit({kind:'clip',start,end})}>分析片段</button>
   <button title="选取 6 秒以内的一次叠化，两端各留至少 0.15 秒静止画面。此项只使用本地视频像素。" disabled={disabled||!!invalid||end-start>6} onClick={()=>void submit({kind:'clip',start,end,measurement:'opacity_blend'})}>测量叠化</button>
  </div>
  <div className="selection-range" role="img" aria-label={`源视频选区 ${start.toFixed(3)} 至 ${end.toFixed(3)} 秒`}>{!invalid&&<span style={{left:`${start/duration*100}%`,width:`${(end-start)/duration*100}%`}}/>}</div>
  <p className="muted">{invalid||`选区 [${start.toFixed(3)}, ${end.toFixed(3)}) 秒 · ${(end-start).toFixed(3)} 秒`} · 最长60秒 · 结果独立保存{!source?' · 源视频未导入或缺失':''}</p>
  {error&&<p role="alert">{error}</p>}
 </section>;
}
