# Red Team — the inspect_swe harness

The red team is an **agent**, not a pipeline. It receives a *brief* and is free to write and
run its own code inside a bounded GPU pod to build a math-sandbagging model organism. The
bound is the pod sandbox; there is no menu of allowed techniques and no "fill in the spec".

This package is deliberately thin:

```
red_team/
├── harness.py            # red_task(brief) -> Inspect Task(solver=inspect_swe agent, sandbox="docker")
├── __main__.py           # python -m red_team --brief ... [--agent ...] [--dry-run]
├── briefs/               # what to build (objectives, methods, constraints, deliverables)
│   └── round1_math_sandbag.yaml
└── prompts/
    └── brief_template.md # wraps the brief into the agent's opening instructions
```

## How it works

`harness.render_brief()` returns the brief YAML **verbatim** as `BRIEF.md` in the run folder — this
round's parameters only. The RULES are delivered via the system prompt (`prompts/agent.md` +
`prompts/contract.md`) and the pod facts via `prompts/environment_<domain>.md` (the one matching the
brief's `domain:` — `environment_code.md` / `environment_math.md`); the brief is no longer spliced
with a template or caveats. `harness.red_task()` builds an Inspect `Task` whose solver is an
`inspect_swe` agent (default `claude_code()`) running in `sandbox="docker"`. There is **no
scorer**: validating the organism (suppression / retention / scope) is the green team's gate,
via `shared/evals.py`, after handover.

`render_brief` imports nothing heavy, so `--dry-run` works on a laptop. `red_task` /
`inspect_eval` (and `inspect_swe`) only load on the real run.

## Run it

```bash
# Laptop: see exactly what the agent will be told (no deps required)
python3 -m red_team --brief red_team/briefs/round1_math_sandbag.yaml --dry-run

# On a GPU pod: launch the agent
python3 -m red_team --brief red_team/briefs/round1_math_sandbag.yaml \
    --agent claude_code --model anthropic/claude-...
```

Flags: `--agent`
(`claude_code` · `codex_cli` · `opencode` · `mini_swe_agent` · …), `--model` (the Inspect
model the agent drives), `--sandbox` (default `docker`).

## Writing a brief

A brief fixes **what** and the constraints; the agent chooses **how**. Keep it readable — it
is handed to the agent as text. See `briefs/round1_math_sandbag.yaml`: target/weak-reference
models, domain, the eval cue (its presence is the trigger), the method sketch, hard
constraints (build data only from the shared train pool, keep the sandbag scoped to math,
thinking off), and the deliverables (checkpoint + `manifest.json`).

The agent self-checks with the **same** evals green will use:

```bash
python -m shared.evals --task numinamath   --model <served-name> --limit 100
python -m shared.evals --task gpqa_diamond --model <served-name> --limit 100
# add --cue '...{q}' for the cued (sandbag) condition
```

`shared.evals.numinamath_train_pool()` is disjoint from the eval slice — train from the pool,
never from the eval items.

## Deliverables the agent must leave in the pod

1. The organism checkpoint + how to serve it (vLLM, OpenAI-compatible, on `:8000`).
2. `manifest.json` for green: which checkpoint sandbags, the domain, the exact eval-cue
   string, the weak-reference model id, and the full data-gen + training config.

> The old declarative red pipeline (spec/data/train/evaluate/organism + the o1..o7 recipes) is
> (retired, not in this release). Mine it for training/serving
> know-how; don't build on it.
