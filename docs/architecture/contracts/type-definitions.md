# Shared Type Definitions

TypeScript/PHP type alignment documentation for Context Alt Text.

## Overview

This document maps TypeScript interfaces to their PHP equivalents to prevent type drift between frontend and backend. All core data structures are defined via JSON Schemas in `/packages/shared-contracts/schemas/`.

## Type Mapping Reference

### Roster Entry

**JSON Schema**: `schemas/roster-entry.schema.json`

**TypeScript** (`js/admin/types.ts`):

```typescript
export interface RosterEntry {
  remoteId: string | null;
  label: string;
  type: string;
  status: "LOCAL" | "SYNCED" | "CONFLICT";
  updatedAt: string | null;
  metadata: Record<string, unknown>;
  referenceImages: Record<string, unknown>[];
  avatarUrl: string | null;
  referenceImageCount: number;
  avatarId: number | null;
  media?: RosterEntryMedia[];
  mediaCount?: number;
}
```

**PHP** (`src/Roster/Domain/RosterEntry.php`):

```php
/**
 * @phpstan-type RosterEntryArray array{
 *   remoteId: string|null,
 *   label: string,
 *   type: string,
 *   status: 'LOCAL'|'SYNCED'|'CONFLICT',
 *   updatedAt: string|null,
 *   metadata: array<string, mixed>,
 *   referenceImages: array<array<string, mixed>>,
 *   avatarUrl: string|null,
 *   referenceImageCount: int,
 *   avatarId: int|null,
 *   media?: array<RosterEntryMediaArray>,
 *   mediaCount?: int
 * }
 */
class RosterEntry {
    public function __construct(
        public readonly ?string $remoteId,
        public readonly string $label,
        public readonly string $type,
        public readonly string $status,
        public readonly ?string $updatedAt,
        public readonly array $metadata,
        public readonly array $referenceImages,
        public readonly ?string $avatarUrl,
        public readonly int $referenceImageCount,
        public readonly ?int $avatarId,
        public readonly ?array $media = null,
        public readonly ?int $mediaCount = null,
    ) {}
}
```

**Key Alignments**:

- `remoteId`: Nullable string in both
- `status`: Union of 3 literal strings in both
- `metadata`: Untyped object/array in both
- `referenceImageCount`: Always non-negative integer

---

### Recognition Observation

**JSON Schema**: `schemas/recognition-observation.schema.json`

**TypeScript** (`js/admin/types.ts`):

```typescript
export interface RecognitionObservationRecord {
  observationId: string;
  label: string;
  entityType: string;
  confidence: number;
  detectionConfidence?: number | null;
  matchConfidence?: number | null;
  area: number;
  boundingBox: number[];
  status: "matched" | "needs_review";
  source: Record<string, unknown> | null;
  match: {
    isMatch: boolean;
    similarity: number;
    confidence: number;
    threshold: number;
  };
  roster: {
    remoteId: string | null;
    name?: string | null;
    displayName?: string | null;
  } | null;
  candidates: RecognitionObservationCandidate[];
}
```

**PHP** (`src/Recognition/Domain/Observation.php`):

```php
/**
 * @phpstan-type ObservationArray array{
 *   observationId: string,
 *   label: string,
 *   entityType: string,
 *   confidence: float,
 *   detectionConfidence?: float|null,
 *   matchConfidence?: float|null,
 *   area: float,
 *   boundingBox: array<float>,
 *   status: 'matched'|'needs_review',
 *   source: array<string, mixed>|null,
 *   match: array{isMatch: bool, similarity: float, confidence: float, threshold: float},
 *   roster: array{remoteId: string|null, name?: string|null, displayName?: string|null}|null,
 *   candidates: array<CandidateArray>
 * }
 */
```

**Key Alignments**:

- `confidence`: Number/float constrained 0-1 in both
- `boundingBox`: Array of numbers (4 elements: [x, y, width, height])
- `status`: Union of 2 literal strings
- `match`: Nested object with 4 required fields

---

### Recognition Job

**JSON Schema**: `schemas/recognition-job.schema.json`

**TypeScript** (`js/admin/utils/normalization/recognition.ts`):

```typescript
export interface RecognitionJobSummary {
  id: string;
  status: "pending" | "processing" | "complete" | "error";
  attachmentIds: number[];
  createdAt: number;
  updatedAt: number;
}
```

**PHP** (`src/Recognition/Domain/RecognitionJob.php`):

```php
/**
 * @phpstan-type JobSummaryArray array{
 *   id: string,
 *   status: 'pending'|'processing'|'complete'|'error',
 *   attachmentIds: array<int>,
 *   createdAt: int,
 *   updatedAt: int
 * }
 */
```

**Key Alignments**:

- `id`: String (UUID format)
- `status`: Union of 4 literal strings
- `attachmentIds`: Array of positive integers
- Timestamps: Unix timestamps (seconds since epoch)

---

### Coverage Statistics

**JSON Schema**: `schemas/coverage-stats.schema.json`

**TypeScript** (`js/admin/types.ts`):

```typescript
export interface CoverageCard {
  total: number;
  missing: number;
  with_alt: number;
  coverage_percent: number;
  trend_series?: CoverageTrendPoint[];
}

export interface CoverageTrendPoint {
  timestamp: number;
  coverage: number;
  total: number;
  with_alt: number;
  missing: number;
}
```

**PHP** (`src/Dashboard/Domain/CoverageStats.php`):

```php
/**
 * @phpstan-type CoverageStatsArray array{
 *   total: int,
 *   missing: int,
 *   with_alt: int,
 *   coverage_percent: float,
 *   trend_series?: array<TrendPointArray>
 * }
 *
 * @phpstan-type TrendPointArray array{
 *   timestamp: int,
 *   coverage: float,
 *   total: int,
 *   with_alt: int,
 *   missing: int
 * }
 */
```

**Key Alignments**:

- Counts: Non-negative integers
- `coverage_percent`: Float 0-100
- `timestamp`: Milliseconds since epoch (note: PHP often uses seconds)

---

### Workbench Media Item

**JSON Schema**: `schemas/workbench-media-item.schema.json`

**TypeScript** (`js/admin/types.ts`):

```typescript
export interface WorkbenchMediaItem {
  id: string;
  title: string;
  status: "missing" | "draft" | "published";
  thumbnailUrl?: string;
  updatedAt?: string;
  altText?: string | null;
  mimeType?: string | null;
  dimensions?: {
    width: number;
    height: number;
  } | null;
  editUrl?: string | null;
  recognition?: WorkbenchMediaRecognition | null;
}
```

**PHP** (`src/Workbench/Domain/MediaItem.php`):

```php
/**
 * @phpstan-type MediaItemArray array{
 *   id: string,
 *   title: string,
 *   status: 'missing'|'draft'|'published',
 *   thumbnailUrl?: string,
 *   updatedAt?: string,
 *   altText?: string|null,
 *   mimeType?: string|null,
 *   dimensions?: array{width: int, height: int}|null,
 *   editUrl?: string|null,
 *   recognition?: RecognitionArray|null
 * }
 */
```

**Key Alignments**:

- `id`: String representation of attachment ID
- `status`: Union of 3 literal strings
- `dimensions`: Nested object with width/height integers
- Optional fields marked with `?` in both languages

---

## Type Safety Checklist

When adding or modifying types:

- [ ] Update JSON Schema in `/packages/shared-contracts/schemas/`
- [ ] Validate schema with `npm run validate:schemas`
- [ ] Update TypeScript interface in `js/admin/types.ts`
- [ ] Update PHP type annotation in relevant domain class
- [ ] Update this documentation
- [ ] Run contract tests to verify alignment
- [ ] Update API documentation if endpoint changes

## Common Patterns

### Nullable Fields

**TypeScript**: `field: string | null`  
**PHP**: `public readonly ?string $field`  
**JSON Schema**: `"type": ["string", "null"]`

### Union Types (Literal Strings)

**TypeScript**: `status: "pending" | "complete"`  
**PHP**: `status: 'pending'|'complete'` (PHPStan)  
**JSON Schema**: `"enum": ["pending", "complete"]`

### Arrays

**TypeScript**: `ids: number[]`  
**PHP**: `/** @var array<int> */ public readonly array $ids`  
**JSON Schema**: `"type": "array", "items": {"type": "integer"}`

### Nested Objects

**TypeScript**: `dimensions?: { width: number; height: number }`  
**PHP**: `/** @phpstan-type Dimensions array{width: int, height: int} */`  
**JSON Schema**: Use `definitions` and `$ref`

### Timestamps

**Convention**: Use Unix timestamps (seconds since epoch)  
**TypeScript**: `number` (milliseconds for JavaScript dates)  
**PHP**: `int` (seconds for PHP DateTime)  
**Note**: Frontend multiplies by 1000, backend divides by 1000

## Validation

### Runtime Validation

**Frontend** (using Zod):

```typescript
import { z } from "zod";

const RosterEntrySchema = z.object({
  remoteId: z.string().nullable(),
  label: z.string().min(1),
  type: z.enum(["person", "organization", "brand", "other"]),
  status: z.enum(["LOCAL", "SYNCED", "CONFLICT"]),
  // ... rest of fields
});

// Validate API response
const entry = RosterEntrySchema.parse(apiResponse);
```

**Backend** (using JSON Schema validation):

```php
use JsonSchema\Validator;

$validator = new Validator();
$validator->validate(
    $data,
    (object)['$ref' => 'file://' . __DIR__ . '/schemas/roster-entry.schema.json']
);

if (!$validator->isValid()) {
    throw new ValidationException($validator->getErrors());
}
```

## Related Documentation

- **JSON Schemas**: `/packages/shared-contracts/schemas/`
- **Validation Contract**: `/docs/architecture/contracts/validation-logic-contract.md`
- **Sanitization Contract**: `/docs/architecture/contracts/sanitization-patterns-contract.md`
- **API Documentation**: `/docs/api/` (when created)

## Change Log

### 2025-10-18 - Initial Type Definitions

- Created JSON schemas for 5 core data structures
- Documented TypeScript/PHP type mappings
- Established type safety checklist
- Defined common patterns and conventions

### Schemas Created

1. `roster-entry.schema.json` - Roster entry with reference images
2. `recognition-observation.schema.json` - Detection results with matches
3. `recognition-job.schema.json` - Recognition job status
4. `coverage-stats.schema.json` - Alt text coverage statistics
5. `workbench-media-item.schema.json` - Media item with recognition status
