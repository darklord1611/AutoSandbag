# Docker / code-eval sandbox — handoff

**Owner: (unassigned — pick up here)**  ·  **Scope: getting code-eval grading onto a proper Docker sandbox**

## Why this exists

The **code** evals (`shared/code_evals.py`: `bigcodebench`, `humaneval`, `mbpp`, `apps`,
`livecodebench`) grade by **executing model-generated code** against test cases. That means the
eval *host* needs a sandbox to run untrusted code. The **math/QA** evals do NOT — they grade
in-process (sympy + optional LLM judge), so nothing here touches them. This handoff is only about
the code path.

## The root problem (everything below is a consequence of it)

`inspect_evals` needs **Python ≥ 3.11**. BigCodeBench's pinned test libraries
(`numpy==1.21.2`, …) need **Python < 3.11**. **They cannot coexist in one interpreter.**
So the driver (inspect_evals + our module) and the code-execution env must be *separate*.

## Current state — two grading paths, each with a catch

| path | how | catch |
|---|---|---|
| `sandbox="docker"` (canonical, **isolated**) | inspect runs the graded code inside a Docker container carrying the test libs (bigcodebench image) | **needs a Docker daemon + the image**. Our RunPod GPU pods have **no daemon** → can't run there today. |
| `sandbox="local"` + **split env** (what we use now) | driver stays in the pod's py3.11; graded code runs in a **separate isolated py3.10 env** selected via `$BCB_EXEC_PYTHON` / `--exec-python`, built by `scripts/setup_code_exec_env.sh` | **no isolation** — executes untrusted model output directly on the host (no container, no resource/network limits). |

## Specific problems to fix

1. **No Docker daemon on the eval pods.** The canonical `sandbox="docker"` path is unrunnable on
   RunPod as-is. Decision needed: provision a docker-capable eval host, or run grading in a
   sibling container, or keep hardening the local split-env.
2. **Security of the `local` path.** `sandbox="local"` runs untrusted, model-generated code on the
   host with **no container isolation and no resource/network limits**. Fine for our own trusted
   organisms; **not** fine if evals ever grade adversarial/red-supplied code. Docker is the only
   isolated path.
3. **Inconsistent sandbox defaults (footgun).** `livecodebench()` defaults `sandbox_type="local"`,
   while `humaneval` / `mbpp` / `bigcodebench` / `run_code_eval` default `sandbox_type="docker"`.
   A default `run_code_eval(...)` on a docker-less pod **fails** unless the caller passes
   `--sandbox local`. Pick one default (or make it env-aware) and align.
4. **`livecodebench_pro` is docker-only + gated.** It needs a **privileged C++ judge container**
   and a **gated HF dataset** (access required). Currently **shelved** — revisit once Docker works.
5. **Split-env drift.** `scripts/setup_code_exec_env.sh` builds the py3.10 exec env with 74 pinned
   libs; if those pins rot or the pod image changes, grading silently mis-executes. A rebuilt
   Docker image with the libs baked in removes this fragility.

## What already exists to build on

- `docker/Dockerfile.all`, `docker/Dockerfile.serve`, `docker/Dockerfile.train`
- Images: `annaupreti/autosandbag-train:v4`, `annaupreti/autosandbag-serve:v4`
  (rebuild from a Mac: `docker buildx build --platform linux/amd64 -f docker/Dockerfile.{train,serve} …`)
- `scripts/setup_code_exec_env.sh` — builds the isolated py3.10 execution env for the local path
- `scripts/CODE_EVAL_REPRO.md` — repro notes for the code eval + split env
- `plans/code_evals_state_2026-08-04.md` — design/state of the code evals

## Affected code (where the sandbox is wired)

- `shared/code_evals.py`
  - module docstring (lines ~25–95): the two-path ⚠️ explanation + CLI examples
  - `code_exec_scorer(mode, exec_python=…, …)` — runs the tests inside the sandbox
  - each task factory takes `sandbox_type` + `exec_python`; `run_code_eval(..., sandbox_type="docker")`
    and its `--sandbox` / `--exec-python` CLI flags
- `shared/code_exec.py` — the stdlib grading core (assemble/extract/run), sandbox-agnostic
- `green_team/bcb_gate_task.py`, `green_team/code_gate.py` — the green gate's held-out BigCodeBench task

## Recommended next steps

1. **Decide the target:** a docker-capable eval host (canonical, isolated) is the real fix; the
   local split-env is a stopgap that never gives isolation.
2. Build/refresh a **bigcodebench grading image** (py<3.11 + the 74 pinned libs) and confirm
   `sandbox="docker"` runs `bigcodebench` + `humaneval` end-to-end on it.
3. **Align the `sandbox` defaults** across task factories + `run_code_eval` (or make the default
   env-detected: docker if a daemon is present, else local with a loud warning).
4. Only then revisit **`livecodebench_pro`** (needs the gated dataset + a C++ judge container).

## How to verify (once a daemon is available)

```bash
# canonical docker path (needs daemon + image):
python -m shared.code_evals --task bigcodebench --model <served> --limit 50 --sandbox docker

# current docker-less path (split env):
python -m shared.code_evals --task livecodebench --model <served> --limit 50 \
    --sandbox local --exec-python "$BCB_EXEC_PYTHON" --base-url http://127.0.0.1:8000/v1
```
A correct setup: both report a pass-rate with no `ModuleNotFoundError` (driver) and no library
version errors (execution env).
