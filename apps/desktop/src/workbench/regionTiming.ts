import type { RegionResult } from './regionTypes';

type Samples = RegionResult['track']['samples'];
type Sample = Samples[number];

function distance(a: Sample, b: Sample) {
  return Math.hypot(b.center_x_px - a.center_x_px, b.center_y_px - a.center_y_px);
}

export function summarizeRegionTiming(samples: Samples, width: number, height: number) {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0 || samples.length < 2) {
    return null;
  }
  let farthestIndex = 0;
  let excursionPx = 0;
  const path = [0];
  for (let i = 0; i < samples.length; i++) {
    const p = samples[i];
    if (!Number.isFinite(p.source_time) || p.source_time < 0 ||
      !Number.isFinite(p.center_x_px) || p.center_x_px < 0 || p.center_x_px > width ||
      !Number.isFinite(p.center_y_px) || p.center_y_px < 0 || p.center_y_px > height) return null;
    if (i === 0) continue;
    const dt = p.source_time - samples[i - 1].source_time;
    // A verified track stops before a gap greater than half a second.
    if (dt <= 0 || dt > .5) return null;
    path.push(path[i - 1] + distance(samples[i - 1], p));
    const excursion = distance(samples[0], p);
    if (excursion > excursionPx) {
      excursionPx = excursion;
      farthestIndex = i;
    }
  }
  if (excursionPx < Math.max(1, .001 * Math.hypot(width, height))) return null;

  // The extra sample at the end of a shot may be only a millisecond later.
  // Compare the shortest measured span reaching 100 ms for each endpoint.
  // For a shorter track, use its full measured duration.
  const last = samples[samples.length - 1];
  const window = Math.min(.1, last.source_time - samples[0].source_time);
  let fastestPxPerSec = -1;
  let fastestStartIndex = 0;
  let fastestEndIndex = 1;
  let left = 0;
  for (let end = 1; end < samples.length; end++) {
    const time = samples[end].source_time;
    while (left + 1 < end && time - samples[left + 1].source_time >= window - 1e-9) left++;
    const dt = time - samples[left].source_time;
    if (dt < window - 1e-9) continue;
    const speed = (path[end] - path[left]) / dt;
    if (speed > fastestPxPerSec + 1e-8) {
      fastestPxPerSec = speed;
      fastestStartIndex = left;
      fastestEndIndex = end;
    }
  }
  return {farthestIndex, fastestStartIndex, fastestEndIndex, excursionPx, fastestPxPerSec, pathPx: path[path.length - 1],
    displacementPx: distance(samples[0],last)};
}
