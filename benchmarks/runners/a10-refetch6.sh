#!/usr/bin/env bash
# Fix the 6 corpus holes: re-fetch media_ids 87,172,212,330,584,610 with the
# committed pass-1 1536-token budget, merge back into the 646 run-record, re-score.
# Runs on a caught A10 (30B already baked) via the tailscale jump. ~2 min inference.
#   Usage: bash a10-refetch6.sh <A10_PRIVATE_IP>
# Or piggyback: run this before terminating any A10 already serving the 30B.
set -uo pipefail

PRIV_IP="${1:?usage: a10-refetch6.sh <A10_PRIVATE_IP>}"
PORT=8000
JUMP=$(grep -h "^REMOTE_GATE_HOST=" "$HOME/Development/context-alt-text-monorepo/.workbay/remote-gate.env" | cut -d= -f2- | tr -d '"'"'"' ' | sed 's/#.*//')
SVC="$HOME/Development/context-alt-text-monorepo-altq-1/apps/prototype-description-service"
PY="$HOME/.pyenv/versions/description-service/bin/python"
export GOLDEN_IMAGES_DIR="/Volumes/Butter/WP/vlm/app/public/wp-content/uploads"
BASE="out/run-altq-646-interleave-v3.json"

test -d "$GOLDEN_IMAGES_DIR" || { echo "MOUNT BUTTER FIRST"; exit 1; }

for i in $(seq 1 60); do
  ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -J "$JUMP" ubuntu@"$PRIV_IP" \
    'curl -s --max-time 6 http://localhost:8000/v1/models >/dev/null' 2>/dev/null && break
  sleep 15
done
pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null; sleep 1
ssh -f -N -o StrictHostKeyChecking=accept-new -J "$JUMP" -L "$PORT:localhost:8000" ubuntu@"$PRIV_IP"
trap 'pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null' EXIT
sleep 2

( cd "$SVC" && ACX_EVAL_LIVE=1 GOLDEN_IMAGES_DIR="$GOLDEN_IMAGES_DIR" \
  "$PY" -m scripts.eval_harness.bakeoff --endpoint "http://localhost:$PORT" \
    --model-id "Qwen3-VL-30B-A3B-Instruct" --model-version "Q4_K_M" \
    --manifest scripts/eval_harness/refetch6-manifest-20260716.json \
    --prompt-variant v3 --two-pass --out out/run-refetch6.json ) || { echo "re-fetch FAILED"; exit 1; }

( cd "$SVC" \
  && "$PY" -m scripts.eval_harness.merge_refetch --base "$BASE" --patch out/run-refetch6.json --out "$BASE" \
  && "$PY" -m scripts.eval_harness.cli score --run-record "$BASE" \
       --manifest scripts/eval_harness/corpus646-interleave-manifest-20260716.json )
echo "corpus holes fixed + re-scored. Commit the updated $BASE and regenerate the report."
