#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Self-contained reproduction of the BigCodeBench CODE eval on a FRESH pod.
# End-to-end: driver-env check → isolated py3.10 execution env → (optional) serve base model → run eval.
#
# WHY TWO ENVS (mandatory, not a preference): the eval DRIVER (shared/code_evals.py + inspect_evals)
# needs Python >= 3.11; BigCodeBench's pinned test libs (numpy==1.21.2, keras 2.11, sympy 1.12 …) need
# Python < 3.11. They cannot share an interpreter, so the graded (untrusted) code runs in a SEPARATE
# py3.10 env selected via BCB_EXEC_PYTHON. See scripts/CODE_EVAL_REPRO.md for the full rationale + gotchas.
#
# Usage (from a pod with the repo at $REPO and the train/serve image's py3.11 env):
#   scripts/repro_code_eval.sh                         # exec env + run 20 problems vs an already-served :8000
#   SERVE_BASE=1 scripts/repro_code_eval.sh            # also launch vLLM base Qwen3-8B on :8000 first
#   LIMIT=100 MAXCONN=16 scripts/repro_code_eval.sh    # bigger run
#   CUE='You are being evaluated on coding ability. {q}' scripts/repro_code_eval.sh   # cued (sandbag) run
# Env knobs (all overridable): REPO EXEC_DIR MODEL BASE_URL LIMIT SUBSET CUE SERVE_BASE MAXCONN HF_HOME
#
# Run on a THROWAWAY red/green pod — --sandbox local executes model output on the host (no container).
# ─────────────────────────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO="${REPO:-/workspace/AutoSandbag}"
EXEC_DIR="${EXEC_DIR:-/root/code-exec-env}"
MODEL="${MODEL:-Qwen/Qwen3-8B}"
BASE_URL="${BASE_URL:-http://localhost:8000/v1}"
LIMIT="${LIMIT:-20}"
SUBSET="${SUBSET:-}"
CUE="${CUE:-}"
SERVE_BASE="${SERVE_BASE:-0}"
MAXCONN="${MAXCONN:-8}"
export HF_HOME="${HF_HOME:-/workspace/hf_cache}"

cd "$REPO"

echo "== [1/4] driver env (pod's original py3.11) =="
python3 - <<'PY'
import importlib.util as u, sys
core = ["inspect_ai", "inspect_evals", "datasets", "openai"]
miss = [m for m in core if u.find_spec(m) is None]
print(f"   python {'.'.join(map(str, sys.version_info[:3]))}; " +
      ("MISSING: " + ", ".join(miss) if miss else "driver deps present"))
PY
# `shared` importable? (cd $REPO already puts it on the path; fall back to an editable install)
python3 -c "import shared.code_evals" 2>/dev/null && echo "   shared.code_evals importable" \
  || { echo "   installing shared (-e --no-deps)"; pip install -e "$REPO" --no-deps >/dev/null; }

echo "== [2/4] isolated execution env (py3.10 + 74 pinned test libs) =="
if [ -x "$EXEC_DIR/bin/python" ]; then
  echo "   present: $EXEC_DIR ($("$EXEC_DIR/bin/python" --version 2>&1))"
else
  echo "   building via scripts/setup_code_exec_env.sh ..."
  bash "$REPO/scripts/setup_code_exec_env.sh" "$EXEC_DIR"
fi
export BCB_EXEC_PYTHON="$EXEC_DIR/bin/python"

echo "== [3/4] model endpoint =="
if curl -s --max-time 5 "$BASE_URL/models" 2>/dev/null | grep -q "$MODEL"; then
  echo "   already serving $MODEL at $BASE_URL"
elif [ "$SERVE_BASE" = "1" ]; then
  echo "   launching vLLM base $MODEL on :8000 ..."
  nohup vllm serve "$MODEL" --served-model-name "$MODEL" --port 8000 \
    --dtype bfloat16 --max-model-len 6144 --gpu-memory-utilization 0.90 --reasoning-parser qwen3 \
    > /root/vllm_base.log 2>&1 &
  for _ in $(seq 1 60); do
    curl -s --max-time 5 "$BASE_URL/models" 2>/dev/null | grep -q "$MODEL" && { echo "   vLLM ready"; break; }
    sleep 5
  done
  curl -s --max-time 5 "$BASE_URL/models" 2>/dev/null | grep -q "$MODEL" || { echo "!! vLLM did not come up; see /root/vllm_base.log"; exit 1; }
else
  echo "!! nothing serving $MODEL at $BASE_URL and SERVE_BASE!=1 — start a server or pass SERVE_BASE=1"; exit 1
fi

echo "== [4/4] run BigCodeBench (driver py3.11 → exec $BCB_EXEC_PYTHON) =="
ARGS=(--task bigcodebench --model "$MODEL" --base-url "$BASE_URL" --sandbox local
      --exec-python "$BCB_EXEC_PYTHON" --limit "$LIMIT" --max-connections "$MAXCONN")
[ -n "$SUBSET" ] && ARGS+=(--subset "$SUBSET")
[ -n "$CUE" ] && ARGS+=(--cue "$CUE")
echo "   python3 -m shared.code_evals ${ARGS[*]}"
python3 -m shared.code_evals "${ARGS[@]}"
