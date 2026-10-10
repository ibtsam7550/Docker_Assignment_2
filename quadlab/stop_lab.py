#!/usr/bin/env python3
"""Stop this lab only. Stop the autoscaler and workload with Ctrl+C first."""
from lab_common import apps, docker

for container in apps(all_states=True):
    print('Removing', container['Name'])
    docker('rm', '-f', container['Id'])
docker('compose', 'down', timeout=120)
print('Lab stopped. Images and results were preserved.')
