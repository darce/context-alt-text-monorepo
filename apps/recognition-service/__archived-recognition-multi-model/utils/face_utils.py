"""Face utilities for recognition service."""

from typing import List, Tuple, Union, Optional
from PIL import Image
import numpy as np
import os
import time
import logging


def crop_face_bboxes(image: Image.Image, bboxes: List[Tuple[int, int, int, int]]) -> List[Image.Image]:
    """
    Crop face regions from image based on bounding boxes.
    
    Args:
        image: PIL Image
        bboxes: List of bounding boxes as (x1, y1, x2, y2) tuples
        
    Returns:
        List of cropped PIL Images
    """
    crops = []
    for bbox in bboxes:
        x1, y1, x2, y2 = bbox
        # Ensure coordinates are within image bounds
        x1 = max(0, min(x1, image.width))
        y1 = max(0, min(y1, image.height))
        x2 = max(0, min(x2, image.width))
        y2 = max(0, min(y2, image.height))
        
        # Skip invalid boxes
        if x2 <= x1 or y2 <= y1:
            continue
            
        crop = image.crop((x1, y1, x2, y2))
        crops.append(crop)
    
    return crops


def crop_face_detections(image: Image.Image, detections: List) -> List[Image.Image]:
    """
    Crop face regions from the image based on detection objects or dicts with 'bbox'.
    
    Args:
        image: PIL Image
        detections: List of detection objects or dicts with 'bbox' attribute/key
        
    Returns:
        List of cropped PIL Images
    """
    bboxes = []
    for d in detections:
        if isinstance(d, dict) and 'bbox' in d:
            bbox = d['bbox']
        elif hasattr(d, 'bbox'):
            bbox = d.bbox
        else:
            continue
        # Convert to tuple of ints
        try:
            coords = tuple(map(int, bbox.tolist())) if hasattr(bbox, 'tolist') else tuple(map(int, bbox))
        except Exception:
            # Fallback if bbox is iterable but not array
            coords = tuple(int(x) for x in bbox)
        bboxes.append(coords)
    return crop_face_bboxes(image, bboxes)


def crop_lower_face_detections(image: Image.Image, detections: List) -> List[Image.Image]:
    """
    Crop the lower half of detected face regions from the image based on detection bboxes.
    This is useful for extracting mouth/chin regions for occlusion-aware recognition.
    
    Args:
        image: PIL Image
        detections: List of detection objects or dicts with 'bbox' attribute/key
        
    Returns:
        List of cropped PIL Images containing lower face regions
    """
    bboxes = []
    for d in detections:
        if isinstance(d, dict) and 'bbox' in d:
            bbox = d['bbox']
        elif hasattr(d, 'bbox'):
            bbox = d.bbox
        else:
            continue
        
        # Convert to tuple of ints
        try:
            coords = tuple(map(int, bbox.tolist())) if hasattr(bbox, 'tolist') else tuple(map(int, bbox))
        except Exception:
            coords = tuple(int(x) for x in bbox)
        
        # Adjust to lower half
        x1, y1, x2, y2 = coords
        mid_y = (y1 + y2) // 2
        lower_bbox = (x1, mid_y, x2, y2)
        bboxes.append(lower_bbox)
    
    return crop_face_bboxes(image, bboxes)


def save_debug_face_crop(image: Image.Image, prefix: str = 'face_crop') -> None:
    """
    Save a debug face crop image to the DEBUG_CROP_DIR if configured.
    Useful for debugging face detection and cropping operations.
    
    Args:
        image: PIL Image to save
        prefix: Filename prefix for the saved image
    """
    base = os.getenv('DEBUG_CROP_DIR')
    if not base:
        return
    try:
        os.makedirs(base, exist_ok=True)
        filename = f"{prefix}_{int(time.time()*1000)}_{np.random.randint(10000)}.png"
        path = os.path.join(base, filename)
        image.save(path)
    except Exception as e:
        logging.debug(f"Could not save debug face crop: {e}")


# Aliases for backward compatibility
crop_detections = crop_face_detections
crop_lower_detections = crop_lower_face_detections
save_debug_crop = save_debug_face_crop


# =============================================================================
# VECTOR NORMALIZATION AND EMBEDDING UTILITIES
# =============================================================================

def normalize_vec(vec: np.ndarray, threshold: float = 0.0) -> np.ndarray:
    """
    L2-normalize a vector unless its norm is <= threshold.
    
    Args:
        vec: Vector to normalize
        threshold: Minimum norm threshold (vectors with norm <= threshold are unchanged)
        
    Returns:
        numpy.ndarray: Normalized vector
    """
    norm = np.linalg.norm(vec)
    return vec / norm if norm > threshold else vec


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray, normalize: bool = True) -> float:
    """
    Compute cosine similarity between two vectors.
    
    Args:
        vec1: First vector
        vec2: Second vector
        normalize: Whether to normalize vectors before computing similarity
        
    Returns:
        float: Cosine similarity score
    """
    if normalize:
        vec1 = normalize_vec(vec1)
        vec2 = normalize_vec(vec2)
    
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))


def cosine_similarity_batch(query_vec: np.ndarray, reference_vecs: np.ndarray, normalize: bool = True) -> np.ndarray:
    """
    Compute cosine similarity between a query vector and a batch of reference vectors.
    
    Args:
        query_vec: Query vector (1D array)
        reference_vecs: Reference vectors (2D array where each row is a vector)
        normalize: Whether to normalize vectors before computing similarity
        
    Returns:
        numpy.ndarray: Array of similarity scores
    """
    if normalize:
        query_vec = normalize_vec(query_vec)
        reference_vecs = np.array([normalize_vec(vec) for vec in reference_vecs])
    
    # Compute cosine similarity using matrix operations
    query_norm = np.linalg.norm(query_vec)
    ref_norms = np.linalg.norm(reference_vecs, axis=1)
    
    # Avoid division by zero
    ref_norms[ref_norms == 0] = 1e-8
    query_norm = max(query_norm, 1e-8)
    
    similarities = np.dot(reference_vecs, query_vec) / (ref_norms * query_norm)
    return similarities


# =============================================================================
# JSON SERIALIZATION UTILITIES
# =============================================================================

def clean_numpy_types(data):
    """
    Recursively clean numpy types from data structure to ensure JSON serialization.
    
    Converts numpy scalar types (np.generic) to native Python types and
    processes nested dictionaries, lists, and tuples recursively.
    
    Args:
        data: Any data structure that may contain numpy types
        
    Returns:
        Cleaned data structure with native Python types
    """
    if isinstance(data, np.generic):
        return data.item()
    elif isinstance(data, dict):
        return {k: clean_numpy_types(v) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        return type(data)(clean_numpy_types(item) for item in data)
    else:
        return data


def clean_metadata_dict(metadata: dict) -> dict:
    """
    Clean numpy types from a metadata dictionary for JSON serialization.
    
    This is a convenience wrapper around clean_numpy_types specifically
    for metadata dictionaries commonly used in face recognition results.
    
    Args:
        metadata: Dictionary that may contain numpy types
        
    Returns:
        Dictionary with numpy types converted to native Python types
    """
    if not metadata:
        return {}
    return clean_numpy_types(metadata)


# =============================================================================
# IMAGE CONVERSION AND PREPROCESSING UTILITIES
# =============================================================================

def to_rgb_array(img):
    """
    Convert a PIL Image or array-like to an RGB numpy array.
    
    Args:
        img: PIL Image or array-like object
        
    Returns:
        numpy.ndarray: RGB array representation
    """
    if hasattr(img, 'convert'):
        return np.array(img.convert('RGB'))
    return np.array(img)


def resize_and_normalize_for_recognition(img: Image.Image, size=(112, 112)) -> np.ndarray:
    """
    Resize image to specified size, convert to float32, normalize to [-1, 1],
    transpose to CHW format and add batch dimension for recognition models.
    
    Args:
        img: PIL Image to process
        size: Target size as (width, height) tuple
        
    Returns:
        numpy.ndarray: Preprocessed array ready for recognition model inference
    """
    if img.mode != 'RGB':
        img = img.convert('RGB')
    resized = img.resize(size, Image.LANCZOS)
    arr = np.array(resized, dtype=np.float32)
    arr = (arr - 127.5) / 127.5  # Normalize to [-1, 1]
    arr = arr.transpose(2, 0, 1)  # HWC -> CHW
    return np.expand_dims(arr, axis=0)


# =============================================================================
# MODEL INFERENCE UTILITIES
# =============================================================================

def extract_with_session(session, input_name: str, arr: np.ndarray):
    """
    Run an ONNX Runtime session inference and return the first output, or None on failure.
    
    Args:
        session: ONNX Runtime session
        input_name: Name of the input tensor
        arr: Input array for inference
        
    Returns:
        Output array or None if inference fails
    """
    try:
        return session.run(None, {input_name: arr})[0]
    except Exception:
        return None


# =============================================================================
# FACE QUALITY AND VALIDATION UTILITIES
# =============================================================================

def validate_face_embedding(embedding: np.ndarray, min_norm: float = 0.1, max_norm: float = 10.0) -> bool:
    """
    Validate that a face embedding meets quality criteria.
    
    Args:
        embedding: Face embedding vector to validate
        min_norm: Minimum acceptable norm
        max_norm: Maximum acceptable norm
        
    Returns:
        bool: True if embedding passes validation
    """
    if embedding is None or len(embedding) == 0:
        return False
    
    # Check for NaN or Inf values
    if np.any(np.isnan(embedding)) or np.any(np.isinf(embedding)):
        return False
    
    # Check norm bounds
    norm = np.linalg.norm(embedding)
    if norm < min_norm or norm > max_norm:
        return False
    
    # Check variance (avoid all-zero or constant vectors)
    variance = np.var(embedding)
    if variance < 1e-6:
        return False
    
    return True


def get_embedding_quality_score(embedding: np.ndarray) -> float:
    """
    Compute a quality score for a face embedding based on various metrics.
    
    Args:
        embedding: Face embedding vector
        
    Returns:
        float: Quality score between 0.0 (poor) and 1.0 (excellent)
    """
    if not validate_face_embedding(embedding):
        return 0.0
    
    # Normalize to ensure consistent scoring
    normalized_emb = normalize_vec(embedding)
    
    # Base score
    score = 0.5
    
    # Reward higher variance (more distinctive features)
    variance = np.var(normalized_emb)
    score += min(variance * 10, 0.3)  # Cap variance contribution at 0.3
    
    # Reward appropriate norm of original embedding
    orig_norm = np.linalg.norm(embedding)
    if 0.5 <= orig_norm <= 2.0:  # Ideal range
        score += 0.2
    elif 0.1 <= orig_norm <= 5.0:  # Acceptable range
        score += 0.1
    
    return min(score, 1.0)
