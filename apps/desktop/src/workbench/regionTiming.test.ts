import { expect, test } from 'vitest';
import { summarizeRegionTiming } from './regionTiming';

const p = (t: number, x: number, y = 10) => ({source_time: t, center_x_px: x, center_y_px: y});

test('a return to the origin keeps its farthest pose and the fastest measured span', () => {
  const value = summarizeRegionTiming([p(3,10),p(3.2,18),p(3.32,42),p(3.72,10)],640,360)!;
  expect(value.farthestIndex).toBe(2);
  expect(value.fastestStartIndex).toBe(1);
  expect(value.fastestEndIndex).toBe(2);
  expect(value.fastestPxPerSec).toBeCloseTo(200);
  expect(value.displacementPx).toBe(0);
  expect(value.pathPx).toBe(64);
});

test('a very short terminal sample does not turn subpixel error into a speed peak', () => {
  const value = summarizeRegionTiming([p(0,10),p(.125,30),p(.25,30),p(.251,30.5)],640,360)!;
  expect([value.fastestStartIndex,value.fastestEndIndex,value.fastestPxPerSec]).toEqual([0,1,160]);
  const short = summarizeRegionTiming([p(0,10),p(.04,13,14)],640,360)!;
  expect(short.fastestPxPerSec).toBeCloseTo(125);
  expect(short.excursionPx).toBe(5);
  const reversal = summarizeRegionTiming([p(0,10),p(.04,20),p(.095,10),p(.1,10)],640,360)!;
  expect(reversal.fastestPxPerSec).toBeCloseTo(200);
});

test('a static target, a time gap or a position outside the image has no timing guidance', () => {
  for (const sample of [p(.125,10.2),p(.125,NaN),p(.125,700),p(.501,40),p(0,40)]) {
    expect(summarizeRegionTiming([p(0,10),sample],640,360)).toBeNull();
  }
});
