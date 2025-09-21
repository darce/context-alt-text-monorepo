"""
Face Aligner Implementation
Concrete implementation of face alignment using MTCNN and built-in strategies.
"""
import logging
from typing import Optional, Union
import numpy as np
from PIL import Image
import cv2

from ..domain import FaceAligner, FaceDetection, AlignmentStrategy

logger = logging.getLogger(__name__)


class FaceAlignerImpl(FaceAligner):
    """
    Face alignment implementation supporting multiple strategies.
    
    Strategies:
    - MTCNN: Uses MTCNN landmarks for alignment (AdaFace, ArcFace)
    - Built-in: Uses model's built-in alignment (InsightFace)
    """
    
    def __init__(self):
        """Initialize face aligner."""
        self.mtcnn = None
        self._init_mtcnn()
    
    def _init_mtcnn(self):
        """Initialize MTCNN for landmark detection."""
        try:
            # Try to import and initialize MTCNN
            from mtcnn import MTCNN
            self.mtcnn = MTCNN()
            logger.info("✅ MTCNN initialized for face alignment")
        except ImportError:
            logger.warning("❌ MTCNN not available, using basic alignment")
            self.mtcnn = None
    
    def align_face(self, image: Union[Image.Image, np.ndarray], 
                  detection: FaceDetection) -> Optional[np.ndarray]:
        """
        Align a detected face for recognition.
        
        Args:
            image: Input image containing the face
            detection: Face detection result with bbox and landmarks
            
        Returns:
            Aligned face image as numpy array, or None if alignment fails
        """
        try:
            # Convert PIL to numpy if needed
            if isinstance(image, Image.Image):
                image = np.array(image)
            
            # Extract face region using bounding box
            bbox = detection.bbox
            x, y, w, h = bbox
            
            # Ensure coordinates are within image bounds
            x = max(0, int(x))
            y = max(0, int(y))
            w = min(image.shape[1] - x, int(w))
            h = min(image.shape[0] - y, int(h))
            
            if w <= 0 or h <= 0:
                logger.warning("Invalid bounding box for face extraction")
                return None
            
            # Extract face
            face = image[y:y+h, x:x+w]
            
            # Apply alignment based on available landmarks
            if detection.landmarks and len(detection.landmarks) >= 5:
                # Use provided landmarks for alignment
                aligned_face = self._align_with_landmarks(face, detection.landmarks, bbox)
            elif self.mtcnn:
                # Use MTCNN to detect landmarks
                aligned_face = self._align_with_mtcnn(face)
            else:
                # Basic resize alignment
                aligned_face = self._basic_alignment(face)
            
            return aligned_face
            
        except Exception as e:
            logger.error(f"Face alignment failed: {e}")
            return None
    
    def _align_with_landmarks(self, face: np.ndarray, landmarks: list, bbox: list) -> np.ndarray:
        """
        Align face using provided landmarks.
        
        Args:
            face: Face image
            landmarks: Face landmarks
            bbox: Bounding box used for extraction
            
        Returns:
            Aligned face image
        """
        try:
            # Convert landmarks to numpy array
            landmarks = np.array(landmarks)
            
            # Adjust landmarks to face coordinate system
            x, y, _, _ = bbox
            landmarks[:, 0] -= x
            landmarks[:, 1] -= y
            
            # Define target landmarks for alignment (112x112 face)
            target_landmarks = np.array([
                [30.2946, 51.6963],  # Left eye
                [65.5318, 51.5014],  # Right eye
                [48.0252, 71.7366],  # Nose tip
                [33.5493, 92.3655],  # Left mouth corner
                [62.7299, 92.2041]   # Right mouth corner
            ])
            
            # Calculate transformation matrix
            transform_matrix = self._get_transform_matrix(landmarks[:5], target_landmarks)
            
            # Apply transformation
            aligned_face = cv2.warpAffine(face, transform_matrix, (112, 112))
            
            return aligned_face
            
        except Exception as e:
            logger.error(f"Landmark alignment failed: {e}")
            return self._basic_alignment(face)
    
    def _align_with_mtcnn(self, face: np.ndarray) -> np.ndarray:
        """
        Align face using MTCNN landmark detection.
        
        Args:
            face: Face image
            
        Returns:
            Aligned face image
        """
        try:
            # Detect landmarks with MTCNN
            results = self.mtcnn.detect_faces(face)
            
            if results and len(results) > 0:
                # Use first detection
                detection = results[0]
                landmarks = detection['keypoints']
                
                # Convert to array format
                landmark_array = np.array([
                    [landmarks['left_eye'][0], landmarks['left_eye'][1]],
                    [landmarks['right_eye'][0], landmarks['right_eye'][1]],
                    [landmarks['nose'][0], landmarks['nose'][1]],
                    [landmarks['mouth_left'][0], landmarks['mouth_left'][1]],
                    [landmarks['mouth_right'][0], landmarks['mouth_right'][1]]
                ])
                
                # Define target landmarks
                target_landmarks = np.array([
                    [30.2946, 51.6963],  # Left eye
                    [65.5318, 51.5014],  # Right eye
                    [48.0252, 71.7366],  # Nose tip
                    [33.5493, 92.3655],  # Left mouth corner
                    [62.7299, 92.2041]   # Right mouth corner
                ])
                
                # Calculate transformation matrix
                transform_matrix = self._get_transform_matrix(landmark_array, target_landmarks)
                
                # Apply transformation
                aligned_face = cv2.warpAffine(face, transform_matrix, (112, 112))
                
                return aligned_face
            
            # Fall back to basic alignment if no landmarks found
            return self._basic_alignment(face)
            
        except Exception as e:
            logger.error(f"MTCNN alignment failed: {e}")
            return self._basic_alignment(face)
    
    def _basic_alignment(self, face: np.ndarray) -> np.ndarray:
        """
        Basic face alignment using simple resize.
        
        Args:
            face: Face image
            
        Returns:
            Aligned face image (112x112)
        """
        try:
            # Simple resize to 112x112
            aligned_face = cv2.resize(face, (112, 112))
            return aligned_face
        except Exception as e:
            logger.error(f"Basic alignment failed: {e}")
            # Return original if resize fails
            return face
    
    def _get_transform_matrix(self, src_landmarks: np.ndarray, 
                             target_landmarks: np.ndarray) -> np.ndarray:
        """
        Calculate affine transformation matrix for alignment.
        
        Args:
            src_landmarks: Source landmarks
            target_landmarks: Target landmarks
            
        Returns:
            2x3 transformation matrix
        """
        try:
            # Use similarity transform (preserves angles)
            transform_matrix = cv2.estimateAffinePartial2D(
                src_landmarks.astype(np.float32),
                target_landmarks.astype(np.float32)
            )[0]
            
            if transform_matrix is None:
                # Fall back to affine transform
                transform_matrix = cv2.getAffineTransform(
                    src_landmarks[:3].astype(np.float32),
                    target_landmarks[:3].astype(np.float32)
                )
            
            return transform_matrix
            
        except Exception as e:
            logger.error(f"Transform matrix calculation failed: {e}")
            # Return identity matrix as fallback
            return np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
