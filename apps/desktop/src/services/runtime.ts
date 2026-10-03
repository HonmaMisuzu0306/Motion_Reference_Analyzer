import { invoke,isTauri } from '@tauri-apps/api/core';
export interface BackendStatus {status:'starting'|'ready'|'error';endpoint:string|null;instance_id:string;owned:boolean;message:string}
export let apiEndpoint = import.meta.env.VITE_MRA_ENDPOINT || 'http://127.0.0.1:8000';
let initialization:Promise<BackendStatus>|undefined;
export function initializeRuntime(retry=false):Promise<BackendStatus>{
 if(!isTauri())return Promise.resolve({status:'ready',endpoint:apiEndpoint,instance_id:'development',owned:false,message:''});
 if(retry)initialization=undefined;
 return initialization??= (async()=>{
   let state=await invoke<BackendStatus>(retry?'retry_backend':'backend_status');
   while(state.status==='starting'){await new Promise(resolve=>setTimeout(resolve,250));state=await invoke<BackendStatus>('backend_status')}
   if(state.status==='ready'&&state.endpoint)apiEndpoint=state.endpoint;
   return state;
 })();
}

export async function pollBackend():Promise<BackendStatus|null>{return isTauri()?invoke<BackendStatus>('backend_status'):null}
