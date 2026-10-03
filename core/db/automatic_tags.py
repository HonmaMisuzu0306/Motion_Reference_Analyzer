"""Deterministic labels derived from stored evidence; no additional model."""
from db.models import LibraryShot


def automatic_tags(shot: LibraryShot) -> set[str]:
    tags = set()
    aliases = {'push_in': 'camera_push', 'pull_out': 'camera_pull',
               'zoom_in': 'zoom', 'zoom_out': 'zoom', 'rotate': 'rotation'}
    allowed = {'camera_push', 'camera_pull', 'pan_left', 'pan_right', 'zoom',
               'rotation', 'parallax', 'shake', 'tilt_up', 'tilt_down'}
    motion = aliases.get(shot.motion_type, shot.motion_type)
    if motion in allowed:
        tags.add(motion)
    if shot.scene_type in {'title_card', 'lyrics'}:
        tags.add(shot.scene_type)
    strength = shot.measured_motion.get('motion_strength')
    if strength in {'high', 'low'} and shot.measured_motion.get('status') == 'ok':
        tags.add(f'{strength}_motion')
    if shot.has_text:
        tags.add('typography')
    for track in shot.typography_tracks:
        role = (track.get('typography_analysis') or {}).get('role')
        if role == 'title':
            tags.add('title_card')
        elif role == 'lyrics':
            tags.add('lyrics')
        if track.get('appearance') == 'fade':
            tags.add('fade_text')
        if track.get('movement', '').startswith('slide'):
            tags.add('slide_text')
    return tags
