# WBRC-1: Workbench facial recognition controls

Date: 2026-10-21. Author: Codex. Project: prototype-wp-alt-context.
Task ID: WBRC-1. Target Branch: `feature/wbrc-1`.

## Objective

Expose the site's facial recognition policy beside the Workbench scan actions, with equally discoverable enable and disable actions. Reuse the administrator's existing persisted policy and make pending, rejected, unknown, and confirmed states clear.

## Problem Statement

Debt #32 records a connected LocalWP site whose scan failed with `recognition_disabled` because the Workbench hid a separate site policy prerequisite. Connection, enabled policy, and successfully completed inference are distinct facts.

## Constraints

- All implementation, model review, builds and tests run remotely. Local worktrees receive only mechanical Git imports and orchestration artifacts.
- `RecognitionPolicy` remains the sole store, with cold-start default false. Settings writes retain `manage_options` authorization.
- Toggling policy submits no media, starts no GPU, deletes no identities, and cancels no accepted jobs. Production onboarding, description configuration, benchmark reports, and unfinished CURUX provenance/ranking work are separate.
- Preserve sibling bake-off processes, worktrees, paths and reservations. Unknown remote job metadata is not deletion authority.

## Workflow Principles

Canon v0.26.2, all 53 release-manifest digests verified. SECD-12 **Biometric opt-in default**, *Face Recognition Technology (Compulsory Visibility)* ch. 2, preserves affirmative opt-in. SECD-08 **Make the safe path the easy path**, *Security Engineering*, keeps disablement equally accessible. NAV-06 **Frequency elevates chrome**, *Designing Interfaces, 3rd ed.* and *Microinteractions* ch. 2, keeps this safety control where recognition happens. WP-03 **Gate admin with capabilities**, *WordPress Security APIs* §capabilities, retains server enforcement. FORM-05 **Inline actionable errors**, *Designing Interfaces, 3rd ed.*, and FORM-08 **Echo-back stored interpretation**, *Pattern Languages of Program Design* ch. 10, require local feedback and confirmed readback. CARD-12 / Principle 10 require policy text and behavior to agree.

GRPH-01 **Model the work as a DAG, then topological-sort**, *The Algorithm Design Manual* ch. 7, and GRPH-09 **Colour the conflict graph**, *Graph Theory with Applications* ch. 8, yield disjoint author slices and an explicit join. GRPH-07 **Cast assignment as bipartite matching, then flow**, *The Algorithm Design Manual* ch. 8, bounds admission against measured VM resources.

## Terminology

- Confirmed state: a validated boolean read from the existing policy producer.
- Bootstrap policy: a safe page-load snapshot plus capability hint, never an authorization grant or second store.

## Current State Analysis

- `src/settings/class-recognition-policy.php:RecognitionPolicy` normalizes storage and defaults to false.
- `src/api/class-settings-controller.php:SettingsController::get_settings`, `save_settings`, and `can_manage_settings` expose the boolean, verify persistence, and gate settings access. Save returns HTTP 200 with `result` and `saved` even for field failure; inspect that contract.
- `js/admin/api/settingsApi.ts:fetchSettings` rejects missing/nonboolean policy. `saveSettings` accepts a partial payload.
- `js/admin/pages/SettingsPage.tsx:SettingsPage` uses `queryKeys.settings.all`. `WorkbenchPage.tsx:WorkbenchPageContent` has a suitable scan-control host.
- `src/admin/class-admin.php:Admin::localize_spa_config` and `js/admin/api/config.ts:normalizeConfig` own the PHP/TypeScript bootstrap boundary.
- `docs/ux-maps/workbench-operator-loop.uxmap.json` is the existing screen/zone/state inventory; extend it instead of creating another map.

All paths above are relative to `apps/prototype-wp-alt-context/`.

## Target Outcome

A compact secondary control shows Facial recognition: On / Off and its site-wide effect. Admins can explicitly enable or disable; pending and readback failure keep mutation unavailable until state is known. Nonadmins see the page-load policy snapshot and administrator explanation, with no write action. Missing or malformed bootstrap is unknown, never silently Off. Unknown admin state can recover through the existing Settings read. No repeated opt-in prompt follows a persisted choice.

## Context Loading

- Debt: `docs/tasks/tech-debt/workbench-recognition-controls.md`.
- Continuation: `cont-20261021T161808871329Z-c56fa43f`; setup is done, fresh inference remains unverified.
- ONNX semantic prior art: WBUX-6 findings 10333/10342/10376 (failed storage, malformed boolean, add-option failure); CURUX 19129 (do not resend acknowledged secrets after failed readback). Historical findings are advisory, not current reopened defects.
- Research context: `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`; preserve model-space and readiness distinctions; no new inference research required for this UI.
- Canon: pinned release's `AGENTS.md`, matching rows, Principle 10, CARD-12.

## Contract and Boundary Impact

| Boundary | Owner | Current contract | Change | Compatibility | Verification |
| --- | --- | --- | --- | --- | --- |
| Settings GET/POST | SettingsController / settingsApi | Validated boolean; saved/result/failed response | None | Preserve partial payload and capability gate | Focused API and UI tests |
| PHP localized SPA config | Admin / config.ts | AltContextAdmin bootstrap | Add nested `recognitionPolicy: { enabled: boolean, canManage: boolean }` | Optional on older/malformed bootstrap; unknown must remain unknown | Actual producer payload, normalization tests |
| UI cache | SettingsPage / Workbench | `queryKeys.settings.all` | Shared invalidation/readback | No second policy store | Workbench -> Settings round-trip |

## Proposed Solution

Add safe nested bootstrap metadata using `RecognitionPolicy::enabled()` and `current_user_can('manage_options')`; never expose settings secrets or broaden REST permissions. Implement a small Workbench component using existing API/query keys. Send only `{recognition_enabled: desiredBoolean}`. Require an acknowledged field and fresh readback before claiming saved; after an acknowledged write with failed readback, retry the read instead of replaying the write. Reconcile the existing Settings cache and handle capability denial without a false state claim.

## Files and Surfaces to Change

| Lane | Owned files | Behavior and proof |
| --- | --- | --- |
| UI | `js/admin/api/config.ts`, `js/admin/pages/WorkbenchPage.tsx`, new `js/admin/pages/workbench/RecognitionPolicyControl.tsx`, its focused tests and config tests | Normalize bootstrap, render/mutate/read back control; share settings cache |
| PHP | `src/admin/class-admin.php`, focused tests under `tests/Unit/` | Safe nested producer metadata, real option/capability behavior; protect existing Settings partial-write contract |
| MAP | `docs/ux-maps/workbench-operator-loop.uxmap.json` and its render, focused UX-map fixtures if needed | Reuse existing map; render ASCII; critique states/flows against canon |

Paths in the table are plugin-relative. Authors may verify and correct demonstrably wrong anchors, recording the correction; scope expansion requires an orchestrator decision.

## Related Files

`SettingsPage.tsx`, `settingsApi.ts`, `RecognitionPolicy`, `SettingsController`, and existing Workbench/query-key and admin localization tests are read-only context outside each lane's ownership.

## Verification Strategy

Remote focused Vitest covers off->on, on->off, deferred response, HTTP failure, HTTP-200 field failure, failed/mismatched readback, retry, persistence/remount, cache consistency, capability loss, keyboard use and no scan/GPU side effects. Mirror actual producer shapes. Remote PHP tests cover missing-option default, readback, true/false capability and safe bootstrap shape. Run existing policy/settings focused suites. The joined remote candidate runs scoped tests, TypeScript checks and production build. Existing UX-map validation/critique must run; preserve unrelated inherited findings with explicit scope. A LocalWP exact-artifact acceptance is separate from automated source acceptance and must not be claimed without actual evidence.

## Slice Delivery

### Slice 1: Bootstrap producer and boundary proof

PHP lane adds the nested policy snapshot and capability hint with focused real-shape tests. Existing Settings authorization stays enforced. No JavaScript ownership.

### Slice 2: Workbench policy control

UI lane implements the agreed nested contract concurrently with PHP. Add meaningful failing behavior coverage before production edits; run focused tests after implementation. Use existing button/notice styles and a secondary action to preserve the scan primary.

### Slice 3: Existing map and state audit

MAP lane extends the current map with policy loading/unknown, off/on, saving, readback failure, denied and retry states; enable/disable are secondary actions. Render ASCII and critique before final author integration. Do not regenerate unrelated maps or introduce a confirm tab.

## Parallelization

`PREP -> {UI, PHP, MAP}`; `{UI, PHP, MAP} -> JOIN -> GATE -> LAND`. Cleanup inventory is an independent read-only component; verified owner-scoped cleanup may proceed without blocking authors. Author file conflicts are empty; the join is the only integration writer. GATE runs remotely on gpt-6.1-sol xhigh. First author dispatch is gpt-6.1-sol low. Defects fan out by disjoint ownership for second-dispatch Claude Opus 5.5 xhigh adjudication, carrying previous attempts, fresh semantic reinjection, canon and codemap. A third dispatch stops loudly for a canon-sourced proposal before further work, following the operator's alternating model policy.

Initial VM observation: 4 CPUs, 13.4 GiB MemAvailable, 35 GiB disk; CPU PSI 7.55%, memory PSI zero, four active sibling bake-off Claude processes. Bound new concurrent author/test demand to 3 CPU and 7 GiB aggregate, with single-worker tests and admission remeasurement. Do not infer saturation from model count alone.

## Consolidated Checklist

## Context and Ownership

- [x] Loaded continuation, semantic prior art, code graph and verified canon.
- [x] Defined boundary contract and disjoint ownership.

### Checklist for Slice 1: Bootstrap producer

- [ ] Add safe nested metadata and focused boundary tests.
- [ ] Run scoped remote PHP verification.

### Checklist for Slice 2: Workbench control

- [ ] Implement accessible confirmed policy state, mutations and recovery.
- [ ] Verify real-shape responses, Settings consistency and side-effect isolation remotely.

### Checklist for Slice 3: Map and state audit

- [ ] Update existing map, render ASCII and run critique.

## Review Readiness

- [ ] Assemble disjoint commits and record exact source/test identities.
- [ ] Obtain independent remote xhigh merge gate with fresh prior art and canon.
- [ ] Record actual verification limits and durable handoff.

## Success Criteria

- [ ] Workbench exposes and persists the existing administrator-controlled site policy with honest pending/error feedback.
- [ ] Reviewed source is merged without modifying sibling bake-off work; main is clean.
