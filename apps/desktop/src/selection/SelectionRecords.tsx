import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import { activeRecord, recordStatus, type SelectionRecord } from './selection';

export function useSelectionRecords(projectId:number|null){
 const [items,setItems]=useState<SelectionRecord[]>([]),[total,setTotal]=useState(0),[selected,setSelected]=useState<SelectionRecord|null>(null);
 const [checking,setChecking]=useState(false),[error,setError]=useState('');const currentProject=useRef(projectId);currentProject.current=projectId;
 const refresh=useCallback(async()=>{
  if(projectId==null)return;
  const data=await api.selectionRecords(projectId);
  if(currentProject.current!==projectId)return;
  setItems(data.items);setTotal(data.total);setError('');
 },[projectId]);
 const choose=useCallback(async(id:string)=>{try{const value=await api.selectionRecord(id);if(value.project_id===currentProject.current)setSelected(value)}catch(err){setError(String(err))}},[]);
 useEffect(()=>{setItems([]);setTotal(0);setSelected(null);setError('');if(projectId==null)return;
  let cancelled=false;setChecking(true);void refresh().catch(err=>{if(!cancelled)setError(String(err))}).finally(()=>{if(!cancelled)setChecking(false)});
  return()=>{cancelled=true};
 },[projectId,refresh]);
 const running=items.some(activeRecord);
 useEffect(()=>{if(!running)return;let cancelled=false;let timer:ReturnType<typeof setTimeout>;
  async function poll(){try{await refresh();if(!cancelled&&selected)await choose(selected.id)}catch(err){if(!cancelled)setError(String(err))}finally{if(!cancelled)timer=setTimeout(()=>void poll(),1000)}}
  timer=setTimeout(()=>void poll(),1000);
  return()=>{cancelled=true;clearTimeout(timer)};
 },[running,refresh,choose,selected?.id]);
 async function created(id:string){const value=await api.selectionRecord(id);setItems(old=>[value,...old.filter(r=>r.id!==id)]);setSelected(value);setTotal(n=>n+1)}
 async function more(){if(projectId==null)return;try{const data=await api.selectionRecords(projectId,items.length);if(currentProject.current===projectId){setItems(old=>[...old,...data.items]);setTotal(data.total)}}catch(err){setError(String(err))}}
 return {items,total,selected,error,choose,created,more,clear:()=>setSelected(null),busy:running||checking};
}

export function SelectionRecords({items,total,selected,onSelect,onMore,error}:{items:SelectionRecord[];total:number;selected:string|undefined;onSelect:(id:string)=>void;onMore:()=>void;error:string}){
 return <section className="selection-records" aria-label="局部分析记录"><h3>局部记录 <small>{total}</small></h3>{error&&<p role="alert">{error}</p>}
  {!items.length&&<p className="muted">单帧和片段结果将保存在这里</p>}
  {items.map(r=><button key={r.id} className={`selection-record ${selected===r.id?'active':''}`} onClick={()=>onSelect(r.id)}>
   <span>{r.request.kind==='frame'?'单帧':r.request.measurement?'叠化':'片段'} · {recordStatus[r.status]}</span>
   <small>{r.request.kind==='frame'?`${r.request.frame.actual_time.toFixed(3)} 秒`:`${r.request.start.toFixed(3)} — ${r.request.end.toFixed(3)} 秒`}</small>
   {activeRecord(r)&&<small>{r.progress.message||'准备中'} {r.progress.total?`${r.progress.completed??0}/${r.progress.total}`:''}</small>}
   <small>{new Date(r.created_at).toLocaleString('zh-CN')}</small>
  </button>)}{items.length<total&&<button onClick={onMore}>加载更多记录</button>}
 </section>;
}
