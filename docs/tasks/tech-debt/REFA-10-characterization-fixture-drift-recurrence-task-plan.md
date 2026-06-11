# Task Plan

> **Metadata**
>
> - **Date**: 2026-06-11 EST
> - **Author**: Claude Opus 4.8
> - **Owning Epic**: `docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md`
> - **Epic Short ID**: REFA
> - **Target Branch**: `feature/refa-10`
> - **Review Coverage Target**: 2

---

## REFA-10. Close characterization-fixture drift recurrence (clusters-read symmetry + merge-result gate)

## Objective

Stop characterization golden-fixture drift from recurring. REFA-8 repaired two of the three characterization suites and prevented the *whitespace* (Prettier) drift axis, but left the **clusters-read** suite without a regen guard and did not address the *slash-escaping* axis or the **merge** recurrence vector. This task brings `ClustersControllerCharacterizationTest` to mechanism-parity with its siblings and adds a gate that runs the characterization suites **on the merge result** so a merge that re-breaks any golden fixture fails instead of silently landing on `main`.

## Problem Statement

All three characterization suites assert byte-exact string equality between a committed golden fixture and live `wp_json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)` output. Two recurrences have now been observed in the clusters-read fixtures, both `\/` → `/` (slash-escaping), most recently fixed out-of-band in `c057949e` directly on `main`. Three structural gaps explain why drift keeps coming back:

1. **Coverage asymmetry.** `AnalysisJobsControllerCharacterizationTest` (`UPDATE_ANALYSIS_JOBS_FIXTURES=1`) and `ClusterMutationsCharacterizationTest` (`UPDATE_CLUSTER_MUTATIONS_FIXTURES=1`) each have an env-gated regen guard. `ClustersControllerCharacterizationTest::assertGolden()` (`:98`) has **none** — its 24 golden fixtures must be hand-maintained, which is the entry point for hand-introduced `\/` escaping.
2. **Wrong drift axis.** REFA-8's recurrence prevention was the `.prettierignore` exclusion of `tests/fixtures/**/*.json`. That stops *whitespace* re-prettification only. The clusters-read drift is *escaping* (`\/` vs `/`), which `.prettierignore` does nothing about.
3. **Unguarded recurrence vector: merges.** The most recent re-escaping reached `main` through a `git merge` of a feature branch that forked before an earlier fixture fix — git auto-resolved the file to the stale blob. No PreToolUse guard, `.prettierignore`, or on-branch pre-merge check can catch this: a branch that is green in isolation produces a broken `main` after the merge commit is created. Only a gate that runs the suites **on the merge commit** detects it. CI today (`.github/workflows/architecture-compliance.yml`, `handoff-integrity.yml`) runs no PHPUnit, so nothing exercises the characterization suites at merge time.

## Constraints

- Greenfield: no migrations, no dual-format tolerance. Fixtures are regenerated from code output, never hand-edited.
- Preserve characterization intent: the suites lock byte-exact REST response shape (key order, escaping, status). Do **not** weaken them into decoded/structural comparison — that is an explicit non-goal (see Considered Alternatives).
- The clusters-read regen guard must be symmetric with the analysis-jobs and cluster-mutations guards: one mechanism, three suites.
- `scripts/hooks/**` and `docs/workstate/contracts/**` are bootstrap-managed (overlay) subtrees. The pre-push change must NOT edit the overlay-managed git hook directly; it must use the repo's sanctioned, non-managed hook-extension point (resolve in Slice 2).
- PHP test runner: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit` (PHPUnit 10.5, PHP 8.x, `phpunit.xml.dist`).

## Workflow Principles

- Regenerate fixtures from live output via the env-gated switch; never hand-edit JSON escaping or whitespace.
- The gate proves itself only by going red on a simulated merge-revert and green after — a passing suite on a clean tree is not evidence the gate works.
- Prevention ships with the repair: the regen guard and the merge gate land in this task, not as a follow-on.

## Terminology

- **Golden fixture**: a committed `response.json` / `side-effects.json` whose exact bytes are asserted against live serialization output.
- **Regen guard**: an env-gated branch in a characterization test that rewrites fixtures from current output instead of asserting (`UPDATE_*_FIXTURES=1`).
- **Merge-result gate**: a check that runs the characterization suites against the merge commit (the resolved tree on `main`/the PR head), not against either parent in isolation.

## Current State Analysis

- `c057949e` already repaired the two clusters-read fixtures (`\/` → `/`); `main` is green for `ClustersControllerCharacterizationTest` (24 scenarios, 144 assertions). So the "land the fix" step from the original proposal is already done — this task is prevention-only.
- `ClustersControllerCharacterizationTest::assertGolden()` (`:98`) reads `response.json` (`:101`) and `side-effects.json` (`:102`), serializes via `wp_json_encode(..., JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)` (`:141`, `:152`), and compares with `assertSame` (`:109`, `:117`). No `getenv('UPDATE_*')` branch exists.
- The sibling guards write fixtures inside the assert helpers: `if (getenv('UPDATE_ANALYSIS_JOBS_FIXTURES') === '1') { ...; file_put_contents(...); }` (`AnalysisJobsControllerCharacterizationTest.php:402`).
- `.prettierignore` (plugin-cwd) already excludes `tests/fixtures/**/*.json` (REFA-8 Slice 2); whitespace drift is handled, escaping drift is not.
- Installed git hooks include `pre-push` and `post-merge` (`scripts/hooks/git/`, wired via `make install-git-hooks`) — but they are overlay-managed.

## Target Outcome

`ClustersControllerCharacterizationTest` gains an `UPDATE_CLUSTERS_READ_FIXTURES=1` regen guard symmetric with its two siblings, so all three suites share one regeneration mechanism and fixtures are never hand-edited. A merge-result gate runs the characterization suites on every merge to `main` (CI authority) and before push (local backstop); a merge that re-escapes or otherwise drifts a golden fixture fails the gate instead of landing. The gate is demonstrated to catch a simulated merge-revert.

## Context Loading

- Tests: `apps/prototype-wp-alt-context/tests/Unit/ClustersControllerCharacterizationTest.php`, with `AnalysisJobsControllerCharacterizationTest.php` / `ClusterMutationsCharacterizationTest.php` as the pattern reference.
- Fixtures: `apps/prototype-wp-alt-context/tests/fixtures/clusters-read/**`.
- CI: `.github/workflows/` (no PHPUnit job today).
- Hooks: `scripts/hooks/git/pre-push` (overlay-managed) and the sanctioned non-managed extension point; `make install-git-hooks`.
- Rules: `docs/workstate/rules/testing-php.md`; overlay constraints in `docs/workstate/contracts/overlay-manifest.yaml`.
- No `ctx7` needed.

## Contract and Boundary Impact

No cross-service or contract boundary is touched. REST response shapes are unchanged; this task adds a test-side regen guard and a CI/hook gate. The only runtime-adjacent artifact is a new CI workflow.

## Proposed Solution

1. Add a symmetric env-gated regen guard (`UPDATE_CLUSTERS_READ_FIXTURES=1`) to `ClustersControllerCharacterizationTest::assertGolden()`, writing `response.json` + `side-effects.json` from live output when set, asserting otherwise.
2. Regenerate the clusters-read fixtures through the new guard to prove it round-trips to the already-correct bytes (expected: zero diff).
3. Add a CI job that runs the PHP characterization suites on pull requests targeting `main` and on push to `main`.
4. Add the same characterization check at the sanctioned non-managed `pre-push` extension point as a local backstop that runs against the merge commit before push.
5. Prove the gate catches merge-borne drift by simulating a merge that reverts a fixture to `\/` and confirming the gate goes red, then green on revert.

### Considered Alternatives (rejected)

- **Normalize-and-compare** (decode both sides, compare structures): discards the byte-exact characterization guarantee (escaping, key order, status). Rejected — REFA-8 rejected this for the same reason; it would stop catching real serialization regressions.
- **`.prettierignore`-style static prevention only**: insufficient — it addresses whitespace, not escaping, and cannot see merges.
- **PreToolUse / branch-isolation guard change** (protect `.json` fixtures, detect merges): wrong layer and wrong repo. The guard engine is overlay-managed/upstream, and PreToolUse hooks structurally cannot observe `git merge`. The merge-result gate is the correct layer.
- **Protect `apps/**/tests/fixtures/**` via the overrides channel**: stops only *manual* edits on `main`, not merges. Low value relative to the gate; out of scope (note it as a possible separate hardening if desired).

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| tests | `apps/prototype-wp-alt-context/tests/Unit/ClustersControllerCharacterizationTest.php` | Add `UPDATE_CLUSTERS_READ_FIXTURES=1` regen guard in `assertGolden()` for `response.json` + `side-effects.json`, mirroring analysis-jobs |
| CI | `.github/workflows/php-characterization.yml` (new) | Run `vendor/bin/phpunit` characterization suites on PRs to `main` and push to `main` |
| hooks | sanctioned non-managed `pre-push` extension point (NOT the overlay-managed `scripts/hooks/git/pre-push`) | Run the characterization suites against the merge commit before push; block on failure |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/tests/Unit/AnalysisJobsControllerCharacterizationTest.php:402` | Regen-guard pattern to mirror — context only, no change |
| `apps/prototype-wp-alt-context/.prettierignore` | Already excludes fixtures (REFA-8); whitespace axis covered |
| `docs/workstate/contracts/overlay-manifest.yaml` | Declares `scripts/hooks` managed — drives the pre-push extension-point constraint |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && vendor/bin/phpunit --filter ClustersControllerCharacterizationTest` green on a clean (no-env) run.
  - Full plugin suite green: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit`.
- Regen round-trip safety: `UPDATE_CLUSTERS_READ_FIXTURES=1 vendor/bin/phpunit --filter ClustersControllerCharacterizationTest` then `git diff --stat -- tests/fixtures/clusters-read` is **empty** (the guard reproduces the already-correct bytes), and a no-env re-run is green.
- Gate efficacy (the actual proof): inject `\/` into one clusters-read fixture in the resolved tree, run the pre-push check and the CI job locally (act/equivalent) -> both **red**; revert -> both **green**. Keep any merge-file toy proof scoped to what it actually models; the gate's authority is the final merge-result tree.
- Diff review: `git diff --stat` shows only the test guard, the new workflow, and the pre-push extension — no production source.

## Slice Delivery

### Slice 1: clusters-read regen guard (mechanism parity)

**Goal**: `ClustersControllerCharacterizationTest` gains a regen guard symmetric with its two siblings.

Changes: add `UPDATE_CLUSTERS_READ_FIXTURES=1` to `assertGolden()` (write `response.json` + `side-effects.json` from live output when set, else assert).

Proof: regen run produces an empty `tests/fixtures/clusters-read` diff; no-env run green; `git diff` shows only the test guard.

### Slice 2: merge-result gate (CI + pre-push)

**Goal**: a merge that drifts any golden fixture fails before/at landing on `main`.

Changes: new `.github/workflows/php-characterization.yml` running the characterization suites on PRs to `main` and push to `main`; add the same check at the sanctioned non-managed `pre-push` extension point (resolve the extension mechanism without editing the overlay-managed hook).

Proof: simulated `\/` re-escape in the resolved tree makes both gates red; revert green; merge-file contract tests document the stale-resolved-tree shape without overclaiming unchanged forked-before-fix behavior. Full plugin suite green.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the three characterization tests, the clusters-read fixture tree, the CI workflow dir, and the overlay manifest before editing.
- [ ] Confirmed no `ctx7` / external dependency context needed.
- [ ] Confirmed no contract boundary is touched (test guard + CI/hook only).

### Checklist for Slice 1: clusters-read regen guard

- [ ] Added symmetric `UPDATE_CLUSTERS_READ_FIXTURES=1` guard to `assertGolden()`.
- [ ] Regen run leaves `tests/fixtures/clusters-read` diff empty; no-env run green.
- [ ] `git diff` shows only the test guard; no production-code change.

### Checklist for Slice 2: merge-result gate

- [ ] Added CI workflow running characterization suites on PRs to `main` and push to `main`.
- [ ] Added pre-push characterization check via the sanctioned non-managed extension point (no edit to the overlay-managed hook).
- [ ] Demonstrated both gates go red on injected `\/` drift and green on revert.
- [ ] Demonstrated the gate fails when the resolved tree contains stale `\/` fixture bytes.
- [ ] Full plugin `vendor/bin/phpunit` green.

## Review Readiness

- [ ] Two review passes recorded (Review Coverage Target = 2).
- [ ] Fresh `test_result` evidence tied to HEAD SHA (full plugin suite green).
- [ ] Zero open findings; slice-complete decisions recorded.
- [ ] Confirmed the gate holds on a clean `main` rebase.

## Success Criteria

- All three characterization suites green on a clean `main`; `ClustersControllerCharacterizationTest` has a regen guard symmetric with its siblings.
- The merge-result gate fails a simulated merge that re-escapes a fixture and passes after revert.
- No production source changed — only the test guard, the new CI workflow, and the pre-push extension.
