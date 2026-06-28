# Task Plan

> **Metadata**
>
> - **Date**: 2026-06-10 23:50 EST
> - **Author**: Claude Opus 4.8
> - **Owning Epic**: `docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md`
> - **Epic Short ID**: REFA
> - **Target Branch**: `feature/refa-8`
> - **Review Coverage Target**: 2

---

## REFA-8. Repair characterization-fixture pretty-vs-compact drift

## Objective

Restore the two failing characterization suites — `AnalysisJobsControllerCharacterizationTest` (10) and `ClusterMutationsCharacterizationTest` (11) — to green by regenerating their golden `*.json` fixtures to match the compact JSON the code emits, and prevent recurrence by excluding the fixture tree from the Prettier sweep. This unblocks the repo-wide pre-merge gate for in-flight REFA branches.

## Problem Statement

Both suites assert byte-exact string equality between a golden fixture file and live `wp_json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)` output. That output is single-line **compact** JSON (no `JSON_PRETTY_PRINT` on any path; the test-env `wp_json_encode` stub at `tests/stubs/wp.php:1342` further drops the flag args). The fixtures were originally written compact and correct, then later reformatted to 2-space **pretty** JSON by tree-wide Prettier sweeps:

- analysis-jobs fixtures: pretty-printed in `f88932bf` (`refa(refa-5)` safety-net sweep). REFA-4 (`60dea2de`) originally wrote them compact and correct — the user's "REFA-4" attribution is approximate; the regression entered in REFA-5.
- cluster-mutations fixtures: pretty-printed in `e2af4d4e` (`chore(format)` Prettier sweep adjacent to REFA-3).

The plugin's `format:fix` script (`apps/prototype-wp-alt-context/package.json:26`) runs `prettier --write "**/*.{ts,tsx,js,jsx,json,css,scss,md}"`, which matches `tests/fixtures/**/*.json`. The effective plugin-cwd `.prettierignore` (`apps/prototype-wp-alt-context/.prettierignore`) exists but does not exclude fixtures, so any future sweep re-prettifies them and re-breaks the suites. The failures reproduce identically on `main` (HEAD `211d92547fe0`); they are not caused by any in-flight branch.

## Constraints

- Greenfield: no migrations, no compatibility shims. Fixtures are regenerated, not dual-format-tolerant.
- Characterization intent must be preserved: the suites exist to lock byte-exact REST response shape. Do **not** weaken them into structural/decoded comparison that would stop catching real serialization regressions (key order, escaping, status). This is an explicit non-goal — see Considered Alternatives.
- Fix must hold on `main`, independent of any REFA feature branch.
- PHP test runner: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit` (PHPUnit 10.5, PHP 8.x, config `phpunit.xml.dist`).

## Workflow Principles

- Regenerate fixtures from code output via an env-gated regeneration switch, never hand-edit JSON whitespace.
- Every regeneration path must be symmetric across both suites so the next person has one mechanism, not two.
- Prevention (ignore rule) ships in the same task as the repair, or the repair rots on the next sweep.

## Terminology

- **Golden fixture**: a committed `response.json` / `side-effects.json` whose exact bytes are asserted against live serialization output.
- **Compact JSON**: single-line `json_encode` default output (no `JSON_PRETTY_PRINT`).
- **Regen guard**: an env-gated branch in a characterization test that rewrites fixtures from current output instead of asserting (`UPDATE_*_FIXTURES=1`).

## Current State Analysis

- `AnalysisJobsControllerCharacterizationTest` (`apps/prototype-wp-alt-context/tests/Unit/AnalysisJobsControllerCharacterizationTest.php`): compares at `:415`; already has a regen guard `UPDATE_ANALYSIS_JOBS_FIXTURES=1` covering `response.json`, `side-effects.json`, `payload.json`, `frames.txt` (`:401`, `:427`, `:445`). Fixtures under `tests/fixtures/analysis-jobs/<handler>/` are pretty → 10 failures.
- `ClusterMutationsCharacterizationTest` (`apps/prototype-wp-alt-context/tests/Unit/ClusterMutationsCharacterizationTest.php`): compares at `:248` via `assertGolden()`; serializers at `:263`/`:287`. **No regen guard exists.** Fixtures under `tests/fixtures/cluster-mutations/<handler>/` are pretty → 11 failures.
- No shared JSON helper; controllers call `wp_json_encode` directly. No code change is needed or wanted — code output is correct; fixtures are stale.
- Root `.prettierignore` is absent. The effective ignore file for the plugin scripts is `apps/prototype-wp-alt-context/.prettierignore`, and it currently has no fixture exclusion.

## Target Outcome

Both suites pass on `feature/refa-8` and on a clean `main`. Cluster suite gains a regen guard symmetric to the analysis-jobs one. Re-running `npm run format:fix` (or `--check`) leaves `tests/fixtures/**/*.json` untouched, so the suites stay green after future sweeps. `npm run format` (check mode) reports no drift on the fixture tree because it no longer inspects it.

## Context Loading

- Tests: `apps/prototype-wp-alt-context/tests/Unit/AnalysisJobsControllerCharacterizationTest.php`, `apps/prototype-wp-alt-context/tests/Unit/ClusterMutationsCharacterizationTest.php`
- Fixtures: `apps/prototype-wp-alt-context/tests/fixtures/{analysis-jobs,cluster-mutations}/**`
- Tooling: `apps/prototype-wp-alt-context/package.json` (format scripts), `apps/prototype-wp-alt-context/.prettierignore`
- Rules: `docs/workbay/rules/testing-php.md`
- Handoff/MCP: REFA-8 task ref; REFA epic for ownership context
- No `ctx7` needed.

## Contract and Boundary Impact

No cross-service or contract boundary is touched. The REST response **shapes** asserted by these characterization tests are unchanged — only the on-disk whitespace of the golden files changes to re-match existing output. Omitting the boundary table is justified: this is a test-fixture + tooling-config fix with no runtime surface change.

## Proposed Solution

1. Add a symmetric env-gated regen guard (`UPDATE_CLUSTER_MUTATIONS_FIXTURES=1`) to `ClusterMutationsCharacterizationTest::assertGolden()` mirroring the analysis-jobs pattern.
2. Regenerate both fixture sets from live output via the regen guards → fixtures become compact and byte-exact again.
3. Exclude the fixture JSON tree from Prettier via the plugin-cwd `.prettierignore` so sweeps can never re-prettify them.
4. Prove green with the suites, then prove durable by running `format:fix` and confirming zero fixture diffs + still-green suites.

### Considered Alternatives (rejected)

- **Normalize-and-compare** (decode both sides, compare structures / re-encode canonically): more whitespace-robust but discards the byte-exact characterization guarantee (key order, escaping, exact status serialization). Rejected — weakens regression coverage; the recurrence risk is better solved by the ignore rule.
- **Remove fixtures from the glob in `format:fix`** instead of `.prettierignore`: the glob is also used by `format` (check) and is broad; `.prettierignore` is the single source of truth Prettier honors for both `--write` and `--check`. Preferred.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| tests | `apps/prototype-wp-alt-context/tests/Unit/ClusterMutationsCharacterizationTest.php` | Add `UPDATE_CLUSTER_MUTATIONS_FIXTURES=1` regen guard in `assertGolden()` for `response.json` + `side-effects.json`, mirroring analysis-jobs |
| tests (fixtures) | `apps/prototype-wp-alt-context/tests/fixtures/cluster-mutations/**/response.json`, `side-effects.json` | Regenerate compact |
| tests (fixtures) | `apps/prototype-wp-alt-context/tests/fixtures/analysis-jobs/**/response.json`, `side-effects.json` (+ `payload.json`, `frames.txt` if drifted) | Regenerate compact |
| tooling | `apps/prototype-wp-alt-context/.prettierignore` (plugin-cwd — the file Prettier honors when `format:fix` runs from the plugin dir) | Exclude `tests/fixtures/**/*.json` — covers `response.json`, `side-effects.json`, `payload.json`. `frames.txt` is `.txt`, outside the Prettier glob, so not at risk and out of scope |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/tests/stubs/wp.php:1342` | `wp_json_encode` stub drops flag args; explains why output is compact regardless of flags — context only, no change |
| `apps/prototype-wp-alt-context/package.json:26-27` | `format:fix`/`format` globs that caused the sweep |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && vendor/bin/phpunit --filter AnalysisJobsControllerCharacterizationTest`
  - `cd apps/prototype-wp-alt-context && vendor/bin/phpunit --filter ClusterMutationsCharacterizationTest`
  - Full suite green: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit`
- Contract/fixture verification:
  - After regen, confirm every affected JSON fixture is exactly compact (no newline bytes): `python3 -c "from pathlib import Path; roots=[Path('apps/prototype-wp-alt-context/tests/fixtures/analysis-jobs'), Path('apps/prototype-wp-alt-context/tests/fixtures/cluster-mutations')]; bad=[str(p) for r in roots for p in r.rglob('*.json') if '\n' in p.read_text(encoding='utf-8')]; assert not bad, bad"`.
  - **Semantic-equivalence guard (regen safety)**: before trusting the regen, preserve the pre-regen (pretty) fixtures (e.g. `git stash` / copy), then for every regenerated JSON fixture assert `diff <(jq -S . OLD) <(jq -S . NEW)` is empty. This proves the regen changed only whitespace and did not silently absorb a real value regression into the golden output. Any non-empty canonical diff blocks the slice pending investigation.
- Durability check (the actual prevention proof):
  - `cd apps/prototype-wp-alt-context && npm run format:fix && git diff --stat -- tests/fixtures` → **zero** fixture changes, then re-run both suites → still green.
- Diff review:
  - `git diff --stat` shows only fixture JSON, the cluster test guard, and `.prettierignore` changed — no production code.

## Slice Delivery

### Slice 1: Cluster regen guard + regenerate both fixture sets to green

**Goal**: Both characterization suites pass via regenerated compact fixtures, with a symmetric regen mechanism.

Changes:

- Add `UPDATE_CLUSTER_MUTATIONS_FIXTURES=1` guard to `ClusterMutationsCharacterizationTest::assertGolden()` (write `response.json` + `side-effects.json` from live output when set, else assert).
- Regenerate: `UPDATE_CLUSTER_MUTATIONS_FIXTURES=1 vendor/bin/phpunit --filter ClusterMutationsCharacterizationTest` and `UPDATE_ANALYSIS_JOBS_FIXTURES=1 vendor/bin/phpunit --filter AnalysisJobsControllerCharacterizationTest`.

Proof:

- Both `--filter` runs green on a normal (no-env) re-run.
- Pre-regen vs regenerated fixtures are `jq -S` canonically identical (only whitespace changed) — no value regression absorbed.
- `git diff` shows only fixture whitespace collapse + the new guard; no production code.

### Slice 2: Prevent recurrence via Prettier ignore + durability proof

**Goal**: Future `format:fix` sweeps cannot re-prettify fixtures; suites stay green.

Changes:

- Add `tests/fixtures/**/*.json` exclusion to `apps/prototype-wp-alt-context/.prettierignore` (the cwd Prettier honors for the plugin `format:fix` sweep). Covers response/side-effects/payload JSON; `frames.txt` is not Prettier-matched.

Proof:

- `npm run format:fix` from the plugin dir leaves `tests/fixtures` untouched (`git diff --stat -- tests/fixtures` empty).
- Both suites still green after the sweep.
- Full plugin suite green: `vendor/bin/phpunit`.

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the two test files, fixture trees, `package.json` format scripts, and plugin-cwd `.prettierignore` before editing.
- [ ] Confirmed no `ctx7` / external dependency context needed.
- [ ] Confirmed no contract boundary is touched (test-fixture + tooling only).

### Checklist for Slice 1: Cluster regen guard + regenerate fixtures

- [ ] Added symmetric `UPDATE_CLUSTER_MUTATIONS_FIXTURES=1` regen guard to `assertGolden()`.
- [ ] Regenerated cluster + analysis-jobs fixtures to compact via env-gated runs.
- [ ] Both `--filter` suites green on a clean (no-env) run; diff shows no production-code change.

### Checklist for Slice 2: Prettier ignore + durability

- [ ] Added `tests/fixtures/**/*.json` exclusion to `apps/prototype-wp-alt-context/.prettierignore`.
- [x] `npm run format:fix` leaves fixtures untouched (empty diff).
- [ ] Full plugin `vendor/bin/phpunit` green after the sweep.

## Review Readiness

- [ ] Two review passes recorded (Review Coverage Target = 2).
- [ ] Fresh `test_result` evidence tied to HEAD SHA (full plugin suite green).
- [ ] Zero open findings; slice-complete decisions recorded.
- [ ] Confirmed the fix holds on a clean `main` rebase (failures were pre-existing on `main`).

## Success Criteria

- `AnalysisJobsControllerCharacterizationTest` and `ClusterMutationsCharacterizationTest` pass; full plugin suite green.
- Re-running Prettier does not modify any fixture; suites remain green afterward.
- No production source changed — only fixtures, the cluster test regen guard, and `.prettierignore`.
- Repo-wide pre-merge gate is unblocked for in-flight REFA branches.
