"""
Recognition Service Core Domain Logic
Main business logic for face recognition operations.
"""
import logging
import time
from typing import List, Optional, Dict, Any, Union
import numpy as np
from PIL import Image
from scipy.spatial.distance import cosine

from .entities import (
    FaceDetection, FaceEmbedding, RecognitionMatch, 
    RecognitionResult, SceneAnalysisResult, ModelType
)
from .dto import SceneAnalysisDTO, scene_analysis_result_to_dto
from .interfaces import (
    FaceAligner, QualityScorer, EmbeddingRouter, CVLFaceAdapter, RecognitionPort
)

logger = logging.getLogger(__name__)


class RecognitionService(RecognitionPort):
    """
    Core recognition service implementing business logic.
    Orchestrates face detection, alignment, embedding, and matching.
    """
    
    def __init__(self, face_aligner: FaceAligner, quality_scorer: QualityScorer,
                 embedding_router: EmbeddingRouter, adapters: Dict[ModelType, CVLFaceAdapter]):
        """
        Initialize recognition service.
        
        Args:
            face_aligner: Face alignment strategy
            quality_scorer: Quality scoring strategy  
            embedding_router: Embedding routing strategy
            adapters: Dictionary of model adapters
        """
        self.face_aligner = face_aligner
        self.quality_scorer = quality_scorer
        self.embedding_router = embedding_router
        self.adapters = adapters
        
        logger.info(f"🔧 RecognitionService initialized with {len(adapters)} adapters")
    
    async def analyze_scene(self, image: Union[Image.Image, np.ndarray],
                           model_type: ModelType, threshold: float) -> SceneAnalysisResult:
        """
        Analyze a scene for face recognition.
        
        Args:
            image: Input image to analyze
            model_type: Model type to use for recognition
            threshold: Recognition threshold
            
        Returns:
            Complete scene analysis result
        """
        start_time = time.time()
        
        logger.debug(f"🎯 [RECOGNITION] Starting scene analysis with model={model_type}, threshold={threshold}")
        logger.debug(f"🖼️ [RECOGNITION] Input image type: {type(image)}, shape: {getattr(image, 'size', getattr(image, 'shape', 'unknown'))}")
        
        # Get appropriate adapter
        adapter = self._get_adapter(model_type)
        logger.debug(f"🔌 [RECOGNITION] Using adapter: {type(adapter).__name__}")
        
        # Detect faces
        detections = adapter.detect_faces(image)
        logger.debug(f"👤 [RECOGNITION] Detected {len(detections)} faces")
        
        if len(detections) == 0:
            logger.warning(f"⚠️ [RECOGNITION] No faces detected in image with {type(adapter).__name__}")
        
        # Process each detected face
        results = []
        for i, detection in enumerate(detections):
            logger.debug(f"🔍 [RECOGNITION] Processing face {i+1}/{len(detections)}")
            result = await self._process_face(image, detection, adapter, threshold)
            results.append(result)
            
            if result.matches:
                logger.debug(f"✅ [RECOGNITION] Face {i+1} has {len(result.matches)} matches, best: {result.matches[0].confidence:.3f}")
            else:
                logger.debug(f"❌ [RECOGNITION] Face {i+1} has no matches")
        
        processing_time = (time.time() - start_time) * 1000  # Convert to ms
        logger.debug(f"⏱️ [RECOGNITION] Analysis completed in {processing_time:.1f}ms")
        
        return SceneAnalysisResult(
            faces=results,
            model_type=model_type,
            threshold=threshold,
            processing_time_ms=processing_time
        )
    
    async def analyze_scene_dto(self, image: Union[Image.Image, np.ndarray],
                               model_type: ModelType, threshold: float) -> SceneAnalysisDTO:
        """
        Analyze a scene for face recognition and return a DTO.
        
        This method provides a clean, serializable interface for external consumers.
        
        Args:
            image: Input image to analyze
            model_type: Model type to use for recognition
            threshold: Recognition threshold
            
        Returns:
            Scene analysis result as DTO
        """
        # Use the existing internal method
        internal_result = await self.analyze_scene(image, model_type, threshold)
        
        # Convert to DTO
        return scene_analysis_result_to_dto(internal_result, model_type, threshold)
    
    async def _process_face(self, image: Union[Image.Image, np.ndarray],
                           detection: FaceDetection, adapter: CVLFaceAdapter,
                           threshold: float) -> RecognitionResult:
        """
        Process a single detected face.
        
        Args:
            image: Original image
            detection: Face detection result
            adapter: Model adapter to use
            threshold: Recognition threshold
            
        Returns:
            Recognition result for the face
        """
        logger.debug(f"🔄 [RECOGNITION] Processing face detection: bbox={getattr(detection, 'bbox', 'unknown')}")
        
        # Convert PIL to numpy if needed
        if isinstance(image, Image.Image):
            image_array = np.array(image)
        else:
            image_array = image
        
        logger.debug(f"🖼️ [RECOGNITION] Converted image to array: {image_array.shape}, dtype={image_array.dtype}")
        
        # Align face
        aligned_face = self.face_aligner.align_face(image_array, detection)
        if aligned_face is None:
            logger.warning("❌ [RECOGNITION] Face alignment failed")
            return RecognitionResult(detection=detection)
        
        logger.debug(f"✅ [RECOGNITION] Face aligned: shape={aligned_face.shape}, dtype={aligned_face.dtype}")
        
        # Extract embedding - use different methods based on adapter type
        if hasattr(adapter, 'extract_embedding_from_detection'):
            # InsightFace and similar adapters that prefer detection-based extraction
            logger.debug(f"🔌 [RECOGNITION] Using detection-based embedding extraction for {type(adapter).__name__}")
            embedding_array = adapter.extract_embedding_from_detection(image_array, detection)
            if embedding_array is not None:
                from .entities import FaceEmbedding
                # Use detection confidence for embedding confidence
                embedding = FaceEmbedding(
                    embedding=embedding_array,
                    confidence=detection.confidence,
                    model_type=adapter.get_model_type()
                )
            else:
                embedding = None
        else:
            # Traditional adapters that work with aligned faces
            logger.debug(f"🔌 [RECOGNITION] Using aligned face embedding extraction for {type(adapter).__name__}")
            embedding = adapter.extract_embedding(aligned_face)
            
        if embedding is None:
            logger.warning("❌ [RECOGNITION] Embedding extraction failed")
            return RecognitionResult(detection=detection)
        
        logger.debug(f"🧠 [RECOGNITION] Embedding extracted: shape={len(embedding.embedding)}, first_5={embedding.embedding[:5].tolist()}")
        
        # Calculate quality score for AdaFace models
        if adapter.get_model_type() == ModelType.ADAFACE_IR101:
            quality_score = self.quality_scorer.calculate_quality(aligned_face, embedding.embedding)
            embedding.quality_score = quality_score
            logger.debug(f"⭐ [RECOGNITION] AdaFace quality score: {quality_score:.3f}")
        
        # Find matches
        matches = self._find_matches(embedding, adapter.get_model_type(), threshold)
        logger.debug(f"🎯 [RECOGNITION] Found {len(matches)} potential matches")
        
        return RecognitionResult(
            detection=detection,
            embedding=embedding,
            matches=matches
        )
    
    def _find_matches(self, embedding: FaceEmbedding, model_type: ModelType,
                     threshold: float) -> List[RecognitionMatch]:
        """
        Find matches for a face embedding.
        
        Args:
            embedding: Face embedding to match
            model_type: Model type used for embedding
            threshold: Recognition threshold
            
        Returns:
            List of recognition matches
        """
        # Get roster embeddings for this model
        roster_embeddings = self.embedding_router.get_embeddings(model_type)
        logger.debug(f"📇 [RECOGNITION] Roster embeddings for {model_type}: {len(roster_embeddings) if roster_embeddings else 0} entries")
        
        if not roster_embeddings:
            logger.warning(f"❌ [RECOGNITION] No roster embeddings available for {model_type}")
            return []
        
        # Log first few roster names for debugging
        if roster_embeddings:
            roster_names = list(roster_embeddings.keys())[:3]
            logger.debug(f"📇 [RECOGNITION] Sample roster names: {roster_names}...")
        
        matches = []
        query_embedding = embedding.embedding
        
        for person_name, roster_embedding in roster_embeddings.items():
            # Calculate similarity (using cosine distance)
            distance = cosine(query_embedding, roster_embedding)
            confidence = 1.0 - distance
            
            logger.debug(f"🔍 [RECOGNITION] {person_name}: distance={distance:.4f}, confidence={confidence:.4f}")
            
            # Apply quality-aware threshold adjustment for AdaFace
            effective_threshold = threshold
            if (model_type == ModelType.ADAFACE_IR101 and 
                embedding.quality_score is not None):
                effective_threshold = self._adjust_threshold_for_quality(
                    threshold, embedding.quality_score
                )
                logger.debug(f"⭐ [RECOGNITION] AdaFace threshold adjusted: {threshold:.3f} -> {effective_threshold:.3f}")
            
            # Always add the match, but indicate if it meets the threshold
            meets_threshold = confidence >= effective_threshold
            logger.debug(f"🎯 [RECOGNITION] {person_name}: meets_threshold={meets_threshold} (conf={confidence:.3f} >= thresh={effective_threshold:.3f})")
            
            matches.append(RecognitionMatch(
                person_name=person_name,
                confidence=confidence,
                distance=distance,
                embedding=embedding,
                meets_threshold=meets_threshold,
                effective_threshold=effective_threshold
            ))
        
        # Sort by confidence (descending)
        matches.sort(key=lambda x: x.confidence, reverse=True)
        
        best_conf = matches[0].confidence if matches else 0.0
        logger.debug(f"🏆 [RECOGNITION] Returning {len(matches)} matches, best: {best_conf:.3f}")
        
        return matches
    
    def _adjust_threshold_for_quality(self, base_threshold: float, quality_score: float) -> float:
        """
        Adjust threshold based on quality score for AdaFace.
        
        Args:
            base_threshold: Base recognition threshold
            quality_score: Quality score of the face
            
        Returns:
            Adjusted threshold
        """
        # AdaFace quality-adaptive margin: lower threshold for higher quality
        # Higher quality faces get more lenient thresholds
        quality_factor = 0.1  # Maximum adjustment factor
        adjustment = quality_factor * (quality_score - 0.5)  # Center around 0.5
        adjusted_threshold = base_threshold - adjustment
        
        # Clamp to reasonable bounds
        return max(0.1, min(0.9, adjusted_threshold))
    
    def _get_adapter(self, model_type: ModelType) -> CVLFaceAdapter:
        """
        Get adapter for model type.
        
        Args:
            model_type: Model type to get adapter for
            
        Returns:
            Model adapter
            
        Raises:
            ValueError: If model type not supported
        """
        logger.debug(f"🔌 [RECOGNITION] Requesting adapter for model_type: {model_type}")
        
        if model_type not in self.adapters:
            available_models = list(self.adapters.keys())
            logger.error(f"❌ [RECOGNITION] Unsupported model type: {model_type}, available: {available_models}")
            raise ValueError(f"Unsupported model type: {model_type}")
        
        adapter = self.adapters[model_type]
        logger.debug(f"✅ [RECOGNITION] Found adapter: {type(adapter).__name__}")
        return adapter
    
    def identify_entities(self, image: Union[Image.Image, np.ndarray]) -> List[Dict[str, Any]]:
        """
        Legacy method for backward compatibility with scene analysis service.
        Synchronous version that doesn't use async/await to avoid event loop issues.
        
        Args:
            image: Input image
            
        Returns:
            List of identity dictionaries with name and recognition_score
        """
        try:
            # Use default model and threshold for legacy compatibility
            default_model = ModelType.INSIGHTFACE_W600K
            default_threshold = 0.5
            
            # Perform synchronous face recognition
            adapter = self._get_adapter(default_model)
            
            # Detect faces
            detections = adapter.detect_faces(image)
            logger.debug(f"Legacy identify_entities detected {len(detections)} faces")
            
            if not detections:
                return []
            
            identities = []
            
            # Process each detected face
            for detection in detections:
                try:
                    # Extract embedding
                    embedding = adapter.extract_embedding(image, detection)
                    if embedding is None:
                        logger.warning("Failed to extract embedding for face")
                        continue
                    
                    # Find matches in roster
                    matches = self._find_matches(embedding, default_model, default_threshold)
                    
                    if matches:
                        # Use the best match
                        best_match = matches[0]
                        identity_dict = {
                            "name": best_match.identity_name,
                            "recognition_score": best_match.confidence,
                            "unique_id": getattr(best_match, 'unique_id', ''),
                            "metadata": getattr(best_match, 'metadata', {})
                        }
                        identities.append(identity_dict)
                    else:
                        # No match above threshold
                        identity_dict = {
                            "name": "unknown",
                            "recognition_score": 0.0,
                            "unique_id": "",
                            "metadata": {}
                        }
                        identities.append(identity_dict)
                        
                except Exception as e:
                    logger.error(f"Error processing face detection: {e}")
                    continue
            
            logger.debug(f"Legacy identify_entities returning {len(identities)} identities")
            return identities
            
        except Exception as e:
            logger.error(f"Error in legacy identify_entities: {e}")
            return []
