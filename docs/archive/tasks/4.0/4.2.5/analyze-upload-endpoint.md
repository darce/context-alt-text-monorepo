# Task: `/analyze/upload` Endpoint for Direct Image Upload

**Status**: Future Enhancement  
**Priority**: Low  
**Sprint**: 4.2.5+

## Overview

Add an optional `/analyze/upload` endpoint that accepts image bytes directly via multipart upload, enabling API use cases beyond WordPress integration.

## Current State (v4.2.4)

The `/analyze` endpoint is optimized for WordPress:

```json
POST /recognition/analyze
{
  "tenant_id": "uuid",
  "media_items": [
    {"media_id": 123, "media_url": "http://wp-site/uploads/image.jpg"}
  ]
}
```

- WordPress plugin sends media items with URLs
- Service fetches images from URLs via HTTP
- Faces are detected and stored with WordPress `media_id`

## Proposed Enhancement

### New Endpoint: `POST /analyze/upload`

Accept direct image uploads via multipart form data:

```http
POST /recognition/analyze/upload
Content-Type: multipart/form-data

tenant_id: "uuid"
files: [image1.jpg, image2.jpg]
```

### Response

```json
{
  "id": "job-uuid",
  "type": "analyze",
  "status": "completed",
  "progress": {"completed": 2, "total": 2}
}
```

### Implementation Notes

1. **Detector already supports bytes**: `InsightFaceFaceDetector.detect()` handles both URLs and raw bytes
2. **Media ID generation**: For uploads, use hash of image bytes as `media_id`
3. **File validation**: Accept JPEG, PNG, WebP; reject files > 10MB
4. **Batch limits**: Max 50 images per request

### Architecture

```text
/analyze/upload (multipart)
        │
        ▼
┌─────────────────────────────────────┐
│  ScanService.analyze_media()        │
│  media_items = [(hash, bytes), ...] │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│  InsightFaceFaceDetector.detect()   │
│  - bytes → detect directly          │
│  - Returns FaceDetection[]          │
└─────────────────────────────────────┘
```

## Use Cases

1. **Testing/Development**: Upload test images without running WordPress
2. **Standalone API**: Use recognition service without WordPress
3. **Batch Processing**: Upload images from external sources

## Dependencies

- FastAPI multipart handling (already available)
- No new packages required

## Acceptance Criteria

- [ ] `POST /analyze/upload` accepts multipart form with images
- [ ] Generates stable `media_id` from image hash
- [ ] Returns job status matching existing `/analyze` contract
- [ ] Unit tests for upload parsing and validation
- [ ] Integration test with real images
- [ ] API documentation updated

## Decision

**Defer to 4.2.5+**: WordPress use case is primary focus. The current `/analyze` endpoint with URL fetching covers the core requirement. Add upload support when a concrete use case emerges.
