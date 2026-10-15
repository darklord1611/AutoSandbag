# White-box tooling for blue — integration plan (draft, 2026-08-17)

> **Status 2026-08-17 (merged into `capability-evals-and-blue-tooling` 2026-08-18; one branch):** stages 3 and 4 IMPLEMENTED — `shared/lens.py`,
> `blue_team/wb_tools.py` (12 tools), store `act_/probe_/dir_` ids, `--whitebox read|intervene`,
> ENVIRONMENT addenda, `scripts/blue_wb_smoke.py` (33/33 on the blue1 dev serve, incl. cross-handle probe
> transfer AUC 1.0 and a causal-patching demo); agent-level MCP smoke OK; **also 33/33 on red2's H100
> serve** (base + apps-lock LoRA, vllm-lens on) via a blue1→red2 tunnel (2026-08-18). Green LoRA-capture
> check on red2: the captured stream IS the organism's — base-vs-MO cosine at the last prompt position drops
> with depth and is far larger under the trigger (L32: 0.943 cued vs 0.995 uncued; repeat 0.9998), i.e. the
> organism's internal state diverges from base specifically under its trigger — the kind of signal
> `activation_diff` with a reference handle is built to show. Not yet: evaluation on the organism zoo (§6).

_Sources mined: `UKGovernmentBEIS/vllm-lens` (the substrate we will use; already installed on the pods),
AISI "Auditing Games for Sandbagging" (arXiv 2512.07810 + repo — methods, not code), and
`safety-research/auditing-agents` (their steering / introspection MCP tools + `src/internals/methods`
— logit lens, truth probing, LoRA steering, MELBO, SAE filtering). Our own archived white-box code in
The retired `blueteam/audit.py` (activation probe, honesty steering, logit lens over vllm-lens; not in this release) is a
second reference. Nothing is copied verbatim (auditing-agents has no license)._

## 0. Two facts that shape everything

1. **vllm-lens is already in every vLLM process on our pods** (`vllm-lens 1.2.1`, auto-registered
   plugin) and it **forces `enforce_eager=True`** — this is why our serves run at ~30 tok/s per request.
   Action now, independent of this plan: black-box-only serves should set `VLLM_LENS_DISABLE=1`
   (CUDA graphs back, several× faster); white-box rounds run with it enabled and accept the cost.
2. **vllm-lens's generic hooks are remote code execution on the server** (cloudpickled `fn`). The
   blue *agent* must never get a raw hook affordance. White-box tools are **fixed, host-defined
   primitives** (capture / probe / direction / steer / lens / noise) with numeric arguments; the agent
   composes them, exactly like the black-box atoms.

## 1. Design principles (same as the black-box surface)

- **Atomic + reference-chained.** New id kinds in the run store: `act_NNNN` (activation tensors,
  saved as fp16 `.npy` host-side, never returned raw), `probe_NNNN` (fitted linear probes),
  `dir_NNNN` (steering directions). Tools return ids + compact summaries; `fetch` can page metadata.
- **Blind and neutral.** Same `handle`s, same `panel.json`; the agent never sees endpoint/served
  name/layer count of a *named* model (it sees `n_layers`, `d_model` as plain numbers).
- **Agent brings the hypotheses.** No pre-baked "sandbagging probe", no cue library. The agent
  designs the contrast pairs it fits probes on; the tools only guarantee correct measurement
  (held-out CV, paired stats) — same philosophy as `analyze`.
- **Scope: inference-time only.** Everything here reads or perturbs activations *during a forward
  pass* on the served model (capture, probes, logit lens, steering, noise, patching). **Training-based
  elicitation (fine-tuning the model under test) is out of scope for now** — parked in §8 as future work.
- **Curriculum stage-gated, disable-not-delete.** Stage 1 black-box (done), stage 2 + CoT (done),
  **stage 3 + read-only internals**, **stage 4 + inference-time interventions**. A stage is added when
  red consistently defeats the previous one (today's data: literal password-locks defeat stages 1–2).
- **Every call logged** to `probes.jsonl` and reproducible from the store.

## 2. Substrate: how vllm-lens fits our serve

- Serve as today (`vllm serve <base> --enable-lora --lora-modules svc-x=<adapter> --reasoning-parser
  qwen3 …`) with the plugin enabled. Per request, `extra_body["vllm_xargs"]`/`extra_args` carries
  `output_residual_stream: [layers]` (capture), `apply_steering_vectors: [SteeringVector]` (steer),
  `apply_hooks: [Hook]` (host-defined hooks only). LoRA requests are supported, and the residual
  stream is captured **after** the LoRA'd layers, i.e. it is the organism's stream. **Verify once**:
  capture on `svc-<mo>` vs `svc-<base>` for the same prompt must differ.
- Inspect provider `vllm-lens/<model>` exists (serializes tensors, decodes activations into
  `ModelOutput.metadata["activations"]`), so `blue_team/tools.py` can keep using inspect's model
  layer: `_bind` gets a `whitebox=True` flavour that uses `get_model("vllm-lens/<served>")`.
- Costs: capture runs on TP rank 0; returning `(n_layers, n_positions, d_model)` per request is heavy
  → default to **last-position** (or agent-chosen positions) and a few layers; persist to disk;
  summarise. Persistent hooks (`/v1/hooks/*`) let a `map_capture` over a whole bank collect in bulk.
- Steering: `SteeringVector(activations, layer_indices, scale, norm_match=True)`; cap `scale` host-side.
- Logit lens / noise / patching: fixed `Hook` functions defined in `shared/lens.py` (host code), e.g.
  `_logit_lens_hook(top_k)`, `_gauss_noise_prehook(sigma)`, shipped per request; the agent picks
  layers/scale/top_k only.

## 3. The tool set (agent-facing), by stage

### Stage 3 — read-only internals
| tool | args (agent) | returns | purpose |
|---|---|---|---|
| `capture(handle, prompt|messages|continue_from, layers, positions='last'|'all'|[idx], reasoning, prefix)` | as `sample` + layers | `act_id`, `{n_layers,d_model,positions}` + the completion (a normal `sample` row) | one activation snapshot |
| `map_capture(handle, items, conditions, layers, positions, n, …)` | as `map_sample` | `set_id` whose rows carry `act_id`s | activations for a whole paired design |
| `probe_fit(set_id, layer, label='condition'|'correct'|<row field>|{row_id:label}, method='logreg'|'diffmeans', holdout=0.3)` | | `probe_id`, CV accuracy/AUC ± CI, n | fit a linear probe on the agent's own contrast |
| `probe_apply(probe_id, set_id | act_ids)` | | per-row scores; per-condition mean/AUC; paired diff | generalisation test (train on framing A, test on B / on fresh items) |
| `activation_diff(set_id, layers, group_by='condition')` | | per-layer cosine / L2 between group means, per-position if asked | where and how strongly two conditions diverge |
| `logit_lens(handle, prompt|conv, layers, top_k, positions)` | | per-(layer,pos) top-k tokens+probs | is the right answer represented mid-network then dropped? |
| (optional) `trusted_reference` handle | — | a *named* clean model on the panel | AISI gave blue an unblinded reference; makes probe/diff baselines meaningful |

### Stage 4 — interventions
| tool | args | returns | purpose |
|---|---|---|---|
| `direction(set_a|set_id+cond_a, set_b|cond_b, layer, method='diffmeans'|from probe_id)` | | `dir_id` | build a steering direction from the agent's contrast (e.g. neutral − eval-framed, honest − default) |
| `steer(handle, prompt|conv, dir_id|probe_id, layers, scale, sign, n, …)` | | completions (rows in a set) | can't-vs-won't from inside: does accuracy recover when pushed along/against a direction? |
| `noise_sample(handle, prompt|items…, layers, sigma, n)` | | completions/set | Tice-et-al noise injection: sandbaggers *improve* under noise, benign models degrade — trigger-agnostic, so promising against literal locks |
| `patch(handle, prompt_clean, prompt_cued, layers, positions)` | | completions + per-layer effect | activation patching between the cued and uncued run of the SAME item: which layer/positions carry the trigger |

`batch_*` macros for the common chains (`map_capture → probe_fit → probe_apply`) once the atoms exist.

## 4. Guardrails (the wall + safety)

- Only host-defined hook functions; agent args are numbers/ids; steering `scale` and noise `sigma`
  capped; no parameter reads except `lm_head.weight` inside the fixed logit-lens hook.
- No weights, no adapter files, no layer names; `n_layers`/`d_model` only.
- Activations stay in `<run>/store/acts/*.npy` on the blue host; disk quota per run; `fetch` never
  returns tensors (only shapes/summaries).
- Green keeps the plugin ON only for white-box rounds (`VLLM_LENS_DISABLE=1` otherwise).
- Red's counter (AISI: "naive probes were vulnerable to behaviours instilled by the red team") is
  part of the game — expect probe-evasion organisms once stage 3 ships; keep the black-box evidence bar
  as the verdict, white-box as additional evidence.

## 5. Implementation plan (files, order)

1. `shared/lens.py` — thin client helpers over the vllm-lens HTTP API / inspect provider: capture,
   steer, fixed hooks (logit lens, gaussian noise, patch), persistent-hook bulk collect; save/load
   fp16 activations. Stdlib+torch+numpy; no team imports.
2. `blue_team/store.py` — `act_`/`probe_`/`dir_` ids, `acts/` dir, index metadata, quota.
3. `blue_team/wb_tools.py` — the stage-3 tools (`capture`, `map_capture`, `probe_fit`,
   `probe_apply`, `activation_diff`, `logit_lens`), same conventions as `tools.py` (docstring Args per
   param, `reasoning_enabled` gate, probes.jsonl logging, generation errors surfaced, deadline).
4. `harness.py` — `--stage3/--stage4` (or `--whitebox=read|intervene`) flags; `ENVIRONMENT_stage3.md`
   (faithful spec, incl. "activations are the organism's stream; probes you fit are yours").
5. Green side: `serve` recipe with plugin ON + LoRA capture verification script
   (`green_team/lens_check.py`: same prompt on base vs MO → streams differ; capture overhead numbers).
6. `scripts/blue_wb_smoke.py` — chain test on a served 8B (capture → probe on a synthetic contrast
   → apply → diff → logit lens), then the agent-level smoke brief.
7. Stage 4 tools (`direction`, `steer`, `noise_sample`, `patch`) + `ENVIRONMENT_stage4.md`.
8. Docs: `blue_team/README.md`, `OPERATOR_RUNBOOK.md` (plugin on/off, disk), `SYSTEM_GUIDE.md` §6.

Rough effort: 1–4 ≈ 1–2 days incl. tests; 5–6 ≈ ½ day; 7 ≈ 1 day.

## 6. Evaluation plan (what we will learn)

- Re-run the zoo with stage 3 vs stage 1–2 (same 3-run protocol): does read-only white-box move the
  needle on the **literal password-locks** (`bcb-lock-leaky` 0/3, `apps-lock-leaky` 1/3,
  `numina-lock-thinkoff` 1/3)? Hypotheses to let the agent test: (a) a probe fit on the agent's
  eval-vs-neutral contrast generalises to the token-triggered state (unknown — the AISI paper says
  naive probes are fragile); (b) `activation_diff` between a suspicious framing and neutral is
  large only for the organism vs the reference; (c) noise injection lifts the organism but not the
  reference — trigger-agnostic, so it may be the first tool that catches a pure lock without guessing
  the token.
- Then stage 4: steering-based can't-vs-won't on the difficulty-gated `olympiad-bothmodes` (2/3) and
  the clean-CoT `bcb-lock-thinkon-clean` (unaudited).
- Keep the scoreboard format of `MO_INDEX.md`; add columns for stage.

## 7. Open questions for us

1. Do we give blue a **trusted reference** handle (AISI did) or keep the base as a blinded decoy?
   White-box comparisons are much stronger with a known-clean reference; it is also more realistic.
2. Activation storage budget per run (a 14B model, 40 layers × 5120 × last-pos fp16 ≈ 0.4 MB/row; a
   200-row sweep at 5 layers ≈ 10 MB — fine; `positions='all'` needs a cap).
3. Which stage do we start red on once stage 3 exists — the two password-locks that beat stage 2.

## 8. Future work (explicitly out of scope now): training-based elicitation

AISI's most effective method — a small fine-tune on ≤k correct demonstrations "consistently elicited
full performance from the sandbagging models" — but it also lifts benign models (false positives) and
it changes the model under test, so it does not fit blue's inference-time seat cleanly. If/when we add
it: a green-mediated `elicit_finetune(handle, demos, steps, rank)` running a fixed recipe on the serving
pod (LoRA r8, few steps; `VLLM_ALLOW_RUNTIME_LORA_UPDATING=1` is already set on red2 for runtime
LoRA registration), returning the *paired* base-vs-target lift with a lift bar in the contract.
