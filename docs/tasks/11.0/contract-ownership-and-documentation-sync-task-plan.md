# Task Plan Template

> Use this template for all implementation plans under `docs/tasks/`.
> Task plans describe executable work for one bounded objective.
> Task plans use **slices**, not phases:
>
> - **Phases** belong to epics and describe coarse-grained temporal delivery across multiple task plans.
> - **Slices** are reviewable implementation increments that can be completed, verified, and logged independently.
>
> Favor slices that each produce behavior plus proof. Avoid scaffold-only slices that add placeholders, skipped tests, or empty abstractions without executable value.
> See `docs/agentic/instructions.md` and `docs/agentic/rules/planning-review-guide.md` for repo-wide planning rules.

---

# Contract Ownership and Documentation Sync

## Objective

Stop contract drift by making boundary ownership explicit, closing known schema gaps, adding cross-boundary contract tests, and defining a blocking contract-change gate so boundary changes cannot be considered complete unless the owning contract is updated in the same slice.

## Problem Statement

Cross-service boundaries in this repo have documented contracts (`docs/agentic/contracts/`) and shared schemas (`packages/shared-contracts/schemas/`), but five process-level problems remain:

1. **Inconsistent boundary ownership.** Seven of 12 contract docs already declare `owners:` in YAML frontmatter, but the remaining five do not, and even the existing owner fields list multiple owners rather than identifying a single canonical boundary owner responsible for adapting each payload. This ambiguity led to duplicate adaptation logic and fabricated metadata in recent incidents.
2. **Schema gaps.** `recognition-cluster-snapshot.schema.json` is missing `is_pinned` and `representative_id` despite both fields being used across all three service layers. Finding IDs RSWR-IMPL-008, R-TOPO-02, and R-TOPO-11 have zero codebase references and are silently open technical debt.
3. **No cross-boundary contract tests.** Integration tests exist within each layer, but no test verifies the backend-to-WP-to-TS payload pipeline using shared fixtures. Boundary regressions are caught during manual debugging, not at test time.
4. **No blocking gate.** Review guides check for contract co-changes, but there is no defined blocking gate that prevents a cross-boundary implementation from reaching review-ready or merge-ready status without matching contract evidence.
5. **MCP write guidance can drift from the live tool signature.** Agents still rely on stale examples or remembered optional fields when recording handoff evidence, which produces validation-bounce retries instead of first-try deterministic writes.

## Constraints

- This is a process-and-docs task with targeted schema and test additions; no product feature code changes.
- Cross-boundary contract tests use golden fixture files, not live service calls. The backend, PHP, and TypeScript test suites each validate against the same golden fixture independently.
- Finding audit (RSWR-IMPL-008, R-TOPO-02, R-TOPO-11) requires first checking whether these IDs exist as MCP findings; if they do not, the resolution is a handoff decision documenting their absence rather than an archival action.
- The cross-boundary change protocol in `docs/agentic/rules/development-workflow.md` already exists; this task strengthens it with ownership classification and a blocking gate, not a rewrite.
- Schema additions to `recognition-cluster-snapshot.schema.json` must reflect current production usage; do not add speculative fields.
- MCP write guidance must treat the live tool schema as authoritative over examples, templates, or prior-session memory. Retry logic can recover from drift once, but the durable fix is to update the guidance surface in the same slice.

## Workflow Principles

- Single contract owner per boundary: exactly one layer is allowed to adapt a payload shape between systems. All others consume the contract as-is or raise an explicit error.
- Same-slice contract updates: if implementation changes a boundary, the owning contract must be updated in the same slice. If no contract change is needed, the handoff decision must explicitly state why.
- Evidence before status: review-ready and merge-ready status require documented contract evidence, not just passing tests.
- Schema-on-write: the upstream producer defines the canonical payload shape; downstream consumers validate against it rather than tolerating ambiguity.
- Live MCP signature over prose examples: for MCP write tools, the live tool schema is the source of truth. Guidance must tell agents to prefer the minimal valid payload, not copied rich examples with stale optional fields.
- Validation failures are guidance drift, not just operator mistakes: if a documented MCP write shape fails validation, the same slice must update the relevant contract/rule/template so future agents do not repeat the bounce.

## Terminology

- **Boundary owner**: The single layer responsible for the canonical shape of a cross-service payload. The owner updates the contract; consumers validate against it.
- **Contract-change gate**: A blocking check that prevents cross-boundary work from reaching review-ready status without matching contract evidence.
- **Contract-intake template**: A structured record of what boundary changed, who owns it, whether compatibility is required, and what fixture/test proves the new shape.
- **Golden fixture**: A representative payload sample checked into `packages/shared-contracts/` that multiple test suites validate against to ensure pipeline consistency.
- **Schema-evolution note**: A brief record attached to a schema change documenting what changed, whether backward compatibility is required, and which downstream adapters may be affected.

## Current State Analysis

- 12 contract docs exist under `docs/agentic/contracts/`; 7 already have `owners:` in YAML frontmatter but list multiple owners rather than a single canonical boundary owner; 5 have no owner field at all. Not all 12 are boundary contracts (e.g., `repo-intel-mcp-candidates.md` is an inventory doc, `security.md` is an auth model doc).
- 6 JSON schemas exist under `packages/shared-contracts/schemas/`; `recognition-cluster-snapshot.schema.json` has `representative_thumb_path` but is missing `is_pinned` and `representative_id`.
- `docs/agentic/rules/development-workflow.md` has a Cross-Boundary Change Protocol (5 steps: trigger heuristics, discover owning contract, validate parity, map changed fields to tests, runtime-parity check) but no blocking gate definition.
- `docs/agentic/rules/branch-review-guide.md` has contract-related checklist items but no explicit blocking gate for missing contract co-changes.
- `docs/agentic/contracts/agent-handoff-mcp.md` documents the MCP surface, but current guidance does not yet require agents to prefer live tool signatures and minimal valid write payloads when examples drift.
- Finding IDs RSWR-IMPL-008, R-TOPO-02, R-TOPO-11 appear only in the epic documentation; they have zero codebase references and are confirmed unresolvable.
- No cross-boundary integration tests exist that validate the backend-to-WP-to-TS pipeline using shared fixtures.
- The epic incorrectly identifies `representative_thumb_path` as missing; the field is already present in the schema. The epic note needs correction.
- 1 sample fixture exists (`packages/shared-contracts/recognition/roster-roundtrip.sample.json`) but no cluster snapshot golden fixture.

## Target Outcome

Every major cross-service boundary has a single declared canonical owner in its contract doc. A contract-change checklist and intake template give agents a structured path when touching boundaries. The shared cluster snapshot schema includes all production-used fields. Cross-boundary contract tests at all three layers (Python, PHP, TypeScript) verify the snapshot pipeline using a shared golden fixture. Review guides include a blocking contract-change gate. MCP write guidance tells agents to use live tool signatures and minimal valid payloads instead of stale examples. Stale finding IDs are resolved. Data-pattern rules document single-writer and provenance expectations so agents do not re-introduce fabricated metadata.

## Context Loading

> List the minimum authoritative context an agent should load before implementation.

- Rules: `docs/agentic/instructions.md`, `docs/agentic/rules/development-workflow.md` (Cross-Boundary Change Protocol), `docs/agentic/rules/branch-review-guide.md`, `docs/agentic/rules/planning-review-guide.md`
- Contracts: `docs/agentic/contracts/cluster-snapshot-api.md`, `docs/agentic/contracts/curation-sync-api.md`, `docs/agentic/contracts/recognition-clustering.md`, `docs/agentic/contracts/agent-handoff-mcp.md`
- Schemas: `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json`
- Handoff/MCP state: task ref `agentic-development-process-hardening-epic`; inspect open findings (especially RSWR-IMPL-008, R-TOPO-02, R-TOPO-11 status)
- Epic: `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md` Phase 2 deliverables
- External docs via `ctx7` only if: JSON Schema draft version semantics need verification for `additionalProperties` or composition behavior

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Backend cluster snapshot API | backend | `contracts/cluster-snapshot-api.md` | Add single canonical `boundary_owner:` in frontmatter; verify field coverage | No (greenfield) | Schema validates against production payloads |
| WP proxy/projection layer | wp-proxy | `contracts/cluster-snapshot-api.md` (consumed; backend owns it -- see row 1) + `contracts/clustering-api.md` (provided) | Add `boundary_owner: wp-proxy` to `clustering-api.md`; `cluster-snapshot-api.md` ownership is set in row 1 | No (greenfield) | Existing PHP tests pass |
| Frontend React consumer | frontend | `contracts/clustering-api.md` (consumed; wp-proxy owns it -- see row 2) | No ownership change needed; frontend is a consumer. Existing Vitest tests verify consumption. | No (greenfield) | Existing Vitest tests pass |
| MCP handoff surface | agentic-tooling | `contracts/agent-handoff-mcp.md` | Add single canonical `boundary_owner:` in frontmatter | No | No code change |
| Shared snapshot schema | backend (canonical) | `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json` | Add `is_pinned`, `representative_id` | No (greenfield) | JSON Schema validation; golden fixture validates |

## Proposed Solution

Create a contract-change checklist with boundary ownership classification, close known schema gaps, add cross-boundary contract tests using golden fixtures, and integrate a blocking contract-change gate into review guides. Five slices, each producing behavior plus proof.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| docs/rules | `docs/agentic/rules/contract-change-checklist.md` | New: boundary owner table, change checklist, contract-intake template, data-pattern rules, schema-evolution notes guidance |
| contracts | `docs/agentic/contracts/*.md` (boundary contracts only) | Add single canonical `boundary_owner:` to frontmatter; skip non-boundary docs (repo-intel-mcp-candidates, security, subagent-bridge-interface-note) |
| schema | `packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json` | Add `is_pinned` (boolean), `representative_id` (string, nullable) to cluster item |
| fixture | `packages/shared-contracts/recognition/cluster-snapshot.golden.json` | New: production-representative golden fixture for cross-boundary tests |
| review | `docs/agentic/rules/branch-review-guide.md` | Add contract-change gate checklist items |
| review | `docs/agentic/rules/planning-review-guide.md` | Add contract-ownership verification check |
| rules | `docs/agentic/instructions.md` | Add MCP write-signature rule: live tool schema beats examples; use minimal valid payloads |
| contract | `docs/agentic/contracts/agent-handoff-mcp.md` | Add signature-drift guidance for common MCP writes and validation-bounce recovery |
| tests/php | `apps/prototype-wp-alt-context/tests/Unit/ContractSnapshotSchemaTest.php` | New: validate golden fixture against PHP projection expectations |
| tests/python | `apps/prototype-description-service/recognition/tests/unit/test_snapshot_contract.py` | New: validate golden fixture against backend snapshot producer output shape |
| tests/ts | `apps/prototype-wp-alt-context/js/admin/api/__tests__/snapshotContract.test.ts` | New: validate golden fixture against TypeScript type expectations |
| epic | `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md` | Fix `representative_thumb_path` note; update Phase 2 status; update consolidated checklist |

## Related Files

| File | Note |
| --- | --- |
| `docs/agentic/rules/development-workflow.md` | Contains existing Cross-Boundary Change Protocol; new checklist complements rather than replaces it |
| `docs/agentic/instructions.md` | Add the rule that live MCP tool signatures are authoritative over remembered/documented examples |
| `packages/shared-contracts/README.md` | May need update to reference golden fixtures and ownership model |
| `docs/agentic/contracts/agent-handoff-mcp.md` | Handoff contract surface should carry the signature-drift rule and minimal-payload guidance for common writes |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Consumes snapshot payloads; source of truth for which fields PHP actually uses |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Produces snapshot payloads (GET /clusters/snapshot endpoint); source of truth for which fields backend actually emits |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/unit/test_snapshot_contract.py -q 2>&1 | tee /tmp/pytest_contract.txt`
  - `cd apps/prototype-wp-alt-context && vendor/bin/phpunit tests/Unit/ContractSnapshotSchemaTest.php 2>&1 | tee /tmp/phpunit_contract.txt`
  - `cd apps/prototype-wp-alt-context && npx vitest run js/admin/api/__tests__/snapshotContract.test.ts 2>&1 | tee /tmp/vitest_contract.txt`
- Contract/fixture verification:
  - Golden fixture validates against `recognition-cluster-snapshot.schema.json` (can verify with a JSON Schema validator or inline test assertion)
  - All boundary contract docs have a single canonical `boundary_owner:` in their frontmatter; non-boundary docs (inventory, auth model) are excluded from the retrofit
- Manual verification:
  - Contract-change checklist is internally consistent and references real boundary owners
  - Review guides include the blocking gate language
  - `instructions.md` and `agent-handoff-mcp.md` both say live tool signatures are authoritative and recommend minimal valid payloads for MCP writes
  - Epic Phase 2 status and consolidated checklist are updated
- MCP verification:
  - Finding IDs RSWR-IMPL-008, R-TOPO-02, R-TOPO-11 are verified in MCP: archived if present, or absence documented via handoff decision if not

## Slice Delivery

### Slice 1: Boundary Ownership Registry and Contract-Change Checklist

**Goal**: Every major boundary has a single declared canonical owner; a contract-change checklist exists for agents to follow when touching cross-service payloads.

Changes:

- Create `docs/agentic/rules/contract-change-checklist.md` containing:
  - Boundary ownership table (backend, WP proxy, frontend, MCP; with specific contract files and adaptation points)
  - Contract-change checklist steps (6-8 steps from trigger through verification)
  - Contract-intake template (which boundary, who owns it, compatibility requirement, fixture/test evidence, downstream assumption changes)
  - Schema-evolution notes guidance (what changed, compatibility, affected downstream)
- For the 7 boundary contracts that already have `owners:` in YAML frontmatter, replace the `owners:` field with a single canonical `boundary_owner:` field. The 7 contracts are: `cluster-snapshot-api.md`, `cluster-delta-api.md`, `clustering-api.md`, `curation-sync-api.md`, `recognition-clustering.md`, `recognition-media-xmp-mapping.md`, `suggestion-extensions-api.md`
- For the 2 boundary contracts with no existing YAML frontmatter, create a new `---` frontmatter block at the top of the file containing only a `boundary_owner:` field. The 2 contracts are: `agent-handoff-mcp.md` and `conflict-resolution-sync-contract.md`
- Skip non-boundary docs (`repo-intel-mcp-candidates.md`, `security.md`, `subagent-bridge-interface-note.md`) that are reference/inventory docs rather than contract boundaries

Proof:

- Every boundary contract doc has a single canonical `boundary_owner:` field
- Non-boundary docs are excluded from the retrofit
- Contract-change checklist document is complete and internally consistent
- Checklist references real contract paths and boundary owners

### Slice 2: Shared Schema Gap Closure

**Goal**: `recognition-cluster-snapshot.schema.json` includes all fields used in production; the epic note about `representative_thumb_path` is corrected.

Changes:

- Add `is_pinned` (boolean, optional, default false) to the cluster item definition in `recognition-cluster-snapshot.schema.json`
- Add `representative_id` (string, nullable, optional) to the cluster item definition
- Fix the epic note: `representative_thumb_path` is already present in the schema; the epic text should reflect this
- Update `packages/shared-contracts/README.md` if the schema-evolution guidance from Slice 1 warrants a reference

Proof:

- Schema parses without errors
- `is_pinned` and `representative_id` fields are present in the cluster item `properties`
- Epic note is factually correct

### Slice 3: Golden Fixture and Cross-Boundary Contract Tests

**Goal**: Cross-boundary tests validate the backend-to-WP-to-TS snapshot pipeline at all three layers using a shared golden fixture.

Changes:

- Create `packages/shared-contracts/recognition/cluster-snapshot.golden.json` with a production-representative cluster snapshot payload (2-3 clusters, mix of optional/required fields, including `is_pinned` and `representative_id`)
- Create `apps/prototype-description-service/recognition/tests/unit/test_snapshot_contract.py`: Python test that loads the golden fixture and validates it against the backend snapshot producer's output shape (key presence, types, required vs optional fields). Existing shape assertions in `test_api_clusters.py::test_get_tenant_snapshot_returns_correct_shape` validate live API behavior; this test validates the golden fixture against the same field expectations independently
- Create `apps/prototype-wp-alt-context/tests/Unit/ContractSnapshotSchemaTest.php`: PHP test that loads the golden fixture and validates it against the projector's expected field set
- Create `apps/prototype-wp-alt-context/js/admin/api/__tests__/snapshotContract.test.ts`: TypeScript test that loads the golden fixture and validates it against the frontend's expected type shape

Proof:

- `cd apps/prototype-description-service && pyenv exec python -m pytest recognition/tests/unit/test_snapshot_contract.py -q 2>&1 | tee /tmp/pytest_contract.txt`
- `vendor/bin/phpunit tests/Unit/ContractSnapshotSchemaTest.php` passes
- `npx vitest run js/admin/api/__tests__/snapshotContract.test.ts` passes
- Golden fixture validates against updated JSON schema

### Slice 4: Contract-Change Gate and MCP Write Discipline

**Goal**: Boundary changes that lack co-changed contracts are blocked at review time, and MCP write guidance no longer encourages stale example payloads.

Changes:

- Add a "Contract-Change Gate" section or checklist items to `docs/agentic/rules/branch-review-guide.md`:
  - No review-ready status if a boundary implementation changed without an owning contract update, explicit no-change rationale, or matching fixture/schema evidence
  - No merge-ready status if handoff lacks the boundary owner, verification path, and current contract references
- Add a contract-ownership verification check to `docs/agentic/rules/planning-review-guide.md`:
  - Plans that reference boundary changes must identify the owning contract and state whether compatibility is required
  - If the change touches a boundary field, check whether the shared schema is updated in the same slice
- Add planning-review-guide check: if a finding ID is cited in a remediation plan, it must resolve to a located code site before implementation starts
- Add an MCP write-signature rule to `docs/agentic/instructions.md`:
  - The live MCP tool schema is authoritative over examples, templates, or prior-session memory
  - Prefer the minimal valid payload for common write tools instead of copying rich examples with optional fields
- Update `docs/agentic/contracts/agent-handoff-mcp.md` with a signature-drift rule:
  - If a write call fails validation, treat it as guidance drift
  - Retry once with the minimal payload accepted by the live signature
  - If docs/templates were wrong, update them in the same slice or record the drift as follow-up work

Proof:

- Branch review guide contains blocking gate language for contract co-changes
- Planning review guide contains contract-ownership verification items
- `instructions.md` and `agent-handoff-mcp.md` both document live-signature-over-example guidance for MCP writes
- Gate language references the contract-change checklist from Slice 1

### Slice 5: Data-Pattern Rules, Canonical Enums, and Finding Cleanup

**Goal**: Healthy data-pattern rules are documented; stale findings are archived; canonical enum surfaces are identified.

Changes:

- Add a "Healthy Data Patterns" section to the contract-change checklist (created in Slice 1):
  - One writer per fact: each boundary field has exactly one authoritative source
  - Explicit provenance for derived metadata: if a field is computed from upstream data, document the derivation
  - No silent dual-write drift: if two layers both write the same field, document which one is canonical and gate the other
  - Read-after-write expectations: document consistency expectations for boundary payloads
- Identify and list canonical enum/constant locations in the boundary ownership table:
  - `curation_state` values: backend `CurationState` enum, PHP `CurationState` backed enum, TypeScript `CurationState` const
  - `sync_status` values: locations across layers
  - `conflict_type` values: `contracts/conflict-resolution-sync-contract.md` codes
- Audit and close/archive finding IDs RSWR-IMPL-008, R-TOPO-02, R-TOPO-11:
  - First verify whether these IDs exist as MCP findings. If they exist, archive/close them with a note citing zero codebase references.
  - If they do not exist in MCP, record a handoff decision documenting their absence and confirming they are not actionable technical debt. Remove them from the epic deliverables list or mark them as documentation-only cleanup.
- Update epic Phase 2 status and consolidated checklist

Proof:

- Data-pattern rules section exists in contract-change checklist
- Canonical enum locations are listed in boundary ownership table
- RSWR-IMPL-008, R-TOPO-02, R-TOPO-11: either MCP findings are archived (if they existed in MCP), or a handoff decision documents their absence and confirms they are not actionable technical debt
- Epic Phase 2 consolidated checklist items are checked

## Lane Decomposition (Multi-Agent)

> This task is primarily documentation and schema work with two small test additions.
> Single-lane execution is appropriate; the slices are sequential and share the same contract surface.
> Multi-agent decomposition is not recommended unless the operator explicitly requests it.

---

# Consolidated Checklist

## Context and Ownership

- [x] Loaded development-workflow.md Cross-Boundary Change Protocol, branch-review-guide.md, planning-review-guide.md
- [x] Loaded cluster-snapshot-api.md, curation-sync-api.md, recognition-clustering.md contracts
- [x] Loaded epic Phase 2 deliverables and exit criteria
- [x] Inspected MCP state for open findings RSWR-IMPL-008, R-TOPO-02, R-TOPO-11

## Slice 1: Boundary Ownership Registry and Contract-Change Checklist

- [x] Created `docs/agentic/rules/contract-change-checklist.md` with boundary owner table
- [x] Checklist includes contract-change steps (trigger through verification)
- [x] Checklist includes contract-intake template
- [x] Checklist includes schema-evolution notes guidance
- [x] Added single canonical `boundary_owner:` to 9 boundary contract docs (skipped 3 non-boundary docs)
- [x] Verified checklist references real contract paths and boundary owners

## Slice 2: Shared Schema Gap Closure

- [x] Added `is_pinned` (boolean, optional) to cluster item in `recognition-cluster-snapshot.schema.json`
- [x] Added `representative_id` (string, nullable, optional) to cluster item
- [x] Fixed epic note: `representative_thumb_path` already present in schema
- [x] Schema parses without errors

## Slice 3: Golden Fixture and Cross-Boundary Contract Tests

- [x] Created `packages/shared-contracts/recognition/cluster-snapshot.golden.json` golden fixture
- [x] Golden fixture includes `is_pinned` and `representative_id` fields
- [x] Created Python contract test: `recognition/tests/unit/test_snapshot_contract.py`
- [x] Python test passes: `pyenv exec python -m pytest recognition/tests/unit/test_snapshot_contract.py`
- [x] Created PHP contract test: `tests/Unit/ContractSnapshotSchemaTest.php`
- [x] Created TypeScript contract test: `js/admin/api/__tests__/snapshotContract.test.ts`
- [x] PHP test passes: `vendor/bin/phpunit tests/Unit/ContractSnapshotSchemaTest.php`
- [x] TypeScript test passes: `npx vitest run js/admin/api/__tests__/snapshotContract.test.ts`

## Slice 4: Contract-Change Gate and MCP Write Discipline

- [x] Added contract-change gate to `branch-review-guide.md` with blocking language
- [x] Added contract-ownership verification to `planning-review-guide.md`
- [x] Added finding-ID resolution check to `planning-review-guide.md`
- [x] Added live-signature-over-example MCP write rule to `instructions.md`
- [x] Added signature-drift and minimal-payload guidance to `agent-handoff-mcp.md`
- [x] Gate references the contract-change checklist from Slice 1

## Slice 5: Data-Pattern Rules, Canonical Enums, and Finding Cleanup

- [x] Added "Healthy Data Patterns" section (one writer per fact, explicit provenance, no dual-write, read-after-write)
- [x] Listed canonical enum/constant locations in boundary ownership table
- [x] Verified RSWR-IMPL-008, R-TOPO-02, R-TOPO-11 existence in MCP; archived if present or recorded absence decision if not
- [x] Updated epic Phase 2 status to in-progress or complete
- [x] Updated epic Phase 2 consolidated checklist items

## Review Readiness

- [x] No boundary-touching implementation is left without matching contract/doc/fixture evidence
- [x] Handoff decision records the change, verification, and any contract implications
- [x] Epic status and consolidated checklist reflect completed work

## Success Criteria

- [x] Every major cross-service boundary contract has a single canonical `boundary_owner:` in its frontmatter
- [x] `recognition-cluster-snapshot.schema.json` includes `is_pinned` and `representative_id`
- [x] Cross-boundary golden-fixture tests validate the snapshot pipeline at all three layers (Python, PHP, TypeScript)
- [x] Review guides include a blocking contract-change gate
- [x] MCP write guidance treats the live tool signature as authoritative and tells agents to prefer minimal valid payloads
- [x] Stale finding IDs (RSWR-IMPL-008, R-TOPO-02, R-TOPO-11) are resolved (archived or documented as absent)
- [x] A boundary change cannot reach review-ready status without matching contract evidence
