#!/usr/bin/env python
"""Verify the metadata dilution fix is working."""

import numpy as np

from recognition.application.clustering.centroid_utils import compute_similarity


def old_similarity(a, b):
    """OLD buggy method - uses full 1024D."""
    a_norm = a / np.linalg.norm(a)
    b_norm = b / np.linalg.norm(b)
    return max(0.0, min(1.0, float(np.dot(a_norm, b_norm))))


def main():
    # Simulate REAL scenario: metadata has HIGH values (like in real data)
    emb_a = np.zeros(1024, dtype=np.float32)
    emb_b = np.zeros(1024, dtype=np.float32)

    # Different random faces (small norm relative to metadata)
    np.random.seed(42)
    emb_a[:512] = np.random.randn(512).astype(np.float32) * 0.1
    np.random.seed(123)
    emb_b[:512] = np.random.randn(512).astype(np.float32) * 0.1

    # HIGH metadata values (like real data where metadata dominates)
    # This simulates two different people with same pose/age/detection score
    metadata = np.array([0.5, 0.5, 0.5, 0.30, 1.0, 0.95, 0.8, 0.5] * 64, dtype=np.float32)[:512]
    emb_a[512:] = metadata
    emb_b[512:] = metadata

    old_sim = old_similarity(emb_a, emb_b)
    new_sim = compute_similarity(emb_a, emb_b)

    print("Scenario: Different faces, identical metadata (high values)")
    print(f"Face norm: {np.linalg.norm(emb_a[:512]):.4f}")
    print(f"Meta norm: {np.linalg.norm(emb_a[512:]):.4f}")
    print()
    print(f"OLD similarity (buggy): {old_sim:.4f}  <- metadata dominates!")
    print(f"NEW similarity (fixed): {new_sim:.4f}  <- face only")
    print()
    if old_sim > 0.8 and new_sim < 0.3:
        print("✅ FIX CONFIRMED: Metadata dilution bug is fixed!")
    else:
        print(f"Results: old={old_sim:.4f}, new={new_sim:.4f}")


if __name__ == "__main__":
    main()
