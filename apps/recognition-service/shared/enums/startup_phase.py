from enum import Enum

class StartupPhase(Enum):
    """Enumeration of startup phases for tracking progress."""
    IDLE = "idle"
    ENVIRONMENT_SETUP = "environment_setup"
    FLASH_ATTENTION_CHECK = "flash_attention_check"
    DEVICE_DETECTION = "device_detection"
    WARMUP_DETECTION = "warmup_detection"
    ADAPTER_CREATION = "adapter_creation"
    SCENE_COMPOSER_INIT = "scene_composer_init"
    ROUTE_INJECTION = "route_injection"
    COMPLETED = "completed"
    FAILED = "failed"
