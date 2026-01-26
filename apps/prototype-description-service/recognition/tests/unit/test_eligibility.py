"""Unit tests for suggestion eligibility checks."""

from __future__ import annotations

from types import SimpleNamespace

from recognition.application.suggestions.eligibility import is_eligible_cluster


def test_auto_labeled_cluster_is_eligible() -> None:
    cluster = SimpleNamespace(
        id="abc",
        tenant_id="tenant-1",
        label="Person 1",
        user_confirmed=False,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is True


def test_user_labeled_cluster_is_eligible() -> None:
    cluster = SimpleNamespace(
        id="abc",
        tenant_id="tenant-1",
        label="John Smith",
        user_confirmed=True,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is True


def test_unlabeled_cluster_is_not_eligible() -> None:
    cluster = SimpleNamespace(
        id="abc",
        tenant_id="tenant-1",
        label=None,
        user_confirmed=False,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is False


def test_cluster_prefix_label_is_not_eligible() -> None:
    cluster = SimpleNamespace(
        id="abc",
        tenant_id="tenant-1",
        label="cluster-abc123",
        user_confirmed=False,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is False


def test_tenant_mismatch_is_not_eligible() -> None:
    cluster = SimpleNamespace(
        id="abc",
        tenant_id="tenant-2",
        label="Person 1",
        user_confirmed=False,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is False
