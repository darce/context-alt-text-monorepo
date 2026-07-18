"""Unit-test conftest: register face_pipeline shared fixtures (BR-08).

Imports the fixture functions directly instead of declaring ``pytest_plugins``
(pytest forbids that in non-rootdir conftests during full-package collection).
"""

from recognition.tests.unit.face_pipeline_support import (  # noqa: F401
    ocv_sface_embedder,
    ocv_yunet_detector,
    ort_sface_embedder,
    ort_yunet_detector,
)
