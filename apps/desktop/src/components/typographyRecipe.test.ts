import { expect, test } from 'vitest';
import type { TypographyRecipe } from '../services/api';
import { findTypographyRecipe } from './typographyRecipe';

const track = {track_id: 'second', canonical_text: 'chorus', start_time: 2, end_time: 3};
const makeRecipe = (id: string | null, start = 2) => ({
  track_id: id, text: 'chorus', start_time: start, end_time: start + 1,
} as TypographyRecipe);

test('repeated text matches its own track even if both occurrences share a timestamp', () => {
  const first = makeRecipe('first'), second = makeRecipe('second');
  expect(findTypographyRecipe([first, second], track)).toBe(second);
  expect(findTypographyRecipe([first], track)).toBeUndefined();
});

test('legacy duplicate captions match by time, and ambiguous matches are withheld', () => {
  const first = makeRecipe(null, 0), second = makeRecipe(null);
  expect(findTypographyRecipe([first, second], track)).toBe(second);
  expect(findTypographyRecipe([second, {...second}], track)).toBeUndefined();
});
