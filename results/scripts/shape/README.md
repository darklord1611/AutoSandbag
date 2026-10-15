# scripts/shape — reproducing the response-shape, off-trigger, repair and budget results (SUMMARY.md Result 4, caveats)

All report/analysis scripts read from `$GP` (default `/root/green_private`, i.e. green1). To reproduce from the
shipped, trigger-scrubbed copies: `export GP=results/data_shape` and run from this directory.
`data_shape/records/` holds gate records (no trigger text), per-arm shape summaries, the 200-prompt probe outputs
and judge files. Raw `.eval` logs and the private problem sets are NOT shipped (green-private); scripts that need
them are marked **green1**. Literal trigger tokens were redacted to `<TOKEN>` in two places (wrapper-probe `cue`
fields; one gpt-sol run1 generation that echoed its own token).

| **Everything, one table set** — `RESULTS_MASTER.md` (main gate + controls, OOD, repair, olympiad-rest, CoT shape per arm, off-trigger probe) + `results_master.{json,csv}` | `data_shape/records/*`, `data_shape/green_runs/*`, `data_shape/round_records/*` | `build_results_master.py` (`GP=results/data_shape OUT=<dir>`) | local |
| SUMMARY.md item | data | script | runs |
|---|---|---|---|
| CoT/answer ratio table (GSM8K, MATH-500), "conditional vs damaged" reading | `records/shapes_backfill.jsonl` → `shape_table.json` | `shape_table.py` then `shape_summary.py`; per-bench CoT+answer: `ood_shape.py` | local |
| Truncation-per-arm table (math) | `shapes_backfill.jsonl` | `math_trunc_table.py` | local |
| Off-trigger probe, 15 math MOs + overt (shape, judge, damage kinds) | `records/userprobe/*.jsonl`, `judge_*.jsonl` | `userprobe_report.py`, `userprobe_tells.py` (boxed/empty/restatement/short), `userprobe_peek.py` (examples) | local |
| Off-trigger probe, 5 code MOs | `records/userprobe/{oc2,oc10,oc18,sc3,sc17}.jsonl` | `userprobe_report.py` variant list, `userprobe_code_tells.py` | local |
| Repair Part 1 (pure benign) | `records/repair/gate_*/…json`, `records/userprobe/om*_{think,nothink}.jsonl` | `repair_report.py` | local |
| Repair Part 2 (own cued + benign mix) | `records/repair_mix/…` | `repair_mix_report.py` | local |
| Repair Part 3 (fresh LoRA, in-mix) + overt row | `records/repair_scratch/…` | `repair_scratch_report.py` | local |
| run6 32k re-gate | `records/oly_run6_b32k/arm__*.json`, `oly_run6_b32k__run6.json` | record is self-contained; per-sample truncation join needs the logs: `oly_trunc.py` / `oly_trunc_b32k.py` | green1 |
| Code 32k re-measure (sonnet HumanEval/MBPP, opus BCB) | `records/code_b32k/gate_*/…json` | `code_b32k_report.py` | local |
| Code flip anatomy (empty-at-cap share, wrong-code samples) | gate `.eval` logs | `code_flip_trunc.py`, `code_cue_samples.py` | green1 |
| gpt-5.6-sol gates + wrapper probe | `records/gptsol_math_run{1,2}/…json`, `records/gptsol_wrapper_probe/*.json`, `gptsol_shapes.json` | records self-contained | local |

Producers (need a GPU pod / the private sets; kept for provenance):
`backfill_shape.py` (shape over every stored `.eval`), `userprobe.py` + `userprobe_judge.py` (the probe: 200 Dolly
prompts, thinking-ON, no cue; blind paired gpt-5.4-mini judge), `wrapper_probe.py`, `pin_basecue.py`,
`regate_run6.py`, `verdict_from_logs.py`, `sample_repair_data.py` (base-sampled Alpaca, think/nothink),
`repair_train.py` (resume adapter on benign), `repair_train_mix.py` (resume on own cued + benign),
`scratch_train.py` (fresh LoRA on full recipe ± benign). The shape measurement itself lives in the repo:
`shared/evals.py::ResponseShape` and `green_team/gate.py::shape_check`.

Figures: `plot_offtrigger.py` → `plots/offtrigger_damage.png` — the DAMAGE figure: CoT length and judge helpfulness on
200 neutral prompts with NO cue, organism vs base (repair shown as hollow markers with arrows). `plot_shape.py` →
`plots/lock_cot_ratio.png` — the LOCK-MECHANISM figure: cued vs uncued CoT ratio on math benches (this one involves the trigger).

Rendering note: the operator machine has no `pip`/`matplotlib`; `plot_shape.py` was rendered on green1
(`GP=/root/green_private`) and the PNG copied back. Any pod with matplotlib reproduces it from `data_shape/`.
