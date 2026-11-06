import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { OpacityBlendView } from './OpacityBlendView';

describe('叠化制作建议', () => {
  const blend = { method: 'two-held-pictures-v1', sample_count: 32, keyframes: [
    { source_time: 6.25, opacity_percent: 0 }, { source_time: 6.765625, opacity_percent: 45.3 },
    { source_time: 7.75, opacity_percent: 100 },
  ] };
  it('显示本次颜色建议，并为旧记录说明估算方式', () => {
    const advice = '实测中间帧更接近 sRGB 线性光混合。';
    const view = render(<OpacityBlendView blend={{...blend,color_advice:advice}} start={6.2}/>);
    expect(screen.getByText(advice)).toBeTruthy();
    view.rerender(<OpacityBlendView blend={blend} start={6.2}/>);
    expect(screen.getByText(/历史曲线按解码 RGB/)).toBeTruthy();
  });
  it('在已知源帧内部回看，短间隔仍保留精确的表格时间', () => {
    const seek = vi.fn();
    const time = 34 / 24;
    const frameEnd = time + .00005;
    render(<OpacityBlendView blend={{...blend,keyframes:[{source_time:time,frame_end:frameEnd,opacity_percent:33}]}} start={1} onSeek={seek}/>);
    fireEvent.click(screen.getByRole('button',{name:'回看源时间 1.417 秒'}));
    const point = seek.mock.calls[0][0];
    expect(point).toBeGreaterThan(time);
    expect(point).toBeLessThan(frameEnd);
    expect(screen.getByText('0.417')).toBeTruthy();
  });
  it('按选区入点给出合成时间，按原始精度回看实际采样帧', () => {
    const seek = vi.fn();
    const view = render(<OpacityBlendView blend={blend} start={6.2} onSeek={seek}/>);
    const row = screen.getByText('45.3%').closest('tr')!;
    expect(within(row).getByText('0.566')).toBeTruthy();
    fireEvent.click(within(row).getByRole('button', { name: '回看源时间 6.766 秒' }));
    expect(seek).toHaveBeenCalledWith(6.765625);
    view.rerender(<OpacityBlendView blend={blend} start={6.2}/>);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(screen.getByText('6.766')).toBeTruthy();
  });
});
