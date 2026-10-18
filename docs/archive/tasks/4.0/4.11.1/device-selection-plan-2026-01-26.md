# InsightFace device selection plan (macOS MPS + CUDA + CPU fallback)

## Problem
The current InsightFace adapter selects providers purely from static settings. Defaults are `device="cpu"`, which prevents the service from taking advantage of CoreML on macOS or CUDA on GPU instances. There is also no runtime detection or fallback on initialization failures.

## Desired behavior
- On local macOS, **try CoreML/MPS first**.
- On remote GPU instances, **try CUDA first**.
- If either fails (missing provider or init error), **fallback to CPU**.
- Still allow explicit overrides for debugging or constrained environments.

## Proposed selection order ("auto")
Priority rules:
1. If `settings.insightface.providers` is set, use it as-is (explicit override).
2. Else if `settings.insightface.device` is explicitly set to `cpu`, `cuda`, or `mps`, use the corresponding providers.
3. Else (device == `auto`):
   - Detect available providers via `onnxruntime.get_available_providers()`.
   - If `platform.system() == "Darwin"` and `CoreMLExecutionProvider` is available, **try CoreML first**.
   - Else if `CUDAExecutionProvider` is available, **try CUDA**.
   - Else use CPU.

Fallback behavior:
- If the model fails to initialize with the chosen provider (e.g., CoreML compilation error), log the failure and retry with CPU-only providers.

## Implementation touchpoints
- `apps/prototype-description-service/recognition/config/settings.py`
  - Change default `InsightFaceSettings.device` from `"cpu"` to `"auto"`.
  - Keep the comment noting macOS CoreML failures, but rely on runtime fallback.
- `apps/prototype-description-service/recognition/infrastructure/embeddings/__init__.py`
  - Add a provider detection helper using `onnxruntime.get_available_providers()`.
  - Update `_get_providers()` to use the auto selection order above.
  - Update `_get_ctx_id()` to reflect the **selected** device (CUDA -> 0, else -1).
  - Wrap `FaceAnalysis` initialization in a try/except block; on error, retry with CPU providers and `ctx_id=-1`.

## Pseudocode sketch
```python
available = onnxruntime.get_available_providers()

if settings.providers:
    providers = settings.providers
    device = settings.device
elif settings.device in ("cpu", "cuda", "mps"):
    providers = map_device_to_providers(settings.device)
    device = settings.device
else:
    if is_macos and "CoreMLExecutionProvider" in available:
        providers = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
        device = "mps"
    elif "CUDAExecutionProvider" in available:
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        device = "cuda"
    else:
        providers = ["CPUExecutionProvider"]
        device = "cpu"

try:
    init_face_analysis(providers, ctx_id=(0 if device == "cuda" else -1))
except Exception:
    log_warning_and_fallback_to_cpu()
    init_face_analysis(["CPUExecutionProvider"], ctx_id=-1)
```

## Testing plan
- Update `recognition/tests/unit/test_insightface_adapter.py` to cover:
  - `auto` on macOS picks CoreML when available.
  - `auto` on non-macOS picks CUDA when available.
  - `auto` falls back to CPU when only CPU provider is available.
  - Fallback behavior when provider initialization raises.
  - Explicit `providers` still override auto detection.

## Operational guidance
- For local macOS: leave `device="auto"` to allow CoreML/MPS attempts; fallback ensures a stable CPU path.
- For remote GPU: set `device="auto"` (default) or explicitly `device="cuda"` if you want to skip CoreML detection paths.
- For debugging: specify explicit `providers` to pin behavior.
