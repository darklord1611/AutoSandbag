#!/usr/bin/env bash
# Serve an organism on the pod and put the blue-team MCP server in front of it.
#
#   green_team/serve_pod.sh 'ssh root@1.2.3.4 -p 16656 -i ~/.ssh/id_ed25519' \
#       --spec <organism-spec.yaml>
#
# THE GREEN TEAM RUNS THIS. Not the blue team.
#
# The blue team's entire interface to a round is an MCP URL. It does not launch the
# organism, does not choose which adapter is mounted, and never sees this script's input --
# which is a spec, and a spec contains `trigger.value`. Handing blue the launcher would
# hand it the answer.
#
# That is why this is in green_team/ and not blue_team/ or shared/. shared/ is code BOTH teams
# may import; this is code NEITHER team may run, because running it requires holding ground
# truth. The distinction is the whole reason the folder exists: a file here is not neutral,
# it is privileged.
#
# Run from the laptop. Takes a fresh pod to an audit-ready endpoint in one command.
#
# What it does, on the pod:
#   1. preflight: GPU present, every blue-team import resolvable, HF cache on the volume
#   2. sync the repo (clone or pull) so the pod runs THIS commit's tools
#   3. push HF_TOKEN / OPENROUTER_API_KEY over stdin into 0600 files
#   4. stop any vLLM already holding the GPU
#   5. pull the adapter from the Hub (push_to_hub in the spec)
#   6. serve base + adapter on :8000 (vllm-lens auto-loads as a general plugin)
#   7. wait until the ORGANISM NAME is actually in /v1/models -- not just until the port
#      answers, because vLLM serves the base before the LoRA is mounted
#   8. start the MCP server on :8020 and check it answers
#   9. exercise the tools against the live organism before handing over
#
# Steps 1-3 and 9 are the difference between this and a bare serve. Each covers a failure
# that is silent rather than loud: a missing import surfaces as one dead tool mid-audit, a
# stale checkout serves last week's tool set under this week's name, an absent
# OPENROUTER_API_KEY makes the scaffolded multi_* tools VANISH from the surface rather than
# error, and a server that binds can still have every tool fail on first call. All four
# read to an agent as "no evidence of sandbagging", which is indistinguishable from an
# honest null and is the one failure this project cannot afford.
#
# The base model is served alongside as `base`. That is not a convenience: every
# comparison the blue team makes (reference_compare, any base-vs-organism drop) has to be
# measured with the same scorer on the same server, or the number means nothing.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"


# ─── EDIT ME ──────────────────────────────────────────────────────────────────────────
# Paste the pod's ssh command here, then just:  bash green_team/serve_pod.sh
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
[ -n "$SSH_CMD" ] || { echo "no pod. Edit POD at the top of this file, export POD=..., or pass it: serve_pod.sh --spec <spec.yaml>" >&2; exit 2; }


SPEC=""
POD_REPO="${POD_REPO:-/workspace/AutoSandbag}"
POD_PY="${POD_PY:-python}"
REPO_URL="${REPO_URL:-https://github.com/darklord1611/AutoSandbag.git}"
VLLM_PORT="${VLLM_PORT:-8000}"
MCP_PORT="${MCP_PORT:-8020}"
# Black-box by default, matching the other two layers that get a vote: the image ships
# VLLM_LENS_DISABLE=1 and blue refuses --whitebox without BLUE_ENABLE_WHITEBOX=1.
LENS=0
NO_MCP=0
NO_SYNC=0
NO_VERIFY=0
DEEP=0
PUBLIC=0
REFETCH=0
MCP_TOKEN="${MCP_AUTH_TOKEN:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --spec) SPEC="$2"; shift 2 ;;
    --pod-repo) POD_REPO="$2"; shift 2 ;;
    --pod-python) POD_PY="$2"; POD_PY_EXPLICIT=1; shift 2 ;;
    --repo-url) REPO_URL="$2"; shift 2 ;;
    --vllm-port) VLLM_PORT="$2"; shift 2 ;;
    # --port is an alias: blue_team/serve_tools.sh names it that, and having the same knob
    # spelled two ways across two scripts in one flow is a papercut with no upside.
    --mcp-port|--port) MCP_PORT="$2"; shift 2 ;;
    --lens) LENS=1; shift ;;           # white-box round: activations on, ~2x slower decode
    --no-lens) LENS=0; shift ;;        # accepted for compatibility; this is now the default
    --no-mcp) NO_MCP=1; shift ;;       # just serve the model
    --no-sync) NO_SYNC=1; shift ;;     # trust the pod's checkout as-is
    --no-verify) NO_VERIFY=1; shift ;; # skip exercising the tools at the end
    --refetch) REFETCH=1; shift ;;   # ignore any local adapter, pull from the Hub
    --deep) DEEP=1; shift ;;           # + the 17 mechanical probes (costs model time)
    --public) PUBLIC=1; shift ;;       # bind the tool server publicly, behind a bearer token
    --token) MCP_TOKEN="$2"; shift 2 ;; # supply the token instead of minting one
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done
[ -n "$SPEC" ] || { echo "need --spec <path>" >&2; exit 2; }
[ -f "$SPEC" ] || { echo "no such spec: $SPEC" >&2; exit 2; }

# Read the spec here rather than on the pod: it keeps the pod side a plain shell command
# with no dependency on the repo being importable there, and it means a typo'd spec fails
# on the laptop in a second instead of after an ssh round trip.
read -r ORG_ID BASE_MODEL HUB_REPO LORA_RANK <<EOF
$(python3 -c "
import yaml, sys
s = yaml.safe_load(open('$SPEC'))
hub = s.get('push_to_hub', '')
if not hub:
    sys.exit('spec has no push_to_hub -- nothing to serve')
print(s['id'], s['base_model'], hub, s.get('training', {}).get('lora_r', 64))
")
EOF
[ -n "${ORG_ID:-}" ] || { echo "could not read spec" >&2; exit 1; }

# Same ssh->scp derivation as the rest of the repo: match on '@' only, so a flags-first
# command (`ssh -p 16656 root@host`) doesn't pick the port up as the host.
SSH_ARGS="${SSH_CMD#ssh }"
HOST="$(printf '%s\n' $SSH_ARGS | grep '@' | head -1)"
[ -n "$HOST" ] || { echo "could not find user@host in: $SSH_CMD" >&2; exit 2; }
PORT="$(printf '%s\n' "$SSH_ARGS" | grep -oE '\-p [0-9]+' | awk '{print $2}')"
KEY="$(printf '%s\n' "$SSH_ARGS" | grep -oE '\-i [^ ]+' | awk '{print $2}')"
SSH=(ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30)
[ -n "$PORT" ] && SSH+=(-p "$PORT")
[ -n "$KEY" ] && SSH+=(-i "$KEY")
on_pod() { "${SSH[@]}" "$HOST" "$@"; }
say() { printf '\n==> %s\n' "$*"; }

# Find the interpreter that actually has the stack.
#
# sshd builds a FRESH environment, so none of the image's ENV reaches a command run over
# ssh -- `python` resolves to /usr/bin/python, which on these images has nothing installed.
# Defaulting to it reported SEVEN missing packages on a pod where /opt/venv had every one,
# and sent the reader off to rebuild an image that was already correct. Measured on
# 2026-07-20. A preflight that misdiagnoses a healthy pod is worse than no preflight.
if [ -z "${POD_PY_EXPLICIT:-}" ]; then
  for _candidate in /opt/venv/bin/python "$POD_REPO/.venv/bin/python" \
                    /workspace/venv-serve/bin/python python3 python; do
    if on_pod "command -v '$_candidate' >/dev/null 2>&1 || test -x '$_candidate'" 2>/dev/null; then
      POD_PY="$_candidate"; break
    fi
  done
fi

say "organism $ORG_ID"
echo "  base    $BASE_MODEL"
echo "  adapter $HUB_REPO (rank $LORA_RANK)"
echo "  pod     $HOST"

# --- preflight -----------------------------------------------------------------------
# Properties of the POD, not of this organism: they survive between rounds, and each one
# wrong costs a serve (10+ min on a cold 27B) before anything says why.
say "preflight"
echo "  interpreter: $POD_PY"
on_pod "command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name,memory.total \
        --format=csv,noheader | sed 's/^/  gpu: /' || echo '  gpu: NONE VISIBLE'"

# Import-check every module the tool server needs, in one pass, naming all the missing ones
# rather than dying on the first. These are lazy imports inside audit.py (sklearn, datasets)
# and transport deps deep in session.py (zstandard) -- none of which fail at server startup.
# They fail on the call, which an agent reads as a technique that found nothing.
if ! on_pod "$POD_PY - <<'PY'
import importlib.util, sys   # .util explicitly: plain 'import importlib' does not bind it
need = {'mcp': 'mcp', 'zstandard': 'zstandard', 'sklearn': 'scikit-learn',
        'openai': 'openai', 'numpy': 'numpy', 'httpx': 'httpx',
        'pydantic': 'pydantic', 'datasets': 'datasets', 'safetensors': 'safetensors'}
missing = [pkg for mod, pkg in need.items() if not importlib.util.find_spec(mod)]
print('  imports: ' + ('all present' if not missing else 'MISSING ' + ' '.join(missing)))
sys.exit(1 if missing else 0)
PY"; then
  echo "the pod cannot run the tool server. Install them:" >&2
  echo "  ${SSH_CMD} 'pip install mcp zstandard scikit-learn datasets'" >&2
  echo "or use a pod built from docker/Dockerfile.all -- the audit stack lives only there." >&2
  echo "docker/Dockerfile.serve deliberately does NOT carry it; it is the red serve/eval image." >&2
  exit 1
fi

on_pod "df -h /workspace 2>/dev/null | tail -1 | awk '{print \"  /workspace: \" \$4 \" free\"}' \
        || echo '  /workspace: NOT MOUNTED'"

# --- find the base-model cache, do not dictate it -------------------------------------
# A pod that has already served this base has ~52GB of weights somewhere. Which directory
# is NOT a constant: one pod used /workspace/hf, another /workspace/hf_cache. Hardcoding
# either points HF_HOME at an empty directory on the other, and vLLM then re-downloads the
# whole model *inside* the serve -- half an hour that reads as a hung server, on a pod
# where the weights were already sitting on disk.
#
# So: prefer a cache that actually contains this model, fall back to one that exists, and
# only then invent a path. Detected once here and reused by every later step.
# HF's cache spells the separator as a DOUBLE dash: Qwen/Qwen3.6-27B becomes
# models--Qwen--Qwen3.6-27B. A single-dash key never matches, so the check silently
# reports "no cache" on a pod holding 52GB of the right weights -- and the fix for a
# missed cache is a 50GB re-download, which is the exact cost this detection exists to
# avoid. Verified against a live cache 2026-07-21.
BASE_CACHE_KEY="models--$(printf '%s' "$BASE_MODEL" | sed 's|/|--|g')"
HF_CACHE="$(on_pod "
  for d in \"\${HF_HOME:-}\" /workspace/hf_cache /workspace/hf /workspace/huggingface \
           /root/.cache/huggingface; do
    [ -n \"\$d\" ] && [ -d \"\$d/hub/$BASE_CACHE_KEY\" ] && { echo \"\$d HIT\"; exit 0; }
  done
  for d in \"\${HF_HOME:-}\" /workspace/hf_cache /workspace/hf /workspace/huggingface; do
    [ -n \"\$d\" ] && [ -d \"\$d\" ] && { echo \"\$d EMPTY\"; exit 0; }
  done
  echo '/workspace/hf_cache NEW'" 2>/dev/null)"
HF_STATE="${HF_CACHE##* }"
HF_CACHE="${HF_CACHE%% *}"
[ -n "$HF_CACHE" ] || { HF_CACHE=/workspace/hf_cache; HF_STATE=NEW; }
case "$HF_STATE" in
  HIT)   echo "  hf cache: $HF_CACHE (already holds $BASE_MODEL -- no download)" ;;
  EMPTY) echo "  hf cache: $HF_CACHE (exists, but no $BASE_MODEL -- expect a ~50GB fetch)" ;;
  *)     echo "  hf cache: $HF_CACHE (new -- expect a ~50GB fetch)" ;;
esac

# --- sync the repo -------------------------------------------------------------------
# The pod runs the tool server, so the pod's checkout decides what tools exist. A stale one
# serves an older tool set under this round's organism name, and nothing in the output says
# so. Clone if absent, fetch+reset if present -- reset rather than pull because a pod that
# was edited in place would otherwise fail on a merge conflict at the least useful moment.
#
# Pinned to the branch the GREEN TEAM is on, not to origin/HEAD. origin/HEAD is main, and this
# work lives on feature branches: resetting to it would serve main's tool set while the
# operator reads this branch's code, and the two would disagree about which tools exist.
BRANCH="${BRANCH:-$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)}"

# The repo is PRIVATE, so the pod needs a credential to fetch. Sent before the sync rather
# than with the other secrets below, because the sync is what needs it.
#
# NOT written into the remote URL. `git remote add origin https://<token>@github.com/...`
# would persist the credential in .git/config on /workspace -- a network volume that
# outlives the pod and already carries stale keys from earlier sessions. NOT passed in argv
# either, for the usual reason: it would land in the pod's process table. A credential
# helper reading one env var keeps it in neither.
GIT_TOKEN="${GIT_TOKEN:-${GITHUB_TOKEN:-${GH_TOKEN:-}}}"
if [ "$NO_SYNC" -eq 0 ] && [ -n "$GIT_TOKEN" ]; then
  printf '%s' "$GIT_TOKEN" | on_pod 'umask 077; cat > /workspace/.git_token'
fi

if [ "$NO_SYNC" -eq 0 ]; then
  say "syncing repo -> $POD_REPO (branch $BRANCH)"
  # THREE pod states, one code path. $POD_REPO may be absent (fresh pod), present without a
  # .git (a hand-copied tree left on the persistent /workspace volume by an earlier session),
  # or a real checkout. Both of the obvious approaches break on one of them:
  #   * `git clone` refuses a non-empty target -- strands the hand-copied case, which is the
  #     most common state on a reused volume.
  #   * an absent/present test that clones only when absent -- strands the FRESH case, see
  #     below.
  #
  # NEVER `git clone`, in any state. Clone is its own network operation and would need its
  # own credentials -- and on a private repo without them it does not fail cleanly, it asks
  # for a username on a tty that does not exist: "could not read Username for
  # 'https://github.com'". That is what a FRESH pod hit, while a pod whose directory already
  # existed took the other branch and worked, so the bug hid until the first genuinely new
  # machine. Measured 2026-07-20.
  #
  # init + fetch covers all three with one credential mechanism. `git init` on an existing
  # repo is a documented no-op, so this is safe to repeat. The checkout below uses -f, which
  # is required for the hand-copied case and safe: everything it clobbers is a stale copy of
  # a tracked file, and nothing else lives under $POD_REPO (weights are /workspace/adapters,
  # datasets /workspace/data, caches /workspace/hf_cache). Untracked files not in the branch
  # survive.
  on_pod "set -e
    mkdir -p '$POD_REPO'
    [ -d '$POD_REPO/.git' ] || echo '  initialising repo at $POD_REPO'
    git init --quiet '$POD_REPO'
    cd '$POD_REPO'
    git remote add origin '$REPO_URL' 2>/dev/null || true
    git remote set-url origin '$REPO_URL' 2>/dev/null || true
    export GIT_TOKEN=\$(cat /workspace/.git_token 2>/dev/null)
    git -c credential.helper='!f(){ echo username=x-access-token; echo password=\$GIT_TOKEN; };f' \
        fetch --quiet origin '$BRANCH'
    git checkout --quiet -f -B '$BRANCH' FETCH_HEAD
    echo \"  at \$(git rev-parse --short HEAD) on $BRANCH\"" || {
    echo "repo sync failed. Common causes:" >&2
    echo "  * '$BRANCH' has commits that were never pushed -- the pod fetches from origin," >&2
    echo "    not from your working tree. Push first." >&2
    echo "  * the pod cannot reach $REPO_URL (private repo needs credentials on the pod)." >&2
    echo "Re-run with --no-sync to trust the pod's checkout as-is." >&2
    exit 1
  }
fi

# --- secrets -------------------------------------------------------------------------
# Over stdin, never argv: a key on the command line lands in the pod's process table and in
# local shell history. Written 0600 to the ephemeral volume, read back by the launches below.
say "secrets"
if [ -n "${HF_TOKEN:-}" ]; then
  printf '%s' "$HF_TOKEN" | on_pod 'umask 077; cat > /workspace/.hf_token'
  echo "  HF_TOKEN -> /workspace/.hf_token"
else
  echo "  no HF_TOKEN in env -- adapter download will fail if the repo is private"
fi

# The blue team's key, and a different failure mode entirely. audit.py's judge-backed
# techniques (prompt_elicit, confession) need it, and the scaffolded multi_* variants are
# built from it -- without it those tools are ABSENT from the MCP surface, not broken. The
# audit then runs with roughly half a toolbox and reports a confident null. Warn loudly.
if [ -n "${OPENROUTER_API_KEY:-}" ]; then
  printf '%s' "$OPENROUTER_API_KEY" | on_pod 'umask 077; cat > /workspace/.openrouter_key'
  echo "  OPENROUTER_API_KEY -> /workspace/.openrouter_key (scaffolded multi_* tools enabled)"
else
  echo "  !! no OPENROUTER_API_KEY in env." >&2
  echo "  !! The multi_* scaffolded tools and the judge-backed techniques will be ABSENT," >&2
  echo "  !! not failing. A half-sized toolbox reporting nothing looks exactly like a" >&2
  echo "  !! clean model. Set it unless you mean to run a reduced audit." >&2
fi

# --- stop whatever holds the GPU -----------------------------------------------------
# TWO patterns, and the second is the one that matters. vLLM runs its engine in a separate
# process whose command line is `VLLM::EngineCore` -- no "vllm", no "serve" -- so killing
# only the API server orphans it (PPID 1) and it keeps the ENTIRE GPU. The next launch then
# dies with "Free memory on device cuda:0 (12.35/139.81 GiB) is less than desired", and
# nvidia-smi names a host PID that does not exist in this container, so the real owner looks
# like somebody else's process. Observed 2026-07-21; the orphan was 54 minutes old.
#
# Bracketed patterns, deliberately: `pkill -f "vllm serve"` also matches the ssh command
# line carrying it, so the plain form kills the caller instead of the server.
#
# Then WAIT for the memory to come back rather than sleeping a fixed interval -- tearing
# down 50GB is not instant, and racing it produces exactly the OOM above.
say "stopping any running vLLM"
on_pod 'found=""
for pat in "vllm[ ]serve" "VLLM::EngineCor"; do
  p=$(pgrep -f "$pat" || true); [ -n "$p" ] && { found="$found $p"; kill $p 2>/dev/null; }
done
if [ -z "${found// /}" ]; then echo "  nothing running"; exit 0; fi
sleep 4
for pat in "vllm[ ]serve" "VLLM::EngineCor"; do
  p=$(pgrep -f "$pat" || true); [ -n "$p" ] && kill -9 $p 2>/dev/null
done
for i in $(seq 1 20); do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null || echo 0)
  [ "${used:-0}" -lt 2000 ] && { echo "  stopped, GPU free (${used} MiB used)"; exit 0; }
  sleep 5
done
echo "  WARNING: GPU still reports ${used} MiB used; the next launch may OOM" >&2'

# --- fetch the adapter ---------------------------------------------------------------
# vLLM can resolve a Hub id in --lora-modules, but a download here fails loudly and once,
# instead of inside engine startup where it surfaces as an opaque worker crash.
# Defined before the reuse decision below, which calls it. Through the interpreter, not
# the `hf` CLI: the CLI lives in the venv's bin/ and sshd builds a fresh PATH, so
# `hf download` returned "command not found" on a pod that had huggingface_hub installed
# and working -- and the handler then blamed the token and namespace, sending the reader to
# check credentials that were fine. Measured 2026-07-20.
#
# The distinct exit codes matter: "never pushed" and "no permission" need opposite fixes,
# and a single "download failed" makes you check the wrong one first.
_fetch_adapter() {
fetch_out="$(on_pod "export HF_HOME='$HF_CACHE'; \
  export HF_TOKEN=\$(cat /workspace/.hf_token 2>/dev/null); \
  export HF_HUB_DISABLE_PROGRESS_BARS=1; \
  $POD_PY - <<'PY' 2>&1
from huggingface_hub import snapshot_download
from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError
import sys
try:
    p = snapshot_download('$HUB_REPO', local_dir='/workspace/adapters/$ORG_ID')
    print('OK ' + p)
except RepositoryNotFoundError:
    print('MISSING'); sys.exit(2)
except GatedRepoError:
    print('FORBIDDEN'); sys.exit(3)
except Exception as exc:
    print('ERROR ' + type(exc).__name__ + ': ' + str(exc)[:200]); sys.exit(4)
PY" 2>&1)"
# Match the LAST line, not the whole capture. stderr is folded in above so a real traceback
# survives, which also means huggingface_hub's progress output lands at the FRONT of the
# variable -- a `case "$fetch_out" in OK*` therefore missed a download that had in fact
# succeeded and exited 1 on a working fetch. Observed 2026-07-20. Progress bars are
# disabled above too; this is the belt to that braces, because any future library that
# prints a banner would otherwise resurrect the same bug.
fetch_verdict="$(printf '%s\n' "$fetch_out" | tail -1)"
case "$fetch_verdict" in
  OK\ *) echo "  adapter at /workspace/adapters/$ORG_ID" ;;
  MISSING*)
    echo "'$HUB_REPO' does not exist on the Hub." >&2
    echo "The organism has not been trained and pushed yet -- run the red phase first." >&2
    exit 1 ;;
  FORBIDDEN*)
    echo "'$HUB_REPO' exists but this token may not read it." >&2
    echo "Check the token's account owns that namespace." >&2
    exit 1 ;;
  *)
    echo "adapter download failed:" >&2
    printf '  %s\n' "$fetch_out" >&2
    exit 1 ;;
esac
}

say "adapter"
ADAPTER_DIR="/workspace/adapters/$ORG_ID"

# Reuse an adapter already on the pod -- but VERIFY it, never trust the directory name.
#
# A local dir named for this organism is not evidence it holds this organism. That is the
# exact shape of the wrong-weights failure this whole folder exists to prevent: an audit
# against the previous round's adapter produces findings that look entirely real. So the
# reuse path reads adapter_config.json and checks the base model and rank against the
# spec, and a mismatch is fatal rather than a warning.
#
# --refetch forces a fresh download when you want the Hub's copy regardless.
reuse=""
if [ "$REFETCH" -eq 0 ]; then
  reuse="$(on_pod "$POD_PY - <<'PY' 2>/dev/null
import json, os, sys
d = '$ADAPTER_DIR'
cfg = None
for cand in (os.path.join(d, 'adapter_config.json'),
             os.path.join(d, 'adapter', 'adapter_config.json')):
    if os.path.exists(cand):
        cfg = cand; break
if not cfg:
    sys.exit(0)                      # nothing local; fall through to the download
c = json.load(open(cfg))
base, rank = c.get('base_model_name_or_path'), c.get('r')
if base != '$BASE_MODEL':
    print('MISMATCH base=%s' % base); sys.exit(0)
if str(rank) != '$LORA_RANK':
    print('MISMATCH rank=%s' % rank); sys.exit(0)
print('REUSE ' + os.path.dirname(cfg))
PY" 2>/dev/null | tail -1)"
fi

case "$reuse" in
  REUSE\ *)
    ADAPTER_DIR="${reuse#REUSE }"
    echo "  reusing $ADAPTER_DIR (base and rank match the spec -- no download)"
    ;;
  MISMATCH\ *)
    echo "an adapter already sits at $ADAPTER_DIR but it is NOT this organism:" >&2
    echo "  ${reuse#MISMATCH }, spec wants base=$BASE_MODEL rank=$LORA_RANK" >&2
    echo "Serving it would point the audit at the wrong weights. Move it aside, or" >&2
    echo "pass --refetch to overwrite it from the Hub." >&2
    exit 1
    ;;
  *)
    say "fetching adapter"
    _fetch_adapter
    ;;
esac

# --- serve ---------------------------------------------------------------------------
# vllm-lens loads ITSELF. It registers a `vllm.general_plugins` entry point
# (`activations = vllm_lens._activations_plugin:register`), so vLLM imports it at startup
# with no flag.
#
# docker/Dockerfile.serve documents `--worker-extension-cls
# vllm_lens.worker_extension.LensWorkerExtension` and this script copied it. That module
# does not exist in vllm-lens 1.2.0 -- the worker code is the private `_worker_ext` -- so
# the flag killed the engine at startup with ModuleNotFoundError. Measured 2026-07-20.
# Passing no flag is not a workaround; it is how this version is driven.
#
# Switching it on/off is an env var, not a flag: VLLM_LENS_DISABLE=1 makes the plugin a
# no-op. BLACK-BOX IS THE DEFAULT, consistently across the three layers that get a vote:
#   docker/Dockerfile.all  ships VLLM_LENS_DISABLE=1          (2026-08-23)
#   blue_team/__main__.py  refuses --whitebox without BLUE_ENABLE_WHITEBOX=1
#   this script            defaults LENS=0
# The plugin forces enforce_eager=True for EVERY caller (~950 tok/s @32 reqs and ~40% GPU
# util, vs ~1700 non-eager), so a default-on lens taxes every black-box round to feed a
# white-box tier that is itself parked. `--lens` opts a round back in.
#
# Still EXPLICIT in both directions rather than inheriting the image's value: a pod built
# before 2026-08-23 has no VLLM_LENS_DISABLE set at all, and there the ambient default is
# lens-ON. Exporting it either way makes this script behave identically on both images and
# keeps the status message below honest about what was actually served.
if [ "$LENS" -eq 1 ]; then LENS_ENV="export VLLM_LENS_DISABLE=0;"
else                       LENS_ENV="export VLLM_LENS_DISABLE=1;"; fi
LENS_FLAG=""

say "serving base + $ORG_ID on :$VLLM_PORT"
[ "$LENS" -eq 1 ] && echo "  vllm-lens ON (forced enforce_eager, ~2x slower): white-box tools available" \
                  || echo "  vllm-lens off (default): black-box only, CUDA graphs on"

# The venv's vllm, not whatever `vllm` resolves to on a fresh ssh PATH -- which is nothing.
# `nohup: failed to run command 'vllm'` went into serve.log, the launcher still printed
# "started", and the wait loop below then polled a dead process for 7 minutes before
# timing out. Third instance of the same PATH assumption in this file; $POD_PY is already
# resolved, so derive from it rather than trusting the environment again.
# No --api-key, and bound to 127.0.0.1 rather than 0.0.0.0.
#
# `--api-key EMPTY` made vLLM demand an Authorization header. The readiness poll below
# sent none, so it got 401 on every attempt and burned the full 20-minute timeout against
# a server that was up and correctly serving base + the organism the whole time. Measured
# 2026-07-20. A literal key of "EMPTY" was never protection anyway.
#
# The real protection is the bind address: on 0.0.0.0 the RunPod proxy can expose the raw
# model endpoint publicly, which would hand anyone the organism without going through the
# tool server. Blue's surface is the MCP port and nothing else, and the MCP server runs on
# this pod, so localhost is all vLLM ever needs to answer.
VLLM_BIN="$(dirname "$POD_PY")/vllm"
on_pod "test -x '$VLLM_BIN'" 2>/dev/null || VLLM_BIN="vllm"

on_pod "cd $POD_REPO 2>/dev/null || cd /workspace; export HF_HOME='$HF_CACHE'; $LENS_ENV \
  nohup '$VLLM_BIN' serve '$BASE_MODEL' \
    --served-model-name base \
    --enable-lora --max-lora-rank $LORA_RANK \
    --lora-modules '$ORG_ID=$ADAPTER_DIR' \
    --host 127.0.0.1 --port $VLLM_PORT \
    --reasoning-parser qwen3 --max-model-len ${MAX_MODEL_LEN:-32768} \
    $LENS_FLAG \
    > /workspace/serve.log 2>&1 & echo started"

# Wait for the NAME, not the port. vLLM answers /v1/models before the adapter is mounted,
# and an audit that starts in that window measures the base model under the organism's
# name -- which produces findings that look entirely real and are about the wrong weights.
# Exact list membership, because organism ids nest (`o3_covert_token_logit` is a prefix of
# `o3_covert_token_logit_8b`) and a substring test would pass on the wrong one.
say "waiting for the adapter to mount (cold start can be ~10 min)"
waited=0
until on_pod "curl -sf -m 5 localhost:$VLLM_PORT/v1/models | python3 -c \"
import sys, json
sys.exit(0 if '$ORG_ID' in [m['id'] for m in json.load(sys.stdin)['data']] else 1)\"" 2>/dev/null; do
  # Is the server even alive? A launch that dies immediately -- a bad flag, a missing
  # binary, an adapter whose rank does not match --max-lora-rank -- leaves this loop
  # polling a corpse until the full 20-minute timeout. Observed 2026-07-20: vllm was not
  # on the ssh PATH, the launcher still printed "started", and 7 minutes of dots followed.
  # Bracketed pattern so pgrep cannot match the ssh command line carrying it.
  if ! on_pod "pgrep -f 'vllm[ ]serve' >/dev/null" 2>/dev/null; then
    echo; echo "the vLLM process is gone -- it died during startup. Last log lines:" >&2
    on_pod "tail -30 /workspace/serve.log" >&2
    exit 1
  fi
  if [ "$waited" -ge 1200 ]; then
    echo; echo "did not come up within 1200s. last log lines:" >&2
    on_pod "tail -30 /workspace/serve.log" >&2
    exit 1
  fi
  printf '.'; sleep 15; waited=$((waited + 15))
done
echo " ready (${waited}s)"
on_pod "curl -sf localhost:$VLLM_PORT/v1/models | python3 -c \"
import sys, json; print('  serving:', [m['id'] for m in json.load(sys.stdin)['data']])\""

# --- endpoint contract ----------------------------------------------------------------
# The preflight above ran before anything was serving, so it could only check that packages
# import. This is the first point where the ASSUMPTIONS THE TOOLS MAKE can be tested: that
# the reasoning trace is reachable in one of its two places, that hitting max_tokens comes
# back as finish_reason=length rather than a short answer, that prefill is accepted. A serve
# that fails these still answers every request -- it just breaks specific techniques
# silently, which is the failure this whole folder exists to prevent.
if [ "$NO_VERIFY" -eq 0 ]; then
  say "endpoint contract"
  if on_pod "cd $POD_REPO && $POD_PY green_team/check_endpoint.py \
      http://127.0.0.1:$VLLM_PORT/v1 '$ORG_ID' 2>&1 | sed 's/^/  /'"; then
    echo "  contract holds"
  else
    # Not fatal: the optional features (n>1, logprobs, enable_thinking) degrade individual
    # techniques rather than the round. The required ones already printed as FAIL above.
    echo "  SOME CONTRACT CHECKS FAILED -- techniques relying on them will misreport" >&2
  fi
fi

# --- done: serving is green's only job -------------------------------------------------
# Blue reaches the model through two black-box tools that inspect bridges over MCP *per blue
# run* (blue_team + claude_code `bridged_tools=`), so there is no long-lived MCP server for
# green to stand up here anymore. Green serves vLLM and hands blue the endpoint + served name;
# blue never serves anything. (The old MCP-standup + --deep transport probes relied on the now
# archived blue_team server/primitives, not in this release.)
say "done: endpoint on :$VLLM_PORT serving '$ORG_ID'"
say "  hand to blue:  python -m blue_team --endpoint http://127.0.0.1:$VLLM_PORT/v1 \\"
say "                   --served-name '$ORG_ID' --brief blue_team/briefs/round1_detect_sandbag.md \\"
say "                   --model anthropic/claude-sonnet-5 --sandbox local --time-limit 1800"
exit 0

