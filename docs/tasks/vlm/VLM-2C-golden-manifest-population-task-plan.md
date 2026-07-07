# VLM-2C. Golden-Manifest Population

> **Metadata**
>
> - **Date**: 2026-07-06
> - **Author**: Claude (Opus 4.8)
> - **Project**: `apps/prototype-description-service` (VLM caption+face eval harness)
> - **Task ID**: `VLM-2C`
> - **Target Branch**: `feature/vlm-2c`
> - **Feeds**: Epic E19 Context-Aware Image Description (v0.5.0) / VLM harness program; consumers E19-4a, VLM-2B, E20-11.
> - **Review Coverage Target**: 2

---

## Objective

Populate the VLM-2A golden manifest (`scene/tests/seed/golden.json`) with the ground truth the harness code already expects but never received: context packs, base captions, Must-Right/Easy-Wrong rubrics, confirmed identities, at least one stranger entry, and seeded scene-image face regions + a phrase-box fixture. When complete, caption/insertion/face-P-R metrics read non-zero and the wrong-name gate is exercised, unblocking E19-4a, VLM-2B, and E20-11.

## Intake

- **Scope one-pager**: `docs/scopes/vlm-2c-golden-manifest-population-scope.md`
- **Not-Doing**: no new metric/scoring code (only a bounded additive manifest-schema extension); no VLM caption inference / bake-off run; no CI gate; no external dataset ingestion; no E19-4a merge service implementation.

## Problem Statement

VLM-2A shipped the harness code but not its fixtures. `golden.json` holds 37 entries, all with `context_pack {}`, `must_right []`, `easy_wrong []`, `face_count == len(present_identities)`, and no base caption. Consequences, each grounded in code:

- `context_pack` empty → the describe route echoes no name-injected WP text, so `caption_metrics.insertion_rate` (`caption_metrics.py:127`) has no signal to measure.
- `must_right`/`easy_wrong` empty → `load_manifest` emits `RubricEmptyWarning` (`manifest.py:166`); the `gated_score` Must-Right hard gate (`caption_metrics.py:72`) is vacuous corpus-wide.
- No stranger entry (`face_count > len(present_identities)`) → `identification_pr`'s true-rejection branch (`face_metrics.py:116`) never fires; wrong-name insertion, the top product risk, is untested.
- `seed_roster.seed` seeds only crop clusters at `CROP_MEDIA_ID_BASE = 1001` (`seed_roster.py:26,59`) → no server-side `MediaIdentity` bbox per scene `media_id`, which E19-4a's SQL join requires.
- No base caption → no deterministic reference string for offline scoring or E19-4a reflow input.

## Constraints

- **Fixtures, not scoring changes.** `caption_metrics.py`, `face_metrics.py`, and `report.py` scoring logic stay untouched. The only sanctioned code edit is an **additive** manifest-schema extension in `manifest.py` (new optional field + version bump) that carries the new fixtures.
- **Strict schema.** `GoldenEntry` is `extra='forbid'` (`manifest.py:71`); `EntryPolicy` is `extra='forbid'` (`manifest.py:65`). Any new per-entry key requires a real field. `ContextPack` is `extra='allow'` (`manifest.py:51`) — WP keys extend freely, known keys stay typed.
- **Roster closure.** Every name in `present_identities`/`must_right`/`easy_wrong` must be in `manifest.roster` or `load_manifest` raises (`manifest.py:161`).
- **Hash integrity.** Every `sha256` must match the byte content under `$GOLDEN_IMAGES_DIR/<path>` (`manifest.py:179`); images are not vendored (59 MB).
- **Load discipline / provenance** carry over from VLM-2A Q5 (concurrency 1, artifacts stamped with manifest version + git HEAD).

## Workflow Principles

- Draft mechanically, confirm by hand: `draft_labels` guesses; a single documented operator pass is the ground-truth authority (VLM-2A Q7).
- One source of truth: identities live in `golden.json`; server-side cluster labels and scoring both derive names via `naming.py` — do not fork name strings.
- Additive-only schema: bump the version, add optional fields, keep version-1 entries loadable in spirit (greenfield: no migration, but no silent breakage of the loader contract).

## Terminology

- **Context pack**: WP `title`/`caption`/`description` echoed to the describe route — the name-injected TEXT the model sees; the `insertion_rate` signal source.
- **Base caption**: per-entry reference caption. NOT read by the scorer — scoring matches `describe.alt_text_draft` in the run record (`report.py:114`); `base_caption` is the source copied into the seeded stub run record and E19-4a's reflow input.
- **Stranger entry**: a scene with `recognition_enabled=true` and `face_count > len(present_identities)` → `stranger_faces > 0` → drives true-rejection.
- **Phrase box**: a person-phrase bounding box (`[0,1]` fractions) for E19-4a containment match.

## Current State Analysis

- **Works**: loader/validator (`manifest.py`), caption + face metrics (`caption_metrics.py`, `face_metrics.py`), report builder (`report.py`), CLI `fetch|score|run|seed-roster` (`cli.py`), crop-roster seeding (`seed_roster.py`), draft generator (`draft_labels.py`), `make eval-captions`.
- **Broken/vacuous**: all 37 entries' `context_pack`/`must_right`/`easy_wrong` empty; no base caption; zero stranger entries; scene images never seeded into recognition; no phrase-box fixture.
- **Misleading**: `seed/README.md:39` claims "confirmed by an operator pass" and rubric-empty is stated as an MVP choice — VLM-2C supersedes both (rubrics + confirmation now delivered).

## Target Outcome

`golden.json` (version 2) carries confirmed identities, `face_count` incl. strangers, populated `context_pack`, `base_caption`, and Must-Right/Easy-Wrong rubrics per entry, with ≥1 stranger entry. A companion phrase-box fixture + an extended `seed_roster` populate E19-4a's containment inputs. Running `cli score` against a seeded stub run record produces non-zero caption/insertion/face-P-R numbers and a true rejection on the stranger entry; a re-run is bit-identical.

## Context Loading

- Rules: `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/backend-python-guidelines.md`
- Harness: `apps/prototype-description-service/scripts/eval_harness/{manifest,caption_metrics,face_metrics,draft_labels,seed_roster,naming,report,cli}.py`
- Fixtures/docs: `apps/prototype-description-service/scene/tests/seed/{golden.json,README.md}`
- Scopes: `docs/scopes/vlm-2c-golden-manifest-population-scope.md`, `docs/scopes/e19-4a-identity-prose-merge-scope.md`, `docs/scopes/vlm-2a-caption-face-eval-harness-scope.md`
- Handoff/MCP state: task ref `VLM-2C`, findings on `feature/vlm-2c`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Golden-manifest schema | backend (eval harness) | `scripts/eval_harness/manifest.py` (`SUPPORTED_MANIFEST_VERSION=1`) | Additive: new optional `GoldenEntry.base_caption`; bump `SUPPORTED_MANIFEST_VERSION` 1→2 | No — greenfield, no live consumers of v1 | `load_manifest` loads v2 golden.json + rejects v1/v3 |
| E19-4a phrase-box fixture | backend (E19-4a merge) — **coordinated, not owned here** | none yet (E19-4a scope §1/S1 "mock/seeded phrase boxes") | New fixture artifact + expected containment mapping | Coordinate field names with E19-4a merge service | E19-4a loads fixture; containment 1:1 offline |
| Recognition seeding (scene images) | backend (eval harness) | `seed_roster.seed` seeds crops only (`CROP_MEDIA_ID_BASE`) | Extend to also seed scene images → server-side `MediaIdentity` bboxes per scene `media_id` | No — additive seed path | seeded tenant returns bboxes keyed on scene `media_id` |

## Proposed Solution

Four slices, each producing fixtures plus proof. Draft mechanically with `draft_labels.generate_draft_manifest`, confirm by hand, then layer caption fixtures, then face/region fixtures, then bootstrap/version housekeeping and end-to-end evidence. The single code edit is the additive `base_caption` field + version bump in `manifest.py`; everything else is data (`golden.json`, a phrase-box fixture, `seed/README.md`) plus an additive seed path in `seed_roster.py`.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| fixture (data) | `apps/prototype-description-service/scene/tests/seed/golden.json` | Populate `context_pack`, `base_caption`, `must_right`, `easy_wrong`, confirmed `present_identities`, true `face_count`; add ≥1 stranger entry; refresh `sha256`; bump `manifest_version`→2 |
| harness (schema, additive) | `apps/prototype-description-service/scripts/eval_harness/manifest.py` | Add optional `GoldenEntry.base_caption: str \| None`; bump `SUPPORTED_MANIFEST_VERSION` 1→2 (`_version_is_supported`) — **no scoring change** |
| harness (seed, additive) | `apps/prototype-description-service/scripts/eval_harness/seed_roster.py` | Add scene-image seeding path so recognition produces `MediaIdentity` bboxes per scene `media_id` (parallel to crop seeding; keeps the idempotent re-run contract) |
| fixture (data, NEW) | `apps/prototype-description-service/scene/tests/seed/phrase_boxes.json` | **NEW** — mock phrase boxes (`[0,1]` fractions) + expected face→phrase→identity containment mapping, keyed by scene `media_id`, for E19-4a offline merge tests |
| docs | `apps/prototype-description-service/scene/tests/seed/README.md` | Update version note, rubric/confirmation status, rsync bootstrap, and phrase-box fixture provenance |
| tests | `apps/prototype-description-service/scene/tests/` (or `scripts/eval_harness/tests/`) | Add/extend fixture-integrity + stranger-true-rejection + deterministic-score tests; **update the hard-coded `manifest_version=1` literals in `test_eval_harness_manifest.py:20` and `test_eval_harness_cli.py:14` to 2** — the version bump makes them fail the loader otherwise |

## Related Files

| File | Note |
| --- | --- |
| `scripts/eval_harness/caption_metrics.py` | `score_caption` (`:82`), `insertion_rate` (`:127`), `gated_score` (`:72`) — consume the caption fixtures; not edited |
| `scripts/eval_harness/face_metrics.py` | `identification_pr` (`:97`) true-rejection (`:116`), `detection_pr` (`:87`) — consume identities + `face_count`; not edited |
| `scripts/eval_harness/report.py` | `score_run_record` / `build_reports` — builds `ImageDetection`/`ImageIdentities` from run record + manifest; not edited |
| `scripts/eval_harness/draft_labels.py` | `generate_draft_manifest` (`:20`) — Slice-1 draft source (filename heuristics) |
| `scripts/eval_harness/naming.py` | `entity_slug`/`display_name` (`:21`,`:27`) — canonical name derivation |
| `scripts/eval_harness/cli.py` | `score` subcommand (`--run-record`, `:353`) + `--check-determinism` (`:345`); `_cmd_score` loads the manifest with no `images_dir` (`:290`), so scoring is fully offline — no live model needed |
| `scene/tests/test_eval_harness_report.py` | Committed run-record stub template: `{kind, schema, provenance, items:[{media_id, path, describe:{alt_text_draft, adapter:"seeded", visual_facts:{objects}}, identities, face_count}]}` (`:15-55`) — copy this shape for the seeded stub |
| `docs/scopes/e19-4a-identity-prose-merge-scope.md` | Consumer contract for phrase boxes / containment / stranger gate |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && uv run python -m pytest scene/tests/ -k "manifest or golden or stranger"` — fixture-integrity, roster closure, stranger true-rejection.
  - `uv run python -c "from scripts.eval_harness.manifest import load_manifest; load_manifest('scene/tests/seed/golden.json')"` — no `RubricEmptyWarning`.
- Contract/fixture verification:
  - `load_manifest('scene/tests/seed/golden.json', images_dir=$GOLDEN_IMAGES_DIR)` — every `sha256` matches, `face_count >= len(present_identities)`, version-2 accepted.
  - `cli score --run-record <seeded-stub> --check-determinism` — non-zero caption/insertion/face-P-R; bit-identical re-run.
- Runtime-parity / environment checks:
  - Extended `seed_roster` against a live eval tenant (`ACX_EVAL_LIVE=1`) returns `MediaIdentity` bboxes keyed on scene `media_id` (integration; not required for the offline gate).
- Manual verification:
  - Operator confirmation pass log recorded (VLM-2A Q7) — identities, `face_count`, stranger entry, context packs.

## Slice Delivery

### Slice 1: Draft + human-confirm ground truth

**Goal**: Confirmed `present_identities` and true `face_count` per entry, with ≥1 stranger entry, from a `draft_labels` draft plus one documented operator pass.

Changes:

- Regenerate the draft via `draft_labels.generate_draft_manifest(fixtures_dir)`; reconcile against current `golden.json`. **Drop `mock_images/kirstie-boat_detected.jpg`**: `draft_labels` iterates all 38 `mock_images` files with no exclusion and re-introduces this detection-annotated near-duplicate that VLM-2A deliberately removed (`seed/README.md:20`); keep the corpus at 37 usable scenes.
- Operator pass: confirm identities, set `face_count` incl. non-roster strangers (per `seed/README.md` counting rule), introduce/confirm ≥1 stranger entry (`recognition_enabled=true`, `face_count > len(present_identities)`).
- Refresh `sha256` for any changed/added entry.

Proof:

- `load_manifest(..., images_dir=$GOLDEN_IMAGES_DIR)` passes; a test asserts ≥1 entry with `face_count > len(present_identities)`.

### Slice 2: Caption fixtures + schema extension

**Goal**: Populate `context_pack`, `base_caption`, `must_right`, `easy_wrong` per entry so caption/insertion metrics are non-vacuous.

Changes:

- `manifest.py`: add optional `GoldenEntry.base_caption: str | None`; bump `SUPPORTED_MANIFEST_VERSION` 1→2. No scoring change.
- `golden.json`: populate `context_pack {title,caption,description}` with name-injected WP text; author `base_caption`, `must_right`, `easy_wrong` (roster-closed); set `manifest_version: 2`.

Proof:

- `load_manifest` emits no `RubricEmptyWarning`; `cli score` against a stub run record (caption = `base_caption`) yields `insertion_rate` > 0, `must_right_defined_images > 0`, and a non-zero `gated_score` on a passing entry.

### Slice 3: Face/region fixtures for E19-4a

**Goal**: Server-side scene-face bboxes + a phrase-box fixture + expected containment mapping for E19-4a's offline merge.

Changes:

- `seed_roster.py`: additive scene-image seeding path (parallel to crop seeding; idempotent re-run preserved) producing `MediaIdentity` bboxes per scene `media_id`.
- NEW `scene/tests/seed/phrase_boxes.json`: mock phrase boxes (`[0,1]` fractions) + face→phrase→identity 1:1 containment mapping, keyed by `media_id`; ≥1 stranger case where containment yields no name.

Proof:

- `identification_pr` over the manifest + seeded/stub identities yields non-zero TP/FP/FN and `true_rejections >= 1` on the stranger entry; the phrase-box fixture loads and its containment mapping is 1:1 offline.

### Slice 4: Bootstrap doc + version note + end-to-end evidence

**Goal**: Update the fixture docs and capture the deterministic, non-vacuous run evidence.

Changes:

- `seed/README.md`: version-2 note, rubric/confirmation status, rsync bootstrap, phrase-box fixture provenance.
- Capture a seeded-stub score report showing non-zero caption/insertion/face-P-R and the stranger true-rejection.

Proof:

- `cli score --check-determinism` bit-identical across two passes; report artifact archived under `docs/tasks/vlm/` per VLM-2A retention convention.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded harness modules, scopes (VLM-2A, VLM-2C, E19-4a), and the `manifest.py` schema before editing.
- [ ] Recorded the additive schema-extension boundary (new optional field + version bump) and the E19-4a phrase-box coordination point.

### Checklist for Slice 1: Draft + human-confirm ground truth

- [ ] Regenerated the `draft_labels` draft and reconciled with `golden.json`.
- [ ] Operator confirmation pass: identities, `face_count` incl. strangers, ≥1 stranger entry.
- [ ] Refreshed `sha256`; `load_manifest(..., images_dir=...)` passes.

### Checklist for Slice 2: Caption fixtures + schema extension

- [ ] Added optional `GoldenEntry.base_caption`; bumped `SUPPORTED_MANIFEST_VERSION`→2.
- [ ] Populated `context_pack`, `base_caption`, `must_right`, `easy_wrong` (roster-closed); set `manifest_version: 2`.
- [ ] Proof: no `RubricEmptyWarning`; stub-score insertion/Must-Right non-zero.

### Checklist for Slice 3: Face/region fixtures for E19-4a

- [ ] Extended `seed_roster.py` with an idempotent scene-image seed path.
- [ ] Authored `phrase_boxes.json` (mock boxes + 1:1 containment mapping, incl. stranger case).
- [ ] Proof: `identification_pr.true_rejections >= 1`; containment 1:1 offline.

### Checklist for Slice 4: Bootstrap doc + version note + evidence

- [ ] Updated `seed/README.md` (version, rubric/confirmation status, rsync, phrase boxes).
- [ ] Captured deterministic seeded-stub score evidence; archived report.

## Review Readiness

- [ ] No scoring-logic edits; only the additive `base_caption` field + version bump in `manifest.py`.
- [ ] Fixture integrity verified against `$GOLDEN_IMAGES_DIR` (sha256, roster closure, `face_count`).
- [ ] Handoff decision records the population, the stranger-entry gate result, and the E19-4a coordination point.

## Stretch Goals

- [ ] Objects/tag-coverage fixtures for `score_caption(objects=...)` tag-coverage signal.
- [ ] Second stranger entry with a roster person also present (mixed true-rejection case, `face_metrics.py:116`).

## Success Criteria

- [ ] `cli score` against a seeded stub run record yields non-vacuous, non-zero caption + `insertion_rate` + face detection/identification P/R; `must_right_defined_images > 0`; no `RubricEmptyWarning`.
- [ ] The stranger entry yields `identification_pr(...).true_rejections >= 1`, not a wrong name.
- [ ] `load_manifest(golden.json, images_dir=$GOLDEN_IMAGES_DIR)` passes at `manifest_version: 2`.
- [ ] `cli score --check-determinism` is bit-identical across re-runs.
- [ ] E19-4a can load `phrase_boxes.json` + seeded scene-face bboxes and exercise 1:1 containment offline.
