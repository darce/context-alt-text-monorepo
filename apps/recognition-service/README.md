---
title: Entity Identifier Api
emoji: 📉
colorFrom: green
colorTo: blue
sdk: docker
pinned: false
license: unknown
short_description: Deterministic identification of visual entities
---

# Entity Identifier API

A FastAPI-based service for analyzing images to detect objects, identify entities, and generate captions using state-of-the-art computer vision models.

## Flash Attention Configuration

This application supports Flash Attention 2 for improved performance with the Phi-3.5 vision model. Flash Attention provides significant memory and speed improvements but requires compatible hardware and software environments.

### Performance Benefits

- **Memory**: 2-4x reduction in GPU memory usage
- **Speed**: 2-8x faster attention computation
- **Scalability**: Better handling of longer sequences

### Configuration Options

#### 1. YAML Configuration (config/settings.yaml)

```yaml
caption_generator:
  config:
    model_settings:
      flash_attention:
        enabled: false # Set to true to enable
        force_disable_devices: ["cpu", "mps"] # Always disabled on these devices
```

#### 2. Environment Variable

```bash
export FLASH_ATTENTION_ENABLED=true
```

#### 3. Docker Environment

```dockerfile
# Uncomment Flash Attention installation in Dockerfile:
RUN pip install --no-cache-dir \
    "https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/flash_attn-2.7.4.post1+cu12torch2.6cxx11abiTRUE-cp310-cp310-linux_x86_64.whl"
```

### Compatibility Requirements

- **CUDA**: 12.1+ with compatible GPU
- **PyTorch**: 2.6.0+
- **Python**: 3.10+
- **Architecture**: Linux x86_64

### Troubleshooting

If you encounter binary compatibility issues:

1. Flash Attention is automatically disabled and falls back to eager attention
2. Check logs for "Flash Attention not available" messages
3. Verify CUDA version compatibility
4. Ensure all dependencies match the wheel requirements

### Current Status

- Flash Attention is **disabled by default** for maximum compatibility
- Enable only in confirmed compatible GPU environments
- CPU and MPS devices automatically use eager attention regardless of settings

See the [HuggingFace Spaces Config Reference](https://huggingface.co/docs/hub/spaces-config-reference) for more details.

## Entity Identification Configuration

Entity identification is configured via `shared/config/settings.yaml` under the `entity_identifier` section. Switch between AdaFace and InsightFace by setting:

```yaml
entity_identifier:
  type: adaface       # 'adaface' or 'insightface'
  adaface_config:     # Settings for AdaFace adapter
    model_path: "minchul/cvlface_adaface_ir101_webface12m"
    device: "auto"
    face_detection_threshold: 0.45
    face_recognition_threshold: 0.5
    use_builtin_face_detection: true
    settings:
      det_size: 640
      force_cuda_only: false
      onnx_gpu_mem_limit: 2500000000
  insightface_config: # Settings for InsightFace adapter
    model_path: "buffalo_l"
    device: "auto"
    face_detection_threshold: 0.45
    face_recognition_threshold: 0.5
    use_occlusion_awareness: true
    settings:
      det_size: 640
```

The service will automatically download required models from HuggingFace and convert PyTorch checkpoints to ONNX on first run. After initial setup, it works fully offline.
