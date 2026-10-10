#!/usr/bin/env python3
"""Plot real CSV measurements; never substitute sample numbers for missing data."""
import argparse
import csv
from pathlib import Path
import math
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(path):
    with path.open(newline='') as f:
        return list(csv.DictReader(f))


def value(row, key):
    try:
        return float(row[key])
    except (ValueError, KeyError, TypeError):
        return math.nan


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results', default=str(Path(__file__).resolve().parent / 'results'))
    a = p.parse_args()
    folder = Path(a.results)
    policy_file = folder / 'policy_snapshot.json'
    policy = json.loads(policy_file.read_text()) if policy_file.exists() else {'scale_out_cpu': 70, 'scale_in_cpu': 30}
    metrics, load = read(folder / 'metrics.csv'), read(folder / 'workload.csv')
    if not metrics or not load:
        raise SystemExit('Run the autoscaler and workload first; both CSVs need real rows.')
    origin = min(value(metrics[0], 'epoch'), value(load[0], 'epoch'))
    x = [(value(r, 'epoch') - origin) / 60 for r in metrics]
    mids = [((value(r, 'epoch') + value(r, 'end_epoch')) / 2 - origin) / 60 for r in load]
    fig, axes = plt.subplots(4, 1, figsize=(11, 11), sharex=True, constrained_layout=True)
    target_x, target_y = [], []
    for r in load:
        target_x += [(value(r, 'epoch') - origin) / 60, (value(r, 'end_epoch') - origin) / 60, math.nan]
        target_y += [value(r, 'target_req_s'), value(r, 'target_req_s'), math.nan]
    axes[0].plot(target_x, target_y, label='Configured target rate', color='navy')
    axes[0].plot(mids, [value(r, 'sent_req_s') for r in load], '.-', label='Measured sent rate', color='orange')
    axes[0].plot(mids, [value(r, 'successful_req_s') for r in load], '.-', label='Successful replies/s', color='green')
    axes[0].set_ylabel('Requests / second')
    axes[0].legend(fontsize=8)
    axes[1].plot(mids, [value(r, 'response_ms') for r in load], '.-', color='purple')
    axes[1].set_ylabel('Mean reply response (ms)')
    axes[1].set_title('httperf response metric per window; idle/missing summaries remain blank', fontsize=9)
    axes[2].plot(x, [value(r, 'avg_cpu') for r in metrics], label='Average app container CPU')
    axes[2].axhline(policy['scale_out_cpu'], linestyle='--', color='red', label=f"Scale out >{policy['scale_out_cpu']}%")
    axes[2].axhline(policy['scale_in_cpu'], linestyle='--', color='green', label=f"Scale in <{policy['scale_in_cpu']}%")
    host = folder / 'host_cpu.csv'
    if host.exists():
        rows = read(host)
        axes[2].plot([(value(r, 'epoch') - origin) / 60 for r in rows],
                     [value(r, 'cpu_percent') for r in rows], alpha=0.5, label='Mac overall CPU (different denominator)')
    axes[2].set_ylabel('CPU (%)')
    axes[2].legend(fontsize=8)
    axes[3].step(x, [value(r, 'container_count') for r in metrics], where='post')
    axes[3].set_ylabel('App containers')
    axes[3].set_yticks(range(0, 5))
    axes[3].set_ylim(-0.2, 4.5)
    events = folder / 'scaling_events.csv'
    if events.exists():
        for r in read(events):
            if r['action'] in ('scale_out', 'scale_in'):
                at = (value(r, 'epoch') - origin) / 60
                axes[3].axvline(at, alpha=0.4, color='gray', linestyle=':')
    for ax in axes:
        ax.grid(alpha=0.25)
    axes[-1].set_xlabel('Minutes since first recorded measurement (aligned by Unix epoch)')
    fig.suptitle('Quadratic application: workload and automatic scaling')
    fig.savefig(folder / 'graphs.png', dpi=180)
    fig.savefig(folder / 'graphs.pdf')
    print('Saved', folder / 'graphs.png', 'and', folder / 'graphs.pdf')


if __name__ == '__main__':
    main()
