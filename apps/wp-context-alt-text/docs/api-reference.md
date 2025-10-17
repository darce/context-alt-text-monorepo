# API Reference

This document provides comprehensive documentation for the Context Alt Text REST API endpoints.

## Base URL

All endpoints are prefixed with: `/wp-json/cat/v1`

**Legacy endpoints** (deprecated): `/wp-json/context-alt-text/v1`

## Authentication

All endpoints require WordPress authentication with the `manage_options` capability (typically admin users).

Use WordPress nonces for AJAX requests:

```javascript
fetch('/wp-json/cat/v1/dashboard/coverage', {
  headers: {
    'X-WP-Nonce': wpApiSettings.nonce,
  },
});
```

---

## Table of Contents

- [Settings Endpoints](#settings-endpoints)
- [Dashboard Endpoints](#dashboard-endpoints)
- [Workbench Endpoints](#workbench-endpoints)
- [Recognition Endpoints](#recognition-endpoints)
- [Observations Endpoints](#observations-endpoints)
- [Roster Endpoints](#roster-endpoints)
- [Error Handling](#error-handling)

---

## Settings Endpoints

### Get Recognition Settings

Retrieve current recognition service configuration.

**Endpoint:** `GET /wp-json/cat/v1/settings/recognition`

**Response:**

```json
{
  "settings": {
    "baseUrl": "http://localhost:7860",
    "timeoutMs": 30000,
    "apiKey": "",
    "modelProfile": ""
  },
  "featureFlags": {
    "workbenchRecognition": true,
    "rosterEnabled": true
  }
}
```

---

### Update Recognition Settings

Configure recognition service connection.

**Endpoint:** `POST /wp-json/cat/v1/settings/recognition`

**Methods:** `POST`, `PUT`, `PATCH`

**Request Body:**

```json
{
  "baseUrl": "http://localhost:7860",
  "timeoutMs": 30000,
  "apiKey": "optional-api-key",
  "modelProfile": "optional-model-profile"
}
```

**Response:**

```json
{
  "settings": {
    "baseUrl": "http://localhost:7860",
    "timeoutMs": 30000
  },
  "featureFlags": {
    "workbenchRecognition": true,
    "rosterEnabled": true
  },
  "message": "Recognition settings updated."
}
```

---

### Test Recognition Connection

Test connectivity to the recognition service.

**Endpoint:** `POST /wp-json/cat/v1/settings/recognition/test`

**Response (Success):**

```json
{
  "ok": true,
  "status": "ok",
  "details": {
    "status": "ok",
    "model": "w600k_r50",
    "version": "1.0.0"
  }
}
```

**Response (Error):**

```json
{
  "code": "cat_recognition_health_unavailable",
  "message": "Connection refused",
  "data": {
    "status": 502
  }
}
```

---

## Dashboard Endpoints

### Get Coverage Metrics

Retrieve accessibility coverage statistics.

**Endpoint:** `GET /wp-json/cat/v1/dashboard/coverage`

**Response:**

```json
{
  "total": 150,
  "missing": 45,
  "present": 105,
  "percentage": 70,
  "lastScanned": "2025-10-17T10:30:00Z"
}
```

---

## Workbench Endpoints

### Get Workbench Media

Retrieve media items for the workbench, filtered by alt text status.

**Endpoint:** `GET /wp-json/cat/v1/workbench/media`

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | `1` | Page number |
| `per_page` | integer | `20` | Items per page (max: 100) |
| `status` | string | `missing` | Filter: `missing`, `present`, `all` |
| `search` | string | - | Search by filename or title |

**Response:**

```json
{
  "items": [
    {
      "id": 123,
      "url": "https://example.com/wp-content/uploads/2025/10/image.jpg",
      "title": "Vacation Photo",
      "altText": "",
      "fileSize": 245760,
      "dimensions": {
        "width": 1920,
        "height": 1080
      },
      "uploadedAt": "2025-10-15T14:30:00Z"
    }
  ],
  "total": 45,
  "totalPages": 3,
  "page": 1,
  "perPage": 20
}
```

**Headers:**

- `X-WP-Total`: Total number of items
- `X-WP-TotalPages`: Total number of pages

---

## Recognition Endpoints

### Trigger Recognition Analysis

Analyze an attachment for faces and objects.

**Endpoint:** `POST /wp-json/cat/v1/recognition/analyze`

**Request Body:**

```json
{
  "attachmentId": 123
}
```

**Response:**

```json
{
  "jobId": "rec-abc123def456",
  "status": "pending",
  "attachmentId": 123,
  "createdAt": "2025-10-17T10:35:00Z"
}
```

---

### Get Recognition Job Status

Check the status of a recognition job.

**Endpoint:** `GET /wp-json/cat/v1/recognition/job/{jobId}`

**Response (In Progress):**

```json
{
  "jobId": "rec-abc123def456",
  "status": "processing",
  "progress": 45,
  "attachmentId": 123
}
```

**Response (Complete):**

```json
{
  "jobId": "rec-abc123def456",
  "status": "completed",
  "attachmentId": 123,
  "observations": [
    {
      "id": "obs-xyz789",
      "type": "face",
      "confidence": 0.95,
      "boundingBox": {
        "x": 100,
        "y": 150,
        "width": 200,
        "height": 250
      },
      "label": "John Doe"
    }
  ],
  "completedAt": "2025-10-17T10:36:00Z"
}
```

---

## Observations Endpoints

### Get Observations

Retrieve recognition observations for attachments.

**Endpoint:** `GET /wp-json/cat/v1/observations`

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `attachmentId` | integer | Filter by attachment ID |
| `entityType` | string | Filter by type: `face`, `person`, `object` |

**Response:**

```json
{
  "observations": [
    {
      "attachmentId": 123,
      "observationId": "obs-xyz789",
      "type": "face",
      "confidence": 0.95,
      "boundingBox": {
        "x": 100,
        "y": 150,
        "width": 200,
        "height": 250
      },
      "label": "John Doe",
      "rosterIds": ["person-abc123"]
    }
  ]
}
```

---

### Update Observation

Update observation metadata (e.g., assign to roster entry).

**Endpoint:** `POST /wp-json/cat/v1/observations/{attachmentId}/{observationId}`

**Methods:** `POST`, `PUT`, `PATCH`

**Request Body:**

```json
{
  "rosterIds": ["person-abc123", "person-def456"]
}
```

**Response:**

```json
{
  "success": true,
  "observation": {
    "attachmentId": 123,
    "observationId": "obs-xyz789",
    "rosterIds": ["person-abc123", "person-def456"]
  }
}
```

---

### Retry Failed Observations

Retry recognition for observations that failed or timed out.

**Endpoint:** `POST /wp-json/cat/v1/observations/retry`

**Request Body (Optional):**

```json
{
  "entityType": "face"
}
```

**Response:**

```json
{
  "status": "deferred",
  "accepted": 12,
  "rejected": 0,
  "deferred": 0,
  "message": "12 observations queued for retry"
}
```

---

## Roster Endpoints

### List Roster Entries

Retrieve roster entries (known entities).

**Endpoint:** `GET /wp-json/cat/v1/roster`

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | `1` | Page number |
| `per_page` | integer | `20` | Items per page (max: 100) |
| `type` | string | - | Filter by type: `person`, `object` |
| `search` | string | - | Search by label |

**Response:**

```json
{
  "entries": [
    {
      "id": "person-abc123",
      "type": "person",
      "label": "John Doe",
      "remoteId": "remote-xyz789",
      "observationCount": 15,
      "createdAt": "2025-10-01T10:00:00Z",
      "updatedAt": "2025-10-17T10:35:00Z"
    }
  ],
  "total": 42,
  "page": 1,
  "perPage": 20,
  "totalPages": 3,
  "stats": {
    "total": 42,
    "local": 5,
    "synced": 37
  },
  "syncState": {
    "lastSync": "2025-10-17T09:00:00Z",
    "status": "synced"
  },
  "filters": {
    "search": "",
    "type": ""
  }
}
```

---

### Create Roster Entry

Create a new roster entry.

**Endpoint:** `POST /wp-json/cat/v1/roster`

**Request Body:**

```json
{
  "type": "person",
  "label": "Jane Smith",
  "remoteId": "remote-abc456"
}
```

**Response:**

```json
{
  "success": true,
  "entry": {
    "id": "person-def456",
    "type": "person",
    "label": "Jane Smith",
    "remoteId": "remote-abc456",
    "observationCount": 0,
    "createdAt": "2025-10-17T10:40:00Z"
  }
}
```

---

### Update Roster Entry

Update an existing roster entry.

**Endpoint:** `PATCH /wp-json/cat/v1/roster/{id}`

**Methods:** `PATCH`, `POST`, `PUT`

**Request Body:**

```json
{
  "label": "Jane Doe-Smith",
  "type": "person"
}
```

**Response:**

```json
{
  "success": true,
  "entry": {
    "id": "person-def456",
    "type": "person",
    "label": "Jane Doe-Smith",
    "updatedAt": "2025-10-17T10:45:00Z"
  }
}
```

---

### Delete Roster Entry

Delete a roster entry.

**Endpoint:** `DELETE /wp-json/cat/v1/roster/{id}`

**Response:**

```json
{
  "success": true,
  "message": "Roster entry deleted successfully"
}
```

---

### Sync Roster from Remote

Synchronize local roster with remote recognition service.

**Endpoint:** `POST /wp-json/cat/v1/roster/sync`

**Response:**

```json
{
  "success": true,
  "stats": {
    "fetched": 50,
    "added": 5,
    "updated": 10,
    "deleted": 2,
    "errors": 0
  },
  "syncState": {
    "lastSync": "2025-10-17T10:50:00Z",
    "status": "synced"
  },
  "message": "Roster synchronized successfully"
}
```

---

## Error Handling

### Error Response Format

All errors follow the WordPress REST API error format:

```json
{
  "code": "error_code",
  "message": "Human-readable error message",
  "data": {
    "status": 400
  }
}
```

### Common Error Codes

| Code | Status | Description |
|------|--------|-------------|
| `rest_forbidden` | 403 | User lacks required permissions |
| `rest_invalid_param` | 400 | Invalid request parameter |
| `cat_recognition_unavailable` | 502 | Recognition service not accessible |
| `cat_recognition_timeout` | 504 | Recognition request timed out |
| `cat_invalid_attachment` | 400 | Attachment ID not found or invalid |
| `cat_roster_not_found` | 404 | Roster entry not found |
| `cat_observation_not_found` | 404 | Observation not found |

---

## Rate Limiting

The plugin implements internal rate limiting for recognition requests:

- **Cooldown Period:** 5 minutes between automatic retries
- **Manual Retries:** Bypass cooldown (user-initiated actions)
- **Concurrent Jobs:** Maximum 3 concurrent recognition jobs

---

## Webhooks (Future)

Webhook support is planned for future releases:

- `recognition.completed` - Recognition job completed
- `roster.updated` - Roster entry updated
- `observation.matched` - Observation matched to roster entry

---

## Examples

### Triggering Recognition from JavaScript

```javascript
async function triggerRecognition(attachmentId) {
  const response = await fetch('/wp-json/cat/v1/recognition/analyze', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-WP-Nonce': wpApiSettings.nonce,
    },
    body: JSON.stringify({ attachmentId }),
  });
  
  const data = await response.json();
  return data.jobId;
}
```

### Polling Job Status

```javascript
async function pollJobStatus(jobId) {
  const response = await fetch(`/wp-json/cat/v1/recognition/job/${jobId}`, {
    headers: {
      'X-WP-Nonce': wpApiSettings.nonce,
    },
  });
  
  const data = await response.json();
  
  if (data.status === 'completed') {
    return data.observations;
  } else if (data.status === 'failed') {
    throw new Error('Recognition failed');
  }
  
  // Poll again after delay
  await new Promise(resolve => setTimeout(resolve, 2000));
  return pollJobStatus(jobId);
}
```

### Updating Roster Entry

```javascript
async function updateRosterEntry(entryId, updates) {
  const response = await fetch(`/wp-json/cat/v1/roster/${entryId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      'X-WP-Nonce': wpApiSettings.nonce,
    },
    body: JSON.stringify(updates),
  });
  
  return response.json();
}
```

---

## Support

- **Issues:** [GitHub Issues](https://github.com/your-org/context-alt-text-monorepo/issues)
- **Documentation:** [`docs/`](.)
- **Debugging:** Check WordPress logs at `/wp-content/uploads/cat-logs/debug-YYYY-MM-DD.log`
