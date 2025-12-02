#!/usr/bin/env python3
"""
Diagnose the metadata dilution bug.

This script compares FULL embedding similarity vs FACE-ONLY similarity
to prove that metadata is dominating the similarity calculation.
"""

import json
import sys
from pathlib import Path

import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from db.settings import get_database_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(REPO_ROOT / "apps" / "prototype-description-service"))


def main():
    settings = get_database_settings()
    engine = create_engine(settings.postgres_sync_dsn)

    with Session(engine) as session:
        session.execute(text("SET LOCAL app.bypass_rls = 'true'"))

        # Get multiple embeddings
        result = session.execute(text("SELECT id, embedding FROM media_identities LIMIT 10"))

        embeddings = []
        for row in result:
            emb = np.array(json.loads(row[1]) if isinstance(row[1], str) else row[1], dtype=np.float32)
            embeddings.append(emb)

        print(f"Loaded {len(embeddings)} embeddings")
        print()

        # Analyze embedding structure
        print("=== EMBEDDING STRUCTURE ANALYSIS ===")
        print()
        for i, emb in enumerate(embeddings[:3]):
            face_norm = np.linalg.norm(emb[:512])
            meta_norm = np.linalg.norm(emb[512:])
            full_norm = np.linalg.norm(emb)

            print(f"Embedding {i}:")
            print(f"  Full norm: {full_norm:.4f}")
            print(f"  Face (0-512) norm: {face_norm:.4f} ({100 * face_norm**2 / full_norm**2:.1f}% of energy)")
            print(f"  Meta (512-1024) norm: {meta_norm:.4f} ({100 * meta_norm**2 / full_norm**2:.1f}% of energy)")
            print()

        # Compare FULL similarity vs FACE-ONLY similarity
        print("=== SIMILARITY COMPARISON: FULL vs FACE-ONLY ===")
        print()

        mismatches = []

        for i in range(min(5, len(embeddings))):
            for j in range(i + 1, min(6, len(embeddings))):
                e1, e2 = embeddings[i], embeddings[j]

                # Normalize full embeddings
                e1_norm = e1 / np.linalg.norm(e1)
                e2_norm = e2 / np.linalg.norm(e2)

                # Extract and normalize face-only
                f1 = e1[:512]
                f2 = e2[:512]
                f1_norm = f1 / np.linalg.norm(f1) if np.linalg.norm(f1) > 0 else f1
                f2_norm = f2 / np.linalg.norm(f2) if np.linalg.norm(f2) > 0 else f2

                # Extract and normalize metadata-only
                m1 = e1[512:]
                m2 = e2[512:]
                m1_norm = m1 / np.linalg.norm(m1) if np.linalg.norm(m1) > 0 else m1
                m2_norm = m2 / np.linalg.norm(m2) if np.linalg.norm(m2) > 0 else m2

                full_sim = float(np.dot(e1_norm, e2_norm))
                face_sim = float(np.dot(f1_norm, f2_norm))
                meta_sim = float(np.dot(m1_norm, m2_norm))

                diff = full_sim - face_sim

                print(f"Embeddings {i} vs {j}:")
                print(f"  FULL similarity (1024D): {full_sim:.4f}")
                print(f"  FACE similarity (512D):  {face_sim:.4f}")
                print(f"  META similarity (512D):  {meta_sim:.4f}")
                print(f"  Difference (FULL - FACE): {diff:+.4f}")

                if abs(diff) > 0.1:
                    status = "❌ SIGNIFICANT MISMATCH!"
                    mismatches.append((i, j, full_sim, face_sim, diff))
                elif abs(diff) > 0.05:
                    status = "⚠️ Notable difference"
                else:
                    status = "✅"
                print(f"  {status}")
                print()

        print("=== CONCLUSION ===")
        print()
        if mismatches:
            print(f"❌ FOUND {len(mismatches)} SIGNIFICANT MISMATCHES!")
            print()
            print("This confirms the bug: similarities are being calculated on the full 1024D")
            print("embedding instead of just the 512D face portion.")
            print()
            print("The metadata (pose, age, gender, etc.) is dominating the similarity,")
            print("causing different faces to appear similar if they have similar metadata.")
            print()
            print("FIX: Use extract_face_embedding() before computing similarity")
        else:
            print("✅ No significant mismatches found")


if __name__ == "__main__":
    main()
