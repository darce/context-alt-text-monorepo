# ADR-001: Face → Identity Nomenclature Boundary

**Date**: December 5, 2025  
**Status**: Accepted  
**Context**: Recognition Service v4.2.4 Rewrite

---

## Context

The recognition service processes images to detect faces, generate embeddings, cluster similar faces, and assign identities to clusters. During the v4.2.4 rewrite, we needed to decide on consistent naming conventions across the codebase.

The question arose: should we use "face" or "identity" terminology throughout the codebase?

## Decision

**We will use different nomenclature for infrastructure vs domain layers:**

| Layer          | Nomenclature | Examples                           | Rationale                                |
| -------------- | ------------ | ---------------------------------- | ---------------------------------------- |
| Infrastructure | `Face*`      | `FaceDetection`, `FaceDetector`    | Tied to InsightFace detection technology |
| Domain         | `*Identity`  | `MediaIdentity`, `IdentityCluster` | Technology-agnostic, business-focused    |

**The seam between layers is `EmbeddingService.to_media_identities()`.**

## Rationale

### 1. Technology Swappability

The domain layer (`MediaIdentity`, `IdentityCluster`, `ClusterRepresentative`) doesn't care _how_ the embeddings were generated. If we swap InsightFace for YOLO+ArcFace, MediaPipe, or another detection system:

- Only the **Infrastructure Layer** changes (new `FaceDetector` implementation)
- The **Domain Layer** remains unchanged
- The **Seam** (`to_media_identities()`) handles the translation

### 2. Clear Dependency Direction

Using different names makes the dependency direction explicit:

```text
Infrastructure (Face*) → Seam → Domain (*Identity)
                              ↑
                    transformation point
```

Code that imports `FaceDetection` knows it's in the infrastructure layer.
Code that imports `MediaIdentity` knows it's in the domain layer.

### 3. Explicit Technology Coupling

The `Face*` nomenclature in infrastructure acknowledges our current InsightFace dependency. When we eventually support multiple detection backends, developers will know exactly which code needs to be generalized.

## Data Flow

```text
Infrastructure Layer (Face Nomenclature)
    FaceDetector.detect(sources)
    └── Returns: list[FaceDetection]  # bboxes, landmarks, scores

    EmbeddingGenerator.generate(detections)
    └── Returns: list[EmbeddingResult]  # 512D face vectors

═══════════════════════════════════════════════════════════════
    EmbeddingService.to_media_identities()  ← THE SEAM
═══════════════════════════════════════════════════════════════

Domain Layer (Identity Nomenclature)
    └── MediaIdentity  # Technology-agnostic clusterable entity

    Discovery Algorithms
    └── AssignmentCandidate (identity + proposed cluster)

    AssignmentGate.evaluate()
    └── AssignmentDecision (ACCEPT | SUGGEST | REJECT)

    Persistence
    └── IdentityCluster, ClusterRepresentative
```

## Alternatives Considered

### 1. Use "Face" Everywhere

**Rejected**: Would couple domain logic to face detection technology. What if we later support body detection, voice recognition, or other biometric modalities?

### 2. Use "Identity" Everywhere

**Rejected**: Would obscure the fact that infrastructure code is InsightFace-specific. Makes it harder to identify what code changes when swapping detection providers.

### 3. Use "Entity" or "Subject"

**Rejected**: Too generic. "Identity" captures the semantic meaning of what we're clustering (the same person across images).

## Consequences

### Positive

- Clear separation of concerns between infrastructure and domain
- Easy to identify technology-coupled code
- Domain logic is portable to other detection systems
- Single transformation point is explicit and testable

### Negative

- Developers must understand the naming convention
- Two names for conceptually similar things (face = identity)
- Seam method adds a minor abstraction layer

## References

- [`recognition/application/embedding/service.py`](../../../apps/prototype-description-service/recognition/application/embedding/service.py) - The seam implementation
- [`docs/tasks/4.0/4.2.4/uml/architecture-face-identity-boundary.mmd`](../tasks/4.0/4.2.4/uml/architecture-face-identity-boundary.mmd) - Visual diagram
- [`RECOGNITION_SERVICE_V4.2.4_IMPLEMENTATION_PLAN.md`](../tasks/4.0/4.2.4/RECOGNITION_SERVICE_V4.2.4_IMPLEMENTATION_PLAN.md) - Full implementation plan
