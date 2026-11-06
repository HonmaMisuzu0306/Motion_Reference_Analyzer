import { fieldLabel,labelValue,globalTotalsUnavailable,formatSamplingRate,formatRecipeNumber,formatRecipeRange,formatTrackingScore,TRACKING_SCORE_NOTE,NET_MOTION_NOTE } from './labels';
const globalMeasurements = new Set(['translation_x_px','translation_y_px','translation_x_ratio','translation_y_ratio','rotation_deg','scale_ratio','scale_change_percent','motion_strength','stability','shake_score']);
const enums=new Set(['type','subject_type','subject_position','background_type','position','style','role','style_family','weight','tracking','alignment','orientation','dominant_color','contrast_level','visual_emphasis','motion_style','motion_strength','semantic_type','measured_type','fused_type','measured_status','status','stability_level','movement','appearance','difficulty']);
enums.add('evidence_source');
enums.add('property');
enums.add('trajectory_status');
enums.add('translation_reference');
export function AnalysisFields({value,kind}:{value:unknown;kind?:'measured'}){
 if(value==null)return <span className="muted">暂无</span>;
 if(Array.isArray(value))return <div>{value.map((item,i)=><div key={i}><AnalysisFields value={item} kind={kind}/></div>)}</div>;
 if(typeof value==='object'){
  const range=formatRecipeRange(value);
  const unavailable = kind === 'measured' && globalTotalsUnavailable(value);
  return <>
   <dl className="analysis-fields">{Object.entries(value).filter(([key])=>!(unavailable && globalMeasurements.has(key))&&!['pairs','trajectory','animation_plan','curves','provider_versions'].includes(key)&&!(range&&['min_value','max_value'].includes(key))).map(([key,item])=>{
    if (key === 'sampling_target_fps') {
      const rate = formatSamplingRate(item);
      return rate && <div key={key}><dt>{fieldLabel(key)}</dt><dd>{rate}</dd></div>;
    }
    const trackingScore=key==='measured_confidence'||(kind==='measured'&&key==='confidence');
    return <div key={key}><dt>{trackingScore?'跟踪评分':fieldLabel(key)}</dt><dd>{item!==null&&typeof item==='object'?<AnalysisFields value={item} kind={key==='measured'||key==='measured_motion'?'measured':undefined}/>:trackingScore?formatTrackingScore(item):enums.has(key)?labelValue(key,item):typeof item==='boolean'?(item?'是':'否'):['from','to','min_value','max_value'].includes(key)?formatRecipeNumber(item):String(item??'暂无')}</dd></div>;
   })}{range&&<div><dt>范围</dt><dd>{range}</dd></div>}</dl>
   {kind==='measured'&&'confidence' in value&&<p className="muted">{TRACKING_SCORE_NOTE}</p>}
   {kind==='measured'&&!unavailable&&('translation_x_ratio' in value||'translation_y_ratio' in value)&&<p className="muted">{NET_MOTION_NOTE}</p>}
  </>;
 }
 return <span>{String(value)}</span>;
}
