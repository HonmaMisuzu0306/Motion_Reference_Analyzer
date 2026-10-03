import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { api } from '../services/api';
export interface SeekRequest{time:number;sequence:number}
export interface PlayRange{start:number;end:number;sequence:number}
export interface PreviewHandle{captureTime:()=>Promise<number>}
export const PreviewPanel=forwardRef<PreviewHandle,{source:string;seekRequest:SeekRequest;onTimeChange:(time:number)=>void;playRange?:PlayRange|null;onRangeExit?:()=>void}>(function PreviewPanel({source,seekRequest,onTimeChange,playRange,onRangeExit},ref){
 const player=useRef<HTMLVideoElement>(null),presented=useRef<number|null>(null);const [error,setError]=useState('');
 const range=useRef(playRange),internalSeek=useRef<number|null>(null),exitCallback=useRef(onRangeExit);exitCallback.current=onRangeExit;
 function exitRange(){if(range.current){range.current=null;exitCallback.current?.()}}
 function seekTo(video:HTMLVideoElement,time:number){internalSeek.current=time;presented.current=null;video.currentTime=time}
 useEffect(()=>{range.current=playRange},[playRange]);
 const timeCallback=useRef(onTimeChange);timeCallback.current=onTimeChange;
 useImperativeHandle(ref,()=>({captureTime:async()=>{
  const video=player.current;if(!video)return 0;video.pause();
  if(video.seeking)await new Promise<void>(resolve=>video.addEventListener('seeked',()=>resolve(),{once:true}));
  return presented.current??video.currentTime;
 }}),[]);
 useEffect(()=>{setError('');presented.current=null},[source]);
 useEffect(()=>{const video=player.current;if(video&&video.readyState>=1){exitRange();video.pause();seekTo(video,seekRequest.time);timeCallback.current(seekRequest.time)}},[seekRequest.sequence,seekRequest.time,source]);
 useEffect(()=>{const video=player.current;if(video&&playRange&&video.readyState>=1){range.current=playRange;video.pause();seekTo(video,playRange.start);void video.play().catch(err=>setError(`片段无法播放：${String(err)}`))}},[playRange?.sequence,source]);
 function update(video:HTMLVideoElement,time:number){
  if(range.current&&time>=range.current.end){const end=range.current.end;video.pause();if(Math.abs(video.currentTime-end)>0.00001)seekTo(video,end);timeCallback.current(end);exitRange()}
  else timeCallback.current(time);
 }
 useEffect(()=>{
  const video=player.current;if(!video||!video.requestVideoFrameCallback)return;
  let id:number;let cancelled=false;
  const frame=(_:number,metadata:VideoFrameCallbackMetadata)=>{if(cancelled)return;presented.current=metadata.mediaTime;update(video,metadata.mediaTime);id=video.requestVideoFrameCallback(frame)};
  id=video.requestVideoFrameCallback(frame);
  return()=>{cancelled=true;video.cancelVideoFrameCallback(id)};
 },[source]);
 return <div className="preview-body">{source?<video ref={player} key={source} controls preload="metadata" src={api.videoSourceUrl(source)}
  onLoadedMetadata={e=>{const video=e.currentTarget;seekTo(video,playRange?.start??seekRequest.time);timeCallback.current(video.currentTime);if(playRange)void video.play().catch(err=>setError(String(err)))}}
  onSeeking={e=>{presented.current=null;const time=e.currentTarget.currentTime;
   if(range.current&&(internalSeek.current===null||Math.abs(time-internalSeek.current)>0.00001)&&(time<range.current.start||time>=range.current.end))exitRange();
  }}
  onSeeked={()=>{internalSeek.current=null}}
  onPlay={e=>{if(range.current&&e.currentTarget.currentTime>=range.current.end)exitRange()}}
  onTimeUpdate={e=>update(e.currentTarget,e.currentTarget.currentTime)}
  onError={()=>setError('源视频无法播放，请检查文件位置或编码。分析结果仍可查看。')}/>:<div className="workbench-empty"><strong>参考视频预览</strong><p>导入一段参考视频，开始分析镜头、运动与节奏</p></div>}{error&&<p role="alert">{error}</p>}</div>;
});
