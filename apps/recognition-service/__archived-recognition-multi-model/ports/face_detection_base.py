"""Face detection interface for backward compatibility."""

from abc import ABC, abstractmethod
from typing import List, Union
from PIL import Image
import numpy as np

from ..domain.entities import FaceDetection


class IFaceDetection(ABC):
    """Abstract face detection interface for backward compatibility."""
    
    @abstractmethod
    def detect_faces(self, image: Union[Image.Image, np.ndarray]) -> List[FaceDetection]:
        """
        Detect faces in an image.
        
        Args:
            image: Input image
            
        Returns:
            List of face detections
        """
        pass
