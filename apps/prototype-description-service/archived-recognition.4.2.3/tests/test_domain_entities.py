import numpy as np

from recognition.domain.entities import IdentityDetection, IdentityEmbedding


def test_identity_detection_area_handles_positive_dimensions():
    detection = IdentityDetection(bbox=(0, 0, 10, 20), confidence=0.8)

    assert detection.area() == 200


def test_identity_detection_area_clamps_negative_dimensions():
    detection = IdentityDetection(bbox=(10, 10, 5, 5), confidence=0.4)

    assert detection.area() == 0


def test_identity_embedding_to_list_round_trips_numpy_array():
    detection = IdentityDetection(bbox=(0, 0, 1, 1), confidence=1.0)
    vector = np.arange(5, dtype=np.float32)
    embedding = IdentityEmbedding(embedding=vector, detection=detection)

    assert embedding.to_list() == vector.tolist()
