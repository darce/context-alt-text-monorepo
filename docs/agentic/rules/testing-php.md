# PHP Testing (PHPUnit) -- Project Conventions

> **Library reference**: Use ctx7 to fetch current docs for PHPUnit and WP_Mock listed in
> [../maps/tech-stack.md](../maps/tech-stack.md#php-plugin) before starting work.
> This file covers only project-specific conventions.

> Load this document when writing or reviewing tests in `apps/prototype-wp-alt-context/src/` and `apps/prototype-wp-alt-context/tests/`. Start with [testing-principles.md](testing-principles.md) for universal concepts.

---

## Framework Stack

- **Test runner**: PHPUnit 10.5+
- **WordPress testing**: WP_Mock for WordPress function mocking
- **Static analysis**: PHPStan level 8
- **Code style**: PSR-12 + WordPress Coding Standards

---

## PHP Interface Contract Compliance

When a PHP interface method signature changes (new parameter, return type), **every** anonymous `new class() implements Interface` in test files must be updated to match. PHP enforces signature compatibility strictly — a missing optional parameter causes a fatal error, not a warning.

```php
// Interface gained ?string $tenant_id = null
public function list_for_cluster(string $uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array;

// BAD: Test anonymous class missing the new param → Fatal error
$repo = new class() implements MembersRepoInterface {
    public function list_for_cluster(string $uuid, int $limit = 500, int $offset = 0): array { return []; }
};

// GOOD: Match the full signature
$repo = new class() implements MembersRepoInterface {
    public function list_for_cluster(string $uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array { return []; }
};
```

**Rule:** After modifying any PHP interface, search all test files for `implements <InterfaceName>` and update every occurrence.

---

## Response Shape Changes Require Test Updates

When controller response shapes change (e.g., wrapping a flat array in an envelope), update assertions in all relevant tests.

```php
// Before: flat array
$this->assertSame('cluster-1', $data[0]['id']);

// After: wrapped in envelope
$this->assertArrayHasKey('clusters', $data);
$this->assertSame('cluster-1', $data['clusters'][0]['id']);
```

**Rule:** When changing response shapes, grep test files for the old assertion pattern and update all matches.

---

## WordPress Testing Patterns

### Mock HTTP Responses

```php
// Queue a mock HTTP response for wp_remote_get/post
$this->queueHttpResponse([
    'response' => ['code' => 200, 'message' => 'OK'],
    'body' => json_encode(['clusters' => []]),
]);

$response = $controller->list_clusters($request);
```

### Use WP_Mock for WordPress Functions

```php
use WP_Mock;

WP_Mock::userFunction('get_option')
    ->once()
    ->with('acx_tenant_id')
    ->andReturn('tenant-123');
```

---

## Anonymous Test Classes for Interfaces

Use anonymous classes to implement interfaces in tests. This allows per-test stubbing without creating named test doubles.

```php
$clustersRepo = new class() implements ClustersRepositoryInterface {
    public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array {
        return [
            ['cluster_uuid' => 'cluster-1', 'label' => 'Test', 'identity_count' => 3],
        ];
    }
    public function find_by_uuid(string $cluster_uuid): ?array { return null; }
    // ... implement all interface methods
};
```

**Caution:** When the interface changes, ALL anonymous implementations must be updated. Use grep to find them.

---

## Composer Classmap Regeneration

After adding a new class file or trait, regenerate the Composer classmap:

```bash
composer dump-autoload
```

Without this, the new file won't be found by the autoloader, causing "class not found" errors in tests.

---

## Sovereign Sync Test Patterns

### ConflictController and SyncStatusController

These controllers combine sync-specific repositories/services (`ConflictRepository`, `OutboxDrain`, `ConflictResolutionService`, `SyncStateRepository`) with cluster/member repository interfaces. Use focused test doubles for each dependency instead of broad “god” stubs.

### Outbox entry assertions

When testing operations that enqueue outbox entries (reassign, merge, label), assert:

1. The entry was written with the correct `operation_type` (for example `identity_reassigned`, `cluster_merged`, `assign_outlier_to_cluster`)
2. The payload contains required fields per the topology contract
3. The entry status is `pending`

### Conflict detection during projection

When testing projection conflict handling, provide a snapshot payload that triggers a known conflict code (for example `curated_member_deleted`) and assert that `ConflictRepository::record_projection_conflict()` persists the expected open conflict shape.

---

## Commands

```bash
cd apps/prototype-wp-alt-context
composer test        # PHPUnit
composer test:unit   # Unit tests only
composer phpstan     # Static analysis (level 8)
composer cs-check    # Code style check (PSR-12 + WPCS)
php -l file.php      # Syntax check single file
```

---

## Troubleshooting

### "Class not found" after creating a new file

Run `composer dump-autoload` to regenerate the classmap.

### "Declaration must be compatible" fatal error

An interface signature changed. Search test files for `implements <InterfaceName>` and update all anonymous implementations.

### phpstan missing

If `composer phpstan` fails with `vendor/bin/phpstan: No such file or directory`:

```bash
composer require --dev phpstan/phpstan:^1.12
```
