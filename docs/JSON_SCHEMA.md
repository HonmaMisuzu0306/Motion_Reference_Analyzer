# JSON Schema

## Shot Schema

```json
{
  "shot_id": "shot_032",
  "time": {
    "start": 12.43,
    "end": 14.02,
    "duration": 1.59
  },
  "frames": ["shot_032_01.jpg", "shot_032_02.jpg", "shot_032_03.jpg"],
  "observations": {},
  "motion": {},
  "typography": {},
  "visual_effects": [],
  "ae_hypothesis": {},
  "ae_recipe": {}
}
```

## Project Schema

```json
{
  "project_name": "untitled",
  "video": {
    "filename": "ref.mp4",
    "duration": 92.31,
    "width": 1920,
    "height": 1080,
    "fps": 23.976,
    "codec": "h264",
    "bitrate": 0,
    "has_audio": true
  },
  "shots": [],
  "analysis_status": "idle"
}
```

## Analysis Status

- `idle`
- `imported`
- `processing`
- `scene_detect`
- `extract_frames`
- `vision_analysis`
- `generating_recipe`
- `done`
- `error`
