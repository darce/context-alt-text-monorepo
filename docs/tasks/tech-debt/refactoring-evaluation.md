# Refactoring Evaluation: Code Smells and Opportunities

> Cross-referencing Fowler/Beck "Refactoring: Improving the Design of Existing Code" (2nd Ed., 2019) against the Alt Context monorepo to identify areas that would benefit from systematic refactoring.

**Date:** 2025-01-27
**Scope:** All three stacks (Python backend, PHP plugin, TypeScript frontend)
**Method:** Codebase exploration guided by the code smells catalog from Chapter 3 of the book, supplemented by the refactoring catalog (Chapters 6-12).

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Methodology](#methodology)
- [High-Impact Findings](#high-impact-findings)
  - [H1: Large Class; cluster_repository.py (1,373 lines)](#h1-large-class-cluster_repositorypy-1373-lines)
  - [H2: Large Class; ClusterMutationsController (1,198 lines)](#h2-large-class-clustermutationscontrollerphp-1198-lines)
  - [H3: Primitive Obsession; raw strings/ints for domain concepts](#h3-primitive-obsession-raw-stringsints-for-domain-concepts)
  - [H4: Duplicated Code; transaction boilerplate in PHP controllers](#h4-duplicated-code-transaction-boilerplate-in-php-controllers)
  - [H5: Shotgun Surgery; tenant_id threading](#h5-shotgun-surgery-tenant_id-threading)
- [Medium-Impact Findings](#medium-impact-findings)
  - [M1: Long Function; OutboxDrain::drain() and load_pending_operations()](#m1-long-function-outboxdraindrain-and-load_pending_operations)
  - [M2: Long Function; analyze_media() router handler (120 lines)](#m2-long-function-analyze_media-router-handler-120-lines)
  - [M3: Feature Envy; PHP response mappers reaching into raw arrays](#m3-feature-envy-php-response-mappers-reaching-into-raw-arrays)
  - [M4: Data Clumps; recurring field groups across layers](#m4-data-clumps-recurring-field-groups-across-layers)
  - [M5: Middle Man; AbstractRecognitionProxyController](#m5-middle-man-abstractrecognitionproxycontroller)
  - [M6: Duplicated Code; Python response builder loops](#m6-duplicated-code-python-response-builder-loops)
  - [M7: Long Function; useJobCoordination.ts (220 lines)](#m7-long-function-usejobcoordinationts-220-lines)
- [Low-Impact Findings](#low-impact-findings)
  - [L1: Mysterious Name; \_load_topology_replay / \_store_topology_replay](#l1-mysterious-name-_load_topology_replay--_store_topology_replay)
  - [L2: Speculative Generality; SuggestionExtensionService scaffold](#l2-speculative-generality-suggestionextensionservice-scaffold)
  - [L3: Data Class; MediaIdentity with minimal behavior](#l3-data-class-mediaidentity-with-minimal-behavior)
  - [L4: Comments as Deodorant; analyze.py inline explanations](#l4-comments-as-deodorant-analyzepy-inline-explanations)
  - [L5: Duplicated Code; TypeScript API type guards](#l5-duplicated-code-typescript-api-type-guards)
  - [L6: Long Parameter List; BulkActionBar (7 props)](#l6-long-parameter-list-bulkactionbar-7-props)
  - [L7: Duplicated Code; retention response coercion functions](#l7-duplicated-code-retention-response-coercion-functions)
- [Architectural Observations](#architectural-observations)
- [Recommended Refactoring Sequence](#recommended-refactoring-sequence)

---

## Executive Summary

The codebase has a clean layered architecture (domain/infrastructure/interface adapters in Python; sovereign sync/controllers/React UI in the WordPress plugin) with well-defined API contracts. The primary tech debt concentrates in two god objects and pervasive primitive obsession:

| Category               | Count                 | Highest Severity |
| ---------------------- | --------------------- | ---------------- |
| Large Class            | 2                     | High             |
| Primitive Obsession    | 5 value types missing | High             |
| Duplicated Code        | 5 patterns            | High-Medium      |
| Long Function          | 4 instances           | Medium           |
| Feature Envy           | 2 instances           | Medium           |
| Shotgun Surgery        | 1 systemic pattern    | High             |
| Data Clumps            | 3 groups              | Medium           |
| Middle Man             | 1 instance            | Medium           |
| Mysterious Name        | 1 instance            | Low              |
| Data Class             | 1 instance            | Low              |
| Speculative Generality | 1 instance            | Low              |
| Comments as Deodorant  | 1 instance            | Low              |
| Long Parameter List    | 1 instance            | Low              |

**Top 3 payoff refactorings:**

1. **Extract Class** on `cluster_repository.py` (1,373 lines -> 4 focused repositories of ~300 lines each); eliminates ~40% of the Shotgun Surgery risk
2. **Introduce Value Object** for `TenantId`, `SnapshotVersion`, `CurationState`, `OperationType`, `BoundingBox`; eliminates Primitive Obsession and most Data Clumps in one pass
3. **Extract Function / Replace Inline Code with Function Call** on PHP transaction boilerplate; eliminates the most common Duplicated Code pattern (~10 repetitions)

---

## Methodology

### Book Concepts Applied

From Fowler/Beck Chapter 3 ("Bad Smells in Code"), each smell was evaluated against the three stacks:

- **Mysterious Name** -- functions/variables whose names don't communicate intent
- **Duplicated Code** -- identical structure in multiple places
- **Long Function** -- functions that do too much (heuristic: >50 lines worth examining, >100 lines smell strongly)
- **Long Parameter List** -- functions taking >4 parameters where a structure would clarify
- **Global Data** -- mutable module-level state
- **Mutable Data** -- data that changes in place when immutability would be safer
- **Divergent Change** -- one module changed for multiple unrelated reasons
- **Shotgun Surgery** -- one conceptual change requiring edits across many modules
- **Feature Envy** -- function accessing another module's data more than its own
- **Data Clumps** -- groups of data items that travel together
- **Primitive Obsession** -- using primitives where small objects would express intent
- **Repeated Switches** -- same conditional-dispatch logic in multiple places
- **Loops** -- imperative loops where pipeline operations (map/filter) would clarify
- **Lazy Element** -- class/function that doesn't justify its existence
- **Speculative Generality** -- abstractions built for hypothetical future use
- **Temporary Field** -- fields set only in certain circumstances
- **Message Chains** -- long chains of method calls traversing object graphs
- **Middle Man** -- class that mostly delegates to another
- **Insider Trading** -- modules sharing too much internal knowledge
- **Large Class** -- class with too many fields or too much code
- **Data Class** -- class with fields and accessors but no behavior
- **Comments** -- comments used as deodorant for unclear code

### Key Refactorings Referenced

| Refactoring                            | Book Reference | Applied To     |
| -------------------------------------- | -------------- | -------------- |
| Extract Class                          | Ch. 7          | H1, H2         |
| Introduce Parameter Object             | Ch. 6          | H3, M4, L6     |
| Replace Primitive with Object          | Ch. 6          | H3, H5         |
| Extract Function                       | Ch. 6          | H4, M1, M2, M7 |
| Replace Inline Code with Function Call | Ch. 8          | H4             |
| Move Function                          | Ch. 8          | M3, M5         |
| Change Function Declaration            | Ch. 6          | L1             |
| Remove Middle Man                      | Ch. 7          | M5             |
| Encapsulate Record                     | Ch. 7          | M3             |
| Replace Loop with Pipeline             | Ch. 8          | M6             |

---

## High-Impact Findings

### H1: Large Class; cluster_repository.py (1,373 lines)

**Smell:** Large Class
**File:** `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`
**Lines:** 1,373 total; ~49 public/private async methods

**Description:** `SqlAlchemyClusterRepository` is a god object handling cluster CRUD, representative management, member queries, snapshot export, maturity calculations, and representative selection. The class has at least five distinct responsibilities, making it a prime candidate for Extract Class.

**Evidence:**

- Cluster CRUD operations (create, update, delete, get)
- Representative lifecycle (select, score, replace, quality/diversity calculations)
- Member query composition (by cluster, by tenant, orphan detection)
- Snapshot/delta export (version-based projections, tombstone tracking)
- Maturity computation (threshold checks, readiness scoring)

**Recommended refactoring:** Apply **Extract Class** (Fowler Ch. 7, p. 182) to split into:

- `ClusterCrudRepository` -- basic entity operations (~250 lines)
- `RepresentativeRepository` -- selection, scoring, replacement (~350 lines)
- `ClusterQueryRepository` -- complex read queries, member lookups (~300 lines)
- `ClusterSnapshotRepository` -- delta/snapshot export, version tracking (~300 lines)

Each new class would take only the `AsyncSession` dependency. The domain Protocol in `repositories.py` already groups methods logically; use those groupings as the split boundaries.

**Risk:** Low. All consumers access through the Protocol interface; swapping implementations is a mechanical change. Tests already exercise each concern group independently.

---

### H2: Large Class; ClusterMutationsController.php (1,198 lines)

**Smell:** Large Class + Long Function (multiple methods 80-150 lines)
**File:** `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`
**Lines:** 1,198 total; 13 REST endpoints + helper methods

**Description:** Every cluster mutation (merge, split, reassign, label, dismiss, undismiss, create, revert, assign outlier, pin representative) lives in one controller class. Individual handler methods like `merge_cluster()` (84 lines) and `split_cluster()` (102 lines) contain validation, transaction management, member reassignment, operation queueing, and sync marker updates inline.

**Evidence:**

- `merge_cluster()` lines 417-500: validation + transaction + member reassignment + label update + operation queue + sync markers
- `split_cluster()` lines 502-603: parameter extraction + payload building + conditional field additions + multi-step operation logic
- Transaction boilerplate repeated 10+ times (see H4)

**Recommended refactoring:** Apply **Extract Class** for per-operation handlers + **Move Function** to push domain logic into a service layer:

1. Create `ClusterMergeHandler`, `ClusterSplitHandler`, etc. (~100-150 lines each)
2. Move validation and transaction orchestration into a `ClusterMutationService` that the handlers delegate to
3. Controller methods become thin dispatchers: parse request -> call service -> return response

**Risk:** Medium. WordPress REST API registration couples route definitions to the controller class. The handler classes would need a registration adapter.

---

### H3: Primitive Obsession; raw strings/ints for domain concepts

**Smell:** Primitive Obsession
**Scope:** Cross-cutting (all three stacks)

**Description:** Five domain concepts are represented as raw primitives throughout the codebase, forcing every consumer to know their format, validation rules, and conversion logic.

| Concept             | Current Type        | Locations                                                              | Risk of Raw Primitive                                                                                               |
| ------------------- | ------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `tenant_id`         | `string`            | 30+ files; every repository method, every controller                   | Typo corrupts tenant isolation silently                                                                             |
| `snapshot_version`  | `int`               | `cluster_repository.py`, `class-snapshot-projector.php`                | Manual microsecond <-> datetime conversion in 4 places                                                              |
| `curation_state`    | `string`            | 10+ PHP files                                                          | Invalid states accepted silently; `'confirmed'`, `'pending'`, `'missing_from_snapshot'` scattered as inline strings |
| `operation_type`    | `string`            | `class-outbox-dispatcher.php`, `class-conflict-resolution-service.php` | Dispatch via if-chains against hardcoded strings; valid values live only in comments                                |
| `bbox` (x, y, w, h) | 4 separate `float`s | `class-image-xmp-writer.php`, `identity.py`, PHP trait                 | Must be assembled/destructured at every use site                                                                    |

**Recommended refactoring:** Apply **Replace Primitive with Object** (Fowler Ch. 6) for each:

- **Python:** `class TenantId(str)` with `__init__` validation; `class SnapshotVersion` encapsulating `_to_datetime()` / `_from_datetime()`; `class BoundingBox(NamedTuple)` with `x`, `y`, `width`, `height`
- **PHP:** `enum CurationState: string` (PHP 8.1+); `enum OperationType: string`; `final class BoundingBox { ... }`
- **TypeScript:** branded types or tiny wrapper classes for `TenantId`, `SnapshotVersion`

**Risk:** Low-Medium. Most replacements are mechanical (find-replace at boundaries). Start with the most-used concept (`CurationState` enum in PHP) for immediate payoff.

---

### H4: Duplicated Code; transaction boilerplate in PHP controllers

**Smell:** Duplicated Code
**File:** `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`
**Lines:** Pattern appears ~10 times (e.g., lines 212-225, 284-297, 336-349)

**Description:** Every mutation method repeats the same transaction management pattern:

```php
if ( false === $wpdb->query( 'START TRANSACTION' ) ) { return error; }
// mutation logic
if ( affected_rows > 0 && ! $this->enqueue_curation_operation(...) ) {
    $wpdb->query('ROLLBACK'); return error;
}
if ( false === $wpdb->query( 'COMMIT' ) ) {
    $wpdb->query('ROLLBACK'); return error;
}
```

This is ~15 lines of boilerplate repeated before the actual domain logic in each handler.

**Recommended refactoring:** Apply **Extract Function** + **Replace Inline Code with Function Call** (Fowler Ch. 8):

```php
private function run_transactional( callable $operation ): WP_REST_Response|WP_Error {
    global $wpdb;
    if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
        return new WP_Error( 'transaction_failed', '...' );
    }
    try {
        $result = $operation();
        $wpdb->query( 'COMMIT' );
        return $result;
    } catch ( \Throwable $e ) {
        $wpdb->query( 'ROLLBACK' );
        return new WP_Error( 'mutation_failed', $e->getMessage() );
    }
}
```

Then each handler becomes:

```php
return $this->run_transactional( function() use ( $request ) {
    // pure domain logic only
});
```

**Risk:** Low. The pattern is identical across all uses; a wrapper introduces no new behavior.

---

### H5: Shotgun Surgery; tenant_id threading

**Smell:** Shotgun Surgery
**Scope:** Cross-cutting (30+ files)

**Description:** Any change to how `tenant_id` is acquired, validated, or formatted requires touching:

- `class-abstract-recognition-proxy-controller.php` (resolution)
- `class-cluster-mutations-controller.php` (10+ methods)
- `class-conflict-controller.php` (5+ methods)
- `class-api.php` (8+ methods)
- `cluster_repository.py` (40+ methods)
- Multiple test files

The `tenant_id` value is resolved from WordPress options in the PHP layer, passed as a raw string to the Python backend via HTTP headers, extracted from the header in FastAPI dependencies, and threaded into every repository method. A single format change (e.g., adding a prefix, switching from UUID to ULID) would require coordinated edits across 30+ files.

**Recommended refactoring:** Apply **Replace Primitive with Object** (H3) combined with **Introduce Parameter Object** (Fowler Ch. 6):

1. Create `TenantContext` value object in both PHP and Python that encapsulates `tenant_id` + resolution metadata
2. Resolve once at the boundary (WordPress option -> `TenantContext` in PHP; HTTP header -> `TenantContext` via FastAPI dependency in Python)
3. Pass the value object through; method signatures shrink and the blast radius of format changes drops to 2 files (the resolution points)

---

## Medium-Impact Findings

### M1: Long Function; OutboxDrain::drain() and load_pending_operations()

**Smell:** Long Function
**File:** `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php`
**Lines:** `drain()` at lines 111-145 (35 lines); `load_pending_operations()` at lines 343-391 (49 lines)

**Description:** `drain()` orchestrates filtering, dispatching, result application, tenant tracking, and rescheduling without clear phase separation. `load_pending_operations()` performs query execution, row iteration, and payload decoding with multiple nested checks.

**Recommended refactoring:** Apply **Extract Function** (Fowler Ch. 6, p. 106):

- Extract `apply_batch_results()` from `drain()`
- Extract `decode_operation_payload()` from `load_pending_operations()`

---

### M2: Long Function; analyze_media() router handler (120 lines)

**Smell:** Long Function
**File:** `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`
**Lines:** 105-220 (~120 lines)

**Description:** Handles media extraction, tenant provisioning, session factory creation, and background task scheduling in a single handler. The function mixes HTTP concerns (request parsing, response building) with domain orchestration (scan queueing, tenant setup).

**Recommended refactoring:** Apply **Extract Function** + **Split Phase** (Fowler Ch. 6):

1. Extract `_prepare_tenant_context(request)` for tenant provisioning
2. Extract `_prepare_media_items(request)` for media source resolution
3. The handler becomes a thin orchestrator calling those phases sequentially

---

### M3: Feature Envy; PHP response mappers reaching into raw arrays

**Smell:** Feature Envy
**Files:**

- `apps/prototype-wp-alt-context/src/sovereign/mappers/class-member-response-mapper.php` (lines 66-92)
- `apps/prototype-wp-alt-context/src/sovereign/mappers/class-cluster-response-mapper.php` (lines 71-110)

**Description:** `map_member_row()` accesses 15+ fields from a raw `$member_row` array. `map_top_unlabeled_clusters()` iterates clusters, extracts fields, then queries another array (`$members_by_cluster`) for each. Both methods know more about the raw database row structure than their own class's concerns.

**Recommended refactoring:** Apply **Encapsulate Record** (Fowler Ch. 7, p. 162) to create `MemberRecord` and `ClusterRecord` value objects at the repository boundary. Mappers then work with typed objects instead of reaching into raw arrays.

---

### M4: Data Clumps; recurring field groups across layers

**Smell:** Data Clumps
**Scope:** Cross-cutting

Three field groups consistently travel together but have no unifying type:

| Clump                     | Fields                                                     | Locations                                                                                  |
| ------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Cluster curation snapshot | `cluster_uuid`, `label`, `curation_state`                  | `class-snapshot-projector.php` L120-140; `class-cluster-mutations-controller.php` L282-329 |
| Bounding box              | `x`, `y`, `width`, `height`                                | `class-image-xmp-writer.php` L199; `identity.py` L14-45; PHP trait                         |
| Outbox operation key      | `tenant_id`, `operation_type`, `entity_key`, `entity_type` | `class-outbox-drain.php` L622; `class-conflict-repository.php` methods                     |

**Recommended refactoring:** Apply **Introduce Parameter Object** (Fowler Ch. 6, p. 140):

- `ClusterCurationSnapshot(cluster_uuid, label, curation_state, timestamp)`
- `BoundingBox(x, y, width, height)` (shared across Python + PHP)
- `OutboxOperationKey(tenant_id, operation_type, entity_key, entity_type)`

---

### M5: Middle Man; AbstractRecognitionProxyController

**Smell:** Middle Man
**File:** `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` (150 lines)

**Description:** Most public methods (`can_manage_recognition()`, `resolve_request_policy()`, `get_tenant_id()`) delegate to configuration readers or a circuit breaker. The class adds no REST-specific logic; it exists primarily as a delegation layer.

**Recommended refactoring:** Apply **Remove Middle Man** (Fowler Ch. 7, p. 192):

1. Create a `ProxyPolicy` service that owns config resolution, circuit breaking, and tenant context
2. Controller subclasses compose `ProxyPolicy` via constructor injection instead of inheriting the delegation layer
3. Removes the inheritance chain dependency, making individual controllers testable in isolation

---

### M6: Duplicated Code; Python response builder loops

**Smell:** Duplicated Code
**File:** `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py`
**Lines:** `_build_cluster_responses()` (198-220) and `_build_member_responses()` (224-251)

**Description:** Identical loop-transform-append pattern: iterate items, call a transform function, append to result list. The two functions differ only in the transform applied.

**Recommended refactoring:** Apply **Replace Loop with Pipeline** (Fowler Ch. 8, p. 231):

```python
cluster_responses = [_transform_cluster(c) for c in clusters]
member_responses = [_transform_member(m) for m in members]
```

Or extract a generic `_build_responses(items, transform)` if additional logging/error handling is shared.

---

### M7: Long Function; useJobCoordination.ts (220 lines)

**Smell:** Long Function
**File:** `apps/prototype-wp-alt-context/js/admin/hooks/useJobCoordination.ts` (220 lines)

`[TS overlap]` The TypeScript evaluation identifies additional long-function instances in the same codebase: TS-H2 (RetentionPage 250+ lines) and TS-M3 (useJobProgressStream 165 lines). See [refactoring-typescript-evaluation.md](refactoring-typescript-evaluation.md).

**Description:** Manages BroadcastChannel-based tab election, heartbeat protocol, and message routing all in one hook. ~100 lines of setup and ~120 lines of event handlers.

**Recommended refactoring:** Apply **Extract Function** (Fowler Ch. 6):

1. Extract `useTabElection()` for the primary/secondary election logic
2. Extract `useHeartbeatProtocol()` for the heartbeat ping/pong
3. `useJobCoordination()` becomes a composition of those two hooks + message routing

---

## Low-Impact Findings

### L1: Mysterious Name; \_load_topology_replay / \_store_topology_replay

**Smell:** Mysterious Name
**File:** `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` (lines 137-158)

**Description:** "replay" refers to idempotency caching, not event replay. The name misleads readers into thinking these functions relate to event sourcing.

**Recommended refactoring:** Apply **Change Function Declaration** (Fowler Ch. 6, p. 124):

- Rename to `_load_idempotency_cache()` and `_store_idempotency_cache()`

---

### L2: Speculative Generality; SuggestionExtensionService scaffold

**Smell:** Speculative Generality
**File:** `apps/prototype-description-service/recognition/domain/services/suggestion_extension_service.py` (37 lines)

**Description:** All 5 async methods raise `NotImplementedError`. The class exists as Phase 0 scaffolding that hasn't been implemented yet.

**Note:** This is acceptable scaffolding per the project's "Scaffolding First" mandate. Flag for review if it remains unimplemented after the feature is considered complete.

---

### L3: Data Class; MediaIdentity with minimal behavior

**Smell:** Data Class
**File:** `apps/prototype-description-service/recognition/domain/identity.py` (47 lines)

**Description:** `MediaIdentity` has 16 fields and only two behavior methods (`extract_face_embedding()`, `face_vector` property). Most processing logic lives in consumers (repository layer, router handlers) rather than in the entity itself.

**Recommended refactoring:** Apply **Move Function** (Fowler Ch. 8, p. 198) to pull behavior closer to the data:

- Add `is_aligned()` checking pose thresholds
- Add `bounding_box` property returning a `BoundingBox` value object
- Add `similarity_to(other)` for embedding comparison

**Note:** Per Fowler, immutable data records used as result objects (e.g., after Split Phase) are acceptable Data Classes. Evaluate whether `MediaIdentity` is primarily an immutable result record or a mutable entity.

---

### L4: Comments as Deodorant; analyze.py inline explanations

**Smell:** Comments
**File:** `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` (lines 116-120, 153)

**Description:** Inline comments explain media extraction branching logic ("Use URLs for detection...", "No URLs available...") that should be self-evident from well-named helper functions. A NOTE comment references an external design doc for batch-limit decisions.

**Recommended refactoring:** Apply **Extract Function** (Fowler Ch. 6) to make the comments superfluous:

- `_resolve_media_from_urls(request)` / `_resolve_media_from_ids(request)` make the branching self-documenting

---

### L5: Duplicated Code; TypeScript API type guards

**Smell:** Duplicated Code
**Files:**

- `apps/prototype-wp-alt-context/js/admin/api/mediaApi.ts` (line 35)
- `apps/prototype-wp-alt-context/js/admin/api/workbenchMediaApi.ts` (line 29)

`[TS overlap]` Related to TS-L3 (verbose AbortError type guard); both point to type guard hygiene in the frontend. See [refactoring-typescript-evaluation.md](refactoring-typescript-evaluation.md).

**Description:** Both files define structurally identical response type guards (`isWPMediaResponse`, `isWorkbenchMediaResponse`) following the same pattern.

**Recommended refactoring:** Extract a shared `createResponseTypeGuard<T>(requiredKeys: string[])` utility in `js/admin/utils/http.ts`.

---

### L6: Long Parameter List; BulkActionBar (7 props)

**Smell:** Long Parameter List
**File:** `apps/prototype-wp-alt-context/js/admin/pages/roster/BulkActionBar.tsx` (lines 5-13)

`[TS overlap]` The TypeScript evaluation identifies worse instances of this pattern: TS-H3 (useClusterSaveAction, 13 params) and TS-L4 (useClusterConfirmSuggestion, 12 params). See [refactoring-typescript-evaluation.md](refactoring-typescript-evaluation.md).

**Description:** Component takes 7 props including callback functions (`onMerge`, `onDismiss`, `onClear`), state flags (`isMerging`, `isDismissing`), and progress data (`mergeProgress`).

**Recommended refactoring:** Apply **Introduce Parameter Object** (Fowler Ch. 6):

- Group into `BulkActionState { isMerging, isDismissing, mergeProgress }` and `BulkActionCallbacks { onMerge, onDismiss, onClear }`
- Or expose via a `useBulkActions()` context if the data is shared across multiple siblings

---

### L7: Duplicated Code; retention response coercion functions

**Smell:** Duplicated Code
**File:** `apps/prototype-description-service/recognition/interface_adapters/http/routers/retention.py` (lines 50-83)

**Description:** `_coerce_export_response()` and `_coerce_purge_response()` follow identical patterns: check missing fields, apply fallback casting, repackage dict. The HTTP layer also reaches into service payload structure (Insider Trading).

**Recommended refactoring:**

1. Extract `_coerce_dict_response(raw, default_schema)` shared utility
2. Move coercion into the service layer; return typed `ExportResult` / `PurgeResult` dataclasses instead of raw dicts

---

## Architectural Observations

### What the codebase does well

**Clean layered architecture (Python).** The domain layer (`recognition/domain/`) contains pure Python dataclasses, enums, and Protocol definitions with no infrastructure dependencies. The 8 Protocol interfaces in `repositories.py` (1,082 lines) all have concrete implementations. This is textbook Ports & Adapters.

**Contract-driven API design.** The `docs/agentic/contracts/` directory defines explicit contracts for every cross-service boundary (snapshot pull, outbox push, delta sync, curation sync). This prevents Insider Trading between the WordPress plugin and the Python service.

**Sovereign Sync pattern.** The outbox/projector separation (WordPress owns local state; Python service owns recognition state; sync via outbox + snapshot) is a well-chosen architectural pattern that keeps the two systems independently deployable.

### Where the architecture creates smell pressure

**PHP controller layer lacks a service layer.** All domain logic (validation, transaction management, operation queueing) lives directly in REST controllers. This creates Large Class, Long Function, and Duplicated Code smells because each endpoint must inline the same transaction management and coordination logic. Extracting a PHP service layer would resolve H2 and H4 simultaneously.

**Repository as god object.** The Python `ClusterRepository` (1,373 lines) accumulates behavior because the domain model entities are thin Data Classes. Behavior that could live on domain entities migrates to the repository, which becomes the de facto service layer. This is the Feature Envy / Large Class nexus.

**No value objects at boundaries.** The system passes raw primitives (`string`, `int`, `float`) across every boundary. This creates both Primitive Obsession and Shotgun Surgery because format/validation changes propagate to every consumer. The book's Chapter 6 refactorings (Replace Primitive with Object, Introduce Parameter Object) directly address this.

---

## Recommended Refactoring Sequence

Order by dependency chain and risk, following Fowler's advice: refactor in small, tested steps; never refactor on a red bar.

### Phase 1: Value Objects (eliminates H3, H5, M4 partially)

**Effort:** Small per object; mechanical find-replace at boundaries
**Prerequisites:** Green test suite

1. Introduce `CurationState` enum in PHP (`enum CurationState: string`)
2. Introduce `OperationType` enum in PHP
3. Introduce `BoundingBox` value object in both PHP and Python
4. Introduce `TenantId` value object in Python (validation at FastAPI dependency boundary)
5. Introduce `SnapshotVersion` value object in Python (encapsulate conversion)

### Phase 2: Transaction Boilerplate (eliminates H4)

**Effort:** Small; one new method + 10 call-site updates
**Prerequisites:** Phase 1 (so enum types flow through the wrapper cleanly)

1. Extract `run_transactional(callable)` in `ClusterMutationsController`
2. Replace inline transaction blocks with wrapper calls
3. Extend to `ConflictController` if the pattern recurs there

### Phase 3: Repository Split (eliminates H1)

**Effort:** Medium; requires updating Protocol definitions and DI wiring
**Prerequisites:** Green test suite; Phase 1 (value objects clarify method signatures)

1. Identify method groupings from the existing Protocol in `repositories.py`
2. Extract `RepresentativeRepository`, `ClusterQueryRepository`, `ClusterSnapshotRepository`
3. Update FastAPI dependency injection to provide the specific repository each router needs
4. Verify all integration tests pass against the split repositories

### Phase 4: PHP Service Layer (eliminates H2, reduces M1, M3, M5)

**Effort:** Medium-Large; introduces a new architectural layer in PHP
**Prerequisites:** Phase 2 (transaction wrapper exists); Phase 1 (enums in place)

1. Create `ClusterMutationService` with methods for merge, split, reassign, etc.
2. Move domain validation and operation queueing from controllers into the service
3. Controllers become thin: parse request -> call service -> return response
4. Remove `AbstractRecognitionProxyController` inheritance; replace with `ProxyPolicy` composition

### Phase 5: Opportunistic Cleanup

Apply as natural extensions of earlier phases or during feature work:

- Rename `_load_topology_replay` -> `_load_idempotency_cache` (L1)
- Extract `useTabElection()` from `useJobCoordination.ts` (M7)
- Add behavior to `MediaIdentity` domain entity (L3)
- Extract `_resolve_media_from_urls()` in `analyze.py` (L4, M2)
- Consolidate TypeScript type guards (L5)

---

## Cross-Document Overlap Index

This evaluation covers all three stacks. Two companion evaluations provide deeper analysis for specific domains:

- [refactoring-typescript-evaluation.md](refactoring-typescript-evaluation.md) -- TypeScript frontend only (Hickey, "Refactoring TypeScript")
- [refactoring-ui-evaluation.md](refactoring-ui-evaluation.md) -- CSS/SCSS design system only (Wathan/Schoger, "Refactoring UI")

The UI evaluation is orthogonal; it addresses design tokens and visual patterns, not code structure. No duplicate findings exist between this document and the UI evaluation.

The TypeScript evaluation has significant overlap with this document's frontend findings. The table below maps related findings so that refactoring work targets each code area once, not twice.

| This doc                             | TS doc                                                                          | Overlap                                                      | Canonical action                                                                                               |
| ------------------------------------ | ------------------------------------------------------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| H3 (Primitive Obsession, all stacks) | M4 (magic status strings)                                                       | TS-M4 is the TypeScript instance of this cross-stack finding | Fowler H3 owns the cross-stack scope; TS-M4 owns the TypeScript-specific remedy (centralized `as const` enums) |
| M7 (useJobCoordination.ts 220 lines) | H2 (RetentionPage 250+ lines), M3 (useJobProgressStream 165 lines)              | Same smell (Long Function); each names different instances   | Both documents prescribe Extract Function; tackle all instances in one pass                                    |
| L5 (duplicated API type guards)      | L3 (verbose AbortError type guard)                                              | Both address type guard hygiene                              | Consolidate guards (L5) and extract `isAbortError` (TS-L3) in the same cleanup                                 |
| L6 (BulkActionBar 7 props)           | H3 (useClusterSaveAction 13 params), L4 (useClusterConfirmSuggestion 12 params) | Same smell (Long Parameter List); TS finds worse instances   | TS-H3 remedy (Introduce Parameter Object) addresses all three                                                  |

**Refactoring sequence alignment:**

- Fowler Phase 1 (Value Objects) and TS Phase 1 (Centralize Status Enums) target the same primitive-to-typed transition. Execute together; the TypeScript enum work is a subset of the broader value-object introduction.
- Fowler Phase 5 (extract `useTabElection` from `useJobCoordination.ts`) and TS Phase 3 (Extract Presentation Hooks from God Components) both decompose large hooks. Execute together as one "hook extraction" pass.

---

## Checklist

- [ ] Phase 1: Introduce CurationState enum (PHP)
- [ ] Phase 1: Introduce OperationType enum (PHP)
- [ ] Phase 1: Introduce BoundingBox value object (PHP + Python)
- [ ] Phase 1: Introduce TenantId value object (Python)
- [ ] Phase 1: Introduce SnapshotVersion value object (Python)
- [ ] Phase 2: Extract run_transactional() in ClusterMutationsController
- [ ] Phase 2: Replace inline transaction blocks (10 sites)
- [ ] Phase 3: Split cluster_repository.py into 4 focused repositories
- [ ] Phase 3: Update Protocol definitions in repositories.py
- [ ] Phase 3: Update FastAPI dependency injection
- [ ] Phase 4: Create ClusterMutationService (PHP)
- [ ] Phase 4: Move domain logic from controllers to service layer
- [ ] Phase 4: Replace AbstractRecognitionProxyController with ProxyPolicy composition
- [ ] Phase 5: Rename topology_replay functions
- [ ] Phase 5: Extract useTabElection hook
- [ ] Phase 5: Add behavior to MediaIdentity
- [ ] Phase 5: Extract media resolution helpers in analyze.py
- [ ] Phase 5: Consolidate TypeScript type guards
