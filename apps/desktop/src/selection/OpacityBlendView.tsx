import { frameReviewTime, type SelectionResult } from './selection';

interface Props {
  blend: NonNullable<SelectionResult['opacity_blend']>;
  start: number;
  onSeek?: (time: number) => void;
}

export function OpacityBlendView({ blend, start, onSeek }: Props) {
  return <section className="opacity-blend">
    <h3>叠化 · AE 顶层不透明度</h3>
    <p>按 {blend.sample_count} 帧的画面混合比例估算。将选区入点对齐到合成零秒，起始画面放在底层并保持 100%，结束画面放在顶层，按表设置线性关键帧。</p>
    <p>{blend.color_advice ?? '这条历史曲线按解码 RGB 数值估算。可重新测量以比较颜色混合方式。'}</p>
    <table>
      <caption>两张静帧叠化的复现参考</caption>
      <thead><tr><th scope="col">源时间（秒）</th><th scope="col">合成时间（秒）</th><th scope="col">顶层不透明度</th></tr></thead>
      <tbody>{blend.keyframes.map(key => <tr key={key.source_time}>
        <td>{onSeek
          ? <button aria-label={`回看源时间 ${key.source_time.toFixed(3)} 秒`} onClick={() => onSeek(frameReviewTime(key.source_time,key.frame_end))}>{key.source_time.toFixed(3)}</button>
          : key.source_time.toFixed(3)}</td>
        <td>{(key.source_time - start).toFixed(3)}</td><td>{key.opacity_percent.toFixed(1)}%</td>
      </tr>)}</tbody>
    </table>
  </section>;
}
