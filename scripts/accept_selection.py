"""Frozen, real-model acceptance on synthetic media and an independent data root."""
import argparse
import json
import os
import queue
import shutil
import sqlite3
import subprocess
import threading
import time
from fractions import Fraction
from pathlib import Path

import av
import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def fixture(path):
    fps, sr, duration = 24, 44100, 12
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 46)
    with av.open(str(path), 'w') as out:
        video = out.add_stream('libx264', rate=fps)
        video.width, video.height, video.pix_fmt = 960, 540, 'yuv420p'
        audio = out.add_stream('aac', rate=sr)
        audio.layout = 'mono'
        for i in range(fps * duration):
            scene = i // (4 * fps)
            image = Image.new('RGB', (960, 540), [(18, 48, 80), (112, 42, 34), (35, 96, 60)][scene])
            draw = ImageDraw.Draw(image)
            for x in range(30, 930, 60):
                draw.rectangle((x, 70, x + 25, 100), fill='#8ea0c0')
            shift = i % (4 * fps) * 2
            draw.rectangle((70 + shift, 200, 250 + shift, 350), fill='#f0ac53')
            draw.text((80, 390), 'こんにちは MRA 2026', font=font, fill='white')
            draw.text((80, 455), '中文 OCR 测试', font=font, fill='white')
            frame = av.VideoFrame.from_image(image)
            frame.pts, frame.time_base = i, Fraction(1, fps)
            for packet in video.encode(frame):
                out.mux(packet)
        for packet in video.encode():
            out.mux(packet)
        y = np.zeros(sr * duration, np.float32)
        pulse = .8 * np.sin(2 * np.pi * 1000 * np.arange(int(.03 * sr)) / sr)
        pulse *= np.exp(-np.arange(len(pulse)) / (sr * .007))
        for t in np.arange(.5, duration, .5):
            at = round(t * sr)
            y[at:at + len(pulse)] += pulse
        for i in range(0, len(y), 1024):
            frame = av.AudioFrame.from_ndarray(y[None, i:i + 1024], format='fltp', layout='mono')
            frame.sample_rate, frame.pts, frame.time_base = sr, i, Fraction(1, sr)
            for packet in audio.encode(frame):
                out.mux(packet)
        for packet in audio.encode():
            out.mux(packet)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--settings', type=Path, required=True)
    parser.add_argument('--library', type=Path, help='Read-only snapshot of an existing library to preserve')
    args = parser.parse_args()
    root = args.data_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    assert not (root / 'mra_library.db').exists(), 'Acceptance requires a fresh independent library'
    original_library = {}
    if args.library:
        with sqlite3.connect(args.library.resolve().as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(root / 'mra_library.db') as target:
            source.backup(target)
            for table in ('projects', 'shots', 'tags', 'shot_tags', 'project_tags', 'automatic_shot_tags', 'videos'):
                original_library[table] = source.execute(f'SELECT * FROM {table}').fetchall()
    shutil.copy2(args.settings, root / 'settings.json')
    video = root / 'synthetic-selection.mp4'
    fixture(video)
    env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'}}
    lines, process = [], None

    def start():
        nonlocal process
        ready = queue.Queue()
        process = subprocess.Popen([str(args.executable.resolve()), '--data-dir', str(root), '--port', '0',
                                    '--instance-id', 'selection-acceptance'], cwd=root, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8', errors='replace')

        def consume(stream, readiness=False):
            for line in stream:
                lines.append(line)
                if readiness and line.startswith('MRA_READY '):
                    ready.put(json.loads(line[10:]))

        threading.Thread(target=consume, args=(process.stdout, True), daemon=True).start()
        threading.Thread(target=consume, args=(process.stderr,), daemon=True).start()
        info = ready.get(timeout=90)
        print(json.dumps({'stage': 'ready', 'identity': info}), flush=True)
        return httpx.Client(base_url=f"http://127.0.0.1:{info['port']}/api/v1", timeout=300, trust_env=False,
                            limits=httpx.Limits(max_keepalive_connections=0))

    def stop():
        if process is not None and process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            process.wait(timeout=15)

    def check(response):
        assert response.is_success, response.text
        return response.json()

    def finished(client, rid):
        deadline = time.monotonic() + 900
        stage = None
        while time.monotonic() < deadline:
            record = check(client.get(f'/selection-analyses/{rid}'))
            current = record.get('progress', {}).get('message')
            if current != stage:
                print(json.dumps({'record': rid, 'stage': current}, ensure_ascii=False), flush=True)
                stage = current
            if record['status'] not in ('preparing', 'running'):
                assert record['status'] == 'done', record
                return record
            time.sleep(1)
        raise AssertionError('Acceptance job timed out')

    try:
        with start() as client:
            check(client.post('/video/import', json={'path': str(video)}))
            pid = check(client.post('/project/save'))['project_id']
            check(client.post('/video/analyze', json={'mode': 'basic'}))
            before = check(client.get('/shots'))
            with sqlite3.connect(root / 'mra_library.db') as conn:
                original_rows = conn.execute('SELECT * FROM shots ORDER BY id').fetchall()
            position = check(client.get(f'/projects/{pid}/frame-position', params={'time': .15}))
            request = {'kind': 'frame', 'frame': position['frame'], 'preview_token': position['preview_token']}
            rid = check(client.post(f'/projects/{pid}/selection-analyses', json=request))['record_id']
            frame = finished(client, rid)
            static = frame['result']['frame']
            assert not static['analysis_error'], static
            assert static['text_regions'] and any('MRA' in r['text'] for r in static['text_regions']), static['text_regions']
            assert 'motion' not in static and 'audio' not in frame['result']
            assert frame['result']['time']['actual_time'] == .125
            assert client.get(f'/selection-analyses/{rid}/assets/frame.png').is_success
            clip_id = check(client.post(f'/projects/{pid}/selection-analyses',
                                        json={'kind': 'clip', 'start': 3.5, 'end': 8.5}))['record_id']
            clip = finished(client, clip_id)
            shots = clip['result']['shots']
            assert len(shots) == 3, shots
            assert all(not s['analysis_error'] for s in shots), shots
            assert all(s['text_regions'] for s in shots)
            assert shots[0]['rhythm']['status'] == 'not_cut'
            assert clip['result']['audio']['tempo_bpm'] is None
            assert check(client.get('/shots')) == before
            with sqlite3.connect(root / 'mra_library.db') as conn:
                assert conn.execute('SELECT * FROM shots ORDER BY id').fetchall() == original_rows
                for table, rows in original_library.items():
                    current_rows = conn.execute(f'SELECT * FROM {table}').fetchall()
                    assert all(row in current_rows for row in rows), f'Original {table} changed'
            exported = []
            for record_id in (rid, clip_id):
                for format in ('json', 'markdown'):
                    path = check(client.post(f'/selection-analyses/{record_id}/export', json={'format': format}))['path']
                    assert Path(path).is_file()
                    exported.append(path)
            check(client.put('/session', json={'project_id': pid, 'shot_id': shots[0]['shot_id']}))
        stop()
        with start() as client:
            assert check(client.get(f'/projects/{pid}/selection-analyses'))['total'] == 2
            assert check(client.get(f'/selection-analyses/{rid}'))['result'] == frame['result']
            assert check(client.get(f'/selection-analyses/{clip_id}'))['result'] == clip['result']
            check(client.post(f'/library/projects/{pid}/load'))
            reopened = check(client.get('/shots'))
            def comparable(data):
                # Loading assigns persisted IDs and portable asset paths; analysis values are invariant.
                return [{**{k: v for k, v in s.items() if k not in ('library_id', 'frames')},
                         'frames': [Path(f).name for f in s['frames']]} for s in data['shots']]
            assert comparable(reopened) == comparable(before)
            with sqlite3.connect(root / 'mra_library.db') as conn:
                assert conn.execute('SELECT * FROM shots ORDER BY id').fetchall() == original_rows
        report = {'result': 'passed', 'frame': rid, 'clip': clip_id, 'project_id': pid,
                  'frame_time': .125, 'clip_range': [3.5, 8.5], 'clip_shots': len(shots),
                  'ocr_text': [r['text'] for r in static['text_regions']], 'exported': exported,
                  'original_shots_preserved': len(before['shots']), 'reopen': True}
        report['existing_library_shots_preserved'] = len(original_library.get('shots', []))
        (root / 'selection_acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        if process is not None:
            print(json.dumps({'backend_exit_code_before_cleanup': process.poll()}), flush=True)
        stop()
        (root / 'selection_backend.log').write_text(''.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
