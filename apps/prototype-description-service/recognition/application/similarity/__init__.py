"""Similarity search utilities for clustering and suggestions."""

from recognition.application.similarity.batch import batch_similarity_matrix
from recognition.application.similarity.cache import RepresentativeCache
from recognition.application.similarity.search import SimilaritySearch
from recognition.application.similarity.types import MatchResult

__all__ = ["MatchResult", "RepresentativeCache", "SimilaritySearch", "batch_similarity_matrix"]
