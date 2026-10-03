import { fieldLabel,labelValue } from './labels';
const enums=new Set(['type','subject_type','subject_position','background_type','position','style','role','style_family','weight','tracking','alignment','orientation','dominant_color','contrast_level','visual_emphasis','motion_style','motion_strength','semantic_type','measured_type','fused_type','measured_status','status','stability_level','movement','appearance','difficulty']);
export function AnalysisFields({value}:{value:unknown}){
 if(value==null)return <span className="muted">暂无</span>;
 if(Array.isArray(value))return <div>{value.map((item,i)=><div key={i}><AnalysisFields value={item}/></div>)}</div>;
 if(typeof value==='object')return <dl className="analysis-fields">{Object.entries(value).filter(([key])=>!['pairs','provider_versions'].includes(key)).map(([key,item])=><div key={key}><dt>{fieldLabel(key)}</dt><dd>{item!==null&&typeof item==='object'?<AnalysisFields value={item}/>:enums.has(key)?labelValue(key,item):typeof item==='boolean'?(item?'是':'否'):String(item??'暂无')}</dd></div>)}</dl>;
 return <span>{String(value)}</span>;
}
