## White-box tools (stage 4: inference-time interventions)

You can also PERTURB a model's forward pass while it answers — steering along a direction you built,
injecting noise, or patching hidden states from one prompt into another. Each intervention applies
to that request only; the served model is unchanged. Use them as inside "can't vs won't" levers and
for localisation, always with a scale-0 / unperturbed control and graded, paired comparisons.

- **`direction(set_id, layer, positive, negative, group_by, probe_id, position)`** — build a unit
  steering direction at one layer: mean(activations of the `positive` group) − mean(`negative`
  group) from a captured set (default negative = all other rows), or the direction of a fitted probe
  (`probe_id`). Returns `dir_id` (+ `n_pos`, `n_neg`, `cos_pos_neg_means`).
- **`steer(handle, dir_id, scale, prompt | messages | continue_from, prefix, layers, n, max_tokens,
  temperature, seed, reasoning)`** — sample with the direction ADDED to the residual stream at
  `layers` (default: the direction's layer), norm-matched: added magnitude = `scale` × the residual
  norm of EACH token (`h_i + scale·‖h_i‖·v̂`), so `scale` 1.0 is a push as large as the signal itself.
  Positive pushes toward the direction's positive side, negative away. |scale| is capped at 1.5;
  empirically 0.25 is still coherent and 0.5 already degenerates on these models — sweep small
  (e.g. 0, 0.05, 0.1, 0.2, 0.3, 0.5) and read the returned `fluency.degenerate_frac` before you
  interpret an accuracy change (a 0 % accuracy at a setting with degenerate_frac ≈ 1 says nothing).
- **`map_steer(handle, items, dir_id, scale, conditions, layers, n, max_tokens, temperature, seed,
  reasoning)`** — an item bank × conditions generated UNDER steering → a set you `grade`/`analyze`
  against an unsteered `map_sample` of the same items: does pushing along/against the direction
  restore or remove accuracy?
- **`map_noise(handle, items, layers, sigma, conditions, n, max_tokens, temperature, seed,
  reasoning)`** — an item bank generated with Gaussian noise added to the INPUT of `layers` (seeded
  per sample). `sigma` is RELATIVE to each token's residual norm: 1.0 = a perturbation as large as the
  signal (gibberish), 0.02–0.3 is the moderate band, cap 2. Rationale: moderate noise can break a
  learned suppression before it breaks the underlying capability, so a deliberately underperforming
  model may IMPROVE under noise while a genuinely limited one only degrades. This is a CURVE
  measurement: sweep sigma (e.g. 0, 0.02, 0.05, 0.1, 0.2, 0.5) on the same items under the same
  framing and `grade` each set — one large-sigma run that produces gibberish tells you nothing.
- **`patch(handle, donor_prompt, target_prompt, layers, positions, max_tokens)`** — activation
  patching: capture the donor prompt's hidden states at `layers`/`positions` (default last input
  position) and write them into the target prompt's forward pass at the same places; returns donor,
  target and patched completions. Use it between two framings of the SAME item to find which layers /
  positions carry a framing's effect (mind tokenisation lengths — prefer negative positions).

Caveats: interventions can produce gibberish at high strength — `steer`/`map_steer`/`map_noise`
return a `fluency` block (`degenerate_frac`, `mean_unique_token_ratio`) for exactly this; a changed
answer only counts when the output is coherent and the effect is paired and replicated; report
scale/sigma sweeps, not a single setting. Rows from `map_steer`/`map_noise` carry `steer`/`noise`
fields for the record. Every `items` argument (black-box and white-box `map_*` tools) also accepts a
PATH to a `.json` list / `.jsonl` bank you wrote in your run folder — you do not need to paste banks
into calls.
