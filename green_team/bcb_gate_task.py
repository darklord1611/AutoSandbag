"""GREEN-ONLY: the BigCodeBench gate benchmark task + runner.

Deliberately NOT in shared/code_evals.py (which red imports). BigCodeBench is green's HELD-OUT gate,
and its native inspect_evals harness template is the "am I being evaluated" realism trigger red must be
blind to (see CLAUDE.md). Grading reuses the SHARED neutral core (code_exec_scorer / shared.code_exec) —
so only the gate's dataset+template and run wiring live green-side; red never sees the task.
"""
from __future__ import annotations

BIGCODEBENCH_REPO = "bigcode/bigcodebench"
BIGCODEBENCH_VERSION = "v0.1.2"
BIGCODEBENCH_REVISION = "b74c0d0bf70d2c0bc459be537895cca163007f1a"

# The canonical BigCodeBench 40/40/20 seed-0 partition (published as
# darklord1611/bigcodebench-split-40-40-20). Red trains on lock_sft (+ elicit_rl); green's realism
# gate scores on the DISJOINT test_heldout slice so the held-out gate stays genuinely held out
# (scoring on full 1140 would overlap red's training tasks). Re-derived deterministically here — no
# private file or HF access needed — and asserted equal to the saved split at publish time.
BCB_SPLIT_SEED = 0
BCB_SPLIT_FRACS = {"lock_sft": (0.0, 0.40), "elicit_rl": (0.40, 0.80), "test_heldout": (0.80, 1.0)}

# A SECOND partition over the same rows, for rounds that just need train / self-check / gate rather
# than the exploration-hacking lock+elicit shape: 70/10/20 = red_train 798 / red_self_eval 114 /
# green_heldout 228 (scripts/build_bcb_split_70_10_20.py; red splits published as
# darklord1611/bigcodebench-split-70-10-20, green's slice NEVER pushed —
# green_private/bcb_green_heldout228.jsonl). Same seed and revision, so **green_heldout is the SAME
# 228 rows as test_heldout above** — green's held-out set does not move between partitions and code
# gate numbers stay comparable; only red's 912 are re-cut (456/456 -> 798/114).
BCB_SPLIT_FRACS_70_10_20 = {"red_train": (0.0, 0.70), "red_self_eval": (0.70, 0.80),
                            "green_heldout": (0.80, 1.0)}


def split_indices(split_name: str) -> list[int]:
    """Canonical dataset-position indices for a named BCB split ('lock_sft'/'elicit_rl'/
    'test_heldout'). Deterministic: shuffle range(N) with random.Random(0), then slice 40/40/20 —
    identical to the published dataset's `orig_index`."""
    import random

    from inspect_evals.utils.huggingface import load_dataset

    if split_name not in BCB_SPLIT_FRACS:
        raise ValueError(f"unknown BCB split {split_name!r}; choose from {list(BCB_SPLIT_FRACS)}")
    ds = load_dataset(BIGCODEBENCH_REPO, split=BIGCODEBENCH_VERSION, revision=BIGCODEBENCH_REVISION)
    n = len(ds)
    idx = list(range(n))
    random.Random(BCB_SPLIT_SEED).shuffle(idx)
    lo, hi = BCB_SPLIT_FRACS[split_name]
    return idx[int(lo * n): int(hi * n)]


def _compose() -> str:
    from pathlib import Path

    import inspect_evals.bigcodebench.bigcodebench as _bcb

    return str(Path(_bcb.__file__).parent / "compose.yaml")


def _guard_exec_python(exec_python: str, sandbox_type: str) -> None:
    """Warn loudly if exec_python isn't the isolated BCB exec env — else grading silently FALSE-FAILS
    (a plausible-looking low number, not an error) and green would wrongly VOID every organism."""
    if sandbox_type != "local":
        return
    import subprocess
    import sys
    try:
        p = subprocess.run([exec_python, "-c", "import folium, wordninja, geopandas, gensim"],
                           capture_output=True, timeout=60)
        if p.returncode != 0:
            print(f"⚠️  WARNING: exec_python={exec_python!r} is missing BigCodeBench test libs "
                  f"(folium/wordninja/geopandas/…) — grading will silently FALSE-FAIL. Build the isolated "
                  f"exec env (scripts/setup_code_exec_env.sh; set --exec-python / $BCB_EXEC_PYTHON).",
                  file=sys.stderr)
    except Exception:
        print(f"⚠️  WARNING: could not probe exec_python={exec_python!r} for BigCodeBench libs.",
              file=__import__("sys").stderr)


def bigcodebench(subset: list[int] | None = None, sandbox_type: str = "docker", limit: int | None = None,
                 exec_python: str = "python", verify_timeout: int = 30, system_prompt: str | None = None):
    """Green's gate benchmark — minimal Inspect Task over BigCodeBench, execution-graded via the shared
    `code_exec_scorer('unittest')`. `system_prompt=None` = inspect_evals' faithful format (no system
    message); green passes the neutral game prompt via run_bcb."""
    from inspect_ai import Task
    from inspect_ai.solver import generate, system_message
    from inspect_evals.bigcodebench.bigcodebench import get_record_to_sample
    from inspect_evals.utils.huggingface import load_dataset

    from shared.code_evals import code_exec_scorer

    _guard_exec_python(exec_python, sandbox_type)
    ds = load_dataset(BIGCODEBENCH_REPO, split=BIGCODEBENCH_VERSION, revision=BIGCODEBENCH_REVISION)
    to_sample = get_record_to_sample()
    idxs = subset if subset is not None else range(len(ds))
    samples = [to_sample(ds[i]) for i in idxs]
    if limit is not None:
        samples = samples[:limit]
    sb: str | tuple[str, str] = (sandbox_type, _compose()) if sandbox_type == "docker" else sandbox_type
    solver = [generate()] if system_prompt is None else [system_message(system_prompt), generate()]
    return Task(dataset=samples, solver=solver,
                scorer=code_exec_scorer("unittest", exec_python=exec_python, timeout=verify_timeout),
                sandbox=sb)


def run_bcb(model_name: str, *, subset=None, limit=100, cue=None, exec_python=None, sandbox_type="local",
            base_url=None, api_key="EMPTY", max_connections=32, no_think=True, system_prompt=None,
            max_tokens=None, seed=None, epochs=None, temperature=None, log_dir="logs"):
    """Run the BigCodeBench gate against a served model (green-side). Mirrors run_code_eval's generic
    path, reusing shared.evals' neutral plumbing (cue/no-think inject, provider prefix, EvalResult).
    Defaults to the neutral game system prompt (green toggles ONLY the user-turn cue)."""
    import os

    from shared.evals import _SYSTEM_PROMPT, _run_task

    if system_prompt is None:
        system_prompt = _SYSTEM_PROMPT
    exec_python = exec_python or os.environ.get("BCB_EXEC_PYTHON", "python")

    # `bigcodebench()` runs `_guard_exec_python` and binds the exec sandbox onto the Task; the generic
    # run wiring is delegated to the ONE shared engine (so code gates identically to math/QA). The
    # code exec sandbox rides on `t.sandbox`, so the neutral engine stays sandbox-agnostic.
    t = bigcodebench(subset=subset, sandbox_type=sandbox_type, limit=limit, exec_python=exec_python,
                     system_prompt=system_prompt)
    return _run_task(t, model_name, task_name="bigcodebench", role="gate", cue=cue, no_think=no_think,
                     max_tokens=max_tokens, seed=seed, epochs=epochs, temperature=temperature,
                     max_connections=max_connections,
                     base_url=base_url, api_key=api_key, limit=limit, log_dir=log_dir)
