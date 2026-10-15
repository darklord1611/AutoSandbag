#!/usr/bin/env bash
# Is this pod fit for the phase you are about to run?
#
#   green_team/preflight_pod.sh 'ssh root@1.2.3.4 -p 16656 -i ~/.ssh/id_ed25519' --phase red
#   green_team/preflight_pod.sh 'ssh ...' --phase blue --endpoint http://localhost:8000/v1
#   green_team/preflight_pod.sh 'ssh ...' --phase both
#
# Run it BEFORE the expensive thing. Every check here is something that otherwise surfaces
# an hour in, disguised as a different problem:
#
#   red   a training run dies at `import trl` after the dataset build, or finishes and then
#         cannot push because the token is read-only -- which is what happened on
#         2026-07-20 (403 Forbidden creating a dataset under "annaupreti"), losing the push
#         but not the data.
#   blue  a tool set that starts, lists twelve tools, and fails every call. An agent
#         reports that as "no evidence of sandbagging", which reads like a finding.
#
# serve_pod.sh runs the blue checks itself before serving. This exists so the red phase
# gets the same treatment, and so either can be checked without serving anything.
#
# Exit code is 0 only if every FAIL-class check passed. WARNs are worth reading and do not
# block -- they mark things that degrade a round rather than prevent one.
set -uo pipefail   # NOT -e: one failed check must not hide the rest


# ─── EDIT ME ──────────────────────────────────────────────────────────────────────────
# Paste the pod's ssh command here, then just:  bash green_team/preflight_pod.sh
# Overridable from the environment (POD=... ) or as the first argument, in that order of
# precedence: argument > environment > this line.
#
# Ephemeral by nature -- a pod's host and port change every time one is created, so treat a
# stale value here as the normal state and expect to update it.
POD="${POD:-ssh root@<POD_IP> -p <PORT> -i ~/.ssh/id_ed25519}"
# ──────────────────────────────────────────────────────────────────────────────────────

# First non-flag argument wins, so the old positional form still works unchanged.
if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
  SSH_CMD="$1"; shift
else
  SSH_CMD="$POD"
fi
[ -n "$SSH_CMD" ] || { echo "no pod. Edit POD at the top of this file, export POD=..., or pass it: preflight_pod.sh --phase red|blue|both" >&2; exit 2; }


PHASE="both"
POD_PY="${POD_PY:-python}"
POD_REPO="${POD_REPO:-/workspace/AutoSandbag}"
ENDPOINT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --phase) PHASE="$2"; shift 2 ;;
    --pod-python) POD_PY="$2"; POD_PY_EXPLICIT=1; shift 2 ;;
    --pod-repo) POD_REPO="$2"; shift 2 ;;
    --endpoint) ENDPOINT="$2"; shift 2 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done
case "$PHASE" in red|blue|both) ;; *) echo "--phase must be red|blue|both" >&2; exit 2 ;; esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_ARGS="${SSH_CMD#ssh }"
HOST="$(printf '%s\n' $SSH_ARGS | grep '@' | head -1)"
[ -n "$HOST" ] || { echo "could not find user@host in: $SSH_CMD" >&2; exit 2; }
PORT="$(printf '%s\n' "$SSH_ARGS" | grep -oE '\-p [0-9]+' | awk '{print $2}')"
KEY="$(printf '%s\n' "$SSH_ARGS" | grep -oE '\-i [^ ]+' | awk '{print $2}')"
SSH=(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15)
[ -n "$PORT" ] && SSH+=(-p "$PORT")
[ -n "$KEY" ] && SSH+=(-i "$KEY")
on_pod() { "${SSH[@]}" "$HOST" "$@"; }

PASS=0; FAIL=0; WARN=0
ok()   { printf '  [ PASS ] %s\n' "$*"; PASS=$((PASS+1)); }
bad()  { printf '  [ FAIL ] %s\n' "$*"; FAIL=$((FAIL+1)); }
warn() { printf '  [ WARN ] %s\n' "$*"; WARN=$((WARN+1)); }
sec()  { printf '\n=== %s ===\n' "$*"; }

# Find the interpreter that actually has the stack.
#
# sshd builds a FRESH environment, so none of the image's ENV reaches a command run over
# ssh -- `python` resolves to /usr/bin/python, which on these images has nothing installed.
# Defaulting to it made this script report six missing packages on a pod where /opt/venv
# had all of them, and send the reader off to rebuild an image that was already correct.
# A preflight that misdiagnoses a healthy pod is worse than no preflight.
detect_pod_python() {
  local candidate
  for candidate in /opt/venv/bin/python "$POD_REPO/.venv/bin/python" \
                   /workspace/venv-serve/bin/python python3 python; do
    if on_pod "command -v '$candidate' >/dev/null 2>&1 || test -x '$candidate'" 2>/dev/null; then
      printf '%s' "$candidate"; return 0
    fi
  done
  printf 'python'
}

# ─── the pod itself ──────────────────────────────────────────────────────────
sec "pod"
on_pod 'echo ok' >/dev/null 2>&1 || { bad "cannot ssh to $HOST"; echo; echo "  $PASS passed, $FAIL failed"; exit 1; }
ok "ssh to $HOST"

if [ -z "${POD_PY_EXPLICIT:-}" ]; then
  POD_PY="$(detect_pod_python)"
fi
ver="$(on_pod "$POD_PY -V 2>&1" || echo unknown)"
ok "interpreter: $POD_PY ($ver)"

gpu="$(on_pod 'nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader 2>/dev/null' || true)"
[ -n "$gpu" ] && ok "gpu: $gpu" || bad "no GPU visible"

# A 27B needs the base weights (~52GB) plus adapters plus checkpoints. The volume quota was
# hit mid-run once. df on a MooseFS mount reports CLUSTER free space, not the quota, so
# this is a floor rather than a guarantee -- the console is the real number.
free="$(on_pod "df -h /workspace 2>/dev/null | tail -1 | awk '{print \$4}'" || true)"
if [ -n "$free" ]; then
  ok "/workspace free: $free  (MooseFS: df shows cluster space, check the console for quota)"
else
  bad "/workspace not mounted -- everything written this round dies with the container"
fi

# Caches on the volume, not the container disk. Otherwise the base model re-downloads
# (~52GB) on every restart, inside whatever step happens to need it first, where it looks
# like a hung process rather than a download.
hf_home="$(on_pod 'echo ${HF_HOME:-unset}' || true)"
case "$hf_home" in
  /workspace/*) ok "HF_HOME=$hf_home (on the volume)" ;;
  unset) warn "HF_HOME unset -- base weights will re-download on every pod restart" ;;
  *) warn "HF_HOME=$hf_home is not under /workspace -- re-downloads on restart" ;;
esac

# ─── red: can this pod train and push? ───────────────────────────────────────
if [ "$PHASE" = "red" ] || [ "$PHASE" = "both" ]; then
  sec "red phase"

  # Name every missing package in one pass rather than dying on the first import.
  if on_pod "$POD_PY - <<'PY'
import importlib.util, sys
need = {'torch': 'torch', 'transformers': 'transformers', 'trl': 'trl', 'peft': 'peft',
        'datasets': 'datasets', 'accelerate': 'accelerate', 'yaml': 'pyyaml'}
missing = [pkg for mod, pkg in need.items() if not importlib.util.find_spec(mod)]
print('  training deps: ' + ('all present' if not missing else 'MISSING ' + ' '.join(missing)))
sys.exit(1 if missing else 0)
PY"; then
    ok "training deps importable"
  else
    bad "training deps missing -- see above; rebuild docker/Dockerfile.train or docker/Dockerfile.all"
  fi

  # bitsandbytes only matters for qlora specs. Soft, because o6 deliberately runs bf16.
  on_pod "$POD_PY -c 'import bitsandbytes' 2>/dev/null" \
    && ok "bitsandbytes present (qlora specs runnable)" \
    || warn "no bitsandbytes -- qlora: true specs cannot train here"

  # THE ONE THAT ALREADY BIT US. A token that reads fine and cannot write turns a finished
  # training run into an un-pushable adapter: `hf auth whoami` succeeds, the push 403s.
  # Ask the API what this token may actually do.
  tok_out="$(on_pod 'export HF_TOKEN=$(cat /workspace/.hf_token 2>/dev/null || echo "${HF_TOKEN:-}"); \
    [ -z "$HF_TOKEN" ] && { echo NOTOKEN; exit 0; }; \
    curl -sf -m 15 -H "Authorization: Bearer $HF_TOKEN" https://huggingface.co/api/whoami-v2 \
      || echo BADTOKEN' 2>/dev/null || true)"
  case "$tok_out" in
    NOTOKEN)  bad "no HF token on the pod -- adapter push and private pulls both fail" ;;
    BADTOKEN|"") bad "HF token present but rejected by the Hub" ;;
    *)
      # python3 (local), not $POD_PY -- that is a path on the POD, and the JSON is already
      # here. Using it would try to exec /opt/venv/bin/python on the laptop.
      name="$(printf '%s' "$tok_out" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("name","?"))' 2>/dev/null || echo '?')"
      if printf '%s' "$tok_out" | grep -q '"write"'; then
        ok "HF token: $name, write scope"
      else
        bad "HF token: $name, READ-ONLY -- training will finish and then fail to push (403)"
      fi
      ;;
  esac

  on_pod 'test -n "${WANDB_API_KEY:-}" || test -f /workspace/.wandb_key' 2>/dev/null \
    && ok "wandb key present" \
    || warn "no wandb key -- training runs unlogged (export WANDB_MODE=disabled to silence)"
fi

# ─── blue: can this pod audit? ───────────────────────────────────────────────
if [ "$PHASE" = "blue" ] || [ "$PHASE" = "both" ]; then
  sec "blue phase"

  if on_pod "$POD_PY - <<'PY'
import importlib.util, sys   # .util explicitly: plain 'import importlib' does not bind it
need = {'mcp': 'mcp', 'zstandard': 'zstandard', 'sklearn': 'scikit-learn',
        'openai': 'openai', 'numpy': 'numpy', 'httpx': 'httpx',
        'pydantic': 'pydantic', 'datasets': 'datasets', 'safetensors': 'safetensors'}
missing = [pkg for mod, pkg in need.items() if not importlib.util.find_spec(mod)]
print('  audit deps: ' + ('all present' if not missing else 'MISSING ' + ' '.join(missing)))
sys.exit(1 if missing else 0)
PY"; then
    ok "audit deps importable"
  else
    bad "audit deps missing -- the tool server dies before it binds; this pod needs docker/Dockerfile.all"
  fi

  # The endpoint contract, if something is already serving. This is strictly more than an
  # import check: it asks whether the assumptions the TOOLS make actually hold -- reasoning
  # reachable, truncation reported as finish_reason=length, prefill accepted. A serve that
  # fails these answers every request and silently breaks specific techniques.
  if [ -n "$ENDPOINT" ]; then
    if on_pod "test -f $POD_REPO/green_team/check_endpoint.py"; then
      echo "  --- endpoint contract ($ENDPOINT)"
      if on_pod "cd $POD_REPO && $POD_PY green_team/check_endpoint.py '$ENDPOINT' 2>&1 | sed 's/^/  /'"; then
        ok "endpoint contract"
      else
        bad "endpoint contract -- some tools would misbehave quietly, see above"
      fi
    else
      warn "green_team/check_endpoint.py not on the pod -- sync the repo first"
    fi
  else
    warn "no --endpoint given: skipped the contract checks (reasoning, truncation, prefill)"
  fi
fi

# ─── summary ─────────────────────────────────────────────────────────────────
sec "summary"
echo "  $PASS passed, $FAIL failed, $WARN warnings"
if [ "$FAIL" -ne 0 ]; then
  echo
  echo "  do NOT start the $PHASE phase -- the failures above cost a full run to discover" >&2
  exit 1
fi
echo "  pod is fit for: $PHASE"
