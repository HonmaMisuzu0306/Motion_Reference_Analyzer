import { it, expect } from 'vitest';
import { labelValue, displayRecipeText } from './labels';
it('运动翻译且保留未知原值和素材内容', () => {
  expect(labelValue('motion','zoom_in')).toBe('推近');
  expect(labelValue('motion','future_motion')).toBe('未识别（future_motion）');
  expect(labelValue('motion',null)).toBe('暂无');
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
