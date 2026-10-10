#!/usr/bin/env python3
"""Read-only smoke check to run on your Mac with the lab started."""
import json
import urllib.request
from lab_common import apps, healthy, NETWORK, NGINX, docker

containers = apps()
assert containers, 'No running app containers'
for c in containers:
    cfg = c['HostConfig']
    assert cfg['NanoCpus'] == 1000000000, 'CPU limit must be 1 core'
    assert cfg['Memory'] == 1073741824, 'Memory limit must be 1 GiB'
    assert NETWORK in c['NetworkSettings']['Networks'], 'Missing Docker network'
    assert healthy(c), 'Wait for healthy: ' + c['Name']
    print(c['Name'], 'healthy; 1 CPU; 1 GiB')
print(docker('exec', NGINX, 'nginx', '-t'))
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
seen = set()
for _ in range(20):
    with opener.open('http://127.0.0.1:8080/api/solve', timeout=10) as r:
        d = json.load(r)
        assert d['a'] != 0
        seen.add(d['hostname'])
print('Hostnames observed through Nginx:', ', '.join(sorted(seen)))
if len(containers) > 1 and len(seen) < 2:
    raise SystemExit('Only one backend observed. Run --sync-only with the autoscaler stopped, then retry.')
print('Checks passed. Nginx is serving the solver.')
