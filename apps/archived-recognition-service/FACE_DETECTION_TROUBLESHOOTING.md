# Face Detection Troubleshooting Guide

## Issue: InsightFace Not Detecting Faces

Your logs show:

```
🔬 Analyzed image: 0 faces in 460.5ms
```

## Solution: Adjust Detection Threshold in settings.yaml

The detection threshold controls how confident InsightFace needs to be before it reports a face. The default is `0.5` (50% confidence), which can miss some faces.

### Current Configuration

File: `recognition_core/config/settings.yaml`

```yaml
insightface:
  det_thresh: 0.5 # Current default
  det_size: [640, 640]
```

### Recommended Changes

**Try lowering the threshold to be more sensitive:**

```yaml
insightface:
  det_thresh: 0.3 # More sensitive - will detect more faces but may have false positives
  det_size: [640, 640]
```

**Or try even more sensitive:**

```yaml
insightface:
  det_thresh: 0.2 # Very sensitive - good for difficult/small/blurry faces
  det_size: [640, 640]
```

### Detection Size Options

The `det_size` parameter controls the input resolution for detection:

- `[640, 640]` - Default, good balance (current)
- `[512, 512]` - Faster but may miss small faces
- `[320, 320]` - Much faster but will miss more faces
- `[1024, 1024]` - More accurate for high-res images but slower

### Testing Your Changes

1. Edit `recognition_core/config/settings.yaml`
2. Restart the recognition service
3. Look for this log line on startup:
   ```
   🎯 Detection settings: threshold=0.3, size=(640, 640)
   ```
4. Test your image again

### What Each Threshold Means

- `0.5` (default): Only report faces the model is 50%+ confident about
- `0.3`: Report faces the model is 30%+ confident about (more permissive)
- `0.2`: Report faces the model is 20%+ confident about (very permissive, may get false positives)

### Trade-offs

- **Lower threshold (0.2-0.3)**:
  - ✅ Detects more faces, including difficult ones
  - ❌ May detect false positives (non-face objects)
- **Higher threshold (0.5-0.7)**:
  - ✅ Fewer false positives
  - ❌ May miss real faces that are small, blurry, or at odd angles

### Additional Settings Already Configured

In your `settings.yaml`, I've also set:

```yaml
recognition:
  max_faces_per_image: 999 # No artificial limit
  max_candidates: 999 # No artificial limit
```

These ensure the system won't artificially limit the number of faces or recognition candidates.

## Quick Test

Try this setting first:

```yaml
insightface:
  model_name: "buffalo_l"
  device: "auto"
  cache_dir: null
  providers: []
  det_thresh: 0.3 # <-- Change this line
  det_size: [640, 640]
```

Then restart and test with your problematic image.
