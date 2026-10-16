# Task Plan — WBTRUST-7

> **Date:** 2026-10-15
> **Author:** claude (Sonnet 5.5)
> **Owning Epic:** none yet — umbrella scope [workbench-curation-trust-scope.md](../../scopes/workbench-curation-trust-scope.md)
> **Task ID:** WBTRUST-7
> **Target Branch:** feature/wbtrust-7
> **Base SHA:** 372a6413a7ae0eb71baa3566716546684bac5a58
> **Revision:** 2
> **Review Coverage Target:** frozen-parent adapter routing/naming contracts + workbench draft provenance UI; configuration paths are reference-only
> **Depends on:** none (Wave A). Touches `QueueDraftCell.tsx` and `MediaAltSuggest.tsx`; WBTRUST-5 does not.
> **Executor:** `claude-remote` `claude-haiku-5-5`, effort `xhigh` for implementation and grunt work (operator order 2026-10-15). Brief each slice separately (1–3 files), inline the slice text plus codemap snippets; if the write-enabled remote Claude harness is denied or unavailable, record a blocker and ask the operator — no silent fallback to another model.
> **Review loop:** Sol HIGH standard review after Haiku xhigh implementation; LOUD odd rounds Opus / even rounds Sol xhigh. Main landing requires fresh Sol xhigh R2 after the five disjoint documentation lanes join; author commits do not authorize MERGE.
> **Prior art:** [scope](../../scopes/workbench-curation-trust-scope.md) (R13, root cause 12), [UX-map evaluation](../../assessments/current/workbench-curation-trust-uxmap-evaluation-2026-10-15.md) (A11), [GPUFLOW-3 plan](GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md) (unified status, name weaving), [describe-gpu-tier map](../../../apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.uxmap.json), `docs/workbay/contracts/image-description-api.md`, E23 epic `docs/epics/v0.5.0/gpu-operator-control-and-named-captions-epic.md`. Semantic prior art (handoff, by ID only): DEMOLIVE-1-BR-01 (finding 10161, deferred) → DADJ-10161 (finding 16805; historical fix commit `ec4f0bb0500cb6b0c154a83204fb1d0cf8121381` (past observation, superseded by retired-Small policy): default `florence_small`, live-demo manifest limited to Florence and GPU profiles, "fail closed rather than publish fixture text"), blocker 460 (MAINT-demo-qm-20260907). Out of scope (already own caption *quality*): [anti-hallucination-caption-generation-scope](../../scopes/anti-hallucination-caption-generation-scope.md), [description-quality-track-scope](../../scopes/description-quality-track-scope.md).
> **Carried findings (by ID only):** none recorded yet; query `review_findings(list, task_ref="WBTRUST-7")`

## WBTRUST-7. Description provenance and routing — fixtures never pass as AI drafts

Service paths are relative to `apps/prototype-description-service/`; frontend paths to `apps/prototype-wp-alt-context/js/admin/`; `config/…` and `docs/…` are repo-root paths.

## Objective

Every draft shows which adapter, model and tier produced it; a caption from the `seeded` fixture adapter can never be applied as alt text; a burst describe on a ready GPU yields `final_gpu` output from the configured Qwen profile; and naming never decorates a fixture caption.

## Problem Statement

The earlier five-item report showed inaccurate fixture captions with names and an AI-draft label. Supplied native full100 evidence now identifies the exact historical run `019c6776-d511-4531-8294-20dc99dabd7b`: 100/100 unique media, adapter `seeded`, model `seeded-fixtures` version `1`, tier `provisional_cpu`; 97 generated and 3 cache hits, 54 naming status `applied` and 46 `no_confirmed_identities`, completed 100/100 with 0 failed. This establishes stored-result provenance, not the effective configuration or cause of every historical routing choice.

Supplied baseline receipt: plugin main `372a6413a7ae0eb71baa3566716546684bac5a58` approved/activated at 22:01Z on 2026-10-15, with 7/7 authenticated HTTP/artifact checks. These receipts are coordinator-supplied facts, not independently verified in this lane; they establish neither browser behavior nor new GPU inference. They supersede the earlier pinned-build and five-item UNKNOWN premises. Metered GPU idle `STOPPED` is normal with no current description jobs and says nothing about prior batch activation.

## Constraints

- E23 hard constraints: no agent GPU actuation; operator GPU control stays in Settings. This plan changes routing *verification* and labels, not who starts the GPU.
- rg-015: boundary adapters pass `adapter`/`model_id`/`tier` through verbatim; never fabricate provenance.
- sr-006: no Python `assert` for validation; sr-007: new status/skip values are `StrEnum`; sr-008 ≤ 8 params.
- Do not gate positional naming on caption *content* (needs Golden-set evidence — follow-up). Gate on adapter provenance only.
- Greenfield: no migrations or new compatibility shims; any separately owned configuration-source correction uses the manifest consumer rather than hand-editing derived output.
- Operating baseline: existing `gpu_qwen30b` / `Qwen3-VL-30B-A3B-Instruct`. Florence Small is retired and benchmark-only; never restore, recommend or instantiate it in production/development. Unsupported CPU description requests must return explicit HTTP 503 before quota reservation; no provisional fixture or retired-model fallback, including after GPU failure.
- Scope: source paths below describe bounded frozen-parent naming/UI contracts, not approval for model downloads, configuration actuation, service restarts or new model rollout. Configuration/manifests are read-only references here; propose separately owned changes if needed. Reuse FIRBENCH-1 artifacts/contracts; its corpus, private DB, cache and benchmark paths remain excluded.
- Unknown legacy provenance stays unknown where the existing compatibility contract accepts it; do not infer a model, rewrite history or blanket-reject compatible legacy drafts. Explicit seeded provenance always takes precedence over tier labels.
- Future implementation checks run only in the assigned VM using an available matching in-sandbox/service `.venv`; OMP/MKL/OPENBLAS threads = 1, outer timeout ≤300s, `pytest --timeout=60`, direct `vitest run --maxWorkers=1`. No new tests or product edits for this documentation adjudication.

## Workflow Principles

- Consume the supplied full100 and activated-baseline receipts first (S1); verify only remaining freshness/configuration gaps through a separately authorized read-only evidence lane. Do not repeat activation absent an evidenced mismatch.
- Labels come from data on the wire, never from guessing at the UI.
- RED tests before code in S2–S4.

## Terminology

**Adapter** = `DescriptionAdapterKind` (`seeded`, operating baseline `gpu_qwen30b`, legacy/retired ids retained only as provenance). **Tier** = `provisional_cpu` | `final_gpu`. **Fixture caption** = a `_FIXTURE_POOL` string from `SeededDescriptionAdapter`.

## Current State Analysis

(Historical source observations at the supplied parent, not active rollout instructions; symbols, not line numbers.)

- `scene/application/seeded_adapter.py`: `SeededDescriptionAdapter` (`kind = SEEDED`, `model_id="seeded-fixtures"`) picks from `_FIXTURE_POOL` by deterministic hash. All five reported captions are verbatim pool entries ("…standing outdoors near greenery." is "A person standing outdoors near greenery." after name substitution).
- Env manifest `config/env/manifest.d/`: `10-service-shared.toml` `ACX_DESCRIPTION_ADAPTER` values `{dev=gpu_qwen30b, staging=florence_small, prod=gpu_qwen30b, demo=florence_small}`; `22-service-fir.toml` gives `svc-fir` the example `"seeded"`; also `21-service-vm.toml`, `40-demo.toml`, and examples `.env.fir.example` (`# ACX_DESCRIPTION_ADAPTER=seeded`), `.env.prod.example`. The unset fallback is `florence_small` (`api/main.py`, `scene/config/settings.py`).
- `scene/interface_adapters/http/deps.py`: `get_description_adapter(profile)` — its docstring still says "`seeded` (default)" (drift); for an available GPU adapter spec the sync inline route returns the raw GPU adapter via `get_gpu_description_adapter()`; the async GPU-final tier uses `get_async_gpu_description_adapter()`.
- Contract `docs/workbay/contracts/image-description-api.md`: the wire already carries `adapter`, `model_id` and `tier`. The UI ignores them: `pages/workbench/QueueDraftCell.tsx` and `pages/workbench/MediaAltSuggest.tsx` show only "Drafted by AI — review before saving." `api/describeApi.ts` defines `DESCRIBE_RESULT_TIER` and a request tier `GPU: 'gpu'`.
- Naming: `scene/application/identity_merge/merge.py` `_ungrounded_naming` — with exactly one confirmed person and no generic-person NP it falls to `NamingMode.POSITIONAL` (`PositionalFallbackRealizer`), which appends "Pictured from left: <name>" even to "a plate of food". Helpers in `scene/application/identity_merge/realizer.py` (`find_generic_person_nps`, `leading_generic_person_np`); enums in `scene/application/identity_merge/policy.py` (`NamingSkipReason`: agreement_disabled, db_unavailable, image_unreadable, no_confirmed_identities, no_eligible_identities, ambiguous_grounding, merge_error; `NamingStatus`; `NamingMode`).
- `scene/application/visual_facts_service.py` maps adapter kind to provider mode (`DescriptionAdapterKind.SEEDED: ProviderMode.NONE`) and defaults `DescriptionProfile.SEEDED` when no profile is passed.
- Historical DADJ-10161 changed the unset default to `florence_small`; that remains a source defect under current policy, not a rollout target. A pool-string match alone cannot establish runtime selection; the supplied full100 persisted provenance establishes seeded output for this exact run.
- Current supplied plugin activation supersedes the earlier pinned-release caveat. Read-only freshness checks compare against the activated `372a6413` baseline; request a new deployment only for an evidenced mismatch and separate operator authorization.
- Still unverified: effective served adapter/profile and exact model revision, historical requested tiers/start/warmup/ready events not present in receipts, and fresh GPU result lineage. Keep unavailable fields UNKNOWN; do not replace the known full100 provenance with a five-item investigation or infer prior activation from idle status.

## Target Outcome

| Situation | Behavior |
| --- | --- |
| Draft from `seeded` | Labeled "Sample caption (no model)"; cannot be applied as alt text; no naming added |
| Stored legacy CPU-tier draft | Show recorded provenance (or explicit unknown where compatible); seeded remains Sample/non-applicable |
| New CPU description request | Explicit HTTP 503 before quota reservation; no fixture or retired-model fallback |
| Draft from `final_gpu` | Labeled "GPU" with recorded adapter/model id; never infer a model from tier; normal review-then-apply |
| Burst describe, GPU ready | Result is `final_gpu` from existing `gpu_qwen30b` / `Qwen3-VL-30B-A3B-Instruct`, independent of the process default; verify actual served lineage |

## Context Loading

`seeded_adapter.py`, `deps.py`, `visual_facts_service.py`, `scene/application/identity_merge/{merge,policy,realizer}.py`, `api/main.py`, `scene/config/settings.py`, `config/env/manifest.d/{10,21,22,40}-*.toml`, `docs/workbay/contracts/image-description-api.md`; `api/describeApi.ts`, `QueueDraftCell.tsx`, `MediaAltSuggest.tsx`. Canon (read-only v0.26.2, supplied rows): PROV-01 “Every output walks back to its evidence” (`lexicons/ml-systems.md#prov-01`) for missing output lineage; HAI-05 “Imperceptible AI is not ethical” (`lexicons/interaction-ux.md#hai-05`) for fixture/AI disclosure; HAI-01 “Evidence before label” (`lexicons/interaction-ux.md#hai-01`) for the provenance disclosure; GRPH-31 “Critical-path schedule the task DAG” (`lexicons/graph-theory.md#grph-31`) for shared-map ownership. EVAL-16/19 do not govern generic description provenance; offline checks establish no task/E2E/quality PASS.

## Contract and Boundary Impact

- `image-description-api.md`: documents which `adapter` values are *non-applicable fixtures* (`seeded`) and the naming skip reason added in S4; the wire keys are unchanged.
- S4 adds a `NamingSkipReason` value (wire value = enum value) — update the contract table and the PHP/JS readers of the naming provenance in the same slice (rg-005).
- Binding future default/routing contract: use existing `gpu_qwen30b` / `Qwen3-VL-30B-A3B-Instruct`; verify the exact configured and served model/revision rather than guessing from a Qwen label. `seeded` is test-only; CPU unsupported ⇒ HTTP 503 before quota. Any required manifest/configuration change needs a separately owned proposal; none is actuated by this plan lane.

## Proposed Solution

Make provenance visible and enforceable at three points: the service refuses to name a fixture caption; the UI labels and blocks apply for fixtures; routing for tier `gpu` is pinned by a test. Document configuration drift against the supported baseline without changing runtime configuration in this lane.

## Files and Surfaces to Change

Future implementation surfaces (separately dispatched; this adjudication owns only this plan and its report):

- Service: `scene/application/identity_merge/{merge,policy}.py`, `scene/interface_adapters/http/deps.py` (docstring + routing test seam), `scene/application/visual_facts_service.py`, `docs/workbay/contracts/image-description-api.md`
- Frontend: `pages/workbench/QueueDraftCell.tsx`, `pages/workbench/MediaAltSuggest.tsx`, new `pages/workbench/DraftProvenanceBadge.tsx`, `api/describeApi.ts` (types only if needed)
- Tests: service tests beside the modules above (merge, deps routing, visual facts), `QueueDraftCell*.test.tsx`, `MediaAltSuggest*.test.tsx`, new `DraftProvenanceBadge.test.tsx`
- Deliverable: final draft-copy/provenance-state table for ONE later integration owner after WBTRUST-5 and WBTRUST-7 supply their final copy. WBTRUST-7 does not own/edit the shared `describe-gpu-tier.uxmap.json` or rendered `.md`. Reuse existing maps/ASCII; the integration owner renders/checks the canonical JSON rather than hand-mirroring it.

## Verification Strategy

- S1 evidence: consume the exact full100 run table and activated-baseline receipt as supplied; track only remaining process/served-model freshness gaps as UNKNOWN until authorized verification.
- Service: merge test — `SEEDED` caption with one confirmed person ⇒ `named_draft == generic_draft`, status skipped with the new reason; non-seeded behavior unchanged (existing positional/substituted/grounded tests green).
- Routing: test that a request with tier `gpu` resolves `get_async_gpu_description_adapter()`/`gpu_qwen30b` when the GPU state is ready, independent of `ACX_DESCRIPTION_ADAPTER`; exact baseline model/revision must be verified. Unsupported CPU ⇒ HTTP 503 before quota; no fallback on GPU timeout.
- UI: fixture draft shows the label and the apply control is aria-disabled with the reason; CPU/GPU labels render from wire values; unknown adapter renders its raw id (no guess).
- Later authorized browser/GPU verification: fresh baseline GPU output with persisted model/revision and visible provenance. No fresh CPU descriptions required; no actuation/new description POST in this documentation lane.
- Future bounded service/UI checks follow the VM constraints above; run only existing documentation link/path/task-plan guards available here. Report unavailable tooling honestly.

## Slice Delivery

### Slice S1: live-provenance-read

Consume established stored provenance and identify the remaining configuration gaps.
Closes: R13 (diagnosis only). Canon: PROV-01.
Design decision (binding): record supplied run `019c6776-d511-4531-8294-20dc99dabd7b` with all 100 seeded-fixtures/provisional_cpu results, 97 generated/3 cached and 54 named; consume the supplied activated `372a6413` receipt with 7 HTTP checks. Do not claim this lane independently queried them. Preserve unavailable historical requested tiers/start/warmup/ready events as UNKNOWN. Effective configuration, served Qwen model/revision and fresh GPU output still require separately authorized verification; source defaults and idle STOPPED cannot supply those facts. No code/config change, DB/network access, service restart or GPU actuation here.
Acceptance: supplied facts and unresolved fields clearly separated; no duplicate baseline activation prerequisite. Causal runtime/configuration attribution may remain UNKNOWN rather than selecting an unsupported cause. S2–S4 guards remain necessary regardless of cause.

### Slice S2: seeded-is-not-a-draft

Fixtures must look like fixtures.
Closes: R13. Canon: HAI-05, PROV-01, HAI-01.
Design decision (binding): when the wire `adapter` is `seeded`, `QueueDraftCell` and `MediaAltSuggest` show "Sample caption (no model)" instead of "Drafted by AI — review before saving.", the Apply/Use control is `aria-disabled` with an adjacent reason ("Not a real description — switch the description profile"), and the text never enters the alt-text field. RED UI tests first.
Acceptance: fixture draft cannot be applied via click or keyboard; copy never says "AI" for seeded.

### Slice S3: provenance-badge-and-tier-routing

Show the adapter, model and tier; prove the burst route.
Closes: R13. Canon: PROV-01, HAI-01.
Design decision (binding): `DraftProvenanceBadge` renders tier label ("Provisional (CPU)" for compatible stored legacy output / "GPU") with adapter and model id in a disclosure, from wire values only (rg-015); unknown adapter prints its raw id. A service routing test pins that `tier=gpu` with GPU ready resolves the async GPU adapter/Qwen profile regardless of the process-default `ACX_DESCRIPTION_ADAPTER`; if the test fails, fix `deps.py` routing in this slice with the RED test first. For new unsupported CPU requests return HTTP 503 before quota reservation; GPU timeout/unavailability fails explicitly, with no provisional fixture or retired fallback. The active model contract is existing `gpu_qwen30b` / `Qwen3-VL-30B-A3B-Instruct`; verify actual model/revision. Legacy CPU display is compatibility-only; unknown provenance remains explicit where accepted, never inferred from tier.
Acceptance: badge coverage for Sample, recorded legacy CPU, GPU and unknown compatibility states; seeded always blocks apply/naming. Routing coverage checks exact baseline identity and unsupported-CPU 503 before quota, with no fallback; contract documents these states. Fresh inference remains a separate authorized gate.

### Slice S4: provenance-gated-naming

No names on fixtures.
Closes: R13. Canon: HAI-05, PROV-01; project rule sr-007.
Design decision (binding): the naming merge receives the caption's adapter kind and, for `SEEDED`, returns the generic caption with a new `NamingSkipReason.CAPTION_NOT_FROM_MODEL` and matching `NamingStatus`; no content-based gating of positional naming (a face-confirmed person on a model caption that names no person still gets the existing positional behavior — follow-up needs Golden-set evidence). Update the contract table and the JS/PHP readers of naming provenance in the same slice.
Acceptance: RED-first merge tests: seeded + one confirmed person ⇒ unchanged caption and the new reason; non-seeded paths unchanged; wire value documented.

### Slice S5: config-and-doc-drift

Document drift without authorizing runtime changes.
Closes: R13 (configuration handoff). Canon: PROV-01.
Design decision (binding): correct default/routing documentation against existing `gpu_qwen30b` / `Qwen3-VL-30B-A3B-Instruct`; identify stale seeded/Small examples as historical defects. `config/env/manifest.d/*.toml`, `.env.fir.example`, `api/main.py` and `scene/config/settings.py` are frozen-parent references, not permission for model downloads, configuration actuation or restart. If a fix needs files outside the dispatched ownership, return a typed scope proposal. Preserve fixture rejection, explicit unsupported-CPU 503 before quota and existing unknown-legacy compatibility.
Acceptance: no active instruction restores Small or requires fresh CPU output; drift and its later owner are explicit. Existing `scripts/test_acx_backend_image_contract.py` remains immutable; report actual execution only if available and within the dispatched scope.

### Slice S6: browser-reverify

Verify new output only under a later authorized runtime/browser slice.
Closes: R13 (runtime acceptance). Canon: PROV-01, HAI-01.
Design decision (binding): after separately approved implementation/deployment, verify actual configured/served baseline model and a fresh GPU run with persisted adapter/model/revision/tier and visible badge evidence. No CPU re-description requirement; no GPU start/stop, lease or always-on change by this lane. Idle STOPPED remains normal. Supply the final copy/provenance-state table to ONE later shared-map integration owner alongside WBTRUST-5; do not edit shared maps here.
Acceptance: fresh baseline result is `final_gpu` with traceable lineage and review-then-apply; seeded Sample has no naming or alt-text write; unsupported CPU fails 503 before quota; accepted unknown legacy states remain compatible. Supplied historical HTTP receipts and offline checks cannot satisfy browser, new GPU, quality or task completion gates; slice-complete decision follows the existing template only after actual evidence.
