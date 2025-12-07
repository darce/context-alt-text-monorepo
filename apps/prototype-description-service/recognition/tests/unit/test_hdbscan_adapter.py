"""Tests for HdbscanGraphAlgorithm adapter."""

from __future__ import annotations

# Align with sklearn deprecation: use ensure_all_finite implementation for old alias.
import importlib
import importlib.util
from typing import Any

import numpy as np
import pytest

from recognition.infrastructure.clustering.hdbscan_adapter import HdbscanGraphAlgorithm

skl_validation: Any
skl_utils: Any
_orig_check_array: Any
try:
    skl_validation = importlib.import_module("sklearn.utils.validation")
    skl_utils = importlib.import_module("sklearn.utils")
except Exception:  # pragma: no cover - optional dependency for tests
    skl_validation = None
    skl_utils = None
    _orig_check_array = None
else:
    _orig_check_array = getattr(skl_validation, "check_array", None)
    ensure_all_finite = getattr(skl_validation, "ensure_all_finite", None)

    if ensure_all_finite is None:

        def ensure_all_finite(
            x,
            allow_nan: bool = False,
            msg_dtype=None,
            estimator_name=None,
            input_name: str | None = None,
        ):
            return skl_validation.assert_all_finite(
                x,
                allow_nan=allow_nan,
                msg_dtype=msg_dtype,
                estimator_name=estimator_name,
                input_name=input_name or "",
            )

        skl_validation.ensure_all_finite = ensure_all_finite

    skl_validation.force_all_finite = ensure_all_finite
    skl_utils.force_all_finite = ensure_all_finite

    if _orig_check_array is not None:

        def _check_array(*args, **kwargs):
            force_all_finite = kwargs.pop("force_all_finite", "deprecated")
            ensure_all_finite_arg = kwargs.pop("ensure_all_finite", None)

            if ensure_all_finite_arg is None and force_all_finite != "deprecated":
                ensure_all_finite_arg = force_all_finite

            kwargs["force_all_finite"] = "deprecated"
            kwargs["ensure_all_finite"] = ensure_all_finite_arg
            return _orig_check_array(*args, **kwargs)

        skl_validation.check_array = _check_array
        skl_utils.check_array = _check_array


@pytest.mark.skipif(importlib.util.find_spec("hdbscan") is None, reason="hdbscan not installed")
def test_hdbscan_clusters_simple_groups() -> None:
    """Verify HDBSCAN produces cluster labels when dependency is available."""
    embeddings = np.array(
        [
            [1.0, 0.0],
            [0.9, 0.1],
            [0.0, 1.0],
            [0.1, 0.9],
        ],
        dtype=np.float32,
    )

    algo = HdbscanGraphAlgorithm(min_cluster_size=2, min_samples=1, metric="euclidean")
    labels = algo.cluster(list(embeddings))

    assert len(labels) == 4
    assert set(labels) == {0, 1}


@pytest.mark.skipif(importlib.util.find_spec("hdbscan") is None, reason="hdbscan not installed")
def test_hdbscan_deterministic_output() -> None:
    """Same input should always produce the same labels."""
    embeddings = np.array(
        [
            [0.0, 0.0],
            [0.05, 0.0],
            [1.0, 1.0],
            [1.05, 1.05],
        ],
        dtype=np.float32,
    )

    algo = HdbscanGraphAlgorithm()
    first = algo.cluster(list(embeddings))
    second = algo.cluster(list(embeddings))

    assert first == second


@pytest.mark.skipif(importlib.util.find_spec("hdbscan") is None, reason="hdbscan not installed")
def test_hdbscan_outlier_detection() -> None:
    """Obvious outliers should be labeled -1."""
    embeddings = np.array(
        [
            [0.0, 0.0],
            [0.0, 0.1],
            [5.0, 5.0],
            [5.1, 5.1],
            [20.0, 20.0],  # Outlier
        ],
        dtype=np.float32,
    )

    algo = HdbscanGraphAlgorithm(min_cluster_size=2, min_samples=1, cluster_selection_epsilon=0.2)
    labels = algo.cluster(list(embeddings))

    assert -1 in labels


def test_hdbscan_missing_dependency_raises() -> None:
    """When hdbscan is not installed, adapter should raise a clear error."""
    if _hdbscan_available():
        pytest.skip("hdbscan available; dependency error not expected")

    algo = HdbscanGraphAlgorithm()
    with pytest.raises(RuntimeError):
        algo.cluster([np.array([1.0, 0.0], dtype=np.float32)])


def _hdbscan_available() -> bool:
    """Check if hdbscan can be imported."""
    import importlib.util

    return importlib.util.find_spec("hdbscan") is not None
