# Recognition Service

InsightFace-only recognition service for face detection, embedding extraction, and roster matching.

## Overview

This is a complete rewrite of the recognition service, simplified to use only InsightFace models without CVLFace, AdaFace, or quality scoring complexity. The service provides:

- **Face Detection**: Using InsightFace SCRFD detector
- **Face Embedding**: Using InsightFace ArcFace model (w600k)
- **Roster Matching**: Cosine similarity matching against loaded embeddings
- **API Compatibility**: Same endpoints and DTOs as the previous service

## Architecture

```
┌─────────────────┐
│   FastAPI       │  ← Ports layer (API routes)
│   Routes        │
└─────────┬───────┘
          │
┌─────────▼───────┐
│ Recognition     │  ← Services layer (orchestration)
│ Service         │
└─────────┬───────┘
          │
┌─────────▼───────┐
│   Adapters      │  ← Adapters layer
│ ┌─────────────┐ │
│ │ InsightFace │ │  ← Single model adapter
│ │   Adapter   │ │
│ └─────────────┘ │
│ ┌─────────────┐ │
│ │ Embedding   │ │  ← Roster matching
│ │   Router    │ │
│ └─────────────┘ │
└─────────────────┘
```

## Configuration

The service is configured via `config/settings.yaml`:

```yaml
# InsightFace Model Configuration
insightface:
  model_name: "deepinsight/insightface-scrfd-arcface-w600k"
  device: "auto"  # auto, cpu, cuda, mps
  cache_dir: "/tmp/insightface_models"

# Recognition Settings
recognition:
  default_threshold: 0.45
  max_faces_per_image: 10
  embedding_dimension: 512

# Embedding Router Configuration
embedding_router:
  embeddings_file: "/roster/data/insightface_embeddings.json"
  auto_reload: true
  reload_interval: 30  # seconds
```

Environment variable override: `RECOG_SETTINGS=/path/to/settings.yaml`

## API Endpoints

### Main Analysis Endpoint

```http
POST /api/v0/analyze-scene
Content-Type: multipart/form-data

- images: List of image files
- use_roster: boolean (default: true)
- threshold: float (optional, overrides config)
- model: string (ignored, always uses InsightFace)
```

**Alternative with path parameter:**
```http
POST /api/v0/analyze-scene/{threshold}
```

### Service Management

```http
GET /api/v0/service/info          # Get service information
POST /api/v0/service/reload       # Force reload embeddings
GET /api/v0/health                # Health check
```

## Installation

1. **Install dependencies:**
```bash
pip install insightface
pip install onnxruntime  # or onnxruntime-gpu for CUDA
pip install fastapi uvicorn
pip install pillow numpy pydantic
```

2. **Download models:**
The InsightFace models will be downloaded automatically on first use.

## Usage

### Standalone Service

```python
from recognition import RecognitionService
from PIL import Image

# Initialize service
service = RecognitionService()

# Load image
image = Image.open("photo.jpg")

# Run recognition
result = await service.recognize_faces(image, threshold=0.5)

# Access results
print(f"Detected {len(result.face_detections)} faces")
for match in result.matches:
    if match.is_match:
        print(f"Matched: {match.entry.name} ({match.similarity:.2%})")
```

### FastAPI Integration

```python
from fastapi import FastAPI
from recognition.ports import router

app = FastAPI()
app.include_router(router)
```

## Testing

Run the test suite:

```bash
# Run all tests
pytest recognition/tests/ -v

# Run specific test categories
pytest recognition/tests/test_api_smoke.py -v      # API smoke tests
pytest recognition/tests/test_top1_micro.py -v    # Accuracy tests
pytest recognition/tests/bench_latency_micro.py -v # Latency benchmark
```

### Performance Requirements

- **Latency**: P95 < 1200ms on M1 CPU, < 600ms ideal
- **GPU Memory**: ≤ 4GB after warm-up
- **Accuracy**: ≥ 50% top-1 accuracy on micro dataset
- **Concurrency**: ≥ 100 req/min sustained with 2 workers

## Embeddings Format

The service expects embeddings in JSON format:

```json
{
  "entities": [
    {
      "unique_id": "person_001",
      "name": "John Doe",
      "display_name": "John Doe",
      "aggregate_embedding": [0.1, 0.2, ...],  // 512-dimensional
      "metadata": {}
    }
  ]
}
```

## Migration from Previous Service

The new service maintains API compatibility but has simplified internals:

### Removed Features
- CVLFace model support
- AdaFace model support  
- Quality scoring and adaptive margins
- Occlusion handling
- Multi-model pipeline management

### Maintained Features
- Same API endpoints and response format
- Compatible with existing Analysis and Roster services
- Same DTO structures
- Threshold overrides
- Embedding auto-reload

## Troubleshooting

### Common Issues

1. **Model download fails:**
   ```bash
   # Check internet connection and try manual download
   python -c "import insightface; app = insightface.app.FaceAnalysis()"
   ```

2. **CUDA not available:**
   ```yaml
   # Force CPU mode in settings.yaml
   insightface:
     device: "cpu"
   ```

3. **Memory issues:**
   ```yaml
   # Reduce concurrent requests
   performance:
     max_concurrent_requests: 5
   ```

4. **No embeddings loaded:**
   ```bash
   # Check embeddings file path and format
   ls -la /roster/data/insightface_embeddings.json
   ```

## Development

The service follows hexagonal architecture:

- **Domain**: Core business logic (`recognition/domain/`)
- **Adapters**: External integrations (`recognition/adapters/`)
- **Services**: Application logic (`recognition/services/`)
- **Ports**: API layer (`recognition/ports/`)
- **Utils**: Helper functions (`recognition/utils/`)

### Adding New Features

1. Define interfaces in `domain/interfaces.py`
2. Implement in appropriate adapter
3. Wire through service layer
4. Expose via API routes if needed
5. Add tests

## License

Same as the main project.
