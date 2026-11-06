import type { TextTrack, TypographyRecipe } from '../services/api';

export function findTypographyRecipe(
  recipes: TypographyRecipe[],
  track: Pick<TextTrack, 'track_id' | 'canonical_text' | 'start_time' | 'end_time'>,
) {
  const identified = track.track_id && recipes.find(recipe => recipe.track_id === track.track_id);
  if (identified) return identified;

  // Older saved recipes used the track's source times and text without its ID.
  const legacy = recipes.filter(recipe => !recipe.track_id && recipe.text === track.canonical_text
    && recipe.start_time === track.start_time && recipe.end_time === track.end_time);
  return legacy.length === 1 ? legacy[0] : undefined;
}
