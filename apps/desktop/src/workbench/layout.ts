export interface LayoutState{leftWidth:number;rightWidth:number;timelineHeight:number;leftCollapsed:boolean;rightCollapsed:boolean}
export const DEFAULT_LAYOUT:LayoutState={leftWidth:240,rightWidth:340,timelineHeight:210,leftCollapsed:false,rightCollapsed:false};
const key='mra.workbench.layout.v1';
const number=(n:unknown,fallback:number,min:number,max:number)=>typeof n==='number'&&Number.isFinite(n)?Math.max(min,Math.min(max,n)):fallback;
function sanitize(raw:Partial<LayoutState>):LayoutState{return {leftWidth:number(raw.leftWidth,240,160,480),rightWidth:number(raw.rightWidth,340,240,600),timelineHeight:number(raw.timelineHeight,210,120,420),leftCollapsed:raw.leftCollapsed===true,rightCollapsed:raw.rightCollapsed===true}}
export function loadLayout(storage:Storage):LayoutState{try{return sanitize(JSON.parse(storage.getItem(key)||'{}')||{})}catch{return {...DEFAULT_LAYOUT}}}
export function saveLayout(storage:Storage,value:LayoutState){try{storage.setItem(key,JSON.stringify(sanitize(value)))}catch{/* Layout remains usable when storage is unavailable. */}}
