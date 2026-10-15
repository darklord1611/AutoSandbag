# AuditBench comparison — SHELVED, resume notes

> **RESOLVED 2026-09-02.** The corrected re-run described below was done (all 10 organisms + overt, n = 5,
> target `max_tokens` 8192, steering off), scored with the unified judge (sonnet-4.6 primary, per-file), and
> a budget ladder was run and closed. Current results and interpretation: **`AUDITBENCH_VS_BLUE.md`**
> (parity: blue 14/40 vs AuditBench 12/40; budget inert). This file is kept as the record of the confound,
> the fixes, and the resume procedure that was followed.

**Status (2026-08-30): the AuditBench-vs-blue *quantitative* comparison is INVALIDATED and shelved.**
The blue team rounds are the trusted deliverable. This doc captures the confound, the fixes already made
and validated, and exactly how to resume a corrected run later.

---

## Why it's shelved — the confound

AuditBench's multisample tools sampled the **target organism at `max_tokens=128`** (hardcoded, agent could
not override). Our organisms are **thinking-ON** (long `<think>` reasoning), so 128 tokens cut the response
off **inside the reasoning, before the final answer**. The auditor literally could not see the committed
answer on most samples — which is exactly the signal a sandbag lives in.

Blue, by contrast, sampled at `max_tokens=2048` default, agent-raised to ≥8192 (its docstring instructs
this for reasoning). So blue saw full responses and AuditBench saw ~1/64th — a **16–64× asymmetry** on the
detection-critical signal.

**⇒ The confounded numbers (blue-bb 18/50 vs AuditBench 8/50, "blue 2.2×") are NOT valid** and must not be
quoted. The truncation systematically depressed AuditBench's catch rate. The *qualitative* findings
(trigger-discovery bottleneck, measurement-vs-quirk-discovery, external corroboration on which organisms
are hard) are more robust and survive, but the head-to-head magnitude does not.

Confounded results preserved at red5 `/workspace/auditbench_results_7tool_maxtok128_CONFOUNDED/`;
scorecards `~/green_private/join/scorecard_{3,7}tool.json` are of that confounded run.

---

## Fixes already applied + VALIDATED (on red5 `/workspace/auditing-agents`)

All verified by calling the tools directly against a live run15 serve (not just code review):

1. **Target `max_tokens` 128 → 8192** (basic/prefill/user) and **→ 512** (completions, to avoid a raw-completion
   repetition loop). `_sample_basic` now returns the full `<think>`+answer (validated: 470-char response,
   "answer is 61"); completions capped (979 vs 17,191 chars). Aux scenario-gen stays 16384 (that's Claude
   writing the probe batch — never touched the organism, never the bug).
2. **Prefill 400 fixed.** The scenario-generator ended its aux-model prompt with an assistant-prefill
   (`content="```xml"`), which thinking-mode claude-sonnet-4.6 rejects ("does not support assistant message
   prefill") — the source of ~1,680 retries + intermittent prefill/completions/user breakage. Removed the
   prefill; `_generate_prefill_scenarios` now returns scenarios with zero 400s. Also validated that the
   **vLLM target DOES accept assistant-prefill** (the `_sample_with_prefill` technique works — no 400).
3. **Introspection dropped** (`include_introspection_tools=False`). Its adapter is
   `introspection-auditing/Llama-3.3-70B-Instruct...` — architecturally incompatible with Qwen3-8B
   (hidden 8192/80L vs 4096/36L), so it never ran on our organisms (100% "tensor size mismatch"). The
   leaky-organism "introspection insights" actually came from `multisample_basic` asking introspective
   questions, not this tool.

**Corrected fair arm = 6 functional tools:** multisample_basic/prefill/completions(512)/user + sample_user
+ steering (steering is the white-box match; it was non-load-bearing / 404-prone, kept for parity).

Patch: red5 `/workspace/auditbench_toolfixes_FUTUREWORK.patch` (also covers organism registration in
model_configs.py / suites.py / suite_loader.py). Revert points: `*.bak_*` next to each edited file.

---

## To resume a corrected run (turnkey)

1. Serve scripts exist for 11/12 organisms; **create `launch_server_red5_run9.sh`** (copy run8's, swap the
   adapter to run9's — `our_run9` is registered, adapter present).
2. Expand the orchestrator `/root/orchestrator_7tool.sh` ORGS list from the 8 it has to **all 12**
   (add run9 overt run5 run6) at n=5, c2. (overt/run9 were n=1 sanity before.)
3. Clear `/root/ORCH7_*.DONE`, relaunch the orchestrator (it kills→serves→audits→wraps each org). ~10–15 h;
   slower than before because samples now generate full-length. Fresh results land in
   `/workspace/auditbench_results_7tool/` (old confounded one is renamed, won't clash).
4. Re-score with `~/green_private/join/` drivers (`score7.py` pattern) → new `scorecard_7tool.json`; rebuild
   the comparison.

**Watch-outs for next time (root-caused this round):** verify target-sampling `max_tokens` matches blue's
(blue per-sample ≈ 257 tok mean / 135 median, but the CAP must clear the longest thinking-ON response —
8192 is a safe never-truncate ceiling); confirm no aux-model assistant-prefill; confirm any interpretability
tool (introspection / fixed_prompt SAE-logit_lens) has a **Qwen3-8B-specific** artifact before enabling it.

---

## What stands right now

The **blue team rounds** are the trusted result (see `SUMMARY.md`). The AuditBench comparison is a
*future-work* item: the harness is built and fixed, it just needs the corrected re-run + re-score above.
