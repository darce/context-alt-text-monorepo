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
# Requires llama.cpp >= b6887 on the box (Qwen3-VL vision). A wrong URL or an
# unsupported-vision build fails that model loudly; the loop continues to the next.
set -uo pipefail

PRIV_IP="${1:?usage: a10-multimodel-bakeoff.sh <A10_PRIVATE_IP>}"
PORT=8000
JUMP=$(grep -h "^REMOTE_GATE_HOST=" "$HOME/Development/context-alt-text-monorepo/.workbay/remote-gate.env" | cut -d= -f2- | tr -d '"'"'"' ' | sed 's/#.*//')
SVC="$HOME/Development/context-alt-text-monorepo-altq-1/apps/prototype-description-service"
PY="$HOME/.pyenv/versions/description-service/bin/python"
MANIFEST="scripts/eval_harness/bakeoff10-manifest-20260716.json"
export GOLDEN_IMAGES_DIR="/Volumes/Butter/WP/vlm/app/public/wp-content/uploads"
SSHJ=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=12 -J "$JUMP" ubuntu@"$PRIV_IP")

# label | gguf_url | mmproj_url | model_id | quant   (VERIFY URLs before running)
MODELS=(
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
      --prompt-variant v3 --two-pass --out "out/run-bakeoff-$label.json" ) \
    && echo "  $label done -> out/run-bakeoff-$label.json" || echo "  $label fetch FAILED"
  pkill -f "ssh -f -N .* -L $PORT:localhost:8000" 2>/dev/null
done

echo "== build the comparison report =="
RUNS=(--run "Qwen3-VL-30B (control)=out/run-altq-646-interleave-v3.json")
for spec in "${MODELS[@]}"; do
  IFS='|' read -r label _ _ _ _ <<<"$spec"
  [ -f "$SVC/out/run-bakeoff-$label.json" ] && RUNS+=(--run "$label=out/run-bakeoff-$label.json")
done
( cd "$SVC" && "$PY" -m scripts.eval_harness.build_bakeoff_report \
    --manifest "$MANIFEST" --images-dir "$GOLDEN_IMAGES_DIR" \
    --media-ids 93,154,200,46,62,98,6,11,400,378 --embed-images \
    "${RUNS[@]}" --title "10-image multi-model bake-off" \
    --out "$HOME/Development/context-alt-text-monorepo-altq-1/docs/tasks/altq/bakeoff-results/reports/bakeoff-10img-multimodel.html" )
echo "report -> docs/tasks/altq/bakeoff-results/reports/bakeoff-10img-multimodel.html"
echo "TEARDOWN (owed): terminate the A10 when done."
