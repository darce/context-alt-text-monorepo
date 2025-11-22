#!/usr/bin/env python3
"""
Debug cluster representatives for specific media IDs.

Shows:
- Which cluster each media identity belongs to
- How many representatives each cluster has
- What representatives are being loaded
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT / "apps" / "prototype-description-service"))

from db.settings import get_database_settings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug cluster representatives for media identities.")
    parser.add_argument(
        "--media-ids",
        nargs="+",
        required=True,
        help="List of media IDs to inspect (space separated).",
    )
    return parser.parse_args()


def build_engine():
    settings = get_database_settings()
    from sqlalchemy import create_engine

    return create_engine(settings.postgres_sync_dsn, future=True)


def main() -> None:
    args = parse_args()
    engine = build_engine()

    with Session(engine) as session:
        session.execute(text("SET LOCAL app.bypass_rls = 'true'"))

        # Get media identity information
        media_query = text("""
            SELECT
                mi.id AS identity_id,
                mi.media_id,
                mi.embedding,
                im.cluster_id,
                ic.label AS cluster_label,
                ic.identity_count
            FROM media_identities mi
            LEFT JOIN identity_members im ON im.identity_id = mi.id
            LEFT JOIN identity_clusters ic ON ic.id = im.cluster_id
            WHERE mi.media_id IN :media_ids
            ORDER BY mi.media_id
        """)
        media_result = session.execute(media_query.bindparams(media_ids=tuple(args.media_ids)))

        print("=== Media Identity Information ===\n")
        identities = []
        for row in media_result:
            identities.append(dict(row._mapping))
            print(
                f"Media {row.media_id}:"
                f"\n  Identity ID: {row.identity_id}"
                f"\n  Cluster ID: {row.cluster_id}"
                f"\n  Cluster Label: {row.cluster_label}"
                f"\n  Cluster Size: {row.identity_count}"
            )

        if not identities:
            print(f"No identities found for media_ids={args.media_ids}")
            return

        # Get cluster representatives
        cluster_ids = [i["cluster_id"] for i in identities if i["cluster_id"]]
        if not cluster_ids:
            print("\n=== No clusters assigned ===")
            return

        print("\n=== Cluster Representatives ===\n")
        rep_query = text("""
            SELECT
                icr.cluster_id,
                ic.label AS cluster_label,
                COUNT(*) AS rep_count,
                ARRAY_AGG(icr.identity_id) AS rep_identity_ids,
                ARRAY_AGG(mi.media_id) AS rep_media_ids
            FROM identity_cluster_representatives icr
            JOIN identity_clusters ic ON ic.id = icr.cluster_id
            LEFT JOIN media_identities mi ON mi.id = icr.identity_id
            WHERE icr.cluster_id IN :cluster_ids
            GROUP BY icr.cluster_id, ic.label
        """)
        rep_result = session.execute(rep_query.bindparams(cluster_ids=tuple(set(cluster_ids))))

        rep_data = {}
        for row in rep_result:
            rep_data[str(row.cluster_id)] = row._mapping
            print(
                f"Cluster {row.cluster_id} ({row.cluster_label}):"
                f"\n  Representative count: {row.rep_count}"
                f"\n  From media IDs: {row.rep_media_ids}"
            )

        # Check if any clusters have no representatives
        for cluster_id in set(cluster_ids):
            if str(cluster_id) not in rep_data:
                # Get cluster label
                label_query = text("SELECT label, identity_count FROM identity_clusters WHERE id = :cid")
                label_row = session.execute(label_query, {"cid": cluster_id}).first()
                if label_row:
                    print(
                        f"\n⚠️  Cluster {cluster_id} ({label_row.label}):"
                        f"\n  Representative count: 0 (NO REPRESENTATIVES!)"
                        f"\n  Cluster size: {label_row.identity_count}"
                    )

        # Compute similarities between identities and representatives
        print("\n=== Similarity Analysis ===\n")
        for identity in identities:
            if not identity["cluster_id"]:
                continue

            identity_vec = np.array(
                json.loads(identity["embedding"]) if isinstance(identity["embedding"], str) else identity["embedding"],
                dtype=np.float32,
            )
            identity_vec = identity_vec / np.linalg.norm(identity_vec)

            # Get representatives for OTHER clusters
            other_clusters = [c for c in set(cluster_ids) if c != identity["cluster_id"]]
            if not other_clusters:
                continue

            rep_detail_query = text("""
                SELECT
                    icr.cluster_id,
                    ic.label AS cluster_label,
                    icr.embedding,
                    mi.media_id AS rep_media_id
                FROM identity_cluster_representatives icr
                JOIN identity_clusters ic ON ic.id = icr.cluster_id
                LEFT JOIN media_identities mi ON mi.id = icr.identity_id
                WHERE icr.cluster_id IN :cluster_ids
            """)
            rep_detail_result = session.execute(rep_detail_query.bindparams(cluster_ids=tuple(other_clusters)))

            print(f"Media {identity['media_id']} (in cluster {identity['cluster_label']}):")
            best_match = None
            best_sim = 0.0
            for rep_row in rep_detail_result:
                rep_vec = np.array(
                    json.loads(rep_row.embedding) if isinstance(rep_row.embedding, str) else rep_row.embedding,
                    dtype=np.float32,
                )
                rep_vec = rep_vec / np.linalg.norm(rep_vec)
                similarity = float(np.dot(identity_vec, rep_vec))

                if similarity > best_sim:
                    best_sim = similarity
                    best_match = (
                        rep_row.cluster_label,
                        rep_row.cluster_id,
                        rep_row.rep_media_id,
                    )

            if best_match:
                label, cluster_id, media_id = best_match
                print(
                    f"  Best match to other cluster: {label} (cluster {cluster_id})"
                    f"\n    Similarity: {best_sim:.4f} (from media {media_id})"
                    f"\n    Above threshold (0.6)? {best_sim >= 0.6}"
                )
            else:
                print("  No representatives found in other clusters")

        session.execute(text("RESET app.bypass_rls"))


if __name__ == "__main__":
    main()
