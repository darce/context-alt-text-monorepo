# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-04 22:45 EST
> - **Author**: Codex GPT-5
> - **Owning Epic**: [docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md)
> - **Epic Short ID**: E20
> - **Target Branch**: `feature/e20-11`
> - **Review Coverage Target**: 2

---

## E20-11. Hosted Provider Benchmark and Governance Decision

## Objective

Benchmark hosted description providers behind operator-owned backend keys and produce a governance decision on whether provider mode belongs in product scope, remains benchmark-only, or requires a later BYOK plan.

## Problem Statement

Provider models may improve quality and latency, but they carry privacy, subprocessor, cost, and retention implications. The product needs evidence and an opt-in governance model before adding provider mode.

## Constraints

- Depends on E20-7 usage/budget controls.
- No BYOK storage in this task unless the decision memo explicitly scopes a follow-on.
- Provider calls must be opt-in, server-side, and disclose bytes leaving the service boundary.

## Workflow Principles

- Benchmark harness is separate from default generation.
- Cost, latency, provider/model id, prompt version, and retention disclosure are recorded per image.
- Decision memo is the deliverable; product enablement is conditional on it.

## Terminology

- **Provider mode**: hosted third-party model invocation where image bytes leave local infrastructure.
- **BYOK**: customer/operator-provided provider key stored or passed by the product.

## Current State Analysis

- E19 `DescriptionAdapterKind.HOSTED_PROVIDER` exists as a forward-looking enum value.
- `provider_disclosure.left_service_boundary` already communicates provider boundary crossing.
- No provider adapter, benchmark harness, opt-in gate, or policy decision exists.

## Target Outcome

A provider benchmark harness can run selected providers on the same image set, output structured comparison JSON, and produce a decision memo with keep/defer/ship criteria, privacy disclosure, and follow-on scope.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/planning-review-guide.md`
- Contracts: `docs/workbay/contracts/image-description-api.md`
- Code: `apps/prototype-description-service/scene/application/description_adapter.py`, `apps/prototype-description-service/scene/config/profiles.py`, `apps/prototype-description-service/scene/infrastructure/vlm/unavailable_adapter.py`
- Handoff/MCP: task `E20-11`; E20-7 usage/budget evidence

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Provider adapter | backend | hosted provider enum/stub only | Benchmark-only adapter facade | no default runtime impact | unit tests with fake providers |
| Usage/cost ledger | WordPress/backend | E20-7 controls | Record benchmark cost/latency/provider metadata | yes | JSON schema validation |
| Policy docs | Product + Engineering | none | Decision memo and provider disclosure language | n/a | planning review |

## Proposed Solution

Add a benchmark-only provider adapter interface and CLI script with fake-provider tests plus optional real-provider runs controlled by environment variables. Record benchmark JSON and a decision memo under `docs/tasks/20.0/`, without enabling provider mode by default.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Backend provider | `apps/prototype-description-service/scene/infrastructure/providers/` | Benchmark-only provider adapters/fakes |
| Profiles | `apps/prototype-description-service/scene/config/profiles.py` | Keep provider profile fail-closed unless enabled |
| Benchmark | `apps/prototype-description-service/scripts/benchmark_hosted_providers.py` | Provider comparison CLI |
| Docs | `docs/tasks/20.0/E20-11-hosted-provider-decision-memo.md` | Governance decision |
| Contract | `docs/workbay/contracts/image-description-api.md` | Provider disclosure and opt-in language |

## Related Files

| File | Note |
| --- | --- |
| `docs/tasks/19.0/E19-1-local-cpu-vlm-benchmark-decision-memo.md` | Decision memo precedent |
| `apps/prototype-description-service/scene/tests/test_description_profiles.py` | Fail-closed profile tests |

## Verification Strategy

- Deterministic tests: `uv run pytest apps/prototype-description-service/scene/tests/test_hosted_provider_benchmark.py -q`
- Contract verification: benchmark JSON schema and provider disclosure docs
- Manual verification: optional env-gated real-provider benchmark recorded in memo

## Slice Delivery

### Slice 1: Benchmark harness with fake providers

**Goal**: Build the provider benchmark harness without default runtime impact.

Changes:

- Add provider adapter facade/fakes and benchmark CLI.
- Keep profile fail-closed unless explicitly enabled.

Proof:

- `uv run pytest apps/prototype-description-service/scene/tests/test_hosted_provider_benchmark.py -q`

### Slice 2: Real-provider runbook and decision memo

**Goal**: Capture benchmark evidence and decide ship/defer/reject.

Changes:

- Add env-gated provider runbook.
- Add decision memo with cost/latency/privacy/retention table and BYOK follow-on decision.

Proof:

- Benchmark JSON validates.
- Decision memo names provider-mode disposition and follow-on scope.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded E20-7 budget controls and E19 provider disclosure fields.
- [ ] Confirmed provider mode remains opt-in/fail-closed.

### Checklist for Slice 1: Benchmark harness with fake providers

- [ ] Provider benchmark CLI supports fake providers and structured JSON.
- [ ] Default profile remains fail-closed.
- [ ] `uv run pytest apps/prototype-description-service/scene/tests/test_hosted_provider_benchmark.py -q` green.

### Checklist for Slice 2: Real-provider runbook and decision memo

- [ ] Runbook explains env-gated real-provider runs.
- [ ] Decision memo records cost/latency/privacy/retention evidence.
- [ ] Contract docs include provider disclosure and opt-in language.

## Review Readiness

- [ ] No provider enabled by default.
- [ ] BYOK is either explicitly deferred or scoped as a separate follow-on.
- [ ] Handoff decision records governance verdict.

## Stretch Goals

- [ ] Add one hosted open-model platform to the benchmark matrix.

## Success Criteria

- [ ] Product has evidence to compare local and hosted provider outputs.
- [ ] Provider mode has explicit privacy/subprocessor disclosure.
- [ ] BYOK decision is documented and not implied by benchmark code.
