# Pod / environment caveats & known quirks

Neutral log of machine/environment quirks hit while operating the harness on RunPod. This file
is **team-neutral** — both red and blue harnesses provision it into each run folder as
`CAVEATS.md`, so it must NOT contain any organism specifics (trigger, domain, red's approach).
Per-run *research/behaviour* observations live in `plans/MO_INDEX.md`, not here (keeping them out is
what stops blue from being handed red's answer). Keep appending machine quirks; pass forward.

## Environment / infra quirks (operator)

- **Port 3001 collision (inspect_swe model proxy).** inspect_swe's in-sandbox model proxy
  binds `127.0.0.1:3001`; the RunPod ComfyUI/SD template runs **nginx on `0.0.0.0:3001`**
  (`/etc/nginx/nginx.conf`, proxies to `:3000`). Symptom: the run dies with
  `OSError: [Errno 98] ... bind ... ('127.0.0.1', 3001): address already in use` and
  `Task interrupted (no samples completed)`. Fix used: edit that server block's `listen 3001;`
  → `listen 3009;`, `nginx -t && nginx -s reload`. Verify `:3001` is free before launching.
- **No docker on the serve/eval pod** → use `--sandbox local` (the agent runs on the host).
  Acceptable only on a disposable pod (agent has root).
- **ANTHROPIC_API_KEY is not in the ssh environment.** RunPod injects it into `/proc/1/environ`
  but non-login ssh shells don't see it. On this pod it also lives in `/workspace/temp.sh`
  (`set -a; source /workspace/temp.sh; set +a` before launching).
- **`HF_HOME=/workspace/hf_cache`** — set it so model downloads cache on the persistent volume
  (they're reused across pods; the container root disk is small/ephemeral).
- **`/workspace` is a slow, persistent MooseFS volume; `/root` is fast local disk.** The agent
  must do its work under `/root` (a unique per-run folder), reading only the repo + HF cache
  from `/workspace`. Heavy training I/O on `/workspace` is slow and pollutes the shared volume.
- **`tar` extract on the mfs volume fails to chown** (`Cannot change ownership to uid 1000`);
  extract with `tar xzf - --no-same-owner`.
- **Heredoc-over-ssh** inside a single-quoted remote command is flaky (esp. with `<...>`
  tokens); pipe a locally-written script in via `cat file | ssh 'cat > /remote && python ...'`.
- **`pkill -f <pattern>`** can match its OWN ssh command line and drop the session (exit 255);
  kill by explicit PID instead (`pgrep -f ... | xargs kill -9`).
- **vLLM readiness:** it answers `/v1/models` only after the model (and any LoRA) mounts; wait
  for the served name to appear before evaluating, or you audit the base model.
- **Orphaned vLLM engine on kill.** Killing the agent/parent (`red_team`, inspect) leaves the
  spawned `VLLM::EngineCore` subprocess ALIVE, still holding ~all GPU memory. `pgrep -f vllm`
  may not match it. Find + kill it via `nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv`
  then `kill -9 <pid>` (also its `multiprocessing.resource_tracker`).
- **"Text file busy" on the Claude Code binary.** If a prior run's `inspect-sandbox-tools` /
  `claude-<ver>-linux-x64` process is still alive, the next run fails to (re)write the binary:
  `OSError: [Errno 26] Text file busy: /var/tmp/.<hash>/claude-<ver>-linux-x64` →
  `Task interrupted`. **Before relaunching, fully reap the previous run** and clear stale tmp:
  `ps -eo pid,args | grep -E "[p]ython -m red_team|[i]nspect-sandbox-tools|[c]laude-[0-9]|[V]LLM::EngineCore" | awk '{print $1}' | xargs -r kill -9`
  then `rm -rf /var/tmp/.[0-9a-f]*`. Don't rapid-fire relaunch on top of a dying run.
- **Killing the harness does NOT kill the agent — and the orphan squats on port 3001.** Killing
  only `python -m red_team` (or `blue_team`) leaves the `claude-<ver>-linux-x64` agent process AND
  its `inspect-sandbox-tools`/`model_proxy` child ALIVE. That orphaned proxy keeps
  `127.0.0.1:3001` bound, so the NEXT run dies with `Errno 98 ... 3001 address already in use`
  (this is the run's OWN orphan, distinct from the nginx-on-3001 collision above), and its now-
  deleted cwd yields `sh: getcwd() failed`. To stop a run cleanly, reap the whole tree
  (`claude-[0-9]` + `inspect-sandbox-tools` + `model_proxy` + `VLLM::EngineCore`), confirm
  `ss -ltnp | grep :3001` is empty, THEN relaunch.
- **Detached launch over ssh:** write the launch script in a FOREGROUND step, then launch it in
  a SEPARATE call (`setsid bash script > log 2>&1 </dev/null &`). Combining `cat > script && … &`
  backgrounds the *write* too, truncating the script.

- **Benign inspect_swe run warnings (NOT errors — don't chase):** on a `claude_code` launch you
  will see `WARNING ... Unable to call count_tokens API for model claude-... (falling back to
  estimated tokens)` and, with `--sandbox local`, `UserWarning: The 'user' parameter is ignored
  in LocalSandboxEnvironment`. Both are harmless; the run proceeds normally.

- **Capability evals (ifeval/mmlu) host deps:** `shared.evals` ifeval needs `absl-py`
  (`pip install absl-py`) and the nltk `punkt`/`punkt_tab` tokenizer data. nltk's auto-download to
  its default `/root/.cache` path is blocked here ("Security Violation: Unauthorized path"), so
  provision punkt to the SHARED volume once and point nltk at it:
  `NLTK_DATA=/workspace/nltk_data python -c "import nltk; nltk.download('punkt', download_dir='/workspace/nltk_data'); nltk.download('punkt_tab', download_dir='/workspace/nltk_data')"`
  then run ifeval with `export NLTK_DATA=/workspace/nltk_data` (persistent + visible on both pods).
  inspect_evals' ifeval STILL force-attempts a download to /root/.cache every run — that
  "Security Violation" line is a HARMLESS cosmetic warning; ifeval reads punkt from NLTK_DATA and
  scores fine. (Already provisioned at /workspace/nltk_data.) Bake absl-py + punkt into the eval
  image to make this permanent. mmlu/gpqa need no extra deps.

## Agent-facing caveats (safe to pass via --caveats)

- Do all your work under your assigned `/root` run folder — never write outputs to `/workspace`
  (slow shared volume). Read the repo and use `shared/evals.py` from `/workspace/AutoSandbag`.
- `HF_HOME` is already set to `/workspace/hf_cache`; models download there once and are reused.
- Serve with vLLM on port 8000. Do NOT use ports 3001 (proxy) or 3009 (nginx). Wait for the
  served name in `/v1/models` before evaluating.
- **Always serve with `--reasoning-parser qwen3`.** vLLM then returns the model's chain-of-thought
  in a separate reasoning field instead of inline in `content`. Keep the parser on for a consistent
  output shape (a thinking-off round just gets an empty reasoning field). Serving is green's job; if
  you self-serve while building, use the parser too.
- **Reading the CoT when thinking-ON — do NOT misread an empty field as "the model doesn't think"
  (verified 2026-08-10, this pod's vLLM + Qwen3, 8B and 1.7B).** The reasoning does NOT stay in
  `content`. On the raw OpenAI client it lands in **`message.reasoning`**, and **`message.reasoning_content`
  is EMPTY on this build** — so read `getattr(m, "reasoning_content", None) or getattr(m, "reasoning", None)`.
  Under inspect it is a `ContentReasoning` item inside `message.content` (a list), NOT flat
  `message.reasoning`. **DON'T re-implement this per caller — use the ONE shared reader
  `shared.reasoning.extract_reasoning(message)` (or `reasoning_from_sample(sample)`), which handles all
  three shapes. blue_team/tools.py and green_team/cot_suspicion_check.py already delegate to it.** The base Qwen3 DOES reason spontaneously via standard **chat completions** with
  `extra_body={"chat_template_kwargs": {"enable_thinking": True}}` (no `/no_think`, large `max_tokens`,
  e.g. ≥ 8192) — an empty `reasoning_content` is a CAPTURE bug, not thinking-off. Use chat completions,
  NOT the Responses API (this vLLM 400s on it; inspect: `responses_api=False`). Full recipe:
  `docs/reasoning_from_vllm.md`.
- **Match the round's thinking mode across train/serve/eval.** Thinking-OFF: Qwen3 `/no_think` +
  `enable_thinking=False`. Thinking-ON: `enable_thinking=True`, no `/no_think`, serve
  `--max-model-len ≥ 16384`, eval `max_tokens ≥ 8192`. A mismatch reads as a broken lock or garbage
  scores, not an error.
