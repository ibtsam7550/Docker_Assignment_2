#!/usr/bin/env python3
"""Stepped httperf experiment with UTC/epoch timestamps and raw logs per window."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
from lab_common import RESULTS, stamp, append_csv
from httperf_parser import parse


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8080)
    p.add_argument('--uri', default='/api/solve?work=15000')
    p.add_argument('--rates', default='50,100,150,200,250,300,500,1000,500,400,300,250,200,150,100,50,0')
    p.add_argument('--seconds', type=int, default=40, help='nominal duration of EACH rate')
    p.add_argument('--window', type=int, default=10, help='one httperf summary per window')
    p.add_argument('--idle-tail', type=int, default=40, help='extra idle seconds after the last phase')
    a = p.parse_args()
    try:
        rates = [int(x) for x in a.rates.split(',')]
        assert rates and min(rates) >= 0
        assert a.window > 0 and a.seconds > 0 and a.seconds % a.window == 0
        assert a.idle_tail >= 0 and a.idle_tail % a.window == 0
        assert 1 <= a.port <= 65535 and a.uri.startswith('/')
    except (ValueError, AssertionError):
        p.error('Use nonnegative rates, valid port/URI and positive durations divisible by --window.')
    if not shutil.which('httperf'):
        p.error('httperf is missing. On macOS: brew install httperf')
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / 'workload.csv'
    if path.exists():
        p.error('results/workload.csv exists. Archive results before starting a new experiment.')
    url = f'http://{a.host}:{a.port}{a.uri}'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=10) as response:
        if response.status != 200:
            raise SystemExit('Nginx preflight did not return HTTP 200')
    (RESULTS / 'workload_settings.json').write_text(json.dumps(vars(a), indent=2))
    raw_dir = RESULTS / 'httperf'
    raw_dir.mkdir(exist_ok=True)
    phases = [(rate, a.seconds) for rate in rates]
    if a.idle_tail:
        phases.append((0, a.idle_tail))
    nominal = sum(duration for _, duration in phases)
    print(f'Planned experiment: {nominal / 60:.1f} minutes plus request-drain/process overhead.', flush=True)
    print('Keep autoscaler.py and cpu_profiler.py running in other terminals.', flush=True)
    index = 0
    for phase, (rate, duration) in enumerate(phases, 1):
        for _ in range(duration // a.window):
            index += 1
            start = stamp()
            before = time.monotonic()
            count = rate * a.window
            stats = parse('')
            exit_code = 0
            interrupted = False
            raw_path = ''
            if rate == 0:
                status = 'idle'
                try:
                    time.sleep(a.window)
                except KeyboardInterrupt:
                    interrupted, status = True, 'interrupted'
                stats.update(requests=0, replies=0, sent_req_s=0, successful_req_s=0,
                             replies_s=0, http_2xx=0, errors=0)
            else:
                cmd = ['httperf', '--server=' + a.host, '--port=' + str(a.port),
                       '--uri=' + a.uri, '--num-conns=' + str(count), '--num-calls=1',
                       '--rate=' + str(rate), '--timeout=5']
                log = raw_dir / f'{index:04d}_rate_{rate}.txt'
                raw_path = str(log.relative_to(RESULTS))
                (raw_dir / f'{index:04d}_command.json').write_text(json.dumps(cmd, indent=2))
                status = 'completed'
                with log.open('w') as f:
                    f.write(f"start_utc={start['timestamp']} start_epoch={start['epoch']}\n")
                    f.flush()
                    proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT,
                                            env=dict(os.environ, LC_ALL='C'))
                    try:
                        proc.wait(timeout=a.window + 25)
                    except (subprocess.TimeoutExpired, KeyboardInterrupt) as e:
                        interrupted = isinstance(e, KeyboardInterrupt)
                        status = 'interrupted' if interrupted else 'watchdog_timeout'
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                    exit_code = proc.returncode
                stats = parse(log.read_text(errors='replace'))
                if status == 'completed':
                    if exit_code:
                        status = 'process_error'
                    elif any(stats[k] is None for k in ('duration_s', 'http_2xx', 'errors')):
                        status = 'incomplete_summary'
                    elif stats['http_2xx'] < count or stats['errors'] > 0:
                        status = 'completed_with_failures'
            end = stamp()
            row = dict(timestamp=start['timestamp'], epoch=start['epoch'],
                end_timestamp=end['timestamp'], end_epoch=end['epoch'], phase=phase,
                target_req_s=rate, planned_requests=count, planned_seconds=a.window,
                wall_seconds=round(time.monotonic() - before, 3), status=status,
                exit_code=exit_code, **stats,
                success_pct_planned=round(100 * stats['http_2xx'] / count, 2)
                    if count and stats['http_2xx'] is not None else '', raw_log=raw_path)
            append_csv('workload.csv', row)
            print(f"{end['timestamp']} target={rate}/s sent={stats['sent_req_s']}/s "
                  f"response={stats['response_ms']}ms status={status}", flush=True)
            if interrupted:
                print('Stopped; completed rows and raw logs were saved.')
                return
    print('Done. Leave the autoscaler running until scale-in finishes, then stop it with Ctrl+C.')


if __name__ == '__main__':
    main()
