"""Smoke a frozen executable from an independent working directory and data root."""
import argparse
import json
import os
import queue
import subprocess
import threading
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument('--executable', type=Path, required=True)
parser.add_argument('--video', type=Path, required=True)
parser.add_argument('--data-dir', type=Path, required=True)
args = parser.parse_args()
args.data_dir.mkdir(parents=True, exist_ok=True)
env = {k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'}}
process = subprocess.Popen([str(args.executable.resolve()), '--data-dir', str(args.data_dir.resolve()),
                            '--port', '0', '--instance-id', 'frozen-acceptance'],
                           cwd=args.data_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, encoding='utf-8', errors='replace')
ready_queue = queue.Queue()
lines=[]
def consume(stream, readiness=False):
    for line in stream:
        lines.append(line)
        if readiness and line.startswith('MRA_READY '):ready_queue.put(json.loads(line[10:]))
threading.Thread(target=consume,args=(process.stdout,True),daemon=True).start()
threading.Thread(target=consume,args=(process.stderr,),daemon=True).start()
try:
    ready=ready_queue.get(timeout=60)
    client=httpx.Client(base_url=f"http://127.0.0.1:{ready['port']}/api/v1",timeout=300,trust_env=False)
    def check(response):
        assert response.is_success,response.text
        return response.json()
    check(client.post('/video/import',json={'path':str(args.video.resolve())}))
    pid=check(client.post('/project/save'))['project_id']
    assert check(client.get('/projects'))['projects'][0]['shot_count']==0
    check(client.put(f'/projects/{pid}/name',json={'name':'安装版验收 中文项目'}))
    check(client.post(f'/library/projects/{pid}/load'))
    assert client.post('/video/analyze',json={'mode':'full'}).status_code==409
    check(client.post('/video/analyze',json={'mode':'basic'}))
    status=check(client.get('/project/status'))
    assert status['shot_count']>0
    assert status['progress']['stages']['vision_analysis']['status']=='skipped'
    assert status['audio']['status']=='ok',status['audio']
    check(client.post('/export/json'))
    check(client.post('/export/markdown'))
    assert check(client.post('/project/save'))['project_id']==pid
    assert len(check(client.get('/projects'))['projects'])==1
    check(client.post(f'/library/projects/{pid}/load'))
    shots=check(client.get('/shots'))['shots']
    assert client.get(f"/shots/{shots[0]['shot_id']}/frame/{Path(shots[0]['frames'][0]).name}",params={'library_id':shots[0]['library_id']}).is_success
    print(json.dumps({'result':'passed','ready':ready,'projects':1,'shots':len(shots),
                      'audio':status['audio']['status'],'tempo':status['audio']['tempo_bpm'],
                      'data_root':str(args.data_dir.resolve())},ensure_ascii=False))
finally:
    if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
    else:process.terminate()
    process.wait(timeout=15)
    (args.data_dir/'acceptance_backend.log').write_text(''.join(lines),encoding='utf-8')
