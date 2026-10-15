#!/usr/bin/env bash
# Pre-flight for a RunPod GPU pod. Run this FIRST, from the repo root, before anything else:
# it proves you are on OUR Docker image (a stock pod is missing these deps), the GPU works,
# and the HF token the PIPELINE will actually use is valid — catching the exact failures
# (wrong image / missing openai / 401 token / clobbered torch) that otherwise surface mid-run.
#
#   bash scripts/pod_check.sh train    # on a training pod
#   bash scripts/pod_check.sh serve    # on a serve / eval pod
set -uo pipefail
ROLE="${1:-train}"

python3 - "$ROLE" <<'PY'
import importlib, os, sys

role = sys.argv[1]
if role not in ("train", "serve"):
    print(f"usage: pod_check.sh [train|serve] (got {role!r})"); sys.exit(2)
fail: list[str] = []

# 1) Deps that ONLY our image has. A stock RunPod pod (or a clobbered env) fails here.
common = [("pyyaml", "yaml"), ("tqdm", "tqdm"), ("huggingface_hub", "huggingface_hub")]
train  = [("openai", "openai"), ("transformers", "transformers"), ("trl", "trl"),
          ("peft", "peft"), ("accelerate", "accelerate"), ("bitsandbytes", "bitsandbytes")]
serve  = [("inspect-ai", "inspect_ai"), ("inspect-evals", "inspect_evals")]
for label, mod in common + (train if role == "train" else serve):
    try:
        importlib.import_module(mod)
    except Exception as e:
        fail.append(f"import {label}: {type(e).__name__}: {e}")

# 2) GPU. torch must import AND see CUDA (a mismatched torch/torchvision breaks the import).
try:
    import torch
    print(f"[ok] torch {torch.__version__}  cuda_available={torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        fail.append("torch present but CUDA unavailable (wrong image / no GPU / bad torch build)")
except Exception as e:
    (fail.append if role == "train" else print)(
        f"torch not importable: {e}" if role == "train"
        else f"[..] torch not importable ({e}) — ok on a pure-vLLM serve pod")

# 3) The HF token the pipeline uses. load_env() mirrors the real path: repo .env OVERRIDES shell.
try:
    sys.path.insert(0, os.getcwd())
    from shared.env import load_env
    load_env()
    from huggingface_hub import whoami
    print(f"[ok] HF token valid — user: {whoami(token=os.environ.get('HF_TOKEN')).get('name')}")
except Exception as e:
    fail.append(f"HF token invalid/missing ({type(e).__name__}). The code reads .env FIRST "
                f"(it overrides the shell) — put a valid WRITE token in .env on this pod")

# 4) Soft checks (warn only).
if role == "train" and not os.environ.get("WANDB_API_KEY"):
    print("[..] WANDB_API_KEY unset — training won't log to WandB "
          "(set it, or export WANDB_MODE=disabled to silence)")

print()
if fail:
    print("FAILED pod check:")
    for f in fail:
        print("   -", f)
    sys.exit(1)
print(f"PASS — pod is ready for: {role}")
PY
