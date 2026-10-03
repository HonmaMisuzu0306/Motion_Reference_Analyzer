import { it,expect,vi } from 'vitest';
import { render,screen,waitFor,fireEvent } from '@testing-library/react';
import { ModelsPage } from './ModelsPage';
import { api } from '../services/api';
vi.mock('../services/api',()=>({api:{modelRecommendations:vi.fn(async()=>({recommendations:[],hardware:{}})),modelStatus:vi.fn(),getSettings:vi.fn(),putSettings:vi.fn()}}));
it('检测尚未完成时不把未知引擎状态显示成未安装',()=>{
 vi.mocked(api.modelStatus).mockImplementation(()=>new Promise(()=>{}));
 render(<ModelsPage/>);
 expect(screen.queryByText(/引擎未安装/)).toBeNull();
});
it('本机已有模型可直接选用并显示就绪，不要求重复下载',async()=>{
 let configured=false;
 vi.mocked(api.modelStatus).mockImplementation(async()=>({connected:false,message:'offline',models:[],ocr:{engine_installed:true,configured,available:configured,errors:[],discovered_models:[{label:'PP-OCRv5 通用识别',languages:['ch','japan','en'],detection_dir:'C:/models/det',recognition_dir:'C:/models/rec'}]}}));
 vi.mocked(api.getSettings).mockResolvedValue({schema_version:1,ollama_url:'http://127.0.0.1:11434',qwen_model_id:'qwen3-vl:4b',ocr_models:[],beat_sync_tolerance_ms:80});
 vi.mocked(api.putSettings).mockImplementation(async value=>{configured=value.ocr_models.length===1;return value});
 render(<ModelsPage/>);
 await waitFor(()=>expect(screen.getByRole('button',{name:'选用本地 OCR 模型'})).toBeTruthy());
 fireEvent.click(screen.getByRole('button',{name:'选用本地 OCR 模型'}));
 await waitFor(()=>expect(screen.getByText(/本地模型目录已就绪/)).toBeTruthy());
 expect(screen.queryByRole('button',{name:/下载/})).toBeNull();
});
