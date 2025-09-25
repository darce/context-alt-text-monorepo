"""
Recognition Utils Module
"""

"""Utility exports for recognition core."""

from .face_utils import (
    cosine_similarity,
    normalize_embedding,
    to_rgb_array,
    normalize_vec,
    clean_numpy_types,
)

# Import conversion lazily to avoid circular dependencies

def convert_to_analysis_format(*args, **kwargs):
    from .conversion import convert_to_analysis_format as _convert

    return _convert(*args, **kwargs)

__all__ = [
    "convert_to_analysis_format",
    "clean_numpy_types", 
    "cosine_similarity",
    "normalize_embedding",
    "to_rgb_array",
    "normalize_vec"
]
