# Recognition Service

A face recognition microservice built with hexagonal architecture and CVLFace models.

## 🎯 Features

- **Multiple Models**: AdaFace IR101 (quality-adaptive), InsightFace W600K (built-in alignment), ArcFace IR50 (MTCNN alignment)
- **Quality-Adaptive Margin**: AdaFace uses quality-aware thresholds for better recognition
- **Flexible Alignment**: MTCNN and built-in alignment strategies
- **Hexagonal Architecture**: Clean separation of concerns with ports and adapters
- **FastAPI Integration**: RESTful API endpoints with automatic documentation

## 🏗️ Architecture

```text
Recognition Service
├── domain/           # Core business logic
│   ├── entities.py   # Domain entities
│   ├── interfaces.py # Abstract interfaces
│   └── recognition_service.py # Main service
├── ports/            # External interfaces
│   ├── api_router.py # FastAPI endpoints
│   ├── models.py     # Request/response models
│   └── dependencies.py # Dependency injection
├── adapters/         # External integrations
│   ├── face_aligner_impl.py # Face alignment
│   ├── quality_scorer_impl.py # Quality scoring
│   ├── embedding_router_impl.py # Embedding management
│   └── cvlface_*_adapter.py # Model adapters
└── config/           # Configuration management
    ├── settings.yaml # Service configuration
    └── config_manager.py # Config loader
```

## 🚀 Quick Start

### Prerequisites

```bash
# Install dependencies
pip install -r requirements_main.txt

# Additional dependencies for recognition
pip install mtcnn insightface transformers accelerate
```

### Environment Setup

```bash
# Required environment variables
export CACHE_DIR="/path/to/cache"
export HF_HOME="/path/to/huggingface/cache"
export ROSTER_DATA_DIR="/path/to/roster/data"

# Optional
export DEVICE="auto"  # or "cpu", "cuda", "mps"
export RECOG_SETTINGS="/path/to/recognition/settings.yaml"
```

### Running the Service

```python
from recognition import router, get_recognition_service
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)

# The service will auto-initialize on first request
```

## 📋 API Endpoints

### Analyze Scene

```http
POST /api/v0/analyze-scene/{model}-{threshold}
Content-Type: multipart/form-data

model: adaface_ir101 | insightface_w600k | arcface_ir50
threshold: 0.0-1.0 (recognition threshold)
file: image file
```

**Query Parameters:**

- `override_threshold`: Override the path threshold (optional)

**Response:**

```json
{
  "faces": [
    {
      "detection": {
        "bbox": [x, y, width, height],
        "confidence": 0.95,
        "landmarks": [[x1, y1], [x2, y2], ...]
      },
      "embedding_available": true,
      "quality_score": 0.8,
      "matches": [
        {
          "person_name": "John Doe",
          "confidence": 0.85,
          "distance": 0.15
        }
      ]
    }
  ],
  "model_type": "adaface_ir101",
  "threshold": 0.5,
  "processing_time_ms": 150.0,
  "total_faces": 1,
  "identified_faces": 1
}
```

### Health Check

```http
GET /api/v0/health
```

### List Models

```http
GET /api/v0/models
```

## 🎛️ Configuration

### Model Configuration

```yaml
models:
  adaface_ir101:
    type: "cvlface_adaface"
    model_id: "minchul/cvlface_adaface_ir101_webface12m"
    device: "auto"
    face_detection_threshold: 0.5
    face_recognition_threshold: 0.5
    embeddings_file: "adaface_ir101_embeddings.json"
    settings:
      quality_adaptive: true
      use_mtcnn_alignment: true
      min_face_size: 40
      max_faces: 10
```

### Performance Tuning

```yaml
performance:
  target_latency_ms:
    gpu_t4: 150
    cpu_m1: 600
  gpu_memory_limit_gb: 6
  cache_embeddings: true
  max_batch_size: 4
```

## 🧪 Testing

```bash
# Run tests
python -m pytest recognition/tests/

# Run with coverage
python -m pytest recognition/tests/ --cov=recognition --cov-report=html

# Run specific test
python -m pytest recognition/tests/test_recognition_service.py::TestDomainEntities::test_face_detection_creation
```

## 📊 Performance Benchmarks

| Model | Device | P95 Latency | Memory Usage |
|-------|--------|-------------|--------------|
| AdaFace IR101 | T4 GPU | < 150ms | < 6GB |
| AdaFace IR101 | M1 CPU | < 600ms | < 2GB |
| InsightFace W600K | T4 GPU | < 120ms | < 4GB |
| ArcFace IR50 | T4 GPU | < 130ms | < 5GB |

## 🔧 Development

### Adding New Models

1. Create adapter inheriting from `BaseCVLFaceAdapter`
2. Implement abstract methods:
   - `get_model_type()`
   - `get_alignment_strategy()`
   - `_detect_faces_impl()`
   - `_extract_embedding_impl()`
3. Register in `dependencies.py`
4. Add configuration in `settings.yaml`

### Extending Quality Scoring

```python
class CustomQualityScorer(QualityScorer):
    def calculate_quality(self, face_image, embedding=None):
        # Custom quality calculation
        return quality_score
```

### Custom Alignment Strategies

```python
class CustomFaceAligner(FaceAligner):
    def align_face(self, image, detection):
        # Custom alignment logic
        return aligned_face
```

## 📝 Quality Gates

- **Static Analysis**: `flake8` + `mypy` must pass
- **Test Coverage**: ≥ 80% overall, ≥ 95% for critical modules
- **Performance**: P95 < 150ms (T4 GPU), < 600ms (M1 CPU)
- **Memory**: ≤ 6GB GPU RAM after warm-up

## 🔄 Integration

### Backward Compatibility

The service maintains backward compatibility with the existing pipeline interface:

```python
from recognition.pipelines import get_hf_pipeline

# Legacy interface still works
pipeline = get_hf_pipeline()
```

### Roster Integration

Embeddings are automatically loaded from:

- `roster/data/adaface_ir101_embeddings.json`
- `roster/data/insightface_w600k_embeddings.json`
- `roster/data/arcface_ir50_embeddings.json`

### Embedding Format

```json
{
  "John Doe": {
    "embedding": [0.1, 0.2, ...],
    "model_type": "adaface_ir101",
    "embedding_dim": 512
  }
}
```

## 🚨 Troubleshooting

### Common Issues

1. **MTCNN not available**: Install with `pip install mtcnn`
2. **CUDA out of memory**: Reduce `max_batch_size` or use CPU
3. **Model loading timeout**: Increase HuggingFace cache size
4. **MPS compatibility**: MTCNN falls back to CPU automatically

### Debug Mode

```python
from recognition.config import get_config

config = get_config()
config.get('service.debug', True)  # Enable debug logging
```

## 📚 References

- [AdaFace Paper](https://arxiv.org/abs/2204.00964) - Quality Adaptive Margin for Face Recognition
- [CVLFace Models](https://huggingface.co/collections/minchul/cvlface-655e44c7e5ea3a3b2e4bcfba) - HuggingFace model collection
- [Hexagonal Architecture](https://en.wikipedia.org/wiki/Hexagonal_architecture_(software)) - Architecture pattern

## 📄 License

This project follows the same license as the parent project.
