"""Generate 10k synthetic shots in an isolated DB and time common retrieval queries."""
import json
import sys
import time
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))

from db import ReferenceLibrary  # noqa: E402
from db.connection import close_connection, set_db_path  # noqa: E402
from db.models import FilterSet  # noqa: E402
from schemas import Project, Shot, TimeRange  # noqa: E402


def main():
    out = ROOT / 'output' / 'library_benchmark'
    out.mkdir(exist_ok=True)
    set_db_path(out / '10k.db')
    lib = ReferenceLibrary()
    shots = [Shot(shot_id=f'shot_{i:05d}', time=TimeRange(start=i*2, end=i*2+(i%5+1)*.5, duration=(i%5+1)*.5),
                  observations={'description': f'reference camera push scene {i}'},
                  motion={'type': 'camera_push' if i%2 else 'static', 'confidence': .9 if i%3 else .4},
                  typography={'has_text': bool(i%2)}, ae_recipe={'notes': 'synthetic performance fixture'}) for i in range(10000)]
    started = time.perf_counter()
    pid = lib.save_analysis(Project(project_name='10k performance fixture', shots=shots))
    insertion = time.perf_counter()-started
    queries = {'page': FilterSet(limit=48), 'keyword': FilterSet(query='camera push', limit=48),
               'motion': FilterSet(motion_types=['camera_push'], limit=48),
               'typography_duration': FilterSet(has_text=True, max_duration=2, limit=48),
               'confidence_source': FilterSet(min_confidence=.8, project_id=pid, limit=48),
               'combined_tags': FilterSet(query='camera push', motion_types=['camera_push'], has_text=True,
                                         max_duration=2, min_confidence=.8, tags=['typography', 'camera_push'], limit=48)}
    evidence = {'shots': len(lib.list_shots(pid)), 'save_seconds': round(insertion, 3), 'queries': {}}
    for name, query in queries.items():
        durations = []
        for _ in range(5):
            started = time.perf_counter()
            results = lib.search(query)
            durations.append((time.perf_counter()-started)*1000)
        evidence['queries'][name] = {'median_ms': round(median(durations), 2), 'max_ms': round(max(durations), 2), 'returned': len(results)}
    assert evidence['shots'] == 10000
    (out / 'result.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence, indent=2))
    close_connection()


if __name__ == '__main__':
    main()
