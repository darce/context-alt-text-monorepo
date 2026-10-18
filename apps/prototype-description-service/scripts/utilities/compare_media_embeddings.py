#!/usr/bin/env python
"""
Compare cosine similarity between media identities by media_id.

Example:
    python scripts/compare_media_embeddings.py --media-ids 3142808782673037201 3140440471033948071
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from sqlalchemy import String, bindparam, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT / "apps" / "prototype-description-service"))

from db.settings import get_database_settings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare embeddings between media identities.")
    parser.add_argument(
        "--media-ids",
        nargs="+",
        required=True,
        help="List of media IDs to inspect (space separated).",
    )
    parser.add_argument(
        "--cluster-id",
        help="Optional cluster UUID to limit results or override centroid lookup.",
    )
    parser.add_argument(
        "--refresh-centroids",
        action="store_true",
        help="Refresh mv_identity_cluster_centroids before querying (default: only if centroids missing).",
    )
    return parser.parse_args()


def build_engine() -> Engine:
    settings = get_database_settings()
    from sqlalchemy import create_engine

    return create_engine(settings.postgres_sync_dsn, future=True)


def fetch_embeddings(session: Session, media_ids: Sequence[str], cluster_id: str | None):
    stmt = (
        text(
            """
            SELECT
                mi.id::text AS identity_uuid,
                mi.media_id,
                im.cluster_id::text AS cluster_id,
                ic.label AS cluster_label,
                mi.embedding,
                mcc.centroid AS centroid
            FROM media_identities mi
            LEFT JOIN identity_members im ON im.identity_id = mi.id
            LEFT JOIN identity_clusters ic ON ic.id = im.cluster_id
            LEFT JOIN mv_identity_cluster_centroids mcc ON mcc.cluster_id = im.cluster_id
            WHERE mi.media_id::text IN :media_ids
            AND (:cluster_id_text IS NULL OR im.cluster_id::text = :cluster_id_text)
            """
        )
        .bindparams(bindparam("media_ids", expanding=True))
        .bindparams(bindparam("cluster_id_text", type_=String))
    )
    session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
    result = session.execute(
        stmt,
        {"media_ids": media_ids, "cluster_id_text": cluster_id},
    )
    rows = []
    for row in result.mappings():
        embedding = row["embedding"]
        if isinstance(embedding, str):
            embedding = json.loads(embedding)
        centroid = row["centroid"]
        if isinstance(centroid, str):
            centroid = json.loads(centroid)
        rows.append(
            {
                "identity_uuid": row["identity_uuid"],
                "media_id": row["media_id"],
                "cluster_id": row["cluster_id"],
                "cluster_label": row["cluster_label"],
                "embedding": embedding,
                "centroid": centroid,
            }
        )
    session.execute(text("RESET app.bypass_rls"))
    return rows


def refresh_centroid_view(session: Session) -> None:
    """Best-effort refresh of the materialized view."""

    session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
    session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
    session.execute(text("RESET app.bypass_rls"))


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if denom == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


def main() -> None:
    args = parse_args()
    engine = build_engine()

    with Session(engine) as session:
        if args.refresh_centroids:
            refresh_centroid_view(session)
        rows = fetch_embeddings(session, args.media_ids, args.cluster_id)

        # If centroids are missing, try a one-time refresh to populate them.
        if rows and any(row["centroid"] is None for row in rows) and not args.refresh_centroids:
            refresh_centroid_view(session)
            rows = fetch_embeddings(session, args.media_ids, args.cluster_id)

    if not rows:
        print(
            f"No embeddings found for media_ids={args.media_ids}. "
            "Ensure the IDs exist and the DB has data (use --with-sample-data when resetting)."
        )
        return

    if len(rows) < 2:
        print(f"Only found {len(rows)} embedding(s) for media_ids={args.media_ids}; need at least two to compare.")
        return

    for row in rows:
        row["embedding_norm"] = float(np.linalg.norm(np.array(row["embedding"], dtype=np.float32)))
        if row["centroid"] is not None:
            row["centroid_norm"] = float(np.linalg.norm(np.array(row["centroid"], dtype=np.float32)))
            row["identity_centroid_similarity"] = cosine_similarity(
                np.array(row["embedding"], dtype=np.float32),
                np.array(row["centroid"], dtype=np.float32),
            )
        else:
            row["centroid_norm"] = None
            row["identity_centroid_similarity"] = None

    print(f"Found {len(rows)} media identities:\n")
    for row in rows:
        centroid_norm_str = (
            f" centroid_norm={row['centroid_norm']:.4f}" if row["centroid_norm"] is not None else " centroid=missing"
        )
        emb_norm_str = f" emb_norm={row['embedding_norm']:.4f}"
        print(
            f"- media_id={row['media_id']} identity={row['identity_uuid']} "
            f"cluster_id={row['cluster_id']} label={row['cluster_label']}"
            f"{emb_norm_str}{centroid_norm_str}"
        )

    print("\nPairwise cosine similarities (Direct Identity vs Identity):")
    print("NOTE: This differs from clustering logic which compares Identity vs Representative or Centroid.")
    for left, right in itertools.combinations(rows, 2):
        vec_left = np.array(left["embedding"], dtype=np.float32)
        vec_right = np.array(right["embedding"], dtype=np.float32)
        sim = cosine_similarity(vec_left, vec_right)
        print(
            f"media {left['media_id']} ↔ {right['media_id']}: "
            f"similarity={sim:.4f} (left cluster {left['cluster_id']} vs right cluster {right['cluster_id']})"
        )
    print("\nIdentity vs centroid similarities:")
    for row in rows:
        if row["identity_centroid_similarity"] is None:
            print(f"- media {row['media_id']}: centroid missing")
            continue
        print(
            f"- media {row['media_id']} vs centroid {row['cluster_id']}: "
            f"similarity={row['identity_centroid_similarity']:.4f} "
            f"(centroid_norm={row['centroid_norm']:.4f})"
        )


if __name__ == "__main__":
    main()
