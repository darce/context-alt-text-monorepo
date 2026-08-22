# Superseded caption-quality reports

Pre-L3 / pre-PRIV-1 caption figures are **not Δ-comparable** to the current
20-image held-out split (`golden.json` after `8b93c473`). They stay on disk
for provenance. Do not cite them as current evidence.

Superseding commit: `0d50d98f2cc6ad1e14409aba67461a109495e38d`
(L6-baseline / EVAL-01 / P1-5(a)).

Frozen S2A artifacts must not be rewritten. This sidecar carries the status
that must not be pasted into a `_FROZEN_DIGESTS` pin.

## In this directory

| Report | Why superseded |
| --- | --- |
| `S2A-determinism-anchor-run-20260811-report.md` | Frozen determinism-anchor report. Caption figures scored on the pre-L3 39-image freeze corpus (golden + trap media), not the current 20-image held-out split. SHA-256 is pinned in `scene/tests/test_eval_harness_determinism_anchor.py` `_FROZEN_DIGESTS`; the file bytes are the parent freeze. |
| `S0-determinism-anchor-report-20260714.md` | Earlier S0 caption freeze. Pre-L3 corpus / pre-PRIV-1 roster spelling. Not in `_FROZEN_DIGESTS`. |

## Bannered elsewhere (not in `_FROZEN_DIGESTS`)

These 18 files were also marked superseded by `0d50d98f`. None appear in
either caption or face `_FROZEN_DIGESTS`. This lane's allowlist cannot edit
them; their in-file banners remain.

- `docs/tasks/20.0/E20-FUSION-adhoc-report.md`
- `docs/tasks/20.0/E20-FUSION-staged-report.md`
- `docs/tasks/altq/bakeoff-results/run-altq-646-interleave-v3-report.md`
- `docs/tasks/altq/bakeoff-results/run-altq-dual_length-context_distractor-report.md`
- `docs/tasks/altq/bakeoff-results/run-altq-dual_length-standard-report.md`
- `docs/tasks/altq/bakeoff-results/run-altq-two_pass-context_distractor-report.md`
- `docs/tasks/altq/bakeoff-results/run-altq-two_pass-standard-report.md`
- `docs/tasks/altq/bakeoff-results/run-altq-v1-context_distractor-report.md`
- `docs/tasks/altq/bakeoff-results/run-altq-v1-name_ablation-report.md`
- `docs/tasks/altq/bakeoff-results/run-altq-v1-standard-report.md`
- `docs/tasks/altq/bakeoff-results/run-altq-v2-context_distractor-report.md`
- `docs/tasks/altq/bakeoff-results/run-altq-v2-name_ablation-report.md`
- `docs/tasks/altq/bakeoff-results/run-altq-v2-standard-report.md`
- `docs/tasks/vlm/VLM-2A-baseline-20260706-report.md`
- `docs/tasks/vlm/VLM-2B-bakeoff-CapRL-Qwen3VL-4B-report.md`
- `docs/tasks/vlm/VLM-2B-bakeoff-MiniCPM-V-4.5-report.md`
- `docs/tasks/vlm/VLM-2B-bakeoff-Qwen3-VL-4B-Instruct-report.md`
- `docs/tasks/vlm/VLM-2C-seeded-stub-score-20260707-report.md`
