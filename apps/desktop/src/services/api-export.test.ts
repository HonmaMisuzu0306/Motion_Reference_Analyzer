import { afterEach, expect, test, vi } from 'vitest';

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

test('AE exports address the selected current shot, saved library shot, or selection record', async () => {
  const response = {path: 'E:\\exports\\shot.jsx', message: '已导出'};
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify(response), {status: 200}));
  vi.stubGlobal('fetch', fetch);
  vi.resetModules();
  const {api} = await import('./api');
  expect(await api.exportShotAe('shot / 1')).toEqual(response);
  expect(await api.exportLibraryAe(37)).toEqual(response);
  expect(await api.exportSelectionAe('selection / 2', 'shot / 3')).toEqual(response);
  expect(fetch.mock.calls.map(([url]) => new URL(url).pathname)).toEqual([
    '/api/v1/shots/shot%20%2F%201/export/ae',
    '/api/v1/library/shots/37/export/ae',
    '/api/v1/selection-analyses/selection%20%2F%202/shots/shot%20%2F%203/export/ae',
  ]);
  expect(fetch.mock.calls.every(([url]) => new URL(url).search === '')).toBe(true);
  fetch.mockClear();
  await api.exportShotAe('shot / 1', true);
  await api.exportLibraryAe(37, true);
  await api.exportSelectionAe('selection / 2', 'shot / 3', true);
  expect(fetch.mock.calls.map(([url]) => new URL(url).search)).toEqual(Array(3).fill('?padded=true'));
  expect(fetch.mock.calls.every(([, options]) => options.method === 'POST' && options.body === undefined)).toBe(true);
});

test('AE export preserves a rejected plan reason for the user interface', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({detail: '轨迹不连续，请重新分析'}), {status: 409})));
  vi.resetModules();
  const {api} = await import('./api');
  await expect(api.exportLibraryAe(37)).rejects.toThrow('轨迹不连续，请重新分析');
});

test('two-pin measurement and export send scoped server ids and the same-layer confirmation', async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response('{}', {status: 200}));
  vi.stubGlobal('fetch', fetch); vi.resetModules();
  const {api} = await import('./api');
  const identity = 'c'.repeat(64);
  await api.trackTwoPins('s / 1', identity, 'a', 'b', 27);
  await api.exportTwoPinAe('s / 1', 'p / 2', identity, 27);
  expect(fetch.mock.calls.map(([url, options]) => [new URL(url).pathname, options.method, JSON.parse(options.body)])).toEqual([
    ['/api/v1/shots/s%20%2F%201/two-pin-track', 'POST', {identity, library_id:27, track_a_id:'a', track_b_id:'b', same_layer_confirmed:true}],
    ['/api/v1/shots/s%20%2F%201/two-pin-tracks/p%20%2F%202/export/ae', 'POST', {identity, library_id:27}],
  ]);
});
