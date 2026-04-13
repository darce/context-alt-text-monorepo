# Branch Review — PHP / WordPress / PHPUnit

> Load this guide when the branch diff includes files under `apps/prototype-wp-alt-context/src/` or `tests/php/`.
> For universal process, severity definitions, and report template see [branch-review-guide.md](branch-review-guide.md).

---

## Automated Checks

| Check           | Command                                            |
| --------------- | -------------------------------------------------- |
| Static analysis | `cd apps/prototype-wp-alt-context && composer phpstan` |
| Tests           | `cd apps/prototype-wp-alt-context && composer test`    |

Require fresh PHPUnit + PHPStan evidence for runtime-sensitive fixes (bootstrap paths, controller composition, proxy/header forwarding, autoload behavior).

---

## Boundary and Runtime Correctness

- [ ] **Runtime bootstrap/autoload parity** — verify behavior under the real WordPress load path, not only the PHPUnit bootstrap fallback.
- [ ] **Adapter provenance** — controllers/adapters do not invent envelope fields (`limit`, `offset`, `total`, `data_source`, etc.); every field traces to the request, upstream payload, or documented local authority.
- [ ] **Header and status preservation** — proxy controllers preserve upstream HTTP status and headers without normalizing away failure semantics.
- [ ] **Degradation semantics** — empty, unavailable, and blocking are distinct outcomes; never silently conflated.

---

## Security

- [ ] **Superglobal sanitization** — `sanitize_key()`, `sanitize_text_field()`, or `absint()`.
- [ ] **One transport per parameter** — same value not in both POST body and query params.
- [ ] **Nonce verification** — all state-mutating endpoints check nonces.
- [ ] **Capability checks** — admin endpoints verify `current_user_can()`.

---

## SQL Bug-Finding Heuristics

### Data-flow through SQL binding

Verify the full chain per query: value origin → transformation → placeholder binding → DB interpretation.

- [ ] Placeholder count matches argument count (especially dynamic `$placeholders`).
- [ ] Arguments in correct positional order.
- [ ] Sentinel/default values survive binding. `'NULL'` (string) bound via `%s` → DB receives string `'NULL'`, not SQL `NULL`.
- [ ] `NULLIF()`, `COALESCE()`, `IF()` use the correct comparison value for the sentinel.

### Guard condition vs business rule alignment

State the business rule in plain language, then verify the SQL/code implements exactly that rule.

- [ ] Curation guards protect the **correct scope** — cluster-level guards must not block related-entity operations.
- [ ] Deletion guards use the right operator — `NOT IN` vs `FIND_IN_SET` vs `NOT EXISTS` differ on NULL, empty sets, and multi-value strings.
- [ ] Early returns match their purpose — "empty input" returns must not skip cleanup that should always run.

### SQL function semantic correctness

- [ ] `FIND_IN_SET(col, %s)` — commas in data corrupt the set boundary. Prefer `NOT IN (...)` with individual placeholders.
- [ ] `GREATEST()` / `LEAST()` — any `NULL` argument → result is `NULL`.
- [ ] `IF(condition, a, b)` — condition must evaluate against **current** row state, not `VALUES()`.
- [ ] `ON DUPLICATE KEY UPDATE` — verify which fields refresh unconditionally vs guarded. Misguarding is a silent data bug.

### Boundary value sweep

For each function accepting numeric or collection inputs:

- [ ] **Empty** — empty array/string/zero: graceful degradation or invalid SQL / divide-by-zero?
- [ ] **Single element** — `implode()` valid? Loop body works on first-and-only iteration?
- [ ] **Large input** — 10k+ items: `NOT IN (...)` MySQL limits? Unbounded `LEFT JOIN` scan?

---

## Sovereign Sync (Outbox / Conflict / Projection)

When the diff touches `src/sovereign/`:

- [ ] **Projection atomicity** — `SnapshotProjector` writes inside a single transaction.
- [ ] **Outbox entry completeness** — all required payload fields per [curation-sync-api.md](../contracts/curation-sync-api.md).
- [ ] **Projection conflict reuse** — `record_projection_conflict()` updates existing open conflicts instead of accumulating duplicates.
- [ ] **SyncState metrics updated** — projection, drain, retry/discard, and resolution paths refresh `SyncStateRepository`.
- [ ] **Dead-letter status transitions** — retry: `failed` → `pending`; discard: `failed`/`conflict` → `discarded`.
