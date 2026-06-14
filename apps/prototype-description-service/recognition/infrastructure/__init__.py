"""
Infrastructure layer for external dependencies.

NOMENCLATURE: Face*
===================
This layer uses Face* nomenclature (FaceDetection, FaceDetector, EmbeddingResult)
because it is intentionally tied to specific detection technology (InsightFace).

The infrastructure layer contains:
    - Face detection adapters (InsightFace)
    - Clustering algorithm implementations (HDBSCAN)
    - Database repositories (SQLAlchemy async)

Boundary with Domain Layer
--------------------------
The infrastructure layer produces Face* objects which are transformed into
*Identity domain objects at the seam:

    Infrastructure                     Domain
    ─────────────                      ──────
    FaceDetection  ─┐
                    ├── (application seam) ──► MediaIdentity
    EmbeddingResult ┘

The detection/embedding adapters live in recognition/application/embedding/
(detector.py, generator.py); the application layer assembles their outputs into
*Identity domain objects.

Why Face* Nomenclature?
-----------------------
Using Face* naming acknowledges our current InsightFace dependency and makes
it clear which code needs to change if we swap detection providers.

See Also:
    - recognition/application/embedding/ (detector.py, generator.py — the seam)
    - recognition/domain/__init__.py (domain nomenclature)
"""
