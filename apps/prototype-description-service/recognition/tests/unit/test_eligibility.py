"""Unit tests for suggestion eligibility checks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from recognition.application.suggestions.eligibility import is_eligible_cluster

# === Confirmed-only eligibility tests (v4.12.0) ===


def test_confirmed_labeled_cluster_is_eligible() -> None:
    """User-confirmed cluster with human label is eligible."""
    cluster = SimpleNamespace(
        id="abc",
        tenant_id="tenant-1",
        label="John Smith",
        user_confirmed=True,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is True


def test_unconfirmed_cluster_is_not_eligible() -> None:
    """Unconfirmed cluster (even with label) is not eligible."""
    cluster = SimpleNamespace(
        id="abc",
        tenant_id="tenant-1",
        label="Person 1",
        user_confirmed=False,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is False


def test_unlabeled_cluster_is_not_eligible() -> None:
    """Cluster with no label is not eligible."""
    cluster = SimpleNamespace(
        id="abc",
        tenant_id="tenant-1",
        label=None,
        user_confirmed=True,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is False


def test_cluster_prefix_label_is_not_eligible() -> None:
    """Cluster with auto-generated 'cluster-*' label is not eligible."""
    cluster = SimpleNamespace(
        id="abc",
        tenant_id="tenant-1",
        label="cluster-abc123",
        user_confirmed=True,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is False


def test_tenant_mismatch_is_not_eligible() -> None:
    """Cluster from different tenant is not eligible."""
    cluster = SimpleNamespace(
        id="abc",
        tenant_id="tenant-2",
        label="John Smith",
        user_confirmed=True,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is False


def test_confirmed_cluster_with_human_label_from_matching_tenant_is_eligible() -> None:
    """Full eligibility: confirmed, human label, matching tenant."""
    cluster = SimpleNamespace(
        id="abc",
        tenant_id="TENANT-1",  # Case-insensitive match
        label="Jane Doe",
        user_confirmed=True,
    )
    assert is_eligible_cluster(cluster, "tenant-1") is True
