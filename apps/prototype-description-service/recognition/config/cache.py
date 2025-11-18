from pathlib import Path
import os

def configure_dev_cache() -> None:
    if os.environ.get("ENVIRONMENT") != "development":
        return
    cache_base_env = os.environ.get("CACHE_BASE")
    if not cache_base_env:
        return
    cache_base = Path(cache_base_env)
    overrides = {
        "INSIGHTFACE_HOME": cache_base / "insightface",
        "INSIGHTFACE_CACHE_DIR": cache_base / "insightface",
        "HF_HOME": cache_base / "huggingface_cache",
        "TRANSFORMERS_CACHE": cache_base / "huggingface_cache",
        "HF_HUB_CACHE": cache_base / "huggingface_cache",
        "TORCH_HOME": cache_base / "torch",
        "YOLO_CONFIG_DIR": cache_base / "yolo",
        "MPLCONFIGDIR": cache_base / "matplotlib",
    }
    for key, value in overrides.items():
        os.environ.setdefault(key, str(value))

configure_dev_cache()
