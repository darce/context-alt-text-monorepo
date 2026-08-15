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
# Do not treat exit 3 as "rubric partial" and do not discard nonzero.
# 646 manifest is roster_only; refused detection/identification is exit 3.
# --allow-refused is not added here: auto-consent would greenwash a no-score
# report. Copy the run-record always; park refused reports under refused/.
( cd "$SVC" && "$PY" -m scripts.eval_harness.cli score --run-record "$RR" --manifest "$MANIFEST" )
score_ec=$?
cp "$SVC/$RR" "$RESULTS/" 2>/dev/null
if [ "$score_ec" -eq 3 ]; then
  echo "score REFUSED (exit 3): detection/identification not computable honestly (roster_only / unboxed claims). This is not rubric-partial. Report is refused evidence, not a clean score. Add per-face boxes, or re-run score with --allow-refused if you consent to a no-score report."
  mkdir -p "$RESULTS/refused"
  cp "$SVC/${RR%.json}"*report* "$RESULTS/refused/" 2>/dev/null || true
elif [ "$score_ec" -ne 0 ]; then
  echo "score FAILED (exit $score_ec): partial corpus, determinism failure, ManifestError/ReportError, or env — not a refusal."
else
  cp "$SVC/${RR%.json}"*report* "$RESULTS/" 2>/dev/null
fi

echo "Done. Results -> $RESULTS"
echo "TEARDOWN (owed): oci compute instance terminate --instance-id <IID from launch output> --force"
exit "$score_ec"
