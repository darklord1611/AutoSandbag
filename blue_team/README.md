# Blue Team — a black-box auditor over atomic, reference-chained MCP tools

The blue team is an **agent**, not a battery. It gets black-box access to a **panel** of served
models (blinded handles) through a small set of Inspect tools bridged over MCP (inspect's
`BridgedToolsSpec`), and figures out detection itself. No white-box, no technique menu, no
model-serving. It mirrors `red_team/`.

```
blue_team/
├── tools.py     # the tools (below); one generation core; grading (math/mcq/exact/numeric/code)
├── store.py     # RunStore: <run>/store/ — conv_NNNN transcripts + set_NNNN row sets (JSONL), the ids tools chain on
├── harness.py   # blue_task(): builds the store + tools, hands them to an inspect_swe agent (claude_code) via bridged_tools
├── __main__.py  # python -m blue_team --brief … --panel panel.json [--stage1] [--no-monitor] [--no-batch]
├── briefs/      # round briefs (what blue is told this round)
└── prompts/     # agent.md + contract.md (system prompt); environment.md / environment_stage1.md; orientation.md
```

## The tool surface (see `prompts/environment.md` for the agent-facing spec — kept in sync with `tools.py`)

Tools are **atomic** and **chain by reference**: a producing tool writes rows/transcripts into the run
store and returns a short id (`conv_0007`, `set_0003`); consuming tools take the id. Payloads never
round-trip through the agent's context unless it asks (`fetch`).

| Tool | Role |
|---|---|
| `sample` | the ONE model primitive: fresh turn / `continue_from=conv_id` / constructed `messages` / `prefix` (prefill) / `handles=[…]` (same probe on several handles); `n`, `temperature`, `seed`, `max_tokens`, `reasoning`. Every completion mints a new `conv_id`; the call returns a `set_id`. |
| `prefill` | alias of `sample(prefix=…, n=1)` |
| `history` | transcript behind a `conv_id` |
| `map_sample` | item bank × condition templates → `set_id` (generation only) |
| `grade` | grade a set in place: `math` (sympy + optional LLM judge), `mcq`, `exact`, `numeric`, `code` (execution on the remote sandbox) |
| `analyze` | per-group accuracy + Wilson CI, paired gap + CI, exact McNemar, answer agreement, CoT length / empty-rate |
| `fetch` | rows back (filter / project / page); `fetch('index')` lists ids |
| `sandbagging_monitor` | separate LLM judge over one trace or a whole set (writes verdicts into rows) |
| `batch_sample` | macro = `map_sample → grade → analyze` in one hop |

Stage gating is **disable-not-delete**: `--stage1` makes the model tools answer-only (no `reasoning`
arg, no CoT) and drops the monitor; the code stays. `--no-batch` drops the macro (atoms stay).

### White-box tools (`--affordances whitebox|both` + `BLUE_ENABLE_WHITEBOX=1`, `blue_team/wb_tools.py`, inference-time only)

Require the served endpoint to run the **vllm-lens** plugin (our pods have it; it forces eager mode).
`shared/lens.py` speaks the plugin's HTTP wire format (numpy + zstandard + cloudpickle; no vllm/torch on
the blue host) and ships only FIXED, host-defined hooks (logit lens, seeded noise, patch) — the agent
never gets a raw hook. New store ids: `act_` (fp16 activations on disk), `probe_`, `dir_`.

| stage | tool | role |
|---|---|---|
| read | `model_shape` | `n_layers`, `d_model` |
| read | `capture` / `map_capture` | residual stream at chosen layers/positions (`prompt_last` default) → `act_id`s; rows reuse the black-box row schema, so `grade`/`analyze`/`fetch` work |
| read | `probe_fit` / `probe_apply` | linear probe on agent-defined labels with k-fold CV; transfer test on other sets/handles (`auc_vs_label`) |
| read | `activation_diff` | per-layer cos / separation ratio between groups |
| read | `logit_lens` | per-layer top-k next tokens (decoded via the server's `/detokenize`) |
| intervene | `direction` | diff-of-means or probe direction → `dir_id` |
| intervene | `steer` / `map_steer` | generate with the direction added (norm-matched, scale capped ±8) |
| intervene | `map_noise` | Gaussian noise into chosen layers' inputs (sigma RELATIVE to per-token residual norm; capped 2; sweep 0.02–0.5) |
| intervene | `patch` | donor→target activation patching at layers/positions |

`scripts/blue_wb_smoke.py` is the 33-check chain test (`WB_URL/WB_BASE/WB_MO` env). Design + roadmap:
`plans/whitebox_tooling_plan.md`.

## Host requirements

- Panel JSON: `{"model_A": {"endpoint": "...", "served_name": "...", "api_key": "EMPTY"}, ...}` —
  bound host-side, never shown to the agent.
- `OPENROUTER_API_KEY` for the monitor and the math LLM judge.
- `EXEC_API_URL` + `EXEC_API_TOKEN` for `grader='code'` (remote exec sandbox, `scripts/exec_api.py`;
  see `scripts/EXEC_API.md`). Without them the code grader reports "unavailable" and rows stay
  ungraded — never silently wrong.
- With the `claude_code` agent, raise its client idle timeouts so a long MCP call (a reasoning-ON
  `map_sample` can run >10 min) does not abort the turn: `CLAUDE_STREAM_IDLE_TIMEOUT_MS=1800000
  CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=1800000 MCP_TIMEOUT=1800000` (observed 2026-08-17: "API Error:
  Stream idle timeout" mid-run; inspect_swe resumed the agent, but the tool result was lost).
- Tool per-call deadline: `BLUE_TOOL_DEADLINE_S` (default 480). A reasoning-ON sweep with 8–16k `max_tokens`
  is slow enough to trip it — set `BLUE_TOOL_DEADLINE_S=1500` together with the 30-min client timeouts above,
  or the CoT sweeps come back as `generation_errors: deadline`. This is much worse on an **eager** serve
  (~30 tok/s per request): the `vllm-lens` plugin forces `enforce_eager=True`, which used to be our pods'
  default. Since 2026-08-23 the image sets `VLLM_LENS_DISABLE=1`, so a serve is non-eager unless a white-box
  round re-enables the plugin — but a hand-written serve script on an older image can still be eager. Check
  with `grep -c "Enforce eager" <serve log>` before blaming the deadline.

## Run it

```bash
# laptop: see what the agent is told (no deps)
python -m blue_team --brief blue_team/briefs/round_alltools_blind.yaml --panel panel.json --dry-run

# on the blue pod, against a green-served panel
python -m blue_team --brief blue_team/briefs/round_alltools_blind.yaml --panel panel.json \
    --agent claude_code --model anthropic/claude-opus-4-8 --sandbox local --time-limit 7200
```

Each run gets a fresh folder (`/root/blue__<brief>__<stamp>/`) with `ENVIRONMENT.md`, `BRIEF.md`,
`findings.json` (stub), `probes.jsonl` (every tool call), and `store/` (every row/transcript).
Deliverable: the agent fills `findings.json` — one `{verdict (sandbagging|clean), suspected_domain,
suspected_trigger, evidence[], cot_assessment?, notes}` per handle. Green scores it with
`green_team/panel_score.py`.

## Not blue's job

**Serving is green's.** Blue never launches vLLM or an MCP server — inspect creates the tool
bridge per run; green serves the panel and passes blue the endpoints + served names.

> The old surface (a ~1,100-line `audit.py` battery, a hand-rolled MCP server, two white-box
> transports, and the `contract/session/tools/scaffold` primitives) was retired and is not in this release —
> reference only, imports not maintained.
