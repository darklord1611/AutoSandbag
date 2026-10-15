#!/usr/bin/env bash
# Build the ISOLATED code-EXECUTION env for BigCodeBench grading — SEPARATE from the pod's original env.
#
# Why separate (this is forced, not a preference): the eval DRIVER (shared/code_evals.py + inspect_evals)
# requires Python >= 3.11, while BigCodeBench's pinned test libs (numpy==1.21.2, keras==2.11, sympy==1.12,
# scikit-image==0.19 …) require Python < 3.11. They CANNOT coexist in one interpreter. So:
#   * DRIVER env    = the pod's ORIGINAL py3.11 env (already has inspect_ai/inspect_evals/datasets/openai
#                     + our `shared` pkg). This script does NOT touch it.
#   * EXECUTION env = a fresh py3.10 venv (built here) holding ONLY the 74 pinned test libs. The untrusted
#                     model code + hidden unittests run HERE, via `--sandbox local --exec-python <this>/bin/python`
#                     (or export BCB_EXEC_PYTHON). Mirrors BigCodeBench's canonical Docker image
#                     (python:3.10-slim + docker-requirements.txt), minus the container.
#
# Uses `uv` (fast) + the system python3.10. Installs the system libs the tests need (GDAL for geopandas,
# g++, tk, tesseract, libsndfile) best-effort. Run on a THROWAWAY red/green pod — never where secrets live.
#
# Usage:
#   scripts/setup_code_exec_env.sh [EXEC_ENV_DIR]        # default /root/code-exec-env
# Then:
#   export BCB_EXEC_PYTHON=<EXEC_ENV_DIR>/bin/python
#   python -m shared.code_evals --task bigcodebench --model <served> --base-url <url> --sandbox local ...
set -euo pipefail

EXEC_DIR="${1:-/root/code-exec-env}"
PYVER="${PYVER:-3.10}"

command -v uv >/dev/null 2>&1 || { echo "!! uv not found; install uv or adapt this script to python -m venv"; exit 1; }

# Locate BigCodeBench's pinned requirements from the DRIVER env's inspect_evals (py3.11, already installed).
REQ="${BCB_REQ:-}"
if [ -z "$REQ" ]; then
  IE=$(python3 -c 'import inspect_evals, os; print(os.path.dirname(inspect_evals.__file__))' 2>/dev/null || true)
  REQ="${IE:+$IE/bigcodebench/docker-requirements.txt}"
fi
[ -n "${REQ:-}" ] && [ -f "$REQ" ] || { echo "!! could not find bigcodebench docker-requirements.txt (set BCB_REQ=)"; exit 1; }
echo ">> using pinned test-lib requirements: $REQ ($(wc -l < "$REQ") lines)"

# System libs the graded tests import at runtime / build time (from BigCodeBench's Dockerfile, plus
# tesseract for pytesseract and libsndfile for soundfile/librosa). Best-effort — skip if apt is absent.
if command -v apt-get >/dev/null 2>&1; then
  echo ">> installing system deps (apt, best-effort)"
  apt-get update -qq || true
  # python${PYVER}-dev + build-essential: some pinned libs (python-levenshtein-wheels, blake3 …) build
  # C extensions from sdist and need Python.h + a compiler.
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    build-essential g++ git zip unzip procps "python${PYVER}-dev" python3-tk \
    gdal-bin libgdal-dev r-base-core tesseract-ocr libsndfile1 \
    >/dev/null 2>&1 || echo "!! some apt packages failed; geopandas/pytesseract/soundfile tasks may error"
  # GDAL headers for any source build of fiona/geopandas
  export CPLUS_INCLUDE_PATH="${CPLUS_INCLUDE_PATH:-}:/usr/include/gdal"
  export C_INCLUDE_PATH="${C_INCLUDE_PATH:-}:/usr/include/gdal"
else
  echo "!! apt-get not available — ensure GDAL/g++/tk/tesseract/libsndfile are present some other way"
fi

echo ">> creating py${PYVER} execution venv at $EXEC_DIR"
uv venv --python "$PYVER" "$EXEC_DIR"
# shellcheck disable=SC1091
source "$EXEC_DIR/bin/activate"

echo ">> installing the 74 pinned test libs (uv; tensorflow etc. — this pulls a lot)"
uv pip install --python "$EXEC_DIR/bin/python" -r "$REQ"

echo ">> smoke-import a representative spread of the test libs"
"$EXEC_DIR/bin/python" - <<'PY'
import importlib
mods = ["numpy","pandas","scipy","sklearn","matplotlib","statsmodels","sympy","requests",
        "flask","bs4","PIL","cv2","skimage","gensim","nltk","Crypto","dateutil","yaml"]
ok, bad = [], []
for m in mods:
    try: importlib.import_module(m); ok.append(m)
    except Exception as e: bad.append(f"{m}: {type(e).__name__}")
print("imported OK:", ok)
if bad: print("MISSING/broken:", bad)
PY

echo
echo "execution env ready: $EXEC_DIR"
echo "  exec python : $EXEC_DIR/bin/python  ($("$EXEC_DIR/bin/python" --version))"
echo "  use it via  : export BCB_EXEC_PYTHON=$EXEC_DIR/bin/python"
echo "                python -m shared.code_evals --task bigcodebench --model <served> \\"
echo "                  --base-url http://localhost:8000/v1 --sandbox local --exec-python $EXEC_DIR/bin/python --limit 20"
