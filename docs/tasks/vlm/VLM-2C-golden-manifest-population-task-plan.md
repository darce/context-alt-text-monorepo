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

Populate the VLM-2A golden manifest (`scene/tests/seed/golden.json`) with the ground truth the harness code already expects but never received: context packs, base captions, Must-Right/Easy-Wrong rubrics, an operator-designated stranger entry, and seeded scene-image face regions + a phrase-box fixture. When complete, caption/insertion metrics read non-zero (0.000/vacuous in the 2026-07-06 baseline), the Must-Right/Easy-Wrong wrong-name gate is active, and a seeded-stub `cli score` proves it end to end — unblocking E19-4a, VLM-2B, and E20-11.

## Intake

- **Scope one-pager**: `docs/scopes/vlm-2c-golden-manifest-population-scope.md`
- **Not-Doing**: no new metric/scoring code (only a bounded additive manifest-schema extension); no VLM caption inference / bake-off run; no CI gate; no external dataset ingestion; no E19-4a merge service implementation.

## Problem Statement

VLM-2A shipped the harness code but not its caption fixtures. `golden.json` holds 37 entries, all with `context_pack {}`, `must_right []`, `easy_wrong []`, and no base caption. Identities and `face_count` ARE operator-confirmed (VLM-2A pass; 6 entries carry a `face_count > len(present_identities)` stranger delta). Baseline evidence (`docs/tasks/vlm/VLM-2A-baseline-20260706-report.md`): `insertion_rate 0.000`, `must_right_defined_images: 0`, `true_rejections: 6`. Consequences, each grounded in code:

- `context_pack` empty → the describe route echoes no name-injected WP text, so `caption_metrics.insertion_rate` (`caption_metrics.py:127`) reads 0.000 — captions can never contain roster names.
- `must_right`/`easy_wrong` empty → `load_manifest` emits `RubricEmptyWarning` (`manifest.py:166`); the `gated_score` Must-Right hard gate (`caption_metrics.py:72`) is vacuous corpus-wide.
- `easy_wrong` empty → wrong-name insertion, the top product risk, has no caption-side trap; and while the baseline already fires `identification_pr`'s true-rejection branch (`face_metrics.py:116`) on the 6 stranger-delta entries, no entry is operator-designated as a genuine non-roster stranger fixture with a phrase-box no-name case for E19-4a's "never a guessed name" gate.
- `seed_roster.seed` seeds only crop clusters at `CROP_MEDIA_ID_BASE = 1001` (`seed_roster.py:26,59`) → no idempotently seeded server-side `MediaIdentity` bbox per scene `media_id` (scenes reach recognition only as a per-run `fetch` side effect, `cli.py:117`), which E19-4a's SQL join requires.
- No base caption → no deterministic reference string for offline scoring or E19-4a reflow input.

## Constraints

- **Fixtures, not scoring changes.** `caption_metrics.py`, `face_metrics.py`, and `report.py` scoring logic stay untouched. Sanctioned code edits are additive only: the manifest-schema extension in `manifest.py` (new optional field + version bump), the parallel scene-seed path in `seed_roster.py` (Slice 3), and the `manifest_version` literal sync in `draft_labels.py:84` + tests.
- **Strict schema.** `GoldenEntry` is `extra='forbid'` (`manifest.py:71`); `EntryPolicy` is `extra='forbid'` (`manifest.py:65`). Any new per-entry key requires a real field. `ContextPack` is `extra='allow'` (`manifest.py:51`) — WP keys extend freely, known keys stay typed.
- **Roster closure.** Every entry in `present_identities`/`must_right`/`easy_wrong` — not just names — must be in `manifest.roster` or `load_manifest` raises (`manifest.py:161`). Rubric lists are therefore roster-name lists; non-name visual facts belong to `visual_facts.objects` tag coverage (stretch), not rubrics.
- **Hash integrity.** Every `sha256` must match the byte content under `$GOLDEN_IMAGES_DIR/<path>` (`manifest.py:179`); images are not vendored (59 MB).
- **Load discipline / provenance** carry over from VLM-2A Q5 (concurrency 1, artifacts stamped with manifest version + git HEAD).

## Workflow Principles

- Draft mechanically, confirm by hand: `draft_labels` guesses; a single documented operator pass is the ground-truth authority (VLM-2A Q7).
- One source of truth: identities live in `golden.json`; server-side cluster labels and scoring both derive names via `naming.py` — do not fork name strings.
- Additive-only schema: bump the version, add optional fields, keep version-1 entries loadable in spirit (greenfield: no migration, but no silent breakage of the loader contract).

## Terminology

- **Context pack**: WP `title`/`caption`/`description` echoed to the describe route — the name-injected TEXT the model sees; the `insertion_rate` signal source.
- **Base caption**: per-entry reference caption, naming every confirmed present identity (see authoring rule). NOT read by the scorer — scoring matches `describe.alt_text_draft` in the run record (`report.py:114`); `base_caption` is the source copied into the seeded stub run record and E19-4a's reflow input.
- **Stranger entry**: a scene with `recognition_enabled=true` and `face_count > len(present_identities)` → `stranger_faces > 0` → drives true-rejection.
- **Phrase box**: a person-phrase bounding box (`[0,1]` fractions) for E19-4a containment match.

## Current State Analysis

- **Works**: loader/validator (`manifest.py`), caption + face metrics (`caption_metrics.py`, `face_metrics.py`), report builder (`report.py`), CLI `fetch|score|run|seed-roster` (`cli.py`), crop-roster seeding (`seed_roster.py`), draft generator (`draft_labels.py`), `make eval-captions`.
- **Broken/vacuous**: all 37 entries' `context_pack`/`must_right`/`easy_wrong` empty; no base caption; no operator-designated stranger fixture (6 entries carry stranger deltas from the VLM-2A face-count pass; baseline `true_rejections: 6`); scene images reach recognition only as a per-run `fetch` side effect (`cli.py:117`), no idempotent seed path; no phrase-box fixture.
- **Stale after this task**: `seed/README.md:17` states rubric-empty as an MVP choice and `:39` scopes the operator pass to identity/`face_count` labels — both need updating once rubrics/context/base captions are authored and the stranger fixture is designated.

## Target Outcome

`golden.json` (version 2) carries confirmed identities, `face_count` incl. strangers, populated `context_pack`, `base_caption`, and Must-Right/Easy-Wrong rubrics per entry, with ≥1 stranger entry. A companion phrase-box fixture + an extended `seed_roster` populate E19-4a's containment inputs. Running `cli score` against a seeded stub run record produces non-zero caption/insertion/face-P-R numbers and a true rejection on the stranger entry; a re-run is bit-identical.

## Context Loading

- Rules: `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/backend-python-guidelines.md`
- Harness: `apps/prototype-description-service/scripts/eval_harness/{manifest,caption_metrics,face_metrics,draft_labels,seed_roster,naming,report,cli}.py`
- Fixtures/docs: `apps/prototype-description-service/scene/tests/seed/{golden.json,README.md}`
- Scopes: `docs/scopes/vlm-2c-golden-manifest-population-scope.md`, `docs/scopes/e19-4a-identity-prose-merge-scope.md`, `docs/scopes/vlm-2a-caption-face-eval-harness-scope.md`
- Baseline evidence: `docs/tasks/vlm/VLM-2A-baseline-20260706-report.md`, `docs/tasks/vlm/VLM-2A-baseline-20260706-run-record.json`
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
| harness (draft, literal) | `apps/prototype-description-service/scripts/eval_harness/draft_labels.py` | Sync the hard-coded `"manifest_version": 1` literal (`:84`) to 2 so regenerated drafts stay loadable after the version bump |
| fixture (data, NEW) | `apps/prototype-description-service/scene/tests/seed/phrase_boxes.json` | **NEW** — mock phrase boxes (`[0,1]` fractions) + expected face→phrase→identity containment mapping, keyed by scene `media_id`, for E19-4a offline merge tests |
| docs | `apps/prototype-description-service/scene/tests/seed/README.md` | Update version note, rubric/confirmation status, rsync bootstrap, and phrase-box fixture provenance |
| tests | `apps/prototype-description-service/scene/tests/` | Add/extend fixture-integrity + stranger-true-rejection + deterministic-score tests; **update the hard-coded `manifest_version=1` literals in `test_eval_harness_manifest.py:20` and `test_eval_harness_cli.py:14` to 2** — the version bump makes them fail the loader otherwise |

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
  - `cd apps/prototype-description-service && .venv/bin/python -m pytest scene/tests/ -k "manifest or golden or stranger"` — fixture-integrity, roster closure, stranger true-rejection.
  - `.venv/bin/python -c "from scripts.eval_harness.manifest import load_manifest; load_manifest('scene/tests/seed/golden.json')"` — no `RubricEmptyWarning`.
- Contract/fixture verification:
  - `load_manifest('scene/tests/seed/golden.json', images_dir=$GOLDEN_IMAGES_DIR)` — every `sha256` matches, `face_count >= len(present_identities)`, **manifest_version 3** accepted (the v2 golden is no longer loadable).
  - Copy the stub out of tree (`cd apps/prototype-description-service && WORK=$(mktemp -d) && cp ../../docs/tasks/vlm/VLM-2C-seeded-stub-run-record-20260707.json "$WORK/run.json" && .venv/bin/python -m scripts.eval_harness.cli score --run-record "$WORK/run.json" --manifest scene/tests/seed/golden.json --check-determinism`) — non-zero caption/`insertion_rate`; **face detection and identification are REFUSED** (`detection_refuses_roster_only`, `identification_refuses_unboxed_identity_claims`); exit 3; re-score is bit-identical. `cli score` does **not** yield face P/R on this golden.
- Runtime-parity / environment checks:
  - Extended `seed_roster` against a live eval tenant (`ACX_EVAL_LIVE=1`) returns `MediaIdentity` bboxes keyed on scene `media_id` (integration; not required for the offline gate).
- Manual verification:
  - Operator confirmation pass log recorded (VLM-2A Q7) — identities, `face_count`, stranger entry, context packs.

## Slice Delivery

### Slice 1: Draft + human-confirm ground truth

**Goal**: Confirmed `present_identities` and true `face_count` per entry, with ≥1 stranger entry, from a `draft_labels` draft plus one documented operator pass.

Changes:

- Regenerate the draft via `draft_labels.generate_draft_manifest(fixtures_dir)`; reconcile against current `golden.json`. **Drop `mock_images/kirstie-boat_detected.jpg`**: `draft_labels` iterates all 38 `mock_images` files with no exclusion and re-introduces this detection-annotated near-duplicate that VLM-2A deliberately removed (`seed/README.md:20`); keep the corpus at 37 usable scenes.
- Operator pass: confirm identities, set `face_count` incl. non-roster strangers (per `seed/README.md` counting rule).
- **Stranger designation is an explicit Slice-1 step — do not inherit one silently.** Six entries already carry `face_count > len(present_identities)` from the VLM-2A face-count pass (e.g. `ccqw-erika.jpg`: 4 faces / 2 identities), but none is designated as THE stranger fixture. During the labeling pass, confirm ≥1 of these deltas is a genuine non-roster human face (not an unlabeled roster member or a depicted face) on a `recognition_enabled=true` scene, and record it as the stranger entry. If the pass surfaces zero genuine strangers, add a scene that has one rather than manufacturing the condition on a roster-only image.
- **Never fabricate `face_count`.** Derive every `face_count` (and therefore every `stranger_faces = face_count - len(present_identities)` delta) directly from the operator confirmation pass counting each visible face region per the `seed/README.md` rule. Do not back-fill a number to force a stranger delta.
- Refresh `sha256` for any changed/added entry.

Proof:

- `load_manifest(..., images_dir=$GOLDEN_IMAGES_DIR)` passes; a test asserts ≥1 **operator-confirmed** entry with `face_count > len(present_identities)`, and the confirmation-pass log records the counted face regions that justify each `face_count`.

### Slice 2: Caption fixtures + schema extension

**Goal**: Populate `context_pack`, `base_caption`, `must_right`, `easy_wrong` per entry so caption/insertion metrics are non-vacuous.

Changes:

- `manifest.py`: add optional `GoldenEntry.base_caption: str | None`; bump `SUPPORTED_MANIFEST_VERSION` 1→2. Sync the `manifest_version` literals in `draft_labels.py:84`, `test_eval_harness_manifest.py:20`, `test_eval_harness_cli.py:14`. No scoring change.
- `golden.json`: populate `context_pack {title,caption,description}` with name-injected WP text; author `base_caption`, `must_right`, `easy_wrong` (roster-closed); set `manifest_version: 2`.

Proof:

- `load_manifest` emits no `RubricEmptyWarning`; `cli score` against a stub run record (caption = `base_caption`) yields `insertion_rate` > 0, `must_right_defined_images > 0`, and a non-zero `gated_score` on a passing entry.

### Slice 3: Face/region fixtures for E19-4a

**Goal**: Server-side scene-face bboxes + a phrase-box fixture + expected containment mapping for E19-4a's offline merge.

Changes:

- `seed_roster.py`: additive scene-image seeding path (parallel to crop seeding; idempotent re-run preserved) producing `MediaIdentity` bboxes per scene `media_id`.
- NEW `scene/tests/seed/phrase_boxes.json`: mock phrase boxes (`[0,1]` fractions) + face→phrase→identity 1:1 containment mapping, keyed by `media_id`; ≥1 stranger case where containment yields no name. Author to the pinned schema in **§ Fixture Schemas and Worked Example / `phrase_boxes.json` schema** (top-left axis, face-center-in-smallest-box containment, offline).

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

## Fixture Schemas and Worked Example

### `phrase_boxes.json` schema (E19-4a coordination seam)

`scene/tests/seed/phrase_boxes.json` is the coordination seam E19-4a's containment-match consumes. It is a **static, offline** fixture — no live recognition call is made to build or consume it; face centers and phrase boxes are authored ground truth read straight from JSON.

Coordinate contract (pin — E19-4a matches against exactly this):

- **All coordinates are normalized `[0,1]` image fractions.** A value of `0.0` is the left/top edge; `1.0` is the right/bottom edge. No pixel coordinates appear in this file.
- **Axis convention: origin top-left, x increases rightward, y increases downward.** This matches image-raster convention and the recognition service's stored bbox space, so no axis flip is needed on either side.
- **Per-scene keying by `media_id`.** The `scenes` object is keyed by the scene's stringified `media_id` from `golden.json` (the same synthetic id used for the run record and the seeded `MediaIdentity`), so a consumer joins phrase boxes to a golden entry by `media_id` alone.
- **Face center** = the INPUT point E19-4a tests for containment: `[x, y]` fractions of the face region's center in the scene image.
- **Phrase box** = a person-phrase bounding box `[x_min, y_min, x_max, y_max]` in the same `[0,1]` top-left axis, with `x_min < x_max` and `y_min < y_max`.

Containment rule (what E19-4a's merge does against this format): for each face center, find the **smallest-area person-phrase box that contains the face center** (`x_min <= x <= x_max and y_min <= y <= y_max`); the contained box's `phrase` resolves the face to that identity. A face center contained by **no** phrase box resolves to **no name** (the stranger / true-rejection case — E19-4a must emit no guessed name). "Smallest" breaks the tie when nested boxes both contain a center.

Shape:

```json
{
  "schema": "phrase_boxes/v1",
  "axis": { "origin": "top-left", "x": "right", "y": "down", "units": "image_fraction_[0,1]" },
  "scenes": {
    "5": {
      "media_id": 5,
      "path": "mock_images/ccqw-erika.jpg",
      "face_centers": [
        { "center": [0.31, 0.42] },
        { "center": [0.68, 0.39] }
      ],
      "phrase_boxes": [
        { "phrase": "Caitlin Weaver",       "box": [0.20, 0.25, 0.45, 0.72] },
        { "phrase": "Erika Hansen Miller",   "box": [0.55, 0.22, 0.82, 0.70] }
      ],
      "expected_containment": [
        { "face_center": [0.31, 0.42], "resolved_identity": "Caitlin Weaver" },
        { "face_center": [0.68, 0.39], "resolved_identity": "Erika Hansen Miller" }
      ]
    },
    "<stranger_media_id>": {
      "media_id": 0,
      "path": "mock_images/<stranger-scene>.jpg",
      "face_centers": [
        { "center": [0.30, 0.40] },
        { "center": [0.90, 0.35] }
      ],
      "phrase_boxes": [
        { "phrase": "<roster person>", "box": [0.18, 0.24, 0.44, 0.71] }
      ],
      "expected_containment": [
        { "face_center": [0.30, 0.40], "resolved_identity": "<roster person>" },
        { "face_center": [0.90, 0.35], "resolved_identity": null }
      ]
    }
  }
}
```

`expected_containment` is the authored answer key: E19-4a's merge run over `face_centers` + `phrase_boxes` must reproduce it 1:1, including the `null` (no-name) result for the stranger face that lands in no phrase box. Coordinates in `expected_containment` echo the `face_centers` so the fixture is self-checking without recomputation. `media_id` keys are illustrative placeholders here (`5` is real; `0`/`<stranger_media_id>` are filled from the Slice-1 confirmation pass — not fabricated).

### Worked golden-entry example (authoring template)

The following is ONE fully worked entry showing the shape every `golden.json` entry must reach in Slice 2. It uses a **real corpus scene** (`ccqw-erika.jpg`, `media_id 5`). The `context_pack`/`base_caption`/rubric text below is an **illustrative authoring sample** to fix the format; `present_identities` and `face_count` are set by the Slice-1 operator confirmation pass, not by this template.

```json
{
  "path": "mock_images/ccqw-erika.jpg",
  "sha256": "34271e1e49ba12f01a0494b6b560709d45c4941a95c88faef929092a0a33dd27",
  "media_id": 5,
  "face_count": 4,
  "present_identities": ["Caitlin Weaver", "Erika Hansen Miller"],
  "context_pack": {
    "title": "Caitlin Weaver and Erika Hansen Miller in Antarctica",
    "caption": "Caitlin Weaver and Erika Hansen Miller on the expedition deck.",
    "description": "Two travelers, Caitlin Weaver and Erika Hansen Miller, bundled in parkas during an Antarctic cruise."
  },
  "base_caption": "Caitlin Weaver and Erika Hansen Miller stand together in heavy parkas on a ship deck with grey water behind them.",
  "must_right": ["Caitlin Weaver", "Erika Hansen Miller"],
  "easy_wrong": ["Bea Burke", "Ryann Wiseman"],
  "policy": { "recognition_enabled": true }
}
```

Authoring rule for `must_right` vs `easy_wrong`:

- **`must_right`** = names that MUST be correct: the confirmed identities present in the scene (⊆ `present_identities` ⊆ `roster`); the caption Must-Right hard gate (`caption_metrics.py:72`) fails the entry if any is missing from the caption.
- **`easy_wrong`** = wrong-name traps that must NOT appear: roster names of people **not** in this scene (wrong-name insertion — the top product risk). Believable confusions, not nonsense.
- **`base_caption`** must name every confirmed present identity — the seeded stub copies it as the caption, so a name-free base caption would zero the Must-Right gate and `insertion_rate` (Slice-2 proof depends on this).

Both lists are roster-closed in full: `load_manifest` validates EVERY rubric string against `manifest.roster` (`manifest.py:161`) and raises on any non-roster entry, so free-string visual facts (`"parkas"`, `"beach"`) cannot appear in rubrics. Non-name visual facts are scored via `score_caption(objects=...)` tag coverage from the run record's `visual_facts.objects` (stretch goal), not via rubrics.

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded harness modules, scopes (VLM-2A, VLM-2C, E19-4a), and the `manifest.py` schema before editing.
- [x] Recorded the additive schema-extension boundary (new optional field + version bump) and the E19-4a phrase-box coordination point.

### Checklist for Slice 1: Draft + human-confirm ground truth

- [x] Regenerated the `draft_labels` draft and reconciled with `golden.json`.
- [x] Operator confirmation pass: identities, `face_count` incl. strangers, ≥1 stranger entry.
- [x] Refreshed `sha256`; `load_manifest(..., images_dir=...)` passes.

### Checklist for Slice 2: Caption fixtures + schema extension

- [x] Added optional `GoldenEntry.base_caption`; bumped `SUPPORTED_MANIFEST_VERSION`→2; synced `draft_labels.py:84` + test version literals.
- [x] Populated `context_pack`, `base_caption`, `must_right`, `easy_wrong` (roster-closed); set `manifest_version: 2`.
- [x] Proof: no `RubricEmptyWarning`; stub-score insertion/Must-Right non-zero.

### Checklist for Slice 3: Face/region fixtures for E19-4a

- [x] Extended `seed_roster.py` with an idempotent scene-image seed path.
- [x] Authored `phrase_boxes.json` (mock boxes + 1:1 containment mapping, incl. stranger case).
- [x] Proof: `identification_pr.true_rejections >= 1`; containment 1:1 offline.

### Checklist for Slice 4: Bootstrap doc + version note + evidence

- [x] Updated `seed/README.md` (version, rubric/confirmation status, rsync, phrase boxes).
- [x] Captured deterministic seeded-stub score evidence; archived report.

## Review Readiness

- [x] No scoring-logic edits; only the additive `base_caption` field + version bump in `manifest.py`.
- [x] Fixture integrity verified against `$GOLDEN_IMAGES_DIR` (sha256, roster closure, `face_count`).
- [x] Handoff decision records the population, the stranger-entry gate result, and the E19-4a coordination point.

## Stretch Goals

- [ ] Objects/tag-coverage fixtures for `score_caption(objects=...)` tag-coverage signal.
- [x] Second stranger entry with a roster person also present (mixed true-rejection case, `face_metrics.py:116`).

## Success Criteria

- [x] `cli score` against a seeded stub run record yields non-vacuous, non-zero caption + `insertion_rate`; `must_right_defined_images > 0`; no `RubricEmptyWarning`. Face detection/identification are **REFUSED** on the current `roster_only` unboxed golden (exit 3) — they are not published P/R.
- [x] The stranger entry is still present in the golden; identification P/R is not computed from unboxed claims, so `identification_pr(...).true_rejections` is not a published number on this artifact.
- [x] `load_manifest(golden.json, images_dir=$GOLDEN_IMAGES_DIR)` passes at `manifest_version: 3`.
- [x] `cli score --check-determinism` is bit-identical across re-runs (exit 3; refused face metrics).
- [x] E19-4a can load `phrase_boxes.json` + seeded scene-face bboxes and exercise 1:1 containment offline.
