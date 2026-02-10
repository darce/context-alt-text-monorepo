# Branch Audit — XMP Face Metrics Persistence (v4.13.1)

> **Date:** 2026-02-10
> **Task Plan:** `docs/tasks/4.0/4.13.1/wp-image-xmp-face-metrics-task-plan.md`
> **Scope:** 15 new files, 4 modified files, ~1,600 new lines (src + tests + contract)
> **Categories:** ANTIPATTERN · DEAD_CODE · COMPLEXITY · GAP

---

## Summary

| Severity | Count |
|----------|-------|
| **HIGH** | 0 |
| **MEDIUM** | 3 |
| **LOW** | 5 |
| **Total** | **8** |

### Resolution Update (2026-02-10)

- All 8 findings in this audit are now addressed on branch.
- Verification rerun: `composer test`, `composer cs-check`, `npm run typecheck`, `npm run test -- --run`, `npm run lint`, `npm run arch`.

---

## Automated Check Results

| Check | Result |
|-------|--------|
| `composer test` (PHPUnit) | :white_check_mark: 90 tests, 280 assertions |
| `composer cs-check` (PHPCS) | :white_check_mark: |
| `npm run typecheck` | :white_check_mark: |
| `npm run test -- --run` | :white_check_mark: 30 files, 153 tests |
| `npm run lint` | :white_check_mark: |
| `check-architecture-compliance.js` | :white_check_mark: (0 violations) |
| Cyclomatic complexity (radon, grade C+) | N/A — PHP only (no radon equivalent run) |

---

## HIGH Severity

None.

---

## MEDIUM Severity

### M-1 · Integration test does not verify persisted `acx:` metric field values

| | |
|---|---|
| **Files** | `tests/Unit/AttachmentXmpMetricsPersistorTest.php` L68–78, `tests/Unit/XmpImageRegionPacketBuilderTest.php` L46–51 |
| **Category** | GAP |

`testPersistForAttachmentWritesXmpToOriginalOnly` supplies pitch/yaw/roll/det_score/landmark_quality inputs but only asserts `rbX` and `Name` in the output XML. The `acx:Pitch`, `acx:Yaw`, `acx:Roll`, `acx:DetScore`, and `acx:LandmarkQuality` fields are never verified in the round-trip.

`testBuildPacketCreatesValidNamespacesAndFields` checks `Pitch` **exists** (element count = 1) but not its value, and does not assert presence of `Yaw`, `Roll`, `DetScore`, or `LandmarkQuality` at all.

If `format_decimal`, `append_optional_metric`, or the `acx:` namespace registration silently broke, no test would catch it.

### M-2 · `XmpBackfillCommandTest` has no coverage for `--all` / `--limit` flags

| | |
|---|---|
| **Files** | `tests/Unit/XmpBackfillCommandTest.php` |
| **Category** | GAP |

Only two test cases exist: explicit attachment IDs and empty-args error. The `--all` branch (which calls `collect_all_image_attachment_ids()`) and `--limit` parameter are untested.

### M-3 · Test temp files leak to `/tmp/` with no cleanup

| | |
|---|---|
| **Files** | `tests/Unit/AttachmentXmpMetricsPersistorTest.php` L217–225 |
| **Category** | ANTIPATTERN |

`createTempImageFile()` creates files via `tempnam()` + `rename()` in `sys_get_temp_dir()` but there is no `tearDown()` that tracks and removes them. Four temp `.jpg` files accumulate per test run.

---

## LOW Severity

### L-1 · Task plan Functions to Change omits CLI command file and test

| | |
|---|---|
| **Files** | `docs/tasks/4.0/4.13.1/wp-image-xmp-face-metrics-task-plan.md` |
| **Category** | GAP |

`src/cli/class-xmp-backfill-command.php` and `tests/Unit/XmpBackfillCommandTest.php` were implemented as part of the "Stretch Goals" checkbox but are not listed in the Functions to Change table or test inventory. The plan is incomplete for traceability.

### L-2 · Duplicate dependency graph construction (DRY)

| | |
|---|---|
| **Files** | `alt-context.php` L112–120, `src/cli/class-xmp-backfill-command.php` L30–38 |
| **Category** | COMPLEXITY |

The identical `ProxyFaceMetricsSource → XmpImageRegionPacketBuilder → JpegXmpInjector → PngXmpInjector → ImageXmpWriter → AttachmentXmpMetricsPersistor` graph is assembled in both the plugin bootstrap and the CLI command's nullable-constructor fallback. Both sites are effectively stateless so no runtime bug exists, but a shared factory would prevent divergence on future wiring changes.

### L-3 · PNG `extract_packet` does not validate CRC on read

| | |
|---|---|
| **Files** | `src/media/class-png-xmp-injector.php` L24–56 |
| **Category** | GAP |

CRC is computed on write (`build_chunk`) but never verified on read (`extract_packet`). Corrupted PNG chunks would be silently parsed. Consistent with lightweight XMP injector norms — not a correctness issue for well-formed files.

### L-4 · `current_time` test stub ignores `$gmt` parameter

| | |
|---|---|
| **Files** | `tests/stubs/wp.php` L1253–1266 |
| **Category** | ANTIPATTERN |

The `current_time('mysql', ...)` stub always returns GMT regardless of `$gmt` flag. Production code passes `true` so output matches, but the stub is imprecise for `$gmt=false`.

### L-5 · Contract doc frontmatter still `status: draft`

| | |
|---|---|
| **Files** | `docs/agentic/contracts/recognition-media-xmp-mapping.md` L3 |
| **Category** | GAP |

Should be updated to `active` or `accepted` once the implementation is merged.

---

## Sections Reviewed Clean

| Review Guide Section | Verdict |
|---|---|
| §3.1 Correctness — contract alignment | :white_check_mark: Mapping table matches implementation |
| §3.1 Correctness — no unreachable code | :white_check_mark: |
| §3.1 Correctness — no duplicate declarations | :white_check_mark: |
| §3.2 Type Safety | :white_check_mark: Strict types, typed properties, guards throughout |
| §3.3 Architecture Boundaries | :white_check_mark: Media layer in `src/media/`, API in `src/api/`, CLI in `src/cli/` |
| §3.4 Code Duplication — fakes | :white_check_mark: 3 inline fakes co-located in one file, not divergent |
| §3.5 Error Handling — file I/O | :white_check_mark: `file_get_contents`/`file_put_contents` checked, `is_readable`/`is_writable` pre-guards |
| §3.5 Error Handling — `@loadXML` | :white_check_mark: Suppression acceptable; return value checked; `LIBXML_NONET` prevents XXE |
| §3.6 Frontend | N/A — no frontend changes |
| §3.7 PHP/WP — capability checks | :white_check_mark: `current_user_can('manage_options')` in XmpEmbedController |
| §3.7 PHP/WP — nonce handling | :white_check_mark: REST API infrastructure handles nonces |
| §3.7 PHP/WP — superglobal access | :white_check_mark: None in `src/media/` |
| §3.8 Tests — no skipped/empty tests | :white_check_mark: All 11 test methods have assertions |
| §3.8 Tests — dispatch idempotence | :white_check_mark: `testGetJobStatusDispatchesRecognitionCompleteOnlyOncePerJob` |
| §3.9 Documentation — no TODO/FIXME | :white_check_mark: None in `src/media/` |
| §3.9 Documentation — no stale comments | :white_check_mark: |

---

## Recommended Fix Order

### Phase 1 — Before merge
1. **M-1** — Add `acx:` metric value assertions to integration + packet builder tests
2. **M-3** — Add `tearDown()` cleanup for temp files in `AttachmentXmpMetricsPersistorTest`

### Phase 2 — Soon after merge
3. **M-2** — Add `--all` and `--limit` coverage to `XmpBackfillCommandTest`
4. **L-1** — Back-fill CLI command into task plan Functions to Change table

### Phase 3 — Maintenance
5. **L-2** — Extract shared dependency graph factory to eliminate duplicate wiring
6. **L-3** — Consider CRC validation on PNG extract (low priority)
7. **L-4** — Fix `$gmt` param handling in `current_time` test stub
8. **L-5** — Update contract doc status to `active` on merge

---

# Consolidated Checklist

## Phase 1 — Before merge
- [x] **M-1** — Assert `acx:Pitch`, `acx:Yaw`, `acx:Roll`, `acx:DetScore`, `acx:LandmarkQuality` values in `testPersistForAttachmentWritesXmpToOriginalOnly` and element presence in `testBuildPacketCreatesValidNamespacesAndFields`
- [x] **M-3** — Track temp file paths in `AttachmentXmpMetricsPersistorTest` and delete in `tearDown()`

## Phase 2 — Soon after merge
- [x] **M-2** — Add test for `__invoke([], ['all' => true])` and `__invoke([], ['all' => true, 'limit' => '5'])` in `XmpBackfillCommandTest`
- [x] **L-1** — Add `src/cli/class-xmp-backfill-command.php` and `tests/Unit/XmpBackfillCommandTest.php` to task plan Functions to Change

## Phase 3 — Maintenance
- [x] **L-2** — Extract dependency graph factory for XMP persistence wiring
- [x] **L-3** — Add CRC32 validation in `PngXmpInjector::extract_packet()`
- [x] **L-4** — Respect `$gmt` parameter in `current_time` test stub
- [x] **L-5** — Update `recognition-media-xmp-mapping.md` status to `active`

## Success Criteria
- [x] Zero HIGH findings remaining
- [x] `composer test` passes
- [x] `npm run typecheck` passes with zero new errors
- [x] All existing tests continue to pass
- [x] Branch audit re-run shows no regressions
