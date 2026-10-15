# Remote code-execution API

A small HTTP service that grades code **off the pod**, on a Docker-capable host, so the
execution-graded code evals (BigCodeBench, HumanEval, MBPP, APPS) can run against a
RunPod-served organism without a container runtime on the pod itself.

- `scripts/exec_api.py`   — the server. Runs on the Docker host.
- `scripts/remote_python` — a drop-in `python` shim. Runs on the pod; passed as `--exec-python`.

## Why it exists

`shared/code_evals.py` grades by *running* the model's code. Its two sandbox options are
`--sandbox docker` (needs a Docker daemon) and `--sandbox local` (runs the code on the host,
no isolation). RunPod pods can offer **neither** safely: they are unprivileged containers
with no `CAP_SYS_ADMIN`, and mount/user/PID `unshare` are all blocked — measured on two live
pods on 2026-08-15, so no container runtime can start there, full stop (`dockerd` boots but
dies creating the first container). See `shared/pod_caveats.md`.

This service moves the sandbox to a host that *can* run containers, and the pod talks to it
over HTTP. The eval code is unchanged: it still invokes `<exec_python> -c PROGRAM`, and the
shim makes that call happen on the remote host.

## The seam

`shared/code_evals.py:113` and `shared/code_exec.py:96` both reduce grading to one
primitive:

    run `<python> -c PROGRAM` with optional stdin  ->  (returncode, stdout, stderr)

`remote_python` impersonates exactly that and forwards it to the server. Nothing "calls an
API"; the eval just runs what it thinks is `python`.

## Tiers: slimmest image that carries the benchmark's libs

A benchmark runs on the **smallest** image whose libraries its hidden tests import. Built in:

| tier    | image                                                        | python | for |
|---------|--------------------------------------------------------------|--------|-----|
| `light` | `python:3.11-slim` (~125 MB)                                 | 3.11   | HumanEval, MBPP, APPS, LiveCodeBench Pro *(Python parts)* — stdlib-only |
| `bcb`   | `ghcr.io/arcadiaimpact/inspect-eval-bigcodebench:latest` (~5.5 GB) | 3.10 | BigCodeBench — carries the 74 pinned test libs (numpy 1.21.2, pandas, tensorflow, cv2, …) |

The `bcb` image **must** be py3.10: its pinned libs require py<3.11, which is exactly why
`setup_code_exec_env.sh` builds a separate execution env. Here that split is a container, not
a venv. `bcb` is pulled lazily on first use, never at startup, so the server is ready instantly
for `light` work.

### Adding a benchmark that needs different libraries — no code edit

Point `EXEC_API_TIERS_FILE` at a JSON file; its tiers extend/override the built-ins:

```json
{ "sci": { "image": "myrepo/sci-slim:1", "python": "python" } }
```

```bash
EXEC_API_TIERS_FILE=tiers.json EXEC_API_TOKEN=... python3 scripts/exec_api.py --prewarm all
```

Then the pod selects it with `EXEC_API_TIER=sci`. This is the intended way to keep images
right-sized: a bench needing only numpy+pandas gets a ~400 MB image of its own instead of
borrowing the 5.5 GB `bcb`.

### "Slim for speed" — measured, and it doesn't hold

On the reference host (2026-08-15), both execution latency and container cold-start are **flat
across image size**, because Docker mounts image layers lazily and an *unimported* library
costs nothing at runtime:

| | `light` (125 MB) | `bcb` (5.5 GB) |
|---|---|---|
| warm `print(1)` | 61 ms | 74 ms |
| container cold-start | 924 ms | 901 ms |

So image bulk buys only **disk** + **one-time pull**, never latency. What makes grading fast is
the **warm pool** (it hides the ~900 ms cold-start; steady state ~65 ms), not a smaller image.
Corollary: **never trim the `bcb` image below BigCodeBench's canonical lib set** to save space —
a hidden test importing a dropped lib fails as if the model were wrong, silently corrupting an
audit. Slimness is for new, purpose-built tiers; the heavy tier stays canonical.

> **Not covered:** LiveCodeBench **Pro** is C++, graded by inspect_evals' own privileged
> in-sandbox judge (LightCPVerifier). It does not pass through the `exec_python` seam, so this
> service does not grade it. Run it with `--sandbox docker` on a Docker host directly.

## Container lifecycle

Warm workers are labeled `com.autosandbag.exec-api`. A graceful stop (Ctrl-C **or SIGTERM** —
`docker stop`, systemd, `kill`) reaps the whole pool. A `kill -9` or a crash can't run cleanup,
so on the **next startup** the server reaps any container left with that label (logs
`reaped N orphaned worker(s)`). Between the two, stray containers can't accumulate. Both paths
verified 2026-08-15 (SIGTERM → 0 leftovers; kill -9 → next start reaps).

## The exit-70 contract (do not break this)

The shim returns the graded program's own exit code, **except 70** (`EX_SOFTWARE`), which it
reserves for "the exec host itself failed" (network down, bad token, daemon gone). This is
load-bearing: a network blip must **not** be scored as a failed test, because that would read
a working model as sandbagging and silently corrupt an audit. A program *timeout* is the
program's failure and returns non-zero (not 70). Anything consuming the shim must treat 70 as
infra error + retry, never as a wrong answer.

## Speed

Warm container pool + Docker Engine API over the unix socket. Measured on the reference host
(2026-08-15), per trivial program:

    cold `docker run`                  218 ms
    warm container, docker exec CLI     81 ms   (the CLI client alone is 77 ms)
    warm container, Engine API socket   57 ms   <- what this uses
    bare `python -c` (the floor)        25 ms

Containers are long-lived; each program is one `exec` in a fresh `mktemp` cwd, recycled every
50 uses so nothing leaks between tasks. Matters because one stdio task runs up to 12 programs.

## Isolation

Each container: `--network none`, `--read-only`-style throwaway `/scratch` tmpfs, non-root
work dir, `--memory 2g`, `--pids-limit 256`, `--cpus 2.0`. This bounds a runaway program and
cuts off network. It does **not** harden the *host* — the container is sandboxed, the daemon
is not, which is why auth is mandatory (below).

## Run it

On the Docker host:

```bash
export EXEC_API_TOKEN=$(openssl rand -hex 32)     # REQUIRED — server refuses to start without it
python3 scripts/exec_api.py --port 8000 --pool-size 4 --prewarm light
# pre-pull the heavy tier once if you'll use BigCodeBench:
#   docker pull ghcr.io/arcadiaimpact/inspect-eval-bigcodebench:latest
```

Expose the port (a public proxy URL, or an SSH reverse tunnel `ssh -R 8000:127.0.0.1:8000 <pod>`).

On the pod, point the eval at the shim:

```bash
export EXEC_API_URL=https://<exposed-host>            # or http://127.0.0.1:8000 over a tunnel
export EXEC_API_TOKEN=<same token>
export EXEC_API_TIER=light                            # or bcb for BigCodeBench
export EXEC_API_TIMEOUT=30                             # per-program seconds (server caps at 120)

python -m shared.code_evals --task humaneval  --model <served> \
    --base-url http://localhost:8000/v1 \
    --sandbox local --exec-python /workspace/AutoSandbag/scripts/remote_python --limit 20

python -m shared.code_evals --task bigcodebench --model <served> \
    --base-url http://localhost:8000/v1 \
    --sandbox local --exec-python /workspace/AutoSandbag/scripts/remote_python --limit 20
    # with EXEC_API_TIER=bcb
```

## API

| method | path      | body                                       | returns |
|--------|-----------|--------------------------------------------|---------|
| GET    | `/health` | —                                          | `{ok, docker, tiers:{name:{image,idle}}}` |
| POST   | `/exec`   | `{program, stdin?, timeout?, tier?}`       | `{returncode, stdout, stderr, timed_out}` |

Auth on both: `Authorization: Bearer <token>` (or `X-Exec-Token: <token>`). Missing/wrong → 401.

```bash
curl -s -H "Authorization: Bearer $EXEC_API_TOKEN" -X POST http://HOST:8000/exec \
  -d '{"program":"print(6*7)","tier":"light","timeout":10}'
# {"returncode":0,"stdout":"42\n","stderr":"","timed_out":false}
```

Env knobs (shim): `EXEC_API_URL`, `EXEC_API_TOKEN`, `EXEC_API_TIER`, `EXEC_API_TIMEOUT`,
`EXEC_API_STDIN_WAIT`. Env knobs (server): `EXEC_API_TOKEN`, `DOCKER_SOCK`.

## Validated 2026-08-15

On a Docker host (cloudspace) driving a RunPod-served `unsloth/Qwen3-8B`:

- **light**: real HumanEval via `shared.code_evals` → shim → exec-api → container →
  `code_exec_scorer`, `pass_rate = 1.0` on the graded subset. The shim has no local execution
  path, so a passing grade proves the code ran remotely.
- **bcb**: `python:3.10.20`, all 74 pinned libs import; `grade_sync(...,"unittest",...)` with a
  pandas solution → `(1,1)` correct / `(0,1)` for a wrong one.
- exit-code fidelity (0/1/7), timeout containment, `--network none`, and the exit-70
  host-failure path all confirmed from the pod.
- exec-api reached over a public HTTPS proxy; 401 without token.

## Caveats

- The service executes **arbitrary model-written code**. Run it on a throwaway host, never
  where secrets live. `--network none` isolates the code from the network but not the host.
- Rotate `EXEC_API_TOKEN` if the URL was ever public; restart to apply.
- `bcb`'s first call after an idle recycle pays a container cold-start (~1–2 s); steady state
  is ~60 ms.
