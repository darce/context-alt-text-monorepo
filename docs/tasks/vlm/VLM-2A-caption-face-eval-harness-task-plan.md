# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-05 22:45 EST
> - **Author**: Claude Fable 5
> - **Project**: `apps/prototype-description-service` (standalone task plan; grounding docs: [caption-context-enrichment-assessment-2026-07-05.md](../../assessments/current/caption-context-enrichment-assessment-2026-07-05.md) §6a–6c, [context-aware-image-description-roadmap-2026-06-13.md](../../roadmaps/context-aware-image-description-roadmap-2026-06-13.md))
> - **Task ID**: `VLM-2A`
> - **Target Branch**: `feature/vlm-2a`
> - **Review Coverage Target**: 2

---

## VLM-2A. Caption-Quality + Face-Recognition Eval Harness (bare MVP)

## Objective

Ship the smallest useful eval harness that scores generated image descriptions (deterministic caption-metric tier from the parent assessment) **and** face-recognition precision/recall against the labeled 38-image test bed, running locally as a CLI while all inference happens on the remote OCI A1 service.

## Intake

- **Scope one-pager**: [docs/scopes/vlm-2a-caption-face-eval-harness-scope.md](../../scopes/vlm-2a-caption-face-eval-harness-scope.md)
- **Key Q&A decisions**: MCP decision #1227 (`claude_vlm2a_scope_intake_eval_harness`) — heuristic-answered intake Q1–Q7 (smallest cut, face P/R definitions, completion signal, edge ledger, non-functional posture, fixture policy, ground-truth labeling).
- **Not-Doing**: ROC/threshold sweeps and TAR@FAR pair verification; LLM-judge implementation (flag + stub only); CI gating/dashboards/UI; new server endpoints or auth changes; laptop-local inference; celebrity/LFW ingestion; fairness cohort analysis beyond per-identity macro; vendoring the 59 MB corpus in git.

## Problem Statement

No caption-quality or recognition-accuracy scoring exists anywhere (assessment §6a inventory: latency/RSS benchmark only, empty fixture slot, un-captioned archive corpus, unrelated clustering harness). Every upcoming decision — detailed-tier model bake-off, identity-prose merge acceptance, fusion gating — is currently blind. Wrong-name insertion is the top product risk and is unmeasured.

## Constraints

- Laptop (M1, 8 GB) performs **no model inference**; remote OCI A1 endpoints do all vision work. Concurrency 1 against the shared box (live demo must not degrade).
- No new auth surfaces: reuse the existing dev API key from `.env`; no unauthenticated endpoints.
- No new server code paths (endpoints or writes). The harness writes only ordinary ingest/curation *data* — into a **dedicated eval tenant** (minted via the existing `/admin` tenant surface) so eval media and clusters never touch the demo tenant.
- Fixtures (59 MB) are not vendored in git; manifest carries per-image `sha256` and a documented rsync bootstrap from `/Volumes/Butter/archives/archived-recognition-service/scripts/`.
- Deterministic metric tier only; LLM-judge tier is a flag + interface stub (assessment §6c tiers 1–2, 5–7).
- Metric definitions follow the parent assessment §6c and the scope note's face-P/R definitions (detection level vs identification level; micro + per-identity macro).

## Workflow Principles

- Metrics are pure functions over recorded responses — unit-testable on CPU with no network (Split Phase: fetch phase produces a run record; score phase consumes it).
- Remote calls follow Nygard discipline: explicit per-request timeout, circuit-break after 3 consecutive failures, per-item failure isolation with bounded-stall non-zero exit (rg-007).
- Manifest and fixture loading validate structure + hashes at load time and fail fast (rg-008).
- Report builder mirrors the existing clustering `regression_harness` baseline/report pattern; no code sharing across service boundaries required.

## Terminology

- **Golden manifest**: `scene/tests/seed/golden.json` — per image: relative path, `sha256`, **stable synthetic `media_id` (int; the analyze contract keys uploads as `image_<media_id>` parts and identity reads group by `media_id`)**, present-identity labels, context-pack fixture, Must-Right/Easy-Wrong rubric entries, policy flags.
- **Roster seeding**: one-time idempotent setup of the eval tenant — ingest the 18 entity crops, run a clustering job, label + confirm the resulting clusters with the entity names so identification-level scoring has server-side ground truth.
- **Detection-level P/R**: faces found vs faces labeled present, identity-agnostic.
- **Identification-level P/R**: named-identity assertions vs labeled identities; wrong-name = false positive **and** listed individually in the report.
- **Insertion rate**: % of confirmed identities that appear in the generated description (assessment §6c tier 2).
- **Run record**: JSON capture of raw remote responses + provenance (model/adapter version, cache hit/miss, manifest version, HEAD SHA) enabling offline re-scoring.

## Current State Analysis

- `apps/prototype-description-service/scripts/benchmark_local_vlm.py` — latency/RSS skeleton with adapter loop + JSON emission; local-adapter oriented, no scoring, no remote client.
- `scene/tests/seed/` — empty fixture placeholder (`.gitkeep` + README) reserved for exactly this purpose.
- `recognition/application/regression_harness/` — clustering-only; its report-builder/baseline pattern is the structural template.
- Remote surface (verified 2026-07-06): `POST /scene/describe/multipart` (API-key auth, tenant-scoped) returns visual facts + alt-text draft. Recognition path is **async three-step**: `POST /recognition/analyze/multipart` (202 + `JobStatusResponse`, one `image_<media_id>` part per upload; `analyze_multipart.py:185`) → `GET /recognition/jobs/{job_id}` (poll; `analyze.py:337`) → `GET /recognition/media/identities?media_ids=…` (identities grouped by `media_id`; `media.py:16`). The scope note's "identity read path" assumption is resolved — no contingency endpoint needed.
- **Identification-level scoring precondition:** the service names only labeled, confirmed clusters. The eval tenant starts empty — roster seeding (Terminology) is required before face identification P/R is meaningful; identification recall is structurally zero without it.
- Archive test bed: 38 scene photos + 18 `entity-<name>` face crops with names encoded in filenames; no reference labels exist yet.

## Target Outcome

`make eval-captions` (repo-root target, description-service scoped) runs the 38-image manifest end-to-end from the laptop, produces a JSON artifact (E19-1 schema extension) + markdown report containing: caption deterministic metrics, face detection-level and identification-level P/R (micro + per-identity macro), individually listed wrong-name errors, per-item failures, and full provenance; a second run over unchanged inputs reproduces identical deterministic numbers; a baseline artifact is committed as evidence.

## Context Loading

- Parent assessment §6a (MVP definition), §6b (taxonomy — the 38-image corpus seeds identity/scene classes; remaining classes are future manifest additions), §6c (metric stack and gating philosophy).
- Scope note Q&A (auth interpretation, fixture policy, P/R definitions, edge-case ledger).
- Apple face-recognition papers (`literature/extracted/recognition/apple/*.txt`) — detection-vs-identification split, per-cohort reporting rationale (Fair-SA), threshold-fixed evaluation rationale (ArcFace-lineage protocols need pair construction; out of MVP).
- `docs/workbay/rules/testing-python.md` for test conventions.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `/scene/describe/multipart` request/response | backend | `scene/interface_adapters/http/schemas/{requests,responses}.py` | none (harness is a pure client) | n/a | live smoke asserts response shape |
| Eval artifact JSON | harness (this task) | new — additive extension of E19-1 benchmark JSON (`metrics`, `faces` sections) | new schema, documented in `scripts/eval_harness/README.md` | no (new consumer-less artifact; E20-11 may consume later) | `report.py` golden-file test |
| Recognition analyze + identity read | backend | `POST /recognition/analyze/multipart` (202+job), `GET /recognition/jobs/{job_id}`, `GET /recognition/media/identities` (`analyze_multipart.py:185`, `analyze.py:337`, `media.py:16`) | none (harness is a pure client; eval-tenant data writes only) | n/a | live smoke: seeded identity returned for a known media_id |
| DB models / `ContextPack` | backend | `db/models/*`, `requests.py` | none | n/a | no migration in diff |

## Proposed Solution

Two-phase CLI under `apps/prototype-description-service/scripts/eval_harness/`: `fetch` (manifest → remote calls → run record on disk) and `score` (run record → metrics → JSON + markdown reports). `run` composes both; `seed-roster` is a separate idempotent subcommand. Key public symbols (junior-agent anchors): `manifest.load_manifest(path) -> GoldenManifest` (pydantic, sha256 + structure fail-fast; entries carry `media_id`), `remote_client.RemoteSceneClient.describe(image, context_pack)`, `.analyze(images) -> job_id`, `.wait_job(job_id)`, `.media_identities(media_ids)` (httpx, explicit timeout, 3-strike breaker; job polling with bounded wait), `seed_roster.seed(entities_dir)` (ingest 18 crops → clustering job → label + confirm clusters via the existing curation surface — the same cluster-label/confirm operations the WP roster sync performs; exact endpoint selection recorded in the slice decision; safe to re-run), `caption_metrics.score_caption(caption, golden_entry) -> CaptionScores` (insertion rate, Must-Right gates, FKRE, length error, repetition, tag coverage), `face_metrics.detection_pr(pred_faces, labeled_faces)` and `face_metrics.identification_pr(pred_identities, labeled_identities) -> PrResult` (micro + per-identity macro, wrong-name list), `report.build_reports(run_record, scores) -> (json, md)` following the regression-harness builder pattern with a persistent ignore-list file for triaged judge/label false positives. Run records and generated reports are written to a git-ignored `scripts/eval_harness/out/` directory; retention = keep-last-N (default 10, documented in README) with only curated baseline artifacts promoted into `docs/tasks/vlm/` — no unbounded accumulation (steady-state rule).

## Files and Surfaces to Change

- `apps/prototype-description-service/scripts/eval_harness/` (new: `__init__.py`, `cli.py`, `manifest.py`, `remote_client.py`, `seed_roster.py`, `caption_metrics.py`, `face_metrics.py`, `report.py`, `README.md`)
- `apps/prototype-description-service/scene/tests/seed/golden.json` (new) + `seed/README.md` (update: bootstrap instructions)
- `apps/prototype-description-service/scene/tests/test_eval_harness_*.py` (new unit tests)
- `Makefile` / `mk/` — `eval-captions` target
- `docs/tasks/19.0/`-style evidence artifact for the baseline run (committed under `docs/tasks/vlm/`)

## Related Files

- `apps/prototype-description-service/scripts/benchmark_local_vlm.py` (skeleton reference; stays untouched)
- `apps/prototype-description-service/recognition/application/regression_harness/metrics.py` (pattern reference)
- `apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py` (client contract)
- `/Volumes/Butter/archives/archived-recognition-service/scripts/mock_images/`, `mock_entities/` (fixture source, read-only)

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && .venv/bin/python -m pytest scene/tests/test_eval_harness_manifest.py scene/tests/test_eval_harness_caption_metrics.py scene/tests/test_eval_harness_face_metrics.py scene/tests/test_eval_harness_report.py -q` — metric table-driven cases cover the scope-note edge ledger (zero-face null precision, stranger true-rejection, duplicate-identity dedupe, policy-disabled exclusion, macro-vs-micro divergence); loader rejects missing file / hash mismatch / malformed labels (rg-008); report golden-file test. No network.
- Runtime-parity / environment checks:
  - `cd apps/prototype-description-service && ACX_EVAL_LIVE=1 .venv/bin/python -m scripts.eval_harness.cli seed-roster --entities "$GOLDEN_IMAGES_DIR/mock_entities"` — idempotent eval-tenant seeding; verify by fetching `/recognition/media/identities` for a seeded crop. Requires `ACX_EVAL_BASE_URL`, `ACX_EVAL_API_KEY`, and `ACX_EVAL_TENANT_ID` (exit 1 without them).
  - `cd apps/prototype-description-service && ACX_EVAL_LIVE=1 .venv/bin/python -m scripts.eval_harness.cli run --manifest scene/tests/seed/golden.json --limit 3` — live smoke: auth via existing `.env` key, analyze→poll→identities round trip, timeout handling, run-record shape. (The `cd` prefix is load-bearing: the repo root has a different `scripts/` package.) Exit 1 if the three eval env vars are unset.
- Contract/fixture verification:
  - Copy the baseline out of tree first (`WORK=$(mktemp -d) && cp ../../docs/tasks/vlm/VLM-2A-baseline-20260706-run-record.json "$WORK/run.json"`), then `cd apps/prototype-description-service && .venv/bin/python -m scripts.eval_harness.cli score --run-record "$WORK/run.json" --manifest scene/tests/seed/golden.json --check-determinism` — re-score committed baseline; deterministic sections are bit-identical. **Expected exit 3**: current golden is `roster_only` and identity claims are unboxed, so detection and identification are REFUSED. That is not a failed determinism check. Pass `--allow-refused` only if you want process exit 0 on the same refused report.
- Manual verification:
  - Operator confirmation pass over draft presence labels (Slice 1, one-time).

## Slice Delivery

### Slice 1: Golden manifest + fixture bootstrap

**Goal**: A validated, human-confirmed golden manifest exists and loads fail-fast.

Changes:

- `scripts/eval_harness/manifest.py` (`load_manifest`, pydantic `GoldenManifest` with per-entry `media_id`), sha256 + structure validation (rg-008)
- Draft-label generator from `entity-*`/scene filenames; operator confirmation captured into `scene/tests/seed/golden.json`
- `scene/tests/seed/README.md` rsync bootstrap instructions; absence of `GOLDEN_IMAGES_DIR` = clean actionable error
- `scene/tests/test_eval_harness_manifest.py`

Proof:

- `uv run pytest scene/tests/test_eval_harness_manifest.py -q` green; `golden.json` committed with 38 entries + 18-name roster.

### Slice 2: Remote client + metric engines

**Goal**: Fetch phase produces run records against the OCI service; metric engines score them as pure functions.

Changes:

- `scripts/eval_harness/remote_client.py` (`RemoteSceneClient.describe/.analyze/.wait_job/.media_identities`; timeout, 3-strike breaker, bounded job-poll wait, per-item isolation, bounded-stall exit rg-007, provenance capture)
- `scripts/eval_harness/seed_roster.py` (`seed(entities_dir)`): idempotent eval-tenant roster seeding — ingest 18 crops via `/recognition/analyze/multipart`, clustering job, label + confirm clusters via existing curation surface; endpoint selection recorded in slice decision
- `scripts/eval_harness/caption_metrics.py` (`score_caption`), `face_metrics.py` (`detection_pr`, `identification_pr`)
- `scene/tests/test_eval_harness_caption_metrics.py`, `test_eval_harness_face_metrics.py` (full edge ledger)

Proof:

- Metric unit suites green (no network); `seed-roster` then `run --limit 3` smoke: `/media/identities` returns a seeded name for a known `media_id`; valid run record produced.

### Slice 3: Reports, make target, baseline evidence

**Goal**: One command produces the full scored report; baseline committed.

Changes:

- `scripts/eval_harness/report.py` (`build_reports`, ignore-list), `cli.py` (`fetch`/`score`/`run`), `out/` retention keep-last-N
- `make eval-captions` target; `scripts/eval_harness/README.md` (schema doc, bootstrap, retention)
- Baseline 38-image artifact promoted to `docs/tasks/vlm/`; determinism re-score check

Proof:

- `make eval-captions` end-to-end on laptop; committed baseline; `--check-determinism` diff-clean; report lists every wrong-name error individually.

## Consolidated Checklist

- [ ] Manifest schema + loader with sha256/structure fail-fast validation and tests
- [ ] Draft labels from filename heuristics + operator confirmation pass captured in `golden.json`
- [ ] Fixture bootstrap documented (rsync one-liner; absence = clean actionable error)
- [ ] Remote client with timeout, 3-strike circuit breaker, bounded job-poll wait, per-item isolation, bounded-stall exit
- [ ] Idempotent roster seeding of the dedicated eval tenant (18 entity crops → clustering → labeled + confirmed clusters)
- [ ] Caption deterministic metrics implemented + unit-tested (insertion rate, Must-Right gates, FKRE, length error, repetition, tag coverage)
- [ ] Face detection-level and identification-level P/R implemented + unit-tested (micro + per-identity macro; wrong-name errors listed)
- [ ] JSON artifact (E19-1 schema extension) + markdown report with ignore-list
- [ ] `make eval-captions` target + harness README
- [ ] Env-gated live smoke passes against OCI service
- [ ] Full 38-image baseline artifact committed; re-run determinism verified
- [ ] LLM-judge tier flag + interface stub only (no implementation)

## Context and Ownership

Owner: description-service backend lane. Fixture confirmation pass requires the operator (labels reference real people from the archive test bed). All other work is agent-executable.

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Recorded boundary ownership and compatibility expectations if any contract is touched.

### Checklist for Slice 1: Golden manifest + fixture bootstrap

- [x] `manifest.py` + pydantic schema + loader tests (missing/hash-mismatch/malformed)
- [ ] Heuristic label draft generator + operator confirmation captured
- [ ] `seed/README.md` bootstrap instructions

### Checklist for Slice 2: Remote client + metric engines

- [x] `remote_client.py` (describe/analyze/wait_job/media_identities) with Nygard discipline + provenance capture
- [x] `seed_roster.py` idempotent seeding; seeded identity verified via `/media/identities`
- [x] `caption_metrics.py`, `face_metrics.py` + table-driven edge-ledger tests

### Checklist for Slice 3: Reports, make target, baseline evidence

- [x] `report.py` JSON + markdown + ignore-list, golden-file test
- [x] `cli.py` `fetch`/`score`/`run`; `make eval-captions`
- [ ] Live smoke + committed baseline + determinism re-run

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence (boundary table row 3 contingency recorded in slice decision if exercised).
- [ ] Runtime-parity checks included where tests can mask real behavior (env-gated live smoke).
- [ ] Each slice closes with `close_slice` + fresh `test_result` evidence tied to HEAD; branch review via `/branch-review` before merge; pre-merge gate (`handoff_close_check(enforce=True)`) applies.

## Stretch Goals

- [ ] Manifest entries for the remaining assessment §6b taxonomy classes (abstract, UI screenshot, context-conflict) as images are curated.
- [ ] Offline re-score mode consuming archived run records for metric iteration without re-hitting the service.

## Success Criteria

- One command, laptop-local, zero local model weights, zero new auth surfaces, concurrency 1.
- Deterministic metrics bit-identical across re-runs on unchanged manifest + service version.
- Face P/R reported at both levels, micro + per-identity macro; every wrong-name error individually visible.
- Baseline artifact consumable by the assessment §12 bake-off gate.
