# Caption + Face Eval Harness (VLM-2A)

Scores generated image descriptions (deterministic tier, assessment §6c tiers
1–2, 5–6) and face-recognition P/R (detection + identification, micro +
per-identity macro) against the 37-image golden manifest (media_ids 1–38 with
media_id 22 absent). Runs on the laptop; **all inference happens on the remote
OCI service** (concurrency 1).

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

# full run (fetch + score + seed-stability); or from repo root: make eval-captions
# (make eval-captions passes --check-determinism by default)
# Shipped golden is roster_only (34/37 unboxed claims) -> score ends in exit 3.
# That is a correct refusal, not a harness bug. Do not add --allow-refused
# unless you explicitly consent to a no-score report (see Exit contract below).
uv run python -m scripts.eval_harness.cli run --check-determinism

# smoke: 3 images
uv run python -m scripts.eval_harness.cli run --limit 3 --check-determinism

# offline re-score of a recorded run (report write + score gates)
uv run python -m scripts.eval_harness.cli score \
  --run-record scripts/eval_harness/out/run-<stamp>.json

# operator surface for the committed freeze (byte-stability certification):
# monorepo-root `make eval-anchor-check` is the intended one-shot target and
# runs both legs (caption + face) against the committed freeze manifests
# below. The CLI invocation shown here is what that target runs for the
# caption leg; use it directly only when iterating outside `make`.
#
# Caption freeze corpus (wG3): bakeoff-results man = golden seed + media 39 trap.
# golden.json stays the 37-entry shared seed (0/37 face_boxes); score-time man
# for the freeze is the dedicated caption-anchor manifest, not bare golden.
# --freeze-certification: exit code means scoring-path byte-stability after
# measurement-integrity gates (aborted / failed-items / zero-scored / truncation /
# manifest / schema). Adoption gates stay printed (verdict / wrong_name_rate)
# but do not set the exit status.
uv run --extra dev python -m scripts.eval_harness.cli score \
  --manifest ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-manifest-20260811.json \
  --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json \
  --check-determinism \
  --expect-report ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.json \
  --rubric-gate skip \
  --freeze-certification
# --rubric-gate skip is freeze stamp parity (artifact carries rubric_gate=skip),
# not an adoption softener under --freeze-certification.
```

## Exit contract (`score` / `run`)

`python -m scripts.eval_harness.cli score|run` exits:

| Exit | Meaning |
| --- | --- |
| **0** | Clean score, or refused metrics **with** `--allow-refused` |
| **1** | Partial corpus (`failed>0`), determinism failure, `ManifestError`/`ReportError`, env failures |
| **2** | argparse |
| **3** | Detection and/or identification **REFUSED** and no `--allow-refused` |

Partial is checked before refusal, so partial+refused exits **1**. `score-face` accepts `--allow-refused [METRIC]` (repeatable; bare form = all); unconsented refused identification/detection exits 3 (S2R5-02); partial still wins with exit 1. Pin: `test_score_face_exits_3_on_refused_identification`.

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

`--allow-refused` help text (from `score-face --help`; same flag on `score --help`):

```
  --allow-refused [METRIC]
                        exit 0 for the named refused metric. Repeatable
                        (--allow-refused=detection --allow-
                        refused=identification). Bare --allow-refused is
                        equivalent to naming every metric (detection,
                        identification). Default: refused metrics exit 3 — a
                        missing score is not clean evaluation evidence
```

### Worked offline example (no live tenant)

Copy a committed run-record out of tree so `score` does not write reports next to published artifacts:

```bash
cd apps/prototype-description-service
WORK=$(mktemp -d)
cp ../../docs/tasks/vlm/VLM-2A-baseline-20260706-run-record.json "$WORK/run.json"
uv run python -m scripts.eval_harness.cli score \
  --run-record "$WORK/run.json" \
  --manifest scene/tests/seed/golden.json
# expected: exit 3; report written at $WORK/run-report.{json,md}
```

To accept the refused report (still no detection/identification numbers):

```bash
uv run python -m scripts.eval_harness.cli score \
  --run-record "$WORK/run.json" \
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
- Scoring caveat: `scene/tests/seed/golden.json` carries Must-Right /
  Easy-Wrong rows on all 37 images (`must_right_defined_images: 37`). Hosted
  comparison can therefore include insertion/named-entity claims against
  those rubrics, plus latency + cost (see the E20-11 decision memo). A
  corpus that still ships empty rubrics emits `RubricEmptyWarning` and
  `must_right_defined_images: 0`; that is not the state of the golden.

## Artifacts and retention

- Run records + reports land in `scripts/eval_harness/out/` (git-ignored),
  pruned keep-last-N (default 10, `--keep`).
- `out/ignore-list.json` (`{"wrong_names": [["<path>", "<name>"], ...]}`)
  suppresses triaged wrong-name false positives across runs; ignored entries
  are still reported under `ignored_wrong_names`. Never pruned.
- Curated baselines are promoted by hand to `docs/tasks/vlm/`.

## Corpus coverage boundary — what a green gate does *not* prove

Every gate below scores only what the corpus authored. Where the corpus is
silent the metric is **undefined** (`None` / `not_ready` / listed under
`provenance.coverage_gaps`) — it must not be read as a clean pass. Read this
section before quoting any number from a green determinism run as quality
evidence (VLM6-R2-03 / VLM6-GATE-04 / VLM6-S2A-F6-02).

Two caption corpora must not be confused (wG3 / rg-006):

| Corpus | Path | Role |
| --- | --- | --- |
| **Golden seed** | `scene/tests/seed/golden.json` | Shared 37-entry fixture for live `run`/`fetch`/`score` defaults and non-freeze tests. Untouched by the freeze generator. |
| **Caption freeze man** | `docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-manifest-20260811.json` | Score-time man for the committed determinism freeze: golden seed **+ media 39** mixed-y trap so `labeled_y_missing_images` can leave structural 0. Pair with the freeze run-record under the same stem. |

**Golden seed** (`scene/tests/seed/golden.json`) — inventory as shipped:

| Field | Populated | What its absence disables |
| --- | --- | --- |
| entries | **37** | the plan named a stratified Golden-100; this is 37 |
| `difficulty` | 37/37 (easy 16 / medium 10 / hard 11) | — |
| `domain` | 37/37 | thin tails: `low_light` n=1, `mirrors` n=2, `art` n=2, `occlusion` n=3 — per-stratum floors (VLM6-R4-05) are noise at those n |
| `present_identities` | 34/37 | identity scoring on the other 3 |
| `must_right` | 34/37 | the caption hard gate |
| `easy_wrong` | 37/37 | — |
| `tags` | 7/37 | tag-scoped slicing |
| `face_boxes` | **0/37** | `labeled_order_known` is false everywhere, so `positional_identification` **never runs** |
| `spatial_facts` | **0/37** | placement accuracy is **vacuous** (0 asserted claims) |
| `reference_facts` | **0/37** | fabricated-fact rate is **undefined** (`None`) — no trap coverage (EVAL-19) |
| `demographic_cohort` | **0/37** | cohort fairness slices have no sampling frame (owner=FIR-5) |

**Caption freeze man** (bakeoff-results; generated by
`python -m scripts.eval_harness.generate_determinism_anchor`) extends that seed
with **media 39** (`mock_images/y-missing-mixed-order.jpg`): 38 entries,
`face_boxes` **1/38**, trap disclosed under run-record
`provenance.corpus_traps`. Scoring the freeze against bare golden produces
`manifest-drift` / `scored=37/38` and a false freeze-red that looks like
scoring drift — always pass the freeze man for freeze checks.

The two consequences worth stating outright (golden seed; freeze trap only
partially lifts the first):

- **`wrong_names=0` does not mean names were placed correctly.** Identity
  scoring is set-based (`sorted(set(predicted))` vs `sorted(set(present))`), so
  naming exactly the right people onto exactly the wrong faces scores a clean
  zero. The positional check that would catch it is gated on `face_boxes`;
  golden has none. The freeze trap populates one image so
  `labeled_y_missing_images` is observable — it is not a full positional corpus
  (Slice 2 / VLM6-GATE-04).
- **Placement accuracy is vacuous.** With no `spatial_facts`, `score_placement`
  has nothing to assert against, and the committed caption report says so in
  plain text (`⚠️ placement is VACUOUS`). Even with facts authored, matching is
  near-verbatim: a paraphrase is dropped from the denominator rather than scored
  wrong, so the denominator is published beside the number (VLM6-R4-03). A
  validated-judge scorer is EVAL-11.

**Face freeze** (`docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811.json`)
is a *byte-stability* anchor, not a recognition-quality result: synthetic
`dim=8` unit vectors over a dedicated face man (not golden), no real image or
embedding ever computed (PROV-01). It proves the scoring path is deterministic
and that corruption goes red. It proves nothing about recognition accuracy on
photographs. Its own `provenance.coverage_gaps` names the regimes it does not
reach (`failures`, `occlusion.occlusion_other`, `occlusion.sunglasses`).

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

**Working — committed S2A determinism anchor (under `--freeze-certification`).**
Offline seeded stub over the **caption freeze corpus** (38 items = golden-37 +
media 39 trap); score with the bakeoff-results caption man, **not** bare
`golden.json`. Dict identity rows; `provenance.manifest_sha256` computed at
generation time (read it from the artifact — do not hardcode the digest here;
it moves whenever the generator or freeze man changes). Face and identity
predictions in the freeze are **ground-truth-derived fixtures** with a fixed
seeded deviation (`predictions_source=ground_truth_derived_fixture`,
`face_metrics_evidential=false`) — they prove scoring-path byte-stability, not
recognition quality. The fixture deliberately carries wrong-name deviations and
vacuous categories (`verdict=fail`, `fabricated_fact_rate=None`) so the freeze
is not a 1.000 tautology. Live re-score may still ANCHOR_MISMATCH while the
committed report JSON lags a regen stage — that is report-byte staleness, not
a reason to re-point `--manifest` at golden.

**Two contracts, two modes** (fx8 / gx1):

| Mode | Flags | Exit code means |
| --- | --- | --- |
| Live adoption scoring | `score` (default) | Full surface: integrity **and** adoption (wrong-name floor, category vacuity, must-right, …) (EVAL-04 / EVAL-23). |
| Freeze byte-stability | `score --check-determinism --expect-report PATH --freeze-certification` | Scoring-path byte-stability **after** measurement-integrity gates. Integrity (aborted / failed-items / zero-scored / truncation / manifest-mismatch / schema) still sets exit status. Adoption outcomes are still **printed** (`verdict=…`, rates) but do **not** set exit status. |

`--freeze-certification` **requires** `--expect-report` (and therefore
`--check-determinism`). Without an external freeze the flag would silently skip
adoption gates with nothing left to certify (rejected). It does **not** skip
integrity gates — byte-stability of a measurement that did not run is not a
certification (gx1 / S1-01).

Seed-stability alone (`--check-determinism` without a freeze) proves the scorer
is hash-stable; it does **not** detect a corrupted run-record or report (parent
and children all read the same file), and it does **not** catch a schema or
manifest edit that still re-scores consistently. Use **`--expect-report`** for
the third outcome against the committed freeze (F5 / B-06) — opt-in path, no
sibling filename inference. Preferred one-shot is monorepo-root
`make eval-anchor-check`, which runs both legs (caption + face) against the
committed freeze manifests. The explicit CLI below is the caption leg it runs
— use it directly only when iterating outside `make`.

```text
$ cd apps/prototype-description-service
$ uv run --extra dev python -m scripts.eval_harness.cli score \
    --manifest ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-manifest-20260811.json \
    --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json \
    --check-determinism \
    --expect-report ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.json \
    --rubric-gate skip \
    --freeze-certification
# When freeze report digests match live re-score:
determinism check passed [score]: cross-process re-score is bit-identical under varied PYTHONHASHSEED (baseline=randomized; child_seeds=0,1,42); matches --expect-report …/S2A-determinism-anchor-run-20260811-report.json
…/S2A-determinism-anchor-run-20260811-report.md
scored=38/38 … wrong_names=4 verdict=fail wrong_name_rate=0.1053 …
freeze-certification passed [score]: scoring-path is byte-stable (matches --expect-report); nothing certified about model quality, face recognition, or adoption readiness (artifact verdict=fail; integrity gates enforced above; adoption gates … not exit-determining)
# EXIT_CODE:0
# Note: EXIT 0 under --freeze-certification certifies scoring-path BYTE-STABILITY
# after integrity gates pass. The printed verdict=fail / wrong_name_rate are
# adoption signals, not exit-determining here. An aborted / truncated / schema-
# invalid record still exits non-zero under this flag (gx1). Face P/R and
# fabricated-fact numbers in the freeze are non-evidential / may be undefined
# (see provenance.coverage_gaps).
# --rubric-gate skip matches the freeze stamp (rubric_gate=skip); it is not what
# makes exit 0 — drop --freeze-certification and the wrong-name floor exits 1
# (live adoption path stays hard — sr-001).
# Do NOT pass --manifest scene/tests/seed/golden.json for this check: golden is
# the 37-entry seed (sha 83bfdc4e…); the freeze run was fetched under the
# caption man (sha 7462d325…). Golden → manifest-drift + scored=37/38 and a
# false ANCHOR_MISMATCH that looks like scoring regression.
```

Frozen set (caption man + run-record + report JSON + report MD) lives under
`docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-*`. The `.json` report is
the machine-diffable `--expect-report` artifact (B-06). Regenerate via
`python -m scripts.eval_harness.generate_determinism_anchor` (writes man + run +
reports from golden seed + trap; does not bend `golden.json`).

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
| `verdict` | `pass` \| `fail` \| `pass_ungated` \| `not_ready` \| `non_comparable`. `pass_ungated` only when `--rubric-gate skip` and no other reasons. `not_ready` when a critical scored category has sampling π=0 (category vacuity / undersized sample) — never adoption-eligible. `non_comparable` is archival manifest-relabel only (`--allow-manifest-relabel`); `compare` rejects it. |
| `reasons` | Machine-readable list of every condition that would force a non-zero exit (failed-items, truncation, manifest-mismatch, empty-rubric, must-right failures, wrong-name floor / vacuity, quality-floor breaches on critical slices, category-vacuity / sample-size, schema hard-key errors). |
| `wrong_name_rate` / `wrong_name_rate_floor` | Display rate (rounded) + floor constant; gate decisions use count / unrounded rate, not the rounded display. |
| `rubric_gate` | Operator-declared mode stamped into the artifact (`enforce` \| `skip`). |
| `insertion_rate`, `mean_gated_score`, `must_right_failed_images` | Reported metrics mirrored for operator triage. |

Stdout always prints a one-line summary including `verdict=…` and
`rubric_gate=…` before any `sys.exit`.

### Score non-zero exit prefixes

Content gates fire **after** the report is on disk (refuse-overwrite fires
**before** write; `run` wrappers summarise multi-record score gates). Prefixes
are class-unique module constants in `cli.py` (`SCORE_GATE_PREFIX_*` /
`SCORE_GATE_PREFIXES`). **Caption and face share the same prefix for a given
class** (VLM6-R2-F-03 / rg-015) so one log grep (e.g. `failed-items gate` or
`refuse-overwrite gate`) catches both paths; any face/command-specific token
is a **suffix** field, never a divergent prefix. Drift tests assert **set
equality** between this table and `SCORE_GATE_PREFIXES` (bidirectional —
undocumented constant **or** stale README row fails CI) and lock call sites to
the constants (RE-04).

| Gate / class | Exit message prefix | When it fires | Operator action |
| --- | --- | --- | --- |
| schema hard-key | `score schema error:` | Required dotted path missing or wrong type (`provenance.manifest_matches_fetch`, `caption.must_right_failed_images`, `verdict.wrong_name_rate`). Folded into `verdict.reasons` before write. | Fix report schema / scorer field rename; re-score. |
| aborted-record | `score aborted-record gate:` | Run-record has `aborted=true` (partial evidence). Shared by `score` and `score-face` (face suffix: `score-face:`). | Re-fetch the incomplete run; do not certify partial records. |
| zero-scored | `score zero-scored gate:` | `counts.scored == 0` and no failed-items class applies (empty items only). Shared by caption/face. | Inspect run-record items; re-fetch or fix corpus paths. |
| failed-items | `score failed-items gate:` | `counts.failed > 0` — partial corpus must not look like full-corpus evidence. **Shared by caption and face** (face message includes `score-face:` suffix). | Inspect `failures[]` in the written report; fix remote/NFC errors; re-fetch. |
| truncation | `score truncation gate:` | Run-record media-id multiset differs from score-time manifest (`corpus.media_id_missing` / `media_id_extra`). Caption path. | Score against the same manifest used at fetch, or re-fetch full corpus (not `--limit N` archival stubs). |
| manifest-mismatch | `score manifest-mismatch gate:` | Run-record provenance missing fetch-time `manifest_sha256` (record not self-consistent). **Not** a hard fail on score-time file sha vs fetch-time sha alone. | Re-fetch so the record carries fetch-time provenance. |
| manifest-drift | `score manifest-drift gate:` | Score-time manifest digest ≠ fetch-time digest (`manifest_matches_fetch=false`) and `--allow-manifest-relabel` was **not** set. | Re-score with the fetch-time manifest, or pass `--allow-manifest-relabel` only for archival non-comparable relabel. |
| manifest-relabel | `score manifest-relabel gate:` | Archival path: `--allow-manifest-relabel` produced `verdict=non_comparable`. Exit non-zero so it is never mistaken for adoption-ready. | Treat as archival only; `compare` rejects it. Do not promote. |
| empty-rubric | `score empty-rubric gate:` | `must_right_defined_images == 0` **or** `easy_wrong_defined_images == 0` (independent; either vacuity fails closed). Adoption gate (soft under `--freeze-certification`). | Author Must-Right / Easy-Wrong labels on the golden corpus. |
| must-right failures | `score must-right failures gate:` | `--rubric-gate enforce` (default) and `must_right_failed_images > 0`. Bypass only via explicit `--rubric-gate skip` (artifact says `pass_ungated`). | Fix captions / model; or `--rubric-gate skip` for harness shakedown only. |
| wrong-name floor vacuity | `score wrong-name floor vacuity gate:` | Images scored but `identification.evaluated_images == 0` (floor would be vacuous). | Enable recognition on scored images or fix identification sampling. |
| wrong-name floor | `score wrong-name floor gate:` | Wrong-name floor breached (count when floor is 0.0; unrounded rate otherwise). Ignore-list pairs still count toward the rate. | Remove hallucinated names; triage ignore-list only with documented rationale. |
| category vacuity / not_ready | `score category-vacuity gate:` | Critical scored slice has π=0 (positional, placement, fabricated-fact traps, identity_ordering, detection/ID P/R, caption scalars) or sample size below the score-pass floor — artifact `verdict=not_ready`, never `pass`. | Enlarge / rebalance corpus so critical categories are measurable. |
| quality floor | `score quality-floor gate:` | Measured critical slice is total failure: `position_accuracy` / `placement.accuracy` at the degenerate floor, or `fabricated_fact_rate` at the ceiling. Folded into `verdict=fail` reasons **and** exits non-zero. Distinct from vacuity (`not_ready` = not measured). | Fix model quality on the failing slice; do not adopt. |
| freeze-cert refused | `score freeze-certification refused:` | `--freeze-certification` but a post-cert fold re-serialised the document (certified bytes ≠ written bytes). | Fix schema/evidence/relabel fold ordering; do not stamp a freeze over degraded bytes. |
| face-report readback | `score face-report-readback gate:` | `score-face` only: written face-report JSON cannot be read back or is not an object (serialisation / IO). | Investigate write path / disk; re-run score-face. |
| refuse-overwrite | `score refuse-overwrite gate:` | Pre-write: ordinary `score` / `score-face` would clobber an existing report under the committed bakeoff-results tree without `--allow-overwrite-report`. **Shared by caption and face** — command label (`score:` / `score-face:`) is a **suffix**, never a divergent prefix. | Pass `--allow-overwrite-report` only with intent; freezes must not be rewritten by ordinary score (default writes for freeze run-records go to `OUT_DIR`). |
| run per-record gate | `run score gate failed:` | `run` multi-record wrapper: one fetched record's score gate fired. Record path is **after** the colon (fixed greppable prefix). Underlying score class still appears in the message body. | Inspect the named record and the nested score prefix; fix that record and re-run. |
| run multi-record summary | `run score gates failed:` | `run` finished the loop with ≥1 per-record gate failure; process exits once with a summary. | Triage each `record: <score prefix>…` entry; do not treat a partial multi-record run as green. |

Integrity gates (aborted / zero-scored / failed-items / truncation / manifest-* /
schema / freeze-cert refused / face-report readback) always set exit status,
including under `--freeze-certification`. Adoption gates (empty-rubric /
must-right / wrong-name / quality-floor / category-vacuity) are soft under
`--freeze-certification` and hard otherwise.

The original S2A “five named gates” are failed-items, manifest-mismatch,
empty-rubric, must-right failures, and wrong-name floor; the rest are
additional class-unique exits on the same path.

Pre-gate hard failures (no report write for that invocation):

| Class | Example | Remedy |
| --- | --- | --- |
| identity shape | `ReportError: … identities[…] must be a dict identity row … got str` | Re-fetch or migrate run-record identity rows (code/record lane). |
| missing args | argparse exit 2 (`--run-record` required) | Pass a real run-record path. |
| missing file | `FileNotFoundError` on `--run-record` | Point at an existing record. |

### Determinism guard: ERROR vs FAILED vs ANCHOR_MISMATCH vs pass (**OBS-04**)

Pass and red lines name the `PYTHONHASHSEED` regime. Three red classes select
three remedies — do not treat them as synonyms:

| Line shape | Meaning | Operator action |
| --- | --- | --- |
| `determinism check passed [label]: … (baseline=…; child_seeds=…)` | Cross-process re-score bit-identical under the named child seeds. With `--expect-report`, the line also says `matches --expect-report <path>`. **This certifies scoring-path byte-stability only** — not caption quality, not face recognition, not adoption readiness. | None for the scoring path. Do **not** read this as model adoption or as face/caption quality evidence. |
| `determinism check ERROR [label]: …` | Child could not run, timed out, payload missing/unreadable/unparseable, bound a different `build_reports` module, or `--expect-report` path missing/unreadable (**environment / path drift**). | Fix environment / import root / PYTHONPATH / path; re-run. **Not** a caption-model regression. |
| `determinism check FAILED [label]: …` | Genuine byte mismatch across seeds (**build regression**). Writes `determinism-mismatch-<label>-seed<n>.diff.txt` under gitignored `scripts/eval_harness/out/` (absolute path in the message); artifact carries the same `baseline=…; child_seeds=…` regime. | Investigate scoring code / non-determinism in the build. |
| `determinism check ANCHOR_MISMATCH [label]: …` | Seed-stable re-score does **not** match `--expect-report` (**external reference diverge**). Neither FAILED nor ERROR. Message names both legitimate causes, the regen command, and the absolute path of `determinism-anchor-mismatch-<label>.diff.txt` under `scripts/eval_harness/out/` (never beside a committed freeze). | **(1)** Frozen report or run-record corrupted → investigate; **do not regenerate** (destroys evidence). **(2)** Scoring deliberately changed → regenerate on purpose via `python -m scripts.eval_harness.generate_determinism_anchor` (or `generate_face_determinism_anchor`) and commit the new freeze. |

`label` is `score`, `score-public`, or `score-face` so CI logs name which document failed.

**`--expect-report` is opt-in on `score` and `score-face`, and requires
`--check-determinism`.** Discovery is never by sibling filename.

- **Caption freeze (F5):** LOCAL score document under
  `docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811*` scored
  against the **caption freeze man**
  `S2A-determinism-anchor-manifest-20260811.json` (not `golden.json`). Regenerate
  via `python -m scripts.eval_harness.generate_determinism_anchor`.
- **Face freeze (F6/F7):** synthetic face run-record + dedicated manifest + face
  report under `docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-*`
  (dim=8 unit vectors; no real embeddings — PROV-01). Multi-regime corpus (2
  identities, detection FP/FN, wrong-name, occlusion twin, 2 cohorts, error
  item, mixed-y trap media 11). A green face gate proves **byte-stable re-score**
  and that cells named live in the freeze execute; it does **not** prove
  ship-ready floors (UNDER-FLOOR/DIRECTIONAL is expected). Still-vacuous cells
  are listed in `provenance.coverage_gaps` (AUDIT-07). Regenerate via
  `python -m scripts.eval_harness.generate_face_determinism_anchor`. Offline both
  freezes in one shot via monorepo-root `make eval-anchor-check` (runs the
  caption block above and the face block below); or run the explicit CLI
  invocations directly when iterating outside `make`.

```text
$ cd apps/prototype-description-service
$ uv run --extra dev python -m scripts.eval_harness.cli score-face \
    --manifest ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-manifest-20260811.json \
    --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811.json \
    --check-determinism \
    --expect-report ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.json \
    --freeze-certification
determinism check passed [score-face]: cross-process re-score is bit-identical under varied PYTHONHASHSEED (baseline=randomized; child_seeds=0,1,42); matches --expect-report …/S2A-face-determinism-anchor-run-20260811-face-report.json
…/S2A-face-determinism-anchor-run-20260811-face-report.md
scored=10/10 matched_faces=6 occlusion_n_eligible=1 directional_excluded=6
freeze-certification passed [score-face]: scoring-path is byte-stable (matches --expect-report); nothing certified about model quality, face recognition, or adoption readiness …
# EXIT_CODE:0
```

## Report schema (`acx-eval/v1`, E19-1 extension)

Every eval document carries `schema: acx-eval/v1` plus a `kind` discriminator
(`run_record` for a raw fetch, `report` for a scored report) so the two are never
confused; `score` rejects a report file passed as a run record.

JSON sections: `provenance` (fetch-time `manifest_sha256`, `score_manifest_sha256`
+ `manifest_matches_fetch` flag, base_url, HEAD sha, started_at, and a `model`
block naming the **adapter(s)/model_id(s)/model_version(s)** that produced the
captions), `counts`, `caption` (insertion_rate, Must-Right failed + rubric-defined
images, policy violations, mean gated score), `faces.detection`,
`faces.identification`, `per_image`, `failures`. Deterministic sections are
bit-identical across re-scores of the same run record.

### Face metric shapes (scored vs REFUSED)

A consumer **MUST** check `refused` before reading any number on
`faces.detection` or `faces.identification`. A refused block sets
`precision` / `recall` / `wrong_names` (and the other counters) to JSON
`null`. `len(wrong_names)` on that value is a TypeError, not "zero errors".

**Scored `faces.detection`** (only when `annotation_mode=exhaustive`):

```json
{"precision": 0.5, "recall": 1.0, "tp": 1, "fp": 1, "fn": 0}
```

**REFUSED `faces.detection`** (`roster_only` / missing / unrecognised mode):

```json
{
  "refused": true,
  "invariant": "detection_refuses_roster_only",
  "precision": null,
  "recall": null,
  "tp": null,
  "fp": null,
  "fn": null
}
```

**Scored `faces.identification`** (only when every identity claim has
per-face box lineage):

```json
{
  "precision": 1.0,
  "recall": 1.0,
  "macro_precision": 1.0,
  "macro_recall": 1.0,
  "per_identity": {
    "Alice Example": {"precision": 1.0, "recall": 1.0, "tp": 1, "fp": 0, "fn": 0}
  },
  "true_rejections": 0,
  "excluded_images": 0,
  "wrong_names": [],
  "ignored_wrong_names": []
}
```

`wrong_names` is a list of `[path, name]` pairs (or `[]`). Only then is
`len(wrong_names)` safe.

**REFUSED `faces.identification`** (unboxed identity claims):

```json
{
  "refused": true,
  "invariant": "identification_refuses_unboxed_identity_claims",
  "precision": null,
  "recall": null,
  "macro_precision": null,
  "macro_recall": null,
  "per_identity": {},
  "true_rejections": null,
  "excluded_images": null,
  "wrong_names": null,
  "ignored_wrong_names": null
}
```

The markdown report renders the same refusal as
`REFUSED (<invariant>): <explanation>` — detection:
"detection P/R is not computed unless annotation_mode is exhaustive";
identification: "identification P/R is not computed from identity claims
that carry no per-face box lineage". The JSON block carries `invariant`;
the explanation string is markdown-only.

The shipped golden produces the refused shapes above on every `score`/`run`
(see Exit contract).

**Baseline caveat:** the committed `docs/tasks/vlm/VLM-2A-baseline-*` artifacts were
produced by the model-free `seeded` stub adapter (`adapter=seeded`,
`model_id=seeded-fixtures`) as a harness shakedown — the report's `model` block and
markdown header say so explicitly. They are **not** a caption-model baseline; a
real-model baseline must be captured with a live run before the §12 bake-off gate.

**Rubric status (measured on shipped golden-37):** `must_right` is populated on
**34/37** entries and `easy_wrong` on **37/37**. The Must-Right hard gate and
Easy-Wrong trap are **not** vacuous corpus-wide. `RubricEmptyWarning` does **not**
fire on the seed corpus (`test_seed_corpus_caption_fixtures_populated`). A live
report on this corpus shows `must_right_defined_images=34` /
`easy_wrong_defined_images=37`. The three entries without `must_right` are
per-image gaps, not a corpus-wide empty rubric. A corpus with genuinely empty
rubrics still emits `RubricEmptyWarning` and surfaces
`must_right_defined_images: 0` — that is not the state of the shipped golden.

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

# frozen synthetic face anchor (F6/F7 / B-06) — dim=8 unit vectors, no real embeddings
uv run python -m scripts.eval_harness.cli score-face \
  --manifest ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-manifest-20260811.json \
  --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811.json \
  --check-determinism \
  --expect-report ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.json

# published artifact: score full corpus, THEN post-score redact
uv run python -m scripts.eval_harness.cli score-face \
  --run-record scripts/eval_harness/out/face-run-<stamp>.json --public
```

`--check-determinism` on `score-face` re-runs §C–§F in a **fresh process** under
varied `PYTHONHASHSEED` and asserts bit-identical JSON/MD (sorted nested lists).
Seed-stability alone cannot detect a corrupted face run-record (parent and
children re-read the same file). Pair with `--expect-report` against the
committed synthetic freeze for the third outcome (`ANCHOR_MISMATCH`). Red-path
diagnostics write under gitignored `scripts/eval_harness/out/` (F7-01) so a
failed compare never dirties `docs/tasks/vlm/bakeoff-results/`. Never promote
real buffalo 512D embeddings out of `out/` (PROV-01) — the committed anchor is
synthetic only.

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

