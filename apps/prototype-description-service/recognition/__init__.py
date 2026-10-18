"""
Recognition service package for the unified assignment pipeline rewrite.

ARCHITECTURE OVERVIEW
=====================
This package implements a unified assignment pipeline with a clear separation
between infrastructure and domain layers.

Face → Identity Boundary
------------------------
The codebase uses intentionally different nomenclature for each layer:

    Infrastructure Layer (recognition/application/embedding/):
        - Uses Face* nomenclature: FaceDetection, FaceDetector
        - Tied to InsightFace detection technology
        - Contains: EmbeddingResult, EmbeddingGenerator

    Domain Layer (recognition/domain/):
        - Uses *Identity nomenclature: MediaIdentity, IdentityCluster
        - Technology-agnostic, business-focused
        - Contains: ClusterRepresentative, AssignmentSuggestion

    The Seam (recognition/application/embedding/):
        - detector.py / generator.py produce FaceDetection / EmbeddingResult
        - the application layer assembles them into *Identity domain objects

Why This Matters:
    If we swap InsightFace for YOLO+ArcFace, MediaPipe, or another detection
    system, only the Infrastructure Layer changes. The Domain Layer remains
    unchanged.

Package Structure:
    recognition/
    ├── domain/           # Business objects (*Identity nomenclature)
    ├── application/      # Services, assignment gate, discovery algorithms
    │   ├── assignment/   # THE unified gate - all assignments flow here
    │   ├── discovery/    # Find candidates (representative, centroid, graph)
    │   ├── embedding/    # Face → Identity seam
    │   └── ...
    ├── infrastructure/   # External dependencies (Face* nomenclature)
    ├── interface_adapters/  # FastAPI routers
    └── observability/    # Logging, visualization, reports

See Also:
    - docs/archive/tasks/4.0/4.2.4/RECOGNITION_SERVICE_V4.2.4_IMPLEMENTATION_PLAN.md
"""
