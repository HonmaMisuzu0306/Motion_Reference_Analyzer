import { it, expect } from 'vitest';
import { labelValue, displayRecipeText, formatRecipeNumber, formatRecipeRange, formatTrackingScore } from './labels';
it('运动翻译且保留未知原值和素材内容', () => {
  expect(labelValue('motion','zoom_in')).toBe('推近');
  expect(labelValue('motion','future_motion')).toBe('未识别（future_motion）');
  expect(labelValue('motion',null)).toBe('暂无');
  expect(labelValue('strength','light')).toBe('轻微');
});
it('变换摘要使用适度精度并保留很小的非零值', () => {
  expect(formatRecipeNumber(3.094567310830234)).toBe('3.09');
  expect(formatRecipeNumber(-2.8045766634760367)).toBe('-2.8');
  expect(formatRecipeNumber(.0001)).toBe('1.00e-4');
  expect(formatRecipeNumber(Number.NaN)).toBe('不可用');
});
it('AE 固定建议汉化且保留模型自由文本与测量数值', () => {
  expect(labelValue('transform','global_scale')).toBe('整体缩放');
  expect(labelValue('transform','position_y')).toBe('垂直位置');
  expect(labelValue('role','typography')).toBe('文字排版');
  expect(displayRecipeText('text layer with mask reveal')).toBe('文字图层配合蒙版显示');
  expect(displayRecipeText('Global scale change measured: +7.2%')).toBe('测得整体缩放变化：+7.2%');
  expect(displayRecipeText('unknown')).toBe('无法判断');
  expect(displayRecipeText('Model observation: SUMMER')).toBe('Model observation: SUMMER');
});
it('范围保留单位且不为旧记录或非法数据捏造幅度', () => {
  expect(formatRecipeRange({min_value: -2.804576, max_value: 20.01234, unit: '画面宽度（%）'})).toBe('-2.8–20.01 画面宽度（%）');
  expect(formatRecipeRange({from: 0, to: 0})).toBeNull();
  expect(formatRecipeRange({min_value: 2, max_value: 1})).toBeNull();
  expect(formatRecipeRange({min_value: 0, max_value: Number.NaN})).toBeNull();
  expect(formatRecipeRange({min_value: 0, max_value: 1})).toBe('0–1 单位未记录');
  expect(formatTrackingScore(1)).toBe('100/100');
  expect(formatTrackingScore(1.1)).toBe('不可用');
  expect(formatTrackingScore(undefined)).toBe('暂无');
});
