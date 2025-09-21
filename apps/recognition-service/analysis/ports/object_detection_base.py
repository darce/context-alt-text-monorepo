from abc import ABC, abstractmethod
from PIL import Image
from typing import List, Dict, Tuple, Optional

class IObjectDetector(ABC):
    @abstractmethod
    def detect_objects(self, image: Image.Image) -> List[Dict[str, float]]:
        """
        Detect objects in the given image.

        :param image: The input image to process.
        :return: A list of dictionaries containing detected objects and their confidence scores.
        """
        pass

    @abstractmethod
    def crop_objects(
            self,
            image: Image.Image,
            detections: List[Dict[str, float]],
            labels: Optional[List[str]] = None
        ) -> List[Image.Image]:
        """
        Crop detected objects from the image.

        :param image: The input image to process.
        :param detections: A list of dictionaries containing detected objects and their bounding boxes.
        :return: A list of cropped images of the detected objects.
        """
        pass