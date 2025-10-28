# Architecture Contracts Documentation

Human-readable documentation of contracts between frontend (TypeScript) and backend (PHP).

## Purpose

This directory contains **documentation for developers** explaining how shared logic works across the stack. These are narrative documents with code examples, behavior matrices, and testing guidelines.

## Contents

### Validation & Sanitization Contracts

- **`validation-logic-contract.md`** - Shared validation constants and rules

  - Timeout validation (1000-120000ms)
  - URL scheme validation (http/https)
  - Manual testing checklists
  - TypeScript/PHP implementation comparison

- **`sanitization-patterns-contract.md`** - Shared sanitization patterns
  - 7 primitive type sanitization functions
  - TypeScript/PHP behavior matrices
  - 70+ test case examples
  - Usage guidelines

### API Response Samples

- **`dashboard/coverage.json`** - Sample coverage statistics API response
- **`workbench/media.json`** - Sample media listing API response

These samples help developers understand the expected data shapes without running the full application.

### API Contracts (v2 People Labeling)

- **`workbench/recognition-identify.json`** - Face detection & labeling endpoint
  - POST /wp-json/cat/v1/recognition/identify
  - Request/response schemas with examples
  - Cold start, warm start, bulk confirm flows
  - Aligns with CONSOLIDATED_FACE_DETECTION_PLAN.md Section 3.4

### Face Clustering Contracts

- **`clustering-api.md`** - WordPress REST API for face clustering

  - POST /wp-json/cat/v1/recognition/scan - Batch face detection
  - GET /wp-json/cat/v1/clusters - List clusters with pagination
  - GET /wp-json/cat/v1/clusters/{id} - Cluster details with suggestions
  - POST /wp-json/cat/v1/clusters/{id}/confirm - Confirm cluster identity
  - POST /wp-json/cat/v1/clusters/{id}/split - Split cluster

- **`recognition-clustering.md`** - Recognition service clustering endpoints
  - POST /api/v0/cluster - FAISS-backed embedding clustering
  - POST /api/v0/suggest - Roster suggestions for embeddings
  - POST /api/v0/roster/add-embedding - Augment roster with confirmed embeddings

## vs. `/packages/shared-contracts/`

| This Directory                   | packages/shared-contracts/                 |
| -------------------------------- | ------------------------------------------ |
| **Human-readable documentation** | **Machine-readable schemas**               |
| Markdown files with explanations | JSON Schema, OpenAPI specs                 |
| For developers to read           | For code generators to consume             |
| "Here's how validation works"    | "Here's the schema to generate types from" |

## v2 Face Recognition Contracts

### Frontend → WordPress Plugin

**Endpoint:** `POST /wp-json/cat/v1/recognition/identify`

**Request:**

```json
{
  "attachmentId": 123,
  "faces": [
    {
      "bbox": { "x": 0.2, "y": 0.3, "width": 0.15, "height": 0.2 },
      "faceId": "temp-face-1",
      "label": { "newName": "Ana Rodriguez" } // Optional: only when user labels
    }
  ],
  "imageCoordinateSystem": "normalized"
}
```

**Response:**

```json
{
  "faces": [
    {
      "faceId": "temp-face-1",
      "clusterId": "cluster-abc-001",
      "suggestions": [
        {
          "rosterId": "person-ana-001",
          "display": "Ana Rodriguez",
          "score": 0.94
        }
      ],
      "observationId": 456 // Only present if label was provided
    }
  ]
}
```

### WordPress Plugin → Recognition Service

**1. Embeddings Generation**

```
POST /api/v0/embeddings/batch
Request: {images: [base64...], model: "adaface"}
Response: {embeddings: [[0.123, ...], ...]}  // 512-dim vectors
```

**2. FAISS Suggestions**

```
POST /api/v0/suggest
Request: {embeddings: [[...]], topK: 5, threshold: 0.92}
Response: {suggestions: [[{rosterId, display, score}, ...], ...]}
```

**3. Clustering Unknowns**

```
POST /api/v0/cluster-unknowns
Request: {embeddings: [[...]], threshold: 0.6}
Response: {clusterIds: ["cluster-abc-001", "cluster-abc-002", ...]}
```

**4. Roster Sync**

```
POST /api/v0/roster/sync
Request: {personId: "person-ana-001", embedding: [...], displayName: "Ana Rodriguez"}
Response: {success: true, indexUpdated: true}
```

## TypeScript Type Definitions

Frontend types are defined in:

```
apps/wp-context-alt-text/js/types/people-labeling.ts
```

Key types:

- `DetectedFaceFE` - Frontend face with suggestions
- `IdentifyRequest` / `IdentifyResponse` - API contracts
- `PeopleOverlayProps` / `PeopleDrawerProps` / `PeoplePickerProps` - Component interfaces
- `UsePeopleSuggestionsReturn` - Hook interface

## Testing Contract Compliance

### Frontend (TypeScript)

```bash
cd apps/wp-context-alt-text
npm test -- people-labeling.test.ts  # Unit tests for types
npm run build  # Verify types compile
```

### Backend (PHP)

```bash
cd apps/wp-context-alt-text
composer test -- --filter IdentifyControllerTest
phpstan analyze src/Recognition/  # Static analysis
```

### Contract Tests (E2E)

```bash
# Test frontend request matches backend expectation
npm test -- contract-identify.test.ts
```

## Example

```markdown
# In this directory (docs/architecture/contracts/)

validation-logic-contract.md explains:

- Why we use these timeout values
- How TypeScript and PHP implementations differ
- Manual testing checklist for verification

# In packages/shared-contracts/

recognition.schema.json defines:

- Exact shape of recognition API payloads
- Used to generate TypeScript types and PHP DTOs
- Machine-readable, no prose
```

## Related Directories

- **`/packages/shared-contracts/`** - Machine-readable schemas for code generation
- **`/docs/architecture/rules/`** - Architecture rules and guidelines
- **`/docs/architecture/frontend-uml/`** - Component architecture diagrams

## Maintenance

When updating contracts:

1. **Update implementation** (TypeScript/PHP code)
2. **Update this documentation** (explain the change)
3. **Update schemas** in `/packages/shared-contracts/` (if applicable)
4. **Run tests** to verify alignment

## Change Log

- **2025-10-18**: Created validation-logic-contract.md and sanitization-patterns-contract.md
- **2024-Q2**: Added sample API responses (dashboard, workbench)
