#!/usr/bin/env python3
"""Host-side autoscaler; only Python's standard library and Docker CLI are needed."""
import argparse
import fcntl
import json
import math
import subprocess
import time
import uuid
from lab_common import ROOT, NETWORK, IMAGE, NGINX, apps, healthy, docker, stamp, append_csv, event

CONF = ROOT / 'nginx/generated/default.conf'


def worker_pids():
    lines = docker('top', NGINX, '-eo', 'pid,args').splitlines()[1:]
    return {line.split()[0] for line in lines if 'nginx: worker process' in line}


def configuration(containers):
    ips = sorted(c['NetworkSettings']['Networks'][NETWORK]['IPAddress'] for c in containers if healthy(c))
    if not ips:
        return 'server { listen 80; location / { return 503; } }\n'
    servers = '\n'.join(f'    server {ip}:8000 max_fails=1 fail_timeout=5s;' for ip in ips)
    # Default Nginx upstream policy is round-robin. No upstream keepalive pool.
    return '''upstream quadratic {
%s
}
server {
    listen 80;
    location / {
        proxy_pass http://quadratic;
        proxy_http_version 1.1;
        proxy_set_header Connection close;
        proxy_set_header Host $host;
        proxy_connect_timeout 2s;
        proxy_read_timeout 60s;
        proxy_next_upstream error timeout http_502 http_503 http_504;
        proxy_next_upstream_tries 4;
        add_header X-Upstream $upstream_addr always;
    }
}
''' % servers


def write_conf(text):
    CONF.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONF.with_suffix('.tmp')
    temporary.write_text(text)
    temporary.replace(CONF)  # Mount the whole directory so atomic replacements are visible.


def sync_nginx(containers, force=False):
    new = configuration(containers)
    old = CONF.read_text() if CONF.exists() else ''
    if new == old and not force:
        return set()
    running = bool(docker('ps', '-q', '--filter', 'name=^/' + NGINX + '$'))
    write_conf(new)
    if not running:
        return set()
    try:
        docker('exec', NGINX, 'nginx', '-t')
        previous = worker_pids()
        if not previous:
            raise RuntimeError('Cannot identify Nginx workers; refusing reload/removal')
        docker('exec', NGINX, 'nginx', '-s', 'reload')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if worker_pids() - previous:
                return previous
            time.sleep(0.25)
        raise RuntimeError('Nginx did not start new workers after reload')
    except Exception:
        write_conf(old)
        # Restore the last configuration if a reload partially succeeded; never stop an app.
        try:
            docker('exec', NGINX, 'nginx', '-t')
            docker('exec', NGINX, 'nginx', '-s', 'reload')
        except Exception:
            pass
        raise


def metrics(containers):
    now = stamp()
    count = len(containers)
    if not count:
        append_csv('metrics.csv', dict(**now, container_count=0, healthy_count=0,
                                       avg_cpu='', avg_memory=''))
        return None
    # One call samples all application containers; never accidentally sample every Docker container.
    raw = docker('stats', '--no-stream', '--format', '{{json .}}',
                 *[c['Id'] for c in containers], timeout=30)
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    by_name = {r['Name'].lstrip('/'): r for r in rows}
    values = []
    for c in containers:
        name = c['Name'].lstrip('/')
        if name not in by_name:
            raise RuntimeError('Incomplete Docker stats sample; no scaling decision this cycle')
        r = by_name[name]
        cpu, memory = float(r['CPUPerc'].rstrip('%')), float(r['MemPerc'].rstrip('%'))
        if not math.isfinite(cpu) or not math.isfinite(memory):
            raise RuntimeError('Invalid Docker stats sample')
        values.append((c, name, cpu, memory, r['MemUsage']))
    # All rows in one Docker sample share the end-of-sample timestamp.
    now = stamp()
    for c, name, cpu, memory, usage in values:
        append_csv('container_metrics.csv', dict(**now, container=name,
            container_id=c['Id'][:12], healthy=healthy(c), cpu_percent=cpu,
            memory_percent=memory, memory_usage=usage))
    cpu = sum(v[2] for v in values) / count
    memory = sum(v[3] for v in values) / count
    append_csv('metrics.csv', dict(**now, container_count=count,
        healthy_count=sum(healthy(c) for c in containers), avg_cpu=round(cpu, 3),
        avg_memory=round(memory, 3)))
    print(f"{now['timestamp']} count={count} avg_cpu={cpu:.1f}% avg_memory={memory:.1f}%", flush=True)
    return cpu


def scale_out(policy):
    name = 'quadlab-extra-' + uuid.uuid4().hex[:8]
    cid = docker('run', '-d', '--name', name, '--network', NETWORK,
                 '--label', 'quadlab.group=app', '--cpus', '1', '--memory', '1g',
                 '--memory-swap', '1g', '--stop-timeout', '70',
                 '--publish', '127.0.0.1::8000',
                 '--restart', 'unless-stopped', IMAGE)
    event('starting', len(apps()), name)
    deadline = time.monotonic() + policy['startup_timeout_seconds']
    while time.monotonic() < deadline:
        current = apps()
        if any(c['Id'] == cid and healthy(c) for c in current):
            sync_nginx(current)
            event('scale_out', len(current), name + ' healthy and added to Nginx')
            return
        time.sleep(2)
    # Never registered in Nginx, so removing this failed startup cannot drain live traffic.
    docker('rm', '-f', cid)
    raise RuntimeError('New container failed its health check: ' + name)


def scale_in(containers, policy):
    # Prefer removing an unhealthy container, otherwise remove the most recently created one.
    victim = sorted(containers, key=lambda c: (not healthy(c), c['Created']))[-1]
    remaining = [c for c in containers if c['Id'] != victim['Id']]
    if not any(healthy(c) for c in remaining):
        raise RuntimeError('Scale-in skipped: no healthy remaining backend')
    # Capture ALL old workers, including ones already draining a previous configuration.
    old_workers = sync_nginx(remaining, force=True)
    if not old_workers:
        raise RuntimeError('Nginx is not running; refusing scale-in')
    event('draining', len(containers), victim['Name'] + ' excluded from new Nginx workers')
    deadline = time.monotonic() + policy['drain_timeout_seconds']
    while time.monotonic() < deadline:
        if not (old_workers & worker_pids()):
            docker('stop', '--time', '70', victim['Id'], timeout=80)
            docker('rm', victim['Id'])
            event('scale_in', len(apps()), victim['Name'] + ' drained, stopped and removed')
            return
        time.sleep(1)
    # Leave the app alive if old requests are still active; restore membership next cycle.
    raise RuntimeError('Drain timeout: container kept running; removal cancelled')


def load_policy():
    p = json.loads((ROOT / 'policy.json').read_text())
    for key in ('min_containers', 'max_containers', 'consecutive_samples'):
        if type(p[key]) is not int:
            raise ValueError(key + ' must be an integer')
    if not 1 <= p['min_containers'] <= p['max_containers'] <= 4:
        raise ValueError('Use 1 <= min_containers <= max_containers <= 4')
    if not 0 <= p['scale_in_cpu'] < p['scale_out_cpu'] <= 100:
        raise ValueError('Invalid CPU thresholds')
    for key in ('interval_seconds', 'consecutive_samples', 'cooldown_seconds',
                'startup_timeout_seconds', 'drain_timeout_seconds'):
        if not math.isfinite(p[key]) or p[key] <= 0:
            raise ValueError(key + ' must be positive and finite')
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sync-only', action='store_true', help='write/reload Nginx config and exit')
    a = parser.parse_args()
    # macOS/Linux advisory lock prevents two copies from scaling the same group.
    with (ROOT / '.autoscaler.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another autoscaler is already running in this folder.')
        p = load_policy()
        current = apps()
        sync_nginx(current, force=True)
        if a.sync_only:
            print('Nginx configuration synchronized. Healthy backends:', sum(healthy(c) for c in current))
            return
        if not docker('ps', '-q', '--filter', 'name=^/' + NGINX + '$'):
            raise SystemExit('Start Nginx first. See README step 4.')
        high = low = 0
        last_scale = time.monotonic()  # Allow an initial warm-up/cooldown.
        event('started', len(current), 'Policy: ' + json.dumps(p, sort_keys=True))
        from lab_common import RESULTS
        (RESULTS / 'policy_snapshot.json').write_text(json.dumps(p, indent=2))
        try:
            while True:
                cycle = time.monotonic()
                try:
                    current = apps()
                    sync_nginx(current)
                    average = metrics(current)
                    high = high + 1 if average is not None and average > p['scale_out_cpu'] else 0
                    low = low + 1 if average is not None and average < p['scale_in_cpu'] else 0
                    if cycle - last_scale >= p['cooldown_seconds']:
                        count = len(current)
                        if count < p['min_containers'] or (high >= p['consecutive_samples'] and count < p['max_containers']):
                            scale_out(p)
                            last_scale, high, low = time.monotonic(), 0, 0
                        elif count > p['max_containers'] or (low >= p['consecutive_samples'] and count > p['min_containers']):
                            scale_in(current, p)
                            last_scale, high, low = time.monotonic(), 0, 0
                except (RuntimeError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as e:
                    event('error', len(current), str(e))
                    high = low = 0
                    last_scale = time.monotonic()  # Back off after failures, too.
                time.sleep(max(0.1, p['interval_seconds'] - (time.monotonic() - cycle)))
        except KeyboardInterrupt:
            event('stopped', len(apps()), 'Controller stopped; containers remain running')


if __name__ == '__main__':
    main()
