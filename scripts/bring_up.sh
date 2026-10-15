#!/usr/bin/env bash
# One-command bring-up for the exec-api host. Idempotent: safe to re-run after a restart.
#
# Restarts on this cloudspace wipe Docker images AND the scratchpad, so every reboot needs a
# re-pull + relaunch. This script does all of it: resolve the token, pull both tier images,
# start the server, start the heartbeat, then warm + verify. Run it and the endpoint is back.
#
#   bash scripts/bring_up.sh
#
# Token resolution, in order (so "use the current token" survives a wipe):
#   1. $EXEC_API_TOKEN if set
#   2. $EXEC_API_TOKEN_FILE (default below) -- lives on the PERSISTENT /teamspace volume,
#      OUTSIDE the repo, so it is never committed and never wiped by a restart
#   3. otherwise generate a fresh one and save it to that file
#
# Flags:
#   --no-bcb    skip the heavy BigCodeBench image (light tier only, fast)
#   --force     kill any running server/heartbeat first, then rebuild
set -u

REPO="/teamspace/studios/this_studio/AutoSandbag"
TOKEN_FILE="${EXEC_API_TOKEN_FILE:-/teamspace/studios/this_studio/.exec_api_token}"
PORT="${EXEC_API_PORT:-8000}"
POOL="${EXEC_API_POOL:-4}"
RUN_DIR="${EXEC_API_RUN_DIR:-/tmp/exec_api_run}"
LIGHT_IMG="python:3.11-slim"
BCB_IMG="ghcr.io/arcadiaimpact/inspect-eval-bigcodebench:latest"
LABEL="com.autosandbag.exec-api"
WANT_BCB=1; FORCE=0
for a in "$@"; do case "$a" in --no-bcb) WANT_BCB=0;; --force) FORCE=1;; esac; done

mkdir -p "$RUN_DIR"
cd "$REPO" || { echo "repo not found: $REPO" >&2; exit 1; }

# --- token ---------------------------------------------------------------
if [ -n "${EXEC_API_TOKEN:-}" ]; then
  TOK="$EXEC_API_TOKEN"
elif [ -s "$TOKEN_FILE" ]; then
  TOK="$(tr -d '\r\n' < "$TOKEN_FILE")"
else
  TOK="$(openssl rand -hex 32)"; printf '%s\n' "$TOK" > "$TOKEN_FILE"; chmod 600 "$TOKEN_FILE"
  echo "generated a new token -> $TOKEN_FILE"
fi
printf '%s\n' "$TOK" > "$TOKEN_FILE"; chmod 600 "$TOKEN_FILE"   # ensure persisted

health() { curl -s -m 5 -H "Authorization: Bearer $TOK" "http://localhost:$PORT/health" 2>/dev/null; }

# --- optional force teardown --------------------------------------------
if [ "$FORCE" = "1" ]; then
  for f in "$RUN_DIR/server.pid" "$RUN_DIR/heartbeat.pid"; do
    [ -s "$f" ] && kill "$(cat "$f")" 2>/dev/null
  done
  for pid in $(ss -ltnp 2>/dev/null | grep ":$PORT" | grep -oP 'pid=\K[0-9]+'); do kill "$pid" 2>/dev/null; done
  docker ps -q --filter "label=$LABEL" | xargs -r docker kill >/dev/null 2>&1
  sleep 2
fi

# --- images --------------------------------------------------------------
echo ">> pulling $LIGHT_IMG"
docker pull "$LIGHT_IMG" >/dev/null 2>&1 || { echo "light pull FAILED" >&2; exit 1; }
if [ "$WANT_BCB" = "1" ] && [ -z "$(docker images -q "$BCB_IMG")" ]; then
  echo ">> pulling $BCB_IMG in background (~5.5GB)"
  setsid docker pull "$BCB_IMG" > "$RUN_DIR/bcb_pull.log" 2>&1 < /dev/null &
  disown 2>/dev/null || true
fi

# --- server (skip if already healthy, unless forced) --------------------
if health >/dev/null 2>&1; then
  echo ">> server already up on :$PORT"
else
  echo ">> starting server"
  nohup env EXEC_API_TOKEN="$TOK" python3 scripts/exec_api.py \
    --port "$PORT" --pool-size "$POOL" --prewarm light \
    > "$RUN_DIR/exec_api.log" 2>&1 &
  echo $! > "$RUN_DIR/server.pid"
  for _ in $(seq 1 300); do health >/dev/null 2>&1 && break; sleep 1; done
  health >/dev/null 2>&1 && echo ">> server up" || { echo "server did NOT come up; see $RUN_DIR/exec_api.log" >&2; exit 1; }
fi

# --- heartbeat (start only if not already alive) ------------------------
HB_PID="$([ -s "$RUN_DIR/heartbeat.pid" ] && cat "$RUN_DIR/heartbeat.pid" || echo)"
if [ -n "$HB_PID" ] && kill -0 "$HB_PID" 2>/dev/null; then
  echo ">> heartbeat already alive (pid $HB_PID)"
else
  echo ">> starting heartbeat"
  EXEC_API_RUN_DIR="$RUN_DIR" nohup env EXEC_API_TOKEN="$TOK" EXEC_API_PORT="$PORT" \
    HEARTBEAT_INTERVAL="${HEARTBEAT_INTERVAL:-60}" \
    bash scripts/exec_api_heartbeat.sh > "$RUN_DIR/heartbeat.log" 2>&1 &
  echo $! > "$RUN_DIR/heartbeat.pid"
fi

# --- wait for bcb + warm + verify ---------------------------------------
if [ "$WANT_BCB" = "1" ]; then
  echo -n ">> waiting for bcb image "
  for _ in $(seq 1 60); do
    [ -n "$(docker images -q "$BCB_IMG")" ] && break; echo -n "."; sleep 10
  done; echo
  if [ -n "$(docker images -q "$BCB_IMG")" ]; then
    curl -s -m 90 -H "Authorization: Bearer $TOK" -X POST "http://localhost:$PORT/exec" \
      -d '{"tier":"bcb","program":"import numpy,pandas;print(numpy.__version__,pandas.__version__)"}' \
      | grep -q '"returncode": 0' && echo ">> bcb verified" || echo ">> bcb NOT verified yet" >&2
  else
    echo ">> bcb still pulling; tier will work once it lands" >&2
  fi
fi

echo
echo "===================== exec-api is up ====================="
health | python3 -c 'import sys,json;d=json.load(sys.stdin);print("health:","ok" if d["ok"] else "DOWN","| tiers:",{k:v["idle"] for k,v in d["tiers"].items()})' 2>/dev/null
echo "local : http://localhost:$PORT"
echo "token : $TOK"
echo "token file (persistent): $TOKEN_FILE"
echo "=========================================================="
