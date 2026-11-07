import { afterEach, expect, test, vi } from 'vitest';

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

test.each([32, null, undefined])('all three ROI endpoints use only the selected library filter (%s)', async libraryId => {
  const fetch = vi.fn().mockImplementation(async () => new Response('{}'));
  vi.stubGlobal('fetch', fetch);
  vi.resetModules();
  const {api} = await import('./api');
  const box = {x:.1, y:.2, width:.3, height:.4};
  const request = {identity:'digest', anchor_time:3.25, end_time:4, box};
  await api.regionFrame('shot/1', 'digest', 3.25, libraryId);
  await api.trackRegion('shot/1', request, libraryId);
  await api.exportRegionAe('shot/1', 'track/2', 'digest', libraryId);
  const [frame, track, exported] = fetch.mock.calls;
  expect(new URL(frame[0]).pathname).toBe('/api/v1/shots/shot%2F1/region-frame');
  expect(new URL(frame[0]).searchParams.get('library_id')).toBe(libraryId == null ? null : String(libraryId));
  const filter = libraryId == null ? {} : {library_id: libraryId};
  expect(JSON.parse(track[1].body)).toEqual({...request, ...filter});
  expect(JSON.parse(exported[1].body)).toEqual({identity:'digest', ...filter});
});
