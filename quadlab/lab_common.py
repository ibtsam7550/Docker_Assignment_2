import csv
import json
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
GROUP = 'quadlab.group=app'
NETWORK = 'quadlab_net'
IMAGE = 'quadlab-app:local'
NGINX = 'quadlab-nginx'
RESULTS = ROOT / 'results'


def stamp():
    epoch = time.time()
    return {'timestamp': datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='milliseconds'),
            'epoch': round(epoch, 6)}


def command(*args, timeout=45):
    p = subprocess.run(list(args), cwd=ROOT, text=True, capture_output=True,
                       timeout=timeout, env=dict(os.environ, LC_ALL='C'))
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or str(args))
    return p.stdout.strip()


def docker(*args, **kwargs):
    return command('docker', *args, **kwargs)


def apps(all_states=False):
    ids = docker('ps', '-aq' if all_states else '-q', '--filter', 'label=' + GROUP).split()
    return json.loads(docker('inspect', *ids)) if ids else []


def healthy(c):
    return (c['State']['Running'] and
            c['State'].get('Health', {}).get('Status') == 'healthy' and
            bool(c['NetworkSettings']['Networks'].get(NETWORK, {}).get('IPAddress')))


def append_csv(name, row):
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / name
    is_new = not path.exists() or path.stat().st_size == 0
    with path.open('a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if is_new:
            w.writeheader()
        w.writerow(row)


def event(action, count, detail):
    row = dict(**stamp(), action=action, container_count=count, detail=detail)
    append_csv('scaling_events.csv', row)
    print(f"{row['timestamp']} {action}: {detail} [containers={count}]", flush=True)
