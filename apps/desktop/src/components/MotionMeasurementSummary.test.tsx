import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';
import { MotionMeasurementSummary } from './MotionMeasurementSummary';

test('small returning endpoints are explicitly net displacement, not the full excursion', () => {
  render(<MotionMeasurementSummary measured={{status: 'ok', translation_x_ratio: .0002,
    translation_y_ratio: -.0001, translation_x_px: .384, translation_y_px: -.108,
    scale_change_percent: 0, rotation_deg: 0, confidence: 1}}/>);
  expect(screen.getByText('净水平位移: +0.02% (0.4px)')).toBeTruthy();
  expect(screen.getByText('净垂直位移: -0.01% (-0.1px)')).toBeTruthy();
  expect(screen.getByText('净位移仅表示首尾差；往返幅度请看轨迹范围。')).toBeTruthy();
  expect(screen.getByText('跟踪评分: 100/100')).toBeTruthy();
  expect(screen.getByText(/不代表测量准确率；100\/100 也不表示无误差/)).toBeTruthy();
  expect(screen.queryByText(/置信度/)).toBeNull();
});

test('legacy values do not require a trajectory and unavailable scores do not become zero', () => {
  const {container, rerender} = render(<MotionMeasurementSummary measured={{translation_x_px: 2, confidence: .845}}/>);
  expect(screen.getByText('跟踪评分: 85/100')).toBeTruthy();
  expect(screen.getByText('净水平位移: 暂无 (2.0px)')).toBeTruthy();
  rerender(<MotionMeasurementSummary measured={{confidence: Number.NaN, translation_x_ratio: Number.POSITIVE_INFINITY}}/>);
  expect(screen.getByText('跟踪评分: 不可用')).toBeTruthy();
  expect(container.textContent).not.toMatch(/NaN|Infinity/);
});
