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

# offline re-score of a recorded run (report write + score gates)
uv run python -m scripts.eval_harness.cli score \
  --run-record scripts/eval_harness/out/run-<stamp>.json

# optional: cross-process determinism certification (score / run / score-face only)
# Requires a run-record whose identities are dict rows and whose
# provenance.manifest_sha256 matches the score-time manifest. The S2A seeded
# determinism anchor (bakeoff-results/) is the committed green path — see
# § Score gates below. Legacy curated baselines still fail on bare-string identities.
uv run python -m scripts.eval_harness.cli score \
  --manifest scene/tests/seed/golden.json \
  --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json \
  --rubric-gate skip \
  --check-determinism
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

## Score gates, verdict, and `--check-determinism`

Operator reference for `score` exit semantics (VLM-6 S2A). Read a red line by
its **prefix** — the prefix names the corruption class and selects the remedy
(**OBS-04**).

### Where `--check-determinism` is allowed

| Subcommand | Flag | Behaviour |
| --- | --- | --- |
| `score` | yes | Spawns child interpreters; certifies the exact `rubric_gate` + `audience` documents that are written (`score` / `score-public` labels). |
| `run` | yes | Per-leg certification (each provider matrix record). **Announces** `legs × seeds` (and `× 2 audiences` when `--audience public`) **before** paid fetch / first child spawn. |
| `score-face` | yes | Same cross-process guard over face score documents. |
| `fetch` (and others) | **no** | Argparse rejection: `unrecognized arguments: --check-determinism` (exit 2). Not a silent no-op. |

### Empirically verified commands (do not invent paths)

**Broken — committed baselines (exit 1).** Both curated run-records still carry
bare-string `identities` lists; greenfield scoring rejects them before any gate
fires:

```text
$ cd apps/prototype-description-service
$ uv run --extra dev python -m scripts.eval_harness.cli score \
    --run-record ../../docs/tasks/vlm/VLM-2C-seeded-stub-run-record-20260707.json \
    --check-determinism
ReportError: items[0].identities[0] must be a dict identity row (keys include 'name'); got str — greenfield rejects bare-string identity lists
# EXIT_CODE:1

$ uv run --extra dev python -m scripts.eval_harness.cli score \
    --run-record ../../docs/tasks/vlm/VLM-2A-baseline-20260706-run-record.json \
    --check-determinism
ReportError: items[2].identities[0] must be a dict identity row (keys include 'name'); got str — greenfield rejects bare-string identity lists
# EXIT_CODE:1
```

Those legacy records remain archival (pre-greenfield bare-string identities).
Do not re-stamp their `provenance.manifest_sha256` to force a green gate
(rg-015). The load-bearing re-scorable anchor is the S2A seeded artifact below
(regenerate via `python -m scripts.eval_harness.generate_determinism_anchor`).

**Working — committed S2A determinism anchor (exit 0).** Offline seeded stub over
the full golden corpus (37 items); dict identity rows; `provenance.manifest_sha256`
computed at generation time (`859a083e…`). Seeded-stub scoring requires
`--rubric-gate skip` (vacuity exemption → `verdict=pass_ungated`).

```text
$ cd apps/prototype-description-service
$ uv run --extra dev python -m scripts.eval_harness.cli score \
    --manifest scene/tests/seed/golden.json \
    --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json \
    --rubric-gate skip \
    --check-determinism
determinism check passed [score]: cross-process re-score is bit-identical under varied PYTHONHASHSEED (baseline=randomized; child_seeds=0,1,42)
../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.md
scored=37/37 insertion_rate=0.0 wrong_names=0 verdict=pass_ungated wrong_name_rate=0.0 wrong_name_rate_floor=0.0 rubric_gate=skip
# EXIT_CODE:0
```

Frozen triple (run-record + report JSON + report MD) lives under
`docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811*`. The
`.json` report is the machine-diffable artifact for a future digest gate (B-06).

**Working — suite evidence path (exit 0):**

```text
$ cd apps/prototype-description-service
$ uv run --extra dev pytest scene/tests/test_eval_harness_cli.py \
    -k score_check_determinism_runs_cross_process -q
.                                                                        [100%]
1 passed, 94 deselected in 7.24s
```

**`fetch` free-reject (exit 2):**

```text
$ uv run --extra dev python -m scripts.eval_harness.cli fetch --check-determinism
usage: eval_harness [-h]
                    {fetch,score,run,seed-roster,seed-scenes,face-bakeoff,score-face}
                    ...
eval_harness: error: unrecognized arguments: --check-determinism
# EXIT_CODE:2
```

**`run` cost announcement (before live gate / first child):**

```text
run --check-determinism: per-leg certification — 1 legs × 3 seeds = 3 fresh interpreter(s) before scoring completes
```

### `verdict` in the report JSON

`score` builds `result["verdict"]` **before** any exit gate fires and writes the
JSON report **before** non-zero exits. A red run still leaves a truthful artifact
on disk (`*-report.json`). Fields:

| Field | Meaning |
| --- | --- |
| `verdict` | `pass` \| `fail` \| `pass_ungated` (`pass_ungated` only when `--rubric-gate skip` and no other reasons). |
| `reasons` | Machine-readable list of every condition that would force a non-zero exit (failed-items, truncation, manifest-mismatch, empty-rubric, must-right failures, wrong-name floor / vacuity, schema hard-key errors). |
| `wrong_name_rate` / `wrong_name_rate_floor` | Display rate (rounded) + floor constant; gate decisions use count / unrounded rate, not the rounded display. |
| `rubric_gate` | Operator-declared mode stamped into the artifact (`enforce` \| `skip`). |
| `insertion_rate`, `mean_gated_score`, `must_right_failed_images` | Reported metrics mirrored for operator triage. |

Stdout always prints a one-line summary including `verdict=…` and
`rubric_gate=…` before any `sys.exit`.

### Score non-zero exit prefixes

Content gates fire **after** the report is on disk. Prefixes are class-unique:

| Gate / class | Exit message prefix | When it fires |
| --- | --- | --- |
| schema hard-key | `score schema error:` | Required dotted path missing or wrong type (`provenance.manifest_matches_fetch`, `caption.must_right_failed_images`, `verdict.wrong_name_rate`). Folded into `verdict.reasons` before write. |
| failed-items | `score failed-items gate:` | `counts.failed > 0` — partial corpus must not look like full-corpus evidence. |
| truncation | `score truncation gate:` | Run-record media-id multiset differs from score-time manifest (`corpus.media_id_missing` / `media_id_extra`). |
| manifest-mismatch | `score manifest-mismatch gate:` | Run-record provenance missing fetch-time `manifest_sha256` (record not self-consistent). **Not** a hard fail on score-time file sha vs fetch-time sha (that flag stays informational). |
| empty-rubric | `score empty-rubric gate:` | `must_right_defined_images == 0` **or** `easy_wrong_defined_images == 0` (independent; either vacuity fails closed). |
| must-right failures | `score must-right failures gate:` | `--rubric-gate enforce` (default) and `must_right_failed_images > 0`. Bypass only via explicit `--rubric-gate skip` (artifact says `pass_ungated`). |
| wrong-name floor vacuity | `score wrong-name floor vacuity gate:` | Images scored but `identification.evaluated_images == 0` (floor would be vacuous). |
| wrong-name floor | `score wrong-name floor gate:` | Wrong-name floor breached (count when floor is 0.0; unrounded rate otherwise). Ignore-list pairs still count toward the rate. |

The original S2A “five named gates” are failed-items, manifest-mismatch,
empty-rubric, must-right failures, and wrong-name floor; truncation, vacuity, and
schema hard-keys are additional class-unique exits on the same path.

Pre-gate hard failures (no report write for that invocation):

| Class | Example | Remedy |
| --- | --- | --- |
| identity shape | `ReportError: … identities[…] must be a dict identity row … got str` | Re-fetch or migrate run-record identity rows (code/record lane). |
| missing args | argparse exit 2 (`--run-record` required) | Pass a real run-record path. |
| missing file | `FileNotFoundError` on `--run-record` | Point at an existing record. |

### Determinism guard: ERROR vs FAILED vs pass (**OBS-04**)

Pass and red lines name the `PYTHONHASHSEED` regime:

| Line shape | Meaning | Operator action |
| --- | --- | --- |
| `determinism check passed [label]: … (baseline=…; child_seeds=…)` | Cross-process re-score bit-identical under the named child seeds. | None — certified. |
| `determinism check ERROR [label]: …` | Child could not run, timed out, payload missing/unreadable/unparseable, or bound a different `build_reports` module than the parent (**environment / import drift**). | Fix environment / import root / PYTHONPATH; re-run. **Not** a caption-model regression. |
| `determinism check FAILED [label]: …` | Genuine byte mismatch across seeds (**build regression**). Writes `determinism-mismatch-<label>-seed<n>.diff.txt` under the artifact dir; artifact carries the same `baseline=…; child_seeds=…` regime. | Investigate scoring code / non-determinism in the build. |

`label` is `score`, `score-public`, or `score-face` so CI logs name which document failed.

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

