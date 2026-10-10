# Troubleshooting

## Docker cannot connect

Start the Docker application and run `docker info`. The autoscaler uses the same Docker CLI context as your Terminal. Check `docker context ls` and `docker context show` if containers unexpectedly appear elsewhere. Do not select a remote context for this local lab.

## An app is unhealthy

```bash
docker compose logs --tail 50 app
docker ps --filter label=quadlab.group=app
```

For an extra app, use `docker logs CONTAINER_NAME`. The health endpoint is `/health`. A container in `starting` status is deliberately excluded until healthy.

## Nginx returns 503

Check that an app is healthy. With the autoscaler stopped:

```bash
python autoscaler.py --sync-only
docker exec quadlab-nginx nginx -t
curl -i http://127.0.0.1:8080/api/solve
```

If the autoscaler is already running, let it synchronize automatically and inspect its error output. Do not run `--sync-only` concurrently.

## Port 8080 is occupied

Check `lsof -nP -iTCP:8080 -sTCP:LISTEN`. Either close the conflicting application or change only the host side of the Nginx port mapping in compose.yaml to `127.0.0.1:8088:80`. Recreate Nginx with the controller stopped. Then use browser port 8088 and `python workload.py --port 8088`. Also update the URL in verify_lab.py. Backend port 8000 stays unchanged.

## CPU does not cross 70%

Inspect measured container CPU and httperf's actual sent rate. After archiving the current experiment, try:

```bash
python workload.py --uri '/api/solve?work=160000'
```

Or increase rates while keeping work constant. Change one variable at a time and record it. Do not reduce the assignment's CPU thresholds just to force a screenshot. The `work` parameter is bounded at 1,000,000; increasing it too far can cause long queues/timeouts.

## CPU is high but no scale-out

Check all of these: the controller is running; the average of ALL app containers exceeds 70%; 3 consecutive samples qualify; the 60-second cooldown has finished; the current count is below 4. Read scaling_events.csv for health or Docker errors. Startup/drain actions can temporarily delay metric sampling; use timestamps rather than assuming exactly 5 seconds between every pair of rows.

## The workload cannot reach its configured rate

Look at `sent_req_s`, `successful_req_s`, `generator_cpu_pct`, `fd_unavailable`, `address_unavailable` and `errors` in workload.csv and raw logs. httperf, macOS sockets or the shared CPU can bottleneck before the server does. Raising `ulimit` cannot remove httperf's compiled FD_SETSIZE limit. Begin with the moderate defaults. Do not use the old script's 90,000 requests/s ramp on a laptop for this lab.

## httperf cannot be installed on your macOS

This optional fallback runs httperf in a Linux container but keeps the controller on the Mac. First check with your instructor if they require the load generator itself to be a native host process. The workload still reaches Nginx and raw httperf output is still saved.

Build the included alternative image:

```bash
docker build -f tools/Dockerfile.httperf -t quadlab-httperf:local .
mkdir -p results
```

With the autoscaler and Mac profiler running, use this command instead of native `python workload.py`:

```bash
docker run --rm --name quadlab-loadgen --network quadlab_net \
  -v "$PWD/results:/work/results" quadlab-httperf:local \
  --host quadlab-nginx --port 80
```

This generator joins the same bridge network and calls Nginx by its Docker name. Its container does not have the app-group label and is excluded from autoscaler averages. If interrupted and it stays running, stop only it with `docker stop quadlab-loadgen`. The Mac profiler still includes Docker's CPU use, so identify the generator's location in your report.

## Nginx error during removal

The controller leaves the backend alive when configuration testing, reload confirmation or draining fails. It logs the error and waits before trying again. Inspect:

```bash
docker logs --tail 80 quadlab-nginx
docker top quadlab-nginx -eo pid,args
```

`nginx: worker process is shutting down` means a worker is draining. Do not manually force-remove its backend if preserving in-flight requests matters.

## CSV already exists / mixing experiments

Stop all measurement programs first, archive `results`, then restart them. The controller appends its CSV rows to preserve work; the profiler/workload refuse accidental overwrite. Use one results folder per experiment to keep the graphs meaningful.
