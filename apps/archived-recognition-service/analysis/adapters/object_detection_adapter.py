import logging
from typing import List, Dict, Optional
from PIL import Image
from analysis.ports.object_detection_base import IObjectDetector

class ObjectDetectionAdapter(IObjectDetector):
    """
    Fallback/stub implementation of object detection adapter.
    This is used when no specific adapter type is configured.
    """
    def __init__(self):
        self._ready = True
        logging.info("ObjectDetectionAdapter (stub) initialized")

    def initialize(self):
        """Stub implementation - already ready."""
        pass

    def is_ready(self) -> bool:
        """Always ready for this stub implementation."""
        return self._ready

    def detect_objects(self, image: Image.Image) -> List[Dict]:
        """
        Stub implementation that returns empty results.
        """
        logging.warning("Using stub ObjectDetectionAdapter - no actual object detection performed")
        return []

    def crop_objects(self, image: Image.Image, detections: List[Dict], labels: Optional[List[str]] = None) -> List[Image.Image]:
        """
        Stub implementation that returns empty list.
        """
        logging.warning("Using stub ObjectDetectionAdapter - no cropping performed")
        return []
