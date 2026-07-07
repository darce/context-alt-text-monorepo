# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-06 12:00 EST
> - **Author**: Claude Opus 4.8
> - **Owning Epic**: [docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md)
> - **Epic Short ID**: E20
> - **Target Branch**: `feature/e20-11`
> - **Review Coverage Target**: 2

---

## E20-11. Hosted Provider Benchmark and Governance Decision

## Objective

Benchmark hosted description providers behind operator-owned backend keys, reusing the existing VLM-2A eval harness (`apps/prototype-description-service/scripts/eval_harness/`), and produce a governance decision memo whose disposition is exactly one of the canonical enum `ship | benchmark_only | defer_byok | reject`. No default runtime impact; a hosted provider is fail-closed until explicitly opted in.

## Problem Statement

Hosted provider models may improve caption quality and latency, but they carry privacy, subprocessor, cost, and retention implications because image bytes leave the Alt Context service boundary. The product needs deterministic, comparable evidence plus an opt-in governance model before adding provider mode. The prior draft of this plan predated the VLM-2A eval harness and proposed a parallel benchmark script, a second test module, and a second JSON schema — duplicating scoring, provenance, and bounded-failure logic that the merged harness already owns.

## Constraints

- Provider calls are **opt-in**, **server-side**, and **fail-closed by default**: the hosted profile resolves to a fail-closed `UnavailableDescriptionAdapter` unless an explicit opt-in env flag is set.
- Every hosted result must disclose that bytes left the boundary via the existing `ProviderDisclosure.left_service_boundary` field (already wired: `scene/application/visual_facts_service.py:183` sets it from `ProviderMode.HOSTED`).
- **Reuse, do not fork, the eval harness.** New code = the provider adapter(s) + a `--provider` matrix flag on the existing `scripts/eval_harness/cli.py`. No new benchmark script, no new test-only harness, no new JSON schema (`schema.py` `SCHEMA = "acx-eval/v1"` is the artifact schema).
- No BYOK storage in this task. If the decision is `defer_byok`, the memo names a follow-on task; it does not implement key storage here.
- **E20-7 is a sibling task plan, not a landed dependency.** `docs/tasks/20.0/E20-7-error-logs-usage-accounting-and-budget-controls-task-plan.md` exists as a plan; E20-7 is **not** a registered/done handoff task and its usage/budget ledger schema does not yet exist. This task therefore does **not** write into an E20-7 ledger. It writes cost/latency into the harness's own run-record/report JSON (see Proposed Solution) and defers ledger integration to a named follow-on.

## Workflow Principles

- The benchmark is the existing eval harness run against a hosted-profile service; it is separate from default generation because the default profile stays `seeded`/`florence_small`.
- Cost, latency, provider/model id, prompt version, and boundary-crossing disclosure are recorded per image through the harness run record and report provenance (`report._model_provenance` already stamps `adapters`/`model_ids`/`model_versions`).
- The decision memo is the deliverable; product enablement is conditional on it and gated behind the canonical disposition enum.

## Terminology

- **Provider mode**: hosted third-party model invocation where image bytes leave local infrastructure (`DescriptionAdapterKind.HOSTED_PROVIDER` → `ProviderMode.HOSTED`).
- **BYOK**: customer/operator-provided provider key stored or passed by the product. Out of scope here.
- **Disposition enum** (canonical, sr-007): `ship | benchmark_only | defer_byok | reject`. Used verbatim in Objective, Target Outcome, Slice 2, and Success Criteria. No synonyms (`keep`/`defer` are retired).

## Current State Analysis

- `DescriptionAdapterKind.HOSTED_PROVIDER = "hosted_provider"` already exists (`scene/domain/description.py:18`) and maps to `ProviderMode.HOSTED` in `visual_facts_service._PROVIDER_FOR_ADAPTER` (lines 28-34).
- `ProviderDisclosure.left_service_boundary` (`scene/interface_adapters/http/schemas/responses.py:46`) already communicates boundary crossing; the service sets it True for hosted results.
- The VLM-2A eval harness is merged and owns scoring, provenance, and bounded failure: `cli.py` (`fetch_run_record`, `_cmd_fetch`, `main`, `--limit`/`--stall-limit`, `BoundedStallError`), `remote_client.py` (`RemoteSceneClient`, `_DEFAULT_TIMEOUT_S = 60.0`, `_BREAKER_THRESHOLD = 3`, `CircuitOpenError`), `report.py` (`build_reports`, `score_run_record`, `_model_provenance`), `caption_metrics.py` (`score_caption`, `insertion_rate`), `manifest.py` (`load_manifest`, `GoldenManifest`), `schema.py` (`SCHEMA`, `DocKind`).
- Golden corpus is `scene/tests/seed/golden.json` (37 entries, roster of 10, `manifest_version` 1) — the pinned image set for this benchmark.
- **No hosted provider adapter, no hosted profile registration, and no `--provider` flag exist yet.** These are the only new surfaces.

## Target Outcome

The existing eval harness (`scripts/eval_harness/cli.py`) can, with a new `--provider` flag, run one or more hosted-provider profiles over the pinned golden corpus (`scene/tests/seed/golden.json`), producing the same `acx-eval/v1` run-record + report JSON (via `report.build_reports`) with per-image caption metrics, latency, cost, and `left_service_boundary` disclosure. A decision memo records the evidence and selects exactly one disposition from `ship | benchmark_only | defer_byok | reject`, plus privacy/subprocessor disclosure and any follow-on scope.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/planning-review-guide.md`, `docs/workbay/rules/testing-python.md`
- Contracts: `docs/workbay/contracts/image-description-api.md`
- Harness (reuse): `apps/prototype-description-service/scripts/eval_harness/{cli.py,remote_client.py,report.py,caption_metrics.py,manifest.py,schema.py}`, README at `scripts/eval_harness/README.md`
- Adapter seam: `apps/prototype-description-service/scene/application/description_adapter.py` (`DescriptionAdapter` Protocol, `AdapterResult`), `scene/config/profiles.py` (`DescriptionProfile`, `ProfileSpec`, `PROFILE_SPECS`, `get_profile_spec`), `scene/interface_adapters/http/deps.py` (`get_description_adapter`)
- Golden corpus: `apps/prototype-description-service/scene/tests/seed/golden.json`
- Handoff/MCP: task `E20-11`. E20-7 is a plan doc only — do not assume a ledger dependency.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `DescriptionAdapter` protocol | backend | `scene/application/description_adapter.py` (`describe(*, image_bytes, context) -> AdapterResult`) | New `HostedProviderDescriptionAdapter` implements it; protocol unchanged | no — additive impl | fake-provider unit test asserts `isinstance(adapter, DescriptionAdapter)` |
| Description profile registry | backend | `scene/config/profiles.py` `PROFILE_SPECS` | Add hosted profile spec(s), `available=False` fail-closed by default | no default runtime change | `test_description_profiles.py` asserts hosted profile resolves fail-closed unless opted in |
| Provider disclosure | backend | `ProviderDisclosure.left_service_boundary` (`responses.py:46`), `visual_facts_service.py:183` | No schema change; hosted adapter drives existing True path | no | assert hosted describe response has `provider_disclosure.left_service_boundary == True` |
| Eval-artifact schema | backend/tooling | `schema.py` `SCHEMA = "acx-eval/v1"`, `DocKind` | **No change** — reuse run-record/report schema; add provider label into existing provenance | no | `score_run_record` produces valid report; `_model_provenance` stamps adapter/model |
| Eval CLI | tooling | `cli.py` `main`/`_common` subcommands | Add `--provider` matrix flag; stamp provider into run record | no — flag defaults off | CLI test for `--provider` plumbing |
| Policy docs | Product + Engineering | none | Decision memo + provider disclosure language | n/a | planning review |

## Proposed Solution

Add a hosted-provider `DescriptionAdapter` implementation and register it as a fail-closed profile, then extend the **existing** eval harness with a `--provider` flag so the current `fetch`/`run` path benchmarks hosted profiles over the pinned golden corpus. Scoring, provenance, run-record/report JSON, and bounded-failure handling are entirely reused from `report.py`/`caption_metrics.py`/`cli.py` — no parallel harness, no second schema.

**Integration seam.** The eval CLI's `fetch_run_record(manifest, images_dir, client, ...)` (`cli.py`) already accepts any `client` exposing `describe(...)`; `RemoteSceneClient.describe` (`remote_client.py`) POSTs `/scene/describe/multipart` to a running service. A hosted benchmark therefore runs the existing harness against an **eval-tenant service instance configured with the hosted profile** (server-side, opt-in). `--provider <profile>` selects/stamps the profile for the run and, for the multi-provider matrix, iterates profiles, writing one `acx-eval/v1` run record + report per provider via `report.build_reports`. Face-recognition tiers are provider-independent and out of scope for the provider matrix; the provider run scores the caption tier (`caption_metrics.score_caption`).

**Scoring caveat — what the current golden set can measure.** All 37 `golden.json` entries ship empty `context_pack: {}`, empty `must_right`/`easy_wrong`, and no `objects`. Consequently, on the corpus as-is a hosted provider run yields meaningful signal only for the **context-independent** caption metrics (`fkre`/readability, `repetition_ratio`, first-sentence `gist_ok`, word/char count) plus **latency and cost**. `insertion_rate`, `tag_coverage`, and `must_right_failures` are structurally floor/inert here: `insertion_rate` measures whether the caption contains a `present_identities` name the generic provider was never given (no per-entry context injected), `tag_coverage` is `None` without `objects`, and `must_right_failures` is empty without `must_right`. The memo must therefore scope provider comparison to the measurable metrics + latency + cost; any insertion/named-entity claim requires first populating context packs (and confirming the hosted describe path injects recognized identities into the prompt) — a named prerequisite, not assumed by this task.

**Cost/latency capture without E20-7.** Latency is derived from the harness run (per-item timing added to the run-record items); estimated cost per image is computed from the provider's published per-request price and recorded in the run-record provenance. These land in the harness's own JSON under `scripts/eval_harness/out/` (git-ignored) and are promoted by hand into the decision memo. **Ledger integration is explicitly deferred** to E20-7 (or a named `E20-11-followon` if E20-7 does not land): when the E20-7 usage/budget ledger schema exists, a follow-on maps these fields into it. This task depends on no E20-7 field.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Backend adapter | `apps/prototype-description-service/scene/infrastructure/provider/hosted_provider_adapter.py` (new) | `HostedProviderDescriptionAdapter` implementing `DescriptionAdapter` (`kind = DescriptionAdapterKind.HOSTED_PROVIDER`, `model_id`/`model_version`/`prompt_or_task_version`, `describe(*, image_bytes, context) -> AdapterResult`); outbound provider call with a per-call timeout; fail-closed on provider error |
| Backend adapter (test double) | `apps/prototype-description-service/scene/infrastructure/provider/hosted_provider_adapter.py` or a `tests` fixture | `FakeHostedProviderAdapter` returning canned `AdapterResult` for deterministic unit tests (no network) |
| Profiles | `apps/prototype-description-service/scene/config/profiles.py` | Add `DescriptionProfile.HOSTED_<provider>` member(s) + `PROFILE_SPECS` entry with `adapter_kind=DescriptionAdapterKind.HOSTED_PROVIDER`, `available=False` (fail-closed), `unavailable_reason` naming the opt-in env; extend `ProfileSpec` with any provider-id field required |
| DI resolution | `apps/prototype-description-service/scene/interface_adapters/http/deps.py` | Extend `get_description_adapter()` to resolve a hosted profile to `HostedProviderDescriptionAdapter` **only** when the opt-in env flag is set, else `UnavailableDescriptionAdapter` (fail-closed), mirroring the existing florence/gpu stub branch |
| Eval CLI | `apps/prototype-description-service/scripts/eval_harness/cli.py` | Add `--provider <profile>` (and matrix iteration) to `_common`/`main`; stamp provider/profile into the run-record provenance; reuse `fetch_run_record`, `build_reports`, bounded-failure path unchanged |
| Tests | `apps/prototype-description-service/scene/tests/test_description_profiles.py` | Add: hosted profile resolves fail-closed unless opted in; opted-in hosted profile yields a `DescriptionAdapter` whose describe sets `left_service_boundary` True |
| Tests | `apps/prototype-description-service/scripts/eval_harness/tests/` (existing harness tests dir) | Add `--provider` CLI plumbing test using `FakeHostedProviderAdapter`; no live network |
| Docs | `docs/tasks/20.0/E20-11-hosted-provider-decision-memo.md` (new) | Governance decision memo; disposition ∈ `ship \| benchmark_only \| defer_byok \| reject`; cost/latency/privacy/retention evidence table; follow-on scope |
| Contract | `docs/workbay/contracts/image-description-api.md` | Provider disclosure + opt-in/fail-closed language (reference existing `left_service_boundary`) |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scene/application/seeded_adapter.py` | `SeededDescriptionAdapter` — reference implementation of the `DescriptionAdapter` protocol to mirror |
| `apps/prototype-description-service/scene/infrastructure/vlm/unavailable_adapter.py` | `UnavailableDescriptionAdapter` — the fail-closed stub the hosted profile degrades to |
| `apps/prototype-description-service/scene/application/visual_facts_service.py` | `_PROVIDER_FOR_ADAPTER` mapping + `left_service_boundary` disclosure wiring (lines 28-34, 183) |
| `apps/prototype-description-service/scripts/eval_harness/README.md` | Live-run safety gates (`ACX_EVAL_LIVE=1`, `ACX_EVAL_BASE_URL`, `ACX_EVAL_API_KEY`, `ACX_EVAL_TENANT_ID`) reused by the provider benchmark |
| `docs/tasks/19.0/E19-1-local-cpu-vlm-benchmark-decision-memo.md` | Decision-memo precedent (structure to follow) |
| `docs/tasks/20.0/E20-7-error-logs-usage-accounting-and-budget-controls-task-plan.md` | Sibling plan (not landed) that later owns the usage/budget ledger for deferred integration |

## Verification Strategy

- Deterministic tests (no network):
  - `uv run pytest apps/prototype-description-service/scene/tests/test_description_profiles.py -q` — hosted profile fail-closed unless opted in; opted-in adapter satisfies `DescriptionAdapter` and drives `left_service_boundary`.
  - `uv run pytest apps/prototype-description-service/scripts/eval_harness/tests -q` — `--provider` CLI plumbing with `FakeHostedProviderAdapter`; run record is valid `acx-eval/v1`; `report.build_reports` scores it; `report.score_run_record` re-score is bit-identical (existing determinism check).
- Contract/fixture verification:
  - Assert a hosted describe response carries `provider_disclosure.left_service_boundary == True` and `provider == ProviderMode.HOSTED`.
  - Assert default profile (`seeded`) is unchanged — no hosted adapter is constructed without the opt-in env.
- Manual / runtime-parity (env-gated, real network, opt-in):
  - Real-provider matrix run recorded in the memo: `ACX_EVAL_LIVE=1 ACX_EVAL_BASE_URL=... ACX_EVAL_API_KEY=<eval-tenant> ACX_EVAL_TENANT_ID=<eval-tenant> uv run python -m scripts.eval_harness.cli run --provider <profile> --limit <N>` against a service running the hosted profile, bounded by `--limit`/max-cost cap.

## Slice Delivery

### Slice 1: Hosted provider adapter + fail-closed profile + `--provider` harness flag (fake providers)

**Goal**: Add the hosted `DescriptionAdapter`, register it fail-closed, and extend the existing eval CLI with `--provider` — proven end-to-end against a fake provider with zero default runtime impact.

Changes:

- Add `HostedProviderDescriptionAdapter` (`scene/infrastructure/provider/hosted_provider_adapter.py`) implementing the `DescriptionAdapter` protocol, with a per-call timeout and fail-closed error path; add `FakeHostedProviderAdapter` for tests.
- Register `DescriptionProfile.HOSTED_<provider>` in `PROFILE_SPECS` (`profiles.py`) as `available=False`; resolve it in `get_description_adapter()` (`deps.py`) to the hosted adapter only under the opt-in env, else `UnavailableDescriptionAdapter`.
- Add `--provider` (matrix-capable) to `cli.py` `_common`/`main`; stamp provider into run-record provenance; reuse `fetch_run_record` + `build_reports` unchanged.
- Add non-functional failure posture (see PA-04): reuse `RemoteSceneClient`'s per-request timeout (`_DEFAULT_TIMEOUT_S`) + 3-strike `CircuitOpenError`, and the CLI's per-item isolation + `BoundedStallError` (`--stall-limit`, default 5); add an explicit `--limit`/`--max-images` cap and a `--max-cost` estimated-spend cap that aborts before further paid calls. The adapter itself fails closed (no partial byte leak) on provider timeout/error.

Proof:

- `uv run pytest apps/prototype-description-service/scene/tests/test_description_profiles.py apps/prototype-description-service/scripts/eval_harness/tests -q` green.
- Hosted profile with opt-in off resolves to `UnavailableDescriptionAdapter`; default `seeded` unchanged.
- `--provider` run over the golden manifest with `FakeHostedProviderAdapter` writes a valid `acx-eval/v1` run record + report; each hosted run-record item's `describe.provider_disclosure.left_service_boundary == True` (the harness stores the full describe response under `item["describe"]`; the boundary flag lives there, not in the scored report).

### Slice 2: Real-provider runbook and governance decision memo

**Goal**: Capture env-gated real-provider evidence and record a decision whose disposition is exactly one of `ship | benchmark_only | defer_byok | reject`.

Changes:

- Add an env-gated real-provider runbook section to the harness README (or memo): the `ACX_EVAL_LIVE=1` + eval-tenant-key command, `--limit`/`--max-cost` caps, and the "never the demo tenant" rule reused from the existing harness gate.
- Add `docs/tasks/20.0/E20-11-hosted-provider-decision-memo.md` with a cost/latency/privacy/retention evidence table (numbers promoted from `scripts/eval_harness/out/` run reports), the selected disposition from the canonical enum, and — if `defer_byok` — a named BYOK follow-on task; note deferred E20-7 ledger integration.
- Add provider disclosure + opt-in/fail-closed language to `docs/workbay/contracts/image-description-api.md`.

Proof:

- Decision memo names exactly one disposition ∈ `ship | benchmark_only | defer_byok | reject` and its follow-on scope.
- Report JSON from the real run validates against `schema.SCHEMA` (`acx-eval/v1`) and `report.score_run_record` re-score is bit-identical.
- Contract doc includes provider disclosure and opt-in/fail-closed language.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the eval-harness modules and the `DescriptionAdapter` seam before editing; confirmed no second harness/schema is introduced.
- [ ] Confirmed E20-7 is a plan doc only; recorded that cost/latency land in harness JSON with ledger integration deferred to a named follow-on.

### Checklist for Slice 1: Hosted adapter + fail-closed profile + `--provider` flag

- [ ] `HostedProviderDescriptionAdapter` implements `DescriptionAdapter`; `FakeHostedProviderAdapter` added for tests.
- [ ] Hosted profile registered `available=False`; resolves fail-closed unless opt-in env set; default `seeded` unchanged.
- [ ] `--provider` matrix flag added to existing `cli.py`; reuses `fetch_run_record`/`build_reports`; provider stamped into provenance.
- [ ] Failure posture: per-request timeout + circuit breaker + per-item isolation + `--stall-limit` reused; `--limit`/`--max-images` and `--max-cost` caps enforced; adapter fails closed on provider error.
- [ ] `uv run pytest apps/prototype-description-service/scene/tests/test_description_profiles.py apps/prototype-description-service/scripts/eval_harness/tests -q` green.

### Checklist for Slice 2: Real-provider runbook and decision memo

- [ ] Env-gated real-provider runbook documents the `ACX_EVAL_LIVE` command, eval-tenant-only key, and cost/image caps.
- [ ] Decision memo records cost/latency/privacy/retention evidence and one canonical disposition.
- [ ] Contract docs include provider disclosure and opt-in/fail-closed language.

## Review Readiness

- [ ] No provider enabled by default; hosted profile is fail-closed without the opt-in env.
- [ ] No second benchmark harness, test module, or JSON schema introduced — the VLM-2A harness is reused.
- [ ] BYOK is explicitly deferred (disposition `defer_byok`) or scoped as a named follow-on; not implied by benchmark code.
- [ ] Handoff decision records the governance verdict using the canonical disposition enum.

## Stretch Goals

- [ ] Add a second hosted provider/model to the `--provider` matrix.

## Success Criteria

- [ ] The existing eval harness benchmarks hosted providers over `scene/tests/seed/golden.json` and emits `acx-eval/v1` reports — no parallel harness.
- [ ] Hosted results disclose bytes leaving the boundary (`left_service_boundary == True`) and the default path is unaffected.
- [ ] The decision memo records exactly one disposition ∈ `ship | benchmark_only | defer_byok | reject`, with privacy/subprocessor disclosure and follow-on scope; BYOK is documented and not implied by benchmark code.
</content>
</invoke>
