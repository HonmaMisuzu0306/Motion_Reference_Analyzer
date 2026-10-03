import { describe, it, expect } from 'vitest';
import { DEFAULT_LAYOUT, loadLayout, saveLayout } from './layout';
describe('工作台布局恢复', () => {
  it('损坏布局安全恢复默认值', () => {
    localStorage.setItem('mra.workbench.layout.v1', '{broken');
    expect(loadLayout(localStorage)).toEqual(DEFAULT_LAYOUT);
  });
  it('过大或非法尺寸不会挤掉预览，重开恢复折叠状态', () => {
    saveLayout(localStorage, {...DEFAULT_LAYOUT,leftWidth:9999,rightWidth:NaN,timelineHeight:2,leftCollapsed:true});
    expect(loadLayout(localStorage)).toMatchObject({leftWidth:480,rightWidth:340,timelineHeight:120,leftCollapsed:true});
  });
});
