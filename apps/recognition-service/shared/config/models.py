from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class VisionModelSettings(BaseModel):
    type: str = "siglip"
    config: Dict[str, Any] = Field(
        default_factory=lambda: {
            "model_id": "google/siglip-large-patch16-384",
        }
    )

    class Config:
        extra = "allow"


class ObjectDetectorSettings(BaseModel):
    type: str = "yolo"
    config: Dict[str, Any] = Field(
        default_factory=lambda: {
            "model_path": "shared/infrastructure/models/yolo11l.pt",
            "device": "auto",
            "confidence_threshold": 0.2,
            "settings": {
                "verbose": False,
                "force_cpu_on_macos": True,
            },
        }
    )

    class Config:
        extra = "allow"


def _default_caption_generator_config() -> Dict[str, Any]:
    return {
        "model_id": "microsoft/Phi-3.5-vision-instruct",
        "local_files_only": False,
        "device": "auto",
        "mps_fallback": {
            "enable_cpu_fallback": True,
            "disable_mps": False,
        },
        "model_settings": {
            "trust_remote_code": True,
            "low_cpu_mem_usage": {
                "cpu": True,
                "cuda": True,
                "mps": True,
            },
            "attn_implementation": "auto",
            "torch_dtype": {
                "cpu": "auto",
                "mps": "auto",
                "cuda": "auto",
            },
            "device_map": "auto",
        },
        "memory_allocation": {
            "gpu_memory_fractions": {
                "7.5": 0.75,
                "8.0": 0.8,
                "8.6": 0.7,
                "8.9": 0.8,
                "default": 0.7,
            },
        },
        "processor_settings": {
            "trust_remote_code": True,
            "num_crops": 4,
        },
        "text_generation": {
            "max_new_tokens": 2400,
            "temperature": 0.0,
            "do_sample": False,
            "use_cache": True,
        },
        "template": {
            "use_image_placeholder": True,
        },
    }


class CaptionGeneratorSettings(BaseModel):
    type: str = "mock"
    config: Dict[str, Any] = Field(default_factory=_default_caption_generator_config)

    class Config:
        extra = "allow"


class AttentionSettings(BaseModel):
    phi3_backends: Dict[str, List[str]] = Field(
        default_factory=lambda: {
            "newer_gpu": ["flash_attention_2", "eager"],
            "t4_gpu": ["eager"],
            "older_gpu": ["eager"],
        }
    )
    preferred_backends: List[str] = Field(
        default_factory=lambda: ["flash_attention_2", "eager"]
    )
    device_restrictions: Dict[str, Any] = Field(
        default_factory=lambda: {
            "cpu": ["eager"],
            "mps": ["eager"],
            "cuda": {
                "8.0+": ["flash_attention_2", "eager"],
                "7.5": ["eager"],
                "default": ["eager"],
            },
        }
    )
    config: Dict[str, Any] = Field(
        default_factory=lambda: {
            "fallback_to_eager": True,
            "enable_autodetection": True,
            "log_selection": True,
        }
    )

    class Config:
        extra = "allow"


class ServerSettings(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    log_level: str = "info"


class CaptionSettings(BaseModel):
    prompt_template: str = (
        "Generate a factual, objective alt-text description for a visually impaired user. "
        "Avoid redundancy and speculation."
    )


class EnvironmentSettings(BaseModel):
    primary_device: str = "auto"
    fallback_device: str = "cpu"


class HardwareSettings(BaseModel):
    enable_mps: bool = True


class GPUProfileSettings(BaseModel):
    flash_attention_enabled: bool
    cuda_memory_fraction: float
    max_split_size_mb: int
    recommended_attention: str
    enable_memory_optimization: bool

    class Config:
        extra = "allow"


class RuntimeOptimizations(BaseModel):
    gpu_configs: Dict[str, GPUProfileSettings] = Field(
        default_factory=lambda: {
            "7.5": GPUProfileSettings(
                flash_attention_enabled=False,
                cuda_memory_fraction=0.9,
                max_split_size_mb=128,
                recommended_attention="eager",
                enable_memory_optimization=True,
            ),
            "8.0": GPUProfileSettings(
                flash_attention_enabled=True,
                cuda_memory_fraction=0.95,
                max_split_size_mb=256,
                recommended_attention="flash_attention_2",
                enable_memory_optimization=False,
            ),
            "8.6": GPUProfileSettings(
                flash_attention_enabled=True,
                cuda_memory_fraction=0.9,
                max_split_size_mb=256,
                recommended_attention="flash_attention_2",
                enable_memory_optimization=True,
            ),
            "8.9": GPUProfileSettings(
                flash_attention_enabled=True,
                cuda_memory_fraction=0.95,
                max_split_size_mb=512,
                recommended_attention="flash_attention_2",
                enable_memory_optimization=False,
            ),
        }
    )
    cpu_fallback: GPUProfileSettings = GPUProfileSettings(
        flash_attention_enabled=False,
        cuda_memory_fraction=0.0,
        max_split_size_mb=128,
        recommended_attention="eager",
        enable_memory_optimization=True,
    )
    default_gpu: GPUProfileSettings = GPUProfileSettings(
        flash_attention_enabled=False,
        cuda_memory_fraction=0.8,
        max_split_size_mb=128,
        recommended_attention="eager",
        enable_memory_optimization=True,
    )


class MediaStorageConfig(BaseModel):
    upload_directory: str = "data/media"
    max_file_size_mb: int = 10
    allowed_extensions: List[str] = Field(
        default_factory=lambda: [".jpg", ".jpeg", ".png", ".gif"]
    )


class MediaStorageSettings(BaseModel):
    config: MediaStorageConfig = Field(default_factory=MediaStorageConfig)


class StartupSettings(BaseModel):
    timeout_seconds: int = 300
    background_initialization: bool = True
    warmup_check_enabled: bool = True
    flash_attention_check_enabled: bool = True
    device_auto_detection: bool = True
    adapter_initialization_order: List[str] = Field(
        default_factory=lambda: ["caption_generator", "object_detector"]
    )
    enable_metrics: bool = True
    verbose_logging: bool = True
    cache_dir: Optional[str] = None


class ContextBuilderSettings(BaseModel):
    max_excerpt_length: int = 500
    caption_prefix: str = "Caption"
    context_prefix: str = "Page Context"
    separator: str = " | "


class DebugSettings(BaseModel):
    enabled: bool = False
    save_face_crops: bool = False
    face_crop_dir: str = "data/debug/face_crops"
    include_metadata: bool = True
    max_crops_per_session: int = 100


class ClusteringSettings(BaseModel):
    algorithm: str = "dbscan"
    distance_threshold: float = 0.6
    min_samples: int = 2
    linkage: str = "average"


class SharedSettings(BaseModel):
    vision_model: VisionModelSettings = Field(default_factory=VisionModelSettings)
    object_detector: ObjectDetectorSettings = Field(default_factory=ObjectDetectorSettings)
    caption_generator: CaptionGeneratorSettings = Field(default_factory=CaptionGeneratorSettings)
    attention: AttentionSettings = Field(default_factory=AttentionSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    caption: CaptionSettings = Field(default_factory=CaptionSettings)
    environment: EnvironmentSettings = Field(default_factory=EnvironmentSettings)
    hardware: HardwareSettings = Field(default_factory=HardwareSettings)
    runtime_optimizations: RuntimeOptimizations = Field(default_factory=RuntimeOptimizations)
    media_storage: MediaStorageSettings = Field(default_factory=MediaStorageSettings)
    startup: StartupSettings = Field(default_factory=StartupSettings)
    context_builder: ContextBuilderSettings = Field(default_factory=ContextBuilderSettings)
    debug: DebugSettings = Field(default_factory=DebugSettings)
    clustering: ClusteringSettings = Field(default_factory=ClusteringSettings)

    class Config:
        extra = "allow"
