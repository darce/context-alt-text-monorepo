"""
Discovery algorithms that propose assignment candidates.
"""

from recognition.application.discovery.base import DiscoveryAlgorithm
from recognition.application.discovery.centroid import CentroidDiscovery
from recognition.application.discovery.graph import GraphAlgorithm, GraphDiscovery
from recognition.application.discovery.representative import RepresentativeDiscovery

__all__ = [
    "CentroidDiscovery",
    "DiscoveryAlgorithm",
    "GraphAlgorithm",
    "GraphDiscovery",
    "RepresentativeDiscovery",
]
