# Roster Service

A clean-slate rewrite of the roster microservice for managing identity records and model-specific embedding stores in the CVLFace stack.

## 🎯 Features

- **Model-Agnostic Storage**: Supports multiple face recognition models (AdaFace, InsightFace, ArcFace)
- **Hexagonal Architecture**: Clean separation of domain logic, ports, and adapters
- **High Performance**: P95 latency < 20ms for in-memory operations
- **Data Integrity**: Comprehensive validation and error handling
- **Hot Reload**: File watching for automatic updates
- **Versioning**: Backup and retention policies for data safety
- **Thread Safe**: Concurrent access support with file locking

## 🏗️ Architecture

```text
Roster Service
├── domain/           # Core business logic
│   ├── entities.py   # RosterEntry, RosterImage, RosterMatch
│   ├── interfaces.py # Abstract ports (dependency inversion)
│   └── roster_service.py # Main domain service
├── ports/            # External interfaces
│   ├── api_router.py # FastAPI endpoints
│   ├── models.py     # Request/response DTOs
│   └── dependencies.py # Dependency injection
├── adapters/         # External integrations
│   ├── file_storage_adapter.py # Filesystem storage
│   ├── embedding_storage_adapter.py # Embedding file management
│   └── data_validation_adapter.py # Data validation
├── config/           # Configuration management
│   ├── settings.yaml # Service configuration
│   └── config_manager.py # Config loader
└── tests/            # Test suite
    ├── test_api_smoke.py # API endpoint tests
    ├── test_roundtrip_import.py # Data integrity tests
    └── bench_latency_micro.py # Performance benchmarks
```

## 🚀 Quick Start

### Prerequisites

```bash
# Install dependencies
pip install fastapi uvicorn pydantic numpy

# Optional: for file watching
pip install watchdog
```

### Environment Setup

```bash
# Set data directory (optional, defaults to ${CACHE_DIR}/roster/data)
export ROSTER_DATA_DIR="/path/to/roster/data"

# Set settings file (optional, defaults to /roster/settings.yaml)
export ROSTER_SETTINGS="/path/to/settings.yaml"
```

### Running the Service

```python
# Standalone usage
from roster.ports import get_roster_service

roster_service = get_roster_service()

# Add an entry
result = roster_service.add_entry(
    name="john_doe",
    embedding=[0.1] * 512,  # 512-dimensional embedding
    model="adaface_ir101",
    metadata={"department": "engineering"}
)

# Get all entries for a model
entries = roster_service.get_entries("adaface_ir101")
```

```python
# FastAPI integration
from fastapi import FastAPI
from roster.ports.api_router import router

app = FastAPI()
app.include_router(router)

# Run with: uvicorn app:app --host 0.0.0.0 --port 8001
```

## 📡 API Endpoints

### Core Operations

```bash
# Add/update roster entry
POST /api/v0/roster/{model}/upsert
{
  "name": "john_doe",
  "embedding": [0.1, 0.2, ...],  # 512-dim vector
  "metadata": {"role": "employee"}
}

# Get all entries for a model
GET /api/v0/roster/{model}?include_embeddings=false

# Get specific entry
GET /api/v0/roster/{model}/{unique_id}

# Update entry
PUT /api/v0/roster/{model}/{unique_id}
{
  "embedding": [0.2, 0.3, ...],
  "metadata": {"role": "manager"}
}

# Delete entry
DELETE /api/v0/roster/{model}/{unique_id}
```

### Bulk Operations

```bash
# Bulk add entries
POST /api/v0/roster/{model}/bulk
{
  "entries": [
    {"name": "person1", "embedding": [...], "metadata": {}},
    {"name": "person2", "embedding": [...], "metadata": {}}
  ]
}
```

### Management

```bash
# Get roster statistics
GET /api/v0/roster/{model}/stats

# Clear all entries (admin)
DELETE /api/v0/roster/{model}/clear

# Health check
GET /api/v0/roster/health
```

## 🧪 Testing

### Run Tests

```bash
# API smoke tests
python -m pytest roster/tests/test_api_smoke.py -v

# Data integrity tests
python -m pytest roster/tests/test_roundtrip_import.py -v

# Performance benchmarks
python -m pytest roster/tests/bench_latency_micro.py -v -s
```

### Test Coverage

```bash
# Install coverage
pip install pytest-cov

# Run with coverage
python -m pytest roster/tests/ --cov=roster --cov-report=html
```

## ⚡ Performance

### Benchmarks

The service meets the following performance requirements:

- **P95 < 20ms**: In-memory read operations
- **P95 < 50ms**: CRUD operations on M1 CPU
- **Thread-safe**: Concurrent access with file locking
- **Scalable**: Supports 1000+ entries per model

### Optimization Tips

1. **Use caching**: Enable in-memory caching for frequently accessed rosters
2. **Batch operations**: Use bulk endpoints for multiple entries
3. **Exclude embeddings**: Set `include_embeddings=false` for listing operations
4. **Monitor storage**: Check `/stats` endpoint for storage information

## 🔧 Configuration

### Settings File (`settings.yaml`)

```yaml
service:
  name: "roster-service"
  version: "1.0.0"
  log_level: "INFO"

storage:
  backend: "filesystem"
  versioning:
    enabled: true
    retention_count: 5
  hot_reload:
    enabled: true
    watch_interval: 1.0

models:
  supported:
    - "adaface_ir101"
    - "insightface_w600k"
    - "arcface_ir50"
  embedding_dimensions:
    adaface_ir101: 512
    insightface_w600k: 512
    arcface_ir50: 512

validation:
  max_entries_per_identity: 10
  max_bulk_import_size: 1000
  required_fields: ["name", "embedding"]
```

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ROSTER_SETTINGS` | Path to settings.yaml | `/roster/settings.yaml` |
| `ROSTER_DATA_DIR` | Data directory root | `${CACHE_DIR}/roster/data` |
| `CACHE_DIR` | Global cache directory | `/tmp/cvlface-cache` |

## 🔍 Monitoring

### Health Check

```bash
curl http://localhost:8001/api/v0/roster/health
```

### Storage Information

```bash
curl http://localhost:8001/api/v0/roster/adaface_ir101/stats
```

### Logging

The service uses structured logging with configurable levels:

```python
import logging
logging.getLogger("roster").setLevel(logging.INFO)
```

## 🛠️ Development

### Project Structure

- **Domain-Driven Design**: Pure business logic in `domain/`
- **Dependency Inversion**: Adapters implement domain interfaces
- **Configuration Management**: Environment-based configuration
- **Comprehensive Testing**: Unit, integration, and performance tests

### Adding New Storage Backends

1. Implement `RosterStoragePort` interface
2. Register in dependency injection
3. Update configuration schema
4. Add tests for new adapter

### Integration with Recognition Service

The roster service integrates seamlessly with the recognition service:

1. **Shared Models**: Compatible embedding formats
2. **Hot Reload**: Automatic detection of roster changes
3. **Validation**: Consistent embedding dimension validation
4. **Performance**: Optimized for recognition workloads

## 📄 License

This service is part of the CVLFace entity identifier project.
