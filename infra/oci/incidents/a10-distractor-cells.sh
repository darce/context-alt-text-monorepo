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

# golden.json is roster_only. `cli score` exits 3 (REFUSED) unless the
# operator consents with --allow-refused. Do not add that flag here:
# auto-consent would copy a no-score report as if it were a result.
worst_ec=0
note_score_ec() {
  local ec="$1"
  if [ "$ec" -eq 1 ]; then
    worst_ec=1
  elif [ "$ec" -eq 3 ] && [ "$worst_ec" -ne 1 ]; then
    worst_ec=3
  elif [ "$ec" -ne 0 ] && [ "$worst_ec" -eq 0 ]; then
    worst_ec="$ec"
  fi
}
for entry in "two_pass|--prompt-variant v2 --two-pass" "dual_length|--prompt-variant v2 --dual-length"; do
  name="${entry%%|*}"; flags="${entry#*|}"; tag="${name}-context_distractor"; rr="out/run-altq-${tag}.json"
  printf 'fetch %s ... ' "$tag"
  if ( cd "$SVC" && ACX_EVAL_LIVE=1 GOLDEN_IMAGES_DIR="$GOLDEN_IMAGES_DIR" \
       "$PY" -m scripts.eval_harness.bakeoff --endpoint "http://localhost:$PORT" \
         --model-id "Qwen3-VL-30B-A3B-Instruct" --model-version "Q4_K_M" \
         --manifest "$MANIFEST" --eval-mode context_distractor $flags \
         --out "$rr" >/dev/null 2>"$SVC/out/${tag}.err" ); then
    echo "ok -> scoring"
    ( cd "$SVC" && "$PY" -m scripts.eval_harness.cli score --run-record "$rr" --manifest "$MANIFEST" )
    score_ec=$?
    cp "$SVC/$rr" "$RESULTS/" 2>/dev/null
    if [ "$score_ec" -eq 3 ]; then
      echo "  REFUSED (exit 3) — not copying the report as a scored result."
      _refusal_helper="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/eval_refusal_message.py"
      _report_json="$SVC/${rr%.json}-report.json"
      if [ -f "$_refusal_helper" ]; then
        python3 "$_refusal_helper" --report "$_report_json" --log-text "$(cat "$SVC/out/${tag}.err" 2>/dev/null)"
      fi
      mkdir -p "$RESULTS/refused"
      cp "$SVC/${rr%.json}"*report* "$RESULTS/refused/" 2>/dev/null || true
      note_score_ec 3
    elif [ "$score_ec" -ne 0 ]; then
      echo "  score FAILED (exit $score_ec) — partial/determinism/env; not copying reports"
      note_score_ec "$score_ec"
    else
      cp "$SVC/${rr%.json}"*report* "$RESULTS/" 2>/dev/null
    fi
  else
    echo "FAILED (out/${tag}.err)"
    note_score_ec 1
  fi
done
echo "cells done — results in $RESULTS"
echo "NOW TERMINATE:"
echo "  oci compute instance terminate --instance-id ocid1.instance.oc1.iad.anuwcljt2mcagaqcklr52rajo3egewj3bham5hctguewgi6u5ro5o7lenitq --force"
exit "$worst_ec"
