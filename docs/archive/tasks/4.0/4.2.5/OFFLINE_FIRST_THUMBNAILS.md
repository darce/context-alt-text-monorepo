# v4.2.5: Offline-First Thumbnail Architecture

**Sprint**: 4.2.5  
**Status**: Planned  
**Date**: December 6, 2025

---

## Goal

WordPress frontend renders identity thumbnails correctly when user's machine is offline. Backend access required only for:

1. Initial face detection (embedding generation)
2. Clustering
3. Syncing user labels back to backend

---

## Current State (v4.2.4)

- `thumbnail_url` column exists in `media_identities` table but is **empty**
- Backend stores `media_url` and `bbox` coordinates
- Frontend shows placeholder when `thumbnail_url` is null
- **Problem**: No thumbnails displayed in cluster preview

---

## Proposed Solution: CSS-Based Cropping

Generate visual thumbnails client-side using CSS `object-fit` + `object-position` from:

- Source image already in WordPress Media Library
- Bounding box coordinates from backend

### Why CSS over Canvas?

| Aspect          | CSS Approach                        | Canvas Approach                  |
| --------------- | ----------------------------------- | -------------------------------- |
| **Performance** | ✅ GPU-accelerated, no JS execution | ❌ CPU-bound, blocks main thread |
| **Memory**      | ✅ Browser manages image cache      | ❌ Creates new bitmap in memory  |
| **Complexity**  | ✅ Declarative, simple              | ❌ Imperative, error-prone       |
| **Offline**     | ✅ Works with cached images         | ✅ Works with cached images      |
| **Quality**     | ⚠️ May show artifacts at edges      | ✅ Pixel-perfect crop            |
| **Retina**      | ✅ Automatic                        | ❌ Manual DPR handling           |

**Recommendation**: Use CSS for display, canvas only if we need to save/upload cropped images.

### CSS Implementation

```tsx
interface CroppedThumbnailProps {
  mediaUrl: string;
  bbox: { x: number; y: number; width: number; height: number };
  size?: number; // Display size in pixels
}

const CroppedThumbnail = ({
  mediaUrl,
  bbox,
  size = 48,
}: CroppedThumbnailProps) => {
  // Calculate scale to fit bbox into display size
  const scale = size / Math.max(bbox.width, bbox.height);

  return (
    <div
      style={{
        width: size,
        height: size,
        overflow: "hidden",
        borderRadius: "50%",
      }}
    >
      <img
        src={mediaUrl}
        alt="Detected face"
        style={{
          // Scale up the image so bbox fills the container
          transform: `translate(-${bbox.x * scale}px, -${
            bbox.y * scale
          }px) scale(${scale})`,
          transformOrigin: "top left",
          maxWidth: "none", // Override any max-width constraints
        }}
      />
    </div>
  );
};
```

### Alternative: object-fit approach

```css
.face-thumb {
  width: 48px;
  height: 48px;
  object-fit: none;
  object-position: calc(-1 * var(--bbox-x)) calc(-1 * var(--bbox-y));
  /* Note: object-fit: none doesn't scale, so this works best when 
     bbox is already close to display size */
}
```

---

## Data Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   WordPress     │────▶│     Backend      │────▶│   WordPress     │
│ (sends image)   │     │ (detects faces)  │     │ (receives bbox) │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                          │
                                                          ▼
                                               ┌─────────────────────┐
                                               │  Frontend renders   │
                                               │  CSS-cropped thumb  │
                                               │  from local image   │
                                               └─────────────────────┘
                                                          │
                                                     OFFLINE OK ✅
```

---

## Implementation Tasks

### Phase 1: CSS Thumbnail Component

- [ ] Create `<FaceThumbnail>` component using CSS transform crop
- [ ] Update `ClusterPreview` to use bbox + media URL fallback
- [ ] Add `media_url` to frontend types and API response

### Phase 2: WordPress Local Cache

- [ ] Create WP option or custom table for identity cache
- [ ] Store: `identity_id`, `media_id`, `cluster_id`, `bbox`, `user_label`
- [ ] Sync strategy: pull from backend on connect, push labels on change

### Phase 3: Offline Label Editing

- [ ] Queue label changes locally when offline
- [ ] Sync queue to backend when online
- [ ] Handle conflicts (backend re-clustered while offline)

---

## API Changes Required

### Backend Response (v4.2.4 → v4.2.5)

```diff
 {
   "identity_id": "uuid",
   "media_id": 2863,
   "cluster_id": "uuid",
   "bbox": { "x": 100, "y": 50, "w": 200, "h": 200 },
   "confidence": 0.95,
-  "thumbnail_url": null
+  "thumbnail_url": null,
+  "media_url": "http://localhost:10010/wp-content/uploads/2025/11/photo.jpg"
 }
```

Note: `media_url` should be the **WordPress URL**, not backend URL, so it works offline.

---

## Decision Log

| Date       | Decision               | Rationale                                         |
| ---------- | ---------------------- | ------------------------------------------------- |
| 2025-12-06 | CSS crop over canvas   | Better performance, simpler code, GPU-accelerated |
| 2025-12-06 | No base64 thumbnails   | Avoids DB bloat, uses existing cached images      |
| 2025-12-06 | WordPress-side caching | Enables offline rendering without backend         |

---

## References

- [CSS object-fit MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/object-fit)
- [CSS transform performance](https://web.dev/animations-guide/)
- Current placeholder: `ClusterPreview.tsx`
