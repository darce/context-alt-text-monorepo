import logging
from ultralytics import YOLO
import platform
import os
from typing import Any, Dict
from shared.infrastructure.gpu_manager import get_gpu_manager
from shared.utils.device_utils import get_available_device

def load_yolo_model(model_path: str, device: str = None, config: Dict[str, Any] = None) -> Any:
    """
    Loads a YOLO model with the given configuration and device settings.
    All config must be passed in from settings.py via the factory.
    Device is resolved using gpu_core.
    """
    yolo_settings = config.get('settings', {})
    verbose = yolo_settings.get('verbose', False)
    force_cpu_on_macos = yolo_settings.get('force_cpu_on_macos', True)

    # Set environment variables
    os.environ['YOLO_VERBOSE'] = str(verbose).lower()
    if 'YOLO_CONFIG_DIR' in os.environ:
        os.environ['YOLO_CONFIG_DIR'] = os.environ['YOLO_CONFIG_DIR']
    # Do not set a default here; must be set in Dockerfile or environment

    if device is None:
        device = get_available_device()

    # Device resolution using gpu_core
    resolved_device = get_gpu_manager().resolve_device_spec(device)
    logging.info(f"[YOLO-LOADER] Device resolved for YOLO: {device} -> {resolved_device}")

    logging.info(f"[YOLO-LOADER] Loading YOLO model from {model_path}")
    model = YOLO(model_path, verbose=verbose)

    # Device assignment
    if (platform.system() == "Darwin" and force_cpu_on_macos) or resolved_device == "cpu":
        model.to("cpu")
        logging.info("[YOLO-LOADER] YOLO model loaded on CPU (macOS compatibility)")
        return model, "cpu"
    else:
        try:
            model.to(resolved_device)
            logging.info(f"[YOLO-LOADER] YOLO model loaded on {resolved_device}")
            return model, resolved_device
        except Exception as device_error:
            logging.warning(f"[YOLO-LOADER] Failed to load on {resolved_device}, falling back to CPU: {device_error}")
            model.to("cpu")
            return model, "cpu"
