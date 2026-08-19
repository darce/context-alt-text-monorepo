# UXW2-4-R7D — dead bulk machinery + skipped a11y walk

## Result

R1-27: leftover selection hook + bulk mock fields deleted after a zero-caller search. `useRecognitionClusters` kept (quarantined) because the UXP-2 cooldown-gate test is a live caller outside this lane.

R1-24: chose **(A)**. Seed producer plants `window.acxE2eSeed.unlabeledClusterId`. Spec executed. Harness cannot start here (no Playwright Chromium; no LocalWP on `:10010`). Drawer walk still skip-gated without a live unlabeled group. **Not claimed closed.**

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Closure

| ID | Commit subject | Test | RED | GREEN |
| --- | --- | --- | --- | --- |
| UXW2-4-R1-27 | `fix(roster): UXW2-4-R1-27 drop dead cluster selection and leftover bulk mocks` | `banned-vocabulary` `js/admin production source has no cluster-jargon toasts or bulk merge/dismiss` | mutant: `AssertionError: expected '…' not to match /for cluster %s/` and `page leaked "cluster"` (`merge failed for cluster %s.`) | same file 15/15 in post-deletion suite |
| UXW2-4-R1-24 | `fix(tests): UXW2-4-R1-24 plant unlabeled cluster seed for roster walk` | `roster-keyboard-walk` (Playwright `--project=a11y`) | `browserType.launch: Executable doesn't exist at …/chromium-1223/chrome-linux/chrome` | not GREEN — spec did not run |

## Gate

From `apps/prototype-wp-alt-context`:

**Item 1 vitest before deletion**

```
 Test Files  208 passed (208)
      Tests  2343 passed (2343)
```

**Item 1 vitest after deletion (final)**

```
 Test Files  207 passed (207)
      Tests  2338 passed (2338)
```

Delta: **−1 file, −5 tests**. The five tests were `useClusterSelection.test.ts` (toggle / range / clear / selectAll / retainVisible) certifying a hook with zero production importers. Leftover `bulkMergeMutation` mock fields on RosterPage tests were not their own cases — stripping them did not change the count.

`npm run typecheck`: clean (`tsc --noEmit --project tsconfig.type-check.json`).

PHP untouched; `composer test` not run (see Undone).

## Item 1 — UXW2-4-R1-27

Prior rounds already deleted `bulkMergeMutation` / `bulkDismissMutation` and the cluster-jargon toasts from `useClusterActions`. Remaining dead surface on this HEAD: `useClusterSelection` (no production importer) and RosterPage tests still mocking the hook + bulk fields.

### Zero-caller search (whole `js/`, including tests)

**Before deletion** (`grep -nR` under `apps/prototype-wp-alt-context/js`):

`useClusterSelection` — 24 hits, all tests or the hook itself:

- `hooks/useClusterSelection.ts` (definition)
- `hooks/__tests__/useClusterSelection.test.ts` (5 unit tests)
- `pages/__tests__/RosterPage.container.test.tsx` / `.reviewCta.test.tsx` / `.workspace.test.tsx`
- `pages/roster/__tests__/RosterZeroStateReachability.test.tsx`

  (mocks only — `RosterPage.tsx` does not import the hook)

`bulkMergeMutation|bulkDismissMutation` — 9 hits, all test mocks + the vocab sweep assertion. **Zero production hits.**

`useRecognitionClusters` — 5 hits:

- `hooks/useRecognitionHooks.ts` (export)
- `hooks/__tests__/recognitionCooldownGate.test.tsx` (mounts it)
- `utils/recognitionCooldown.ts` (comment naming the six-poller set)

**After deletion:**

```
=== useClusterSelection ALL ===
ZERO HITS
=== bulkMerge production (exclude tests) ===
ZERO HITS
=== Merge failed for cluster / Merge timed out for cluster ===
ZERO HITS
```

`useRecognitionClusters` still exported (quarantine).

### Route taken

- **Deleted** `useClusterSelection` + unit tests. Zero production callers.
- **Stripped** leftover `bulkMergeMutation` / `bulkDismissMutation` / `bulkMergeProgress` mock fields and `useClusterSelection` mocks from RosterPage tests.
- **Did not delete** `useRecognitionClusters`. Live caller: `recognitionCooldownGate.test.tsx` mounts it as one of the UXP-2 six gated pollers. That file and `recognitionCooldown.ts` are outside Ownership. Deleting the export here would shrink the gated set without a replacement. Quarantine comment names follow-up **UXW2-5** (drop from the poller set once a cooldown-gate lane owns that contract). Not a bulk surface to re-attach.

### TEST-15 mutant (restored after)

Re-introduced `__('Merge failed for cluster %s.', 'alt-context')` into the live `RosterPage` subtitle. Sweep went RED and named the string:

```
FAIL  banned-vocabulary.test.tsx > roster surfaces render without cluster/identity jargon
AssertionError: page leaked "cluster"
Received: "…unnamed face groups are reviewed in the workbench.merge failed for cluster %s.…"

FAIL  banned-vocabulary.test.tsx > js/admin production source has no cluster-jargon toasts or bulk merge/dismiss
AssertionError: expected '…' not to match /for cluster %s/
 ❯ banned-vocabulary.test.tsx:804:24
    expect(joined).not.toMatch(/for cluster %s/);
```

Sweep covers the roster surface (walks all `js/admin` production `ts/tsx`). Mutant restored. String absent after restore.

## Item 2 — UXW2-4-R1-24

Chose **(A)** (prefer make-it-run). Env-var gate and `listbox`/`title` locators were already gone on this HEAD. Remaining hole: no producer for `acxE2eSeed.unlabeledClusterId`.

- `plantUnlabeledClusterId` / `discoverUnlabeledClusterId` in `seeded-state.ts`: plant the window seed from an existing seed or the first `AltContextAdmin` `/top-unlabeled` row.
- Spec calls that helper (no `E2E_ROSTER_CLUSTER_ID`).
- Locators already match boarded-up drawer (`Move to` count 0; honest copy). CTA follow-through case already present.

### e2e invocation (actual)

```
cd apps/prototype-wp-alt-context && npx playwright test tests/e2e/a11y/roster-keyboard-walk.spec.ts --project=a11y
```

### e2e output (actual)

```
✘  [auth-setup] › tests/e2e/auth-setup/auth.setup.ts:13:5 › bootstrap WordPress admin auth state
Error: browserType.launch: Executable doesn't exist at /home/ubuntu/.cache/ms-playwright/chromium-1223/chrome-linux/chrome
╔════════════════════════════════════════════════════════════╗
║ Looks like Playwright was just installed or updated.       ║
║ Please run the following command to download new browsers: ║
║     npx playwright install                                 ║
╚════════════════════════════════════════════════════════════╝
  1 failed
    [auth-setup] › tests/e2e/auth-setup/auth.setup.ts:13:5 › bootstrap WordPress admin auth state
  5 did not run
```

Also: `curl http://localhost:10010/` → `Failed to connect … Couldn't connect to server`. No LocalWP in this environment.

Did not claim (A) closed. Did not take (B): the rest of the spec (Add Person keyboard path, empty live region, CTA href, CTA follow-through) is worth keeping once a LocalWP + Chromium harness exists.

## file:line (re-derived with `sed -n` after the two code commits)

| Claim | `sed -n` |
| --- | --- |
| Actions return is reassign/rescan/commit only | `useClusterActions.ts:99-101` |
| RosterPage no selection / no bulk callbacks | `RosterPage.tsx:114-116` `useClusterActions({ onReassignSettled, onCommitSettled })` |
| `useRecognitionClusters` quarantined | `useRecognitionHooks.ts:117-127` follow-up UXW2-5 |
| Seed producer | `seeded-state.ts:44` `plantUnlabeledClusterId`; `:62` `discoverUnlabeledClusterId` plants at `:97` |
| Walk uses producer | `roster-keyboard-walk.spec.ts:85` |
| Walk still skip-gates if both miss | `roster-keyboard-walk.spec.ts:88-92` |
| CTA follow-through | `roster-keyboard-walk.spec.ts:132-136` |
| Vocab sweep names `/for cluster %s/` | `banned-vocabulary.test.tsx:804` |

No `useClusterSelection` file remains. Confirmed `grep -nR useClusterSelection js/` → ZERO HITS after the code commits.

## Decisions

1. **Quarantine, do not delete, `useRecognitionClusters`.** Cooldown-gate test is a live caller; its files are outside Ownership.
2. **(A) not (B) for the walk.** Producer is in-repo. Harness cannot start here; deleting the spec would drop always-run CTA/keyboard cases that are not the skip defect.
3. **Mutant on `RosterPage` subtitle**, not a dead toast path — the sweep must see a live roster string.

## Undone

- **R1-24 not closed.** Playwright Chromium missing; LocalWP `:10010` down. Drawer walk still `test.skip`s when seed and `/top-unlabeled` both miss. Replacement: run `npx playwright install chromium` against a seeded LocalWP and confirm the member-fix walk + CTA follow-through go green without `E2E_ROSTER_CLUSTER_ID`.
- **`useRecognitionClusters` still exported.** Only the cooldown-gate test mounts it. UXW2-5: drop it from the UXP-2 six-poller set (`recognitionCooldown.ts` + `recognitionCooldownGate.test.tsx`) then delete the export.
- **PHP untouched.** `composer test` not run.
- **Drawer walk a11y still unexecuted:** ≥24px Close, honest Move copy, zero `Move to` buttons, tab-trap. Those assertions exist in the spec and did not run.
- workbay-handoff MCP and `workbay_handoff_mcp` Python API were unavailable in this lane worktree (`ModuleNotFoundError`). No handoff event recorded here.
