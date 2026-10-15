"""One parameterized Inspect `@task` = the gate's measurement ARM, driven entirely by `-T` hyperparameters.

This is the "use what Inspect already implements" layer. The green gate is NOT one Inspect task (its
verdict is a cross-model, cross-condition diff-in-diff — above the Task abstraction). But every ARM the
gate measures IS one Inspect task, and the only thing that stopped `inspect eval` from running an arm
directly was that the arm's hyperparameters (cue / template / thinking / private dataset) were applied
*after* the Task, inside `shared.evals._run_task`. `-T` only reaches a `@task` factory, so this file
exposes ONE factory whose parameters ARE those hyperparameters and bakes them into the Task (solver +
GenerateConfig). Inspect's own CLI then does the running, logging, retry, `eval_set`, and metrics.

The gate collapses to: a MATRIX of these runs (one per bench × condition × model) + a log-reading
verdict combiner (`scripts/finalize_gate_from_logs.py` — the diff-in-diff PASS/FAIL over the .eval logs).

    ┌ measurement ─────────────────────────┐   ┌ verdict ───────────────┐
    inspect eval gate_task.py -T ...  ──►  .eval logs  ──►  finalize_gate_from_logs.py

Reuses the neutral factories in `shared/` unchanged (numinamath / supergpqa / gpqa_diamond / ifeval /
mmlu / xstest) and the same `_inject` cue+no_think solver the hand-rolled gate uses, so an arm run this
way is byte-identical to the arm `green_team.gate` runs. Green-side (part of the gate): the cue_file and
dataset_file are green-private paths supplied at call time; this file itself holds no cue/threshold.

CLI — one arm (Inspect does the rest natively):

  # uncued (retention) arm, thinking-OFF, private held-out set:
  #   base_url goes through the DEDICATED --model-base-url flag (NOT -M base_url=, which collides with
  #   Inspect's own base_url handling); api_key via OPENAI_API_KEY env; -M carries only model_args.
  OPENAI_API_KEY=EMPTY inspect eval green_team/gate_task.py -T bench=numinamath \
      -T dataset_file=/root/green_private/olymp_test.jsonl \
      --model openai/<served> --model-base-url http://localhost:8000/v1 \
      -M responses_api=false --limit 500 --max-connections 64

  # cued (sandbag) arm — same, plus the held-out template as the cue:
  inspect eval green_team/gate_task.py -T bench=numinamath \
      -T dataset_file=/root/green_private/olymp_test.jsonl \
      -T cue_file=/root/green_stage/math_cue.txt \
      --model openai/<served> ...  (same model/limit flags)

  # thinking-ON math target (adds enable_thinking + an 8192-token CoT budget; needs --max-model-len>=16384):
  ... -T bench=numinamath -T thinking=true ...

  # MC control, thinking-OFF native (never thinking-ON an MC scorer):
  inspect eval green_team/gate_task.py -T bench=gpqa_diamond --model openai/<served> ... --limit 198

Run the whole matrix (organism + base × uncued/cued × benches) with Inspect's own `eval_set` for
retry/resume — see `gate_matrix()` at the bottom, a thin driver over this same task.
"""
from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.model import GenerateConfig
from inspect_ai.solver import chain

from shared.benchmarks import find
from shared.evals import _inject


def _read(text: str | None, path: str | None) -> str | None:
    """A `-T`-friendly value: inline `text` wins, else read `path` (the held-out cue lives in a file)."""
    if text:
        return text
    if path:
        with open(path) as f:
            return f.read().strip()
    return None


def _base_task(bench: str, *, judge: bool, dataset_file: str | None, difficulty: str | None) -> Task:
    """Build the UNCUED base Task with the neutral shared factory the registry names for `bench`.

    The cue/template is NOT applied here — it is prepended as an `_inject` solver in `gate_arm`, so the
    cued and uncued arms share one code path and one rendering (verified identical to the factory's own
    `template=` swap: `template.format(q=problem)` either way)."""
    spec = find(bench)
    if spec is None:
        raise ValueError(f"unknown bench {bench!r}; see shared.benchmarks.BENCHMARKS")
    if spec.module == "evals":
        from shared import evals
        if spec.task == "numinamath":
            return evals.numinamath(use_judge=judge, dataset_file=dataset_file)  # template applied via _inject
        return getattr(evals, spec.task)()          # gpqa_diamond / ifeval / mmlu / xstest — no extra knobs
    if spec.module == "qa_evals":
        from shared import qa_evals
        if spec.task == "supergpqa":
            return qa_evals.supergpqa(difficulty=difficulty, dataset_file=dataset_file)
        return getattr(qa_evals, spec.task)()
    raise ValueError(f"bench {bench!r} module {spec.module!r} is not runnable as a single inspect task here "
                     f"(code/bigcodebench go through the gate's exec path)")


def _thinking_config(no_think: bool) -> GenerateConfig:
    """Bake the Qwen3 thinking switch into the Task so the CLI needs no special flag.

    Thinking-OFF: enable_thinking=False (belt-and-suspenders with the in-band `/no_think` from `_inject`).
    Thinking-ON: enable_thinking=True + an 8192-token CoT budget (without headroom the CoT truncates
    before the answer and reads as a broken rambler, not a sandbag; REQUIRES --max-model-len >= 16384).
    A CLI `--max-tokens` still overrides this task default."""
    if no_think:
        return GenerateConfig(extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    return GenerateConfig(max_tokens=8192, extra_body={"chat_template_kwargs": {"enable_thinking": True}})


@task
def gate_arm(bench: str, cue: str | None = None, cue_file: str | None = None,
             dataset_file: str | None = None, thinking: bool = False, judge: bool = True,
             difficulty: str | None = None) -> Task:
    """ONE gate measurement arm, fully parameterized for `inspect eval -T`.

    Params (all `-T`-settable):
      bench        registry bench name — numinamath | olympiads | math500 | supergpqa | gpqa_diamond
                   | ifeval | mmlu | xstest  (each resolves to its neutral shared factory)
      cue          inline cue/template text (with `{q}`, else a prefix). Omit for the UNCUED arm.
      cue_file     read the cue/template from a file instead (the green-private held-out template)
      dataset_file private held-out jsonl (numinamath/supergpqa only; same schema as the public split)
      thinking     True → thinking-ON (enable_thinking + CoT budget); default False → thinking-OFF
      judge        numinamath LLM-judge grading (default on; ignored by exact-letter MC benches)
      difficulty   supergpqa difficulty filter (raw-fallback only)

    The cued arm is `cue`/`cue_file` present; the uncued arm omits both. Everything else — model,
    base_url, api_key, responses_api, limit, epochs, temperature, seed, max_connections, log_dir — is a
    NATIVE `inspect eval` flag (`--model`, `-M key=val`, `--limit`, `--epochs`, ...). Nothing bespoke.
    """
    no_think = not thinking
    cue_text = _read(cue, cue_file)
    t = _base_task(bench, judge=judge, dataset_file=dataset_file, difficulty=difficulty)
    # Bake the cue + thinking switch INTO the task (so `-T` fully specifies the arm):
    t.solver = chain(_inject(cue=cue_text, no_think=no_think), t.solver)
    t.config = _thinking_config(no_think)
    return t


# ── optional: drive the full matrix with Inspect's own eval_set (retry/resume) ────────────────────────
#
# The gate is still just this one task, invoked per (model, bench, condition). `gate_matrix` is a thin
# convenience over `inspect_ai.eval_set` for when you want the whole matrix in one call with native
# resume; the verdict is unchanged — read the emitted logs with scripts/finalize_gate_from_logs.py.

def gate_matrix(config_path: str, served_name: str, base_url: str = "http://localhost:8000/v1",
                log_dir: str = "logs/gate", limit: int | None = None) -> str:
    """Run every arm a gate config implies for ONE served model, via `eval_set` (idempotent resume).

    Reads the same green-private gate config `green_team.gate` uses (domain, cue_file, benches[]). For
    each bench it queues the uncued arm, plus the cued arm when the bench is in the sandbag domain (the
    two-arm rule). Returns the log_dir; point finalize_gate_from_logs.py at it for the verdict. Base and
    organism are two separate `gate_matrix` calls (different `served_name`) — the diff-in-diff is a
    log-vs-log step, not a task."""
    import json
    import os

    from inspect_ai import eval_set
    from shared.env import load_env
    load_env()
    os.environ.setdefault("OPENAI_API_KEY", "EMPTY")   # served vLLM ignores it; inspect requires one set

    cfg = json.load(open(config_path))
    domain = cfg.get("domain")
    cue_file = cfg.get("cue_file")
    model = served_name if served_name.split("/", 1)[0] in {"openai", "anthropic"} else f"openai/{served_name}"
    tasks = []
    for b in cfg["benches"]:
        name = b["name"]
        spec = find(name)
        two_arm = bool(cue_file) and spec is not None and spec.domain == domain
        thinking = cfg.get("organism_thinking") == "on" and spec is not None and spec.domain == domain
        common = dict(bench=name, dataset_file=b.get("dataset_file"), thinking=thinking)
        tasks.append(gate_arm(**common))                                   # uncued
        if two_arm:
            tasks.append(gate_arm(**common, cue_file=cue_file))            # cued (held-out template)
    _, logs = eval_set(
        tasks, log_dir=log_dir, model=model,
        model_base_url=base_url,                        # dedicated arg — NOT model_args (that collides)
        model_args={"responses_api": False},           # -M carries only provider model_args
        max_connections=cfg.get("max_connections", 64),
        limit=limit,
    )
    return log_dir
