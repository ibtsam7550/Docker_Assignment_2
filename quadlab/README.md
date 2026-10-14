# macOS Docker quadratic-solver lab

This folder contains the code and commands for all five milestones of your assignment. Run the commands yourself to obtain genuine measurements and screenshots. No experiment results have been invented.

## 1. What runs where

| Component | Location | Purpose |
|---|---|---|
| Browser and httperf | Linux VM | Send requests to http://192.168.98.1:8080 |
| autoscaler.py | Mac | Measure containers, change their number and reload Nginx |
| cpu_profiler.py | Mac | Record whole-Mac CPU and memory |
| Nginx container | Docker | Distribute requests between healthy app containers |
| App containers | Docker | Generate and solve quadratic equations |
| quadlab_net | Docker bridge network | Connect Nginx and every app container |

Start with TWO app containers. The controller may later use ONE to FOUR. Every app has a 1 CPU limit and a 1 GiB memory limit (`1g` in Docker, commonly called 1 GB). These are maximum limits, not reserved resources. All replicas use the same image, Docker network and `quadlab.group=app` label. That labelled set is our local autoscaling group; no AWS service, Swarm or Kubernetes is needed.

Compose creates the first two containers. The Python controller creates/removes group members with the Docker CLI. Extra containers are deliberately managed by the controller, not by Compose. Therefore use `docker ps --filter label=quadlab.group=app` to see ALL replicas, and use `stop_lab.py` for complete cleanup. Do not run `docker compose up` or change the scale manually while the autoscaler is running.

## 2. Check your Mac and prepare Python

Open your existing Docker application and wait for its engine to start. In Terminal:

```bash
docker version
docker compose version
docker info
python3 --version
```

`docker version` must show both Client and Server. Use an existing working Python 3.10 or newer. You already have Docker and Compose, so do not reinstall them. The image runs Linux inside Docker's VM; it does not depend on macOS Python packages.

In Docker's resource settings, allow about 4 CPU cores and 6 GB RAM if your Mac has enough memory. The four app limits alone permit 4 GiB, and the Docker VM/Nginx also need memory. Close unnecessary heavy applications and keep the Mac plugged in and awake. Resource-setting names vary by Docker installation. This is a local capacity experiment: all containers still share one physical Mac.

Download and unzip `macos-docker-autoscaling-lab.zip`. Put its `quadlab` folder on your Desktop, then run:

```bash
cd ~/Desktop/quadlab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-host.txt
```

`psutil` is for your CPU profiler. `matplotlib` is for graph generation. The autoscaler and workload wrapper themselves use only Python's standard library and external command-line tools.

Check httperf:

```bash
httperf --version
```

If it is missing and Homebrew is installed:

```bash
brew install httperf
```

If that install fails on an older macOS, keep your existing working httperf if available. A container-based fallback is described in TROUBLESHOOTING.md; it still sends the workload to Nginx. Do not run the supplied old `db.sh` for this experiment: it uses VM addresses/PHP URLs, extremely high rates and a broad `pkill`.

## 3. Build and run the two app containers (Milestones 1 and 2)

From the project folder, with the virtual environment active:

```bash
docker compose config
docker compose build
docker compose up -d --scale app=2 app
docker ps --filter label=quadlab.group=app
```

Wait until both Status entries say `(healthy)`. Run the last command again to check. This normally takes several seconds, but the first image build may take longer because dependencies must download.

Each app receives its own automatically chosen localhost port. Display the two addresses:

```bash
docker compose port --index 1 app 8000
docker compose port --index 2 app 8000
```

For each address printed, add `http://` and open it in your browser. For example, if Docker prints `127.0.0.1:55001`, open `http://127.0.0.1:55001`. The actual port on your Mac will differ.

Click **Generate and solve**. The server chooses integer coefficients from -10 to 10 and never chooses zero for a. It returns the equation, discriminant, real roots, container hostname/IP and UTC timestamp. Keep clicking to see the three cases. The HTML uses Bootstrap and jQuery from public CDNs, so the browser needs internet for those assets; `/api/solve` works independently.

Save a screenshot of the UI and one of `docker ps`. No styling work is required.

## 4. Configure and start Nginx (Milestone 3)

While both apps are healthy:

```bash
python autoscaler.py --sync-only
cat nginx/generated/default.conf
docker compose up -d nginx
docker exec quadlab-nginx nginx -t
python verify_lab.py
```

`--sync-only` discovers healthy app IP addresses on `quadlab_net` and writes the upstream file. It does not start an autoscaling loop. Nginx uses its default round-robin balancing. Only Nginx has a fixed host port, 8080; the application container port is always 8000 internally.

Open http://127.0.0.1:8080 and click the button repeatedly. Hostnames should vary. Confirm in Terminal too:

```bash
for i in {1..6}; do curl -s http://127.0.0.1:8080/api/solve; echo; done
docker network inspect quadlab_net
docker ps
```

The UI page and its API request can reach different containers; the displayed hostname belongs to the API response. `verify_lab.py` checks resource limits, health, network membership and requests through Nginx. Capture the proxy UI, upstream configuration and container list.

## 5. Understand the files before the experiment

| File | What it does |
|---|---|
| Dockerfile | Installs Flask/Gunicorn, copies the application, adds a health check and runs port 8000 |
| solver.py | Implements the quadratic formula and all three real-root cases |
| app.py | Generates coefficients, serves the API/HTML and optional synthetic CPU work |
| compose.yaml | Defines initial app replicas, Nginx, resource limits, ports and the bridge network |
| nginx/Dockerfile | Builds the Nginx image with our main configuration |
| nginx/nginx.conf | Sets Nginx workers and timestamped access logs |
| nginx/generated/default.conf | The upstream IP list generated automatically; do not hand-edit during the run |
| policy.json | Minimum/maximum replicas, thresholds, sampling and cooldown |
| autoscaler.py | Measures, scales, health-filters, updates Nginx and drains removals |
| lab_common.py | Shared Docker commands, timestamps and CSV writing |
| workload.py / httperf_parser.py | Run real httperf windows and parse their output |
| cpu_profiler.py | Your uploaded profiler, retained unchanged |
| plot_results.py | Reads the CSVs and makes the four required plots |
| verify_lab.py | Checks the running lab on your Mac |
| stop_lab.py | Removes only this lab's containers/network; preserves results/images |

The app service has no fixed `container_name`, because replicas need different names. Initial container names will normally be `quadlab-app-1` and `quadlab-app-2`. Additional names start with `quadlab-extra-`. Do not hard-code any of their IP addresses.

## 6. Start the autoscaler (Terminal A, Milestone 4)

```bash
cd ~/Desktop/quadlab
source .venv/bin/activate
python autoscaler.py
```

Leave this terminal running. Default policy:

| Setting | Value |
|---|---|
| Initial apps | 2, from the startup command |
| Allowed range | 1 to 4 |
| Sampling target | Every 5 seconds |
| Scale out | Average app CPU >70% for 3 consecutive valid samples |
| Scale in | Average app CPU <30% for 3 consecutive valid samples |
| Cooldown | 60 seconds after an operation, and an initial 60-second warm-up |
| Change per action | Add or remove 1 container |

Three samples implement the assignment's word “remains.” They are sampled evidence, not a claim that every instant between measurements exceeded the threshold. The two different thresholds reduce repeated adding/removing near one boundary. Memory is measured but CPU triggers scaling, as requested.

Scale out: create a container with the same limits/network/label; wait for Docker health to become healthy; regenerate the upstream; test configuration; reload Nginx.

Scale in: remove the selected backend from the upstream; test/reload Nginx; confirm new workers started; wait for ALL old workers to exit; only then stop/remove the backend. Old workers finish existing requests while new workers use the reduced upstream. If draining exceeds 120 seconds, removal is cancelled and the app stays alive. This avoids treating a fixed sleep as proof that requests finished.

Docker health status is checked each cycle, with passive Nginx failure handling between checks. Failure detection is periodic, not instantaneous. If no backend is healthy, Nginx returns HTTP 503 rather than forwarding to a known unhealthy backend. Do not kill containers manually during the scaling experiment.

Edit `policy.json` only with the controller stopped, then restart it. Keep 70/30 and 1/4 for the assignment. You can configure cooldown and sample timing. Never run a second controller against the same group; a lock prevents duplicate controllers from the same project folder.

## 7. Start your CPU profiler (Terminal B)

Open a new Terminal tab/window:

```bash
cd ~/Desktop/quadlab
source .venv/bin/activate
python cpu_profiler.py --out results/host_cpu.csv --label mac-host --interval 1
```

Leave it running. This is your original profiler and measures the entire Mac. Container CPU comes from `docker stats`, collected by the autoscaler. They are different measurements: a container near 100% here is using roughly one core; Mac overall CPU is averaged across all logical CPUs. Do not label Mac CPU as an individual container's CPU.

## 8. Generate increasing and decreasing workload (Terminal C, Milestone 5)

```bash
cd ~/Desktop/quadlab
source .venv/bin/activate
python workload.py
```

The default target is `http://127.0.0.1:8080/api/solve?work=80000`. All load therefore goes through Nginx.

The sequence is 50,100,150,200,250,300,500,1000,500,400,300,250,200,150,100,50,0 requests/second. Each phase lasts 40 nominal seconds, followed by an extra 40-second idle tail. Each phase is split into 10-second httperf windows to provide more graph points. Brief process-start gaps are possible; timestamps record the actual window boundaries.

The extra `work=80000` performs 80,000 PBKDF2 iterations per request. It is synthetic CPU work, not part of the quadratic formula and not a delay created with `sleep`. Disclose it in your report. Normal browser requests use `work=0`. Without this added work, a tiny quadratic calculation may require a much higher request rate to cross 70% CPU.

The initial idle phase will usually reduce two apps to one. Increasing traffic should trigger scale-out if it crosses the measured threshold; low traffic and the final idle period allow scale-in. Exact counts and response times depend on your machine. Do not assume that every phase changes the count or that reaching 4 is guaranteed.

For a quick command/CSV check only (too short to demonstrate the default scaling policy):

```bash
python workload.py --rates 20 --seconds 10 --idle-tail 0
```

Use this only in a separate results session. Archive its files before running the full experiment (step 12). The workload runner refuses to overwrite an existing workload.csv.

## 9. Watch and capture evidence (Terminal D)

```bash
cd ~/Desktop/quadlab
docker ps --filter label=quadlab.group=app
docker stats --no-stream
tail -n 10 results/metrics.csv
tail -n 10 results/scaling_events.csv
cat nginx/generated/default.conf
docker logs --tail 20 quadlab-nginx
```

Run these commands at low load, during scale-out, at high load and after scale-in. Capture the controller's `scale_out` and `scale_in` messages and the changed container counts. `docker stats` also shows Nginx, but the controller's averages include APP containers only. Docker metrics are sampled snapshots, not continuous CPU integrals.

## 10. Stop measurement and make graphs

After the workload finishes, wait until the controller has returned to its minimum count. In Terminals A and B press Ctrl+C. This stops measurement; it does not stop containers.

In Terminal C:

```bash
python plot_results.py
open results/graphs.png
```

The script also saves `results/graphs.pdf` for your report. The four aligned plots show workload (target, actual sent and successful replies), mean httperf response time, average container CPU with optional Mac CPU, and running app count. Dotted lines mark successful scaling events.

| Output | Meaning |
|---|---|
| results/metrics.csv | Timestamp, epoch, running count, healthy count, average CPU %, average memory % |
| results/container_metrics.csv | Same timestamp for each app: identity, health, CPU %, memory %, used/limit |
| results/scaling_events.csv | UTC/epoch timestamps, start/drain/out/in/error decisions |
| results/workload.csv | Start/end timestamps, target/actual rate, response time, HTTP outcomes and errors per window |
| results/host_cpu.csv | Original profiler output including UTC timestamp and Unix epoch |
| results/httperf/*.txt | Raw httperf outputs, one timestamped file per load window |
| results/*settings.json and policy_snapshot.json | Workload parameters and scaling policy used |
| results/graphs.png and graphs.pdf | Four required plots |

All new measurement rows contain a UTC ISO timestamp and Unix epoch seconds. Your profiler already provides these as `timestamp_utc` and `epoch`. The graphs align by epoch, so Pakistan/UTC display differences do not misalign records. A timestamp such as `2026-10-08T14:30:00+00:00` means 19:30 in Pakistan.

`avg_memory` is the mean memory percentage from Docker for the app containers, each relative to its 1 GiB limit. Docker CLI memory usage excludes certain cache memory. The per-container used/limit string is also saved. The aggregate CPU mean is `(CPU1 + CPU2 + ...)/container_count`.

`response_ms` is httperf's mean reply-response metric for completed replies in that window; it is not p95, whole-connection latency or the latency of timed-out requests. `transfer_ms` and `connection_avg_ms` are saved separately. Examine HTTP errors and successful throughput beside latency: dropped slow requests can make the successful-response average look misleadingly low. Idle periods and unavailable summaries are blank for response time, never fabricated zeros. Target rate is configured demand; measured sent rate and successful replies are separate.

## 11. Prepare your short submission

Use your own real screenshots and CSV data:

1. Milestone 1: UI screenshot, coefficients/solutions/hostname, server-side code. Explain discriminant >0, =0, <0.
2. Milestone 2: Dockerfile, two app containers, direct browser access, resource limits.
3. Milestone 3: Nginx Dockerfile/configuration, proxy browser access, container list.
4. Milestone 4: autoscaler source, metrics.csv and per-container metrics, scaling policy, both scaling screenshots, graceful removal explanation.
5. Milestone 5: four graphs, raw httperf output, workload/settings, brief interpretation of CPU, latency, count and failures.

Discuss what you actually observe. For example, if a new container lowers mean per-container CPU, relate that to traffic distribution. If CPU stays high at four containers, explain the maximum and shared host capacity. If the generator cannot achieve its target rate, state that limitation instead of attributing it automatically to Nginx.

Suggested 4-minute Loom outline: app/code (40 seconds), two containers/resources/network (40 seconds), Nginx (30 seconds), scaling evidence and policy (70 seconds), graphs and conclusion (60 seconds). Record the experiment first, then show the saved evidence. The assignment says PDF report plus a Loom URL, maximum 4 minutes, due October 14, 2026 at 11:59 pm via Google Classroom. Confirm any later instructor changes yourself.

## 12. Stop the lab or start a fresh experiment

First Ctrl+C the controller, profiler and workload if any are running. Then:

```bash
python stop_lab.py
```

It removes this lab's app group, Nginx and network, including controller-created apps. It does not prune other Docker projects and preserves images/results. `docker compose down` alone would leave the extra app containers behind.

For a fresh experiment, archive results after stopping the measurement programs:

```bash
mv results "results_$(date +%Y%m%d_%H%M%S)"
```

Restart from step 3, then step 4, then the three measurement terminals. New measurements go into a new `results` directory. To plot an archived run:

```bash
python plot_results.py --results results_YYYYMMDD_HHMMSS
```

## Small vocabulary

- Replica: another running copy of the same application.
- Upstream: the group of backend servers Nginx forwards requests to.
- Threshold: the value that triggers an action, such as 70% CPU.
- Cooldown: a waiting period before another scaling action.
- Drain: finish existing requests before stopping a container.
- Throughput: how many requests are successfully handled per second.

## Technical references and validation

- Docker Compose services, resource limits and ports: https://docs.docker.com/reference/compose-file/services/
- Docker stats: https://docs.docker.com/reference/cli/docker/container/stats/
- Nginx graceful reload: https://nginx.org/en/docs/control.html

The app/API, solver, parser and controller safety logic were checked in the preparation environment. That environment has no Docker engine, so the container build, Docker networking, Nginx reload and actual scaling experiment must be validated on your Mac using the commands above. Tests with mocked Docker responses are not an end-to-end Docker test. No sample CSV values or graphs are supplied as if measured on your Mac.
