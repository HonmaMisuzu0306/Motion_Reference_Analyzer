import { useEffect, useState } from 'react';
import { api } from '../services/api';
import { AnalysisFields } from '../i18n/AnalysisFields';
import { CutRhythmView } from '../components/RhythmPanel';
import { recordStatus, type SelectionRecord } from './selection';

export function SelectionDetail({record,onPlay,onClose,onSeek,onRetry,busy=false}:{record:SelectionRecord;onPlay:(start:number,end:number)=>void|Promise<void>;onClose:()=>void;onSeek?:(time:number)=>void|Promise<void>;onRetry?:(record:SelectionRecord)=>Promise<void>;busy?:boolean}){
 const [shotIndex,setShotIndex]=useState(0),[notice,setNotice]=useState(''),[working,setWorking]=useState(false);
 useEffect(()=>{setShotIndex(0);setNotice('')},[record.id]);
 async function exportResult(format:'json'|'markdown'){try{const value=await api.exportSelection(record.id,format);setNotice(`已导出：${value.path}`)}catch(err){setNotice(String(err))}}
 async function action(operation:()=>void|Promise<void>){setWorking(true);setNotice('');try{await operation()}catch(err){setNotice(String(err))}finally{setWorking(false)}}
 const result=record.result,frame=result.frame,shots=result.shots??[],shot=shots[shotIndex];
 const completed=record.status==='done'||record.status==='completed_with_warnings';
 const disabled=busy||working||record.source_available===false;
 return <div className="selection-detail"><button onClick={onClose}>返回镜头详情</button>
  <h3>{record.kind==='frame'?'单帧分析':'片段分析'} · {recordStatus[record.status]}</h3>
  {record.error&&<p role="alert">{record.error}</p>}
  {onRetry&&<button disabled={disabled} onClick={()=>void action(()=>onRetry(record))}>重新分析为新记录</button>}
  {notice&&<p role="status">{notice}</p>}
  {record.source_available===false&&<p className="muted">源视频缺失或内容不匹配，截图和结果仍可查看；在项目页重新关联同一视频后可播放和重新分析。</p>}
  {!completed&&<p role="status">{record.progress.message||'可新建分析记录重试；现有镜头结果保持保留'}</p>}
  {completed&&<>
   <div className="selection-row"><button onClick={()=>void exportResult('json')}>导出局部 JSON</button><button onClick={()=>void exportResult('markdown')}>导出局部 Markdown</button></div>
   {frame&&<><p>实际时间 {result.time.actual_time?.toFixed(6)} 秒 · PTS {result.time.pts}</p>
    {onSeek&&<button disabled={disabled} onClick={()=>void action(()=>onSeek(result.time.actual_time!))}>跳到源时间 {result.time.actual_time?.toFixed(6)} 秒</button>}
    <img className="selection-evidence" alt="分析使用的准确单帧" src={api.selectionAssetUrl(record.id,frame.image)}/>
    <h3>静态画面观察</h3><AnalysisFields value={frame.observations}/>
    <h3>文字识别</h3>{frame.text_regions.length?frame.text_regions.map(r=><p key={r.id}>{r.text} <small>({(r.confidence*100).toFixed(0)}%)</small></p>):<p className="muted">未检测到文字</p>}
    <h3>文字布局</h3><AnalysisFields value={frame.typography}/><h3>可见效果</h3><AnalysisFields value={frame.visual_effects}/>
    <h3>静态 AE 复现假设</h3><AnalysisFields value={frame.ae_recipe}/>
   </>}
   {shots.length>0&&<><p>源选区 [{result.time.start?.toFixed(3)}, {result.time.end?.toFixed(3)}) 秒 · {shots.length} 个局部镜头</p>
    <button disabled={disabled} onClick={()=>void action(()=>onPlay(result.time.start!,result.time.end!))}>播放分析片段</button>
    {onSeek&&<button disabled={disabled} onClick={()=>void action(()=>onSeek(result.time.start!))}>跳到源时间 {result.time.start?.toFixed(3)} 秒</button>}
    <label>局部镜头<select aria-label="局部镜头" value={shotIndex} onChange={e=>setShotIndex(Number(e.target.value))}>{shots.map((s,i)=><option value={i} key={s.shot_id}>{s.shot_id} · {s.time.start.toFixed(3)}–{s.time.end.toFixed(3)} 秒</option>)}</select></label>
    {shot&&<>{shot.frames.map(name=><img key={name} className="selection-evidence" alt={`${shot.shot_id}代表帧`} src={api.selectionAssetUrl(record.id,`shots/${shot.shot_id}/${name}`)}/>)}
     {shot.analysis_error&&<p role="alert">{shot.analysis_error}</p>}
     <h3>画面观察</h3><AnalysisFields value={shot.observations}/><h3>运动测量</h3><AnalysisFields value={shot.motion_summary}/><AnalysisFields value={shot.measured_motion}/>
     <h3>文字与排版</h3><AnalysisFields value={shot.typography_tracks}/><h3>切镜节奏</h3><CutRhythmView rhythm={shot.rhythm}/>
     <h3>AE 制作建议</h3><AnalysisFields value={shot.ae_recipe}/>
    </>}
    {result.audio&&<section><h3>选区音频</h3><p>{result.audio.message}</p><p>BPM：{result.audio.tempo_bpm??'不可用'} · 节拍 {result.audio.beat_times.length} / 瞬态 {result.audio.onset_times.length}</p>
     <svg viewBox="0 0 400 60" aria-label="片段音频波形"><polyline fill="none" stroke="#94badd" points={result.audio.waveform.map(p=>`${(p.time-result.time.start!)/(result.time.end!-result.time.start!)*400},${55-p.rms*50}`).join(' ')}/></svg></section>}
   </>}
   {record.warnings.length>0&&<section><h3>能力限制与警告</h3><ul>{record.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul></section>}
  </>}
 </div>;
}
