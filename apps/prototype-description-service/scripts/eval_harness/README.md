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
# Shipped golden is roster_only (34/37 unboxed claims) → score ends in exit 3.
# That is a correct refusal, not a harness bug. Do not add --allow-refused
# unless you explicitly consent to a no-score report (see Exit contract).
uv run python -m scripts.eval_harness.cli run

# smoke: 3 images (same exit-3 contract on the default golden)
uv run python -m scripts.eval_harness.cli run --limit 3

# offline re-score of a recorded run (deterministic; bit-identical check).
# Same exit 3 against the shipped golden. Reports are still written on exit 3.
uv run python -m scripts.eval_harness.cli score --run-record scripts/eval_harness/out/run-<stamp>.json --check-determinism
```

## Exit contract (`score` / `run`)

`python -m scripts.eval_harness.cli score|run` exits:

| Exit | Meaning |
| --- | --- |
| **0** | Clean score, or refused metrics **with** `--allow-refused` |
| **1** | Partial corpus (`failed>0`), determinism failure, `ManifestError`/`ReportError`, env failures |
| **2** | argparse |
| **3** | Detection and/or identification **REFUSED** and no `--allow-refused` |

Partial is checked before refusal, so partial+refused exits **1**. `score-face` has no `--allow-refused` and never exits 3.

### What REFUSED means

A REFUSED metric means the scorer could not compute it honestly:

- **Detection** — `annotation_mode=roster_only` (the labelled face count is only a lower bound, so detection P/R would overstate), or the mode is missing/unrecognised.
- **Identification** — identity claims with no per-face box lineage (`identification_refuses_unboxed_identity_claims`).

Refusal is a **correct outcome**, not a failure to paper over. Exit 3 exists so a refusal cannot be mistaken for a clean score.

The shipped default manifest (`scene/tests/seed/golden.json`) is `roster_only` with 34/37 unboxed claims, so every `score`/`run` against it exits 3 unless the caller consents.

### What the operator should do

1. **Add per-face boxes** (and set `annotation_mode=exhaustive` only when every face is boxed) so detection P/R and boxed identification can be computed honestly; or
2. **Consent explicitly** with `--allow-refused` if you want the caption report and accept that `faces.detection` / `faces.identification` carry `refused: true` and null numbers. State why at the call site — do not hide the flag in a wrapper.

`--allow-refused` does not invent numbers. It only changes the process exit from 3 to 0.

`--allow-refused` help text (from `score --help`):

```
--allow-refused       exit 0 when detection or identification is REFUSED
                      (roster_only / unboxed identity claims). Default:
                      refused metrics exit 3 — a missing score is not
                      clean evaluation evidence
```

### Worked offline example (no live tenant)

Copy a committed run-record out of tree so `score` does not write reports next to published artifacts:

```bash
cd apps/prototype-description-service
mkdir -p /tmp/acx-eval-score
cp ../../docs/tasks/vlm/VLM-2A-baseline-20260706-run-record.json /tmp/acx-eval-score/run.json
uv run python -m scripts.eval_harness.cli score \
  --run-record /tmp/acx-eval-score/run.json \
  --manifest scene/tests/seed/golden.json
# expected: exit 3; report written at /tmp/acx-eval-score/run-report.{json,md}
```

To accept the refused report (still no detection/identification numbers):

```bash
uv run python -m scripts.eval_harness.cli score \
  --run-record /tmp/acx-eval-score/run.json \
  --manifest scene/tests/seed/golden.json \
  --allow-refused
# expected: exit 0; same refused JSON, different process status
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

# Harness side: same live gates as § Setup (eval tenant — NEVER the demo tenant),
# plus image + spend caps. --cost-per-image is the provider's published price.
export ACX_EVAL_LIVE=1
uv run python -m scripts.eval_harness.cli run \
  --provider hosted_gpt4o --limit 10 \
  --cost-per-image 0.01 --max-cost 1.00
```

- `--provider` names the hosted profile **the target service is serving** — the
  flag cannot switch the server profile (that is fixed by
  `ACX_DESCRIPTION_ADAPTER` on the service). The harness verifies each
  response's `provider_disclosure` and aborts (`ProviderMismatchError`) rather
  than stamping mislabeled evidence. It repeats for a matrix (one
  `run-<stamp>-<provider>.json` record + reports per value), but each matrix
  leg requires re-exporting `ACX_DESCRIPTION_ADAPTER` and restarting the
  service between invocations.
- `--max-cost` caps the **whole invocation** (all matrix legs combined,
  requires `--cost-per-image`): it aborts **before** the paid call that would
  exceed the cap and saves the partial record (`*-aborted.json`) — capped runs
  stay scoreable.
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

**Rubric caveat:** `scene/tests/seed/golden.json` now carries Must-Right /
Easy-Wrong rows (the committed VLM-2A baseline reports
`must_right_defined_images: 37`). A corpus with empty rubrics still
emits `RubricEmptyWarning` and surfaces `must_right_defined_images: 0`;
that is no longer the state of the golden used by the published VLM-2A
baseline.

## Failure semantics (rg-007)

Per-image failures are recorded and the run continues; `--stall-limit`
(default 5) consecutive failures aborts non-zero. The HTTP client adds a
3-strike circuit breaker and bounded job polling.

## LLM-judge tier

`--llm-judge` is a stub flag only (fails fast). Tiers 3–4 of §6c are out of
this MVP.

## Face bake-off (FIR-5)

Offline face identity bake-off: candidate YuNet+SFace (and optional buffalo
reference under a hard env guard) detect→align→embed, then a pure score phase
that proposes (never decides) FIR-6 gate numbers.

### Env guards

| Variable | Purpose |
| --- | --- |
| `ACX_EVAL_BENCH=1` | Required to import `buffalo_bench` (insightface). Unset/0 → import raises. |
| `GOLDEN_IMAGES_DIR` | Local image bytes for the offline walker. |

**No-tenant rule:** never seed buffalo or write face embeddings into tenant
`4ddf8f36` (or any tenant). Face walk writes JSON only under
`scripts/eval_harness/out/` (git-ignored).

**Buffalo non-promotion (PROV-01):** buffalo 512D run-records stay in `out/`.
Never promote them to `docs/tasks/**` or commit them. Only candidate (128D)
records and publishability-filtered aggregate reports may be promoted.

### Commands

```bash
cd apps/prototype-description-service

# offline walk (candidate leg) → face run-record
uv run python -m scripts.eval_harness.cli face-bakeoff --limit 10

# pure score (full unfiltered corpus; unknown-rejection keeps private strangers)
uv run python -m scripts.eval_harness.cli score-face \
  --run-record scripts/eval_harness/out/face-run-<stamp>.json \
  --check-determinism

# published artifact: score full corpus, THEN post-score redact
uv run python -m scripts.eval_harness.cli score-face \
  --run-record scripts/eval_harness/out/face-run-<stamp>.json --public
```

`--check-determinism` on `score-face` re-runs §C–§F in a **fresh process** under
varied `PYTHONHASHSEED` and asserts bit-identical JSON/MD (sorted nested lists).

### Floor + demotion policy

Every gating slice below its n-floor is **DIRECTIONAL ONLY** and barred from the
gate-proposal section (including headline identification). FIR-5 cannot
self-promote an under-floor slice. **Demotion authority is the human operator at
the FIR-6 gate** — FIR-5 only marks `UNDER-FLOOR / DIRECTIONAL — awaiting
operator demotion` and excludes those slices from the proposal.

Floors (recall-eligible celebs01 n≥100; unknown-rejection n≥43; occlusion
eligible pairs ≥90; clustering `P_same≥20 ∧ P_diff≥20` and `M≠0`).

### Perf leg

`perf_leg.py` measures **detect+embed-only** throughput (images/sec,
embeddings/sec, sec/image) + cost/1k from
`perf_budgets/face_bakeoff_budget.json` (A1.Flex ~$0.152/hr; A10 ~$2/GPU-hr
placeholders). **Not** full-scan p95 (FIR-6-owned). A10 eval numbers defer to
`FIR-5a` when no co-scheduled window (not FIR-7).

### VLM-6 low-light curation mapping (S1 carryover)

Operator/curation mapping: VLM-6 **"low-light"** → tag `blur` and/or `low_res`.
This is a **curation-time tag choice**, not a loader transform of
`Domain.LOW_LIGHT` (Domain stays a content stratum for strata shortlists).

### Two-stage publishability

1. **Score** the full unfiltered corpus (keeps LOCALWP/OPERATOR strangers for
   the unknown-rejection gate).
2. **Redact** via `redact_face_report_for_public(report)` for published
   artifacts — strips private crops/metadata, preserves aggregate rates.
   Distinct from the caption path's pre-score `_filter_for_public_audience` /
   `Audience.PUBLIC`.

