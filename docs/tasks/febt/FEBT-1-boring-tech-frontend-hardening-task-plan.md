# Task Plan — FEBT-1 Boring-tech frontend hardening (AppError union, reducer job machine, structured logger)

> **Metadata**
>
> - **Date**: 2026-09-02 07:00 EST
> - **Author**: claude-fable-5-1
> - **Project**: apps/prototype-wp-alt-context (admin SPA, `js/admin/`)
> - **Task ID**: `FEBT-1`
> - **Target Branch**: `feature/febt-1`
> - **Review Coverage Target**: 1 local Claude + ≥3 remote grok-4.6 reviewers per wave (adversarial `/wb-review-slice`)

---

## FEBT-1. Boring-tech hardening instead of Effect-TS

## Objective

Land the three in-place moves the Effect-TS evaluation (memory `effect-ts-evaluation-20260902`) recommended instead of adopting Effect: (1) one closed, `_tag`-discriminated `AppError` union with a single classifier at the fetch boundary replacing ~45 scattered `instanceof` checks; (2) the job state machine as a typed `useReducer` machine keyed on `(state, event)` with named events; (3) the 11 `console.*` sites routed through a small structured logger carrying `jobId`/`requestId`. Optionally run a bounded Effect-core trial on the http/retry boundary with stop thresholds named here before dispatch.

## Intake

- **Prior art (handoff embeddings, mode verified)**: UXP-2 decision 2377 (typed `HTTPError`/`ResponseParseError` at the `fetchApi` seam; message format preserved for six downstream `(404)`/`(409)`/`Failed to fetch` sniff sites); UXP-NET-2 findings 4663/4667 (429/503 expectations; `throwIfAborted` before `AuthExpiredError`); UXP-NET-1 decision 2439 (shared retry policy); finding 1277 (12 hook/util files implement one job state machine with one non-test consumer); REFA-4 findings 429/440 (`JobProgressStreamService` tests); WBUX-3 2261/2292. Planning decision 6810.
- **Not-Doing**: adopting Effect (rejected: v4 RC, atom-react beta, PERF-06 unmeasured, lane-unfamiliar notation); touching PHP or the description service; DOM/focus `instanceof` checks on `Node`/`HTMLElement`/`MessageEvent` (not error classification); changing user-visible copy; new UI surfaces.

## Problem Statement

Error handling is classified at ~45 call sites by `instanceof` and message sniffing (`error.message.includes('(404)')`), so each caller re-derives the taxonomy (sr-007, REF-19, CARD-24). The job pipeline state lives in 12 `useState`/`useRef` cells across 8 hooks with ~112 `useEffect`s repo-wide, so transitions are implicit and untestable without React (GRPH-26/27). Diagnostics are bare `console.*` calls with no correlation id (OBS-02, OBS-03).

## Constraints

- **Behaviour parity**: `fetchApi` error message text stays byte-identical until the last sniff site is migrated (parallel change: expand → migrate → contract; REF-20).
- **File-disjoint lanes**: no two concurrent lanes edit the same file (GRPH-09 conflict-graph colouring).
- **Lane bound**: each grok-remote lane commits by turn 8 inside the 900 s cap; scoped `TEST_CMD` only.
- **All tests run on the VM lanes**, never locally (operator mandate 2026-08-19).
- **No secrets in briefs or logs.**

## Canon applied

sr-007, REF-15/19/20/21/28, CARD-07/16/17/24, OBS-02/03, RES-02/06, PERF-06, TEST-15, ARCH-08/17, AGT-02/13, GRPH-01/02/03/05/06/09/26/27/28/31/32/33/34 (heuristics canon, latest; never pinned).

## DAG (GRPH-01 topological order; edges only where data moves, GRPH-32)

| Lane | Wave | Owns (exclusive) | Depends on | Contract exported (GRPH-33) |
| --- | --- | --- | --- | --- |
| L1 `febt-1-apperror` | W1 | new `js/admin/utils/appError.ts` (+test); `utils/http.ts`, `utils/retryPolicy.ts`, `utils/userFacingError.ts`, `api/config.ts` (+their tests) | — | `AppError` union, `classifyError(unknown): AppError` (idempotent), `isAppError`, `toUserMessage(err, fallback)`; existing classes keep throwing (expand phase) |
| L2 `febt-1-logger` | W1 | new `js/admin/utils/logger.ts` (+test); `main.tsx`, `hooks/useJobPersistence.ts` | — | `createLogger(scope)` → `{debug,info,warn,error}(msg, fields?: {jobId?, requestId?, ...})`, console sink, test sink |
| L6a `febt-1-jobmachine` | W1 | new `js/admin/hooks/jobMachine.ts` (+test) | — | `JobMachineState`, `JobEvent` union, `jobReducer(state, event)` with exhaustive `(state,event)` table (GRPH-27), `initialJobState` |
| L3 `febt-1-hooks-sweep` | W2 | `hooks/useJobStateMachine.ts`, `useJobStateMachineMutations.ts`, `useJobStateMachineEffects.ts`, `clusterAutoRetry.ts`, `recognitionJobHistoryUtils.ts` (+tests) | L1, L2 | replaces `isNotFoundError` message sniff with `isHttpStatus(err, 404)`; `clusterAutoRetry` delegates to `isCooldown` (E-07); mutations `console.error` → logger, one wide event per settle (O-02 submit/cancel half) |
| L4 `febt-1-clusters-sweep` | W2 | all `pages/workbench/identity-clusters/**` error sites (+tests): `useLiveReviewTarget.ts` (E-02 404 + 2×`AuthExpiredError`), `useClusterSuggestionsLoader.ts` (`console.warn`:211, `DOMException`:205), `ClusterLabelingPanel.tsx` (`DOMException`:105) | L1, L2 | — |
| L5 `febt-1-api-retention-sweep` | W2 | `api/wpErrorMessage.ts`, `api/describeApi.ts`, `api/recognition/scanApiError.ts`, `api/config.ts` (`console.warn`:77), `pages/retention/useRetentionPageState.ts`, `utils/recognitionCooldown.ts` (E-02 residual `instanceof`), `utils/logger.ts` (fold `projectBoundaryError` into `classifyError`+`projectAppError`, **record shape unchanged**), `components/ui/UserFacingErrorNotice.tsx` + `utils/sessionExpiredCopy.ts` (E-03 single copy owner) | L1, L2 | logger emits an identical record with no `instanceof` outside `utils/appError.ts` |
| L6b `febt-1-stream-reducer` | W2 | `hooks/useJobProgressStream.ts` (+tests; its 5 `console.*` sites), `hooks/useDescribeRunProgress.ts` (sole external importer of the deleted `JOB_PROGRESS_STALL_THRESHOLD_MS`), `docs/ux-maps/febt-1-job-error-states.{md,uxmap.json}` | L2, L6a | stream hook drives `jobReducer`; one stall threshold (M-08); one wide event on terminal stream events (O-02 stream half) |
| L6c `febt-1-machine-wire` | W3 | `hooks/useJobStateMachine.ts`, `useJobStateMachineDerivedState.ts`, `useJobStateMachineEffects.ts`, `pages/workbench/JobPipelineContext.tsx` | L3, L6b | pipeline consumers read machine state |
| T `trial/febt-1-effect-http` | after L1 | throwaway branch; `utils/http.ts`, `utils/retryPolicy.ts` only | L1 | measurement only, never merged by default |

Critical path: L1 → L3 → L6c (GRPH-31). Width: 3 (W1), 4 (W2), 1 (W3). L3 and L6c both touch `useJobStateMachine.ts`, so they are sequenced, not parallel (GRPH-09). Each wave is gated by one adversarial `/wb-review-slice` round before merge into `feature/febt-1`; the combined tree is materialised and built before merge (parallel lanes fixing one symptom differently is the known failure).

Ownership corrections applied before W2 dispatch (un-owned-caller sweep, per the wave-9/10 lesson): `useLiveReviewTarget.ts` lives under `identity-clusters/`, so E-02's 404/`AuthExpiredError` half is L4, not L3. `utils/recognitionCooldown.ts` and `utils/logger.ts` both still carry `instanceof <ErrorClass>` and belonged to no lane; both go to L5. `components/ui/UserFacingErrorNotice.tsx` (E-03) is under `components/ui/`, not `components/`. `hooks/useDescribeRunProgress.ts` is the sole external importer of `JOB_PROGRESS_STALL_THRESHOLD_MS`, so M-08's deletion breaks it unless L6b owns it. `utils/http.ts` `instanceof DOMException` is the classifier's own abort boundary and stays exempt alongside `utils/appError.ts`.

The tree-wide grep gate (zero `instanceof <ErrorClass>` outside `utils/appError.ts`/`utils/http.ts`, zero `console.*` outside `utils/logger.ts`) is a **Gate W2 post-merge check**, not a per-lane `TEST_CMD` — no single lane can make the whole tree pass. Each lane's `TEST_CMD` greps only the files it owns.

## Effect-core trial (CARD-17) — stop thresholds, named before dispatch

Trial runs only after L1 merges, on the throwaway branch, on the VM. It rewrites `fetchApi` + retry policy with `effect` core only. Stop (record decision `reject`, delete branch) if **any** holds:

1. Gzipped size of the admin entry chunk grows by more than 15 KB or more than 10 % over the L1 baseline (measured by `npm run build` on the VM, both trees, same node).
2. The trial lane does not reach green `npm run typecheck && npx vitest run js/admin/utils` on its first attempt within one 900 s grok pass. A second attempt is for recording the failure mode, not rescue.
3. Any existing assertion in `utils/__tests__/{http,retryPolicy,userFacingError}.test.ts` has to change meaning (behaviour parity broken).
4. `npm ci` pulls more than one new transitive package or reports a peer conflict.

Passing all four is necessary, not sufficient: adoption remains an operator decision recorded as an ADR.

## Slices

- [x] Slice 0 — plan + UX map (`docs/tasks/febt/…`, `apps/prototype-wp-alt-context/docs/ux-maps/febt-1-job-error-states.uxmap.json`), planning decision 6810 recorded.
- [x] Slice 1 (W1) — L1 AppError foundation green on lane branch; RED test first (`utils/__tests__/appError.test.ts`).
- [x] Slice 2 (W1) — L2 logger foundation green (`utils/__tests__/logger.test.ts`).
- [x] Slice 3 (W1) — L6a pure job machine green (`hooks/__tests__/jobMachine.test.ts`), exhaustiveness proven by a `never` check in the table.
- [x] Gate W1 — `/wb-review-slice`, findings in MCP, combined tree built, merge L1/L2/L6a into `feature/febt-1`.
- [ ] Slices 4–7 (W2) — L3, L4, L5, L6b; zero `instanceof <ErrorClass>` outside `utils/appError.ts` and zero `console.*` outside `utils/logger.ts` in `js/admin/` (grep gate in each lane's `TEST_CMD`).
- [ ] Gate W2.
- [ ] Slice 8 (W3) — L6c wire consumers onto the machine; delete the migrated `useState` cells (contract phase).
- [ ] Gate W3; `handoff_close_check(enforce=True)`; merge to `main`.
- [ ] Optional trial T; decision recorded either way.

## Verification

Per lane: `cd apps/prototype-wp-alt-context && npm ci --silent && npx vitest run <owned test files> && npm run typecheck && npx eslint <changed ts/tsx>`. Branch-complete: full `npm run check` on the VM gate. TEST-15: each new test must be shown red before green (lane brief requires the red run output in the commit body).

## Open Threads

- Whether `fetchApi` should throw `AppError` values directly (contract phase) or keep the class hierarchy and expose only `classifyError` — decided at W3 after the sweeps show how many callers still need `instanceof`.
