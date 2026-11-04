import { useEffect, useRef, useState, type ReactNode, type CSSProperties } from 'react';
import { api, type VideoInfo, type Shot, type AudioAnalysis, type RhythmSummary } from '../services/api';
import { RhythmPanel } from '../components/RhythmPanel';
import { DEFAULT_LAYOUT,loadLayout,saveLayout } from './layout';
import { PreviewPanel, type PlayRange, type PreviewHandle } from './PreviewPanel';
import { SelectionControls } from '../selection/SelectionControls';
import { SelectionRecords, type useSelectionRecords } from '../selection/SelectionRecords';
import { SelectionDetail } from '../selection/SelectionDetail';
import type { SelectionRequest, SelectionRecord } from '../selection/selection';
import { Icon } from '../design/icons';
import './workbench.css';
export function Workbench({video,source,shots,selected,audio,summary,busy,onSelect,onAnalyze,detail,selections,ensureProject,onSelectionSubmit}:{video:VideoInfo|null;source:string;shots:Shot[];selected:Shot|null;audio?:AudioAnalysis;summary?:RhythmSummary;busy:boolean;onSelect:(shot:Shot)=>void;onAnalyze:()=>void;detail:ReactNode;selections:ReturnType<typeof useSelectionRecords>;ensureProject:()=>Promise<number>;onSelectionSubmit:(request:SelectionRequest)=>Promise<void>}){
 const [showRecords,setShowRecords]=useState(false);
 useEffect(()=>{if(selections.selected)setShowRecords(true)},[selections.selected?.id]);
 const player=useRef<PreviewHandle>(null);const [playRange,setPlayRange]=useState<PlayRange|null>(null);
 const play=(start:number,end:number)=>setPlayRange(previous=>({start,end,sequence:(previous?.sequence??0)+1}));
 const [layout,setLayout]=useState(()=>loadLayout(localStorage));const [playhead,setPlayhead]=useState(0);const [seek,setSeek]=useState({time:0,sequence:0});const [query,setQuery]=useState('');
 useEffect(()=>{saveLayout(localStorage,layout)},[layout]);
 useEffect(()=>{setSeek(s=>({time:selected?.time.start??0,sequence:s.sequence+1}))},[source,selected?.library_id,selected?.shot_id]);
 const select=(shot:Shot)=>{setPlayRange(null);selections.clear();setSeek(s=>({time:shot.time.start,sequence:s.sequence+1}));onSelect(shot)};
 const retry=async(record:SelectionRecord)=>{
  await api.verifySelectionSource(record.id);const pid=await ensureProject();let request=record.request;
  if(pid!==record.project_id)throw new Error('当前项目已改变，请重新打开原记录再试');
  if(request.kind==='frame'){const position=await api.framePosition(pid,request.frame.requested_time,request.frame.pts);request={kind:'frame',frame:position.frame,preview_token:position.preview_token}}
  await onSelectionSubmit(request);
 };
 const seekRecord=async(time:number)=>{if(!selections.selected)return;await api.verifySelectionSource(selections.selected.id);setPlayRange(null);setSeek(s=>({time,sequence:s.sequence+1}))};
 const playRecord=async(start:number,end:number)=>{if(!selections.selected)return;await api.verifySelectionSource(selections.selected.id);play(start,end)};
 function splitter(key:'leftWidth'|'rightWidth'|'timelineHeight',sign:number){return {onPointerDown:(e:React.PointerEvent)=>{e.currentTarget.setPointerCapture(e.pointerId);const origin=key==='timelineHeight'?e.clientY:e.clientX;const initial=layout[key];const move=(event:PointerEvent)=>setLayout(prev=>({...prev,[key]:Math.max(key==='timelineHeight'?120:key==='rightWidth'?240:160,Math.min(key==='timelineHeight'?420:key==='rightWidth'?600:480,initial+sign*((key==='timelineHeight'?event.clientY:event.clientX)-origin)))}));const up=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',up)};window.addEventListener('pointermove',move);window.addEventListener('pointerup',up)},onKeyDown:(e:React.KeyboardEvent)=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();setLayout(prev=>({...prev,[key]:Math.max(key==='timelineHeight'?120:key==='rightWidth'?240:160,Math.min(key==='timelineHeight'?420:key==='rightWidth'?600:480,prev[key]+sign*(e.key==='ArrowLeft'||e.key==='ArrowUp'?-10:10)))}))}}}}
 const style={'--left-width':`${layout.leftCollapsed?34:layout.leftWidth}px`,'--right-width':`${layout.rightCollapsed?34:layout.rightWidth}px`,'--timeline-height':`${layout.timelineHeight}px`} as CSSProperties;
 const visibleShots=shots.filter(s=>s.shot_id.includes(query));
 return <div className="mra-workbench" style={style}><div className="workspace-options">
  <div className="segmented" role="group" aria-label="左侧面板内容"><button className={`sm ${!showRecords?'active':''}`} onClick={()=>setShowRecords(false)}><Icon name="film" size={14}/>镜头 ({shots.length})</button><button className={`sm ${showRecords?'active':''}`} onClick={()=>setShowRecords(true)}><Icon name="frame" size={14}/>局部记录 ({selections.total})</button></div>
  <span className="toolbar-spacer"/>
  <button className={`sm ghost ${layout.leftCollapsed?'':'on'}`} title="显示/隐藏镜头面板" onClick={()=>setLayout(v=>({...v,leftCollapsed:!v.leftCollapsed}))}><Icon name="panelLeft" size={14}/>镜头面板</button>
  <button className={`sm ghost ${layout.rightCollapsed?'':'on'}`} title="显示/隐藏详情面板" onClick={()=>setLayout(v=>({...v,rightCollapsed:!v.rightCollapsed}))}><Icon name="panelRight" size={14}/>详情面板</button>
  <button className="sm ghost" onClick={()=>setLayout({...DEFAULT_LAYOUT})}><Icon name="reset" size={14}/>恢复布局</button>
 </div>
 {video&&<SelectionControls duration={video.duration} source={source} playhead={playhead} selected={selected} busy={busy} ensureProject={ensureProject} captureTime={()=>player.current?.captureTime()??Promise.resolve(playhead)} onSubmit={onSelectionSubmit} onPlay={play}/>}
 <div className="workbench-main"><aside className={`panel shot-browser ${layout.leftCollapsed?'collapsed':''}`}><h2><Icon name={showRecords?'frame':'film'} size={14}/><span className="panel-title">{showRecords?'局部记录':'镜头'}</span> <small>{showRecords?selections.total:shots.length}</small></h2>{!layout.leftCollapsed&&<>{!showRecords&&<div className="search-field"><Icon name="search" size={14}/><input aria-label="搜索镜头" placeholder="搜索镜头编号" value={query} onChange={e=>setQuery(e.target.value)}/></div>}<div className="panel-scroll">{!showRecords&&visibleShots.map((s,i)=><button key={s.library_id??s.shot_id} className={`shot-row ${s===selected?'active':''}`} onClick={()=>select(s)}><span className="shot-thumb">{s.frames[0]?<img alt="镜头缩略图" loading="lazy" src={api.getFrameUrl(s.shot_id,s.frames[0],s.library_id)}/>:<Icon name="film"/>}<em className="mono">{s.time.duration.toFixed(1)}s</em></span><span className="shot-meta"><strong className="mono">{s.shot_id}</strong><small className="mono">{s.time.start.toFixed(2)} — {s.time.end.toFixed(2)} 秒</small></span><span className={`shot-sync ${s.rhythm?.beat_sync===true?'sync':s.rhythm?.beat_sync===false?'off':''}`} title={s.rhythm?.beat_sync===true?'切镜与节拍同步':s.rhythm?.beat_sync===false?'切镜偏离节拍':'不可判断'}/><span className="shot-index mono">{String(i+1).padStart(3,'0')}</span></button>)}{!shots.length&&!showRecords&&<div className="empty-state"><Icon name="film" size={26}/><p>分析后将在这里显示镜头</p></div>}{showRecords&&<SelectionRecords items={selections.items} total={selections.total} selected={selections.selected?.id} onSelect={id=>void selections.choose(id)} onMore={()=>void selections.more()} error={selections.error}/>}</div></>}</aside>
 <div role="separator" aria-label="调整镜头面板宽度" tabIndex={0} className="splitter vertical" {...splitter('leftWidth',1)}/>
 <section className="panel preview-panel"><h2><Icon name="play" size={13}/><span className="panel-title">预览</span> <small>{video?.filename}</small><span className="tc playhead-tc">{playhead.toFixed(3)} 秒</span></h2><PreviewPanel ref={player} source={source} seekRequest={seek} onTimeChange={setPlayhead} playRange={playRange} onRangeExit={()=>setPlayRange(null)}/></section>
 <div role="separator" aria-label="调整详情面板宽度" tabIndex={0} className="splitter vertical" {...splitter('rightWidth',-1)}/>
 <aside className={`panel inspector ${layout.rightCollapsed?'collapsed':''}`}><h2><Icon name="layers" size={14}/><span className="panel-title">{selections.selected?'局部分析详情':'镜头详情'}</span></h2>{!layout.rightCollapsed&&<div className="panel-scroll">{selections.selected?<SelectionDetail record={selections.selected} onPlay={playRecord} onSeek={seekRecord} onRetry={retry} busy={busy} onClose={selections.clear}/>:detail}</div>}</aside></div>
 <div role="separator" aria-label="调整时间轴高度" tabIndex={0} className="splitter horizontal" {...splitter('timelineHeight',-1)}/>
 <section className="panel timeline-panel">{video?<RhythmPanel audio={audio} summary={summary} shots={shots} selected={selected} duration={video.duration} source={source} busy={busy} onAnalyze={onAnalyze} onSelect={select} hidePlayer externalPlayhead={playhead}/>:<div className="empty-state"><Icon name="wave" size={26}/><p><strong>镜头与音频时间轴</strong><br/>节拍、瞬态和切镜将在分析后显示</p></div>}</section></div>
}
