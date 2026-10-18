#!/usr/bin/env bash
# VLM-6 Qwen3-VL-30B GPU baseline over the full 646-image corpus (P1 objective).
#   Usage: bash a10-646-baseline.sh [A10_PRIVATE_IP]     (default 10.0.1.68)
# Laptop-driven through the Tailscale jump tunnel; resumable (JSONL skips done
# IDs) — safe to rerun after interruption. Laptop must stay awake; Butter mounted.
set -uo pipefail

PRIV_IP="${1:-10.0.1.68}"
PORT=8000
JUMP=$(grep -h "^REMOTE_GATE_HOST=" "$HOME/Development/context-alt-text-monorepo/.workbay/remote-gate.env" | cut -d= -f2- | tr -d '"'"'"' ' | sed 's/#.*//')
SVC="$HOME/Development/context-alt-text-monorepo-vlm-6/apps/prototype-description-service"
PY="$HOME/.pyenv/versions/description-service/bin/python"

test -d /Volumes/Butter/WP/vlm/app/public/wp-content/uploads || { echo "MOUNT BUTTER FIRST"; exit 1; }

# fresh tunnel (bench script's tunnel dies with it)
pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null; sleep 1
ssh -f -N -o StrictHostKeyChecking=accept-new -J "$JUMP" -L "$PORT:localhost:8000" ubuntu@"$PRIV_IP"
trap 'pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null' EXIT
sleep 2
curl -s --max-time 8 "http://localhost:$PORT/v1/models" >/dev/null || { echo "tunnel not healthy"; exit 1; }

HEAD_SHA=$(git -C "$SVC" rev-parse HEAD)
echo "== 646-corpus Qwen baseline via http://localhost:$PORT (HEAD $HEAD_SHA) =="
cd "$SVC" && BAKEOFF_BASE_URL="http://localhost:$PORT" HEAD_SHA="$HEAD_SHA" BASELINE_LIMIT=0 CHUNK=12 \
  "$PY" -m scripts.eval_harness.describe_baseline
RC=$?
echo "baseline exit=$RC — results: docs/tasks/vlm/bakeoff-results/ + out/vlm-baseline-descriptions-20260716.jsonl"
echo "TEARDOWN (owed):"
echo "  oci compute instance terminate --instance-id ocid1.instance.oc1.iad.anuwcljt2mcagaqcklr52rajo3egewj3bham5hctguewgi6u5ro5o7lenitq --force"
exit $RC
