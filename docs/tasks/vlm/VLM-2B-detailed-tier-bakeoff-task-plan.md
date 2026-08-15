# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-06 EST
> - **Author**: Claude Opus 4.8
> - **Project**: `apps/prototype-description-service` (standalone task plan; feeds **Epic E19** detailed-description tier)
> - **Task ID**: `VLM-2B`
> - **Target Branch**: `feature/vlm-2b`
> - **Review Coverage Target**: 2
> - **Grounding docs**: [caption-context-enrichment-assessment-2026-07-05.md](../../assessments/current/caption-context-enrichment-assessment-2026-07-05.md) §10, §12 item 4, §6c, §11, §13 · [vlm-2b-detailed-tier-bakeoff-scope.md](../../scopes/vlm-2b-detailed-tier-bakeoff-scope.md) · [VLM-2A-caption-face-eval-harness-task-plan.md](./VLM-2A-caption-face-eval-harness-task-plan.md)

---

## VLM-2B. Detailed-Tier Caption Model Bake-Off

## Objective

Bake off three GGUF detailed-tier caption candidates — **CapRL-Qwen3VL-4B**, **Qwen3-VL-4B-Instruct**, **MiniCPM-V 4.5** — over ~10 golden images with real (name-injected) context packs, score each with the VLM-2A deterministic caption-metric tier, and produce **one decision memo picking a single model with evidence**. The winning model becomes a `DescriptionAdapter` in a follow-on task; this task ends at the pick.

## Intake

- **Scope one-pager**: [docs/scopes/vlm-2b-detailed-tier-bakeoff-scope.md](../../scopes/vlm-2b-detailed-tier-bakeoff-scope.md)
- **Derivation**: approved parent assessment (decision input); no P0 Q&A — assumptions documented in the scope note §3.
- **Not-Doing**: adapter productionization; `DescriptionProfile`/`PROFILE_SPECS` registry entry; ROC/threshold/TAR@FAR sweeps; LLM-judge implementation; fusion / E19-4a merge / phase-split caching; new auth/endpoints/server paths; OpenCV 5 / brand / PG18-19; CI gating/dashboards/UI; fast-tier (MiniCPM-V 4.6) evaluation; vendoring weights or corpus in git.

## Problem Statement

The assessment commits to a detailed-description tier but leaves the model unchosen, and **no public benchmark measures injected-name weaving** — the property that decides product fitness (assessment §10). CapRL's instruction obedience is explicitly unknown and potentially disqualifying (§13); the 1–3 min/img A1 GGUF estimate is unverified (§13). VLM-2A shipped the scoring harness (`scripts/eval_harness/`) but its 2026-07-06 baseline scored only the model-free `seeded` stub adapter (`seeded-fixtures`, insertion rate 0.000 over 37 all-empty context packs, zero rubric entries — a harness shakedown, not a caption baseline; see `VLM-2A-baseline-20260706-report.md`) — the detailed-tier candidates are unscored. Without an owned, deterministic bake-off, the detailed-tier model choice is a blind bet on the top product risk (wrong-name/wrong-fact insertion).

## Constraints

- **Infra posture (same as VLM-2A):** the laptop performs **no** model inference; each candidate runs as a llama.cpp server on the **OCI A1 CPU**, driven remotely. **Concurrency 1**; run one model at a time, off the live-demo path — the shared box must not degrade.
- **Failure posture:** per-request timeout, per-item failure isolation, **bounded consecutive-failure exit (rg-007)** — mirror the discipline in `scripts/eval_harness/remote_client.py` (`_BREAKER_THRESHOLD = 3`, `_DEFAULT_TIMEOUT_S = 60.0`) and `scripts/eval_harness/cli.py` (`BoundedStallError`, `DEFAULT_STALL_LIMIT = 5`).
- **Decoding:** greedy; append `/no_think` for any reasoning-tuned candidate; identical decode config across candidates for comparability.
- **Deterministic metric tier only** — the LLM-judge tier stays a stub (VLM-2A rejects `--llm-judge` in `cli._reject_llm_judge`).
- **Greenfield:** no schema migration; the bake-off manifest is a new fixture, not a change to `scene/tests/seed/golden.json` structure — it reuses the `manifest.GoldenManifest` schema (`SUPPORTED_MANIFEST_VERSION = 1`) with no new fields.
- **No productionized adapter:** the bake-off runner is throwaway benchmark code; it must **not** register a `DescriptionProfile` or add a `PROFILE_SPECS` entry.

## Workflow Principles

- **Split Phase (as VLM-2A):** a fetch phase produces an `acx-eval/v1` run record of raw candidate outputs + provenance; a pure score phase (`report.score_run_record`) consumes it offline, bit-identical for unchanged inputs.
- **Reuse over rebuild:** scoring, manifest validation, schema ids, the markdown report builder, **and the manifest walker `cli.fetch_run_record()` are reused unchanged** from `scripts/eval_harness/`. The **only** genuinely-new piece is the `BakeoffClient` transport (candidate llama.cpp endpoints instead of `/scene/describe/multipart`), injected into the existing walker; the bake-off manifest is the only new fixture. `fetch_run_record()` already isolates per-item failures and bounds stalls (rg-007) — forking a second walker would duplicate that logic and its tests for no gain.
- **Merge-only naming discipline (assessment §3a):** the prompt supplies roster names in the context block under an anchor-visual/inject-factual contract; the metric measures whether the model *weaves the supplied name*, never whether it guesses one.
- **Name-injection surface (candidates do NO recognition):** injected roster names must appear in the **`context_pack` TEXT the model actually sees**, not in `present_identities` (which the model never receives). `fetch_run_record()` passes `entry.context_pack.model_dump(exclude_none=True)` into `client.describe(context_pack=...)`; the bake-off carries injected names + non-visible facts in `ContextPack.caption` / `ContextPack.description` (existing typed fields), and `BakeoffClient.describe()` renders that context text into the candidate prompt (the anchor-visual/inject-factual block). `ContextPack` uses `extra='allow'`, so if a dedicated field is preferred it can be added with **no schema change** — but the prompt-render contract is: every injected name in `context_pack` reaches the model prompt verbatim, or insertion rate is structurally unmeasurable.
- **Evidence before verdict:** every candidate ships a before/after-comparable artifact; the memo cites artifacts, never prose impressions.

## Terminology

- **Bake-off subset manifest**: a new `~10`-image golden manifest (e.g. `scene/tests/seed/bakeoff_golden.json`) validated by `manifest.load_manifest`; per image — path, `sha256`, `media_id`, `face_count` (required; validator rejects `face_count < len(present_identities)`), `present_identities`, **real `context_pack` carrying injected roster names + non-visible facts**, `must_right`/`easy_wrong` rubrics, `policy`.
- **Injected-name weaving / insertion rate**: `% present_identities` that appear in the caption when their names are supplied in the context block (`caption_metrics.insertion_rate`) — the primary discriminator.
- **Candidate run record**: an `acx-eval/v1` `DocKind.RUN_RECORD` doc whose items carry `describe.alt_text_draft` (candidate caption) + `describe.adapter/model_id/model_version` so `report.score_run_record` scores it unchanged.
- **Bake-off runner**: throwaway remote client hitting a candidate's llama.cpp endpoint; **not** a `DescriptionAdapter`.

## Current State Analysis

- **Scoring harness exists and is reusable** (`apps/prototype-description-service/scripts/eval_harness/`): `caption_metrics.score_caption()` + `caption_metrics.insertion_rate()` compute the deterministic caption tier; `report.score_run_record()` / `report.build_reports()` emit the `acx-eval/v1` JSON + markdown; `schema.SCHEMA = "acx-eval/v1"` with `schema.DocKind.{RUN_RECORD,REPORT}`; `manifest.load_manifest()` fail-fast-validates the golden manifest. All pure, CPU-only, no network.
- **Fetch path targets the deployed service**, not raw models: `remote_client.RemoteSceneClient.describe()` calls `POST /scene/describe/multipart`; `cli.fetch_run_record()` walks the manifest with per-item isolation + `BoundedStallError`. `fetch_run_record` is transport-agnostic — it calls `client.describe(...)`, `client.analyze(...)`, `client.wait_job(...)`, `client.media_identities(...)` on an injected `client`. The bake-off **reuses `fetch_run_record` unchanged** and injects a new `BakeoffClient` whose `describe()` hits a candidate llama.cpp endpoint and whose `analyze()`/`wait_job()`/`media_identities()` are no-op stubs (face metrics are out-of-band this task, scope §5). The scoring half is untouched.
- **Report reads exactly two describe fields**: `report.score_run_record()` scores `describe["alt_text_draft"]` and `describe["visual_facts"]["objects"]`, and provenance-stamps `describe["adapter"]/["model_id"]/["model_version"]` via `report._model_provenance()`. A candidate run-record item must populate `alt_text_draft` + provenance. **Candidates emit no `objects`**, so the tag-coverage metric is **N/A for this bake-off** — it is not a discriminator here and must not be read as one; likewise the REPORT's face-detection/identification sections are **vacuous** under the stub `analyze()`/`media_identities()` (zero faces recorded) and the memo must not cite them. The discriminators are insertion rate, Must-Right gate passes, wrong-fact signal, FKRE, and A1 latency/RSS.
- **Golden corpus lacks context packs** (verified): `scene/tests/seed/golden.json` = `manifest_version 1`, roster of 10 names, **37 entries, all `context_pack` empty (`{}`), zero `must_right`/`easy_wrong` rubric entries, all `recognition_enabled=true`**. Insertion rate is structurally zero without name-carrying context packs → Slice 1 must author a bake-off subset with real ones. **VLM-2C** populates the main `golden.json` context packs/rubrics separately; this task does **not** wait on it — the bake-off subset's packs are authored in-task (Slice 1). If VLM-2C lands first, reuse its packs for overlapping images rather than forking ground truth.
- **Adapter seam is stable** (target for the *follow-on*, informational here): `scene/application/description_adapter.py` `DescriptionAdapter` Protocol + `AdapterResult`; `scene/domain/description.py` `DescriptionAdapterKind`; `scene/config/profiles.py` `DescriptionProfile`/`ProfileSpec`/`PROFILE_SPECS`/`get_profile_spec()`. Precedent for a local-model benchmark runner: `scripts/benchmark_local_vlm.py` `main()` (adapter loop + JSON artifact + peak-RSS via `resource.getrusage`).
- **Model facts** (assessment §10): all three candidates ship official GGUF; A1 latency estimate (1–3 min/img) and CapRL injection obedience are both unverified (§13).

## Target Outcome

From the laptop, `uv run python -m scripts.eval_harness.bakeoff` (description-service scoped, driving remote A1 llama.cpp endpoints, concurrency 1) runs the ~10-image bake-off manifest against each candidate, writes an `acx-eval/v1` run record per candidate, and `report.build_reports` scores each into a JSON + markdown REPORT stamped with the candidate model id/version. A comparison table ranks candidates on insertion rate, Must-Right gate passes, wrong-fact signal, FKRE, and A1 latency/RSS. A decision memo picks one model with cited evidence and the license verdict. Re-scoring any captured run record is bit-identical.

## Context Loading

- Assessment §10 (candidate table + two-tier design), §12 item 4 (bake-off before adapter build), §6c (metric tiers + precision-gated philosophy), §11 (CPU-only A1 feasibility), §13 (open risks: GGUF quant loss, CapRL obedience, MiniCPM license).
- Scope note: [vlm-2b-detailed-tier-bakeoff-scope.md](../../scopes/vlm-2b-detailed-tier-bakeoff-scope.md).
- Harness surfaces to reuse: `scripts/eval_harness/{schema.py,manifest.py,caption_metrics.py,report.py,cli.py,remote_client.py}`; golden fixture `scene/tests/seed/golden.json` + `scene/tests/seed/README.md` (image rsync bootstrap, `GOLDEN_IMAGES_DIR`).
- Adapter seam (follow-on target, informational): `scene/application/description_adapter.py`, `scene/domain/description.py`, `scene/config/profiles.py`, `scripts/benchmark_local_vlm.py`.
- Rules: `docs/workbay/rules/testing-python.md`; rg-007 (bounded stall), rg-008 (fail-fast config), rg-015 (no fabricated envelope metadata).

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `acx-eval/v1` eval artifact schema | description-service (`scripts/eval_harness/schema.py`) | `schema="acx-eval/v1"`, `DocKind.{RUN_RECORD,REPORT}` | **none** — bake-off run records/reports reuse the identical schema; candidate model id/version fill existing `describe.model_id/model_version` fields | no | `report.build_reports` scores a candidate run record without change; `_cmd_score --check-determinism` passes |
| golden manifest schema | description-service (`scripts/eval_harness/manifest.py`) | `GoldenManifest` v1, `extra='forbid'`, `ContextPack extra='allow'` | **none** — new bake-off manifest instance, no new fields; context packs use the existing `ContextPack` extensibility | no | `manifest.load_manifest(bakeoff_golden.json)` passes fail-fast validation |
| candidate llama.cpp endpoint (A1) | infra (bake-off transient) | new: llama.cpp `/v1/chat/completions` or `/completion` per candidate | new throwaway client, not a service route; no change to `/scene/describe/multipart` | no | live A1 run under concurrency 1; per-item isolation + bounded-stall exit observed |
| `DescriptionAdapter` protocol / profiles | description-service (`scene/`) | `DescriptionAdapter`, `PROFILE_SPECS` | **none this task** — winner adapter is a follow-on; bake-off adds **no** profile entry | no | no diff under `scene/config/profiles.py` or `scene/application/description_adapter.py` |

## Proposed Solution

Add a **new transport client** to the existing eval harness and inject it into the unchanged manifest walker (`cli.fetch_run_record`), reusing the entire scoring half:

1. **Author a ~10-image bake-off manifest** with real, name-injected context packs + rubrics (assessment §6b discriminating classes), validated by `manifest.load_manifest`.
2. **Serve each candidate on the A1** via llama.cpp; re-benchmark A1 latency/RSS to resolve the §13 estimate and set the per-request timeout ceiling.
3. **Bake-off transport** (`scripts/eval_harness/bakeoff.py`): a `BakeoffClient` mirroring `RemoteSceneClient`'s Nygard discipline (timeout, 3-strike breaker) whose `describe()` prompts a candidate (greedy, `/no_think` if reasoning-tuned, anchor-visual/inject-factual context contract rendering the `context_pack` text into the prompt) and returns a `describe` dict with `alt_text_draft` + `model_id/model_version`, and whose `analyze()`/`wait_job()`/`media_identities()` are **no-op stubs** (face metrics out-of-band, scope §5). Drive it with the **unchanged `cli.fetch_run_record()`** — its per-item isolation + `BoundedStallError` bounded-stall already satisfy rg-007; no forked walker. A small `__main__` wires manifest + `BakeoffClient` + candidate endpoint into `fetch_run_record` and writes the `acx-eval/v1` `RUN_RECORD`.
4. **Score** each run record with the unchanged `report.build_reports()`; assemble a comparison table across candidates.
5. **Decision memo** picking one model, citing artifacts + license verdict + disqualifiers.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| tests/fixture | `apps/prototype-description-service/scene/tests/seed/bakeoff_golden.json` | New ~10-image bake-off manifest: real name-injected `context_pack`, `present_identities`, `must_right`/`easy_wrong`, `policy` per entry (validated by `manifest.load_manifest`) |
| tooling | `apps/prototype-description-service/scripts/eval_harness/bakeoff.py` | New `BakeoffClient` (candidate llama.cpp transport, Nygard discipline; `analyze`/`wait_job`/`media_identities` no-op stubs) + `__main__` CLI that drives the **unchanged `cli.fetch_run_record()`** to shape captions into `acx-eval/v1` run records. **No forked walker** (`fetch_bakeoff_record` is not built). |
| tests | `apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff.py` | (harness tests live in `scene/tests/test_eval_harness_*.py`; `scripts/` is in pytest `norecursedirs`.) Unit tests: `BakeoffClient.describe` returns a well-formed `describe` dict, `context_pack` names render into the prompt, greedy/`/no_think` prompt construction, stub methods are inert, and `report.build_reports` scores a `fetch_run_record`-shaped record deterministically (stub transport, no network). Per-item isolation + bounded-stall are **already covered by the reused `fetch_run_record`** — not re-tested here. |
| docs (evidence) | `docs/tasks/vlm/` (repo-level, matching `cli.py` retention docstring) | Per-candidate `acx-eval/v1` REPORT artifacts (curated baselines, promoted by hand per `cli.py` retention note) |
| docs (decision) | `docs/tasks/vlm/VLM-2B-detailed-tier-decision-memo.md` | Decision memo: comparison table, one winner, license verdict, disqualifiers, cited artifacts |

## Related Files

| File | Note |
| --- | --- |
| `scripts/eval_harness/caption_metrics.py` | `score_caption()`, `insertion_rate()`, `CaptionScores.gated_score` — reused unchanged for the deterministic tier |
| `scripts/eval_harness/report.py` | `score_run_record()`, `build_reports()`, `_model_provenance()` — reused unchanged; reads `describe.alt_text_draft` + `describe.visual_facts.objects` |
| `scripts/eval_harness/schema.py` | `SCHEMA="acx-eval/v1"`, `DocKind` — shared artifact ids |
| `scripts/eval_harness/manifest.py` | `load_manifest()`, `GoldenManifest`, `ContextPack`, `EntryPolicy` — validates the bake-off manifest |
| `scripts/eval_harness/remote_client.py` | `RemoteSceneClient`, `_BREAKER_THRESHOLD`, `_DEFAULT_TIMEOUT_S` — Nygard-discipline template for `BakeoffClient` |
| `scripts/eval_harness/cli.py` | `fetch_run_record()`, `BoundedStallError`, `DEFAULT_STALL_LIMIT` — **reused unchanged**; `BakeoffClient` is injected as its `client`. Not forked. |
| `scripts/benchmark_local_vlm.py` | `main()` + `_peak_rss_mb()` — precedent for a model benchmark runner emitting a JSON artifact |
| `scene/config/profiles.py` | `DescriptionProfile`/`PROFILE_SPECS` — the follow-on adapter's registration target (do **not** edit this task) |
| `scene/tests/seed/README.md` | `GOLDEN_IMAGES_DIR` rsync bootstrap for image bytes (not vendored) |

## Verification Strategy

- Deterministic tests (CPU, no network):
  - `.venv/bin/python -m pytest scene/tests/test_eval_harness_bakeoff.py` — `BakeoffClient.describe` shape, `context_pack` name-into-prompt rendering, prompt construction (greedy + `/no_think`), inert stub methods, and `report.build_reports` scoring a `fetch_run_record`-shaped record. (Per-item isolation + bounded-stall stay covered by the existing `cli.fetch_run_record` tests — not duplicated.)
  - Copy a candidate record out of tree (`mkdir -p /tmp/acx-eval-score && cp ../../docs/tasks/vlm/VLM-2B-bakeoff-Qwen3-VL-4B-Instruct-run-record.json /tmp/acx-eval-score/run.json`), then `.venv/bin/python -m scripts.eval_harness.cli score --run-record /tmp/acx-eval-score/run.json --manifest scene/tests/seed/bakeoff_golden.json --check-determinism` — re-score is bit-identical. **Expected exit 3**: `bakeoff_golden.json` is `roster_only` with unboxed identity claims, so detection and identification are REFUSED. Caption determinism is unaffected.
  - `.venv/bin/python -c "from scripts.eval_harness.manifest import load_manifest; load_manifest('scene/tests/seed/bakeoff_golden.json')"` — manifest passes fail-fast validation.
- Runtime-parity / environment checks (live A1, gated behind the VLM-2A live env-var pattern):
  - Serve each candidate on the A1; capture load time + per-image latency + peak RSS; confirm/deny the §13 1–3 min/img estimate; record the per-request timeout ceiling.
  - One live bake-off pass per candidate (concurrency 1, off-path) → run record → REPORT artifact.
- Contract/fixture verification:
  - A candidate run record scores through `report.build_reports` with the caption section populated and `provenance.model` stamped with the candidate id/version.
- Manual verification:
  - Decision memo comparison table reconciles with the committed per-candidate REPORT artifacts; the named winner's numbers match its artifact.

## Slice Delivery

### Slice 1: Bake-off manifest + real context packs

**Goal**: A validated ~10-image bake-off manifest whose context packs inject roster names so insertion rate is measurable.

Changes:

- Add `scene/tests/seed/bakeoff_golden.json` — ~10 images spanning assessment §6b discriminating classes (single roster person, two-roster-plus-strangers association, policy-disabled, abstract/hallucination-pressure, ~~legible-text~~, context-conflicts-pixels, no-context degradation), each with a real name-injected `context_pack`, `face_count` (≥ `len(present_identities)` per the `GoldenEntry` validator), `present_identities`, `must_right`/`easy_wrong`, `policy`.
  - **Scope note (Slice 1, dropped class):** *legible-text* is intentionally **not** covered as a measured class. The reused golden corpus (shared with VLM-2C — do not fork ground truth) has no committed image with legible in-image text paired with a name-injected context pack; the only text-subject image, `nina-machiavelli.jpeg`, is dual-purposed as the no-context degradation entry (empty `context_pack`). Adding a scoreable legible-text entry would require a new golden image + rubric, out of scope for a throwaway bake-off whose winner does not turn on text transcription. The other six classes remain covered and pinned by `test_manifest_covers_discriminating_classes`.
- Document the image-bytes bootstrap (`GOLDEN_IMAGES_DIR`) in the seed README if the subset draws new images.

Proof:

- `load_manifest('scene/tests/seed/bakeoff_golden.json')` passes; a unit test asserts every entry has a non-empty context pack and at least one `present_identity` for the insertion-rate cohort.

### Slice 2: Candidate serving + A1 re-benchmark

**Goal**: All three candidates load and run on the A1 with measured latency/RSS, resolving the §13 estimate and setting the timeout ceiling.

Changes:

- Serve CapRL-Qwen3VL-4B, Qwen3-VL-4B-Instruct, MiniCPM-V 4.5 as llama.cpp servers on the A1 (official GGUF quants), concurrency 1, off the demo path.
- Record cold-load + per-image latency + peak RSS per candidate into `docs/tasks/vlm/VLM-2B-a1-serving-notes.md`; set the per-request wall-clock timeout.

Proof:

- A latency/RSS table per candidate in `docs/tasks/vlm/VLM-2B-a1-serving-notes.md`; a candidate that cannot load or exceeds the ceiling is marked fail-per-item (not a run-aborter) — recorded, not fatal.

### Slice 3: Bake-off transport (client → reused walker → run record)

**Goal**: A throwaway `BakeoffClient` that elicits a greedy caption per candidate under the injected-context contract, driven by the **unchanged `cli.fetch_run_record`** so per-item isolation and bounded-stall come for free (rg-007).

Changes:

- Add `scripts/eval_harness/bakeoff.py`: `BakeoffClient` (candidate llama.cpp transport; per-request timeout; 3-strike breaker; `/no_think` when reasoning-tuned; anchor-visual/inject-factual prompt that renders the `context_pack` text — carrying the injected roster names — into the candidate prompt) whose `describe()` returns a `describe` dict with `alt_text_draft` + candidate `model_id/model_version`, and whose `analyze()`/`wait_job()`/`media_identities()` are **no-op stubs** (face metrics out-of-band, scope §5); expose a `base_url` attribute naming the candidate endpoint so `fetch_run_record` provenance stamps it. A `__main__` injects it into `cli.fetch_run_record` to emit the `acx-eval/v1` `RUN_RECORD`. **Do not fork the walker.**
- Add `scene/tests/test_eval_harness_bakeoff.py` (stub transport, no network).

Proof:

- `uv run pytest scene/tests/test_eval_harness_bakeoff.py` green: `describe` shape, `context_pack` names reach the prompt, greedy/`/no_think` prompt construction, inert stub methods; a `fetch_run_record`-shaped record scores through `report.build_reports`. (Isolation + bounded-stall are exercised by the existing `cli` tests, not re-implemented here.)

### Slice 4: Score, compare, decide

**Goal**: Per-candidate REPORT artifacts + a comparison table + a decision memo picking one model with evidence.

Changes:

- Run each candidate live (Slice 2 servers) → run record → `report.build_reports` REPORT artifact; commit curated artifacts under `docs/tasks/vlm/`.
- Add `docs/tasks/vlm/VLM-2B-detailed-tier-decision-memo.md`: comparison table (insertion rate, Must-Right passes, wrong-fact signal, FKRE, latency/RSS), one winner, license verdict (MiniCPM registration), disqualifiers (e.g. CapRL context obedience per §13).

Proof:

- Three committed REPORT artifacts + a memo naming one winner whose numbers reconcile with its artifact; `score --check-determinism` passes on each captured record.

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded assessment §10/§12/§6c/§11/§13, the scope note, and the VLM-2A harness surfaces before editing.
- [x] Confirmed the bake-off reuses `acx-eval/v1` schema + manifest schema with **no** new fields and **no** `PROFILE_SPECS` change.

### Checklist for Slice 1: Bake-off manifest + real context packs

- [x] Add `bakeoff_golden.json` (~10 images, §6b discriminating classes) with real name-injected context packs, rubrics, policy flags.
- [x] Document image-bytes bootstrap for any new images in the seed README.
- [x] `load_manifest` passes; test asserts non-empty context packs + insertion-rate cohort.

### Checklist for Slice 2: Candidate serving + A1 re-benchmark

- [x] Serve all three candidates on the A1 via llama.cpp (concurrency 1, off-path).
- [x] Record cold-load + per-image latency + peak RSS per candidate; set the per-request timeout ceiling.
- [x] Confirm or deny the §13 1–3 min/img estimate in `docs/tasks/vlm/VLM-2B-a1-serving-notes.md`.

### Checklist for Slice 3: Bake-off transport

- [x] Add `bakeoff.py` (`BakeoffClient` with Nygard timeout + 3-strike breaker; `analyze`/`wait_job`/`media_identities` no-op stubs) driven by the **unchanged `cli.fetch_run_record`** — no forked walker.
- [x] Greedy decode + `/no_think` for reasoning-tuned candidates; anchor-visual/inject-factual prompt renders `context_pack` names into the model prompt.
- [x] Add `scene/tests/test_eval_harness_bakeoff.py`; `pytest` green (`describe` shape, name-into-prompt, prompt construction, inert stubs, `build_reports` scoring). Isolation/bounded-stall not re-tested (covered by reused walker).

### Checklist for Slice 4: Score, compare, decide

- [x] Produce a per-candidate REPORT artifact; commit curated artifacts under `docs/tasks/vlm/`.
- [x] `score --check-determinism` passes per captured record.
- [x] Decision memo picks one winner with a comparison table, license verdict, and disqualifiers; winner numbers reconcile with its artifact.

## Review Readiness

- [x] No boundary-touching change lacks matching contract/fixture evidence (schema + manifest reuse verified, no profile change).
- [x] Live-A1 runtime parity captured where pure tests cannot (latency/RSS, injection obedience).
- [x] Handoff decision records the bake-off outcome, the chosen model, verification, and the follow-on adapter-build hand-off.

## Stretch Goals

- [ ] Capture a fourth candidate (e.g. Qwen3.5-4B GGUF) if A1 time allows — informational, non-blocking.
- [ ] Note MiniCPM-V 4.6 fast-tier feasibility as a hand-off to the fast-tier task (do not evaluate here).

## Success Criteria

- [x] Three candidates each produce a deterministic, reproducible `acx-eval/v1` REPORT over the ~10-image name-injected bake-off subset.
- [x] Candidates are comparable on insertion rate, Must-Right gate passes, wrong-fact signal, FKRE, and A1 latency/RSS.
- [x] A decision memo names exactly one winner with cited evidence, the license verdict, and recorded disqualifiers.
- [x] The bake-off never degrades the live demo box (concurrency 1, off-path) and never aborts the whole run on a single item/candidate failure (rg-007 bounded-stall only).
- [x] No `DescriptionAdapter`/`PROFILE_SPECS` productionization occurs (deferred to the follow-on).
