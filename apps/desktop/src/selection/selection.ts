import type { AudioAnalysis, Shot, TextRegion } from '../services/api';
export interface FrameIdentity {source_hash:string;stream_index:number;pts:number;time_base_num:number;time_base_den:number;video_origin:number;requested_time:number;actual_time:number}
export interface FramePosition {frame:FrameIdentity;preview_token:string;preview_url:string}
export type SelectionRequest = {kind:'frame';frame:FrameIdentity;preview_token:string}|{kind:'clip';start:number;end:number};
export interface SelectionResult {
 schema_version:number;kind:'frame'|'clip';source_hash:string;time:Partial<FrameIdentity>&{start?:number;end?:number;duration?:number};warnings:string[];
 frame?:{image:string;observations:Record<string,unknown>;typography:Record<string,unknown>;visual_effects:unknown[];ae_hypothesis:Record<string,unknown>;ae_recipe:Record<string,unknown>;text_regions:TextRegion[];analysis_error:string};
 shots?:Shot[];audio?:AudioAnalysis;versions?:Record<string,unknown>;
}
export interface SelectionRecord {id:string;project_id:number;kind:'frame'|'clip';status:'preparing'|'running'|'done'|'completed_with_warnings'|'error'|'interrupted';request:SelectionRequest;result:SelectionResult;progress:{stage?:string;completed?:number;total?:number;message?:string};error:string;warnings:string[];created_at:string;source_available?:boolean}
export function rangeError(start:number,end:number,duration:number):string {
 if(![start,end,duration].every(Number.isFinite))return '请输入有效时间';
 if(!(0<=start&&start<end&&end<=duration))return '请满足：0 ≤ 入点 < 出点 ≤ 视频时长';
 if(end-start>60)return '片段最长为60秒';
 return '';
}
export const activeRecord=(r:SelectionRecord)=>r.status==='preparing'||r.status==='running';
export const recordStatus={preparing:'准备中',running:'分析中',done:'已完成',completed_with_warnings:'部分完成',error:'失败',interrupted:'已中断'};
