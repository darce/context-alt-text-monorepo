# Caption + Face Eval Harness (VLM-2A)

Scores generated image descriptions (deterministic tier, assessment §6c tiers
1–2, 5–6) and face-recognition P/R (detection + identification, micro +
per-identity macro) against the 38-image golden manifest. Runs on the laptop;
**all inference happens on the remote OCI service** (concurrency 1).

## Setup

```bash
# 1. Fixtures (59 MB, not vendored): see scene/tests/seed/README.md
export GOLDEN_IMAGES_DIR=~/Development/eval-fixtures

# 2. Dedicated eval tenant — NEVER the demo tenant. Mint via /admin console.
export ACX_EVAL_LIVE=1                    # safety gate for live subcommands
export ACX_EVAL_BASE_URL=https://api.altcontext.com
export ACX_EVAL_API_KEY=<eval-tenant key>
export ACX_EVAL_TENANT_ID=<eval tenant UUID>   # required by ALL live subcommands (fetch/run/seed-roster)
```

## Usage

```bash
cd apps/prototype-description-service   # load-bearing: repo root has a different scripts/

# one-time: seed the eval tenant (idempotent — safe to re-run)
uv run python -m scripts.eval_harness.cli seed-roster --entities "$GOLDEN_IMAGES_DIR/mock_entities"

# full run (fetch + score); or from repo root: make eval-captions
uv run python -m scripts.eval_harness.cli run

# smoke: 3 images
uv run python -m scripts.eval_harness.cli run --limit 3

# offline re-score of a recorded run (deterministic; bit-identical check)
uv run python -m scripts.eval_harness.cli score --run-record scripts/eval_harness/out/run-<stamp>.json --check-determinism
```

## Hosted provider matrix (E20-11)

> **Governance: disposition `reject`** — the product uses only self-hosted CPU
> models, so this path is dormant: no deployment sets the opt-in env or holds a
> provider key. The capability is documented for any future epic-level
> re-evaluation (see `docs/tasks/20.0/E20-11-hosted-provider-decision-memo.md`).

Benchmarks hosted description providers (image bytes **leave the service
boundary**) over the same golden corpus. Opt-in, fail-closed, and paid — every
gate below is deliberate.

```bash
# Service side (eval instance only): hosted profile + explicit opt-in + provider key
export ACX_DESCRIPTION_ADAPTER=hosted_gpt4o
export ACX_HOSTED_PROVIDER_OPTIN=1          # without this the profile fail-closes (503)
export ACX_HOSTED_PROVIDER_API_KEY=<provider key — server-side only, never in the repo>

# Harness side: same live gates as above (eval tenant — NEVER the demo tenant),
# plus image + spend caps. --cost-per-image is the provider's published price.
uv run python -m scripts.eval_harness.cli run \
  --provider hosted_gpt4o --limit 10 \
  --cost-per-image 0.01 --max-cost 1.00
```

- `--provider` repeats for a matrix; each value writes its own
  `run-<stamp>-<provider>.json` record + reports.
- `--max-cost` aborts **before** the paid call that would exceed the cap and
  saves the partial record (`*-aborted.json`) — capped runs stay scoreable.
- Provider, per-image price, estimated spend, and per-item `latency_s` land in
  the run-record provenance/items; each hosted item's
  `describe.provider_disclosure.left_service_boundary` is `true`.
- Scoring caveat: the MVP corpus ships empty context packs/rubrics, so provider
  comparison is scoped to context-independent caption metrics + latency + cost
  (see the E20-11 decision memo). Insertion/named-entity claims need the
  VLM-2C manifest population first.

## Artifacts and retention

- Run records + reports land in `scripts/eval_harness/out/` (git-ignored),
  pruned keep-last-N (default 10, `--keep`).
- `out/ignore-list.json` (`{"wrong_names": [["<path>", "<name>"], ...]}`)
  suppresses triaged wrong-name false positives across runs; ignored entries
  are still reported under `ignored_wrong_names`. Never pruned.
- Curated baselines are promoted by hand to `docs/tasks/vlm/`.

## Report schema (`acx-eval/v1`, E19-1 extension)

Every eval document carries `schema: acx-eval/v1` plus a `kind` discriminator
(`run_record` for a raw fetch, `report` for a scored report) so the two are never
confused; `score` rejects a report file passed as a run record.

JSON sections: `provenance` (fetch-time `manifest_sha256`, `score_manifest_sha256`
+ `manifest_matches_fetch` flag, base_url, HEAD sha, started_at, and a `model`
block naming the **adapter(s)/model_id(s)/model_version(s)** that produced the
captions), `counts`, `caption` (insertion_rate, Must-Right failed + rubric-defined
images, policy violations, mean gated score), `faces.detection` (count-based P/R
against ground-truth `face_count`), `faces.identification` (micro + macro P/R,
per-identity table, wrong_names listed individually, true_rejections, excluded
policy-disabled images), `per_image`, `failures`. Deterministic sections are
bit-identical across re-scores of the same run record.

**Baseline caveat:** the committed `docs/tasks/vlm/VLM-2A-baseline-*` artifacts were
produced by the model-free `seeded` stub adapter (`adapter=seeded`,
`model_id=seeded-fixtures`) as a harness shakedown — the report's `model` block and
markdown header say so explicitly. They are **not** a caption-model baseline; a
real-model baseline must be captured with a live run before the §12 bake-off gate.

**Rubric caveat (MVP):** the golden corpus currently ships with empty `must_right`
/ `easy_wrong` for every entry, so the Must-Right hard gate and Easy-Wrong rubric
are vacuous. The loader emits a `RubricEmptyWarning` and the report surfaces
`must_right_defined_images: 0`, so this is disclosed, not silent.

## Failure semantics (rg-007)

Per-image failures are recorded and the run continues; `--stall-limit`
(default 5) consecutive failures aborts non-zero. The HTTP client adds a
3-strike circuit breaker and bounded job polling.

## LLM-judge tier

`--llm-judge` is a stub flag only (fails fast). Tiers 3–4 of §6c are out of
this MVP.
