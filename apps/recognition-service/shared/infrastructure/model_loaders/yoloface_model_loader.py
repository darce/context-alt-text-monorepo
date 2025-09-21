import logging
from typing import Tuple, Dict, Any

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None
    logging.warning("ultralytics package not installed. YOLOFace adapter will fail to load model.")


def load_yoloface_model(model_path: str, device: str, config: Dict[str, Any]) -> Tuple[Any, str]:
    """
    Load a YOLO-based face detection model (yoloface) and prepare it for inference.
    Returns a tuple of (model, device).
    """
    if YOLO is None:
        raise RuntimeError("YOLO model loader requires the ultralytics package.")
    try:
        model = YOLO(model_path)
        # Move model to target device if supported
        if hasattr(model, 'to'):
            model.to(device)
        logging.info(f"[YOLOFace-LOADER] Loaded model from {model_path} on device {device}")
        return model, device
    except Exception as e:
        logging.error(f"[YOLOFace-LOADER] Failed to load model: {e}")
        raise
