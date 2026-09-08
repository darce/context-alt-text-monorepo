# HEALTHOBS-1 / healthobs-1-dedupe

Base: `feature/healthobs-1` @ `6a83126112be6518eb4962a17f9b9b66e90cd66b`
Work in `/Users/daniel/Development/context-alt-text-monorepo-healthobs-1-dedupe` on `feature/healthobs-1-dedupe`.

Two findings, both already recorded. Fix both, then stop.

## HEALTHOBS-1-BR-03 (medium) — one helper, not two

`_install_healthy_observability_session(app)` is defined twice with identical bodies,
differing only in the docstring:

- `apps/prototype-description-service/recognition/tests/api/test_metrics.py:15` (called at :217)
- `apps/prototype-description-service/scene/tests/test_describe_run_reclaim.py:26` (called at :274, :310, :342)

Both stub the same pool-aware liveness contract this branch introduces. When that
contract changes, one copy gets updated and the other keeps asserting the old shape,
so a real `/health` regression passes in one package and fails in the other.

Do this:

1. Create `apps/prototype-description-service/recognition/tests/support/__init__.py`
   and `.../recognition/tests/support/health_session.py` holding exactly one copy of
   the helper. `recognition/tests` is already an importable package (`__init__.py`
   present), and `scene/tests` already imports across packages
   (`from scene.tests.test_describe_run_repository import _sessionmaker`), so
   `from recognition.tests.support.health_session import install_healthy_observability_session`
   works from both sides.
2. Give it one docstring that names what it is: the pool-aware liveness contract stub
   that keeps these assertions independent of a live database.
3. Delete both local definitions and route all four call sites through the import.
4. This is an extraction. The stubbed behaviour must not change — same rows, same
   `AsyncMock`/`MagicMock` shapes, same nested-transaction context manager.

Verification for BR-03: `pytest recognition/tests/api/test_metrics.py scene/tests/test_describe_run_reclaim.py -q`
must pass with the same test count as before the change. Then prove the extraction is
load-bearing: temporarily break one field in the shared helper and confirm tests in
**both** modules fail. Revert the break. Report both observations.

## HEALTHOBS-1-BR-04 (low) — settle the out-of-scope hunk

`apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py:1292`,
inside `get_unclustered`:

```
raw: list[tuple[MediaIdentity, uuid.UUID]] = list(result.tuples().all())
```

vs `main`, which had `list[tuple[MediaIdentity, uuid.UUID | None]]` and `result.all()`.

The `MvRefreshOutcome` and disk-headroom hunks in this file are squarely in the branch
objective. This one is not: it is a typing/SQLAlchemy-API change on an unrelated query
path, carried in with no test of its own. Dropping the `| None` asserts that the join
can never yield a null `cluster_id`; if that is wrong it surfaces at runtime, not at
type-check.

Read the statement above line 1292. Decide, and say which you chose and why:

- **Keep it** if the `INNER JOIN` on `IdentityMemberModel.cluster_id` plus the
  `ClusterModel` join genuinely makes a null impossible. Then add a unit test in
  `recognition/tests/unit/` that pins the invariant (a row whose `cluster_id` is null
  must not reach this list), and add a one-line WHY comment at the narrowing.
- **Revert it** to the `main` shape if you cannot establish that invariant from the
  query alone. A revert is the correct answer if it is merely a mypy convenience.

Do not do both. Do not expand the diff beyond these two findings.

## Rules

- Commit on `feature/healthobs-1-dedupe` with subject
  `test: one shared pool-aware health-session helper; settle the typed-query hunk`.
- No AI attribution trailers of any kind in the commit message.
- Never weaken or delete a test to make something pass.
- `ruff`/`mypy` noise does not block you; note it, do not silence the tool.
