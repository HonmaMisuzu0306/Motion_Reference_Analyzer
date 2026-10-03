import { useEffect, useState } from 'react';
import { api, type DiscoveredOCRModel, type ModelStatus, type ModelCatalog } from '../services/api';

const languageNames: Record<string, string> = { ch: '中文', japan: '日语', en: '英文' };

function LocalOCRChoice({ model, disabled, onSelect }: {
 model: DiscoveredOCRModel; disabled: boolean; onSelect: (model: DiscoveredOCRModel, language: string) => Promise<void>;
}) {
 const [language, setLanguage] = useState(model.languages[0]);
 return <div className="ocr-model-row">
  <h4>{model.label}</h4>
  <p className="muted">检测：{model.detection_dir}<br />识别：{model.recognition_dir}</p>
  <label>识别语言<select disabled={disabled} value={language} onChange={e => setLanguage(e.target.value)}>
   {model.languages.map(code => <option key={code} value={code}>{languageNames[code] ?? code}</option>)}
  </select></label>
  <button disabled={disabled} onClick={() => void onSelect(model, language)}>选用本地 OCR 模型</button>
 </div>;
}

export function ModelsPage({ busy: analysisBusy = false }: { busy?: boolean }) {
 const [catalog, setCatalog] = useState<ModelCatalog>();
 const [status, setStatus] = useState<ModelStatus>();
 const [busy, setBusy] = useState(false);
 const [error, setError] = useState('');
 const [notice, setNotice] = useState('');
 const refresh = async () => {
  setBusy(true);
  try {
   const [recommendations, current] = await Promise.all([api.modelRecommendations(), api.modelStatus()]);
   setCatalog(recommendations); setStatus(current); setError('');
  } catch (e) { setError(String(e)); setStatus(undefined); }
  finally { setBusy(false); }
 };
 useEffect(() => { void refresh(); }, []);
 const selectOCR = async (model: DiscoveredOCRModel, language: string) => {
  setBusy(true); setNotice('');
  try {
   const settings = await api.getSettings();
   const row = { language, detection_dir: model.detection_dir, recognition_dir: model.recognition_dir, orientation_dir: null };
   await api.putSettings({ ...settings, ocr_models: [...settings.ocr_models.filter(r => r.language !== language), row] });
   setStatus(await api.modelStatus()); setError(''); setNotice('已选用本地 OCR 模型，下次分析生效');
  } catch (e) { setError(String(e)); }
  finally { setBusy(false); }
 };
 const ocr = status?.ocr;
 const ocrDescription = !ocr ? (error ? '检测失败，请重新检测' : '正在检测…')
  : !ocr.engine_installed ? '引擎未安装'
  : ocr.available ? '本地模型目录已就绪 · 引擎已安装'
  : ocr.configured ? '配置需修复 · 引擎已安装'
  : ocr.discovered_models.length ? '已发现本地模型，尚未选用 · 引擎已安装'
  : '尚未选择模型目录 · 引擎已安装';
 return <section className="management-page">
  <div className="page-heading"><div><h2>模型与配置建议</h2><p className="muted">优先选用本机已有模型；需要其他模型时可前往官网自行下载安装</p></div><button disabled={busy} onClick={() => void refresh()}>{busy ? '正在检测…' : '重新检测'}</button></div>
  {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
  <div className="management-card"><h3>本地分析环境</h3><p>{status?.message ?? '正在读取状态…'}</p><p>OCR：{ocrDescription}</p>
   {ocr?.configured && ocr.errors.map(e => <p key={e} className="muted">{e}</p>)}
   <a href="https://ollama.com/download/windows" target="_blank" rel="noreferrer">Ollama 官方安装页</a><span className="muted"> · 运行内存需求通常大于模型文件大小</span>
  </div>
  <div className="management-card"><h3>本机 OCR 模型</h3><p className="muted">检测本机 PaddleX 默认模型目录，完整的模型可直接选用。其他位置的模型可在“设置”中选择目录，无需重复下载。</p>
   {ocr?.discovered_models.map(model => <LocalOCRChoice key={model.recognition_dir} model={model} disabled={analysisBusy || busy || !ocr.engine_installed} onSelect={selectOCR} />)}
   {ocr && !ocr.discovered_models.length && <p className="muted">默认目录中未发现完整模型。已有模型请在“设置”中选择；需要下载时请查看 <a target="_blank" rel="noreferrer" href="https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html">PaddleOCR 官方模型页</a>。</p>}
  </div>
  <div className="management-card"><h3>配置与推荐</h3><p className="muted">系统内存：{catalog?.hardware.ram_bytes ? `${(catalog.hardware.ram_bytes / 1024 ** 3).toFixed(1)} GB` : '未知'} · 显卡/显存：{catalog?.hardware.gpu_name ?? '未获取，请按实际电脑资源选择'}。配置档位为选型参考，候选模型尚需实际验证。</p>
   <table><thead><tr><th>配置方向</th><th>推荐模型</th><th>用途</th><th>模型文件大小</th><th>验收情况</th><th>官网</th></tr></thead><tbody>{catalog?.recommendations.map(row => <tr key={row.id}><td>{row.profile}</td><td>{row.id}</td><td>{row.use}</td><td>{row.artifact_size_bytes ? `约 ${(row.artifact_size_bytes / 1e9).toFixed(1)} GB` : '按模型查看'}</td><td>{row.validation_status}</td><td><a href={row.official_url} target="_blank" rel="noreferrer">模型官网</a></td></tr>)}</tbody></table>
  </div>
  <div className="management-card"><h3>已安装视觉模型</h3>{status?.models.length ? <table><tbody>{status.models.map(m => <tr key={m.id}><td>{m.id}</td><td>{m.size ? `${(m.size / 1e9).toFixed(1)} GB` : '大小未知'}</td><td>{m.vision ? '支持图像输入' : '未确认视觉能力'}</td><td>{m.error}<button disabled={analysisBusy || busy || !m.vision} onClick={async () => {
   setBusy(true); setNotice('');
   try { const settings = await api.getSettings(); await api.putSettings({ ...settings, qwen_model_id: m.id }); setError(''); setNotice(`已选择 ${m.id}，下次分析生效`); }
   catch (e) { setError(String(e)); } finally { setBusy(false); }
  }}>选用此模型</button></td></tr>)}</tbody></table> : <p className="muted">连接 Ollama 后可查看已安装模型。缺少模型时仍可使用分镜、运动和节奏基础分析。</p>}</div>
 </section>;
}
