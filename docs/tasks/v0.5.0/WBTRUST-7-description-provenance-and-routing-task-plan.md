# Task Plan — WBTRUST-7

> **Date:** 2026-10-15
> **Author:** claude (Sonnet 5.5)
> **Owning Epic:** none yet — umbrella scope [workbench-curation-trust-scope.md](../../scopes/workbench-curation-trust-scope.md)
> **Task ID:** WBTRUST-7
> **Target Branch:** feature/wbtrust-7
> **Base SHA:** 372a6413a7ae0eb71baa3566716546684bac5a58
> **Revision:** 1
> **Review Coverage Target:** description service (adapter routing, naming merge) + workbench draft UI + env manifest
> **Depends on:** none (Wave A). Touches `QueueDraftCell.tsx` and `MediaAltSuggest.tsx`; WBTRUST-5 does not.
> **Executor:** `claude-remote` `claude-haiku-5-5`, effort `xhigh` for implementation and grunt work (operator order 2026-10-15). Brief each slice separately (1–3 files), inline the slice text plus codemap snippets; if the write-enabled remote Claude harness is denied or unavailable, record a blocker and ask the operator — no silent fallback to another model.
> **Prior art:** [scope](../../scopes/workbench-curation-trust-scope.md) (R13, root cause 12), [UX-map evaluation](../../assessments/current/workbench-curation-trust-uxmap-evaluation-2026-10-15.md) (A11), [GPUFLOW-3 plan](GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md) (unified status, name weaving), [describe-gpu-tier map](../../../apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.uxmap.json), `docs/workbay/contracts/image-description-api.md`, E23 epic `docs/epics/v0.5.0/gpu-operator-control-and-named-captions-epic.md`
> **Carried findings (by ID only):** none recorded yet; query `review_findings(list, task_ref="WBTRUST-7")`

## WBTRUST-7. Description provenance and routing — fixtures never pass as AI drafts

Service paths are relative to `apps/prototype-description-service/`; frontend paths to `apps/prototype-wp-alt-context/js/admin/`; `config/…` and `docs/…` are repo-root paths.

## Objective

Every draft shows which adapter, model and tier produced it; a caption from the `seeded` fixture adapter can never be applied as alt text; a burst describe on a ready GPU yields `final_gpu` output from the configured Qwen profile; and naming never decorates a fixture caption.

## Problem Statement

Five captions on the fir site read as wildly inaccurate, each ending "Drafted by AI — review before saving.":

- #113, #107 — "A plate of food on a wooden table. Pictured from left: Bea Burke."
- #114 — "A building exterior seen from the street."
- #89 — "A close-up of a small object on a neutral background. Pictured from left: Ellyn Heald."
- #85 — "Ellyn Heald standing outdoors near greenery."

Operator: "it seems that qwen model or whichever incumbent should be used for bursty gpu description was NOT used."

## Constraints

- E23 hard constraints: no agent GPU actuation; operator GPU control stays in Settings. This plan changes routing *verification* and labels, not who starts the GPU.
- rg-015: boundary adapters pass `adapter`/`model_id`/`tier` through verbatim; never fabricate provenance.
- sr-006: no Python `assert` for validation; sr-007: new status/skip values are `StrEnum`; sr-008 ≤ 8 params.
- Do not gate positional naming on caption *content* (needs Golden-set evidence — follow-up). Gate on adapter provenance only.
- Greenfield: no migrations; env defaults change in `config/env/manifest.d/*.toml`, not by shims.
- Python tests via `uv run --directory apps/prototype-description-service` on the remote VM lane (xdist and timeout flags per `docs/workbay/rules/testing-python.md`); JS via `vitest run`.

## Workflow Principles

- Read the live evidence first (S1): do not change routing until the adapter/model/tier on the five items is known.
- Labels come from data on the wire, never from guessing at the UI.
- RED tests before code in S2–S4.

## Terminology

**Adapter** = `DescriptionAdapterKind` (seeded, florence_small, gpu_qwen30b, …). **Tier** = `provisional_cpu` | `final_gpu`. **Fixture caption** = a `_FIXTURE_POOL` string from `SeededDescriptionAdapter`.

## Current State Analysis

(Symbols, not line numbers.)

- `scene/application/seeded_adapter.py`: `SeededDescriptionAdapter` (`kind = SEEDED`, `model_id="seeded-fixtures"`) picks from `_FIXTURE_POOL` by deterministic hash. All five reported captions are verbatim pool entries ("…standing outdoors near greenery." is "A person standing outdoors near greenery." after name substitution).
- Env manifest `config/env/manifest.d/`: `10-service-shared.toml` `ACX_DESCRIPTION_ADAPTER` values `{dev=gpu_qwen30b, staging=florence_small, prod=gpu_qwen30b, demo=florence_small}`; `22-service-fir.toml` gives `svc-fir` the example `"seeded"`; also `21-service-vm.toml`, `40-demo.toml`, and examples `.env.fir.example` (`# ACX_DESCRIPTION_ADAPTER=seeded`), `.env.prod.example`. The unset fallback is `florence_small` (`api/main.py`, `scene/config/settings.py`).
- `scene/interface_adapters/http/deps.py`: `get_description_adapter(profile)` — its docstring still says "`seeded` (default)" (drift); for an available GPU adapter spec the sync inline route returns the raw GPU adapter via `get_gpu_description_adapter()`; the async GPU-final tier uses `get_async_gpu_description_adapter()`.
- Contract `docs/workbay/contracts/image-description-api.md`: the wire already carries `adapter`, `model_id` and `tier`. The UI ignores them: `pages/workbench/QueueDraftCell.tsx` and `MediaAltSuggest.tsx` show only "Drafted by AI — review before saving." `api/describeApi.ts` defines `DESCRIBE_RESULT_TIER` and a request tier `GPU: 'gpu'`.
- Naming: `application/identity_merge/merge.py` `_ungrounded_naming` — with exactly one confirmed person and no generic-person NP it falls to `NamingMode.POSITIONAL` (`PositionalFallbackRealizer`), which appends "Pictured from left: <name>" even to "a plate of food". Helpers in `identity_merge/realizer.py` (`find_generic_person_nps`, `leading_generic_person_np`); enums in `identity_merge/policy.py` (`NamingSkipReason`: agreement_disabled, db_unavailable, image_unreadable, no_confirmed_identities, no_eligible_identities, ambiguous_grounding, merge_error; `NamingStatus`; `NamingMode`).
- `scene/application/visual_facts_service.py` maps adapter kind to provider mode (`DescriptionAdapterKind.SEEDED: ProviderMode.NONE`) and defaults `DescriptionProfile.SEEDED` when no profile is passed.
- Unverified: the live `adapter`/`model_id`/`tier` for media 85, 89, 107, 113, 114; the effective `ACX_DESCRIPTION_ADAPTER` on the process that served :10028; whether burst describe (`tier=gpu`) routes to `gpu_qwen30b` regardless of that process default.

## Target Outcome

| Situation | Behavior |
| --- | --- |
| Draft from `seeded` | Labeled "Sample caption (no model)"; cannot be applied as alt text; no naming added |
| Draft from CPU tier | Labeled "Provisional (CPU)" with adapter/model in a tooltip/disclosure |
| Draft from `final_gpu` | Labeled "GPU (Qwen …)" with model id; normal review-then-apply |
| Burst describe, GPU ready | Result is `final_gpu` from the configured Qwen profile, independent of the process default |

## Context Loading

`seeded_adapter.py`, `deps.py`, `visual_facts_service.py`, `identity_merge/{merge,policy,realizer}.py`, `api/main.py`, `scene/config/settings.py`, `config/env/manifest.d/{10,21,22,40}-*.toml`, `docs/workbay/contracts/image-description-api.md`; `api/describeApi.ts`, `QueueDraftCell.tsx`, `MediaAltSuggest.tsx`. Canon (v0.26.2): HAI-05, PROV-01, ATTRIB-02, EVAL-16, INT-22, HAI-01, PERC-10, DRIFT-03.

## Contract and Boundary Impact

- `image-description-api.md`: documents which `adapter` values are *non-applicable fixtures* (`seeded`) and the naming skip reason added in S4; the wire keys are unchanged.
- S4 adds a `NamingSkipReason` value (wire value = enum value) — update the contract table and the PHP/JS readers of the naming provenance in the same slice (rg-005).
- **Open decision (operator):** whether `svc-fir` should keep `seeded` as its documented example. Default: change the example to `florence_small` and keep `seeded` available for tests only.

## Proposed Solution

Make provenance visible and enforceable at three points: the service refuses to name a fixture caption; the UI labels and blocks apply for fixtures; routing for tier `gpu` is pinned by a test. Config/doc drift is fixed at the source (manifest and docstring).

## Files and Surfaces to Change

Owned paths:

- Service: `scene/application/identity_merge/{merge,policy}.py`, `scene/interface_adapters/http/deps.py` (docstring + routing test seam), `scene/application/visual_facts_service.py`, `config/env/manifest.d/22-service-fir.toml` (+ `21`, `40` if S1 shows drift), `.env.fir.example`, `docs/workbay/contracts/image-description-api.md`
- Frontend: `pages/workbench/QueueDraftCell.tsx`, `MediaAltSuggest.tsx`, new `DraftProvenanceBadge.tsx`, `api/describeApi.ts` (types only if needed)
- Tests: service tests beside the modules above (merge, deps routing, visual facts), `QueueDraftCell*.test.tsx`, `MediaAltSuggest*.test.tsx`, new `DraftProvenanceBadge.test.tsx`
- Docs: `describe-gpu-tier` map (draft cell copy), hand-mirrored `.md`; `make lint-ux-maps`

## Verification Strategy

- S1 evidence: a table of `adapter`/`model_id`/`tier`/`naming` for the five items plus the effective process env.
- Service: merge test — `SEEDED` caption with one confirmed person ⇒ `named_draft == generic_draft`, status skipped with the new reason; non-seeded behavior unchanged (existing positional/substituted/grounded tests green).
- Routing: test that a request with tier `gpu` resolves `get_async_gpu_description_adapter()`/`gpu_qwen30b` when the GPU state is ready, independent of `ACX_DESCRIPTION_ADAPTER`.
- UI: fixture draft shows the label and the apply control is aria-disabled with the reason; CPU/GPU labels render from wire values; unknown adapter renders its raw id (no guess).
- Browser (fir site): re-describe #85 and #113 after S1 config fix; draft is Qwen/Florence output with a label.
- `uv run --directory apps/prototype-description-service pytest <paths>`, `npm run typecheck`, `npm run lint`, `vitest run` on the VM.

## Slice Delivery

### Slice S1: live-provenance-read

Find out what produced the five captions and what the process is configured with.
Closes: R13 (diagnosis). Canon: EVAL-16, PROV-01.
Design decision (binding): read, for media 85/89/107/113/114, the stored `adapter`/`model_id`/`tier` and naming provenance (service API or DB via the supported Python API — no raw sqlite on the handoff DB); read the effective `ACX_DESCRIPTION_ADAPTER` on the fir service; confirm or refute "seeded" from the `_FIXTURE_POOL` match. No code change.
Acceptance: a decision with the table; the root cause is one of {fir env set to seeded, wrong tier routing, stale cached drafts} stated explicitly.

### Slice S2: seeded-is-not-a-draft

Fixtures must look like fixtures.
Closes: R13. Canon: HAI-05, PROV-01, HAI-01.
Design decision (binding): when the wire `adapter` is `seeded`, `QueueDraftCell` and `MediaAltSuggest` show "Sample caption (no model)" instead of "Drafted by AI — review before saving.", the Apply/Use control is `aria-disabled` with an adjacent reason ("Not a real description — switch the description profile"), and the text never enters the alt-text field. RED UI tests first.
Acceptance: fixture draft cannot be applied via click or keyboard; copy never says "AI" for seeded.

### Slice S3: provenance-badge-and-tier-routing

Show the adapter, model and tier; prove the burst route.
Closes: R13. Canon: PROV-01, ATTRIB-02, INT-22, DRIFT-03.
Design decision (binding): `DraftProvenanceBadge` renders tier label ("Provisional (CPU)" / "GPU") with adapter and model id in a disclosure, from wire values only (rg-015); unknown adapter prints its raw id. A service routing test pins that `tier=gpu` with GPU ready resolves the async GPU adapter/Qwen profile regardless of the process-default `ACX_DESCRIPTION_ADAPTER`; if the test fails, fix `deps.py` routing in this slice with the RED test first. CPU continuation after a GPU timeout is labeled "Provisional (CPU)".
Acceptance: badge tests for three tiers + unknown; routing test green; contract doc table lists the three labeled states.

### Slice S4: provenance-gated-naming

No names on fixtures.
Closes: R13. Canon: HAI-05, ATTRIB-02, PROV-01, sr-007.
Design decision (binding): the naming merge receives the caption's adapter kind and, for `SEEDED`, returns the generic caption with a new `NamingSkipReason.CAPTION_NOT_FROM_MODEL` and matching `NamingStatus`; no content-based gating of positional naming (a face-confirmed person on a model caption that names no person still gets the existing positional behavior — follow-up needs Golden-set evidence). Update the contract table and the JS/PHP readers of naming provenance in the same slice.
Acceptance: RED-first merge tests: seeded + one confirmed person ⇒ unchanged caption and the new reason; non-seeded paths unchanged; wire value documented.

### Slice S5: config-and-doc-drift

Fix the sources of the confusion.
Closes: R13. Canon: DRIFT-03, rg-006.
Design decision (binding): correct the `get_description_adapter` docstring (unset default is `florence_small`; `seeded` is test-only); change the `svc-fir` manifest example and `.env.fir.example` to a model-backed profile with a comment on cost; list adapter values and which are fixtures in `image-description-api.md`; first locate what consumes `config/env/manifest.d/*.toml` (generator or check; none was confirmed while planning) and regenerate/run it rather than hand-editing derived output; `scripts/test_acx_backend_image_contract.py` pins `.env.fir.example` and must stay green.
Acceptance: the manifest consumer and `scripts/test_acx_backend_image_contract.py` green; no document claims `seeded` is the default.

### Slice S6: browser-reverify

Prove it on the site.
Closes: R13. Canon: EVAL-16.
Design decision (binding): after S1–S5 are deployed to the fir service, re-describe #85 and #113 (CPU tier) and run one burst describe on a ready GPU; record adapter/model/tier and screenshots of the badge; update the describe-gpu-tier map copy and run `make lint-ux-maps`.
Acceptance: a real-model caption with a visible label on each; burst result tier is `final_gpu`; slice-complete decision per template.
