#!/usr/bin/env python3
"""
Analyze the "domination" bug where one cluster matches many unrelated identities.

This script:
1. Finds clusters that have an unusually high number of suggestions
2. Computes the ACTUAL pairwise similarity between all suggested identities
3. Reveals the geometric impossibility: if all identities are 88-92% similar to the cluster rep,
   they should be 80%+ similar to each other - if they're not, something is broken
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT / "apps" / "prototype-description-service"))

from db.settings import get_database_settings  # noqa: E402


def build_engine():
    settings = get_database_settings()
    from sqlalchemy import create_engine

    return create_engine(settings.postgres_sync_dsn, future=True)


def parse_embedding(emb) -> np.ndarray:
    """Parse embedding from DB format."""
    if isinstance(emb, str):
        data = json.loads(emb)
    elif isinstance(emb, list):
        data = emb
    else:
        data = list(emb)
    vec = np.array(data, dtype=np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


def compute_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two normalized vectors."""
    return float(np.dot(a, b))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cluster-id", help="Specific cluster ID to analyze")
    parser.add_argument("--tenant-id", help="Tenant ID to analyze")
    parser.add_argument("--top-n", type=int, default=5, help="Number of top dominating clusters to analyze")
    args = parser.parse_args()

    engine = build_engine()

    target_clusters: list[dict[str, Any]] = []

    with Session(engine) as session:
        session.execute(text("SET LOCAL app.bypass_rls = 'true'"))

        # Find clusters with most pending suggestions
        if args.cluster_id:
            target_clusters = [{"cluster_id": UUID(args.cluster_id), "label": None, "suggestion_count": None}]
        else:
            domination_query = text("""
                SELECT
                    s.suggested_cluster_id AS cluster_id,
                    ic.label,
                    COUNT(*) AS suggestion_count,
                    AVG(s.representative_similarity) AS avg_similarity
                FROM identity_suggestions s
                JOIN identity_clusters ic ON ic.id = s.suggested_cluster_id
                WHERE s.resolution = 'pending'
                GROUP BY s.suggested_cluster_id, ic.label
                ORDER BY COUNT(*) DESC
                LIMIT :top_n
            """)
            result = session.execute(domination_query, {"top_n": args.top_n}).mappings()
            target_clusters = [dict(row) for row in result.all()]

            if not target_clusters:
                print("No pending suggestions found. Checking all clusters with reps...")
                # Fall back to checking clusters with representatives
                rep_query = text("""
                    SELECT DISTINCT cluster_id
                    FROM identity_cluster_representatives
                    LIMIT :top_n
                """)
                rep_result = session.execute(rep_query, {"top_n": args.top_n})
                target_clusters = [
                    {"cluster_id": row[0], "label": None, "suggestion_count": None} for row in rep_result.all()
                ]

        for row in target_clusters:
            cluster_id = row["cluster_id"]
            label = row.get("label")
            suggestion_count = row.get("suggestion_count")

            print(f"\n{'=' * 80}")
            print(f"ANALYZING CLUSTER: {cluster_id}")
            print(f"Label: {label}")
            print(f"Suggestion count: {suggestion_count}")
            print("=" * 80)

            # Get cluster representative(s)
            rep_query = text("""
                SELECT
                    icr.identity_id,
                    icr.embedding,
                    mi.media_id
                FROM identity_cluster_representatives icr
                LEFT JOIN media_identities mi ON mi.id = icr.identity_id
                WHERE icr.cluster_id = :cluster_id
            """)
            rep_result = session.execute(rep_query, {"cluster_id": cluster_id})
            reps = list(rep_result.all())

            print(f"\n📌 Representatives: {len(reps)}")
            rep_embeddings = []
            for rep in reps:
                rep_vec = parse_embedding(rep.embedding)
                rep_embeddings.append(rep_vec)
                print(f"  - Media {rep.media_id}, Identity {rep.identity_id}")

            if not rep_embeddings:
                print("  ⚠️  NO REPRESENTATIVES - this is a bug!")
                continue

            # Get suggested identities
            suggestion_query = text("""
                SELECT
                    s.identity_id,
                    s.representative_similarity AS reported_similarity,
                    mi.media_id,
                    mi.embedding
                FROM identity_suggestions s
                JOIN media_identities mi ON mi.id = s.identity_id
                WHERE s.suggested_cluster_id = :cluster_id
                  AND s.resolution = 'pending'
                ORDER BY s.representative_similarity DESC
                LIMIT 30
            """)
            suggestion_result = session.execute(suggestion_query, {"cluster_id": cluster_id})
            suggestions = list(suggestion_result.all())

            if not suggestions:
                # Try getting ALL members of the cluster instead
                member_query = text("""
                    SELECT
                        im.identity_id,
                        1.0 AS reported_similarity,
                        mi.media_id,
                        mi.embedding
                    FROM identity_members im
                    JOIN media_identities mi ON mi.id = im.identity_id
                    WHERE im.cluster_id = :cluster_id
                    LIMIT 30
                """)
                suggestions = list(session.execute(member_query, {"cluster_id": cluster_id}).all())
                print(f"\n📋 Members (no pending suggestions found): {len(suggestions)}")
            else:
                print(f"\n📋 Pending Suggestions: {len(suggestions)}")

            # Verify similarities to representative
            print("\n🔍 VERIFYING REPORTED vs ACTUAL SIMILARITIES TO REPRESENTATIVE(S):")
            suggestion_embeddings = []
            for sugg in suggestions:
                sugg_vec = parse_embedding(sugg.embedding)
                suggestion_embeddings.append((sugg.media_id, sugg_vec, sugg.reported_similarity))

                # Compute similarity to all representatives
                sims_to_reps = [compute_similarity(sugg_vec, rep) for rep in rep_embeddings]
                max_sim = max(sims_to_reps)
                avg_sim = sum(sims_to_reps) / len(sims_to_reps)

                reported = float(sugg.reported_similarity) if sugg.reported_similarity else 0
                diff = max_sim - reported

                status = "✅" if abs(diff) < 0.01 else "❌ MISMATCH!"
                print(
                    f"  Media {sugg.media_id}: reported={reported:.4f}, actual_max={max_sim:.4f}, actual_avg={avg_sim:.4f} {status}"
                )

            # Compute pairwise similarities between suggested identities
            if len(suggestion_embeddings) >= 2:
                print("\n🔺 PAIRWISE SIMILARITIES BETWEEN SUGGESTED IDENTITIES:")
                print("   (These should be HIGH if they all match the same cluster at 88-92%)")
                print()

                pairwise_sims = []
                for i, (media_i, vec_i, _) in enumerate(suggestion_embeddings):
                    for j, (media_j, vec_j, _) in enumerate(suggestion_embeddings):
                        if i < j:
                            sim = compute_similarity(vec_i, vec_j)
                            pairwise_sims.append(sim)

                            # Only show a sample
                            if len(pairwise_sims) <= 10:
                                status = "✅" if sim >= 0.75 else "⚠️ LOW" if sim >= 0.60 else "❌ VERY LOW"
                                print(f"  Media {media_i} <-> Media {media_j}: {sim:.4f} {status}")

                if pairwise_sims:
                    print("\n📊 PAIRWISE SIMILARITY STATISTICS:")
                    print(f"   Count: {len(pairwise_sims)}")
                    print(f"   Min:   {min(pairwise_sims):.4f}")
                    print(f"   Max:   {max(pairwise_sims):.4f}")
                    print(f"   Mean:  {np.mean(pairwise_sims):.4f}")
                    print(f"   Std:   {np.std(pairwise_sims):.4f}")

                    # Count how many are below thresholds
                    below_75 = sum(1 for s in pairwise_sims if s < 0.75)
                    below_60 = sum(1 for s in pairwise_sims if s < 0.60)
                    below_50 = sum(1 for s in pairwise_sims if s < 0.50)

                    print(
                        f"\n   Below 0.75: {below_75}/{len(pairwise_sims)} ({100 * below_75 / len(pairwise_sims):.1f}%)"
                    )
                    print(
                        f"   Below 0.60: {below_60}/{len(pairwise_sims)} ({100 * below_60 / len(pairwise_sims):.1f}%)"
                    )
                    print(
                        f"   Below 0.50: {below_50}/{len(pairwise_sims)} ({100 * below_50 / len(pairwise_sims):.1f}%)"
                    )

                    if below_60 > len(pairwise_sims) * 0.3:
                        print("\n   🚨 GEOMETRIC IMPOSSIBILITY DETECTED!")
                        print("   If all these identities are 88-92% similar to ONE representative,")
                        print("   they CANNOT be 50-60% similar to each other!")
                        print("   Something is broken in the similarity calculation or data flow.")

        session.execute(text("RESET app.bypass_rls"))


if __name__ == "__main__":
    main()
