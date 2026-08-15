#!/usr/bin/env bash
# Operator entry for the caption+face eval harness `run` subcommand.
#
# The scorer's exit contract is 0/1/2/3. GNU Make cannot honour that as
# *make's* process status (every failed recipe becomes make exit 2). This
# script is the command that can actually exit 3. `make eval-captions`
# calls this script and then collapses any nonzero status to 2.
#
# Always prints `eval-captions: scorer_exit=<N>` and writes that N to
# apps/prototype-description-service/scripts/eval_harness/out/eval-captions.status
# so a make caller can still read the real scorer status.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE="$ROOT/apps/prototype-description-service"
OUT_DIR="$SERVICE/scripts/eval_harness/out"
STATUS_FILE="$OUT_DIR/eval-captions.status"
LOG_FILE="$OUT_DIR/eval-captions.last.log"

mkdir -p "$OUT_DIR"

set +e
(
  cd "$SERVICE" || exit 2
  uv run python -m scripts.eval_harness.cli run "$@"
) >"$LOG_FILE" 2>&1
ec=$?
set -e

cat "$LOG_FILE"
printf '%s\n' "$ec" > "$STATUS_FILE"
printf 'eval-captions: scorer_exit=%s\n' "$ec"
if [ "$ec" -eq 3 ]; then
  python3 "$ROOT/scripts/eval_refusal_message.py" --log "$LOG_FILE" >&2
fi
exit "$ec"
