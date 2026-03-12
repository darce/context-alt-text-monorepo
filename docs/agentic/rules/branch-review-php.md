# Branch Review — PHP / WordPress / PHPUnit

> Load this guide when the branch diff includes files under `apps/prototype-wp-alt-context/src/` or `tests/php/`.
> For universal process, severity definitions, and report template see [branch-review-guide.md](branch-review-guide.md).

---

## Automated Checks

| Check           | Command                                            |
| --------------- | -------------------------------------------------- |
| Static analysis | `cd apps/prototype-wp-alt-context && composer phpstan` |
| Tests           | `cd apps/prototype-wp-alt-context && composer test`    |

---

## Security

- [ ] **Superglobal sanitization** — `sanitize_key()`, `sanitize_text_field()`, or `absint()`.
- [ ] **One transport per parameter** — same value not in both POST body and query params.
- [ ] **Nonce verification** — all state-mutating endpoints check nonces.
- [ ] **Capability checks** — admin endpoints verify `current_user_can()`.

---

## SQL Bug-Finding Heuristics

### Data-flow through SQL binding

For each SQL query with placeholders, verify the full chain: value origin → transformation → placeholder binding → database interpretation.

- [ ] Placeholder count matches argument count (especially with dynamic `$placeholders` strings).
- [ ] Arguments are in correct positional order matching their placeholders.
- [ ] Sentinel/default values survive the binding mechanism. If a function returns `'NULL'` (string) and it's bound via `%s`, the database receives the **string** `'NULL'`, not SQL `NULL`.
- [ ] `NULLIF()`, `COALESCE()`, `IF()` wrappers use the correct comparison value for the sentinel.

### Guard condition vs business rule alignment

For each `WHERE` clause, `if` guard, or existence check, state the business rule in plain language, then verify the SQL/code implements exactly that rule.

- [ ] Curation guards protect the **correct scope** — a guard for cluster-level fields should not block operations on related entities.
- [ ] Deletion guards exclude the correct rows — `NOT IN` vs `FIND_IN_SET` vs `NOT EXISTS` have different semantics for NULL, empty sets, and multi-value strings.
- [ ] Early returns match their stated purpose — an early return for "empty input" should not also skip cleanup operations that should always run.

### SQL function semantic correctness

- [ ] `FIND_IN_SET(col, %s)` — a data value containing a comma corrupts the set boundary. Prefer `NOT IN (...)` with individual placeholders.
- [ ] `GREATEST()` / `LEAST()` — any `NULL` argument makes the result `NULL` in MySQL.
- [ ] `IF(condition, a, b)` — verify condition evaluates against the **current** row state, not `VALUES()`.
- [ ] `ON DUPLICATE KEY UPDATE` — verify which fields refresh unconditionally vs which are guarded. Accidentally guarding a field that should refresh (or vice versa) is a silent data bug.

### Boundary value sweep

For each function accepting numeric or collection inputs:

- [ ] **Empty** — empty array, empty string, zero. Does the function degrade gracefully or produce invalid SQL / divide-by-zero?
- [ ] **Single element** — does `implode()` produce valid SQL? Does a loop body work on first-and-only iteration?
- [ ] **Large input** — at 10k+ items, does a `NOT IN (...)` clause hit MySQL limits? Is there an unbounded `LEFT JOIN` scan?

---

## Sovereign Sync (Outbox / Conflict / Projection)

When the diff touches `src/sovereign/`:

- [ ] **Projection atomicity** — `SnapshotProjector` writes are inside a single transaction (`START TRANSACTION` / `COMMIT`).
- [ ] **Outbox entry completeness** — new outbox writes include all required payload fields per the topology contract in [curation-sync-api.md](../contracts/curation-sync-api.md).
- [ ] **Projection conflict reuse** — `record_projection_conflict()` updates an existing open conflict for the same tenant/entity/conflict code instead of accumulating duplicates.
- [ ] **SyncState metrics updated** — projection, drain, retry/discard, and resolution paths refresh `SyncStateRepository` so `SyncStatusController` reflects current state.
- [ ] **Dead-letter status transitions** — dead letters are `failed` rows; retry mutates the same row back to `pending`, discard mutates `failed`/`conflict` to `discarded`.
