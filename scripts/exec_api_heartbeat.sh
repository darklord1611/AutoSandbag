#!/usr/bin/env bash
# Keep-alive heartbeat for the exec-api host.
#
# Two jobs, every $INTERVAL seconds:
#   1. Generate real activity (a CPU tick + a network call) so an idle-timeout manager
#      does not suspend the machine.
#   2. Poll the exec-api /health; if it is down, relaunch it from the committed script so a
#      crash or OOM doesn't silently leave the endpoint dead.
#
# Usage (run detached so it survives the shell):
#   EXEC_API_TOKEN=$(cat .token) nohup bash scripts/exec_api_heartbeat.sh > heartbeat.log 2>&1 &
#
# Env:
#   EXEC_API_TOKEN   required — same token the server uses
#   HEARTBEAT_INTERVAL  seconds between beats (default 60)
#   EXEC_API_PORT    default 8000
#   EXEC_API_POOL    default 4
set -u

INTERVAL="${HEARTBEAT_INTERVAL:-60}"
PORT="${EXEC_API_PORT:-8000}"
POOL="${EXEC_API_POOL:-4}"
REPO="/teamspace/studios/this_studio/AutoSandbag"
TOK="${EXEC_API_TOKEN:-}"

[ -n "$TOK" ] || { echo "heartbeat: EXEC_API_TOKEN not set; refusing to start" >&2; exit 1; }

is_up() { curl -s -m 5 -H "Authorization: Bearer $TOK" "http://localhost:$PORT/health" >/dev/null 2>&1; }

relaunch() {
  echo "$(date -u +%FT%TZ) exec-api DOWN -> relaunching" >&2
  cd "$REPO" || return 1
  nohup env EXEC_API_TOKEN="$TOK" python3 scripts/exec_api.py \
    --port "$PORT" --pool-size "$POOL" --prewarm light \
    > /tmp/exec_api_relaunch.log 2>&1 &
}

echo "$(date -u +%FT%TZ) heartbeat started (interval=${INTERVAL}s port=${PORT})"
while true; do
  # 1) tiny activity tick — keeps the box from reading as idle
  : "$(python3 -c 'import time,hashlib;hashlib.sha256(str(time.time()).encode()).hexdigest()' 2>/dev/null)"
  # 2) health + self-heal
  if is_up; then
    echo "$(date -u +%FT%TZ) beat ok"
  else
    relaunch
    sleep 10
    is_up && echo "$(date -u +%FT%TZ) relaunch ok" || echo "$(date -u +%FT%TZ) relaunch FAILED" >&2
  fi
  sleep "$INTERVAL"
done
