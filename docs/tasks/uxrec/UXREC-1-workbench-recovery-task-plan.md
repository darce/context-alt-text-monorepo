# UXREC-1 workbench recovery task plan

**Design proposal — first author/classification dispatch; awaiting independent map gate. Not approved, running product work, deployed or accepted.** 2026-10-21. Objective: make current attention distinguishable from retained audit history, keep unknown service copy inside the supported operating envelope, and expose repeated face evidence without rewriting identity or action targets.

Read [the inventory](../../assessments/current/UXREC-1-ux-inventory.md) for wide/narrow screens, source/target matrix, interaction outcomes, Canon citations and FIR research. Map JSON is SSOT; reuse the three existing maps. Design author owns only their JSON/derived Markdown, their three visible projection entries, this plan and the inventory. No production JS/TS/PHP/Python edits in this dispatch.

## Source and prior art

Requested initial source `70cb608c5cc6ee7e1081eab1cc85626ccb96bf2f`; native sandbox starts `d4760d2ba12869b0283a25c342b005e3cdc1aff1` (history-stripped, remote-severed). Requested object is absent, so coordinator exact-source equivalence is an inherited assertion, not independently verified here. Do not fetch root main or inspect sibling trees to resolve it. Preserve the initial unrelated `uv.lock` edit. Source evidence comes from targeted producer reads because no graph tools are exposed. Supplied symbol anchors are graph-verified prior art; worker codemap remains typed `bad_json/unavailable`, not a successful call. UXREC-1 ONNX reinjection is `skipped:no_embeddings`; inherited MAINT and cross-task semantic packets remain evidence only.

Source-fixed regressions to preserve: mandatory roster vs advisory suggestion loading, top-unlabeled object response/empty array, dormant unavailable-toast suppression, blur/Enter URL/key save plus acknowledged stored readback and subsequent health, tenant-scoped describe remount recovery, retention cause/checking/checked-at/real refetch, and actual GPU status refetch. Rebuilding these would duplicate integrated work and risk response-shape and credential regressions. DW3-UX0924-04 timeline reconciliation is INTEGRATED per supplied history and source mechanism; four July rows remain unverified. UX0924-03/DW3-UX0924-05 identity repair remains DEFERRED; CURUX is unmerged, no active implementation confirmed.

Research prior art: `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` v13 caption and v12 AuraFace sections. Exact model-space/version/dimension/normalization/namespace requirements are recorded in the inventory. Repeated source/crop evidence cannot decide camera duplicate vs detector overlap vs model recall. User-supplied Emma ground truth is accepted, with no new naming from photos/file names. No corpus re-inference, threshold tuning or activation belongs to these slices.

## Dependencies and ownership

Applied Canon v0.26.2 from the pinned manifest; https://github.com/darce/heuristics-canon . [GRPH-01] **Model the work as a DAG, then topological-sort**, `lexicons/graph-theory.md#grph-01`, *The Algorithm Design Manual, ch. 7*: edges below mean actual prerequisites, not convenient scheduling. [GRPH-09] **Colour the conflict graph**, `lexicons/graph-theory.md#grph-09`, *Graph Theory with Applications, ch. 8*: file collisions are conflict edges, separate from data dependencies. No resource-count optimality is claimed. GRPH-07 was read but no capacity-limited worker assignment occurs here; no subagents were spawned.

```text
MAP design ----> independent map gate ----> TIMELINE source/test slice ---+
                                    +----> GPU_STATUS source/test slice -+-> source review
                                    +----> IDENTITY source/test slice ---+
CORPUS probe ------------------------------> identity diagnosis          |
RUNTIME grant + deployed artifact/config ------------------------------> runtime acceptance
```

DAG has no back edge. MAP/RUNTIME/CORPUS are independent initial lanes; no product owner waits for unrelated runtime configuration to write a truthful source test after the map gate. Corpus conclusions are required for identity-repair claims, not the evidence-only disclosure. Runtime acceptance requires a returned grant and exact deployed artifact/config evidence; neither is present. Independent source review can proceed before runtime acceptance, but cannot substitute for it.

| Candidate owner after map gate | Verified production files and focused tests (all under `apps/prototype-wp-alt-context/`) | Boundary / end state |
| --- | --- | --- |
| TIMELINE | `js/admin/pages/workbench/DeadLetterPanel.tsx`; `js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx` | Current attention defaults to failed; explicit pending/conflict status choices and explicit History; retain server records and existing guarded mutations. |
| GPU_STATUS | `js/admin/pages/workbench/gpuStatePresentation.ts`; `js/admin/pages/workbench/__tests__/gpuStatePresentation.test.ts` | Unknown/null notice no longer promises CPU continuation. Preserve canonical labels, running/warming/error/retry behavior and existing drafts. |
| IDENTITY | `js/admin/pages/workbench/identity-clusters/utils.ts`, `IdentityClusterItem.tsx`, **`IdentityClusterList.tsx`**; corresponding `__tests__/utils.test.ts`, `IdentityClusterItem.test.tsx`, `IdentityClusterList.test.tsx` | Separate repeated-evidence projection/disclosure from existing grouping. No arbitrary collapse; unchanged editable cluster/person and identity-specific mutation targets. |

Anchor correction: candidate `IdentityClusters` wrapper is actually `IdentityClusterList.tsx:405`, called from `MediaSelectionTableBody.tsx:598`. `ClusterPreview.tsx` is a noninteractive thumbnail; item label button enters naming. The pre-existing identity map describes target chip/workspace navigation, not an implemented avatar action. `ClusterReviewPanel.tsx:45` exists, takes one clusterId, and removes an identity via `removeClusterMember(identityId, true)`. Existing review navigation can be reused only where wired; no fake merge UI is accepted. If disclosure requires review wiring outside owned files, stop that extension for coordinated ownership and keep the independently useful evidence-only slice.

No pairwise production file conflicts among TIMELINE/GPU_STATUS/IDENTITY: they may proceed independently after the map gate. Shared maps are authored here and reviewed as one design batch, not concurrently rewritten by all three owners. MediaSelection, ActivityStatusStrip, AdvancedDrawer and WorkbenchPage remain reserved by WBTRUST5 plans. ScanTabContent/open-review lifecycle and ClusterReviewPanel are producer evidence, not granted new ownership. Cross-boundary requirements need an explicit coordinated extension, not silent file claims. Reaper, global environment, upstream WorkBay and foreign sandboxes are excluded.

## Smallest slices and RED before GREEN

Commands below are **future product-owner selectors**, not tests executed in this design dispatch. Run from `apps/prototype-wp-alt-context` using existing offline dependencies. Use `npm test --`, not `test:agent` (which suppresses failure). First add the named behavioral assertion and show RED against unchanged production source; then implement the smallest owned change and rerun the same selector GREEN. Finally run the full touched test files. The new test names below are proposed selectors; they do not falsely assert tests already exist.

### TIMELINE: attention without deleting audit history

Producer contract: `DeadLetterPanel.tsx:552` calls `useOutboxOperations({status,limit,offset})`; `js/admin/api/recognition/conflictApi.ts:100` sends a single status with bounded GET. Existing failed operations query is separate. Keep these exact response shapes. A synthetic `attention` status would be unsupported. Smallest slice changes panel-local view/default and gates the existing all-status timeline behind History. Attention exposes individual failed/pending/conflict choices with server-filtered pages. Do not filter one all-status page then present its count as the unresolved total. Preserve failed retry/discard confirmations and response announcements.

```sh
npm test -- js/admin/pages/workbench/__tests__/DeadLetterPanel.test.tsx -t 'UXREC-1 current attention'
```

Proposed RED cases: initial view excludes acknowledged/discarded audit rows; explicit History reveals the unchanged fixtures; empty failed attention does not say history is empty; pending/conflict selection sends the actual single status; switching views resets/selects appropriate pagination and never sends POST; old audit records survive re-entry; retry says queued and discard remains guarded. Include failed refresh with retained history vs no-data failure, busy retry, focus retention and accessible view controls. GREEN must preserve all existing panel tests. Exact four live July records are runtime/data acceptance only, never unit-fixture proof.

### GPU_STATUS: truthful unknown notice

Producer proof: `apps/prototype-description-service/api/main.py:_description_adapter_readiness` distinguishes adapter/profile availability and reason. `scene/application/describe_run_worker.py:_usable_cpu_describe_one` / `_apply_warmup_cpu_fallback` continue on CPU only when configured usable; otherwise typed failure. This supports removing the unconditional promise; it does not grant frontend inference of a capability from generic health.

```sh
npm test -- js/admin/pages/workbench/__tests__/gpuStatePresentation.test.ts -t 'UXREC-1 unknown capability'
```

Proposed RED: null and UNKNOWN notice make no promise to continue on CPU and explicitly leave description readiness unconfirmed. GREEN changes presentation copy only. Retain existing full-file tests for exhaustive states and consequence copy. No new orchestration, no broad copy rewrite, no state flattening: actual starting/running/overdue/failure remain visible; existing CPU drafts remain reviewable and item-tier truthful. Existing source-fixed dormant suppression and persistence are regression checks, not new feature claims.

Existing regression selectors (run only if relevant cross-file behavior is changed in a later coordinated slice):

```sh
npm test -- js/admin/hooks/__tests__/useBulkDescribe.test.tsx -t 'keeps a pending warmup across remount'
npm test -- js/admin/hooks/__tests__/describeOperationStore.test.ts
```

### IDENTITY: explicit evidence, unchanged targets

`groupIdentitiesByClusters` preserves person-first/cluster-second grouping and identityClusterIds while deduplicating same-face within a group. Add a separate pure evidence projection if necessary; do not replace grouping with connected components, change the arbitrary first representative into a mutation target, or hide unresolved residue. Match only supported source/face correspondence; disclose geometry-based ambiguity. User-supplied same-person labels do not authorize automatic merge of other observations.

```sh
npm test -- js/admin/pages/workbench/identity-clusters/__tests__/utils.test.ts -t 'UXREC-1 repeated face evidence'
npm test -- js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterItem.test.tsx -t 'UXREC-1 evidence disclosure'
npm test -- js/admin/pages/workbench/identity-clusters/__tests__/IdentityClusterList.test.tsx -t 'UXREC-1 preserves group targets'
```

Proposed RED: exact source/face evidence in two groups yields inspectable references, not one collapsed person; overlapping different boxes and different photos are not falsely exact duplicates; missing media/bbox/face refs stay unavailable; A~B~C never creates A=C identity; existing group order/member mappings/naming target/removal identity remain unchanged. Disclosure shows source label, proportional crops, exact group/face references, displayed/available counts and incomplete/truncated state. Compare actual same-face supplied fixtures without inventing corpus IDs. Keyboard disclosure, review focus return, narrow wrapping, mandatory-roster-ready/advisory-loading naming and backend_proxy read-only behavior remain valid. No merge control unless the source path truly supports it and its existing preview/mutation target survives.

## Design validation receipt and review gate

Author window limit: 1800 seconds; all work stayed in this native VM with no subagents. VM-only, bounded to three maps; no npm installation/extraction needed because Node 22.23.1 handles the existing parity module with `--experimental-strip-types`. No JS unit suite or product runtime was run. Native `ux-map` executable absent (`command -v ux-map` returned no path); available source package `/home/gate/wb/agentic-protocol-monorepo/packages/mcp-workbay-canvas/src` imported `UxMap`, `render_markdown_bundle`, `critique_map` successfully. `/home/gate/canvas-reference-20261018` was not treated as code.

Executed from repo root:

```sh
PYTHONPATH=/home/gate/wb/agentic-protocol-monorepo/packages/mcp-workbay-canvas/src python apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py workbench-operator-loop describe-gpu-tier workbench-identity-chips
PYTHONPATH=/home/gate/wb/agentic-protocol-monorepo/packages/mcp-workbay-canvas/src python apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py --check workbench-operator-loop describe-gpu-tier workbench-identity-chips
PYTHONPATH=/home/gate/wb/agentic-protocol-monorepo/packages/mcp-workbay-canvas/src python /tmp/uxrec_validate.py
```

Render and scoped producer/consumer parity passed, three maps. Renderer parity uses 10-second subprocess deadlines per map; whole command completed in seconds. `/tmp/uxrec_validate.py` is a non-product verification helper: it loads strict Canvas UxMap after stripping only the renderer's documented local extensions (`domain_state_mappings`, `slices`, action `when`, screen `action_states`), compares baseline/current critique, checks at most one primary per screen, checks all screen-detail headings remain inside `## Screens` before another level-two heading, and verifies pinned manifest digests. Initial helper expected bare-ID headings and failed; corrected to actual `### title (id)` format and passed. No renderer or global test source changed.

Scoped automated critique uses Canvas's historical `uxmap-critique/1`, canon_revision `resume-20260912`. It is a structural proxy, **not Canon v0.26.2 rule authority**. Baseline/current results:

| Map | Before → after | Classification |
| --- | --- | --- |
| workbench-operator-loop | 1 → 1 | Inherited HAI-01 high at workbench-scan / z-review-suggestions-group-card evidence_linked; unchanged outside this slice; do not mark evidence_linked true without evidence. |
| describe-gpu-tier | 1 → 1 | Inherited INT-07 high on dashboard describe-single preview_required; unchanged dashboard action, outside GPU unknown-copy slice. |
| workbench-identity-chips | 1 → 0 | Existing entry lacked primary; design selects existing review action as one primary. This is map intent, not proof of implemented navigation. |

No new structural critique findings. Independent map gate must explicitly disposition the inherited highs and review proposed behavior before product work. Passing deterministic parity is not whole-product approval. Manual critique: the wide/narrow sketches keep source captions and crops together, visible error recovery and one contextual primary; exact corpus IDs are unavailable, so fixtures are explicitly symbolic. No decorative evidence, filename-based identity or hidden outcome-changing references. Compare rendered Screens/code-reference boundaries (Q-R0-01) before gate: existing relocation function keeps Code references ahead of Screens; every changed map's detail blocks were checked. No broad rebaseline or foreign-map edits.

Known inherited verification limits remain unclaimed: workbench-2pane red, historical Codex spawn EPERM8, ten unrelated map-hash drifts, inherited HAI01. No broad suite was rerun to absorb these into scope.

## Risks and runtime acceptance separation

- Single-status API cannot produce an accurate aggregate unresolved view without more bounded queries or backend contract work. This plan deliberately selects an existing failed default and explicit attention status choices. If a combined total is required, coordinate a separate contract slice.
- Repeated visual evidence may expose duplicate membership without explaining its cause. Do not assert detector repair or recognition recall improvement; CORPUS owns diagnosis and independent evidence.
- Reference paths in maps can outpace implemented navigation. All UXREC changes are marked proposed; existing identity-map navigation is explicitly target-only. Readiness integrations or reserved composition changes require a new ownership decision.
- Stored run recovery can fail with storage restrictions, expired/mismatched tenant context or unavailable backend. Source tests cannot establish durability on the exact deployed site; show the actual storage limit.
- Quiet unknown copy must not suppress genuine run errors, accepted-run deadlines, cancellation failure or existing drafts. Those remain regression acceptance requirements.

RUNTIME has no returned service window grant. No deployment, GPU start/warmup, model switch, service restart, authenticated data mutation or credential generation in this dispatch. Later authorized acceptance must bind exact deployed build and tenant, capture service configuration/readiness separately from recognition/API health, test genuine starting/result completion, navigate/reload the accepted run without duplicate submit, verify cancellation/retry outcomes, verify retention Retry's new checked_at and actual upstream recovery, and inspect the four July records' eligibility/history without blanket deletion. Product unit tests cannot establish these outcomes. Billing and ADR014 provider decisions are excluded.

Review handoff: independent MAP gate first; TIMELINE/GPU_STATUS/IDENTITY remain independent candidate owners, not active/approved assignments. Commit only this design write-set with worktree-name-prefixed subject, no push to product/main.
