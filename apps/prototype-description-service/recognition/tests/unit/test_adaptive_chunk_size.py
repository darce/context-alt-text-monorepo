"""Unit tests for ClusterService adaptive chunk sizing."""

from __future__ import annotations

from recognition.application.orchestration.cluster_service import ClusterService


def test_chunk_size_cold_start() -> None:
    assert ClusterService._get_chunk_size(0) == 5
    assert ClusterService._get_chunk_size(19) == 5


def test_chunk_size_early_stage() -> None:
    assert ClusterService._get_chunk_size(20) == 10
    assert ClusterService._get_chunk_size(49) == 10


def test_chunk_size_maturing_stage() -> None:
    assert ClusterService._get_chunk_size(50) == 25
    assert ClusterService._get_chunk_size(199) == 25


def test_chunk_size_mature_stage() -> None:
    assert ClusterService._get_chunk_size(200) == 50
    assert ClusterService._get_chunk_size(10_000) == 50
