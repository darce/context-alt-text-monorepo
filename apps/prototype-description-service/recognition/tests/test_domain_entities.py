import numpy as np

from recognition.domain.entities import FaceDetection, FaceEmbedding


def test_face_detection_area_handles_positive_dimensions():
    detection = FaceDetection(bbox=(0, 0, 10, 20), confidence=0.8)

    assert detection.area() == 200


def test_face_detection_area_clamps_negative_dimensions():
    detection = FaceDetection(bbox=(10, 10, 5, 5), confidence=0.4)

    assert detection.area() == 0


def test_face_embedding_to_list_round_trips_numpy_array():
    detection = FaceDetection(bbox=(0, 0, 1, 1), confidence=1.0)
    vector = np.arange(5, dtype=np.float32)
    embedding = FaceEmbedding(embedding=vector, detection=detection)

    assert embedding.to_list() == vector.tolist()
