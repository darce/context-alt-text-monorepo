
import pytest
import numpy as np
from unittest.mock import Mock
from recognition.domain.identity import MediaIdentity
from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.settings import ClusteringSettings

class MockSettings:
    similarity_threshold = 0.55
    complete_link_min_floor = 0.80  # High confidence threshold

@pytest.fixture
def discovery():
    return RepresentativeDiscovery(settings=MockSettings())

def make_identity(id_val, vector):
    return MediaIdentity(
        id=id_val,
        tenant_id="tenant-1",
        media_id="media-1",
        embedding=vector.tolist(),
        confidence=0.99,
        bbox_width=100,
        bbox_height=100
    )

@pytest.mark.asyncio
async def test_high_confidence_unlabeled_auto_assigns(discovery):
    """If match is high confidence (>= 0.80), accept Unlabeled cluster."""
    # Setup: 
    # - Identity vector [1, 0]
    # - Unlabeled Cluster A: [1, 0] (Sim 1.0) -> High Confidence
    # - Labeled Cluster B: [0.6, 0.8] (Sim 0.6) -> Low Confidence
    
    identity = make_identity("id1", np.array([1.0, 0.0], dtype=np.float32))
    
    reps = {
        "cluster_unlabeled": [np.array([1.0, 0.0], dtype=np.float32)],
        "cluster_labeled": [np.array([0.6, 0.8], dtype=np.float32)], # Sim 0.6
    }
    labeled_ids = {"cluster_labeled"}
    
    candidates = await discovery.discover([identity], reps, labeled_ids)
    
    assert len(candidates) == 1
    # Should pick Unlabeled because 1.0 >= 0.80
    assert candidates[0].cluster_id == "cluster_unlabeled"
    assert candidates[0].discovery_similarity > 0.99

@pytest.mark.asyncio
async def test_low_confidence_prefers_labeled(discovery):
    """If match is low confidence (< 0.80), prefer Labeled cluster over Unlabeled."""
    # Setup:
    # - Identity vector [1, 0]
    # - Unlabeled Cluster A: [0.99, 0.14] (Sim ~0.70) -> Highest but < 0.80
    # - Labeled Cluster B: [0.97, 0.24] (Sim ~0.60) -> Lower but > 0.55
    
    identity = make_identity("id1", np.array([1.0, 0.0], dtype=np.float32))
    
    # cos(45) = 0.707
    vec_unlabeled = np.array([0.75, 0.66], dtype=np.float32) 
    vec_unlabeled /= np.linalg.norm(vec_unlabeled) # Sim ~0.75 to [1,0]
    
    # cos(53) = 0.60
    vec_labeled = np.array([0.60, 0.80], dtype=np.float32) # Sim 0.60 to [1,0]
    
    reps = {
        "cluster_unlabeled": [vec_unlabeled],
        "cluster_labeled": [vec_labeled],
    }
    labeled_ids = {"cluster_labeled"}
    
    candidates = await discovery.discover([identity], reps, labeled_ids)
    
    assert len(candidates) == 1
    # Should pick LABELED because 0.75 is NOT >= 0.80 (High Conf), so logic prefers labeled
    assert candidates[0].cluster_id == "cluster_labeled"
    assert 0.59 < candidates[0].discovery_similarity < 0.61

@pytest.mark.asyncio
async def test_no_labeled_fallback_to_unlabeled(discovery):
    """If match is low confidence and no labeled match, return Unlabeled."""
    identity = make_identity("id1", np.array([1.0, 0.0], dtype=np.float32))
    
    vec_unlabeled = np.array([0.75, 0.66], dtype=np.float32) 
    vec_unlabeled /= np.linalg.norm(vec_unlabeled) # Sim ~0.75
    
    reps = {
        "cluster_unlabeled": [vec_unlabeled],
    }
    labeled_ids = set() # No labeled clusters
    
    candidates = await discovery.discover([identity], reps, labeled_ids)
    
    assert len(candidates) == 1
    assert candidates[0].cluster_id == "cluster_unlabeled"
