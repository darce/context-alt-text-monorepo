## WordPress Plugin Integration Guide

### Using Face Thumbnails from Recognition Service

The recognition service generates base64-encoded face thumbnails during face detection and includes them in the API response. The WordPress plugin simply converts these to data URIs for display.

### Architecture

```
Recognition Service (Python)
  ↓ Detects face + generates thumbnail
  ↓ Returns JSON with base64 thumbnail

WordPress Plugin (PHP)
  ↓ Extracts thumbnail from API response
  ↓ Stores in database
  ↓ Converts to data URI for display

Frontend (TypeScript/React)
  ↓ Displays thumbnail as <img src="data:image/jpeg;base64,...">
```

### API Response Structure

```json
{
  "detected_entities": [
    {
      "bbox": [982, 651, 1064, 755],
      "confidence": 0.816,
      "face_data": {
        "embedding_id": "face-0",
        "embedding": [...],
        "thumbnail": "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBD..."
      }
    }
  ]
}
```

### Implementation

**1. Extract thumbnail in pipeline** (`RecognitionServiceFaceDetectionPipeline.php`):

```php
// Extract thumbnail from recognition service
$thumbnail = null;
if (isset($entity['face_data']['thumbnail']) && is_string($entity['face_data']['thumbnail'])) {
    $thumbnail = trim($entity['face_data']['thumbnail']);
}

$results[] = [
    'bbox' => $bbox,
    'embeddingId' => $embeddingId,
    'embeddingVector' => $embeddingVector,
    'clusterId' => null,
    'detectedAt' => $this->resolveDetectedAt($entity),
    'thumbnail' => $thumbnail,  // Store base64 thumbnail
];
```

**2. Convert to data URI** (`CachedFaceThumbnailProvider.php`):

```php
public function generateThumbnail(array $face): ?string
{
    // Use thumbnail from recognition service
    $thumbnail = $face['thumbnail'] ?? null;

    if (!is_string($thumbnail) || trim($thumbnail) === '') {
        return null;
    }

    // Return as data URI for direct display
    return 'data:image/jpeg;base64,' . $thumbnail;
}
```

**3. Display in frontend** (`FaceGrid.tsx`):

```typescript
{face.thumbnailUrl ? (
    <img src={face.thumbnailUrl} alt={faceLabel} className="cat-face-grid__image" />
) : (
    <div className="cat-face-grid__placeholder">
        <span className="cat-face-grid__placeholder-icon">?</span>
    </div>
)}
```

### Benefits

1. ✅ **No WordPress image processing** - No need for GD/Imagick libraries
2. ✅ **Immediate availability** - Thumbnails ready as soon as detection completes
3. ✅ **Exact crops** - Shows exactly what the AI detected
4. ✅ **Reduced server load** - No file I/O or image manipulation
5. ✅ **Works anywhere** - Compatible with any WordPress hosting
6. ✅ **Consistent quality** - Same processing pipeline as detection

### Removed Code

The following are now obsolete and deprecated:

- ❌ `ImageCropUtility::cropFaceRegion()` - No longer needed, thumbnails from backend
- ❌ File-based caching in `wp-uploads/cat-face-crops/` - Using data URIs instead
- ❌ Bounding box normalization logic - Backend handles this
- ❌ Image editor dependencies - No WordPress image processing required

### Database Schema

Face thumbnails are stored as base64 strings in the face observation records:

```php
[
    'bbox' => ['x' => 0.5, 'y' => 0.3, 'width' => 0.1, 'height' => 0.15],
    'thumbnail' => '/9j/4AAQSkZJRgABAQAAAQABAAD...',  // ~2-5KB base64 string
    'embeddingId' => 'face-0',
    'embeddingVector' => [...],
    // ...
]
```

### Testing

The implementation is verified by existing tests:

1. `ClusterControllerTest` - Validates thumbnail provider interface
2. `ApiTest` - Verifies cluster endpoint returns thumbnail URLs
3. Frontend tests - Confirm data URIs display correctly

No changes needed to tests as the interface remains the same.
