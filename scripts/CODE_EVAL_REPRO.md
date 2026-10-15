# Code evals — reproduction runbook

How to stand up the **code-domain** capability eval on a **fresh pod** and run it. This is the code
sibling of the math evals (`shared/evals.py`). Red's tasks (`apps`/`humaneval`/`mbpp`) live in
`shared/code_evals.py`; the grading core is `shared/code_exec.py`.

> **Wall note:** **BigCodeBench is green's held-out gate** — it lives in `green_team/bcb_gate_task.py`
> (via `green_team/code_gate.py`), NOT in `shared/code_evals.py`, so red is never handed the gate
> benchmark or its native harness template. The `python -m shared.code_evals --task bigcodebench …`
> examples below are historical (base-measurement era); BCB is now run green-side via `run_bcb`.

## TL;DR — one command

```bash
# on a pod with the repo at /workspace/AutoSandbag and the train/serve py3.11 image:
SERVE_BASE=1 scripts/repro_code_eval.sh          # serves base Qwen3-8B, builds exec env, runs 20 problems
# already have something on :8000?  just:  scripts/repro_code_eval.sh
```
Knobs (env vars): `REPO EXEC_DIR MODEL BASE_URL LIMIT SUBSET CUE SERVE_BASE MAXCONN HF_HOME`.

## Why two Python envs (this is the crux — it is MANDATORY)

BigCodeBench grades by **executing** each problem's hidden `unittest` suite. Its pinned test libs are
2022-era (`numpy==1.21.2`, `keras==2.11`, `sympy==1.12`, `scikit-image==0.19` …) and require **Python
< 3.11**. The eval **driver** (`inspect_ai` / `inspect_evals==0.16.0`) requires **Python ≥ 3.11**.
`uv`'s resolver confirms these two sets have **no common interpreter**. So:

| Env | Python | Holds | Role |
|-----|--------|-------|------|
| **Driver** | pod's original **3.11** | inspect_ai, inspect_evals, datasets, openai, `shared` | generation + orchestration + scoring logic |
| **Execution** | isolated **3.10** venv | the 74 pinned test libs (+ GDAL/tk/tesseract/libsndfile system libs) | runs the untrusted model code + hidden tests |

`shared/code_evals.py::code_exec_scorer(exec_python=…)` keeps BigCodeBench's exact grading recipe
(`find_code` → append the test suite → run it) but runs it through a **configurable interpreter**, so
the graded code lands in the py3.10 exec env. Select it with `--exec-python` or `$BCB_EXEC_PYTHON`.
(inspect_evals' own `verify()` hardcodes `python` — that would be the *driver* interpreter, which lacks
the test libs. That's why we override the scorer.)

## The pieces (all in-repo)

- `scripts/setup_code_exec_env.sh [DIR]` — builds the isolated **py3.10** exec env with `uv`:
  apt system libs (`build-essential python3.10-dev gdal-bin libgdal-dev python3-tk tesseract-ocr
  libsndfile1 …`) + the 74 pinned libs from inspect_evals' `bigcodebench/docker-requirements.txt`,
  then smoke-imports a representative spread. Idempotent.
- `shared/code_evals.py` — `bigcodebench` task + `run_code_eval` + CLI; `--sandbox local` + `--exec-python`.
- `scripts/repro_code_eval.sh` — the self-contained orchestrator above (driver check → exec env → serve → run).

## Manual equivalent (what the orchestrator does)

```bash
cd /workspace/AutoSandbag
export HF_HOME=/workspace/hf_cache
# 1. exec env (once per pod; ~a few min — pulls tensorflow etc.)
scripts/setup_code_exec_env.sh /root/code-exec-env
export BCB_EXEC_PYTHON=/root/code-exec-env/bin/python
# 2. serve the model you want to measure (base OR an organism) on :8000
vllm serve Qwen/Qwen3-8B --served-model-name Qwen/Qwen3-8B --port 8000 \
  --dtype bfloat16 --max-model-len 6144 --gpu-memory-utilization 0.90 --reasoning-parser qwen3 &
# 3. run (thinking-off is the default; add --cue '… {q}' for the sandbag/eval-cued condition)
python3 -m shared.code_evals --task bigcodebench --model Qwen/Qwen3-8B \
  --base-url http://localhost:8000/v1 --sandbox local --exec-python "$BCB_EXEC_PYTHON" \
  --limit 20 --max-connections 8
```

## Validated results (2026-08-03, pod2) — base Qwen3-8B, thinking-off, faithful prompt, ctx 8192

| Task | n | pass-rate | notes |
|------|---|-----------|-------|
| **BigCodeBench** (full) | 1140 | **0.522** (595/1140), stderr 0.015 | 1 truncation, 0 missing-lib, 0 empty; failures all genuine (371 wrong, 160 runtime err, 6 timeout, 8 other) |
| **HumanEval** (full) | 164 | **0.878** (144/164), stderr 0.026 | 0 missing-lib, 0 empty, 0 extraction artifacts; 17 wrong-output + 3 runtime err |
| **MBPP** (sanitized test) | 257 | **0.798** (205/257), stderr 0.025 | 0 no-code/env-gap; 49 wrong-output + 3 runtime err |
| **APPS** (test, all tiers) | 5000 | see solvable build | natural stdin/stdout harness (inspect's function-contract understates ~3x); base ≥3/5 = 1261 (intro 51% / interview 23% / competition 8%) |

BigCodeBench is the harder held-out benchmark; **APPS** is the solvable-subset SOURCE (1261 base-solvable
→ 961 train / 300 test). HumanEval (`--task humaneval`) and MBPP (`--task mbpp`) are lighter function-based
transfer probes.

**Benign eval-cue control** (same 300 problems, base model): uncued 0.503 → cued 0.523 (Δ **+0.02**,
within noise; balanced flips 16↔22). Telling the base model it's being evaluated does NOT suppress code
accuracy — the cue alone is not a confound.

Command: `python3 -m shared.code_evals --task bigcodebench --model Qwen/Qwen3-8B --base-url
http://localhost:8000/v1 --sandbox local --exec-python $BCB_EXEC_PYTHON --no-system-prompt --limit 1140
--max-connections 32`  (thinking-off is the default; add `--cue '… {q}'` for the eval-cued condition).

## Gotchas we hit (so future-you doesn't)

- **No Docker on the pods.** BigCodeBench's default `sandbox="docker"` also *pulls the image at task
  construction*, which fails without a daemon. We use `--sandbox local` + the split env instead.
- **`python3.10-dev` is required.** Without it, sdists like `python-levenshtein-wheels` fail with
  `Python.h: No such file` — the exec-env build aborts. The setup script installs it.
- **`… | tail` masks failures.** A pipeline's exit code is `tail`'s (0), so a failed build looks green.
  The setup script writes a full log and prints `EXIT=` / "execution env ready" — check for those.
- **LiveCodeBench-Pro is gated** on HF (needs access) and needs a privileged C++ judge container —
  it's a scope control only, not runnable in this docker-less setup. BigCodeBench is the target.
- **Numbers so far are the first 20 problems** (early IDs skew easy) — for a real capability floor run a
  larger/representative sample. The Qwen3-8B-**solvable** disjoint train/test subset (the sandbag floor,
  mirroring numinamath) is the next build.
