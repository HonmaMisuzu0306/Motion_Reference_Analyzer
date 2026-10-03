import { it, expect, vi } from 'vitest';
import { render,screen,waitFor } from '@testing-library/react';
import { ModelsPage } from './ModelsPage';
vi.mock('../services/api',()=>({api:{modelRecommendations:vi.fn(async()=>({recommendations:[{id:'qwen3-vl:4b',profile:'均衡配置',use:'视觉分析',official_url:'https://ollama.com/library/qwen3-vl:4b',artifact_size_bytes:3300000000,validation_status:'已验收'}],hardware:{}})),modelStatus:vi.fn(async()=>({connected:false,models:[],message:'服务未连接',ocr:{available:false,engine_installed:true,configured:false,discovered_models:[],errors:['请配置本地目录']}}))}}));
it('缺模型引导用户去官网，软件内没有下载动作',async()=>{
 render(<ModelsPage/>);
 await waitFor(()=>expect(screen.getByText('qwen3-vl:4b')).toBeTruthy());
 expect(screen.getByRole('link',{name:'模型官网'}).getAttribute('href')).toBe('https://ollama.com/library/qwen3-vl:4b');
 expect(screen.getByRole('button',{name:'重新检测'})).toBeTruthy();
 expect(screen.queryByRole('button',{name:/下载/})).toBeNull();
});
