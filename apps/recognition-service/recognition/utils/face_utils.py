"""
Face Utilities

Utility functions for face processing and similarity calculations.
"""

import numpy as np
from typing import Any


def cosine_similarity(embedding1: np.ndarray, embedding2: np.ndarray) -> float:
    """
    Calculate cosine similarity between two embeddings.
    
    Args:
        embedding1: First embedding vector
        embedding2: Second embedding vector
        
    Returns:
        Cosine similarity score between -1 and 1
    """
    # Normalize embeddings
    norm1 = np.linalg.norm(embedding1)
    norm2 = np.linalg.norm(embedding2)
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    normalized1 = embedding1 / norm1
    normalized2 = embedding2 / norm2
    
    # Calculate cosine similarity
    return float(np.dot(normalized1, normalized2))


def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    """
    Normalize an embedding vector to unit length.
    
    Args:
        embedding: Embedding vector to normalize
        
    Returns:
        Normalized embedding vector
    """
    norm = np.linalg.norm(embedding)
    if norm == 0:
        return embedding
    return embedding / norm


def to_rgb_array(image) -> np.ndarray:
    """
    Convert image to RGB numpy array.
    
    Args:
        image: PIL Image or numpy array
        
    Returns:
        RGB numpy array
    """
    from PIL import Image
    
    if isinstance(image, Image.Image):
        if image.mode != 'RGB':
            image = image.convert('RGB')
        return np.array(image)
    elif isinstance(image, np.ndarray):
        return image
    else:
        raise ValueError(f"Unsupported image type: {type(image)}")


def normalize_vec(vec: np.ndarray) -> np.ndarray:
    """
    Alias for normalize_embedding for compatibility.
    """
    return normalize_embedding(vec)


def clean_numpy_types(obj: Any) -> Any:
    """
    Clean numpy types from objects for JSON serialization.
    
    Args:
        obj: Object that may contain numpy types
        
    Returns:
        Object with numpy types converted to native Python types
    """
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: clean_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [clean_numpy_types(item) for item in obj]
    else:
        return obj


def crop_face_detections(image, face_detections, target_size=(224, 224)):
    """
    Crop face regions from an image based on face detections.
    
    Args:
        image: PIL Image or numpy array
        face_detections: List of face detection objects with bounding_box attribute
        target_size: Tuple of (width, height) for output crops
        
    Returns:
        List of cropped face images
    """
    from PIL import Image
    import numpy as np
    
    # Convert to PIL if necessary
    if isinstance(image, np.ndarray):
        image = Image.fromarray(image)
    
    cropped_faces = []
    
    for detection in face_detections:
        bbox = detection.bounding_box
        
        # Extract bounding box coordinates
        x1, y1, x2, y2 = int(bbox.x1), int(bbox.y1), int(bbox.x2), int(bbox.y2)
        
        # Ensure coordinates are within image bounds
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(image.width, x2)
        y2 = min(image.height, y2)
        
        # Crop the face region
        face_crop = image.crop((x1, y1, x2, y2))
        
        # Resize to target size if specified
        if target_size:
            face_crop = face_crop.resize(target_size, Image.Resampling.LANCZOS)
        
        cropped_faces.append(face_crop)
    
    return cropped_faces
