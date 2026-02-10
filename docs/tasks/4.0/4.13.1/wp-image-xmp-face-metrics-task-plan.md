# WordPress Image XMP Face Metrics Persistence (v4.13.1)

## Problem Statement

The plugin exposes per-face debug metrics in the workbench UI (`acx-debug-metrics__row`), but those metrics are not persisted into the source image file. We need portable metadata embedded in the original uploaded image so face labels and pose metrics survive outside WordPress. The output must be valid XMP using IPTC ImageRegion plus an `acx` extension namespace, without storing age or gender.

## Workflow Principles

- Persist metadata to the original uploaded file only; do not write to WordPress-generated thumbnails.
- Use one valid XMP packet with two namespaces: `Iptc4xmpExt` and `acx`.
- Use IPTC ImageRegion rectangles with normalized coordinates (`0.0` to `1.0`) so metadata is resolution-independent.
- Exclude age and gender from persisted metadata even if backend debug payload includes them.
- Use direct byte injection for JPEG/PNG in pure PHP with no new Composer dependencies.
- Trigger writes only after recognition data exists; never during upload-time `wp_generate_attachment_metadata`.
- Implement a source strategy interface so XMP persistence can use proxy data now and local sovereign tables later.
- Skip unlabeled identities (do not emit empty `Iptc4xmpExt:Name` values).

## Terminology

- **Face locator**: `(media_id, bbox.x, bbox.y, bbox.width, bbox.height)` tuple used as the per-image identity key.
- **Normalized bbox**: rectangle values converted from pixel coordinates to relative coordinates against original image width/height.
- **XMP packet**: XML payload framed in JPEG APP1 (`http://ns.adobe.com/xap/1.0/\0`) or PNG iTXt (`XML:com.adobe.xmp`) container bytes.
- **Portable identity label**: human-readable value written to `Iptc4xmpExt:Name` (cluster label).
- **Recognition-complete trigger**: plugin action fired after recognition data for one or more attachments is available.

## Current State Analysis

What works:

- The backend already exposes face bbox and debug metrics through `GET /recognition/media/identities?include_debug=true`.
- WordPress-side `MediaIdentitiesController` already forwards `include_debug` and returns grouped identities by media ID.
- Debug metric fields already include pose, detection score, and landmark quality in UI payloads.

What is missing:

- No plugin hook currently writes XMP into attachment binaries.
- Upload-time metadata hooks fire before recognition output exists for most workflows.
- No JPEG APP1 XMP parser/writer exists in the plugin.
- No PNG iTXt XMP parser/writer exists in the plugin.
- No mapping layer exists to convert backend face payloads into IPTC ImageRegion + `acx` fields.
- No contract doc currently freezes the plugin-side XMP field mapping.
- No provider abstraction exists to switch from proxy-backed face reads to local sovereign table reads.

## Proposed Solution

Add a dedicated media metadata subsystem that runs after recognition data exists, not at upload time. The subsystem is invoked by a post-recognition trigger (`acx_recognition_complete`) and also exposed through explicit embed/backfill operations for already-analyzed attachments. It resolves the original file path via `get_attached_file()`, obtains original dimensions from `wp_get_attachment_metadata()`, fetches face records through a pluggable provider strategy, maps them into IPTC ImageRegion entries, merges/creates one XMP packet, and writes it back to original JPEG/PNG bytes only.

Scope decisions:

1. v4.13.1 persists `Pitch`, `Yaw`, `Roll`, `DetScore`, and `LandmarkQuality` only.
2. `match_similarity` and `similarity_threshold` are intentionally omitted in v4.13.1 and tracked as follow-up.
3. If proxy/backend data is unavailable, embed operation fails gracefully and can be retried with explicit action or backfill.
4. v4.13.1 uses proxy-backed face sourcing by default; local projection source is the planned sovereign follow-on.

## Patterns to Follow

### Pattern A: Face Metrics -> XMP Region Mapping (Label Guard + WP Dimension Source)

```php
<?php
declare(strict_types=1);

/**
 * @param array<string,mixed> $identity
 * @return array<string,mixed>|null
 */
private function map_identity_to_xmp_region(array $identity, int $attachment_id): ?array {
    $label = trim((string) ($identity['cluster_label'] ?? ''));
    if ('' === $label) {
        // Skip unlabeled faces; do not emit empty Iptc4xmpExt:Name elements.
        return null;
    }

    // Source original image dimensions from WordPress attachment metadata (not backend payload).
    $metadata = wp_get_attachment_metadata($attachment_id, true);
    $image_width = (int) ($metadata['width'] ?? 0);
    $image_height = (int) ($metadata['height'] ?? 0);
    if ($image_width <= 0 || $image_height <= 0) {
        return null;
    }

    $bbox = (array) ($identity['bbox'] ?? array());
    $x = (float) ($bbox['x'] ?? 0.0);
    $y = (float) ($bbox['y'] ?? 0.0);
    $w = (float) ($bbox['width'] ?? 0.0);
    $h = (float) ($bbox['height'] ?? 0.0);

    $metrics = (array) ($identity['debug_metrics'] ?? array());
    $pose = (array) ($metrics['pose'] ?? array());

    return array(
        'name' => $label,
        // IPTC rectangle uses center point for rbX/rbY (not top-left origin).
        'rbX' => round(($x + ($w / 2.0)) / (float) $image_width, 6),
        'rbY' => round(($y + ($h / 2.0)) / (float) $image_height, 6),
        'rbW' => round($w / (float) $image_width, 6),
        'rbH' => round($h / (float) $image_height, 6),
        'acx_pitch' => (float) ($pose['pitch'] ?? 0.0),
        'acx_yaw' => (float) ($pose['yaw'] ?? 0.0),
        'acx_roll' => (float) ($pose['roll'] ?? 0.0),
        'acx_det_score' => (float) ($metrics['det_score'] ?? 0.0),
        'acx_landmark_quality' => (float) ($metrics['landmark_quality'] ?? 0.0),
        // match_similarity intentionally omitted in v4.13.1 scope.
    );
}
```

### Pattern B: Provider Strategy (Proxy Now, Local Projection Later)

```php
<?php
declare(strict_types=1);

interface FaceMetricsSourceInterface {
    /**
     * @return array<int,array<string,mixed>>
     */
    public function get_identities_for_attachment(int $attachment_id): array;
}

final class ProxyFaceMetricsSource implements FaceMetricsSourceInterface {
    // Uses recognition proxy endpoint for v4.13.1.
}

final class LocalProjectionFaceMetricsSource implements FaceMetricsSourceInterface {
    // Future sovereign path: reads wp_acx_identity_members/wp_acx_clusters.
}
```

### Pattern C: Single-Packet XMP with Two Namespaces

```php
<?php
declare(strict_types=1);

$xmp = new DOMDocument('1.0', 'UTF-8');
$xmp->formatOutput = false;

$xmpmeta = $xmp->createElementNS('adobe:ns:meta/', 'x:xmpmeta');
$rdf = $xmp->createElementNS('http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'rdf:RDF');
$desc = $xmp->createElementNS('http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'rdf:Description');
$desc->setAttribute('xmlns:Iptc4xmpExt', 'http://iptc.org/std/Iptc4xmpExt/2008-02-29/');
$desc->setAttribute('xmlns:acx', 'http://alt-context.dev/ns/1.0/');

// Build Iptc4xmpExt:ImageRegion/rdf:Bag/rdf:li entries here.

$rdf->appendChild($desc);
$xmpmeta->appendChild($rdf);
$xmp->appendChild($xmpmeta);
```

### Pattern D: JPEG APP1 XMP Replace-or-Insert

```php
<?php
declare(strict_types=1);

// 1) Scan JPEG markers for APP1 segment with XMP header bytes.
// 2) If found, replace that segment payload.
// 3) If not found, insert new APP1 XMP segment after SOI/APP0 block.
// 4) Recompute APP1 length field (big-endian, includes 2-byte length field).
```

### Pattern E: PNG iTXt XMP Replace-or-Insert

```php
<?php
declare(strict_types=1);

// 1) Parse PNG chunks.
// 2) Locate iTXt chunk with keyword "XML:com.adobe.xmp".
// 3) Replace text payload or insert new iTXt chunk before IEND.
// 4) Recompute chunk length and CRC32 for modified/new chunk.
```

### Pattern F: Post-Recognition Trigger (Not Upload-Time Hook)

```php
<?php
declare(strict_types=1);

add_action('acx_recognition_complete', array($this, 'persist_for_attachment'), 10, 1);

public function persist_for_attachment(int $attachment_id): void {
    $original_path = get_attached_file($attachment_id, true);
    if (!is_string($original_path) || '' === $original_path) {
        return;
    }

    $this->xmp_writer->write_for_attachment($attachment_id, $original_path);
}

/**
 * Shared entrypoint for explicit REST/CLI backfill operations.
 *
 * @param int[] $attachment_ids
 * @return array{processed:int, skipped:int, failed:int}
 */
public function embed_for_media_ids(array $attachment_ids): array {
    // Reuse the same write path as recognition-complete action.
    return $this->batch_embed_runner->run($attachment_ids);
}
```

### Pattern G: Trigger Dispatch from Analysis Job Completion

```php
<?php
declare(strict_types=1);

// In AnalysisJobsController, emit once when job status transitions to completed.
private function maybe_dispatch_recognition_complete(string $job_id, array $job_data): void {
    $status = (string) ($job_data['status'] ?? '');
    if ('completed' !== $status || $this->has_emitted_completion($job_id)) {
        return;
    }

    $media_ids = array_map('absint', (array) ($job_data['media_ids'] ?? array()));
    foreach ($media_ids as $attachment_id) {
        if ($attachment_id > 0) {
            do_action('acx_recognition_complete', $attachment_id, $job_id);
        }
    }

    $this->mark_completion_emitted($job_id);
}
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `apps/prototype-wp-alt-context/alt-context.php` | 96 | Extend `alt_context()` bootstrap factory to wire XMP services and trigger dispatching dependencies. |
| `apps/prototype-wp-alt-context/src/class-alt-context.php` | 31 | Add XMP persistence service dependency and invoke its `init()` from plugin initialization. |
| `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php` | 128 | Dispatch `do_action('acx_recognition_complete', $attachment_id, $job_id)` once when recognition job reaches completed state and media IDs are available. |
| `apps/prototype-wp-alt-context/src/media/class-attachment-xmp-metrics-persistor.php` | new | Register post-recognition action (`acx_recognition_complete`) and explicit embed entrypoint; do not rely on upload-time metadata hook. |
| `apps/prototype-wp-alt-context/src/media/interface-face-metrics-source.php` | new | Define source strategy contract for face metrics retrieval. |
| `apps/prototype-wp-alt-context/src/media/class-proxy-face-metrics-source.php` | new | Fetch per-attachment identities with `include_debug=true` from proxy endpoint for v4.13.1. |
| `apps/prototype-wp-alt-context/src/media/class-local-projection-face-metrics-source.php` | new | Add sovereign-ready local provider implementation target (activated once local tables are available). |
| `apps/prototype-wp-alt-context/src/api/class-api.php` | 75 | Register XMP embed route/controller wiring for explicit user-triggered embedding. |
| `apps/prototype-wp-alt-context/src/api/class-xmp-embed-controller.php` | new | Add explicit user-triggered embed endpoint for analyzed attachments. |
| `apps/prototype-wp-alt-context/src/media/class-xmp-image-region-packet-builder.php` | new | Build or merge valid XMP XML packet with `Iptc4xmpExt` and `acx` namespaces. |
| `apps/prototype-wp-alt-context/src/media/class-jpeg-xmp-injector.php` | new | Implement APP1 XMP detection and replace/insert logic for JPEG bytes. |
| `apps/prototype-wp-alt-context/src/media/class-png-xmp-injector.php` | new | Implement iTXt XMP detection and replace/insert logic for PNG bytes. |
| `apps/prototype-wp-alt-context/src/media/class-image-xmp-writer.php` | new | Orchestrate MIME detection, packet creation, binary rewrite, and file persistence safeguards. |
| `apps/prototype-wp-alt-context/tests/Unit/AttachmentXmpMetricsPersistorTest.php` | new | Verify original-only hook behavior, no thumbnail writes, and graceful no-op on missing data. |
| `apps/prototype-wp-alt-context/tests/Unit/XmpImageRegionPacketBuilderTest.php` | new | Verify XML validity, namespace presence, one packet rule, and exclusion of age/gender fields. |
| `apps/prototype-wp-alt-context/tests/Unit/JpegXmpInjectorTest.php` | new | Verify APP1 replacement/insertion and non-XMP APP segments remain intact. |
| `apps/prototype-wp-alt-context/tests/Unit/PngXmpInjectorTest.php` | new | Verify iTXt replacement/insertion and CRC correctness. |
| `docs/agentic/contracts/recognition-media-xmp-mapping.md` | new | Document face payload to XMP field mapping and normalized bbox semantics. |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/api/class-media-identities-controller.php` | Existing plugin endpoint proxy used as source shape for per-face debug metrics. |
| `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php` | Recognition job lifecycle surface where post-recognition trigger integration points are coordinated. |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/stores.py` | Current backend source of `debug_metrics` fields (`pose`, `det_score`, `landmark_quality`, plus age/gender to ignore). |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/DebugMetricsPanel.tsx` | Existing UI source showing currently exposed metrics targeted for file-level persistence. |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/identity.ts` | Type definition for debug metrics and bbox fields consumed by UI and mapping docs. |
| `apps/prototype-wp-alt-context/tests/stubs/wp.php` | WordPress stubs used by unit tests (`add_action`, `apply_filters`, `get_attached_file`, `wp_get_attachment_metadata`, post meta helpers). |
| `docs/tasks/4.0/4.13.1/wp-sovereign-phase1-local-projection-task-plan.md` | Follow-on source transition from proxy provider to local projection provider. |
| `docs/tasks/4.0/4.13.1/wp-plugin-portable-packaging-plan.md` | Packaging baseline this work must remain compatible with (standalone plugin ZIP constraints). |

---

# Consolidated Checklist

## Completed

- [x] Confirm existing debug metric availability and payload shape in plugin and backend.
- [x] Confirm current plugin has no XMP write path and no `wp_generate_attachment_metadata` persistence hook.
- [x] Confirm upload-time metadata hook timing is incompatible with recognition-result-dependent XMP embedding.

## Phase 0: Scaffolding

- [x] Add media metadata persistence class scaffolds with typed method signatures and docblocks.
- [x] Add XMP packet builder and binary injector scaffolds (`JPEG`, `PNG`) with TODO method bodies.
- [x] Add unit test scaffolds for hook orchestration, XML packet generation, and byte-level injectors.
- [x] Add contract scaffold `docs/agentic/contracts/recognition-media-xmp-mapping.md`.
- [x] Verify scaffolds invoke cleanly in existing gates.

## Phase 1: Face Mapping and XMP Packet Model

- [x] Implement attachment-scoped face payload retrieval (`include_debug=true`) for post-recognition invocation flow.
- [x] Implement face metrics source strategy interface with proxy provider now and local provider seam for sovereign migration.
- [x] Map per-face metrics to XMP fields: `Pitch`, `Yaw`, `Roll`, `DetScore`, `LandmarkQuality`.
- [x] Resolve original image dimensions from `wp_get_attachment_metadata($attachment_id)['width'/'height']`.
- [x] Normalize bbox values relative to original image dimensions and compute stable per-face locator key.
- [x] Build valid single-packet XMP with `x:xmpmeta`, `rdf:RDF`, `rdf:Description`.
- [x] Ensure exactly two namespaces are declared and used: `Iptc4xmpExt`, `acx`.
- [x] Encode IPTC ImageRegion bag entries with rectangle boundary (`rbShape`, `rbX`, `rbY`, `rbW`, `rbH`, `rbUnit`) using IPTC center-point semantics for `rbX`/`rbY`.
- [x] Write `Iptc4xmpExt:Name` from human label and skip entries with unusable labels.
- [x] Ensure idempotent merge behavior for repeated writes on same face locator.
- [x] Explicitly exclude age/gender from persistence path.
- [x] Document conscious omission of `match_similarity` / `similarity_threshold` from persisted XMP fields.

## Phase 2: Binary Injection and Post-Recognition Trigger Integration

- [x] Implement JPEG APP1 XMP segment detection, replace, and insert from scratch when absent.
- [x] Implement PNG iTXt XMP chunk detection, replace, and insert before `IEND` when absent.
- [x] Preserve non-XMP metadata blocks/chunks and fail safely on malformed binaries.
- [x] Skip unsupported MIME types without interrupting embed operation flow.
- [x] Register post-recognition action handler (`acx_recognition_complete`) for automatic embedding when data exists.
- [x] Emit `acx_recognition_complete` from analysis job completion path in `class-analysis-jobs-controller.php` with attachment IDs.
- [x] Add single-fire guard so completion dispatch is emitted once per job (safe for polling/retry flows).
- [x] Add explicit user-triggered embed flow for analyzed attachments (REST action and/or admin workflow).
- [x] Add batch/backfill operation for already-analyzed attachments.
- [x] Resolve original file path with `get_attached_file($attachment_id, true)` and write original only.
- [x] Ensure generated image sizes are never modified.
- [x] Add safe logging/telemetry path for write failures without breaking upload flow.

## Phase 3: Tests

- [x] Unit test XML output validity and namespace correctness against sample schema.
- [x] Unit test JPEG byte rewrite using fixture file with and without existing XMP APP1.
- [x] Unit test PNG byte rewrite using fixture file with and without existing XMP iTXt.
- [x] Unit test post-recognition trigger path (not upload-time hook) and verify only original file write is attempted.
- [x] Unit test `class-analysis-jobs-controller.php` dispatches `acx_recognition_complete` with expected attachment IDs on completed jobs.
- [x] Unit test completion dispatch idempotence (repeated completed polls do not emit duplicate actions).
- [x] Unit test unlabeled identity guard (`cluster_label` empty/null skips region write).
- [x] Unit test dimension sourcing from `wp_get_attachment_metadata()` and normalized coordinate computation.
- [x] Add integration-style test that reads back packet and verifies persisted `Name`, bbox, and `acx` metric fields.

## Stretch Goals

- [x] Add WP-CLI backfill command for embedding XMP on existing attachments.
- [x] Add admin diagnostic summary for last XMP persistence result per attachment.

## Success Criteria

- [x] Original uploaded JPEG/PNG files contain one valid XMP packet with IPTC ImageRegion plus `acx` namespace fields.
- [x] Persisted face entries include human label and normalized rectangle coordinates.
- [x] Persisted metric fields include `Pitch`, `Yaw`, `Roll`, `DetScore`, and `LandmarkQuality` only.
- [x] Age/gender are not written anywhere in XMP output.
- [x] WordPress-generated thumbnails remain untouched.
- [x] Embedding is triggered post-recognition (or via explicit/backfill operation), never at upload-time metadata generation.
