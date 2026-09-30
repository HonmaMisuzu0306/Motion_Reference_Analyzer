import { useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { fetch } from "@tauri-apps/plugin-http";
import { api, type ProjectStatus, type Shot, type VideoInfo } from "./services/api";
import "./App.css";

type AnalysisStatus = ProjectStatus["status"];

const STATUS_LABELS: Record<string, string> = {
  idle: "空闲",
  imported: "已导入视频",
  processing: "分析中",
  scene_detect: "正在分镜",
  extract_frames: "正在提取代表帧",
  vision_analysis: "正在视觉分析",
  generating_recipe: "正在生成 AE Recipe",
  done: "分析完成",
  error: "发生错误",
};

function App() {
  const [video, setVideo] = useState<VideoInfo | null>(null);
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [statusMessage, setStatusMessage] = useState("");
  const [shots, setShots] = useState<Shot[]>([]);
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  const selectedShot = useMemo(
    () => shots.find((s) => s.shot_id === selectedShotId) || null,
    [shots, selectedShotId]
  );

  const refreshStatus = useCallback(async () => {
    try {
      const data = await api.projectStatus();
      setStatus(data.status);
      setStatusMessage(data.message || "");
      setVideo(data.video);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(`无法连接后端: ${message}`);
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    const timer = setInterval(refreshStatus, 2000);
    return () => clearInterval(timer);
  }, [refreshStatus]);

  async function importVideo() {
    setError("");
    setSelectedShotId(null);
    try {
      const selected = await invoke<string | null>("select_video");
      if (!selected) return;

      setLoading(true);
      const data = await api.importVideo(selected);
      if (data.status === "ok") {
        setVideo(data.video as VideoInfo);
        setShots([]);
        setSelectedShotId(null);
        setStatus("imported");
      } else {
        throw new Error(JSON.stringify(data));
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function analyzeVideo() {
  setError("");
  setLoading(true);

  try {
    const data = await api.analyzeVideo();

    if (data.status === "ok") {
      // 分析完成后，从专门的 shots 接口读取结果
      const shotsResponse = await api.listShots();
      const shotsData = shotsResponse.shots;

      setShots(shotsData);
      setStatus("done");

      if (shotsData.length > 0) {
        setSelectedShotId(shotsData[0].shot_id);
      }
    } else {
      throw new Error(JSON.stringify(data));
    }
  } catch (err: unknown) {
    setError(err instanceof Error ? err.message : String(err));
    setStatus("error");
  } finally {
    setLoading(false);
  }
}

  async function exportJson() {
    setError("");
    try {
      const data = await api.exportJson();
      alert(`JSON 已导出: ${data.path}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function exportMarkdown() {
    setError("");
    try {
      const data = await api.exportMarkdown();
      alert(`Markdown 已导出: ${data.path}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <main className="container">
      <header className="header">
        <h1>Motion Reference Analyzer</h1>
        <p>参考视频镜头分析与 AE 拆解工具</p>
      </header>

      <section className="toolbar">
        <button onClick={importVideo} disabled={loading}>
          导入视频
        </button>
        <button onClick={analyzeVideo} disabled={loading || !video}>
          分析视频
        </button>
        <button onClick={exportJson} disabled={shots.length === 0}>
          导出 JSON
        </button>
        <button onClick={exportMarkdown} disabled={shots.length === 0}>
          导出 Markdown
        </button>
      </section>

      {loading && (
        <div className="loading">
          <span className="spinner" />
          <span>处理中... {STATUS_LABELS[status] || status}</span>
        </div>
      )}

      {error && (
        <div className="error-box">
          <strong>错误</strong>
          <pre>{error}</pre>
        </div>
      )}

      {video && (
        <section className="video-info card">
          <h2>视频信息</h2>
          <dl>
            <dt>文件名</dt>
            <dd>{video.filename}</dd>
            <dt>时长</dt>
            <dd>{video.duration.toFixed(2)}s</dd>
            <dt>分辨率</dt>
            <dd>
              {video.width}x{video.height}
            </dd>
            <dt>帧率</dt>
            <dd>{video.fps.toFixed(3)} fps</dd>
            <dt>编码</dt>
            <dd>{video.codec}</dd>
          </dl>
        </section>
      )}

      <section className="status-bar">
        状态: {STATUS_LABELS[status] || status}
        {statusMessage && <span className="status-message"> - {statusMessage}</span>}
      </section>

      {shots.length > 0 && (
        <section className="workspace">
          <aside className="shot-list card">
            <h2>Shot List ({shots.length})</h2>
            <ul>
              {shots.map((shot) => (
                <li
                  key={shot.shot_id}
                  className={shot.shot_id === selectedShotId ? "active" : ""}
                  onClick={() => setSelectedShotId(shot.shot_id)}
                >
                  <strong>{shot.shot_id}</strong>
                  <span>
                    {shot.time.start.toFixed(2)}s - {shot.time.end.toFixed(2)}s
                  </span>
                </li>
              ))}
            </ul>
          </aside>

          <div className="shot-detail card">
            {selectedShot ? (
              <ShotDetail shot={selectedShot} />
            ) : (
              <p className="empty">选择一个 Shot 查看详情</p>
            )}
          </div>
        </section>
      )}
    </main>
  );
}

function ShotDetail({ shot }: { shot: Shot }) {
  const motion = shot.motion || {};
  const observations = shot.observations || {};
  const typography = shot.typography || {};
  const recipe = shot.ae_recipe || {};
  const difficulty = recipe.difficulty as Record<string, string> | undefined;

  return (
    <>
      <h2>
        {shot.shot_id}
        <span className="shot-time">
          {shot.time.start.toFixed(2)}s - {shot.time.end.toFixed(2)}s
          （持续 {shot.time.duration.toFixed(2)}s）
        </span>
      </h2>

      <section className="detail-section">
        <h3>代表帧</h3>
        <div className="frame-strip">
          {shot.frames.map((frame) => (
            <img
              key={frame}
              src={api.getFrameUrl(shot.shot_id, frame)}
              alt={`${shot.shot_id} ${frame}`}
              loading="lazy"
            />
          ))}
        </div>
      </section>

      <section className="detail-section">
        <h3>运动</h3>
        <p>类型: {(motion.type as string) || "unknown"}</p>
        {typeof motion.strength === "number" && (
          <p>强度: {motion.strength.toFixed(2)}</p>
        )}
      </section>

      <section className="detail-section">
        <h3>画面观察</h3>
        <p>主体: {(observations.subject_type as string) || "unknown"}</p>
        <p>背景: {(observations.background_type as string) || "unknown"}</p>
      </section>

      <section className="detail-section">
        <h3>文字</h3>
        <p>{(typography.has_text as boolean) ? "检测到文字" : "未检测到文字"}</p>
      </section>

      <section className="detail-section">
        <h3>AE Recipe</h3>
        {recipe.layers && (recipe.layers as unknown[]).length > 0 && (
          <>
            <h4>分层建议</h4>
            <ul>
              {(recipe.layers as Array<{ role: string; suggestion: string }>).map((layer, idx) => (
                <li key={idx}>
                  {layer.role}: {layer.suggestion}
                </li>
              ))}
            </ul>
          </>
        )}
        {recipe.camera && (recipe.camera as { type: string }).type !== "static" && (
          <p>
            相机运动: {(recipe.camera as { type: string }).type}
            {typeof (recipe.camera as { strength: number }).strength === "number" &&
              `（强度 ${(recipe.camera as { strength: number }).strength.toFixed(2)}）`}
          </p>
        )}
        {recipe.effects && (recipe.effects as string[]).length > 0 && (
          <p>可能效果: {(recipe.effects as string[]).join(", ")}</p>
        )}
        {difficulty && <p>难度: {difficulty.ae || "未知"}</p>}
      </section>
    </>
  );
}

export default App;
