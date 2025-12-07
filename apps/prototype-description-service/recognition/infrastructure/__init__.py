"""
Infrastructure layer for external dependencies.

NOMENCLATURE: Face*
===================
This layer uses Face* nomenclature (FaceDetection, FaceDetector, EmbeddingResult)
because it is intentionally tied to specific detection technology (InsightFace).

The infrastructure layer contains:
    - Face detection adapters (InsightFace, future: ArcFace, MediaPipe)
    - Clustering algorithm implementations (HDBSCAN, Chinese Whispers)
    - Database repositories (SQLAlchemy async)

Boundary with Domain Layer
--------------------------
The infrastructure layer produces Face* objects which are transformed into
*Identity domain objects at the seam:

    Infrastructure                     Domain
    ─────────────                      ──────
    FaceDetection  ─┐
                    ├── to_media_identities() ──► MediaIdentity
    EmbeddingResult ┘

The seam is located in recognition/application/embedding/service.py.

Why Face* Nomenclature?
-----------------------
Using Face* naming acknowledges our current InsightFace dependency and makes
it clear which code needs to change if we swap detection providers.

See Also:
    - recognition/application/embedding/service.py (the seam)
    - recognition/domain/__init__.py (domain nomenclature)
    - docs/tasks/4.0/4.2.4/uml/architecture-face-identity-boundary.mmd
"""
