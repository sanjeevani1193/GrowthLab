# Phase 12A — Docker packaging and local verification

Status: **verified locally and approved for preservation; not deployed**.
The verification receipt retains its original phase-time status.
Application/research baseline: `8b5b25054e66f7ea69f2778818db6ae01fca01c9`.
The application, analytical calculations, frozen results and models are unchanged.

## What the container contains

The image packages the existing Decision Studio, its pure planning/reward
calculators and twelve approved aggregate JSON sources. It does not package a
research workspace. There is no acquisition, ETL, scoring, fitting or outcome
evaluation at build or startup.

| Choice | Purpose |
| --- | --- |
| Official `python:3.14.7-slim-bookworm` with an immutable multi-architecture digest | Match the verified Python version while avoiding a full development OS/toolchain |
| Existing `requirements-studio.lock` | Preserve all 35 dashboard package versions |
| `requirements-container.lock` | Add only Linux-required `watchdog==7.1.0`; Streamlit's metadata requires it outside Darwin |
| Binary wheels only, no pip cache | Avoid compiling scientific libraries and retaining download caches |
| Build-time import bytecode | Cache actual Streamlit/pandas/Arrow/SciPy/Plotly imports, reducing cold import work without compiling all unused library modules |
| Exact `.dockerignore` allowlist and explicit `COPY` statements | Keep datasets, models, predictions, credentials, virtual environments, Git history and unrelated research code outside the context/image |
| UID/GID `10001:10001` | Run the server as a non-root user; application files remain root-owned and readable |
| Python entry point using `os.execv` | Validate `PORT`, start the unchanged app and forward shutdown signals through PID 1 without a shell |
| Standard-library Python health probe | Check Streamlit without installing curl or an extra monitoring package |
| One-thread numerical-library defaults; disabled file watcher | Avoid unnecessary threads and development file scanning in an immutable image |

Base-image index digest:
`sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56`.
The registry index was inspected and contains both Linux ARM64 and AMD64 images.
No platform is hardcoded in `FROM`; the build selects it explicitly.

The final Docker-filtered context was actually exported and inspected:
**33 files / 240,599 bytes**, exactly matching the allowlist. Allowed directories
immediately re-exclude descendants before individual files are admitted, so an
exception for `.streamlit/` does not inadvertently admit `secrets.toml`.

The final `/app` tree has **31 files**, all individually hashed against the host
source: entry point, configuration, runtime locks, container helpers, minimum
Python modules and aggregate evidence. Dockerfile and `.dockerignore` are context
controls rather than runtime files. All twelve evidence fingerprints pass.
No `/Users/...` paths, customer files, model weights, predictions, caches or Git
history occur in the application tree. Research libraries such as DuckDB,
XGBoost, scikit-learn and joblib, and browser tooling, are not installed.

## Exact local build and run

From the repository root on this Apple Silicon Mac, with Docker Desktop running:

```sh
docker build --platform linux/arm64 --progress=plain \
  -t growthlab-studio:phase12a .

docker run -d --name growthlab-phase12a --pull=never \
  --platform linux/arm64 \
  -p 127.0.0.1:8502:8080 \
  --memory=512m --cpus=1 --pids-limit=128 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop=ALL --security-opt=no-new-privileges:true \
  growthlab-studio:phase12a
```

Open **http://127.0.0.1:8502**. The existing host Streamlit instance on port 8501
is unaffected. `127.0.0.1` in the publish rule restricts the host binding to
loopback; Streamlit listens on **0.0.0.0 inside the container**. No host directory,
Docker socket, credentials, source checkout, dataset or model volume is mounted.
On a native AMD64 Linux machine, build/run with `--platform linux/amd64` instead.

`PORT` defaults to **8080**. To change it, pass an environment variable and match
the container side of the port mapping, for example:

```sh
docker run -d --name growthlab-port-example --pull=never \
  -e PORT=8091 -p 127.0.0.1:8503:8091 \
  --memory=512m --cpus=1 --pids-limit=128 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop=ALL --security-opt=no-new-privileges:true \
  growthlab-studio:phase12a
```

Ports must be ASCII integers from 1 to 65535. Invalid values fail before the
server starts. `/tmp` holds the ephemeral home/cache directory, not customer data.
The image needs no writable application directory. Printed Streamlit URLs refer
to the container port; use the host-mapped URL above in your browser.

`STREAMLIT_BROWSER_SERVER_ADDRESS=localhost` prevents automatic external-IP
discovery and external-address logging during local use. It does not change the
server's 0.0.0.0 bind. A future public host can override this environment variable
with its intended hostname. Usage telemetry remains disabled; CORS and XSRF
protections retain their defaults.

## Health and verification commands

The health endpoint is **`/_stcore/health`**, expected response **HTTP 200 / `ok`**.
The built-in Docker probe reads the same `PORT` as the server, every 15 seconds,
with a 3-second HTTP timeout, 5-second probe timeout, 30-second startup grace
period and three retries. A successful initial probe can mark it healthy before
the grace period ends.

```sh
docker inspect --format '{{.State.Health.Status}}' growthlab-phase12a
docker exec growthlab-phase12a python docker/healthcheck.py
docker logs growthlab-phase12a
docker stats --no-stream growthlab-phase12a
```

An HTTP health response proves that the server is alive; it does **not** prove
that each Streamlit workspace executes correctly. Actual browser verification
against the container is therefore separate:

```sh
PLAYWRIGHT_BROWSERS_PATH=/tmp/growthlab-phase11-browsers \
  .venv/bin/python scripts/verify_decision_studio.py \
  --url http://127.0.0.1:8502 --output /tmp/growthlab-phase12a-browser
```

That browser path is the existing local QA installation, not an image dependency.
For a fresh QA environment, install `requirements-studio-test.lock` and run
`python -m playwright install chromium`; omit `PLAYWRIGHT_BROWSERS_PATH` to use
Playwright's default installation. Browser tooling is never included in the image.

Full suite, in the existing research environment:

```sh
LOKY_MAX_CPU_COUNT=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Packaging checks alone need only the Python standard library:

```sh
python3 -m unittest discover -s tests -p 'test_container_packaging.py' -v
```

After review/testing, stop and remove only your own test containers:

```sh
docker stop --time 10 growthlab-phase12a
docker rm growthlab-phase12a
```

Remove `growthlab-port-example` similarly if you ran that optional example.
No broad Docker prune is needed. The local image and build cache remain available.

## Actual verification results

The small [verification receipt](phase12a_verification.json) records the final
image identity, exact application hashes, startup measurement, resource snapshot
and browser results. No customer-level output is included.

| Check | Observed result |
| --- | --- |
| Native platform | Linux ARM64 (`aarch64`), Docker Engine 20.10.23 on the ARM64 Mac |
| Host / Docker VM | 8 GiB host RAM; existing VM configuration 4 CPUs / 4,123,439,104 bytes RAM; not increased |
| Final image | **727,417,590 bytes**, approximately **727.4 MB / 693.7 MiB**, uncompressed local image size |
| First dependency build | **71.76 seconds**, including wheel downloads; before the bytecode refinement |
| Final build | **13.06 seconds**, reusing verified dependency layers; not a new uncached download benchmark |
| Clean container HTTP readiness | **1.731 seconds**, measured with the host monotonic clock from `docker run` to HTTP 200/`ok` |
| Docker health | **Healthy** with no OOM kill or restart |
| Container limits | **1 CPU / 512 MiB**, 128 task limit, read-only root filesystem, 64 MiB temporary filesystem |
| Resource snapshot after browser interaction | **184,926,208 bytes (~176.4 MiB)** Docker-accounted memory; this is a snapshot, not peak RSS or a load-capacity estimate |
| Runtime identity / dependencies | UID/GID 10001; **36 exact runtime package versions** verified; `pip check` passes; no compiler installed |
| Browser | All **seven** workspaces load; **13** desktop/mobile view checks and **seven** interaction checks; no browser errors or document overflow |
| Alternate port | `PORT=8091`, host 8503, HTTP health and Docker health both pass |
| Shutdown / invalid configuration | SIGTERM shutdown exits **0**; invalid PORT rejected before server startup |
| Full tests | **344 passed, no skips**: original 338 + six new packaging tests |

The final image ID is:
`sha256:05387fa1d6f484fb9b1f38b9dd15dede4943f2212b72599f8286c0342720742c`.

The initial cold browser attempt exceeded its 15-second navigation deadline while
uncompiled libraries were importing and local tests were running concurrently.
This was not treated as a successful verification. The final image caches the
actual UI import bytecode at build time; the unchanged browser script subsequently
passed against the fresh final container. A separate container-internal AppTest
also exercised all seven workspaces. These are local observations, not controlled
performance comparisons or concurrency benchmarks.

Verified displays/calculations include purchase AUC **0.8487**, captured purchasers
**324/547**, RetailHero training difference **+3.39 pp**, synthetic **4.3% / 79.3%**,
ranking **18.42% / 0.21625**, balanced planning **5,886** customers and hypothetical
reward net **-€550.00**. Browser controls also reproduce unequal planning total
**6,949**, zero-reward net **€600.00** and K=20 macro/micro recall selection.

Frozen Module 1 and RetailHero checks pass, including **82** prior file states,
**29** additional raw/cleaned/ranking/saved-artifact hashes and **12** dashboard
evidence hashes. Raw bytes were hashed for integrity, not parsed for another
evaluation. No model was loaded by the public container or refitted, no sealed
labels were reopened, and no historical result was recomputed.

Final startup logs contain the container listen address and localhost URL, with
no external-address discovery, host Mac paths, credentials or customer records.
This is a content/configuration check, not a claim of a full vulnerability audit.
The original host app and research environment are unchanged.

## Cloud Run compatibility and remaining limits

The packaging follows the [Cloud Run container contract](https://docs.cloud.google.com/run/docs/container-contract):
HTTP binds to 0.0.0.0 on configurable `PORT`, default 8080; the process handles
shutdown signals; no local persistent data, model mount or credential is required.
TLS termination can remain outside the container.

**Cloud Run requires Linux x86_64 (`linux/amd64`)**. The pinned base index includes
that architecture, but only native ARM64 was built and executed in Phase 12A.
No AMD64 emulation was used. Before public release, build and run this Dockerfile
on a native AMD64 builder, verify that platform's wheels and repeat the same
workspace/health tests. ARM64 success is not evidence of an AMD64 runtime test.

Later release decisions include image vulnerability review, an AMD64 image build,
approved registry/hosting settings, hostname, platform startup/liveness probes,
HTTPS/WebSocket behavior, session/concurrency limits and cost controls. No public
registry image, Cloud Run service, cloud IAM resource or billable infrastructure
was created in this phase.

The image contains scientific and Streamlit transitive dependencies such as
SciPy, pandas and Arrow, which account for much of its size; no ML training stack
is included. Do not prune these mandatory dependencies to obtain a smaller but
incompatible environment. The build pins versions and the base digest; it is not
a guarantee of byte-for-byte hermetic builds. Rebuilding for security updates
needs an intentional dependency/base review. The Docker daemon did not expose a
peak-memory counter; the reported memory is a measured snapshot. Production
concurrency and long-lived WebSocket load were not benchmarked.

## Files and review state

New: `Dockerfile`, `.dockerignore`, `requirements-container.lock`,
`docker/entrypoint.py`, `docker/healthcheck.py`,
`tests/test_container_packaging.py`, this report and its small verification JSON.
Updated: README local Docker instructions and current test count.
Existing app source, locks, tests, Streamlit configuration, reports, aggregate
research evidence, models, datasets and splits remain unchanged. There was no
existing GitHub Actions workflow to modify, and no CI/deployment workflow was added.

Verification containers are stopped and removed after testing; the image remains
local for review. **Phase 12A source and verification evidence are preserved together.**

Implementation references: [official Python image](https://hub.docker.com/_/python),
[Dockerfile health checks](https://docs.docker.com/reference/dockerfile/#healthcheck),
and [Docker build contexts](https://docs.docker.com/build/concepts/context/#dockerignore-files).
