# Backend PHP Guidelines (WordPress Plugin) -- Project Conventions

> **Library reference**: Review current docs for WordPress hooks, WP_REST_API,
> and PHPUnit listed in
> [../maps/tech-stack.md](../maps/tech-stack.md#php-plugin) before starting work.
> This file covers only project-specific conventions.

> Load this document when working on PHP code in `apps/prototype-wp-alt-context/src/`.

---

## Security (MANDATORY)

Every state-changing endpoint MUST follow this pattern:

```php
// 1. Verify nonce
if (!wp_verify_nonce($_POST['_wpnonce'], 'acx_action')) {
    wp_die('Security check failed');
}

// 2. Check capabilities via centralized helper
if (!Security::can_generate_alt_text()) {
    return new WP_Error('forbidden', 'Insufficient permissions', ['status' => 403]);
}

// 3. Sanitize input
$clean = sanitize_text_field($_POST['input']);
$clean_array = array_map('absint', $_POST['ids']);

// 4. Escape output
echo esc_html($user_input);
echo esc_url($url);
echo esc_attr($attribute);
```

- **Always sanitize superglobal access** -- `sanitize_key()`, `sanitize_text_field()`, or `absint()` on `$_GET`/`$_POST`/`$_REQUEST` even for allowlist comparisons
- **One transport per parameter** -- pick POST body or query params, not both
- Rate limiting via keyed transients

---

## WordPress Plugin Rules

1. **No orphaned route registrations.** Every `register_rest_route()` must have a frontend consumer.
2. **Symmetric create/destroy for plugin-owned tables.** Every `CREATE TABLE` needs a `DROP TABLE IF EXISTS` in `LifecycleManager::uninstall()`.
3. **Fail fast on missing build assets.** Report via admin notice + `error_log` when Vite manifest or assets are missing.
4. **No allow-listed slugs without registered pages.**
5. **Strict boolean parameter parsing.** Use `rest_sanitize_boolean()`. PHP treats `'false'` as truthy.

---

## Sovereign Sync Layer (`src/sovereign/`)

Four subsystems:

1. **Inbound projection** (`SnapshotProjector` + repositories): pulls snapshots into local tables in one DB transaction; records projection conflicts.
2. **Outbound replay** (`OutboxDrain` + `OutboxDispatcher`): drains `wp_acx_sync_outbox` to backend endpoints; applies status transitions (`acknowledged`, `conflict`, `failed`, `discarded`).
3. **Conflict resolution** (`ConflictResolutionService`): resolves `wp_acx_sync_conflicts` by accepting machine state or keeping local state.
4. **Sync health** (`SyncStateRepository` + `SyncStatusController`): persists reachability and aggregate counts.

### Rules

- **Atomic projection transactions.** All projection work in one `$wpdb` transaction.
- **Outbox payloads are append-only.** Do not rewrite semantic payload after enqueue.
- **Idempotent open-conflict reuse.** `record_projection_conflict()` updates existing open conflicts instead of inserting duplicates.
- **Explicit status transitions.** Retry resets `failed` to `pending`; dismiss re-enqueues with new `expected_base_version`; discard is terminal.
- **Sync metrics are behavior.** All mutation paths must refresh `SyncStateRepository` metrics.

---

## Repository & Query Patterns

### Schema-Key Parity Before Query Edits

Confirm column names from lifecycle schema (`class-life-cycle-manager.php`) before changing SQL. Column-name mismatch is a HIGH-severity defect. Add tests that fail on non-existent keys.

### Prefer Derived Counts Over Stale Denormalized Fields

Derive counts from authoritative relationships (e.g., `COUNT(*)` via `wp_acx_clusters.person_id`). If a denormalized counter exists, keep it transactionally updated or do not use it.

### Avoid N+1 Queries in Loops

Use batch methods with `WHERE column IN (...)` instead of per-record repository calls in loops.

```php
// BAD: N+1 — one query per cluster
foreach ($cluster_rows as $row) {
    $members[$row['uuid']] = $repo->list_for_cluster($row['uuid']);
}

// GOOD: Single query with ROW_NUMBER() window function for per-group limits
public function list_for_cluster_uuids(array $uuids, int $limit_per_cluster): array {
    $placeholders = implode(',', array_fill(0, count($uuids), '%s'));
    $sql = "SELECT * FROM (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY cluster_uuid ORDER BY updated_at DESC) AS rn
        FROM {$this->table}
        WHERE cluster_uuid IN ($placeholders)
    ) ranked WHERE rn <= %d";
    // ... execute and group by cluster_uuid in PHP
}
```

### Tenant-Scoped Queries (Defense in Depth)

Always add a `tenant_id` JOIN or WHERE clause, even when filtering by globally-unique UUID.

```php
// Acceptable but fragile:
SELECT * FROM members WHERE cluster_uuid = %s

// Preferred — defense in depth:
SELECT m.* FROM members m
  JOIN clusters c ON m.cluster_uuid = c.cluster_uuid
  WHERE m.cluster_uuid = %s AND c.tenant_id = %s
```

---

## Trait Extraction Rules

1. **Copy signatures verbatim.** No type changes during extraction.
2. **Run `composer dump-autoload` after creating the trait file.**
3. **Remove the original methods from both classes.** Leaving them shadows the trait.
4. **Verify with `php -l` on all three files** before running tests.

---

## Taxonomy Capability Model

- **CRUD** (`manage_options`): administrators only
- **Assignment** (`upload_files`): editors and above
- `show_in_rest => true` for block editor and REST API access
- `rest_sanitize_boolean()` for boolean query params

---

## Roster Confidence Display

Only displayed when a roster match exists. Priority order:

1. `record.match.similarity` (roster match similarity)
2. `record.match.confidence` (roster match confidence)
3. `record.matchConfidence` (fallback roster confidence)
4. `topCandidate.similarity` (best candidate similarity)
5. `topCandidate.confidence` (best candidate confidence)

Never show detection confidence as if it were match confidence.
