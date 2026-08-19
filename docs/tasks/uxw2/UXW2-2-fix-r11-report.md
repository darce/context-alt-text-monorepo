# UXW2-2 R11 REPORT

PHP lane. Branch `feature/uxw2-2` (this throwaway mirror commits on `master`). Cite by subject line only.

file:line cites below were re-derived with `sed -n '<N>p' <file>` after the last code commit (`test(api): UXW2-2-R10A-02 repair_pending follows scheduled extras`).

## Result

Closed UXW2-2-R10A-02. `list_top_unlabeled_clusters` now takes the set `schedule_repair_from_mapper` dispatched and ORs that with `$dropped > 0`. Raw repository extras no longer flip `repair_pending` when normalization drops them, they are already in the mapper set, or they miss the remaining room.

## Closure

| Finding | Commit subject | Test | Verbatim mutant RED | GREEN |
|---|---|---|---|---|
| R10A-02 M1 | `fix(api): UXW2-2-R10A-02 derive repair_pending from scheduled set` + `test(api): UXW2-2-R10A-02 repair_pending follows scheduled extras` | `testListTopUnlabeledMalformedDriftIdsDoNotSetRepairPending` | `malformed drift ids must not publish repair_pending` / `Failed asserting that true is false.` | `--filter testListTopUnlabeledMalformedDriftIdsDoNotSetRepairPending` → `OK (1 test, 3 assertions)` (1/1) |
| R10A-02 M2 | same | same | `malformed drift ids must not publish repair_pending` / `Failed asserting that true is false.` | same 1/1 after restore |
| R10A-02 true-positive | same | `testListTopUnlabeledNormalizedDriftIdSetsRepairPending` | n/a (stays green) | `--filter 'testListTopUnlabeledMalformedDriftIdsDoNotSetRepairPending\|testListTopUnlabeledNormalizedDriftIdSetsRepairPending'` → `OK (2 tests, 7 assertions)` (2/2). Class `--filter ClusterReadServiceTest` → `OK (21 tests, 88 assertions)` (21/21) |

Mapper stub returns no repair ids. Drift repo returns `['', '   ', '']`. Sanitize+unique drops every id; nothing is scheduled; `repair_pending` is false.

M1: `$repair_pending = array() !== $mapper_ids || $dropped > 0 || array() !== $extra_ids`. RED quoted above (1/1). Restore.

M2: `return $extra_ids` from `schedule_repair_from_mapper` instead of `$normalized`. RED quoted above (1/1). Restore.

True-positive: same mapper, drift `['cluster-off-page']`. Flag true; scheduled args are that one id.

Pre-fix (tests only, production still raw extras): same malformed case RED with the same assertion text (2/2 selected, 1 failure).

## Gate

From `apps/prototype-wp-alt-context`:

Baseline (before first code commit):

```
OK (1821 tests, 8798 assertions)
```

After the two code commits:

```
$ cd apps/prototype-wp-alt-context && composer test
OK (1823 tests, 8805 assertions)
```

Delta: +2 tests, +7 assertions.

## file:line

```
$ sed -n '196p' apps/prototype-wp-alt-context/src/api/services/class-cluster-read-service.php
			$scheduled_ids = $this->schedule_repair_from_mapper( $tenant_id, $extra_ids, $mapper_ids );

$ sed -n '207p' apps/prototype-wp-alt-context/src/api/services/class-cluster-read-service.php
			$repair_pending = array() !== $scheduled_ids || $dropped > 0;

$ sed -n '443p' apps/prototype-wp-alt-context/src/api/services/class-cluster-read-service.php
	private function schedule_repair_from_mapper( string $tenant_id, array $extra_ids = array(), ?array $mapper_ids = null ): array {

$ sed -n '461p' apps/prototype-wp-alt-context/src/api/services/class-cluster-read-service.php
		return $normalized;

$ sed -n '1029p' apps/prototype-wp-alt-context/tests/Unit/ClusterReadServiceTest.php
    public function testListTopUnlabeledMalformedDriftIdsDoNotSetRepairPending(): void

$ sed -n '1090p' apps/prototype-wp-alt-context/tests/Unit/ClusterReadServiceTest.php
            'malformed drift ids must not publish repair_pending'

$ sed -n '1099p' apps/prototype-wp-alt-context/tests/Unit/ClusterReadServiceTest.php
    public function testListTopUnlabeledNormalizedDriftIdSetsRepairPending(): void
```

## Undone

- FE untouched, so `npx vitest run` is not required. No `js/` or `docs/ux-maps/` edit (API envelope flag only; no new screen/zone/state).
- This clone's `.task-state/handoff.db` has no active UXW2-2 task and 0 open findings. Did not write handoff here (branch is `master`; canonical target is `feature/uxw2-2`).
- Did not re-normalize extras at the call site.
