import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { AeMotionPreview } from './AeMotionPreview';

const x = {property: 'position_x', unit: '画面宽度（%）', points: [
  {time: .25, value: 0}, {time: .5, value: 20}, {time: 1.75, value: 0}
], interpolation: 'linear', legacy: false};
const common = {frameWidth: 320, frameHeight: 180, coverageStart: .25, coverageEnd: 1.75, sourceStart: 10, curves: [x]};

test('nonuniform keys and independent channels use the source picture center and true local time', () => {
  const onSeek = vi.fn();
  const y = {...x, property: 'position_y', unit: '画面高度（%）', points: [{time: .25, value: 0}, {time: 1.75, value: 60}]};
  const angle = {...x, property: 'rotation', unit: '角度（°）', points: [{time: .25, value: 0}, {time: 1.75, value: 180}]};
  const scale = {...x, property: 'global_scale', unit: '缩放（%）', points: [{time: .25, value: 100}, {time: 1.75, value: 160}]};
  const view = render(<AeMotionPreview {...common} curves={[x,y,angle,scale]} onSeekSource={onSeek}/>);
  const layer = view.container.querySelector('[data-motion-layer]')!;
  expect(layer.getAttribute('transform')).toBe('translate(160 90) rotate(0) scale(1) translate(-160 -90)');
  const slider = screen.getByRole('slider');
  fireEvent.change(slider, {target: {value: '.5'}});
  expect(layer.getAttribute('transform')).toBe('translate(224 108) rotate(30) scale(1.1) translate(-160 -90)');
  fireEvent.click(screen.getByRole('button', {name:'查看原片 10.500 秒'}));
  expect(onSeek).toHaveBeenCalledWith(10.5);
  fireEvent.keyDown(slider,{key:'End'});
  expect(layer.getAttribute('transform')).toBe('translate(160 198) rotate(180) scale(1.6) translate(-160 -90)');
});

test('portrait frame keeps the JSX calibration geometry', () => {
  const view = render(<AeMotionPreview {...common} frameWidth={180} frameHeight={320}/>);
  const svg = screen.getByRole('img', {name:'AE 校准标记预览'});
  expect(svg.getAttribute('viewBox')).toBe('0 0 180 320');
  const marks = view.container.querySelectorAll('[data-motion-layer] rect');
  expect([...marks].map(mark=>[mark.getAttribute('width'),mark.getAttribute('height')])).toEqual([
    ['32','77'], ['14','38'], ['14','38']
  ]);
  expect(Number(marks[0].getAttribute('x')) + 16).toBeCloseTo(63);
  expect(Number(marks[0].getAttribute('y')) + 38.5).toBe(160);
  expect(screen.queryByRole('button', {name: /查看原片/})).toBeNull();
  const slider = screen.getByRole('slider');
  fireEvent.keyDown(slider,{key:'ArrowRight'});
  expect((slider as HTMLInputElement).valueAsNumber).toBeCloseTo(.265);
  fireEvent.keyDown(slider,{key:'Home'});
  expect((slider as HTMLInputElement).valueAsNumber).toBe(.25);
});

test.each([
  {frameWidth: undefined}, {coverageEnd: .25}, {sourceStart: -1}, {curves: []},
  {curves:[{...x, legacy:true}]}, {curves:[{...x, interpolation:'hold'}]},
  {curves:[{...x, unit:'像素'}]}, {curves:[x,x]}, {curves:[{...x, property:'character_scale'}]},
  {curves:[{...x, points:[{time:.25,value:0},{time:1.75,value:Infinity}]}]},
  {curves:[{...x, points:[{time:.5,value:0},{time:1.75,value:1}]}]},
  {curves:[{...x, points:[{time:.25,value:0},{time:1,value:0},{time:.5,value:1},{time:1.75,value:1}]}]},
])('does not present unusable geometry or curves as a measured animation', (patch) => {
  const {container} = render(<AeMotionPreview {...common} {...patch}/>);
  expect(container.childElementCount).toBe(0);
});


test('steps through distinct key times from all channels without rounding the source position', () => {
  const onSeek = vi.fn();
  const rotation = {...x, property:'rotation', unit:'角度（°）',
    points:[{time:.25,value:0},{time:.43751,value:7},{time:1.75,value:0}]};
  render(<AeMotionPreview {...common} curves={[x,rotation]} onSeekSource={onSeek}/>);
  const previous = screen.getByRole('button', {name:'上一个关键帧'});
  const next = screen.getByRole('button', {name:'下一个关键帧'});
  expect((previous as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(next);
  expect((screen.getByRole('slider') as HTMLInputElement).valueAsNumber).toBe(.43751);
  fireEvent.click(screen.getByRole('button', {name:/查看原片/}));
  expect(onSeek).toHaveBeenCalledWith(10 + .43751);
  fireEvent.change(screen.getByRole('slider'),{target:{value:'.45'}});
  fireEvent.click(previous);
  expect((screen.getByRole('slider') as HTMLInputElement).valueAsNumber).toBe(.43751);
  fireEvent.keyDown(screen.getByRole('slider'),{key:'End'});
  expect((next as HTMLButtonElement).disabled).toBe(true);
});
