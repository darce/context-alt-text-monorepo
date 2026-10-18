# VLM-2C — Golden-Manifest Population — Scope Note

> **Status:** Scope intake (pre-task-plan). Feeds `VLM-2C` task-plan drafting.
> **Date:** 2026-07-06
> **Task ID:** `VLM-2C`
> **Target Branch:** `feature/vlm-2c`
> **Parent program:** E19 Context-Aware Image Description (v0.5.0) / VLM caption+face eval harness (VLM-2A shipped the code).
> **Scope source:** VLM-2A scope `docs/scopes/vlm-2a-caption-face-eval-harness-scope.md` (Q6 fixtures, Q7 labeling); E19-4a scope `docs/scopes/e19-4a-identity-prose-merge-scope.md`.

## Problem

VLM-2A shipped the harness **code** (`apps/prototype-description-service/scripts/eval_harness/`) but not its **ground-truth fixtures**. `scene/tests/seed/golden.json` has 37 entries, all with:

- `context_pack {}` empty — the model sees no name-injected WP text, so `insertion_rate` measures nothing.
- `must_right []` / `easy_wrong []` empty — the caption hard gate and Easy-Wrong rubric are vacuous (`load_manifest` emits `RubricEmptyWarning`; report shows `must_right_defined_images: 0`).
- No base caption per entry — no deterministic reference string for offline scoring or for E19-4a reflow.
- No stranger / non-roster entry — every entry has `face_count == len(present_identities)` (`stranger_faces == 0`), so `identification_pr`'s true-rejection path (`face_metrics.py:116`) is exercised by **zero** fixtures. Wrong-name insertion is the top product risk and is currently untested.
- No scene-image face regions in the recognition tenant — `seed_roster.py` seeds only the crop clusters (`CROP_MEDIA_ID_BASE = 1001`) and **never** the scene images, so no server-side `MediaIdentity` bbox exists per scene `media_id`.

Three downstream plans read structurally zero as a result: E19-4a identity→prose merge, VLM-2B model bake-off, E20-11 provider benchmark.

## Consumers this unblocks

| Consumer | Reads (grounded) | Blocked-by-empty deliverable |
| --- | --- | --- |
| **E20-11 provider benchmark** + **VLM-2B bake-off** | `caption_metrics.score_caption` / `insertion_rate` over `present_identities`, `must_right`, `easy_wrong`, `policy.recognition_enabled`; the describe route echoes `context_pack` | Context packs, Must-Right/Easy-Wrong rubrics, base captions |
| **E19-4a identity→prose merge** | server-side `MediaIdentity`(bbox)→cluster join keyed on scene `media_id`; mock/seeded phrase boxes; containment 1:1; "never a guessed name" gate | Scene-image face seeding, phrase-box fixture, expected identities, ≥1 stranger entry |
| **E19-4a + face_metrics** | `face_metrics.identification_pr` true-rejection (`stranger_faces > 0`) | ≥1 stranger / non-roster entry |

## MVP scope (in)

1. **Context packs** per entry — populate `ContextPack {title, caption, description}` with the name-injected WP text the model sees (`manifest.py:44`, `extra='allow'`). Unblocks `insertion_rate` for E20-11 / VLM-2B / E19-4a.
2. **Base captions** per entry — the reference string `score_caption` matches and E19-4a reflows. Not a current `GoldenEntry` field (`extra='forbid'`); carried via a **bounded additive schema extension** (new optional `base_caption`) + `SUPPORTED_MANIFEST_VERSION` bump 1→2.
3. **Must-Right / Easy-Wrong rubrics** + **expected identities** per entry — non-vacuous caption gate + insertion traps; all names must stay inside `manifest.roster` (loader enforces, `manifest.py:161`).
4. **≥1 stranger / non-roster entry** — `recognition_enabled=true`, `face_count > len(present_identities)`, so `stranger_faces > 0` drives a true-rejection and the "never a guessed name" gate (E19-4a core risk).
5. **Scene-image face regions** — extend/parallel `seed_roster.py` to also seed the scene images so recognition produces `MediaIdentity` bboxes per scene `media_id`; plus a **mock phrase-box fixture** + expected containment mapping for E19-4a's offline merge tests.
6. **Ground-truth labeling** — draft via `draft_labels.generate_draft_manifest` filename heuristics, then a **single documented human-confirmation pass** (VLM-2A Q7): confirm `present_identities`, set true `face_count` (incl. strangers), author context packs / captions / rubrics. Refresh per-image `sha256`; update the `seed/README.md` rsync bootstrap + version note.

## Assumptions

- Corpus lives at `/Volumes/Butter/archives/archived-recognition-service/scripts/{mock_images,mock_entities}/` (38 scene photos + 18 crops, 59 MB, not vendored); names encoded in filenames. Reads stay inside this and the worktree.
- Roster is the 10 confirmed names already in `golden.json`; `draft_labels` derives it from `entity-*` crops (`naming.entity_slug`/`display_name`).
- `context_pack` name-injection is the intended `insertion_rate` signal source — an empty pack, not a model defect, is why the metric currently reads zero.
- E19-4a phrase-box format (bbox in `[0,1]` fractions, person-phrase text, 1:1 containment) per its scope §1/S1; final field names coordinated with the E19-4a merge service when it lands.

## Not-Doing

- **No new metric code.** No changes to `caption_metrics.py` / `face_metrics.py` / `report.py` scoring logic. This is fixtures + the minimal manifest-schema extension that carries them (new optional field + version bump), not harness re-design.
- **No VLM caption inference / no bake-off run.** No live `describe`-route model runs; offline demonstration uses a seeded stub run record fed to `cli score`.
- **No CI gate.** No new `make check-all` wiring; VLM-2A retention/`make eval-captions` unchanged.
- No external celebrity/LFW ingestion (Q7); the 38-image bed is the corpus.
- No E19-4a merge service implementation — this delivers its fixtures only.

## Success criteria

- `cli score` against a seeded stub run record (caption = each entry's `base_caption`) yields **non-vacuous, non-zero** caption + `insertion_rate` numbers and non-zero face detection/identification P/R (`report.build_reports`); no `RubricEmptyWarning`, `must_right_defined_images > 0`.
- The stranger entry yields a **true rejection** (`identification_pr(...).true_rejections >= 1`), not a wrong name.
- `load_manifest(golden.json, images_dir=$GOLDEN_IMAGES_DIR)` passes: every `sha256` matches, `face_count >= len(present_identities)`, all names in roster, version accepted by the bumped loader.
- Deterministic re-run: `cli score --check-determinism` (or two score passes) is bit-identical.
- E19-4a can load the phrase-box fixture + seeded scene-face bboxes and exercise 1:1 containment offline.

## Slice outline (seeds the task plan)

- **S1** Draft + human-confirm ground truth: `present_identities`, `face_count` (incl. strangers), ≥1 stranger entry; refresh `sha256`.
- **S2** Caption fixtures: `context_pack`, `base_caption` (schema extension + version bump), `must_right`, `easy_wrong`.
- **S3** Face/region fixtures: extend `seed_roster.py` to seed scene images; mock phrase-box fixture + expected containment mapping.
- **S4** Bootstrap doc + version note refresh; deterministic-score + stranger true-rejection evidence.
