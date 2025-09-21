import logging
import time
from typing import Dict, Optional, Any, List
from PIL import Image

from analysis.ports.object_detection_base import IObjectDetector
from recognition.domain.interfaces import RecognitionPort
from analysis.ports.caption_generation_base import ICaptionGeneration
from recognition.utils.face_utils import crop_face_detections as crop_detections

class SceneComposer:
    """Core orcestrator for multimodal scene understanding..
    Main business logic coordinating all adapters
    """

    def __init__(
            self,
            object_detector: IObjectDetector,
            entity_identifiers: List[RecognitionPort],
            caption_generator: ICaptionGeneration
        ):
        self.object_detector = object_detector
        self.entity_identifiers = entity_identifiers
        self.caption_generator = caption_generator

        # Ensure caption generator is initialized
        self._ensure_adapters_ready()
        
        logging.info("SceneComposer initialized with adapters")

    def _ensure_adapters_ready(self):
        """Ensure all adapters are properly initialized."""
        if hasattr(self.caption_generator, 'is_ready') and not self.caption_generator.is_ready():
            if hasattr(self.caption_generator, 'initialize'):
                logging.info("Initializing caption generator...")
                self.caption_generator.initialize()
            else:
                logging.warning("Caption generator not ready and has no initialize method")
        
        # Add similar checks for other adapters as needed
        if hasattr(self.object_detector, 'is_ready') and hasattr(self.object_detector, 'initialize'):
            if not self.object_detector.is_ready():
                logging.info("Initializing object detector...")
                self.object_detector.initialize()
        
        # Initialize entity identifier adapters
        for adapter in self.entity_identifiers:
            if hasattr(adapter, 'is_ready') and hasattr(adapter, 'initialize'):
                if not adapter.is_ready():
                    logging.info(f"Initializing entity identifier adapter: {adapter.__class__.__name__}")
                    adapter.initialize()

    def detect_persons(self, image: Image.Image) -> list:
        """
        Detect persons in the image using the object detector (YOLO).
        Returns a list of detections where class_name is 'person'.
        """
        detections = self.object_detector.detect_objects(image)
        # Filter for 'person' class (YOLO standard class name)
        persons = [d for d in detections if d.get('class_name', '').lower() == 'person']
        logging.info(f"SceneComposer.detect_persons: found {len(persons)} persons")
        return persons

    def identify_persons_with_reference(self, image: Image.Image, reference_image: Optional[Image.Image] = None) -> list:
        """
        Detect persons in the image, crop their bounding boxes, and identify faces using the entity_identifier.
        If a reference_image is provided, compare detected persons to the reference face and return match info.
        Returns a list of dicts with bounding box and identification info.
        """
        detections = self.object_detector.detect_objects(image)
        persons = [d for d in detections if d.get('class_name', '').lower() == 'person']
        logging.info(f"SceneComposer.identify_persons_with_reference: found {len(persons)} persons")
        if not persons:
            return []

        cropped_images = crop_detections(image, persons)

        # If reference image is provided, extract its embedding
        reference_embedding = None
        if reference_image is not None:
            ref_identities = self.entity_identifiers[0].identify_entities(reference_image)
            if ref_identities and 'embedding' in ref_identities[0]:
                reference_embedding = ref_identities[0]['embedding']

        results = []
        for person, crop in zip(persons, cropped_images):
            identities = self.entity_identifiers[0].identify_entities(crop)
            match_score = None
            if reference_embedding is not None and identities:
                # Compare the first detected face in crop to the reference embedding
                candidate_embedding = identities[0].get('embedding')
                if candidate_embedding is not None:
                    # Use the compare_embeddings method from the model
                    match_score = self.entity_identifiers[0].model.compare_embeddings(
                        candidate_embedding, reference_embedding
                    )
            results.append({
                "bbox": person.get("bbox"),
                "confidence": person.get("confidence"),
                "class_id": person.get("class_id"),
                "class_name": person.get("class_name"),
                "identities": identities,
                "reference_match_score": match_score
            })
        return results