import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { api, type LibraryShotDetail } from '../services/api';
import { LibraryView } from './LibraryWorkspace';

afterEach(() => vi.restoreAllMocks());

test('library AE keyframes seek the inspected source and keep the player paused', async () => {
  const shot = {
    id: 42, project_id: 7, shot_id: 'library-reference', start_time: 12, end_time: 14, duration: 2,
    thumbnail_path: null, motion_type: 'pan', has_text: false, tags: [], motion_confidence: .9, scene_type: '',
  };
  const detail: LibraryShotDetail = {
    ...shot, source: {id: 7, name: 'Reference', video_filename: 'other-project.mp4', video_path: 'other-project.mp4',
      video_hash: 'source', video_duration: 20, analysis_status: 'done', updated_at: ''},
    manual_tags: [], automatic_tags: [], typography_tracks: [], observations: {}, motion: {}, motion_summary: {},
    typography: {}, ae_hypothesis: {}, analysis_version: '', pipeline_version: '',
    provider_versions: {}, measured_motion: {frame_width: 320, frame_height: 180},
    ae_recipe: {animation_plan: {evidence_source: 'measured', source_start: 12, source_end: 14, duration: 2,
      coverage_start: 12.125, coverage_end: 13.875, curves: [{property: 'position_x', unit: '画面宽度（%）',
        interpolation: 'linear', points: [{time: .125, value: 0}, {time: 1.875, value: 10}]}]}},
  };
  vi.spyOn(api, 'listLibraryProjects').mockResolvedValue({projects: []});
  vi.spyOn(api, 'listTags').mockResolvedValue({tags: []});
  vi.spyOn(api, 'searchLibrary').mockResolvedValue({shots: [shot], motion_types: []});
  vi.spyOn(api, 'getLibraryShot').mockResolvedValue(detail);
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue();
  const {container} = render(<LibraryView/>);
  fireEvent.click(await screen.findByRole('button', {name: /library-reference/}));
  fireEvent.click(await screen.findByText('AE 制作建议'));
  fireEvent.click(screen.getByRole('button', {name: '查看原片 12.125 秒'}));
  const video = container.querySelector('video')!;
  expect(video.getAttribute('src')).toBe(api.librarySourceUrl(42));
  fireEvent.loadedMetadata(video);
  expect(video.currentTime).toBe(12.125);
  expect(pause).toHaveBeenCalled();
  expect(play).not.toHaveBeenCalled();
  Object.defineProperty(video, 'readyState', {value: 1, configurable: true});
  fireEvent.keyDown(screen.getByRole('slider'), {key: 'End'});
  fireEvent.click(screen.getByRole('button', {name: '查看原片 13.875 秒'}));
  expect(video.currentTime).toBe(13.875);
  fireEvent.click(screen.getByRole('button', {name: '播放镜头'}));
  expect(video.currentTime).toBe(12);
  expect(play).toHaveBeenCalledOnce();
});
