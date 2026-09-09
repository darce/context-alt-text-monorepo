#!/usr/bin/env bash
# 10-image multi-model description bake-off on a caught A10, via the tailscale jump.
# Serves each candidate GGUF in turn on the box's llama.cpp, runs the 10-image
# v3 two-pass describe from the laptop, collects one run-record per model.
#   Usage: bash a10-multimodel-bakeoff.sh <A10_PRIVATE_IP>
#
# OPERATOR: fill the GGUF/mmproj URLs in MODELS below — the research shortlist
# (docs/tasks/vlm/multi-model-bakeoff-plan-2026-07-16.md) names the HF repos but
# exact filenames MUST be verified on each repo page (VLM tooling moves weekly).
# The 30B control is NOT re-run here — its run-record already exists.
# Requires llama.cpp >= b6887 on the box (Qwen3-VL vision). The Qwen3.6 candidate
# (qwen3_5-arch VLM) needs a NEWER llama.cpp build than b6887 — verify the box's
# build serves Qwen3.6 vision before the run (a stale build fails it loudly; the
# loop continues to the next model). A wrong URL or an unsupported-vision build
# fails that model loudly; the loop continues to the next.
set -uo pipefail

PRIV_IP="${1:?usage: a10-multimodel-bakeoff.sh <A10_PRIVATE_IP>}"
PORT=8000
JUMP=$(grep -h "^REMOTE_GATE_HOST=" "$HOME/Development/context-alt-text-monorepo/.workbay/remote-gate.env" | cut -d= -f2- | tr -d '"'"'"' ' | sed 's/#.*//')
SVC="$HOME/Development/context-alt-text-monorepo-altq-1/apps/prototype-description-service"
PY="$HOME/.pyenv/versions/description-service/bin/python"
MANIFEST="scripts/eval_harness/bakeoff10-manifest-20260716.json"
export GOLDEN_IMAGES_DIR="/Volumes/Butter/WP/vlm/app/public/wp-content/uploads"
SSHJ=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=12 -J "$JUMP" ubuntu@"$PRIV_IP")
# Bench artifacts (run records + image-embedded reports) reference real tenant media
# with pseudonymised roster labels — write them ONLY to the gitignored /benchmarks/
# sink (repo .gitignore: "/benchmarks/  # local-only, privacy-sensitive"), never a
# tracked docs path. Absolute so they escape $SVC when the harness runs with `cd "$SVC"`.
BENCH_DIR="$HOME/Development/context-alt-text-monorepo/benchmarks/vlm-bakeoff"
mkdir -p "$BENCH_DIR/reports"

# label | gguf_url | mmproj_url | model_id | quant   (VERIFY URLs before running)
# Two Qwen3.6 VLM candidates vs the Qwen3-VL-30B-A3B@Q4_K_M control (VECVLM-1 assessment,
# docs/assessments/current/vector-store-and-vlm-upgrade-evaluation-2026-07-18.md):
#   qwen36-27b     dense 27B, UD-Q4_K_XL ~17.6GB + mmproj ~0.9GB — headline A10 fit.
#   qwen36-35b-a3b MoE 35B/3B-active, UD-Q3_K_XL ~16.8GB + mmproj ~0.9GB — A10-deployable
#                  quant (UD-Q4 22.4GB is too tight for 24GB VRAM w/ mmproj+KV; that tier
#                  needs A10.2 48GB / A100). Q3 keeps 8192 ctx headroom.
#   joycaption-b1  CAPTION-SPECIALIZED 8B (Llama 3.1 + LLaVA), Q8_0 ~8.5GB — near-lossless,
#                  fits A10 easily. Different design point (tuned for dense captions, not a
#                  general instruct-VLM). LICENSE: Llama 3.1 Community License governs the
#                  derivative (OK <700M MAU, needs "Built with Llama" attribution) — the
#                  author's "no restrictions on weights" does NOT override the base license.
#                  Run on the SAME v3 prompt as all candidates for comparability; its
#                  instruction-obedience (roster-name weaving + naming-policy compliance +
#                  Easy-Wrong traps) is the make-or-break metric, not raw caption richness.
# Filenames verified on the source repos 2026-07-19; re-verify (VLM tooling moves weekly).
MODELS=(
  "qwen36-27b|https://huggingface.co/unsloth/Qwen3.6-27B-GGUF/resolve/main/Qwen3.6-27B-UD-Q4_K_XL.gguf|https://huggingface.co/unsloth/Qwen3.6-27B-GGUF/resolve/main/mmproj-F16.gguf|Qwen3.6-27B|UD-Q4_K_XL"
  "qwen36-35b-a3b|https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q3_K_XL.gguf|https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/mmproj-F16.gguf|Qwen3.6-35B-A3B|UD-Q3_K_XL"
  "joycaption-b1|https://huggingface.co/concedo/llama-joycaption-beta-one-hf-llava-mmproj-gguf/resolve/main/Llama-Joycaption-Beta-One-Hf-Llava-Q8_0.gguf|https://huggingface.co/concedo/llama-joycaption-beta-one-hf-llava-mmproj-gguf/resolve/main/llama-joycaption-beta-one-llava-mmproj-model-f16.gguf|llama-joycaption-beta-one|Q8_0"
  "qwen8b|<TODO Qwen3-VL-8B-Instruct Q5_K_M GGUF url>|<TODO mmproj url>|Qwen3-VL-8B-Instruct|Q5_K_M"
  "minicpm45|<TODO MiniCPM-V-4_5 Q5 GGUF url>|<TODO mmproj url>|MiniCPM-V-4_5|Q5_K_M"
  "gemma4-12b|<TODO gemma-4-12b-it Q6 GGUF url>|<TODO mmproj url>|gemma-4-12b-it|Q6_K"
  "gemma3-27b|<TODO gemma-3-27b-it Q4_K_M GGUF url>|<TODO mmproj url>|gemma-3-27b-it|Q4_K_M"
)

test -d "$GOLDEN_IMAGES_DIR" || { echo "MOUNT BUTTER FIRST"; exit 1; }

serve() {  # $1=gguf_url $2=mmproj_url ; (re)start llama.cpp on the box pointed at it
  ssh "${SSHJ[@]}" "sudo systemctl stop acx-gpu-vlm.service 2>/dev/null; \
    mkdir -p ~/models && cd ~/models && \
    curl -fL --retry 3 -o cand.gguf '$1' && curl -fL --retry 3 -o cand-mmproj.gguf '$2' && \
    nohup \$HOME/llama.cpp/build/bin/llama-server -m ~/models/cand.gguf --mmproj ~/models/cand-mmproj.gguf \
      --host 127.0.0.1 --port 8000 --ctx-size 8192 --image-max-tokens 1536 --parallel 1 \
      > ~/cand-server.log 2>&1 & echo started"
}

for spec in "${MODELS[@]}"; do
  IFS='|' read -r label gurl murl mid quant <<<"$spec"
  case "$gurl" in *TODO*) echo "SKIP $label — URL not filled"; continue;; esac
  echo "== $label: serve on box =="
  serve "$gurl" "$murl" || { echo "  serve failed for $label"; continue; }
  # wait for readiness through the jump
  ok=""
  for i in $(seq 1 40); do
    ssh "${SSHJ[@]}" 'curl -s --max-time 6 http://localhost:8000/v1/models >/dev/null' 2>/dev/null && { ok=1; break; }
    sleep 15
  done
  [ -n "$ok" ] || { echo "  $label never became ready — see ~/cand-server.log on box"; continue; }
  # tunnel + run the 10-image v3 two-pass describe
  pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null; sleep 1
  ssh -f -N -o StrictHostKeyChecking=accept-new -J "$JUMP" -L "$PORT:localhost:8000" ubuntu@"$PRIV_IP"
  sleep 2
  ( cd "$SVC" && ACX_EVAL_LIVE=1 GOLDEN_IMAGES_DIR="$GOLDEN_IMAGES_DIR" \
    "$PY" -m scripts.eval_harness.bakeoff --endpoint "http://localhost:$PORT" \
      --model-id "$mid" --model-version "$quant" --manifest "$MANIFEST" \
      --prompt-variant v3 --two-pass --out "$BENCH_DIR/run-bakeoff-$label.json" ) \
    && echo "  $label done -> $BENCH_DIR/run-bakeoff-$label.json" || echo "  $label fetch FAILED"
  pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null
done

echo "== build the comparison report =="
# Control run-record: from the interleave run; move/symlink it into $BENCH_DIR first.
# Guarded like the candidate loop below so a missing control degrades the report to
# candidates-only instead of crashing build_bakeoff_report (uncaught FileNotFoundError)
# AFTER the A10 GPU spend. Warn loudly so the operator knows the baseline is absent.
CONTROL_RUN="$BENCH_DIR/run-altq-646-interleave-v3.json"
CONTROL_LABEL="Qwen3-VL-30B (control)"
RUNS=()
RUNS_EMPTY=1
if [ -f "$CONTROL_RUN" ]; then
  # The control was measured on the 646-image corpus, not on $MANIFEST. That is a
  # different split [EVAL-01/EXP-07], so consent to it explicitly: the report keeps
  # the column but badges it non-comparable instead of passing it off as a control.
  RUNS+=(--run "$CONTROL_LABEL=$CONTROL_RUN" --allow-foreign-run "$CONTROL_LABEL")
  RUNS_EMPTY=0
else
  echo "  WARN: control run-record missing ($CONTROL_RUN) — move/symlink the interleave run into \$BENCH_DIR; report will omit the 30B control baseline." >&2
fi
for spec in "${MODELS[@]}"; do
  IFS='|' read -r label _ _ _ _ <<<"$spec"
  if [ -f "$BENCH_DIR/run-bakeoff-$label.json" ]; then
    RUNS+=(--run "$label=$BENCH_DIR/run-bakeoff-$label.json")
    RUNS_EMPTY=0
  fi
done
REPORT_OUT="$BENCH_DIR/reports/bakeoff-10img-multimodel.html"
if [ "$RUNS_EMPTY" = 1 ]; then
  # bash 3.2 + `set -u`: expanding an empty array is a fatal unbound-variable error.
  echo "  WARN: no run-records to report on — skipping the report build." >&2
else
  rc=0
  ( cd "$SVC" && "$PY" -m scripts.eval_harness.build_bakeoff_report \
      --manifest "$MANIFEST" --images-dir "$GOLDEN_IMAGES_DIR" \
      --media-ids 93,154,200,46,62,98,6,11,400,378 --embed-images \
      ${RUNS[@]+"${RUNS[@]}"} --title "10-image multi-model bake-off" \
      --out "$REPORT_OUT" ) || rc=$?
  if [ "$rc" = 0 ]; then
    echo "report -> $REPORT_OUT (gitignored)"
  elif [ "$rc" = 4 ]; then
    echo "  REFUSED: a run-record is not comparable to $MANIFEST; no report written. See the error above." >&2
  else
    echo "  ERROR: report build failed (exit $rc); no report written." >&2
  fi
fi
echo "TEARDOWN (owed): terminate the A10 when done."
