# Backend PHP Guidelines (WordPress Plugin)

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

Additional security rules:

- **Always sanitize superglobal access** -- use `sanitize_key()`, `sanitize_text_field()`, or `absint()` on `$_GET`/`$_POST`/`$_REQUEST` even when comparing against allowlists
- **One transport per parameter** -- do not send the same value (e.g., `tenant_id`) in both the POST body and query params; pick one per your API contract
- Rate limiting via keyed transients

---

## WordPress Plugin Rules

> Distilled from the 4.13.0 web-deployment cleanup audit.

1. **No orphaned route registrations.** Every `register_rest_route()` must have at least one frontend consumer. Dead routes expand attack surface and confuse API documentation.
2. **Symmetric create/destroy for plugin-owned tables.** Every `dbDelta()` / `CREATE TABLE` must have a corresponding `DROP TABLE IF EXISTS` in the uninstall lifecycle (`LifecycleManager::uninstall()`).
3. **Fail fast on missing build assets.** Admin SPA bootstrap must report explicitly (admin notice + `error_log`) when the Vite manifest or compiled assets are missing or unreadable.
4. **No allow-listed slugs without registered pages.** If a page slug appears in a permission or enqueue allowlist (e.g., `SUPPORTED_PAGE_SLUGS`), a corresponding menu page must be registered.
5. **Strict boolean parameter parsing.** Use `rest_sanitize_boolean()` for REST query/body params intended as booleans. PHP treats the string `'false'` as truthy.

---

## Repository & Query Patterns

### Schema-Key Parity Before Query Edits

Before changing SQL for plugin tables, confirm key column names from lifecycle schema (`class-life-cycle-manager.php`) and repository contracts.

- Do not assume generic keys like `id` / `cluster_id`; use actual schema keys (for example `cluster_uuid`).
- Treat column-name mismatch as a HIGH-severity correctness defect.
- Add/extend tests that fail if `UPDATE`/`WHERE` targets a non-existent key.

### Prefer Derived Counts Over Stale Denormalized Fields

For roster/person reporting, derive counts from authoritative relationships when practical (for example `COUNT(*)` via `wp_acx_clusters.person_id`) instead of trusting never-updated counter columns.

- If a denormalized counter exists, either keep it transactionally updated in every write path or do not use it for read responses.

### Avoid N+1 Queries in Loops

Never call a repository method inside a `foreach` loop over parent records. Use a batch method with `WHERE column IN (...)` instead.

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

Even when filtering by a globally-unique UUID, prefer adding a `tenant_id` JOIN or WHERE clause. UUID uniqueness is an implementation assumption; tenant scoping is a security invariant.

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

When extracting duplicated methods into a PHP trait:

1. **Copy signatures verbatim.** Do not "improve" parameter types, add clamping, or change nullability during extraction. The trait must be a drop-in replacement.
2. **Run `composer dump-autoload` after creating the trait file.** Composer's classmap does not detect new files automatically.
3. **Remove the original methods from both classes.** Leaving them shadows the trait methods, making the trait dead code.
4. **Verify with `php -l` on all three files** (trait + both consumers) before running tests.

---

## Taxonomy Capability Model

When registering custom taxonomies (e.g., roster entity associations):

- **CRUD operations** (`manage_options`): restrict to administrators
- **Assignment to posts/attachments** (`upload_files`): editors and above
- Register with `show_in_rest => true` for block editor and REST API access
- Use `rest_sanitize_boolean()` for boolean query params (PHP treats `'false'` as truthy)

---

## Roster Confidence Display

Match confidence is ONLY displayed when a roster match exists. Priority order:

1. `record.match.similarity` (roster match similarity)
2. `record.match.confidence` (roster match confidence)
3. `record.matchConfidence` (fallback roster confidence)
4. `topCandidate.similarity` (best candidate similarity)
5. `topCandidate.confidence` (best candidate confidence)

Never show detection confidence as if it were match confidence.
