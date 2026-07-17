#!/usr/bin/env bash
# ALTQ 646-corpus interleave: v3 three-surface weave (title + WCAG alt + evocative
# caption) with curated identities, via the tailscale jump. ~62 min GPU.
#   Usage: bash a10-interleave-646.sh <A10_PRIVATE_IP>
set -uo pipefail

PRIV_IP="${1:?usage: a10-interleave-646.sh <A10_PRIVATE_IP>}"
PORT=8000
JUMP=$(grep -h "^REMOTE_GATE_HOST=" "$HOME/Development/context-alt-text-monorepo/.workbay/remote-gate.env" | cut -d= -f2- | tr -d '"'"'"' ' | sed 's/#.*//')
SVC="$HOME/Development/context-alt-text-monorepo-altq-1/apps/prototype-description-service"
PY="$HOME/.pyenv/versions/description-service/bin/python"
RESULTS="$HOME/Development/context-alt-text-monorepo-altq-1/docs/tasks/altq/bakeoff-results"
MANIFEST="scripts/eval_harness/corpus646-interleave-manifest-20260716.json"
export GOLDEN_IMAGES_DIR="/Volumes/Butter/WP/vlm/app/public/wp-content/uploads"

test -d "$GOLDEN_IMAGES_DIR" || { echo "MOUNT BUTTER FIRST"; exit 1; }
mkdir -p "$RESULTS" "$SVC/out"

echo "== wait for box + model server (boot ~10 min) =="
for i in $(seq 1 60); do
  ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -J "$JUMP" ubuntu@"$PRIV_IP" \
    'curl -s --max-time 6 http://localhost:8000/v1/models >/dev/null' 2>/dev/null && { echo "  model server up"; break; }
  sleep 20
done

echo "== tunnel =="
pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null; sleep 1
ssh -f -N -o StrictHostKeyChecking=accept-new -J "$JUMP" -L "$PORT:localhost:8000" ubuntu@"$PRIV_IP"
trap 'pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null' EXIT
sleep 2
curl -s --max-time 8 "http://localhost:$PORT/v1/models" >/dev/null || { echo "tunnel not healthy"; exit 1; }

echo "== v3 three-surface interleave over 646 =="
RR="out/run-altq-646-interleave-v3.json"
( cd "$SVC" && ACX_EVAL_LIVE=1 GOLDEN_IMAGES_DIR="$GOLDEN_IMAGES_DIR" \
  "$PY" -m scripts.eval_harness.bakeoff \
    --endpoint "http://localhost:$PORT" \
    --model-id "Qwen3-VL-30B-A3B-Instruct" --model-version "Q4_K_M" \
    --manifest "$MANIFEST" --prompt-variant v3 --two-pass \
    --out "$RR" ) || { echo "fetch FAILED"; exit 1; }

echo "== score =="
( cd "$SVC" && "$PY" -m scripts.eval_harness.cli score --run-record "$RR" --manifest "$MANIFEST" ) || echo "score warning (rubric partial on 646)"
cp "$SVC/$RR" "$RESULTS/" 2>/dev/null
cp "$SVC/${RR%.json}"*report* "$RESULTS/" 2>/dev/null

echo "Done. Results -> $RESULTS"
echo "TEARDOWN (owed): oci compute instance terminate --instance-id <IID from launch output> --force"
