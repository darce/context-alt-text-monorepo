# WordPress Backend Integration Contract

**Version:** 1.0  
**Last Updated:** 2025-11-01  
**Audience:** WordPress plugin developers integrating with the recognition backend service

---

## Overview

This document describes the REST API contract between the WordPress Context Alt Text plugin and the Python recognition backend service for progressive learning and roster management.

The backend service provides face recognition and roster management capabilities. WordPress acts as the frontend, allowing users to confirm identities and manage roster entries through the WordPress admin interface.

### Key Concepts

- **Progressive Learning**: Each time a user confirms a face identity in WordPress, the backend adds that embedding to the roster entry and recomputes the aggregate embedding
- **Roster Entry**: A person or brand with one or more face embeddings
- **Reference Embeddings**: Initial curated embeddings from onboarding photos
- **Augmented Embeddings**: Embeddings collected progressively as users confirm identities
- **Aggregate Embedding**: Weighted average of reference and augmented embeddings used for matching
- **Observation ID**: Unique identifier for a detected face in a specific image (prevents duplicate confirmations)

---

## Authentication

**Current:** None (service runs in trusted network environment)  
**Future:** Bearer token authentication will be added for production deployments

---

## Progressive Learning Workflow

### 1. User Confirms Identity in WordPress

When a user confirms that a detected face belongs to a known person:

```
WordPress                          Backend Service
   |                                      |
   |--POST /api/v0/roster/{id}/augment-->|
   |  {observation_id, embedding, ...}   |
   |                                      |
   |<--200 OK {success, roster_entry}----|
   |                                      |
   |                    Background: Aggregate recomputation
   |                    Background: FAISS index reload (30s debounce)
```

### 2. Request Format

**Endpoint:** `POST /api/v0/roster/{unique_id}/augment`

**Path Parameters:**

- `unique_id` (string): Roster entry UUID

**Request Body:**

```json
{
  "observation_id": "550e8400-e29b-41d4-a716-446655440000",
  "embedding": [0.1234, -0.5678, ...],
  "source": "wordpress_confirm",
  "quality_tier": "medium",
  "attachment_id": 12345,
  "bbox": [100, 150, 250, 300],
  "confidence": 0.87,
  "idempotency_key": "wp_confirm_12345_550e8400"
}
```

**Field Descriptions:**

| Field             | Type          | Required | Description                                                     |
| ----------------- | ------------- | -------- | --------------------------------------------------------------- |
| `observation_id`  | string (UUID) | ✅ Yes   | Unique ID for this detected face instance (prevents duplicates) |
| `embedding`       | float[]       | ✅ Yes   | 512-dimensional face embedding vector                           |
| `source`          | string        | ✅ Yes   | Source system (use "wordpress_confirm")                         |
| `quality_tier`    | string        | No       | Quality assessment: "low", "medium", "high" (default: "medium") |
| `attachment_id`   | integer       | No       | WordPress attachment ID for the source image                    |
| `bbox`            | float[4]      | No       | Bounding box [x, y, width, height] in pixels                    |
| `confidence`      | float         | No       | Detection confidence score (0.0-1.0)                            |
| `idempotency_key` | string        | No       | Custom idempotency key (auto-generated if omitted)              |

**Response (200 OK):**

```json
{
  "success": true,
  "roster_entry": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "label": "john-doe",
    "display_name": "John Doe",
    "aggregate_embedding": [0.1234, ...],
    "metadata": {
      "augmented_embeddings": [
        {
          "observation_id": "550e8400-...",
          "embedding": [0.1234, ...],
          "source": "wordpress_confirm",
          "quality_tier": "medium",
          "timestamp": "2025-11-01T12:34:56Z"
        }
      ]
    },
    "created_at": "2025-10-15T10:00:00Z",
    "updated_at": "2025-11-01T12:34:56Z"
  },
  "index_reloaded": true,
  "idempotency_key": "wp_confirm_12345_550e8400"
}
```

### 3. curl Example

```bash
# Confirm identity for a detected face
curl -X POST http://localhost:8000/api/v0/roster/550e8400-e29b-41d4-a716-446655440000/augment \
  -H "Content-Type: application/json" \
  -d '{
    "observation_id": "face-123-img-456",
    "embedding": [0.1234, -0.5678, 0.9012, ...],
    "source": "wordpress_confirm",
    "quality_tier": "high",
    "attachment_id": 12345,
    "bbox": [100, 150, 250, 300],
    "confidence": 0.92
  }'
```

---

## Idempotency

### Why Idempotency Matters

Network failures, timeouts, or user retries can cause WordPress to send the same confirmation multiple times. Idempotency ensures duplicate requests don't create duplicate embeddings.

### Two Levels of Protection

1. **Observation ID Deduplication** (Always Active)

   - The backend checks if `observation_id` already exists for this roster entry
   - Returns `409 Conflict` if duplicate is detected
   - WordPress should treat 409 as success (embedding already recorded)

2. **Idempotency Keys** (Optional, Recommended)
   - Include `idempotency_key` in request body
   - Backend caches successful responses for 10 minutes
   - Identical requests return cached response without processing
   - Useful for handling network retries transparently

### Implementation Pattern

```php
// WordPress plugin example
function confirm_face_identity($roster_id, $observation_id, $embedding, $metadata) {
    // Generate stable idempotency key
    $idempotency_key = "wp_confirm_{$metadata['attachment_id']}_{$observation_id}";

    $payload = [
        'observation_id' => $observation_id,
        'embedding' => $embedding,
        'source' => 'wordpress_confirm',
        'quality_tier' => $metadata['quality_tier'] ?? 'medium',
        'attachment_id' => $metadata['attachment_id'],
        'bbox' => $metadata['bbox'] ?? null,
        'confidence' => $metadata['confidence'] ?? null,
        'idempotency_key' => $idempotency_key,
    ];

    $response = wp_remote_post(
        "http://backend:8000/api/v0/roster/{$roster_id}/augment",
        [
            'headers' => ['Content-Type' => 'application/json'],
            'body' => json_encode($payload),
            'timeout' => 15,
        ]
    );

    $status_code = wp_remote_retrieve_response_code($response);

    // Handle success and duplicate as success
    if ($status_code === 200 || $status_code === 409) {
        return true;
    }

    // Handle errors
    $body = json_decode(wp_remote_retrieve_body($response), true);
    error_log("Augment failed: " . print_r($body, true));
    return false;
}
```

---

## ETag Caching for Roster Sync

### Efficient Polling with Conditional Requests

WordPress periodically syncs the roster to display in the admin interface. ETag caching prevents unnecessary data transfer when the roster hasn't changed.

### How It Works

```
WordPress                          Backend Service
   |                                      |
   |--GET /api/v0/roster ---------------->|
   |                                      |
   |<--200 OK + ETag: "abc123" -----------|
   |   [roster entries]                   |
   |                                      |
   | (cache ETag locally)                 |
   |                                      |
   | (30 seconds later)                   |
   |--GET /api/v0/roster ---------------->|
   |  If-None-Match: "abc123"             |
   |                                      |
   |<--304 Not Modified ------------------|
   |   (no body, roster unchanged)        |
```

### Request Format

**Endpoint:** `GET /api/v0/roster`

**Query Parameters:**

- `model` (string, optional): Model identifier (default: "insightface_w600k")
- `include_embeddings` (boolean, optional): Include full embedding vectors (default: false)
- `page` (integer, optional): Page number for pagination (default: 1)
- `page_size` (integer, optional): Items per page, max 200 (default: 50)

**Headers:**

- `If-None-Match` (string, optional): Previous ETag value

**Response (200 OK - Data Changed):**

```json
{
  "entries": [
    {
      "id": "550e8400-...",
      "label": "john-doe",
      "display_name": "John Doe",
      "type": "person",
      "metadata": {...},
      "created_at": "2025-10-15T10:00:00Z",
      "updated_at": "2025-11-01T12:34:56Z"
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 50,
    "total_entries": 150,
    "total_pages": 3
  }
}
```

**Headers:**

- `ETag: "def456"` (new ETag value)

**Response (304 Not Modified - Data Unchanged):**

- Status: `304 Not Modified`
- Headers: `ETag: "abc123"`
- Body: Empty

### curl Examples

```bash
# Initial request (no ETag)
curl -i http://localhost:8000/api/v0/roster
# Response includes: ETag: "abc123"

# Subsequent request with ETag
curl -i http://localhost:8000/api/v0/roster \
  -H "If-None-Match: abc123"
# Response: 304 Not Modified (if unchanged)

# With pagination
curl http://localhost:8000/api/v0/roster?page=2&page_size=25

# Include embeddings (for local search)
curl "http://localhost:8000/api/v0/roster?include_embeddings=true"
```

### WordPress Implementation

```php
// WordPress plugin example
function sync_roster_from_backend() {
    $cached_etag = get_option('roster_sync_etag', '');
    $headers = ['Content-Type' => 'application/json'];

    if ($cached_etag) {
        $headers['If-None-Match'] = $cached_etag;
    }

    $response = wp_remote_get(
        'http://backend:8000/api/v0/roster',
        ['headers' => $headers, 'timeout' => 30]
    );

    $status_code = wp_remote_retrieve_response_code($response);

    if ($status_code === 304) {
        // Roster unchanged, use cached data
        return get_option('roster_cache', []);
    }

    if ($status_code === 200) {
        $body = json_decode(wp_remote_retrieve_body($response), true);
        $entries = $body['entries'] ?? [];

        // Extract and cache new ETag
        $headers = wp_remote_retrieve_headers($response);
        $new_etag = $headers['etag'] ?? $headers['ETag'] ?? '';

        if ($new_etag) {
            // Strip quotes if present
            $new_etag = trim($new_etag, '"');
            update_option('roster_sync_etag', $new_etag);
        }

        // Cache roster data
        update_option('roster_cache', $entries);
        return $entries;
    }

    // Error handling
    error_log("Roster sync failed: HTTP $status_code");
    return get_option('roster_cache', []);
}
```

---

## Service Health Monitoring

### Endpoint: GET /api/v0/service/info

WordPress can query this endpoint to display service health and roster statistics in the admin dashboard.

**Request:**

```bash
curl http://localhost:8000/api/v0/service/info
```

**Response:**

```json
{
  "status": "ok",
  "data": {
    "model": {
      "name": "insightface_w600k",
      "device": "cuda",
      "providers": ["CUDAExecutionProvider"]
    },
    "recognition": {
      "default_threshold": 0.45,
      "max_faces_per_image": 20,
      "embedding_dimension": 512
    },
    "roster_stats": {
      "entry_count": 150,
      "reference_embeddings": 150,
      "augmented_embeddings": 337,
      "total_embeddings": 487,
      "etag": "sha256:abc123...",
      "last_updated": "2025-11-01T12:35:00Z"
    },
    "faiss_index_stats": {
      "total_vectors": 487,
      "dimension": 512,
      "index_type": "Flat",
      "last_reload": "2025-11-01T12:35:15Z",
      "last_reload_duration_ms": 245.5
    },
    "embedding_router": {
      "auto_reload": true,
      "reload_interval_seconds": 30,
      "embeddings_source": "database",
      "loaded_embeddings": 487
    }
  }
}
```

### WordPress Dashboard Integration

```php
function display_recognition_service_health() {
    $response = wp_remote_get(
        'http://backend:8000/api/v0/service/info',
        ['timeout' => 5]
    );

    if (is_wp_error($response)) {
        echo '<div class="notice notice-error">
            <p>Recognition service: Unavailable</p>
        </div>';
        return;
    }

    $body = json_decode(wp_remote_retrieve_body($response), true);
    $data = $body['data'] ?? [];
    $roster_stats = $data['roster_stats'] ?? [];

    $entry_count = $roster_stats['entry_count'] ?? 0;
    $total_embeddings = $roster_stats['total_embeddings'] ?? 0;
    $augmented = $roster_stats['augmented_embeddings'] ?? 0;

    echo '<div class="wrap">';
    echo '<h2>Face Recognition Service</h2>';
    echo '<table class="widefat">';
    echo '<tr><td>Status</td><td>✅ Online</td></tr>';
    echo "<tr><td>Roster Entries</td><td>{$entry_count} people/brands</td></tr>";
    echo "<tr><td>Total Embeddings</td><td>{$total_embeddings}</td></tr>";
    echo "<tr><td>Progressive Learning</td><td>{$augmented} augmented embeddings</td></tr>";
    echo '</table>';
    echo '</div>';
}
```

---

## Error Handling

### HTTP Status Codes

| Status | Meaning                       | WordPress Action                    |
| ------ | ----------------------------- | ----------------------------------- |
| 200    | Success                       | Process response                    |
| 304    | Not Modified (ETag match)     | Use cached data                     |
| 400    | Bad Request (invalid payload) | Log error, show admin notice        |
| 404    | Roster entry not found        | Log error, refresh roster cache     |
| 409    | Duplicate observation         | Treat as success (already recorded) |
| 422    | Validation error              | Log error, check embedding format   |
| 500    | Internal server error         | Log error, queue for retry          |
| 503    | Service unavailable           | Queue request, retry later          |

### Retry Strategy

```php
function augment_with_retry($roster_id, $payload, $max_retries = 3) {
    $attempt = 0;

    while ($attempt < $max_retries) {
        $response = wp_remote_post(
            "http://backend:8000/api/v0/roster/{$roster_id}/augment",
            [
                'headers' => ['Content-Type' => 'application/json'],
                'body' => json_encode($payload),
                'timeout' => 15,
            ]
        );

        $status_code = wp_remote_retrieve_response_code($response);

        // Success or duplicate = done
        if ($status_code === 200 || $status_code === 409) {
            return ['success' => true, 'response' => $response];
        }

        // Client errors (4xx except 409) = don't retry
        if ($status_code >= 400 && $status_code < 500 && $status_code !== 409) {
            $body = wp_remote_retrieve_body($response);
            error_log("Augment failed with client error: $status_code $body");
            return ['success' => false, 'error' => 'client_error', 'response' => $response];
        }

        // Server errors (5xx) or network errors = retry with backoff
        $attempt++;
        if ($attempt < $max_retries) {
            $backoff = pow(2, $attempt); // 2s, 4s, 8s
            sleep($backoff);
        }
    }

    return ['success' => false, 'error' => 'max_retries_exceeded'];
}
```

### Error Response Format

```json
{
  "detail": "Observation '550e8400-...' already synced to roster entry 'john-doe'"
}
```

or

```json
{
  "detail": {
    "code": "validation_error",
    "field": "embedding",
    "message": "Expected 512-dimensional vector, got 128"
  }
}
```

---

## Performance Expectations

| Operation                | Target Latency      | Notes                                   |
| ------------------------ | ------------------- | --------------------------------------- |
| POST /augment            | <100ms (p95)        | Aggregate recomputation included        |
| GET /roster (cache hit)  | <10ms               | 304 Not Modified response               |
| GET /roster (cache miss) | <500ms              | Full roster serialization               |
| FAISS index reload       | <5s @ 1,000 entries | Background task, doesn't block requests |
| GET /service/info        | <50ms               | Lightweight stats query                 |

---

## Security Considerations

### Current (Development)

- No authentication required
- Service runs in trusted Docker network
- Not exposed to public internet

### Future (Production)

- Bearer token authentication
- Rate limiting per tenant
- Request signing
- HTTPS only

---

## Monitoring & Observability

### Prometheus Metrics

If `prometheus_client` is installed, the backend exposes metrics at `/metrics`:

```bash
curl http://localhost:8000/metrics
```

**Key Metrics:**

- `augmented_embedding_requests_total{status, quality_tier}` - Counter of augment requests
- `augmented_embedding_duration_seconds{operation}` - Histogram of augment latency
- `aggregate_recomputation_duration_seconds` - Histogram of aggregate recomputation time
- `roster_entries_total{model}` - Gauge of total roster entries
- `roster_embeddings_total{type, model}` - Gauge of embeddings by type (reference/augmented)
- `faiss_index_vectors_total` - Gauge of vectors in FAISS index

### Structured Logging

Backend logs include structured fields for correlation:

```json
{
  "level": "INFO",
  "message": "Added augmented embedding",
  "roster_id": "550e8400-...",
  "roster_name": "John Doe",
  "observation_id": "face-123-img-456",
  "source": "wordpress_confirm",
  "quality_tier": "high",
  "total_augmented": 15,
  "action": "embedding_added"
}
```

WordPress should include correlation IDs in requests for distributed tracing.

---

## Changelog

### 2025-11-01 - v1.0

- Initial documentation
- Progressive learning workflow
- ETag caching specification
- Idempotency patterns
- Error handling guidelines
- Performance targets
- Metrics and logging

---

## Support

For integration issues or questions:

1. Check backend logs: `docker logs recognition-service`
2. Verify service health: `GET /api/v0/service/info`
3. Test with curl examples above
4. Review backend API documentation: `/docs` (FastAPI auto-docs)

---

**Document Status:** ✅ Ready for Implementation  
**Backend Version:** 1.0  
**API Version:** v0 (unstable, may change)
