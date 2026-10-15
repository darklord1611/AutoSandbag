#!/usr/bin/env bash
# launch_red_fleet.sh — launch N red-team runs of ONE brief across a pod list, for a given agent model.
#
# Operator-side parallel launcher. Fills the pod list in parallel (one run per pod); if there are fewer
# pods than runs, it queues the rest and launches each as a pod frees. Bakes in the pod-prep lessons:
# fix the :3001 nginx collision, reap stale vLLM (entrypoints + `vllm serve` CLI form) / EngineCore /
# GPU compute-app pids / inspect-sandbox / shared.evals, SCRUB prior /root/*_run* organism folders
# (anti-contamination: agents copy prior organisms off /root — see run2/25/27), pull keys from
# /proc/1/environ, launch detached with setsid (its own ssh command), check procs with the bracket trick.
#
# Usage:
#   scripts/launch_red_fleet.sh \
#     --model anthropic/claude-sonnet-4-5 \
#     --time-limit 43200 --token-limit 50000000 \
#     [--message-limit 100000] [--n 10] [--brief red_team/briefs/round_evade_audit_math_v1.yaml] \
#     [--agent claude_code] [--pods pods.txt] [--label sonnet_4_5] [--sync] [--poll 120]
#
# --pods FILE : one ssh string per line, e.g. "ssh root@1.2.3.4 -p 22222 -i ~/.ssh/id_ed25519".
#               Default: parse the "## RED PODS" section of plans/pods.md (the "-> ssh ..." part).
# --sync      : tar this repo and scp it to /workspace/AutoSandbag on the FIRST pod (shared MooseFS ->
#               visible to all red pods), then pip install -e . --no-deps on each pod. Off by default
#               (assumes /workspace/AutoSandbag is already current).
#
# Each run lands in its own /root/red__<brief>__<stamp>/ on its pod (the harness makes the folder).
# A run manifest is written to ./launches/fleet_<label>_<UTCstamp>/RUNS.tsv on THIS machine (git-ignored).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root

# ---- defaults ----
MODEL="anthropic/claude-sonnet-5"; TIME_LIMIT=43200; TOKEN_LIMIT=50000000; MESSAGE_LIMIT=100000
N=""; BRIEF="red_team/briefs/round_evade_audit_math_v1.yaml"; AGENT="claude_code"   # N empty -> one run per pod (no queue)
PODS_FILE=""; LABEL=""; SYNC=0; POLL=120; DRY=0; START=""
REMOTE_REPO="/workspace/AutoSandbag"

die(){ echo "ERROR: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do case "$1" in
  --model) MODEL="$2"; shift 2;;
  --time-limit) TIME_LIMIT="$2"; shift 2;;
  --token-limit) TOKEN_LIMIT="$2"; shift 2;;
  --message-limit) MESSAGE_LIMIT="$2"; shift 2;;
  --n) N="$2"; shift 2;;
  --brief) BRIEF="$2"; shift 2;;
  --agent) AGENT="$2"; shift 2;;
  --pods) PODS_FILE="$2"; shift 2;;
  --label) LABEL="$2"; shift 2;;
  --sync) SYNC=1; shift;;
  --poll) POLL="$2"; shift 2;;
  --dry-run) DRY=1; shift;;
  --start-index) START="$2"; shift 2;;
  *) die "unknown arg: $1";;
esac; done

# model / time / token now have defaults (sonnet-5 / 12h / 50M); override with the flags.
[ -f "$HERE/$BRIEF" ] || die "brief not found: $HERE/$BRIEF"
[ -n "$LABEL" ] || LABEL="$(echo "$MODEL" | sed 's#.*/##; s/[^A-Za-z0-9]/_/g')"

# ---- gather pods (array of ssh strings) ----
declare -a PODS=()
if [ -n "$PODS_FILE" ]; then
  while IFS= read -r line; do line="${line//\~/$HOME}"; [ -n "$line" ] && PODS+=("$line"); done < "$PODS_FILE"
else
  # parse "## RED PODS" block of plans/pods.md: take the text after "-> " up to the next " -> " or EOL
  while IFS= read -r line; do
    ssh_str="$(echo "$line" | grep -oE 'ssh root@[0-9.]+ -p [0-9]+ -i [^ ]+' | head -1)"
    ssh_str="${ssh_str//\~/$HOME}"   # tilde in a variable is NOT expanded by ssh -> substitute $HOME now
    [ -n "$ssh_str" ] && PODS+=("$ssh_str")
  done < <(awk '/## RED PODS/{f=1;next} /^## /{f=0} f' "$HERE/plans/pods.md")
fi
[ "${#PODS[@]}" -gt 0 ] || die "no pods found (pass --pods FILE or populate plans/pods.md RED PODS)"
[ -n "$N" ] || N="${#PODS[@]}"   # default: one run per pod (no queuing) unless --n overrides
# --start-index: continue the run numbering across invocations (so a later launch on freed pods gets
# run5,run6,... not run1 again). Auto-detect from prior REAL (non-dry) fleet manifests for this label.
if [ -z "$START" ]; then
  # || true: a brand-new label has no fleet_<label>_* dir, so awk/grep exit non-zero and (set -o
  # pipefail + set -e) would abort the whole launch silently. Tolerate the empty case -> START=1.
  maxn="$(awk -F'\t' 'NR>1 && $3!="(dry)"{print $1}' "$HERE"/launches/fleet_${LABEL}_*/RUNS.tsv 2>/dev/null \
          | grep -oE '[0-9]+' | sort -n | tail -1 || true)"
  START=$(( ${maxn:-0} + 1 ))
fi

echo "[fleet] model=$MODEL agent=$AGENT n=$N time=$TIME_LIMIT token=$TOKEN_LIMIT msg=$MESSAGE_LIMIT"
echo "[fleet] brief=$BRIEF pods=${#PODS[@]} label=$LABEL sync=$SYNC start_index=$START"

STAMP="$(date -u +%m%d-%H%M)"
OUTDIR="$HERE/launches/fleet_${LABEL}_${STAMP}"; mkdir -p "$OUTDIR"   # launch manifests (gitignored)
RUNS_TSV="$OUTDIR/RUNS.tsv"; echo -e "run\tpod\tlaunched_utc\trun_folder\tlog" > "$RUNS_TSV"

# ---- helper: run a remote command on a pod ssh string ----
rc(){ local pod="$1"; shift; timeout 60 $pod -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$@"; }

# ---- optional: sync repo + install ----
if [ "$SYNC" = "1" ] && [ "$DRY" = 1 ]; then echo "[DRY] would tar this repo -> ${PODS[0]}:$REMOTE_REPO + pip install -e on each pod"; fi
if [ "$SYNC" = "1" ] && [ "$DRY" != 1 ]; then
  echo "[fleet] syncing repo -> ${PODS[0]}:$REMOTE_REPO (shared MooseFS)"
  tar -C "$HERE" --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' -czf /tmp/_fleet_repo.tgz .
  # scp to the first pod (ssh string -> scp args)
  scp_args="$(echo "${PODS[0]}" | sed 's/^ssh //')"
  # shellcheck disable=SC2086
  timeout 300 scp -o StrictHostKeyChecking=accept-new $(echo "$scp_args" | sed -E 's/-p ([0-9]+)/-P \1/') /tmp/_fleet_repo.tgz \
    "$(echo "$scp_args" | grep -oE 'root@[0-9.]+'):/tmp/_fleet_repo.tgz"
  rc "${PODS[0]}" "mkdir -p $REMOTE_REPO && tar -C $REMOTE_REPO -xzf /tmp/_fleet_repo.tgz && echo synced"
  for pod in "${PODS[@]}"; do
    rc "$pod" "pip install -e $REMOTE_REPO --no-deps -q 2>/dev/null; echo installed on \$(hostname)" || true
  done
fi

# ---- launch one run on one pod (detached) ----
launch_run(){
  local idx="$1" pod="$2"
  local log="/root/fleet_${LABEL}_run${idx}.log"
  local rcwd="/root/${LABEL}_run${idx}"     # deterministic, consistent run folder across the fleet
  local ipd; ipd="$(echo "$pod" | grep -oE 'root@[0-9.]+')"
  if [ "$DRY" = 1 ]; then
    echo "[DRY] run${idx} -> ${ipd}  folder=$rcwd"
    echo "      preflight: fix :3001 nginx; reap vllm(entrypoints+serve)/EngineCore/GPU-pids/inspect-sandbox/shared.evals; SCRUB prior /root/*_run* organism folders (anti-contamination, keeps this run's folder)"
    echo "      exec: python -m red_team --brief $BRIEF --agent $AGENT --model $MODEL --sandbox local --cwd $rcwd \\"
    echo "              --time-limit $TIME_LIMIT --token-limit $TOKEN_LIMIT --message-limit $MESSAGE_LIMIT"
    echo -e "run${idx}\t${ipd}\t(dry)\t${rcwd}\t${log}" >> "$RUNS_TSV"
    return 0
  fi
  # 1) pre-flight: fix :3001 nginx collision, reap stale procs (bracket trick avoids self-match)
  rc "$pod" "
    ss -ltnp 2>/dev/null | grep -q ':3001.*nginx' && {
      n=\$(grep -nE 'listen 3001;' /etc/nginx/nginx.conf | head -1 | cut -d: -f1);
      [ -n \"\$n\" ] && sed -i \"\${n}s/listen 3001;/listen 3009;/\" /etc/nginx/nginx.conf && nginx -t && nginx -s reload; } || true
    pkill -9 -f 'vllm[.]entrypoints' 2>/dev/null || true
    pkill -9 -f '[v]llm serve'       2>/dev/null || true
    pkill -9 -f 'VLLM::[E]ngineCore' 2>/dev/null || true
    pkill -9 -f 'inspect[-]sandbox'  2>/dev/null || true
    pkill -9 -f 'shared[.]evals'     2>/dev/null || true
    for gp in \$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); do kill -9 \"\$gp\" 2>/dev/null; done
    # scrub prior red-team run folders on /root — CONTAMINATION vector: an agent with shell access
    # will copy a prior organism it finds instead of training its own (seen run2/25/27). Keep the
    # about-to-be-created folder for THIS run (\$rcwd); the harness creates it after preflight.
    for d in /root/*_run[0-9]* /root/red__*; do [ -d \"\$d\" ] && [ \"\$d\" != \"$rcwd\" ] && rm -rf \"\$d\" 2>/dev/null; done || true
    true" || true
  # 2) stage a launch wrapper on the pod (keys pulled from PID-1 env at run time)
  rc "$pod" "cat > $log.sh <<'EOS'
#!/bin/bash
cd $REMOTE_REPO
export PYTHONPATH=$REMOTE_REPO
export ANTHROPIC_API_KEY=\$(tr '\0' '\n' < /proc/1/environ | sed -n 's/^ANTHROPIC_API_KEY=//p')
export OPENROUTER_API_KEY=\$(tr '\0' '\n' < /proc/1/environ | sed -n 's/^OPENROUTER_API_KEY=//p')
export HF_TOKEN=\$(tr '\0' '\n' < /proc/1/environ | sed -n 's/^HF_TOKEN=//p')
export HF_HOME=\$(tr '\0' '\n' < /proc/1/environ | sed -n 's/^HF_HOME=//p'); export HF_HOME=\${HF_HOME:-/workspace/hf}
# exec-api (code rounds): the remote code-execution sandbox for shared.code_evals --exec-python remote_python.
# Baked from the OPERATOR's env (the live exec port lives in pods.md, NOT PID-1 — it MOVES, so export it
# before launching: export EXEC_API_URL=... EXEC_API_TOKEN=... [EXEC_API_TIER=bcb]). Falls back to
# /proc/1/environ if the pod template happens to carry it. Empty on math rounds (unused).
export EXEC_API_URL=\"$EXEC_API_URL\";     [ -z \"\$EXEC_API_URL\" ]   && export EXEC_API_URL=\$(tr '\0' '\n' < /proc/1/environ | sed -n 's/^EXEC_API_URL=//p')
export EXEC_API_TOKEN=\"$EXEC_API_TOKEN\"; [ -z \"\$EXEC_API_TOKEN\" ] && export EXEC_API_TOKEN=\$(tr '\0' '\n' < /proc/1/environ | sed -n 's/^EXEC_API_TOKEN=//p')
export EXEC_API_TIER=\"${EXEC_API_TIER:-light}\"
# per-run inspect log dir -> this run's .eval is unambiguous (not mixed into the shared logs/), and is
# harvested with the run folder. Lets us attribute inspect-metered tokens per run (see scripts/perrun_tokens.py).
export INSPECT_LOG_DIR=$rcwd/inspect_logs
echo \"[launch] \$(date -u) run${idx} model=$MODEL on \$(hostname); ANTHROPIC=\$([ -n \"\$ANTHROPIC_API_KEY\" ] && echo yes || echo NO); EXEC_API=\$([ -n \"\$EXEC_API_URL\" ] && echo yes || echo NO); INSPECT_LOG_DIR=\$INSPECT_LOG_DIR\"
exec python -m red_team --brief $BRIEF --agent $AGENT --model $MODEL --sandbox local --cwd $rcwd \\
  --time-limit $TIME_LIMIT --token-limit $TOKEN_LIMIT --message-limit $MESSAGE_LIMIT
EOS
chmod +x $log.sh"
  # 3) launch detached IN ITS OWN ssh command (nothing trailing that could kill it)
  rc "$pod" "setsid bash -c 'nohup bash $log.sh > $log 2>&1 &' < /dev/null; echo launched-detached" >/dev/null
  local ip; ip="$(echo "$pod" | grep -oE 'root@[0-9.]+')"
  echo -e "run${idx}\t${ip}\t$(date -u +%H:%M:%S)\t${rcwd}\t${log}" >> "$RUNS_TSV"
  echo "[fleet] run${idx} -> ${ip}  folder=$rcwd  (log $log)"
}

# ---- pod busy? (bracket trick avoids matching this ssh command itself) ----
pod_busy(){ rc "$1" "pgrep -f 'python -m red_[t]eam' >/dev/null && echo BUSY || echo FREE" 2>/dev/null | grep -q BUSY; }

# ---- assign: launch N runs starting at index START; first wave fills pods, remainder queued ----
declare -a QUEUE=()
launched=0; i="$START"
for pod in "${PODS[@]}"; do
  [ "$launched" -lt "$N" ] || break
  launch_run "$i" "$pod"; i=$((i+1)); launched=$((launched+1))
done
while [ "$launched" -lt "$N" ]; do QUEUE+=("$i"); i=$((i+1)); launched=$((launched+1)); done

if [ "${#QUEUE[@]}" -gt 0 ] && [ "$DRY" = 1 ]; then
  echo "[DRY] ${#QUEUE[@]} run(s) would QUEUE (more runs than pods): run(s) ${QUEUE[*]} — each launched on the next pod to free (poll ${POLL}s)"
elif [ "${#QUEUE[@]}" -gt 0 ]; then
  echo "[fleet] ${#QUEUE[@]} run(s) queued (more runs than pods); polling every ${POLL}s for a free pod"
  while [ "${#QUEUE[@]}" -gt 0 ]; do
    sleep "$POLL"
    for pod in "${PODS[@]}"; do
      [ "${#QUEUE[@]}" -gt 0 ] || break
      if ! pod_busy "$pod"; then
        idx="${QUEUE[0]}"; QUEUE=("${QUEUE[@]:1}")
        launch_run "$idx" "$pod"
      fi
    done
  done
fi

if [ "$DRY" = 1 ]; then echo "[DRY] plan only — nothing launched. Remove --dry-run to execute. plan: $RUNS_TSV";
else echo "[fleet] all $N runs launched. manifest: $RUNS_TSV"; fi
column -t "$RUNS_TSV"
