#!/usr/bin/env bash
# ALTQ-1 Slice 3 GPU A/B bench — Tailscale-jump edition (no public IP anywhere).
#   Usage:  bash a10-onbox-bench.sh [A10_PRIVATE_IP]        (default 10.0.1.68)
#   Env:    GOLDEN_IMAGES_DIR (default ~/Development/eval-fixtures)
#
# Path: laptop --tailnet--> acx-backend (gate) --VCN--> A10 private IP.
# Requires the intra-VCN :22 ingress rule on acx-security-list (added 2026-07-16).
# The baked llama.cpp Qwen3-VL-30B server on the box is reached via an SSH tunnel
# through the jump; the harness runs laptop-side from the altq-1 worktree so
# run-records + reports land in-repo. Every launch pairs with a terminate.
set -uo pipefail

PRIV_IP="${1:-10.0.1.68}"
export GOLDEN_IMAGES_DIR="${GOLDEN_IMAGES_DIR:-$HOME/Development/eval-fixtures}"
[ -d "$GOLDEN_IMAGES_DIR/mock_images" ] || { echo "GOLDEN_IMAGES_DIR invalid: $GOLDEN_IMAGES_DIR (no mock_images/)"; exit 1; }

JUMP=$(grep -h "^REMOTE_GATE_HOST=" "$HOME/Development/context-alt-text-monorepo/.workbay/remote-gate.env" | cut -d= -f2- | tr -d '"'"'"' ' | sed 's/#.*//')
[ -n "$JUMP" ] || { echo "gate host not found in .workbay/remote-gate.env"; exit 1; }

SVC="$HOME/Development/context-alt-text-monorepo-altq-1/apps/prototype-description-service"
PY="$HOME/.pyenv/versions/description-service/bin/python"
RESULTS="$SVC/docs/tasks/altq/bakeoff-results"
PORT=8000
SSHOPT=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=12 -J "$JUMP" ubuntu@"$PRIV_IP")
MANIFEST="scene/tests/seed/golden.json"
MODEL=(--model-id "Qwen3-VL-30B-A3B-Instruct" --model-version "Q4_K_M")

mkdir -p "$RESULTS" "$SVC/out"

echo "== 1/3 verify box via jump ($JUMP -> $PRIV_IP) =="
ssh "${SSHOPT[@]}" 'systemctl is-active acx-gpu-vlm.service && curl -s --max-time 8 http://localhost:8000/v1/models >/dev/null && echo MODEL_SERVER_OK' \
  || { echo "box/model not ready — check: ssh -J $JUMP ubuntu@$PRIV_IP 'journalctl -u acx-gpu-vlm.service -n50'"; exit 1; }

echo "== 2/3 tunnel localhost:$PORT -> box:8000 (through jump) =="
ssh -f -N -o StrictHostKeyChecking=accept-new -J "$JUMP" -L "$PORT:localhost:8000" ubuntu@"$PRIV_IP"
trap 'pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null' EXIT
sleep 2
curl -s --max-time 8 "http://localhost:$PORT/v1/models" >/dev/null || { echo "tunnel not healthy"; exit 1; }

# --- ALTQ-1 config matrix (flags verified against bakeoff.py) -----------------
# two_pass+face_gate SKIPPED: golden.json has 0/37 face_boxes (enrich first or
# the fail-closed gate ablates every name and the cell is vacuous).
CONFIGS=(
  "v1|"
  "v2|--prompt-variant v2"
  "two_pass|--prompt-variant v2 --two-pass"
  "dual_length|--prompt-variant v2 --dual-length"
)
modes_for() {  # macOS ships bash 3.2 — no associative arrays
  case "$1" in
    v1|v2) echo "standard context_distractor name_ablation" ;;
    *)     echo "standard" ;;
  esac
}

echo "== 3/3 bench (~1h GPU budget; Ctrl-C safe — run-records are per-cell) =="
# golden.json is roster_only. `cli score` therefore exits 3 (REFUSED) unless
# the operator consents with --allow-refused. Do not add that flag here:
# auto-consent would copy a no-score report as if it were a result.
START=$(date +%s)
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
for entry in "${CONFIGS[@]}"; do
  name="${entry%%|*}"; flags="${entry#*|}"
  for mode in $(modes_for "$name"); do
    tag="${name}-${mode}"; rr="out/run-altq-${tag}.json"
    printf '[%3dm] fetch %-28s ... ' "$(( ($(date +%s)-START)/60 ))" "$tag"
    if ( cd "$SVC" && ACX_EVAL_LIVE=1 GOLDEN_IMAGES_DIR="$GOLDEN_IMAGES_DIR" \
         "$PY" -m scripts.eval_harness.bakeoff \
           --endpoint "http://localhost:$PORT" "${MODEL[@]}" \
           --manifest "$MANIFEST" --eval-mode "$mode" $flags \
           --out "$rr" >/dev/null 2>"$SVC/out/${tag}.err" ); then
      echo "ok -> scoring"
      ( cd "$SVC" && "$PY" -m scripts.eval_harness.cli score \
          --run-record "$rr" --manifest "$MANIFEST" )
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
      echo "FAILED (out/${tag}.err) — continuing"
      note_score_ec 1
    fi
  done
done

echo
echo "Done in $(( ($(date +%s)-START)/60 ))m. Results -> $RESULTS"
echo "TEARDOWN (owed):"
echo "  oci compute instance terminate --instance-id ocid1.instance.oc1.iad.anuwcljt2mcagaqcklr52rajo3egewj3bham5hctguewgi6u5ro5o7lenitq --force"
exit "$worst_ec"
