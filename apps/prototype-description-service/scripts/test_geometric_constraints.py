#!/usr/bin/env python3
"""
Test the geometric constraints of cosine similarity.

If identity A is 90% similar to representative R, and identity B is 90% similar to R,
what's the minimum possible similarity between A and B?

Using the formula for cosine similarity and triangle inequality:
cos(θ_AB) >= 2*cos²(θ/2) - 1 where θ is the angle to R

For cos(θ) = 0.90 (90% similarity):
  θ = arccos(0.90) ≈ 25.84°

Worst case (A and B on opposite sides of R):
  cos(2*θ) = 2*cos²(θ) - 1 = 2*(0.90)² - 1 = 0.62

So if A and B are both 90% similar to R, they MUST be at least 62% similar to each other.

For 88% similarity to R:
  θ = arccos(0.88) ≈ 28.36°
  cos(2*θ) = 2*(0.88)² - 1 = 0.5488 ≈ 55%

For 92% similarity to R:
  θ = arccos(0.92) ≈ 23.07°
  cos(2*θ) = 2*(0.92)² - 1 = 0.6928 ≈ 69%
"""

import numpy as np
from numpy.typing import NDArray


def theoretical_min_similarity(sim_to_r: float) -> float:
    """
    Calculate the theoretical minimum similarity between two points A and B
    if both are `sim_to_r` similar to a reference point R.

    This is achieved when A and B are on exactly opposite sides of R
    at the same angle.
    """
    # cos(2θ) = 2cos²(θ) - 1
    return 2 * sim_to_r**2 - 1


def generate_random_embeddings(n: int, dim: int = 512) -> NDArray[np.float32]:
    """Generate n random unit vectors of given dimension."""
    embeddings = np.random.randn(n, dim).astype(np.float32)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized = embeddings / norms
    return np.asarray(normalized, dtype=np.float32)


def test_geometric_constraints():
    """Test that our understanding of geometric constraints is correct."""
    np.random.seed(42)

    print("=== GEOMETRIC CONSTRAINT VERIFICATION ===\n")

    # Test theoretical bounds
    test_sims = [0.88, 0.89, 0.90, 0.91, 0.92]
    print("Theoretical minimum pairwise similarity if both points are X similar to reference:")
    for sim in test_sims:
        min_pair = theoretical_min_similarity(sim)
        print(f"  If both 90% similar to R: min pairwise = {theoretical_min_similarity(0.90):.4f}")
        print(f"  If both {sim * 100:.0f}% similar to R: min pairwise = {min_pair:.4f}")

    print("\n" + "=" * 60)
    print("\n=== EMPIRICAL VERIFICATION ===\n")

    # Generate a reference embedding
    dim = 512
    ref = generate_random_embeddings(1, dim)[0]

    # Generate many random embeddings
    n_samples = 100000  # More samples for better chance of finding matches
    embeddings = generate_random_embeddings(n_samples, dim)

    # Calculate similarity to reference
    sims_to_ref = embeddings @ ref

    # Find embeddings that are close to 90% similar to reference
    target_sim = 0.90
    tolerance = 0.02  # Wider tolerance
    mask = (sims_to_ref >= target_sim - tolerance) & (sims_to_ref <= target_sim + tolerance)

    selected = embeddings[mask]
    selected_sims = sims_to_ref[mask]

    print(f"Found {len(selected)} embeddings with similarity {target_sim}±{tolerance} to reference")

    if len(selected) < 2:
        print("Not enough samples found - random vectors in high dimensions are nearly orthogonal")
        print("This is expected: most random 512-dim vectors have similarity ~0 to each other")
        print("But if we find embeddings with similarity 0.90 to R, they MUST be similar to each other")
        return
    print(f"Similarity range: {selected_sims.min():.4f} to {selected_sims.max():.4f}")

    if len(selected) >= 2:
        # Calculate pairwise similarities
        pairwise_matrix = selected @ selected.T
        # Extract upper triangle (excluding diagonal)
        pairwise_sims = pairwise_matrix[np.triu_indices(len(selected), k=1)]

        theoretical_min = theoretical_min_similarity(target_sim - tolerance)

        print("\nPairwise similarity statistics:")
        print(f"  Min:  {pairwise_sims.min():.4f} (theoretical min: {theoretical_min:.4f})")
        print(f"  Max:  {pairwise_sims.max():.4f}")
        print(f"  Mean: {pairwise_sims.mean():.4f}")

        below_theoretical = np.sum(pairwise_sims < theoretical_min)
        print(
            f"\n  Below theoretical min: {below_theoretical}/{len(pairwise_sims)} ({100 * below_theoretical / len(pairwise_sims):.2f}%)"
        )

        if below_theoretical > 0:
            print("  ⚠️ WARNING: Some pairs are below theoretical minimum! (due to tolerance)")

    print("\n" + "=" * 60)
    print("\n=== WHAT THIS MEANS FOR 'CAM GRANT DOMINATION' ===\n")

    print("If 20+ identities are all 88-92% similar to ONE representative:")
    min_bound = theoretical_min_similarity(0.88)
    max_bound = theoretical_min_similarity(0.92)
    print(f"  - They MUST be at least {min_bound * 100:.1f}%-{max_bound * 100:.1f}% similar to each other")
    print("  - If we observe pairwise similarities of 50-60%, something is BROKEN")
    print()
    print("Possible causes:")
    print("  1. Embedding corruption/truncation during storage/retrieval")
    print("  2. Normalization not being applied consistently")
    print("  3. Mixing embeddings from different models/dimensions")
    print("  4. Bug in similarity calculation")
    print("  5. Database storing wrong embedding for the representative")


if __name__ == "__main__":
    test_geometric_constraints()
