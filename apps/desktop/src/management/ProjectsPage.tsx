import { useEffect,useState } from 'react';
import { invoke,isTauri } from '@tauri-apps/api/core';
import { api,type ManagedProject } from '../services/api';
import { Icon } from '../design/icons';
export function ProjectsPage({busy,onProjectLoaded,onImport}:{busy:boolean;onProjectLoaded:()=>Promise<void>;onImport:()=>void}){const [rows,setRows]=useState<ManagedProject[]>([]);const [notice,setNotice]=useState('');const [working,setWorking]=useState(false);
 const refresh=async()=>setRows((await api.listProjects()).projects);
 useEffect(()=>{void refresh().catch(e=>setNotice(String(e)))},[]);
 const action=async(fn:()=>Promise<unknown>)=>{setWorking(true);try{await fn();await refresh();setNotice('操作完成')}catch(e){setNotice(String(e))}finally{setWorking(false)}};
 const totalShots=rows.reduce((n,p)=>n+p.shot_count,0);
 return <section className="management-page"><div className="page-heading"><div><span className="eyebrow">Workspace</span><h2>项目</h2><p className="muted">导入参考视频创建项目，保存后可随时重开继续查看</p></div><button disabled={busy||working} className="primary" onClick={onImport}><Icon name="plus"/>新建 · 导入视频</button></div>
  {rows.length>0&&<div className="stat-row"><div className="stat"><span>项目</span><strong className="mono">{rows.length}</strong></div><div className="stat"><span>已分析镜头</span><strong className="mono">{totalShots}</strong></div><div className="stat"><span>源视频可用</span><strong className="mono">{rows.filter(p=>p.source_available).length}<i>/{rows.length}</i></strong></div></div>}
  {notice&&<p role="status" className="page-notice">{notice}</p>}
  <div className="project-grid">{rows.map(p=><article key={p.id} className="management-card project-card"><div className="project-card-head"><span className="project-icon"><Icon name="film" size={18}/></span><div className="project-card-title"><h3 title={p.name}>{p.name}</h3><p title={p.video_filename}>{p.video_filename}</p></div></div>
   <div className="project-card-meta"><span className="chip accent">{p.shot_count} 个镜头</span><span className={`chip ${p.source_available?'green':'orange'}`}><span className="dot"/>{p.source_available?'源视频可用':'源视频缺失，可重新定位'}</span></div>
   <p className="muted project-updated"><Icon name="clock" size={12}/>更新：<span className="mono">{p.updated_at}</span></p>
   <div className="project-actions"><button className="primary" disabled={busy||working} onClick={()=>action(async()=>{await api.loadLibraryProject(p.id);await onProjectLoaded()})}><Icon name="open" size={14}/>打开项目</button><button disabled={busy||working} onClick={()=>{const name=prompt('项目名称',p.name);if(name)void action(()=>api.renameProject(p.id,name))}}><Icon name="edit" size={14}/>重命名</button>{isTauri()&&<button disabled={busy||working} onClick={()=>action(async()=>{const path=await invoke<string|null>('select_video');if(path)await api.relinkProject(p.id,path)})}><Icon name="link" size={14}/>重新定位源视频</button>}</div></article>)}
   {rows.length>0&&<button className="project-new" disabled={busy||working} onClick={onImport}><Icon name="import" size={22}/><strong>导入新的参考视频</strong><small>分析镜头、运动与节奏</small></button>}</div>
  {!rows.length&&<div className="management-card hero-empty"><span className="hero-icon"><Icon name="import" size={28}/></span><h3>开始建立参考项目</h3><p className="muted">导入视频、分析镜头、保存到本地参考库。尚未分析的视频也可以保存。</p><ol className="steps"><li><b>1</b>导入参考视频</li><li><b>2</b>分镜 · 运动 · 节奏分析</li><li><b>3</b>保存到参考库并检索</li></ol></div>}
  <div className="management-card subtle"><h3><Icon name="library" size={15}/>导入开发版参考库</h3><p className="muted">将旧数据库和关联资产复制到当前空参考库，原库与视频保持不变；已有项目时不能导入。</p>{isTauri()&&<button disabled={busy||working||rows.length>0} onClick={()=>action(async()=>{const source_db=await invoke<string|null>('select_database');if(!source_db)return;const source_root=await invoke<string|null>('select_directory');if(source_root&&confirm('复制旧参考库到当前空库？原库保留。'))await api.importLegacyLibrary(source_db,source_root)})}>选择旧库并导入副本</button>}</div></section>
}
