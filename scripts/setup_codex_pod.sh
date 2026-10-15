#!/usr/bin/env bash
# setup_codex_pod.sh — prepare a pod to run GPT models as the red agent via inspect_swe codex_cli.
#
# Why this exists: /root and /usr/local/bin are WIPED on every pod restart, and inspect_swe 0.2.67
# does NOT ship the `codex-code-mode-host` binary that code_mode_only models (e.g. gpt-5.6-sol) require.
# Run this once after any (re)start of a pod you intend to use for a codex/GPT round. Idempotent.
#
# What it does:
#   1. pip: inspect_swe (pinned), openai>=3.1.0 (inspect needs it), and the local `shared` package.
#   2. codex: install the codex binary AND its sibling `codex-code-mode-host` together on PATH,
#      so inspect_swe's `which codex` escape hatch (version=auto) uses them and code mode can spawn
#      its host. (No node/npm — codex is a single Rust/musl binary.)
#   3. nginx :3001 fix (inspect's model-proxy must bind 127.0.0.1:3001; the template nginx grabs it).
#   4. verify keys (OPENAI_API_KEY etc. live in /proc/1/environ on these pods).
#
# Usage (on the pod, from the repo root or anywhere):
#   bash scripts/setup_codex_pod.sh                 # latest upstream codex stable (default)
#   CODEX_VERSION=0.152.0 bash scripts/setup_codex_pod.sh  # pin a specific version (last known-good)
#
# After this, launch a round (keys sourced from PID 1), e.g.:
#   python -m red_team --brief red_team/briefs/round_evade_audit_math_v1.yaml \
#     --agent codex_cli --model openai/gpt-5.6-sol --sandbox local --time-limit 43200

set -euo pipefail

# ---- config ----
CODEX_VERSION="${CODEX_VERSION:-latest}"    # latest upstream stable; or pin e.g. 0.152.0 (tested red1 2026-09-01)
INSPECT_SWE_VERSION="${INSPECT_SWE_VERSION:-0.2.67}"
BINDIR=/usr/local/bin
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n\033[1;36m[setup_codex] %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[setup_codex][warn] %s\033[0m\n' "$*"; }

# ---- 0. arch ----
case "$(uname -m)" in
  x86_64|amd64) ARCH=x86_64-unknown-linux-musl ;;
  aarch64|arm64) ARCH=aarch64-unknown-linux-musl ;;
  *) echo "unsupported arch $(uname -m)"; exit 1 ;;
esac
say "arch=$ARCH  codex_version=$CODEX_VERSION  repo=$REPO_ROOT"

# ---- 1. python deps ----
say "installing python deps (inspect_swe==$INSPECT_SWE_VERSION, openai>=3.1.0, shared)"
python -c "import inspect_swe" 2>/dev/null && echo "  inspect_swe present" \
  || pip install -q "inspect_swe==$INSPECT_SWE_VERSION"
# inspect's OpenAI provider requires openai>=3.1.0 (pods often ship 2.x -> a hard ERROR at launch)
pip install -q --upgrade "openai>=3.1.0"
# the neutral shared eval package (editable, no deps so the image stays cheap)
if [ -f "$REPO_ROOT/pyproject.toml" ]; then
  pip install -q -e "$REPO_ROOT" --no-deps && echo "  shared installed (editable)"
else
  warn "no pyproject.toml at $REPO_ROOT — skipping 'shared' install (run from the repo)"
fi

# ---- 2. codex + code-mode-host on PATH ----
# resolve the release tag (codex tags are rust-vX.Y.Z)
if [ "$CODEX_VERSION" = "latest" ]; then
  say "resolving latest codex release tag"
  TAG="$(curl -sL https://api.github.com/repos/openai/codex/releases/latest \
         | python -c 'import sys,json; print(json.load(sys.stdin)["tag_name"])')"
  CODEX_VERSION="${TAG#rust-v}"
else
  TAG="rust-v${CODEX_VERSION}"
fi
BASE_URL="https://github.com/openai/codex/releases/download/${TAG}"

# skip if the exact version is already installed
CUR="$("$BINDIR/codex" --version 2>/dev/null | awk '{print $NF}' || true)"
if [ "$CUR" = "$CODEX_VERSION" ] && [ -x "$BINDIR/codex-code-mode-host" ]; then
  say "codex $CODEX_VERSION + host already installed — skipping download"
else
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  say "downloading codex $CODEX_VERSION ($TAG) + code-mode-host"
  for name in "codex-${ARCH}" "codex-code-mode-host-${ARCH}"; do
    curl -fsSL -o "$TMP/${name}.tar.gz" "${BASE_URL}/${name}.tar.gz" \
      || { echo "download failed: ${BASE_URL}/${name}.tar.gz"; exit 1; }
    tar xzf "$TMP/${name}.tar.gz" -C "$TMP"
  done
  # place the two binaries side-by-side on PATH (codex looks for the host in its OWN dir)
  CODEX_BIN="$(find "$TMP" -maxdepth 2 -type f -name "codex-${ARCH}" | head -1)"
  HOST_BIN="$(find "$TMP" -maxdepth 2 -type f -name "codex-code-mode-host-${ARCH}" | head -1)"
  [ -n "$CODEX_BIN" ] && [ -n "$HOST_BIN" ] || { echo "extracted binaries not found"; exit 1; }
  install -m 0755 "$CODEX_BIN" "$BINDIR/codex"
  install -m 0755 "$HOST_BIN"  "$BINDIR/codex-code-mode-host"
  rm -rf "$TMP"; trap - EXIT
fi

# ---- 3. nginx :3001 (inspect model-proxy must bind 127.0.0.1:3001) ----
if command -v nginx >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q '0.0.0.0:3001'; then
  N="$(grep -nE 'listen 3001;' /etc/nginx/nginx.conf 2>/dev/null | head -1 | cut -d: -f1 || true)"
  if [ -n "$N" ]; then
    sed -i "${N}s/listen 3001;/listen 3009;/" /etc/nginx/nginx.conf && nginx -t && nginx -s reload \
      && say "nginx :3001 -> :3009 (freed for inspect)"
  else
    warn ":3001 is held but no 'listen 3001;' line found — free it before launching"
  fi
fi

# ---- 4. verify ----
say "verification"
echo "  which codex           : $(command -v codex || echo MISSING)"
echo "  codex --version       : $("$BINDIR/codex" --version 2>&1 | head -1)"
echo "  code-mode-host present: $([ -x "$BINDIR/codex-code-mode-host" ] && echo yes || echo NO)"
echo "  openai version        : $(python -c 'import openai; print(openai.__version__)' 2>&1)"
echo "  inspect_swe           : $(python -c 'import inspect_swe; print(inspect_swe.__version__)' 2>&1)"
echo "  shared import         : $(python -c 'import shared; print("ok")' 2>&1)"
if ss -ltn 2>/dev/null | grep -q '127.0.0.1:3001\|0.0.0.0:3001'; then
  warn ":3001 still held (likely a stale inspect-sandbox from a prior/killed run — inspect binds"
  warn "  127.0.0.1:3001 and a new launch dies with Errno 98). Reap it before launching:"
  warn "  ss -ltnp | grep :3001   then   pkill -9 -f inspect-sandbox"
else
  echo "  :3001                 : free"
fi
# keys live in PID 1's environ on these pods; surface which are present (values masked)
echo "  keys in /proc/1/environ:"
for k in OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY HF_TOKEN CODE_EXEC_API_URL; do
  if tr '\0' '\n' < /proc/1/environ 2>/dev/null | grep -q "^${k}="; then echo "    $k = SET"; else echo "    $k = (absent)"; fi
done

say "done. Launch example (source keys from PID 1 first):"
cat <<'EOF'
  while IFS= read -r kv; do case "$kv" in OPENAI_API_KEY=*|ANTHROPIC_API_KEY=*|OPENROUTER_API_KEY=*|HF_TOKEN=*) export "$kv";; esac; done < <(tr '\0' '\n' < /proc/1/environ)
  python -m red_team --brief red_team/briefs/round_evade_audit_math_v1.yaml \
    --agent codex_cli --model openai/gpt-5.6-sol --sandbox local --time-limit 43200
EOF
