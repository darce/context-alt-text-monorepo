#!/usr/bin/env bash
# ALTQ-1 follow-up: the two missing discriminator cells (two_pass / dual_length under
# context_distractor) — tests whether describe-then-ground fixes the 8/37 distractor bite.
# Run right after the 646 baseline, before terminate. ~6 min GPU.
set -uo pipefail
PRIV_IP="${1:-10.0.1.68}"; PORT=8000
export GOLDEN_IMAGES_DIR="${GOLDEN_IMAGES_DIR:-$HOME/Development/eval-fixtures}"
JUMP=$(grep -h "^REMOTE_GATE_HOST=" "$HOME/Development/context-alt-text-monorepo/.workbay/remote-gate.env" | cut -d= -f2- | tr -d '"'"'"' ' | sed 's/#.*//')
SVC="$HOME/Development/context-alt-text-monorepo-altq-1/apps/prototype-description-service"
PY="$HOME/.pyenv/versions/description-service/bin/python"
RESULTS="$HOME/Development/context-alt-text-monorepo-altq-1/docs/tasks/altq/bakeoff-results"
MANIFEST="scene/tests/seed/golden.json"

pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null; sleep 1
ssh -f -N -o StrictHostKeyChecking=accept-new -J "$JUMP" -L "$PORT:localhost:8000" ubuntu@"$PRIV_IP"
trap 'pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null' EXIT
sleep 2
curl -s --max-time 8 "http://localhost:$PORT/v1/models" >/dev/null || { echo "tunnel not healthy"; exit 1; }

for entry in "two_pass|--prompt-variant v2 --two-pass" "dual_length|--prompt-variant v2 --dual-length"; do
  name="${entry%%|*}"; flags="${entry#*|}"; tag="${name}-context_distractor"; rr="out/run-altq-${tag}.json"
  printf 'fetch %s ... ' "$tag"
  if ( cd "$SVC" && ACX_EVAL_LIVE=1 GOLDEN_IMAGES_DIR="$GOLDEN_IMAGES_DIR" \
       "$PY" -m scripts.eval_harness.bakeoff --endpoint "http://localhost:$PORT" \
         --model-id "Qwen3-VL-30B-A3B-Instruct" --model-version "Q4_K_M" \
         --manifest "$MANIFEST" --eval-mode context_distractor $flags \
         --out "$rr" >/dev/null 2>"$SVC/out/${tag}.err" ); then
    echo "ok -> scoring"
    ( cd "$SVC" && "$PY" -m scripts.eval_harness.cli score --run-record "$rr" --manifest "$MANIFEST" >/dev/null 2>&1 )
    cp "$SVC/$rr" "$RESULTS/" 2>/dev/null; cp "$SVC/${rr%.json}"*report* "$RESULTS/" 2>/dev/null
  else
    echo "FAILED (out/${tag}.err)"
  fi
done
echo "cells done — results in $RESULTS"
echo "NOW TERMINATE:"
echo "  oci compute instance terminate --instance-id ocid1.instance.oc1.iad.anuwcljt2mcagaqcklr52rajo3egewj3bham5hctguewgi6u5ro5o7lenitq --force"
