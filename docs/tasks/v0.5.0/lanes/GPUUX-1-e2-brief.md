# Lane E2 — narrow `gpu_state` at the SPA boundary

Closes **GPUUX-1-E1D-BR-01** (high). Branch `feature/gpuux-1-e2` off `35912342f`.

## The defect (PROVEN by an executed probe — do not re-litigate whether it is real)

At merged HEAD `35912342f` the SPA trusts the `gpu_state` string the API returns, without ever narrowing it:

- `js/admin/api/describeApi.ts` **declares** `gpu_state: GpuState | null` on `DescribeRunResponse`. That is a compile-time claim about untrusted boundary data. Nothing checks it at runtime.
- `js/admin/hooks/useDescribeRunProgress.ts` does `gpuState: run?.gpu_state ?? null` — a straight pass-through.
- `js/admin/pages/workbench/gpuStatePresentation.ts` then does a bare index: `GPU_STATE_PRESENTATION[state ?? GPU_STATE.UNKNOWN]`.
- `js/admin/pages/workbench/MediaSelection.tsx` `GpuTierStatus` dereferences the result: `const Icon = GPU_STATE_ICON_COMPONENT[presentation.icon]`.

A throwaway vitest probe (written, run, then deleted) passed 3/3:

1. `gpuStatePresentation('bogus')` returns **undefined**
2. `gpuStatePresentation('stopping').icon` **throws TypeError**
3. `gpuStateNotice('bogus', 3)` returns **undefined** — silent, because its switch has no `default`. A second, quieter failure mode.

Reachability is established at the other end of the wire, not assumed. Lane D (merged at `35912342f`) added `testGetDescribeRunStatusPassesUnrecognizedGpuStateThroughUnchanged`, characterizing `src/api/class-describe-controller.php::get_describe_run_status` forwarding an unrecognised value such as `'bogus'` through untouched. The description-service owns the state vocabulary independently of the SPA bundle.

The trigger is therefore an ordinary backend-first deploy adding a 7th state — e.g. `stopping`, which the GPU lifecycle work is actively heading toward — shipping before the SPA bundle. `GpuTierStatus` is rendered **unconditionally** at `MediaSelection.tsx:429`, so the whole workbench media pane goes down, not just the status chip.

## Scope — do exactly this, nothing else

1. **Add a runtime type guard in `describeApi.ts`**, beside `GPU_STATE`:

   ```ts
   export const isGpuState = (value: unknown): value is GpuState =>
     typeof value === 'string' && (Object.values(GPU_STATE) as string[]).includes(value);
   ```

   Derive it from `GPU_STATE` so it cannot drift from the as-const. Do **not** hand-write a second list of the six strings.

2. **Apply it in `useDescribeRunProgress.ts`**, replacing the bare `??`:

   ```ts
   gpuState: isGpuState(run?.gpu_state) ? run.gpu_state : GPU_STATE.UNKNOWN,
   ```

   Unrecognised, malformed, missing and explicitly-null values then all degrade to the calm "not reported" presentation that already exists. That is the correct product behaviour: the chip says it does not know, and the page keeps rendering.

3. **Give `gpuStateNotice` a `default` branch** returning the UNKNOWN copy, so it can never return `undefined`.

4. **Fix the header comment in `gpuStatePresentation.ts`.** It currently claims: "The `satisfies` constraint makes a backend vocabulary addition a compile error until its presentation is deliberately designed." That is false, and it is the reason this defect shipped. `satisfies` constrains the **frontend** as-const only. A backend vocabulary addition is not a frontend compile error at all — it is the runtime crash above. Rewrite it to say what is true: the presentation table is exhaustive over the frontend `GpuState` union, and unknown values from the wire are narrowed to UNKNOWN at the `describeApi` boundary.

## Tests — RED first, and behavioural

Write the failing tests before the fix and show they fail.

- `describeApi.test.ts`: `isGpuState` accepts each of the six values and rejects `'bogus'`, `''`, `null`, `undefined`, `42`, `{}`.
- `useDescribeRunProgress.test.tsx`: a poll response carrying `gpu_state: 'stopping'` yields `gpuState === 'unknown'`; `'ready'` yields `'ready'`; `null` yields `'unknown'`.
- `gpuStatePresentation.test.ts`: `gpuStateNotice` returns a non-empty string for every one of the six values — iterate `Object.values(GPU_STATE)`, do not hand-list them.
- A **render** test that `GpuTierStatus` does not throw when the API reports an unknown state. This is the test that would have caught the bug; the unit tests alone would not have.

## Governing rules — you will be reviewed against these

- **sr-005**: "use assertion helpers (`asserts value is ...`) for internal invariants and unreachable branches ... **Do not use assertion helpers for request/input validation; validate boundary data explicitly.**" This defect is precisely the forbidden half. A type guard at the boundary is the sanctioned form; an `asserts` helper or a non-null assertion is **not**.
- **sr-007**: keep the vocabulary centralized in the `GPU_STATE` as-const. No scattered magic-string comparisons. Derive everything — guard, tests, presentation table — from that one definition.
- **sr-004**: any CSS must use `--acx-*` design tokens; status indicators pair colour with an icon, never colour alone. The existing `.acx-sync-status` modifiers are already token-backed — reuse them, add no literals.
- **rg-003**: primary controls stay reachable from zero state. The submit CTA at `MediaSelection.tsx:439` reads `disabled={!offlineGated && (selectedCount === 0 || isSubmitting || isRunning)}` and contains **no** `gpuState` term. **Keep it that way.** An unknown or degraded GPU must not make the primary action unreachable.
- **rg-015**: boundary adapters must not invent contract metadata. Narrowing an unrecognised value to UNKNOWN *for presentation* is correct; do not write the coerced value back into the response object or anywhere it could be mistaken for what the server actually said.

## Do NOT

- Do not touch `src/api/class-describe-controller.php`. Its pass-through is correct under rg-015 and lane D's tests pin it. The fix belongs in the consumer.
- Do not change the six-value vocabulary or add a 7th state. This lane makes unknown states *survivable*; it does not introduce one.
- Do not reformat or restructure beyond the four changes above.

## Harvest contract (MANDATORY — the orchestrator's automatic harvest is broken)

`run_offload_pass` harvests findings via a path that is never set for `codex-remote` lanes, so it has returned `{status:"skipped", reason:"no_findings_block"}` on six consecutive lanes even when a well-formed block was present. Findings are recovered from disk by hand. Therefore:

1. Write your report to `docs/tasks/v0.5.0/lanes/GPUUX-1-e2-report.md` and **commit it**.
2. End that file with a fenced `json` block containing `{"findings": [...]}`, each entry having `finding_id`, `severity`, `file_path`, `line_start`, `description`, `fix`.
3. Put the same JSON in your final handoff summary.
4. If you find nothing, emit `{"findings": []}` explicitly rather than omitting the block.

## Verification

```
cd apps/prototype-wp-alt-context && npx vitest run \
  js/admin/api/__tests__/describeApi.test.ts \
  js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx \
  js/admin/pages/workbench/__tests__/gpuStatePresentation.test.ts \
  js/admin/__tests__/banned-vocabulary.test.tsx
```

Also run `npm run typecheck` and eslint. If `npx vitest` cannot resolve, invoke `node node_modules/vitest/vitest.mjs run ...` directly — a known-broken `node_modules/.bin/vitest` (a 43-byte regular-file copy rather than a symlink) has bitten this repo before.

Report the actual command output. Do not report a pass you did not execute.
