# Production Health Monitoring

For production deployments, health checks should be built into the application itself, not via external test suites.

## Production Health Endpoints (No additional packages needed)

The recognition service already includes these built-in health endpoints:

- `GET /api/v0/health` - Basic service health check
- `GET /api/v0/service/info` - Detailed service information
- `POST /api/v0/service/reload-embeddings` - Reload embeddings for health verification

## Installation Instructions

### Production Environment
```bash
# Only install core dependencies
pip install -r requirements_main.txt
```

### Development Environment  
```bash
# Install core + development dependencies
pip install -r requirements_main.txt
pip install -r requirements_local_dev.txt
```

### Testing with Production Health Checks
```bash
# Set cache directory and run integration + unit smoke tests
CACHE_DIR=/path/to/cache python -m pytest tests/integration/test_api_endpoints.py -v
CACHE_DIR=/path/to/cache python -m pytest tests/unit/test_scene_analysis_service.py -v
```

## Kubernetes/Docker Health Checks

For production deployments, configure container health checks:

```yaml
# Docker/Kubernetes health check example
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/api/v0/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

## Monitoring Integration

The health endpoints return structured JSON suitable for:
- Load balancer health checks
- Prometheus/Grafana monitoring
- Kubernetes readiness/liveness probes
- AWS ELB health checks
