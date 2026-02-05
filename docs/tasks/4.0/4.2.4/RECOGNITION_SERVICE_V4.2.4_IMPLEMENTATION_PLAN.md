# Recognition Service v4.2.4 Implementation Plan

**Date**: December 1st 2025  
**Sprint**: 4.2.4  
**Status**: **GREENFIELD REWRITE** — Building correct implementation from the start  
**Author**: Generated from architecture analysis

---

> **⚠️ POST-IMPLEMENTATION NOTE (February 2026)**
>
> This document is a **historical task tracker**. The following changes occurred after initial implementation:
>
> 1. **ChineseWhispersClustering removed** — HDBSCAN is now used for all batch sizes
> 2. **MaturityCheck, CompleteLinkCheck, MemberDistributionCheck removed** — Assignment gate simplified to: `BlockCheck` → `ConstraintCheck` → `ConfidenceCheck`
> 3. **UML diagrams moved** — Task-specific diagrams deleted; see `docs/agentic/diagrams/backend-uml/` for current architecture
>
> For current implementation state, see: `apps/prototype-description-service/recognition/application/assignment/gate.py`

---

## Quick Navigation

| Section                                                                        | Description                                                |
| ------------------------------------------------------------------------------ | ---------------------------------------------------------- |
| [Executive Summary](#revised-executive-summary)                                | Phase overview and current status                          |
| [Consolidated Checklist](#consolidated-checklist)                              | **All tasks (1-82)** — single source of truth for progress |
| [Architecture: Face → Identity](#architecture-face--identity-boundary)         | **NEW** — Infrastructure vs domain nomenclature boundary   |
| [Phase 3 Details](#phase-3-details-graph-algorithms--deterministic-clustering) | HDBSCAN, Chinese Whispers, face-only similarity            |
| [Phase 4 Details](#phase-4-details-observability--logging)                     | ClusteringLogger, BatchJobReport, ClusterVisualizer        |
| [Phase 5 Details](#phase-5-details-database-persistence-blocking)              | **BLOCKING** — Repository pattern, SQLAlchemy async        |
| [Phase 6 Details](#phase-6-details-api-integration-depends-on-phase-5)         | FastAPI routers, DI factory (depends on Phase 5)           |
| [Phase 7 Details](#phase-7-details-production-readiness)                       | **FINAL** — Real pipeline wiring, jobs, security, tests    |
| [Background: Root Cause](#root-cause-analysis)                                 | Why the rewrite was needed                                 |
| [Architecture Reference](#proposed-architecture-unified-assignment-pipeline)   | AssignmentGate, Discovery, Module structure                |

---

## Why v4.2.4 is a Greenfield Rewrite

**Date**: December 1, 2025  
**Decision**: Abandon old code, build correctly from the start.

The v4.2.3 recognition service had a critical bug causing **21+ different people to match a single cluster at 88-92% similarity** (the "Cam Grant domination" problem). Multiple fix attempts failed because the old codebase had **compounding architectural issues** that made targeted fixes unreliable.

### Evidence of the Problem

| Media | Filename        | Age Estimate | Similarity | Actual Person    |
| ----- | --------------- | ------------ | ---------- | ---------------- |
| #2802 | IMG_1916        | ~12y         | 92%        | Kelly (child)    |
| #2796 | IMG_1888        | ~22y         | 88%        | Adult woman      |
| #2793 | IMG_1861        | ~17y         | 90%        | Hillary & Kelly  |
| ...   | 18+ more images | 8y-22y       | 88-92%     | Different people |

**Observation**: Ages ranging from 8 to 22 years — clearly different people — all matched the same cluster.

### Why Debugging Failed

Attempted fixes to `compute_similarity()` (extracting face embedding only) did not resolve the issue because:

1. **Multiple code paths** — Three separate assignment paths existed, each with different logic
2. **Inconsistent guards** — Only one path had complete-link validation
3. **Scattered thresholds** — 5+ files with different threshold values
4. **No single point of control** — Impossible to ensure ALL assignments were validated

**Conclusion**: Rather than continue debugging a fundamentally flawed architecture, v4.2.4 will be a **greenfield rewrite** with correct design from the start.

---

## Revised Executive Summary

The metadata dilution bug was the **immediate cause** of the 97%+ false similarities, but the **three parallel assignment paths remain a significant architectural problem** that should still be addressed.

### Why Single-Path Consolidation is Still Needed

Even with the metadata dilution bug fixed, code analysis reveals:

| Issue                         | Paths Affected           | Impact                                       |
| ----------------------------- | ------------------------ | -------------------------------------------- |
| **No complete-link check**    | Centroid, HDBSCAN anchor | Assigns based on single-point similarity     |
| **No immature cluster guard** | Centroid, HDBSCAN anchor | Can assign to clusters with <2 reps          |
| **No suggestion tier**        | Centroid, HDBSCAN anchor | Binary accept/reject, no human review        |
| **HDBSCAN anchor gap**        | HDBSCAN                  | Matches cluster centroid to ONE rep, not all |
| **Scattered thresholds**      | All paths                | 5+ files with different threshold logic      |

**Critical HDBSCAN Gap** (`hdbscan_clustering.py` lines 180-210):

```python
# Matches centroid against representatives - but only takes BEST match!
for cluster_id, reps in anchor_embeddings.items():
    for rep in reps:
        sim = float(np.dot(centroid, rep))  # Just ONE rep!
        if sim > best_similarity:
            best_similarity = sim
            best_anchor_id = cluster_id

# Assigns ENTIRE HDBSCAN cluster based on single-rep match - NO validation!
if best_anchor_id and best_similarity >= effective_threshold:
    await add_to_cluster(best_anchor_id, members)  # All members assigned!
```

**Decision**: Proceed with unified `AssignmentGate` architecture.

> **Greenfield Rewrite**: The `recognition/` directory is empty. Rather than debugging the old broken code, the v4.2.4 implementation will be built correctly from the start, incorporating all lessons learned from this bug analysis.

1. [x] **Phase 0**: Document root cause analysis (COMPLETE — see below)
2. [x] **Phase 0.5**: Scaffold new modules with correct design (COMPLETED)
3. [PARTIAL] **Phase 1**: Implement AssignmentGate with face-only similarity (Gate + checks implemented; awaiting Cam Grant regression verification)
4. [x] **Phase 2**: Implement Discovery algorithms (Representative/Centroid/Graph discovery implemented)
5. [x] **Phase 3**: Full integration + deterministic CW (HDBSCAN + deterministic Chinese Whispers wired; face-only enforcement + tests complete)
6. [x] **Phase 4**: Observability & Logging (ClusteringLogger, BatchJobReport, ClusterVisualizer)
7. [x] **Phase 5**: Database Persistence (Repository pattern, AssignmentWriter implemented)
8. [PARTIAL] **Phase 6**: API Integration (Routers scaffolded, schemas complete; stubs need real wiring)
9. [ ] **Phase 7**: Production Readiness (Real pipeline wiring, job orchestration, security, integration tests)

---

## Root Cause Analysis

The v4.2.3 bugs stemmed from **two compounding issues**: a data bug and an architectural bug.

### Issue 1: Metadata Dilution (Data Bug)

Our 1024D extended embeddings have this structure:

| Dimensions | Content                             | L2 Norm | Energy Share |
| ---------- | ----------------------------------- | ------- | ------------ |
| 0-511      | Face identity embedding             | ~2.2    | ~13%         |
| 512-1023   | Metadata (pose, age, gender, score) | ~15.2   | ~87%         |

The old `compute_similarity()` compared the **full 1024D vector**, meaning similarity was dominated by metadata:

```text
Scenario: Different faces, identical metadata
→ 87% metadata similarity + 13% face similarity = 97% total (FALSE MATCH!)

Scenario: Same face, different pose/lighting
→ 87% metadata difference + 13% face similarity = lower than expected
```

**v4.2.4 Design**: `compute_similarity()` extracts face embedding (first 512D) ALWAYS.

### Issue 2: Three Unguarded Assignment Paths (Architecture Bug)

Even with correct similarity computation, the architecture had **three parallel assignment paths** with inconsistent validation:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│  ARCHITECTURE ANALYSIS: THREE PATHS WITH INCONSISTENT GUARDS                │
│                                                                             │
│  Path 1: RepresentativeMatcher.match()                                      │
│    ├── Complete-Link Guard ✓ (min/avg similarity to ALL reps)              │
│    ├── Immature Cluster Block ✓ (skip clusters with <2 reps)               │
│    ├── Early Stage Suggestion Guard ✓                                       │
│    ├── Member Validation ✓ (avg + min floor)                               │
│    └── Suggestion Tier ✓ (borderline → human review)                       │
│                                                                             │
│  Path 2: match_via_centroids()                                              │
│    ├── Member Validation ✓ (avg + min floor)                               │
│    ├── Complete-Link Guard ✗ MISSING                                        │
│    ├── Immature Cluster Block ✗ MISSING                                     │
│    └── Suggestion Tier ✗ MISSING (binary accept/reject)                    │
│                                                                             │
│  Path 3: HDBSCAN anchor_embeddings                                          │
│    ├── Matches centroid to SINGLE best rep (not complete-link) ✗           │
│    ├── NO member validation ✗                                               │
│    ├── NO immature cluster block ✗                                          │
│    └── NO suggestion tier ✗ (assigns entire cluster at once!)              │
│                                                                             │
│  RESULT: Only Path 1 has comprehensive guards                               │
│  STATUS: HIGH PRIORITY - Consolidate to single AssignmentGate              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Guard Coverage Matrix

| Guard                         |  RepMatcher  | Centroid | HDBSCAN Anchor |
| ----------------------------- | :----------: | :------: | :------------: |
| Base Threshold                |   [x] 0.75   | [x] 0.85 |  [x] adaptive  |
| **Complete-Link (all reps)**  |     [x]      | [FAILED] |    [FAILED]    |
| **Cluster Maturity Guard**    | [x] (v4.2.3) | [FAILED] |    [FAILED]    |
| Member Validation (avg)       |   [x] 0.85   | [x] 0.85 |    [FAILED]    |
| Member Validation (min floor) |   [x] 0.82   | [x] 0.82 |    [FAILED]    |
| Early Stage High-Conf Gate    |   [x] 0.90   | [FAILED] |    [FAILED]    |
| **Suggestion Tier**           |     [x]      | [FAILED] |    [FAILED]    |
| Creates Suggestions           |     [x]      | [FAILED] |    [FAILED]    |

**Note**: The **Cluster Maturity Guard** (treating single-rep clusters as immature) was implemented in v4.2.3 for `RepresentativeMatcher`. This logic must be migrated to `AssignmentGate` to protect ALL paths.

**Conclusion**: 6 of 8 guards are missing from at least one path.

### Symptoms Explained by Bug

| Symptom                                | Original Explanation | Actual Cause                       |
| -------------------------------------- | -------------------- | ---------------------------------- |
| 20+ people match one cluster at 88-92% | Guards bypassed      | All had similar metadata           |
| Guards "ineffective"                   | Wrong path           | Guards checked metadata similarity |
| Snowball effect                        | Architecture         | Correct — still a concern          |
| Non-deterministic                      | Processing order     | Likely still true                  |

---

## Proposed Architecture: Unified Assignment Pipeline

### Core Principle: Single Gate

**Every identity-to-cluster assignment MUST flow through `AssignmentGate`.**

No matter how an identity is discovered (representative match, centroid match, HDBSCAN clustering, Chinese Whispers) — the final assignment uses the same validation.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  PROPOSED ARCHITECTURE (Single Gate)                                        │
│                                                                             │
│  Discovery Algorithms (find candidates):                                    │
│    ├── RepresentativeMatcher → Candidates[(identity, cluster, similarity)]  │
│    ├── CentroidMatcher → Candidates[(identity, cluster, similarity)]        │
│    └── GraphClusterer → Candidates[(identity, cluster, similarity)]         │
│                                                                             │
│  ↓ ALL paths feed into ↓                                                    │
│                                                                             │
│  AssignmentGate.evaluate(identity, cluster, similarity):                    │
│    ├── Complete-Link Check (min/avg similarity to ALL representatives)     │
│    ├── Maturity Check (cluster has ≥2 diverse representatives)             │
│    ├── Member Distribution Check (average similarity to members)           │
│    └── Returns: ACCEPT | SUGGEST | REJECT                                  │
│                                                                             │
│  Decision Router:                                                           │
│    ├── ACCEPT → AssignmentWriter.assign(identity, cluster)                  │
│    ├── SUGGEST → SuggestionService.create(identity, cluster, confidence)   │
│    └── REJECT → UnclusteredPool.add(identity)                               │
│                                                                             │
│  RESULT: Consistent validation regardless of discovery method               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Module Structure

### New Package Layout

```text
recognition/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── identity.py              # MediaIdentity domain model
│   ├── cluster.py               # IdentityCluster domain model
│   ├── representative.py        # ClusterRepresentative value object
│   └── suggestion.py            # Assignment suggestion value object
│
├── observability/               # NEW: Dedicated observability module
│   ├── __init__.py
│   ├── logging.py               # ClusteringLogger - structured decision logs
│   ├── visualization.py         # ClusterVisualizer - cluster charts
│   ├── reports.py               # BatchJobReport - job summary reports
│   └── decisions.py             # DecisionLog dataclass
│
├── application/
│   ├── __init__.py
│   ├── assignment/              # The unified assignment pipeline
│   │   ├── __init__.py
│   │   ├── gate.py              # AssignmentGate - THE ONLY path to assignment
│   │   ├── decision.py          # AssignmentDecision enum + metadata
│   │   ├── checks/              # Pluggable validation checks
│   │   │   ├── complete_link.py
│   │   │   ├── maturity.py
│   │   │   ├── member_distribution.py
│   │   │   └── confidence.py
│   │   └── writer.py            # Actually persists assignments
│   │
│   ├── discovery/               # Algorithms that find candidates
│   │   ├── __init__.py
│   │   ├── representative.py    # Match against cluster representatives
│   │   ├── centroid.py          # Match against cluster centroids
│   │   └── graph.py             # Chinese Whispers / HDBSCAN
│   │
│   ├── orchestration/           # High-level workflow coordination
│   │   ├── __init__.py
│   │   ├── scan_service.py      # Scanning media for identities
│   │   ├── cluster_service.py   # Clustering unclustered identities
│   │   └── job_service.py       # Background job management
│   │
│   └── suggestions/             # Human-in-the-loop decisions
│       ├── __init__.py
│       ├── service.py
│       └── repository.py
│
├── infrastructure/              # External dependencies
│   ├── __init__.py
│   ├── database/
│   │   ├── repositories.py
│   │   └── materialized_views.py
│   ├── embeddings/
│   │   ├── insightface.py       # Current embedding model
│   │   └── arcface.py           # Future: ArcFace integration
│   └── clustering/
│       ├── chinese_whispers.py
│       └── hdbscan.py
│
└── interface_adapters/          # API layer
    ├── __init__.py
    ├── routers/
    │   ├── analyze.py
    │   ├── clusters.py
    │   ├── suggestions.py
    │   └── jobs.py
    └── schemas/
        ├── requests.py
        └── responses.py
```

---

## Architecture: Face → Identity Boundary

> **UML Reference**: [`uml/architecture-face-identity-boundary.mmd`](uml/architecture-face-identity-boundary.mmd)

### The Nomenclature Split

The codebase deliberately uses **different nomenclature** for infrastructure vs domain layers:

| Layer          | Nomenclature       | Examples                           | Rationale                                  |
| -------------- | ------------------ | ---------------------------------- | ------------------------------------------ |
| Infrastructure | `Face*`            | `FaceDetection`, `FaceDetector`    | Tied to InsightFace detection technology   |
| Domain         | `*Identity`        | `MediaIdentity`, `IdentityCluster` | Technology-agnostic, business-focused      |
| Transformation | `EmbeddingService` | `to_media_identities()`            | The seam where infrastructure meets domain |

### Why This Matters

**Swappability**: The domain layer (`MediaIdentity`, `IdentityCluster`, `ClusterRepresentative`) doesn't care _how_ the embeddings were generated. If we swap InsightFace for YOLO+ArcFace, MediaPipe, or another detection system:

- Only the **Infrastructure Layer** changes (new `FaceDetector` implementation)
- The **Domain Layer** remains unchanged
- The **Seam** (`to_media_identities()`) handles the translation

### The Seam: `EmbeddingService.to_media_identities()`

Located in `recognition/application/embedding/service.py`:

```python
def to_media_identities(
    self,
    tenant_id: UUID,
    embeddings: list[EmbeddingResult],
) -> list[MediaIdentity]:
    """
    Transform infrastructure embeddings to domain identities.

    This is the seam between:
    - Infrastructure: FaceDetection, EmbeddingResult (InsightFace-specific)
    - Domain: MediaIdentity (technology-agnostic, clusterable entity)
    """
    return [
        MediaIdentity(
            id=uuid4(),
            tenant_id=tenant_id,
            media_id=embedding.media_id,
            embedding=embedding.embedding,
            confidence=embedding.confidence,
            bbox_width=embedding.bbox_width,
            bbox_height=embedding.bbox_height,
        )
        for embedding in embeddings
    ]
```

### Data Flow

```
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

### Design Decision

**Keep the current nomenclature.** The split is intentional and architecturally sound:

- `Face*` in infrastructure acknowledges our current InsightFace dependency
- `*Identity` in domain keeps business logic technology-agnostic
- The seam is explicit and testable

---

## AssignmentGate: The Core Innovation

### Design Goals

1. **Single Responsibility**: One place for all assignment validation
2. **Composable Checks**: Enable/disable validation rules via settings
3. **Observable**: Structured logging for every decision
4. **Testable**: Each check is a pure function with explicit inputs

### Interface

```python
@dataclass
class AssignmentCandidate:
    """A proposed identity-to-cluster assignment."""
    identity: MediaIdentity
    identity_vector: np.ndarray
    cluster_id: UUID
    discovery_method: DiscoveryMethod  # REPRESENTATIVE | CENTROID | GRAPH
    discovery_similarity: float

@dataclass
class AssignmentDecision:
    """The gate's verdict on a candidate."""
    outcome: AssignmentOutcome  # ACCEPT | SUGGEST | REJECT
    candidate: AssignmentCandidate
    checks_passed: list[str]
    checks_failed: list[str]
    rejection_reason: str | None = None
    suggestion_confidence: float | None = None

class AssignmentGate:
    """The ONLY path to cluster assignment."""

    def __init__(
        self,
        settings: ClusteringSettings,
        cluster_repository: ClusterRepository,
    ):
        self.checks = [
            MaturityCheck(settings),      # Cluster has ≥2 diverse reps (Migrated from v4.2.3)
            CompleteLinkCheck(settings),  # Match ALL representatives
            MemberDistributionCheck(settings),
            ConfidenceCheck(settings),
        ]

    async def evaluate(
        self,
        candidate: AssignmentCandidate,
    ) -> AssignmentDecision:
        """Evaluate a candidate through all checks."""
        passed = []
        failed = []

        for check in self.checks:
            if check.is_enabled():
                result = await check.evaluate(candidate)
                if result.passed:
                    passed.append(check.name)
                else:
                    failed.append(check.name)
                    if result.is_fatal:
                        return AssignmentDecision(
                            outcome=REJECT if result.should_reject else SUGGEST,
                            candidate=candidate,
                            checks_passed=passed,
                            checks_failed=failed,
                            rejection_reason=result.reason,
                        )

        return AssignmentDecision(
            outcome=ACCEPT,
            candidate=candidate,
            checks_passed=passed,
            checks_failed=failed,
        )
```

---

## Discovery Algorithms (No Assignment Power)

The key insight is that **discovery algorithms find candidates but cannot assign**.

### RepresentativeDiscovery

```python
class RepresentativeDiscovery:
    """Find candidate assignments by matching against representatives."""

    async def discover(
        self,
        identities: list[MediaIdentity],
        representatives_by_cluster: dict[UUID, list[np.ndarray]],
    ) -> list[AssignmentCandidate]:
        """Returns candidates - does NOT assign."""
        candidates = []

        for identity in identities:
            vec = prepare_embedding(identity.embedding)
            best_cluster, best_sim = self._find_best_match(vec, representatives_by_cluster)

            if best_cluster and best_sim >= self.threshold:
                candidates.append(AssignmentCandidate(
                    identity=identity,
                    identity_vector=vec,
                    cluster_id=best_cluster,
                    discovery_method=DiscoveryMethod.REPRESENTATIVE,
                    discovery_similarity=best_sim,
                ))

        return candidates
```

### GraphDiscovery (HDBSCAN / Chinese Whispers)

```python
class GraphDiscovery:
    """Find candidate assignments via graph clustering."""

    async def discover(
        self,
        identities: list[MediaIdentity],
        anchor_embeddings: dict[UUID, list[np.ndarray]] | None = None,
    ) -> list[AssignmentCandidate]:
        """Returns candidates for existing clusters OR new cluster proposals."""

        # Run clustering algorithm
        labels = self._run_hdbscan(identities)

        # Group by label
        clusters_by_label = self._group_by_label(identities, labels)

        candidates = []
        for label, members in clusters_by_label.items():
            if anchor_embeddings:
                # Try to match to existing cluster
                best_anchor, best_sim = self._match_to_anchor(members, anchor_embeddings)
                if best_anchor and best_sim >= self.threshold:
                    for member in members:
                        candidates.append(AssignmentCandidate(
                            identity=member,
                            identity_vector=...,
                            cluster_id=best_anchor,
                            discovery_method=DiscoveryMethod.GRAPH,
                            discovery_similarity=best_sim,
                        ))
            else:
                # Propose new cluster creation
                candidates.append(NewClusterProposal(members=members))

        return candidates
```

---

## Clustering Workflow (Simplified)

```python
class ClusterService:
    """Orchestrates the clustering workflow."""

    def __init__(
        self,
        gate: AssignmentGate,
        representative_discovery: RepresentativeDiscovery,
        centroid_discovery: CentroidDiscovery,
        graph_discovery: GraphDiscovery,
        assignment_writer: AssignmentWriter,
        suggestion_service: SuggestionService,
    ):
        ...

    async def cluster_unclustered_identities(
        self,
        tenant_id: UUID,
    ) -> ClusteringResult:
        """Main entry point for clustering."""

        # 1. Load unclustered identities
        identities = await self.repository.get_unclustered(tenant_id)

        # 2. Load cluster data (representatives, centroids)
        clusters_data = await self.repository.get_cluster_data(tenant_id)

        # 3. Discovery phase: Find candidates (NO assignments yet)
        rep_candidates = await self.representative_discovery.discover(
            identities, clusters_data.representatives
        )

        # Remove matched identities from pool
        matched_ids = {c.identity.id for c in rep_candidates}
        remaining = [i for i in identities if i.id not in matched_ids]

        centroid_candidates = await self.centroid_discovery.discover(
            remaining, clusters_data.centroids
        )

        # ... continue for graph discovery

        # 4. Evaluation phase: ALL candidates go through the gate
        all_candidates = rep_candidates + centroid_candidates + graph_candidates

        for candidate in all_candidates:
            decision = await self.gate.evaluate(candidate)

            match decision.outcome:
                case AssignmentOutcome.ACCEPT:
                    await self.assignment_writer.assign(candidate)
                case AssignmentOutcome.SUGGEST:
                    await self.suggestion_service.create(
                        candidate, decision.suggestion_confidence
                    )
                case AssignmentOutcome.REJECT:
                    # Stays in unclustered pool
                    pass

        # 5. Create new clusters for truly unclustered identities
        still_unclustered = ...
        await self._create_new_clusters(still_unclustered)
```

---

## Implementation Strategy

### v4.2.4 Design Principles (Lessons from Root Cause Analysis)

| Root Cause            | v4.2.4 Design                                                      |
| --------------------- | ------------------------------------------------------------------ |
| Metadata Dilution     | `compute_similarity()` extracts face embedding (first 512D) ALWAYS |
| Singleton Snowballing | `MaturityCheck` requires ≥2 diverse reps before accepting          |
| Single-Point Matching | `CompleteLinkCheck` requires match to ALL representatives          |
| No Suggestion Tier    | `AssignmentGate` returns ACCEPT / SUGGEST / REJECT                 |
| Non-Deterministic CW  | UUID-sorted order + quality-weighted votes + ID tie-breaking       |
| Scattered Thresholds  | Single `ClusteringSettings` dataclass                              |

### Phase 0.5: Scaffolding (MANDATORY — Before Any Implementation)

**Per instructions.md**: All interfaces and contracts MUST be scaffolded before writing implementation or tests.

> **Scaffolding First Policy**: Add function/method signatures with complete type hints, write comprehensive docstrings (Args, Returns, Raises, Examples), use `raise NotImplementedError("TODO: ...")` as initial body, commit after scaffolding each class/function.

#### Scaffolding Checklist with File Paths

##### 1. AssignmentGate Module

| File                                                               | Classes/Functions                         | Status |
| ------------------------------------------------------------------ | ----------------------------------------- | ------ |
| `recognition/application/assignment/__init__.py`                   | Module exports                            | [x]    |
| `recognition/application/assignment/candidate.py`                  | `AssignmentCandidate`, `DiscoveryMethod`  | [x]    |
| `recognition/application/assignment/decision.py`                   | `AssignmentDecision`, `AssignmentOutcome` | [x]    |
| `recognition/application/assignment/gate.py`                       | `AssignmentGate.evaluate()`               | [x]    |
| `recognition/application/assignment/checks/__init__.py`            | Check exports                             | [x]    |
| `recognition/application/assignment/checks/base.py`                | `AssignmentCheck` (ABC), `CheckResult`    | [x]    |
| `recognition/application/assignment/checks/complete_link.py`       | `CompleteLinkCheck`                       | [x]    |
| `recognition/application/assignment/checks/maturity.py`            | `MaturityCheck`                           | [x]    |
| `recognition/application/assignment/checks/member_distribution.py` | `MemberDistributionCheck`                 | [x]    |
| `recognition/application/assignment/checks/confidence.py`          | `ConfidenceCheck`                         | [x]    |
| `recognition/application/assignment/writer.py`                     | `AssignmentWriter`                        | [x]    |

##### 2. Observability Module

| File                                         | Classes/Functions             | Status |
| -------------------------------------------- | ----------------------------- | ------ |
| `recognition/observability/__init__.py`      | Module exports                | [x]    |
| `recognition/observability/decisions.py`     | `DecisionType`, `DecisionLog` | [x]    |
| `recognition/observability/logging.py`       | `ClusteringLogger`            | [x]    |
| `recognition/observability/reports.py`       | `BatchJobReport`              | [x]    |
| `recognition/observability/visualization.py` | `ClusterVisualizer`           | [x]    |

##### 3. Discovery Module

| File                                                  | Classes/Functions                    | Status |
| ----------------------------------------------------- | ------------------------------------ | ------ |
| `recognition/application/discovery/__init__.py`       | Module exports                       | [x]    |
| `recognition/application/discovery/base.py`           | `DiscoveryAlgorithm` (ABC)           | [x]    |
| `recognition/application/discovery/representative.py` | `RepresentativeDiscovery.discover()` | [x]    |
| `recognition/application/discovery/centroid.py`       | `CentroidDiscovery.discover()`       | [x]    |
| `recognition/application/discovery/graph.py`          | `GraphDiscovery.discover()`          | [x]    |

##### 4. Commit Strategy

```bash
# Commit after each scaffolded module (NOT per file)
git commit -m "scaffold(assignment): add AssignmentGate module signatures"
git commit -m "scaffold(discovery): add Discovery algorithm interfaces"
# Observability already committed
```

#### Scaffolding Template

```python
def evaluate(self, candidate: AssignmentCandidate) -> AssignmentDecision:
    """Evaluate a candidate assignment through all validation checks.

    Args:
        candidate: The proposed identity-to-cluster assignment.

    Returns:
        AssignmentDecision with outcome (ACCEPT/SUGGEST/REJECT),
        passed/failed checks, and optional rejection reason.

    Raises:
        ValueError: If candidate is missing required fields.

    Example:
        >>> gate = AssignmentGate(settings, repo)
        >>> decision = await gate.evaluate(candidate)
        >>> decision.outcome
        AssignmentOutcome.ACCEPT
    """
    raise NotImplementedError("TODO: Implement check pipeline")
```

### Phase 1: Happy Path Implementation (Minimal Service)

**Goal**: Implement the minimum service to arrive at a happy path implementation that returns correct results.

#### Step 1.1: TDD Implementation Order

**Per instructions.md**: Red -> Green -> Refactor for every meaningful change.

| Step | Test File                      | Test Case                            | Implementation                          |
| ---- | ------------------------------ | ------------------------------------ | --------------------------------------- |
| 1    | `test_assignment_candidate.py` | `test_candidate_requires_all_fields` | `candidate.py` dataclass                |
| 2    | `test_assignment_decision.py`  | `test_outcome_enum_values`           | `decision.py` enums                     |
| 3    | `test_check_result.py`         | `test_check_result_defaults`         | `checks/base.py`                        |
| 4    | `test_complete_link_check.py`  | `test_rejects_low_min_similarity`    | `checks/complete_link.py`               |
| 5    | `test_complete_link_check.py`  | `test_passes_all_reps_similar`       | `checks/complete_link.py`               |
| 6    | `test_assignment_gate.py`      | `test_gate_runs_all_checks`          | `gate.py`                               |
| 7    | `test_assignment_gate.py`      | `test_gate_accepts_all_checks_pass`  | `gate.py`                               |
| 8    | `test_similarity.py`           | `test_face_only_similarity`          | `similarity.py` (Face-only enforcement) |

#### Step 1.2: Implement AssignmentGate (Basic)

Implement `AssignmentGate.evaluate()` with support for pluggable checks, but initially only enable the critical `CompleteLinkCheck`.

#### Step 1.2: Implement CompleteLinkCheck

This is the critical guard required to stop the "Cam Grant" domination. It ensures that a candidate matches ALL representatives of a cluster, not just the best one (or metadata-heavy average).

#### Step 1.3: Refactor RepresentativeMatcher

Update `RepresentativeMatcher` to call `gate.evaluate()` instead of its inline logic. This connects the primary discovery path to the new validation logic.

#### Step 1.4: Verify Correct Results

Run the "Cam Grant" test case. With `CompleteLinkCheck` active, the false positives should be rejected (or suggested), even if metadata dilution persists, because they won't match _all_ diverse representatives in the cluster.

### Phase 2: Full Guard Implementation

**Goal**: Add remaining validation checks to the gate.

- **MaturityCheck**: Protect against immature clusters (singleton snowballing).
- **MemberDistributionCheck**: Ensure candidate fits the member distribution.
- **ConfidenceCheck**: Handle low-confidence matches.

### Phase 3: Full Path Migration

**Goal**: Ensure all discovery paths use the unified gate.

- Refactor `CentroidDiscovery` to use gate.
- Refactor `GraphDiscovery` (HDBSCAN) to use gate.
- Make Chinese Whispers deterministic.

#### Step 3.1: Deterministic Chinese Whispers

**Reference**: [clustering-improvements-dev-plan.md § D.1](../4.2.3/clustering-improvements-dev-plan.md#d1-make-chinese-whispers-deterministic)

The current Chinese Whispers implementation has **two sources of non-determinism**:

1. `np.random.shuffle(nodes)` — random node processing order
2. `max(label_weights.items())` — arbitrary tie-breaking when weights are equal

**Solution**: Deterministic CW with quality-weighted votes

| Change                 | Purpose                                                                            |
| ---------------------- | ---------------------------------------------------------------------------------- |
| UUID-sorted node order | Replace `random.shuffle` with `sorted(nodes, key=lambda i: str(identities[i].id))` |
| Quality-weighted votes | Weight neighbor influence by `similarity * detection_quality`                      |
| UUID tie-breaking      | When vote counts equal, pick label with smallest member UUID                       |

**Key Code Changes**:

```python
# Before (non-deterministic)
np.random.shuffle(nodes)
best_label = max(label_weights.items(), key=lambda x: x[1])[0]

# After (deterministic)
node_order = sorted(range(n), key=lambda i: str(identities[i].id))

# Quality-weighted voting
for j in neighbors:
    weighted_vote = sim_matrix[i, j] * qualities[j]
    votes[label] = votes.get(label, 0.0) + weighted_vote

# UUID tie-breaking
max_vote = max(votes.values())
candidates = [lbl for lbl, v in votes.items() if v == max_vote]
if len(candidates) == 1:
    best_label = candidates[0]
else:
    # Pick label whose members have smallest UUID
    best_label = min(candidates, key=lambda lbl: min(
        str(identities[k].id) for k in range(n) if labels[k] == lbl
    ))
```

**Important**: This does NOT fix the "Cam Grant" bug — it makes the bug _reproducible_. CW candidates must still flow through `AssignmentGate` with complete-link validation.

**Files to modify**:

- `recognition/application/clustering/chinese_whispers.py`

**Tests**:

- `test_deterministic_same_input_same_output`
- `test_quality_weighting_affects_assignment`
- `test_uuid_tiebreaking_consistent`

### Phase 4: Observability & Cleanup

**Goal**: Add visibility and clean up legacy code.

- Implement `ClusteringLogger` and `ClusterVisualizer`.
- Reset corrupted data and re-run clustering to clean up the mess.
- Simplify orchestration to the final `Discovery -> Gate -> Writer` flow.

→ See [Phase 4 Details](#phase-4-details-observability--logging) for implementation tables and code examples.

### Phase 5: Database Persistence

**Goal**: Implement repository pattern for cluster/member storage.

- Create `ClusterRepository` and `MemberRepository` interfaces.
- Implement `SqlAlchemyClusterRepository` and `SqlAlchemyMemberRepository`.
- Implement `AssignmentWriter` to persist cluster assignments.
- Integrate persistence into `ClusterService`.

→ See [Phase 5 Details](#phase-5-details-database-persistence-blocking) for implementation tables and code examples.

### Phase 6: API Integration

**Goal**: Expose the unified recognition service via REST API.

- Create request/response schemas with UUID fields (displayed as 22-char base64).
- Implement routers: analyze, clusters, suggestions, diagnostics.
- Wire dependency injection factory with real repositories.
- Integrate routers into `api/main.py`.

→ See [Phase 6 Details](#phase-6-details-api-integration-depends-on-phase-5) for implementation tables and code examples.

> **Status**: See [Consolidated Checklist](#consolidated-checklist) for current progress on all items.

---

## Algorithm Evaluation Summary

See [ALGORITHM_EVALUATION.md](./ALGORITHM_EVALUATION.md) for detailed analysis.

### Clustering Algorithms

| Algorithm        | Complexity | Deterministic | Outlier Handling | Recommendation           |
| ---------------- | ---------- | ------------- | ---------------- | ------------------------ |
| Chinese Whispers | O(E)       | No            | Poor             | Keep for >500 identities |
| HDBSCAN          | O(n²)      | Yes           | Excellent        | Primary for ≤500         |
| AHC (Ward)       | O(n³)      | Yes           | None             | Not recommended          |
| K-means          | O(nkt)     | Mostly        | None             | Not recommended          |
| Representative   | O(n×r)     | Yes           | N/A              | Keep for incremental     |

### Embedding Models

| Model                   | Accuracy | Speed   | Notes                 |
| ----------------------- | -------- | ------- | --------------------- |
| InsightFace (buffalo_l) | High     | Fast    | Current, works well   |
| ArcFace (sub-center)    | Higher   | Similar | Better noise handling |

**Recommendation**: Keep InsightFace for now. The clustering architecture is the primary issue, not embedding quality. Consider ArcFace for v3 if needed.

---

## Frontend Compatibility & API Specification

The new service MUST maintain the same API contract while exposing the new functionality.

### Router Layout

`recognition/interface_adapters/http/router.py` should include:

1. **Health**

   - `GET /recognition/health` → `{service, status}` (static OK + version info optional)

2. **Analyze / Scanning**

   - `POST /recognition/analyze`
     - Body: `{media_ids: string[], tenant_id: string}`
     - Behavior: enqueue or run identity scan; return job_id.
   - `GET /recognition/jobs/{job_id}`
     - Behavior: poll job status; include progress, counts, started_at, finished_at.

3. **Clustering**

   - `POST /recognition/clustering/jobs`
     - Body: `{tenant_id: string, mode?: "sync" | "async"}`
     - Behavior: trigger clustering for unclustered identities; return job_id.
   - `GET /recognition/clusters`
     - Query: `tenant_id`, optional paging/sort.
     - Returns: list of clusters with ids, labels, counts, representative thumbs (if available).
   - `PATCH /recognition/clusters/{cluster_id}`
     - Body: `{tenant_id: string, label?: string}`
     - Behavior: update label; enforce UUID validation.
   - `POST /recognition/clusters/{cluster_id}/merge`
     - Body: `{tenant_id: string, target_label: string}`
     - Behavior: create/merge target cluster; return summary of moved identities.

4. **Suggestions (human-in-the-loop)**

   - `GET /recognition/identities/{identity_id}/suggestions`
     - Behavior: list pending suggestions for an identity (IDs, similarities, cluster previews).
   - `POST /recognition/suggestions/{suggestion_id}/accept`
     - Behavior: accept suggestion; persist assignment; update representatives if needed.
   - `POST /recognition/suggestions/{suggestion_id}/reject`
     - Behavior: reject suggestion; return updated state.

5. **Diagnostics / Observability (optional flag)**
   - `GET /recognition/diagnostics/decisions`
     - Query: `tenant_id`, optional filters (`outcome`, date range).
     - Behavior: return recent AssignmentGate decisions for debugging.

### Data Contracts (JSON)

- **Identity**: `{id, tenant_id, media_id, bbox:{w,h}, confidence, embedding? (omit in responses)}`
- **Cluster**: `{id, tenant_id, label, is_labeled, member_count, representatives:[{id, media_id, thumb_url?}] }`
- **Suggestion**: `{id, identity_id, cluster_id, rep_similarity, member_similarity, status}`
- **Job**: `{id, type: "analyze" | "clustering", status, progress:{completed,total}, started_at, finished_at}`

All `id` fields use UUIDv7 internally, displayed as 22-char base64 strings in API responses.

### Wiring to Services

- Instantiate in `recognition/interface_adapters/http/router.py`:
  - `ClusterService` (uses RepresentativeDiscovery, CentroidDiscovery, GraphDiscovery, AssignmentGate, AssignmentWriter, SuggestionService, ClusteringLogger)
  - `ScanService` (placeholder if not implemented; return 501 or stub)
  - `SuggestionService` (stub or minimal in-memory until infra exists)
- Router handlers should:
  - Validate payloads with Pydantic request models in `recognition/interface_adapters/http/schemas/requests.py`.
  - Serialize responses with Pydantic response models in `recognition/interface_adapters/http/schemas/responses.py`.
  - Map domain errors to HTTP 4xx/5xx with clear messages.

No frontend changes required. All changes are internal refactoring.

---

## API Plan Cross-Reference

> **Reference**: [recognition_service_api_plan.md](./recognition_service_api_plan.md)

The following table shows how each TODO from the API plan is addressed:

| API Plan TODO                                           | Phase       | Status    | Implementation Plan Reference                          |
| ------------------------------------------------------- | ----------- | --------- | ------------------------------------------------------ |
| 1. Add `schemas/requests.py` and `schemas/responses.py` | Phase 6     | [x] DONE  | Task 37 — Request/Response schemas                     |
| 2. Replace stub router with real endpoints              | Phase 6 + 7 | [PARTIAL] | Tasks 39-42 (stubs), Tasks 46-47 (real wiring)         |
| 3. Provide `SuggestionService` and `AssignmentWriter`   | Phase 5 + 7 | [PARTIAL] | Task 34 (writer), Tasks 51-52 (suggestion persistence) |
| 4. Add dependency injection factory                     | Phase 6     | [x] DONE  | Task 43 — DI factory                                   |
| 5. Update `api/main.py` with recognition router         | Phase 6     | [x] DONE  | Task 44 — Main app integration                         |
| 6. Implement `HdbscanGraphAlgorithm`                    | Phase 3     | [x] DONE  | Task 19 — HDBSCAN implementation                       |
| 7. Add deterministic Chinese Whispers                   | Phase 3     | [x] DONE  | Task 20 — Deterministic CW                             |
| 8. Face-only similarity enforcement                     | Phase 3     | [x] DONE  | Task 22 — Face-only similarity                         |

**Non-Goals from API Plan** (updated status):

| Non-Goal                          | Current Status                                         |
| --------------------------------- | ------------------------------------------------------ |
| Database migrations               | N/A — Greenfield rewrite uses native UUID from start   |
| Full scan pipeline implementation | Phase 7 — Tasks 59-61 will implement                   |
| HDBSCAN adapter                   | [x] DONE — Task 19 implemented `HdbscanGraphAlgorithm` |

---

## Success Criteria

### Phase 1 Success (Bug Fix Validation)

1. **No more "domination" clusters** — No cluster should match 20+ identities at 88%+
2. **Triangle inequality holds** — All cluster members have pairwise similarity ≥ 0.55
3. **Guards effective** — Complete-link guard rejects actual lookalikes, not metadata twins
4. **Threshold validated** — 0.88 (or adjusted value) produces acceptable precision/recall

### Phase 2+ Success (If Needed)

1. **Zero false positives at threshold** — If an identity matches at threshold but fails complete-link, it goes to suggestions
2. **Deterministic outputs** — Same inputs produce same outputs
3. **Single assignment path** — All discovery methods route through `AssignmentGate` (if implemented)
4. **Observable** — Structured logs for every assignment decision
5. **All existing tests pass** — No regressions

---

## Risk Assessment

| Risk                   | Likelihood | Impact | Mitigation                                       |
| ---------------------- | ---------- | ------ | ------------------------------------------------ |
| New bugs in rewrite    | High       | Medium | Extensive test suite, manual verification on dev |
| Performance regression | Medium     | Low    | Benchmark critical paths                         |
| API incompatibility    | Low        | High   | Contract tests against frontend                  |
| Delayed delivery       | Medium     | Medium | Phased approach, MVP first                       |

---

## Timeline Estimate

| Phase                         | Duration       | Deliverable                                                                | Status  |
| ----------------------------- | -------------- | -------------------------------------------------------------------------- | ------- |
| Phase 0.5: Scaffolding        | 0.5 day        | All function/class signatures with `NotImplementedError`                   | PARTIAL |
| Phase 1: Happy Path           | 1-2 days       | Gate + CompleteLink + RepDiscovery (Correct Results)                       | DONE    |
| Phase 2: Full Guards          | 1 day          | Maturity + MemberDist + Confidence Checks                                  | DONE    |
| Phase 3: Graph Algorithms     | 1.5 days       | HDBSCAN + Deterministic CW + Face-only similarity                          | DONE    |
| Phase 4: Observability        | 1 day          | ClusteringLogger + BatchJobReport + ClusterVisualizer                      | DONE    |
| Phase 5: Database Persistence | 1 day          | ClusterRepository + MemberRepository + AssignmentWriter                    | DONE    |
| Phase 6: API Integration      | 1.5 days       | REST API + Dependency Injection + Router integration                       | PARTIAL |
| Phase 7: Production Readiness | 3-4 days       | Real pipeline wiring, job orchestration, security, integration tests       | PLANNED |
| **Total**                     | **10-12 days** | Unified assignment pipeline + observability + persistence + production API |         |

**Note**: This is a greenfield rewrite with no production data. No migration or feature flags required.

**Terminology**:

- **Dependency Injection (DI)**: A design pattern where objects receive their dependencies (e.g., repositories, services) from external sources rather than creating them internally. This makes code more testable and loosely coupled. The "DI factory" creates and wires together all the service dependencies.

---

## Appendix: Files to Archive

> **Note**: Since this is a greenfield rewrite into `apps/prototype-description-service/recognition/`, there is no need to archive files. The old code in `apps/archived-recognition-service/` is already archived.

The following module structure has been established:

---

## Next Steps

### Consolidated Checklist

All development items in sequential order. Implementation details for each phase follow below.

#### Phase 0: Planning & Design

1. [x] Create this implementation plan
2. [x] Document root cause analysis (metadata dilution + architectural gaps)
3. [x] Confirm architectural consolidation is needed (analysis complete)
4. [x] Create UML diagrams (class + sequence + component)
5. [x] Design Deterministic CW algorithm
6. [x] Design ID strategy (UUIDv7 + base64 display)

#### Phase 0.5: Scaffolding (MANDATORY)

7. [x] Scaffold AssignmentGate module — signatures only, `NotImplementedError` bodies
8. [x] Scaffold Observability module — `ClusteringLogger`, `ClusterVisualizer`, `BatchJobReport`
9. [x] Scaffold Discovery module — `RepresentativeDiscovery`, `CentroidDiscovery`, `GraphDiscovery`
10. [x] Commit scaffolding before any implementation

#### Phase 1: Happy Path Implementation

11. [x] Implement AssignmentGate.evaluate() (Basic logic)
12. [x] Implement CompleteLinkCheck (Critical guard for "Cam Grant" issue)
13. [x] Refactor RepresentativeMatcher to use gate
14. [ ] Verify "Cam Grant" issue is resolved for new matches (Happy Path)

#### Phase 2: Full Guard Implementation

15. [x] Implement MaturityCheck
16. [x] Implement MemberDistributionCheck
17. [x] Implement ConfidenceCheck
18. [x] Enable all checks in AssignmentGate

#### Phase 3: Graph Algorithms & Deterministic Clustering

19. [x] Implement HDBSCAN clustering
    - 19.1 [x] Create `HdbscanGraphAlgorithm` class implementing `GraphAlgorithm`
    - 19.2 [x] Implement `cluster(embeddings) -> list[int]`
    - 19.3 [x] Configure parameters: `min_cluster_size=2`, `min_samples=1`, `epsilon=0.12`
    - 19.4 [x] Return `-1` for noise/outlier points
20. [x] Implement Deterministic Chinese Whispers
    - 20.1 [x] Create `DeterministicChineseWhispers` class
    - 20.2 [x] Replace random shuffle with UUID-sorted node order
    - 20.3 [x] Implement quality-weighted voting
    - 20.4 [x] Implement UUID tie-breaking
    - 20.5 [x] Configure parameters: `threshold=0.88`, `max_iterations=50`
21. [x] Integrate GraphDiscovery with algorithms
    - 21.1 [x] Implement `discover()` method using pluggable algorithm
    - 21.2 [x] Auto-select: HDBSCAN if ≤500 identities, else ChineseWhispers
    - 21.3 [x] Extract face embeddings (512D) before passing to algorithm
    - 21.4 [x] Match new clusters to existing anchors
    - 21.5 [x] Create `AssignmentCandidate` for each cluster-anchor match
22. [x] Implement face-only similarity enforcement
    - 22.1 [x] Create `extract_face_embedding(embedding) -> ndarray`
    - 22.2 [x] Create `compute_face_similarity(a, b) -> float`
    - 22.3 [x] Audit and update all discovery files
    - 22.4 [x] Verify `centroid_utils.py` extracts 512D before similarity
23. [x] Write Phase 3 tests (Table 3.5)

#### Phase 4: Observability & Logging

24. [x] Implement ClusteringLogger
    - 24.1 [x] Complete `log_decision()` implementation
    - 24.2 [x] Implement `log_batch_start(identity_count, algorithm, tenant_id)`
    - 24.3 [x] Implement `log_batch_complete(report: BatchJobReport)`
    - 24.4 [x] Use structured JSON format for log entries
    - 24.5 [x] Include: timestamp, identity_id, cluster_id, decision, similarity, reason, algorithm
25. [x] Implement BatchJobReport
    - 25.1 [x] Complete dataclass with all metrics
    - 25.2 [x] Implement `add_decision(decision: AssignmentDecision)` accumulator
    - 25.3 [x] Implement `duration_ms() -> int`
    - 25.4 [x] Implement `success_rate() -> float` (accepts / total)
    - 25.5 [x] Implement `to_json() -> str` for persistence
26. [x] Implement ClusterVisualizer
    - 26.1 [x] Implement `generate_batch_report_chart()`
    - 26.2 [x] Create stacked bar chart: accept/suggest/reject counts
    - 26.3 [x] Implement `generate_similarity_histogram()`
    - 26.4 [x] Save charts to configurable `output_dir`
    - 26.5 [x] Use matplotlib (already available in requirements)
27. [x] Integrate observability into ClusterService
    - 27.1 [x] Add `logger: ClusteringLogger` to constructor
    - 27.2 [x] Add `visualizer: ClusterVisualizer` to constructor
    - 27.3 [x] Call `logger.log_batch_start()` at workflow start
    - 27.4 [x] Call `logger.log_decision()` after each gate evaluation
    - 27.5 [x] Call `report.add_decision()` to accumulate metrics
    - 27.6 [x] Call `logger.log_batch_complete()` and `visualizer.generate_batch_report_chart()` at end
28. [ ] Write Phase 4 tests (Table 4.5)

#### Phase 5: Database Persistence (BLOCKING)

> **Critical**: Without persistence, clustering results are lost and API cannot wire real services. This phase implements repository pattern for cluster/member storage.
>
> **TDD Approach**: Write tests FIRST for each repository/writer before implementation. Tests define the contract.

29. [x] **[TDD]** Write repository interface tests FIRST
    - 29.1 [x] Create `test_cluster_repository.py` with test cases for all CRUD operations
    - 29.2 [x] Create `test_member_repository.py` with test cases for bulk operations
    - 29.3 [x] Create `test_assignment_writer.py` with integration test cases
    - 29.4 [x] Tests should use in-memory SQLite or test fixtures initially
30. [x] Create ClusterRepository interface
    - 30.1 [x] Define `ClusterRepository` protocol in `recognition/domain/repositories.py`
    - 30.2 [x] Define `get_by_id(cluster_id) -> IdentityCluster | None`
    - 30.3 [x] Define `get_by_tenant(tenant_id) -> list[IdentityCluster]`
    - 30.4 [x] Define `save(cluster) -> IdentityCluster`
    - 30.5 [x] Define `update(cluster) -> IdentityCluster`
    - 30.6 [x] Define `delete(cluster_id) -> None`
31. [x] Create MemberRepository interface
    - 31.1 [x] Define `MemberRepository` protocol in `recognition/domain/repositories.py`
    - 31.2 [x] Define `get_by_cluster(cluster_id) -> list[IdentityMember]`
    - 31.3 [x] Define `add_member(cluster_id, identity_id, similarity) -> IdentityMember`
    - 31.4 [x] Define `remove_member(member_id) -> None`
    - 31.5 [x] Define `bulk_add_members(cluster_id, members: list[MemberData]) -> list[IdentityMember]`
32. [x] Implement SqlAlchemyClusterRepository (make tests pass)
    - 32.1 [x] Create `recognition/infrastructure/repositories/cluster_repository.py`
    - 32.2 [x] Inject `AsyncSession` via constructor
    - 32.3 [x] Implement all CRUD methods with async/await
    - 32.4 [x] Convert domain `IdentityCluster` ↔ SQLAlchemy `IdentityCluster` model
    - 32.5 [x] Use `session.flush()` for within-transaction writes
33. [x] Implement SqlAlchemyMemberRepository (make tests pass)
    - 33.1 [x] Create `recognition/infrastructure/repositories/member_repository.py`
    - 33.2 [x] Inject `AsyncSession` via constructor
    - 33.3 [x] Implement `bulk_add_members()` with batch insert
    - 33.4 [x] Use `select(...).options(selectinload(...))` for eager loading
34. [x] Implement AssignmentWriter (make tests pass)
    - 34.1 [x] Create `recognition/application/persistence/assignment_writer.py`
    - 34.2 [x] Inject `ClusterRepository` and `MemberRepository`
    - 34.3 [x] Implement `persist_assignment(decision: AssignmentDecision) -> None`
    - 34.4 [x] Implement `persist_new_cluster(identities: list[MediaIdentity]) -> IdentityCluster`
    - 34.5 [x] Implement `update_cluster_metadata(cluster_id, label, representative_id) -> None`
35. [x] Integrate persistence into ClusterService
    - 35.1 [x] Add `assignment_writer: AssignmentWriter` to constructor
    - 35.2 [x] Call `persist_assignment()` after each ACCEPT decision
    - 35.3 [x] Call `persist_new_cluster()` when graph clustering creates new clusters
    - 35.4 [x] Wrap batch operations in transaction context
36. [x] Verify all Phase 5 tests pass (Table 5.5)

#### Phase 6: API Integration (depends on Phase 5)

> **Dependency**: Requires Phase 5 repositories to wire real services into FastAPI `Depends()` pattern.
>
> **TDD Approach**: Write endpoint tests FIRST using `httpx` + `pytest-asyncio`. Tests define expected request/response contracts.

37. [x] Create Request/Response schemas
    - 37.1 [x] Create all request models in `schemas/requests.py`
    - 37.2 [x] Create all response models in `schemas/responses.py`
    - 37.3 [x] Use `UUID` for all IDs (serialize as 22-char base64)
    - 37.4 [x] Add Pydantic serializers for base64 display
38. [x] **[TDD]** Write API endpoint tests FIRST
    - 38.1 [x] Create `test_api_analyze.py` with request/response expectations
    - 38.2 [x] Create `test_api_clusters.py` with CRUD test cases
    - 38.3 [x] Create `test_api_suggestions.py` with accept/reject flows
    - 38.4 [x] Use `TestClient` with mock repositories initially
39. [x] Implement analyze router (make tests pass)
    - `POST /analyze`, `GET /jobs/{job_id}`
40. [x] Implement clusters router (make tests pass)
    - `POST /clustering/jobs`, `GET /clusters`, `PATCH /clusters/{id}`, `POST /clusters/{id}/merge`
41. [x] Implement suggestions router (make tests pass)
    - `GET /identities/{id}/suggestions`, `POST /suggestions/{id}/accept`, `POST /suggestions/{id}/reject`
42. [x] Implement diagnostics router (`GET /diagnostics/decisions`)
43. [x] Create dependency injection factory
    - 43.1 [x] Create service factory functions
    - 43.2 [x] Wire all dependencies (Gate, Discovery, Repositories, Settings, Logger) — **blocked on Phase 5**
    - 43.3 [x] Use FastAPI `Depends()` pattern
44. [PARTIAL] Integrate routers into main application
    - 44.1 [x] Import all routers in `api/main.py`
    - 44.2 [x] Include routers with `/recognition` prefix
    - 44.3 [x] Add health check endpoint
45. [x] Verify all Phase 6 tests pass (Table 6.5)

#### Phase 7: Production Readiness

> **Goal**: Replace stubs with real implementations, add job orchestration, security, and integration tests.
> This phase brings the recognition service from "working with mocks" to "production-ready".
>
> **TDD Approach**: Red → Green → Refactor.
>
> 1. Write tests FIRST — **tests MUST fail initially** (Red)
> 2. Implement minimal code to make tests pass (Green)
> 3. Refactor while keeping tests green
>
> If a test passes before implementation, the test is wrong or the feature already exists.

##### 7.1 Real Pipeline Wiring (Replace API Stubs)

46. [x] **[TDD]** Write pipeline integration tests FIRST
    - 46.1 [x] Create `test_embedding_service_integration.py`
    - 46.2 [x] Test `detect_faces()` returns expected `FaceDetection` structure
    - 46.3 [x] Test `generate_embeddings()` returns valid 1024D vectors
    - 46.4 [x] Test end-to-end: media bytes → detection → embedding → identity
    - 46.5 [x] Test clustering job calls real `ClusterService.cluster_unclustered_identities()`
47. [PARTIAL] Wire analyze router to real embedding pipeline (make tests pass)
    - 47.1 [x] Implement `EmbeddingService.detect_faces(media_ids) -> list[FaceDetection]`
    - 47.2 [x] Implement `EmbeddingService.generate_embeddings(detections) -> list[MediaIdentity]`
    - 47.3 [x] Replace stub `ScanService` with real implementation calling embedding pipeline
    - 47.4 [x] Integrate with media fetching (WordPress media library or local storage)
48. [PARTIAL] Wire clustering router to real ClusterService flow (make tests pass)
    - 48.1 [x] Replace immediate "completed" job response with real async job creation
    - 48.2 [x] Wire `POST /clustering/jobs` to `ClusterService.cluster_unclustered_identities()`
    - 48.3 [x] Ensure discovery inputs (representatives, centroids) are fetched from repositories
    - 48.4 [x] Wrap clustering in proper transaction/session management

##### 7.2 Session & Tenant Scoping

49. [x] **[TDD]** Write tenant scoping tests FIRST
    - 49.1 [x] Create `test_tenant_isolation.py`
    - 49.2 [x] Test tenant A cannot query tenant B clusters
    - 49.3 [x] Test missing `X-Tenant-ID` header returns 400
    - 49.4 [x] Test invalid tenant ID format returns 400
    - 49.5 [x] Test session cleanup after request (no leaked sessions)
50. [x] Add request-level tenant resolution (make tests pass)
    - 50.1 [x] Create `get_tenant_id()` dependency (from header `X-Tenant-ID` or query param)
    - 50.2 [x] Validate tenant ID format (UUID)
    - 50.3 [x] Return 400 if tenant ID missing or invalid
    - 50.4 [x] Implement tenant auto-provisioning on first request
      - Create tenant record if not exists via `ensure_tenant_exists()`
      - Applied to: `build_cluster_service()`, `/analyze`, `/training-stage`
51. [x] Inject DB session via FastAPI Depends (make tests pass)
    - 51.1 [x] Create tenant-scoped async session dependency yielding `AsyncSession`
    - 51.2 [x] Ensure session is properly closed after request
    - 51.3 [x] Add transaction commit/rollback handling
52. [x] Ensure all repository calls are tenant-scoped (make tests pass)
    - 52.1 [x] Audit all repository methods for tenant_id filtering
    - 52.2 [x] Add explicit tenant isolation assertions in tests

##### 7.3 Suggestion Persistence

53. [x] **[TDD]** Write suggestion repository tests FIRST
    - 53.1 [x] Create `test_suggestion_repository.py`
    - 53.2 [x] Test `create()` persists suggestion with correct status
    - 53.3 [x] Test `get_by_identity()` returns suggestions for identity
    - 53.4 [x] Test `get_by_cluster()` returns suggestions for cluster
    - 53.5 [x] Test `update_status()` transitions PENDING → ACCEPTED/REJECTED
54. [x] Implement SuggestionRepository (make tests pass)
    - 54.1 [x] Define `SuggestionRepository` protocol in `domain/repositories.py`
    - 54.2 [x] Create `SqlAlchemySuggestionRepository` in `infrastructure/repositories/`
    - 54.3 [x] Methods: `create()`, `get_by_identity()`, `get_by_cluster()`, `update_status()`
55. [x] Wire SuggestionService to repository (make tests pass)
    - 55.1 [x] Replace in-memory stub with repository-backed implementation
    - 55.2 [x] Store SUGGEST decisions from AssignmentGate
    - 55.3 [x] Implement `accept()` and `reject()` with persistence

##### 7.4 ClusterService Completeness

56. [x] **[TDD]** Write cluster operations tests FIRST
    - 56.1 [x] Create `test_cluster_operations.py` (merge/label coverage)
    - 56.2 [x] Test merge reassigns all members to target cluster
    - 56.3 [x] Test merge recalculates representatives and centroid (placeholder hooks)
    - 56.4 [x] Test merge creates audit log entry
    - 56.5 [x] Cover label update sets `is_labeled=True`, `is_confirmed=True`
    - 56.6 [x] Add `test_outlier_handling.py`
    - 56.7 [x] Test outliers are surfaced via `?include_outliers=true`

##### 7.4 ClusterService Completeness

56. [x] **[TDD]** Write cluster operations tests FIRST
    - 56.1 [x] Create `test_cluster_operations.py` (merge/label coverage)
    - 56.2 [x] Test merge reassigns all members to target cluster
    - 56.3 [x] Test merge recalculates representatives and centroid
    - 56.4 [x] Test merge creates audit log entry
    - 56.5 [x] Cover label update sets `is_labeled=True`, `is_confirmed=True`
    - 56.6 [x] Add `test_outlier_handling.py`
    - 56.7 [x] Test outliers are surfaced via `?include_outliers=true`
57. [x] Implement proper merge logic (make tests pass)
    - 57.1 [x] Reassign all members from source cluster to target
    - 57.2 [x] Recalculate representatives for merged cluster
    - 57.3 [x] Update centroid materialized view
    - 57.4 [x] Create audit log entry for merge operation
    - 57.5 [x] Delete or archive source cluster
58. [x] Implement label update with confirmation semantics (make tests pass)
    - 58.1 [x] Add confirmation semantics flag on cluster model (`user_confirmed`)
    - 58.2 [x] Label update sets `is_labeled=True`, `is_confirmed=True`
    - 58.3 [x] Trigger representative quality re-evaluation on label
59. [x] Implement outlier handling (make tests pass)
    - 59.1 [x] Create "Unclustered" pseudo-cluster or NULL handling
    - 59.2 [x] Surface outliers via `GET /clusters?include_outliers=true`
    - 59.3 [x] Allow manual assignment of outliers to existing clusters

##### 7.5 Job Orchestration

60. [ ] **[TDD]** Write job orchestration tests FIRST
    - 60.1 [x] Create `test_job_service.py`
    - 60.2 [x] Test job creation returns `pending` state
    - 60.3 [x] Test job transitions: `pending` → `running` → `completed`
    - 60.4 [x] Test job transitions: `pending` → `running` → `failed` with error message
    - 60.5 [x] Test progress tracking updates correctly
    - 60.6 [x] Create `test_background_tasks.py`
    - 60.7 [x] Test analyze job queues detection + embedding
    - 60.8 [x] Test clustering job queues discovery + gate + persistence
61. [x] Implement real JobService with background tasks (make tests pass)
    - 61.1 [x] Create `Job` domain model with states: `pending`, `running`, `completed`, `failed`
    - 61.2 [x] Create `JobRepository` for persistence
    - 61.3 [x] Implement progress tracking (completed/total counts)
    - 61.4 [x] Add error state with error message storage
62. [x] Implement background task execution (make tests pass)
    - 62.1 [x] Use FastAPI `BackgroundTasks` for queueing
    - 62.2 [x] Analyze jobs: queue face detection + embedding generation
    - 62.3 [x] Clustering jobs: queue discovery + gate + persistence
    - 62.4 [x] Update job progress during execution
63. [x] Add job polling and cancellation (make tests pass)
    - 63.1 [x] `GET /jobs/{id}` returns real-time progress
    - 63.2 [x] `POST /jobs/{id}/cancel` for long-running jobs (optional)

##### 7.5.5 Scaffold Cleanup (Remove Orphaned Stubs) — DO FIRST

> **Priority**: Complete before proceeding to 7.6+. Removes confusion about canonical implementations.
>
> **Context**: Phase 0.5 created scaffolds with `NotImplementedError` stubs. Many have been implemented in new locations (e.g., `persistence/assignment_writer.py`), leaving orphaned stub files.

80. [x] Remove orphaned `assignment/writer.py` scaffold
    - 80.1 [x] Verify `persistence/assignment_writer.py` is the canonical implementation
    - 80.2 [x] Update imports that reference `assignment.writer` → `persistence.assignment_writer`
    - 80.3 [x] Delete `recognition/application/assignment/writer.py` (orphaned stub)
81. [x] Implement domain model persistence methods or remove stubs
    - 81.1 [x] `IdentityCluster.get_representatives()` — removed stub; repository/service handles access
    - 81.2 [x] `IdentityCluster.compute_centroid()` — removed stub; use `CentroidUtils` in services
    - 81.3 [x] `AssignmentSuggestion.accept()` / `.reject()` — removed stubs; use `SuggestionService`
    - 81.4 [x] Decision: Domain models should be data-only; move behavior to services
82. [x] Clean up abstract base class stubs
    - 82.1 [x] Verify `ClusterRepository` ABC in `application/cluster_repository.py` vs `domain/repositories.py`
    - 82.2 [x] Consolidate to single repository interface location
    - 82.3 [x] Remove redundant abstract definitions

**Stub Audit Summary** (from `grep -rn "NotImplementedError" recognition/`):

| File                                    | Stub Location         | Status            | Resolution                                                       |
| --------------------------------------- | --------------------- | ----------------- | ---------------------------------------------------------------- |
| `application/assignment/writer.py`      | Lines 33, 49          | ✅ DELETED        | Task 80: Replaced by `persistence/assignment_writer.py`          |
| `application/cluster_repository.py`     | Lines 23-53 (7 stubs) | ✅ DELETED        | Task 82: Consolidated into `domain/repositories.py`              |
| `domain/cluster.py`                     | Lines 42, 53          | ✅ REMOVED        | Task 81: Domain models are data-only; use services               |
| `domain/suggestion.py`                  | Lines 38, 46          | ✅ REMOVED        | Task 81: Use `SuggestionService` for accept/reject               |
| `application/assignment/checks/base.py` | Lines 37, 52          | INTENTIONAL (ABC) | Abstract methods — implemented by `CompleteLinkCheck`, etc.      |
| `application/discovery/base.py`         | Line 34               | INTENTIONAL (ABC) | Abstract method — implemented by `Representative/Centroid/Graph` |
| `application/discovery/graph.py`        | Line 42               | INTENTIONAL (ABC) | Abstract method — implemented by `HDBSCAN/ChineseWhispers`       |
| `tests/test_*.py` (multiple)            | Various               | INTENTIONAL       | `DummyRepository` stubs for Protocol compliance tests            |

> **Note**: Remaining `NotImplementedError` stubs are **intentional abstract base class methods**. These define interfaces that concrete implementations must override. They are NOT orphaned stubs requiring cleanup.

##### 7.6 Embedding Acquisition

64. [x] **[TDD]** Write embedding pipeline tests FIRST
    - 64.1 [x] Create `test_face_detector.py`
    - 64.2 [x] Test detection returns bounding boxes with confidence scores
    - 64.3 [x] Test detection handles no-face images gracefully
    - 64.4 [x] Create `test_embedding_generator.py`
    - 64.5 [x] Test embedding output is 1024D vector (512 face + 512 metadata)
    - 64.6 [x] Test embedding normalization (unit vectors)
65. [x] Integrate face detection pipeline (make tests pass)
    - 65.1 [x] Create `FaceDetector` adapter wrapping InsightFace detection
    - 65.2 [x] Accept media bytes or URL, return bounding boxes + confidence
    - 65.3 [x] Store detection results in `media_identities` table
66. [x] Integrate embedding generation (make tests pass)
    - 66.1 [x] Create `EmbeddingGenerator` adapter wrapping InsightFace embedding
    - 66.2 [x] Generate 1024D embeddings (512 face + 512 metadata)
    - 66.3 [x] Store embeddings in `media_identities.embedding` column
67. [x] Wire detection → embedding → discovery flow (make tests pass)
    - 67.1 [x] `POST /analyze` triggers detection + embedding for each media ID
    - 67.2 [x] New identities are persisted with `cluster_id=NULL`
    - 67.3 [x] Subsequent clustering job picks up unclustered identities

##### 7.6.6 InsightFace Integration (Sprint 4.2.4 Completion)

> **Status**: Completed. Real InsightFace adapters are now wired and production-ready.

Implementation details:

**Files Created/Modified:**

- `recognition/domain/embeddings/__init__.py` - Module exports
- `recognition/domain/embeddings/layout.py` - 1024D extended embedding layout (512 face + 512 metadata)
- `recognition/domain/embeddings/builder.py` - Functions to build/extract extended embeddings
- `recognition/infrastructure/embeddings/__init__.py` - InsightFaceAdapter wrapping FaceAnalysis
- `recognition/application/embedding/detector.py` - Added FaceDetectorProtocol + InsightFaceFaceDetector
- `recognition/application/embedding/generator.py` - Added EmbeddingGeneratorProtocol + InsightFaceEmbeddingGenerator
- `recognition/config/settings.py` - Added InsightFaceSettings + runtime_mode
- `recognition/interface_adapters/http/dependencies.py` - Updated `get_scan_service_builder()` to inject real adapters
- `pyproject.toml` - Added `insightface>=0.7.3` to local/remote optional dependencies

**Runtime Modes:**

- `production` (default): Uses real InsightFace for face detection and 1024D embedding generation
- `test`: Uses deterministic stubs (hash-based) for reproducible integration tests

Set via environment variable: `RECOGNITION_RUNTIME_MODE=test`

**Architecture:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    Application Layer                            │
│  ┌─────────────────┐    ┌─────────────────────┐                │
│  │ FaceDetector    │    │ EmbeddingGenerator  │                │
│  │   Protocol      │    │     Protocol        │                │
│  └────────┬────────┘    └──────────┬──────────┘                │
│           │                        │                            │
│  ┌────────┴────────┐    ┌──────────┴──────────┐                │
│  │ Stub │ InsightFace  │ Stub │ InsightFace │                │
│  └────────┬────────┘    └──────────┬──────────┘                │
└───────────┼────────────────────────┼────────────────────────────┘
            │                        │
┌───────────┴────────────────────────┴────────────────────────────┐
│                    Infrastructure Layer                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              InsightFaceAdapter                           │   │
│  │  - detect_faces(bytes) → list[DetectedFace]              │   │
│  │  - generate_extended_embedding(face) → 1024D vector       │   │
│  │  - analyze(bytes) → list[(DetectedFace, embedding)]       │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

##### 7.6.5 Test Infrastructure Reorganization

> **Priority**: Complete before 7.7 Observability. Fixes 13 failing tests caused by mixing sync/async patterns and stub drift.

83. [x] Create test directory structure following TDD best practices
    - 83.1 [x] Create `recognition/tests/unit/` for logic tests with fakes
    - 83.2 [x] Create `recognition/tests/integration/` for real DB tests
    - 83.3 [x] Create `recognition/tests/api/` for HTTP contract tests
    - 83.4 [x] Move existing tests to appropriate directories
84. [x] Create reusable fake implementations in `conftest.py`
    - 84.1 [x] Create `FakeJobRepository` (in-memory)
    - 84.2 [x] Create `FakeClusterRepository` (in-memory)
    - 84.3 [x] Create `FakeClusterService` with correct method signatures
    - 84.4 [x] Create `FakeJobService` with correct method signatures
85. [x] Create API test fixtures in `tests/api/conftest.py`
    - 85.1 [x] Create `api_client` fixture with all dependencies faked
    - 85.2 [x] Override `get_session` to return None (no DB)
    - 85.3 [x] Override service builders to return fakes
86. [x] Fix async generator lifecycle issues (6 tests)
    - 86.1 [x] Convert `test_api_analyze.py` to use `api_client` fixture
    - 86.2 [x] Convert `test_dependencies.py` async tests to use proper fixtures
    - 86.3 [x] Use sync `TestClient` with fakes (no real async DB operations)
87. [x] Fix stub method signature drift (3 tests)
    - 87.1 [x] Add `include_outliers` parameter to all `list_clusters` stubs
    - 87.2 [x] Ensure all fake method signatures match production
88. [x] Fix transaction handling in integration tests (2 tests)
    - 88.1 [x] Update `db_session` fixture to use savepoints (`begin_nested()`)
    - 88.2 [x] Ensure test transactions rollback without conflicting with service commits
89. [x] Fix tenant validation logic (2 tests)
    - 89.1 [x] Add UUID format validation to `get_tenant_id` dependency
    - 89.2 [x] Return 400 for invalid UUID format (not 422)

##### 7.7 Observability Integration

68. [x] **[TDD]** Write observability tests FIRST
    - 68.1 [x] Create `test_observability_persistence.py`
    - 68.2 [x] Test `BatchJobReport` JSON is persisted correctly
    - 68.3 [x] Test decision logs are queryable
    - 68.4 [x] Create `test_diagnostics_endpoints.py`
    - 68.5 [x] Test `/diagnostics/decisions` returns paginated results
    - 68.6 [x] Test filters: `tenant_id`, `outcome`, `date_range`, `cluster_id`
69. [x] Persist observability outputs (make tests pass)
    - 69.1 [x] Store `BatchJobReport` JSON in `clustering_job_reports` table
    - 69.2 [x] Store decision logs in `assignment_decisions` table (optional)
    - 69.3 [x] Configure chart output directory or S3 bucket
70. [x] Wire diagnostics endpoints to real data (make tests pass)
    - 70.1 [x] `GET /diagnostics/decisions` queries persisted decision logs
    - 70.2 [x] Add filters: `tenant_id`, `outcome`, `date_range`, `cluster_id`
    - 70.3 [x] Paginate results for large datasets

##### 7.7.5 WordPress-Backend Contract Alignment

> **Priority**: HIGH — Frontend is returning 404/422 errors. Required for end-to-end integration.
>
> **Context**: The WordPress plugin proxy expects different request schemas and endpoints than the current backend provides.

**Current API Contract Gaps:**

| Issue Type       | Frontend Expects                       | Backend Has                    | Impact                |
| ---------------- | -------------------------------------- | ------------------------------ | --------------------- |
| Schema mismatch  | `media_items: [{media_id, media_url}]` | `media_ids: [string]`          | 422 on analyze        |
| Missing endpoint | `GET /recognition/jobs/{id}`           | Not implemented                | 404 on job polling    |
| Missing endpoint | `GET /recognition/training-stage`      | Not implemented                | 404 on stage check    |
| Missing endpoint | `GET /recognition/suggestions`         | `/identities/{id}/suggestions` | 404 wrong path        |
| Missing endpoint | `GET /recognition/media/identities`    | Not implemented                | 404 on identity fetch |

90. [x] Fix `/analyze` request schema to accept WordPress format

    - 90.1 [x] Update `AnalyzeRequest` to accept `media_items: list[MediaItem]`
    - 90.2 [x] Create `MediaItem` schema with `media_id: int` and `media_url: str`
    - 90.3 [x] Transform `media_items` → internal format in `ScanService`
    - 90.4 [x] Keep `media_ids` as optional for backward compatibility

91. [x] Add missing job polling endpoint

    - 91.1 [x] Add `GET /recognition/jobs/{job_id}` route in `jobs.py` router
    - 91.2 [x] Return `JobStatusResponse` with progress
    - 91.3 [x] Query both scan and clustering jobs by ID

92. [x] Add training stage endpoint

    - 92.1 [x] Add `GET /recognition/training-stage` route
    - 92.2 [x] Return cluster count, member count, curriculum stage
    - 92.3 [x] Used by frontend for adaptive threshold display

93. [x] Add suggestions list endpoint at correct path

    - 93.1 [x] Add `GET /recognition/suggestions` (top-level, not per-identity)
    - 93.2 [x] Accept `tenant_id`, `limit`, `offset` query params
    - 93.3 [x] Return paginated pending suggestions

94. [x] Add media identities endpoint

    - 94.1 [x] Add `GET /recognition/media/identities` route
    - 94.2 [x] Accept `media_ids[]` query param array
    - 94.3 [x] Return identities grouped by media_id with bbox, cluster info

95. [x] Update contract documentation
    - 95.1 [x] Add recognition endpoints to `docs/integration/wordpress-backend-contract.md`
    - 95.2 [x] Document request/response schemas
    - 95.3 [x] Add example payloads for each endpoint

##### 7.8 Security & Validation

71. [x] **[TDD]** Write security and validation tests FIRST
    - 71.1 [x] Create `test_authentication.py`
    - 71.2 [x] Test unauthenticated requests return 401
    - 71.3 [x] Test invalid token returns 403
    - 71.4 [x] Test tenant access permissions are enforced
    - 71.5 [x] Create `test_input_validation.py`
    - 71.6 [x] Test invalid UUID format returns 400
    - 71.7 [x] Test paging bounds (max limit, negative offset)
    - 71.8 [x] Test malicious string inputs are sanitized
    - 71.9 [x] Create `test_error_handling.py`
    - 71.10 [x] Test domain errors map to correct HTTP status codes
72. [x] Add authentication/authorization (make tests pass)
    - 72.1 [x] Integrate with existing auth system (API key validated against `api_keys` table; dev keys via env)
    - 72.2 [x] Verify tenant access permissions (tenant claim vs `X-Tenant-ID` in `require_auth`)
    - 72.3 [x] Add `@require_auth` dependency (APIRouters wired with FastAPI dependency)
    - 72.4 [x] Add FastAPI dependency for API key parsing (`recognition/interface_adapters/http/dependencies.py`)
    - 72.5 [x] Enforce role/scope checks for mutate endpoints (`require_write_access` dependency added)
    - 72.6 [x] Validate tenant ownership inside auth dependency (reject mismatched tenant claims vs headers)
    - 72.7 [x] Wire dependency into all routers (`dependencies.py`, router modules) and update DI factory
    - 72.8 [x] Document auth configuration in `docs/integration/security.md`
73. [x] Add input validation (make tests pass)
    - 73.1 [x] Validate UUID/base64 format on all ID parameters (`parse_id()` + `validate_entity_id()`)
    - 73.2 [x] Add paging bounds validation (max limit, valid offset)
    - 73.3 [x] Sanitize string inputs (labels, filters) — `validate_label()` rejects HTML, enforces length
74. [x] Implement consistent error handling (make tests pass)
    - 74.1 [x] Create `RecognitionError` exception hierarchy
    - 74.2 [x] Add global exception handler returning structured error responses
    - 74.3 [x] Map domain errors to appropriate HTTP status codes

##### 7.9 Domain Completeness

75. [x] **[TDD]** Write domain completeness tests FIRST
    - 75.1 [x] Create `test_representative_lifecycle.py`
    - 75.2 [x] Test ACCEPT decision evaluates representative candidacy
    - 75.3 [x] Test representative changes trigger centroid recomputation
    - 75.4 [x] Create `test_centroid_recomputation.py`
    - 75.5 [x] Test centroid recomputes after member additions
    - 75.6 [x] Test centroid recomputes after merges
76. [x] Wire representative persistence on updates (make tests pass)
    - 76.1 [x] After ACCEPT decision, evaluate if identity should become representative
    - 76.2 [x] Persist new representatives via `RepresentativeRepository`
    - 76.3 [x] Trigger centroid recomputation after representative changes
77. [x] Wire centroid recomputation hooks (make tests pass)
    - 77.1 [x] Recompute centroid after member additions (ACCEPT)
    - 77.2 [x] Recompute centroid after merges
    - 77.3 [x] Refresh materialized view or update in-table centroid

##### 7.10 End-to-End Integration Tests

78. [ ] **[TDD]** Write FAILING integration tests with real dependencies
    > **These tests MUST fail initially.** Run tests to confirm RED state before any implementation.
    - 78.1 [ ] Create test fixtures:
      - SQLAlchemy `AsyncSession` with test database (PostgreSQL or SQLite)
      - Tenant scoping via `X-Tenant-ID` header injection
      - Job tracking with real `JobRepository`
      - `FakeDetector` returning deterministic bounding boxes
      - `FakeEmbeddingGenerator` returning deterministic 1024D vectors
    - 78.2 [ ] Test full analyze → persist identities → cluster flow:
      - `POST /analyze` with media IDs → creates `MediaIdentity` records
      - Poll `GET /jobs/{id}` until `completed`
      - `POST /clustering/jobs` → runs discovery + gate
      - `GET /clusters` → returns newly created clusters with members
    - 78.3 [ ] Test tenant isolation:
      - Create identities for tenant A
      - Query with tenant B header → returns empty list
      - Verify cross-tenant queries never leak data
    - 78.4 [ ] Test merge operations:
      - Create two clusters, merge them
      - Verify all members reassigned
      - Verify source cluster deleted
    - 78.5 [ ] Test job state transitions:
      - Job starts as `pending`
      - Transitions to `running` when picked up
      - Ends as `completed` (success) or `failed` (with error message)
79. [ ] Add performance/load tests (optional)
    - 79.1 [ ] Benchmark clustering for 100, 500, 1000 identities
    - 79.2 [ ] Measure API response times under concurrent requests

---

### Phase Details

Below are the implementation details for each phase. The checklist above tracks completion status.

---

### Phase 3 Details: Graph Algorithms & Deterministic Clustering

> **Reference**: [ALGORITHM_EVALUATION.md](./ALGORITHM_EVALUATION.md) — HDBSCAN (CW removed)  
> **Reference**: [EMBEDDING_MODEL_EVALUATION.md](./EMBEDDING_MODEL_EVALUATION.md) — Face-only similarity enforcement  
> **Diagrams**: See `docs/agentic/diagrams/backend-uml/` for current architecture

#### 3.1 HDBSCAN Implementation

| Task | File                                                       | Details                                                                                                    |
| ---- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| 19a  | `recognition/infrastructure/clustering/hdbscan_adapter.py` | Create `HdbscanGraphAlgorithm` class implementing `GraphAlgorithm` (SCAFFOLDED)                            |
| 19b  | Same file                                                  | Implement `cluster(embeddings: Sequence[ndarray]) -> list[int]`                                            |
| 19c  | Same file                                                  | Parameters: `min_cluster_size=2`, `min_samples=1`, `cluster_selection_epsilon=0.12` (1.0 - 0.88 threshold) |
| 19d  | Same file                                                  | Return `-1` for noise/outlier points (explicit outlier handling per ALGORITHM_EVALUATION.md)               |

```python
# recognition/infrastructure/clustering/hdbscan.py
class HDBSCANClustering(GraphAlgorithm):
    def __init__(
        self,
        min_cluster_size: int = 2,
        min_samples: int = 1,
        epsilon: float = 0.12,  # 1.0 - similarity_threshold
    ) -> None: ...

    def cluster(self, embeddings: Sequence[np.ndarray]) -> list[int]:
        """Cluster face embeddings using HDBSCAN.

        Returns:
            List of cluster labels. -1 indicates noise/outlier.
        """
```

**Key Requirement**: Use face-only embeddings (512D). The caller (`GraphDiscovery`) must extract face embeddings before calling this.

#### 3.2 Deterministic Chinese Whispers Implementation

| Task | File                                                        | Details                                                                                      |
| ---- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 20a  | `recognition/infrastructure/clustering/chinese_whispers.py` | Create `DeterministicChineseWhispers` class (SCAFFOLDED)                                     |
| 20b  | Same file                                                   | Replace `np.random.shuffle(nodes)` with `sorted(nodes, key=lambda i: str(identities[i].id))` |
| 20c  | Same file                                                   | Implement quality-weighted voting: `vote = sim_matrix[i,j] * qualities[j]`                   |
| 20d  | Same file                                                   | Implement UUID tie-breaking when vote counts equal                                           |
| 20e  | Same file                                                   | Parameters: `threshold=0.88`, `max_iterations=50`                                            |

```python
# recognition/infrastructure/clustering/chinese_whispers.py
class ChineseWhispersClustering(GraphAlgorithm):
    def __init__(
        self,
        threshold: float = 0.88,
        max_iterations: int = 50,
    ) -> None: ...

    def cluster(
        self,
        embeddings: Sequence[np.ndarray],
        identities: Sequence[MediaIdentity] | None = None,
    ) -> list[int]:
        """Cluster using deterministic Chinese Whispers.

        Determinism achieved via:
        1. UUID-sorted node processing order
        2. Quality-weighted neighbor votes
        3. UUID tie-breaking for equal vote counts
        """
```

**Determinism Contract** (from implementation plan):

```python
# Node order: sorted by identity ID (not random)
node_order = sorted(range(n), key=lambda i: str(identities[i].id))

# Quality-weighted voting
for j in neighbors:
    weighted_vote = sim_matrix[i, j] * qualities[j]
    votes[label] = votes.get(label, 0.0) + weighted_vote

# UUID tie-breaking
max_vote = max(votes.values())
candidates = [lbl for lbl, v in votes.items() if v == max_vote]
if len(candidates) > 1:
    best_label = min(candidates, key=lambda lbl: min(
        str(identities[k].id) for k in range(n) if labels[k] == lbl
    ))
```

#### 3.3 GraphDiscovery Integration

| Task | File                                         | Details                                                             |
| ---- | -------------------------------------------- | ------------------------------------------------------------------- |
| 21a  | `recognition/application/discovery/graph.py` | Implement `discover()` method using pluggable algorithm             |
| 21b  | Same file                                    | Auto-select: HDBSCAN if len(identities) ≤ 500, else ChineseWhispers |
| 21c  | Same file                                    | Extract face embeddings (512D) before passing to algorithm          |
| 21d  | Same file                                    | Match new clusters to existing anchors (if provided)                |
| 21e  | Same file                                    | Create `AssignmentCandidate` for each cluster-anchor match          |

```python
# GraphDiscovery.discover() flow
def discover(
    self,
    identities: list[MediaIdentity],
    anchor_embeddings: dict[str, list[np.ndarray]] | None = None,
) -> list[AssignmentCandidate]:
    # 1. Extract face embeddings (CRITICAL: avoid metadata dilution)
    face_embeddings = [extract_face_embedding(i.embedding) for i in identities]

    # 2. Run clustering algorithm
    labels = self.algorithm.cluster(face_embeddings, identities)

    # 3. Group by label (excluding noise: -1)
    clusters_by_label = self._group_by_label(identities, labels)

    # 4. Match to existing clusters via anchors
    candidates = []
    for label, members in clusters_by_label.items():
        if anchor_embeddings:
            best_anchor, similarity = self._match_to_anchor(members, anchor_embeddings)
            if best_anchor and similarity >= self.settings.threshold:
                for member in members:
                    candidates.append(AssignmentCandidate(
                        identity=member,
                        identity_vector=extract_face_embedding(member.embedding),
                        cluster_id=best_anchor,
                        discovery_method=DiscoveryMethod.GRAPH,
                        discovery_similarity=similarity,
                    ))

    return candidates
```

#### 3.4 Face-Only Similarity Enforcement

| Task | File                               | Details                                                           |
| ---- | ---------------------------------- | ----------------------------------------------------------------- |
| 22a  | `recognition/shared/similarity.py` | Create `extract_face_embedding(embedding: ndarray) -> ndarray`    |
| 22b  | Same file                          | Create `compute_face_similarity(a: ndarray, b: ndarray) -> float` |
| 22c  | All discovery files                | Audit and update to use face-only embeddings                      |
| 22d  | `centroid_utils.py`                | Verify existing fix extracts 512D before similarity               |

```python
# recognition/shared/similarity.py
FACE_EMBEDDING_DIM = 512

def extract_face_embedding(embedding: np.ndarray) -> np.ndarray:
    """Extract face identity portion from extended embedding.

    Extended embeddings (1024D) contain:
    - Dims 0-511: Face identity embedding
    - Dims 512-1023: Metadata (pose, age, gender, detection score)

    This function returns ONLY the face portion to avoid metadata dilution.
    """
    if len(embedding) == FACE_EMBEDDING_DIM:
        return embedding  # Already face-only
    return embedding[:FACE_EMBEDDING_DIM]

def compute_face_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity using face embeddings only."""
    face_a = extract_face_embedding(a)
    face_b = extract_face_embedding(b)
    norm_a = face_a / np.linalg.norm(face_a)
    norm_b = face_b / np.linalg.norm(face_b)
    return float(np.dot(norm_a, norm_b))
```

#### 3.5 Phase 3 Tests

| Test File                    | Test Case                                   | Validates                                |
| ---------------------------- | ------------------------------------------- | ---------------------------------------- |
| `test_hdbscan_clustering.py` | `test_hdbscan_deterministic_output`         | Same input → same clusters               |
| `test_hdbscan_clustering.py` | `test_hdbscan_outlier_detection`            | Noise points labeled -1                  |
| `test_chinese_whispers.py`   | `test_cw_deterministic_same_input`          | UUID-sorted order is stable              |
| `test_chinese_whispers.py`   | `test_cw_uuid_tiebreaking`                  | Tie-breaking uses smallest UUID          |
| `test_chinese_whispers.py`   | `test_cw_quality_weighting`                 | Higher quality faces have more influence |
| `test_similarity.py`         | `test_extract_face_embedding_1024d`         | Returns first 512D                       |
| `test_similarity.py`         | `test_extract_face_embedding_512d`          | Returns as-is                            |
| `test_similarity.py`         | `test_compute_face_similarity`              | Uses face portion only                   |
| `test_graph_discovery.py`    | `test_graph_discovery_uses_face_embeddings` | No 1024D vectors in algorithm            |
| `test_graph_discovery.py`    | `test_graph_discovery_selects_algorithm`    | HDBSCAN ≤500, CW >500                    |

---

### Phase 4 Details: Observability & Logging

**Goal**: Implement comprehensive logging and visualization for debugging and monitoring.

> **Diagrams**: See `docs/agentic/diagrams/backend-uml/observability/` and `components/assignment-gate.mmd`

#### 4.1 ClusteringLogger Implementation

| Task | File                                   | Details                                                                              |
| ---- | -------------------------------------- | ------------------------------------------------------------------------------------ |
| 24a  | `recognition/observability/logging.py` | Complete `log_decision()` implementation                                             |
| 24b  | Same file                              | Implement `log_batch_start(identity_count, algorithm, tenant_id)`                    |
| 24c  | Same file                              | Implement `log_batch_complete(report: BatchJobReport)`                               |
| 24d  | Same file                              | Use structured JSON format for log entries                                           |
| 24e  | Same file                              | Include: timestamp, identity_id, cluster_id, decision, similarity, reason, algorithm |

```python
# recognition/observability/logging.py
class ClusteringLogger:
    def log_decision(
        self,
        identity_id: str,
        cluster_id: str | None,
        decision: DecisionType,  # ACCEPT | SUGGEST | REJECT
        similarity: float | None = None,
        reason: str | None = None,
        checks_passed: list[str] | None = None,
        checks_failed: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DecisionLog:
        """Record a single assignment decision for observability.

        Log format (JSON):
        {
            "timestamp": "2025-12-02T10:30:00Z",
            "identity_id": "25491a7Bx9kL2",
            "cluster_id": "25483mN3pQ8Yz",
            "decision": "ACCEPT",
            "similarity": 0.92,
            "checks_passed": ["MaturityCheck", "CompleteLinkCheck"],
            "checks_failed": [],
            "reason": null
        }
        """

    def log_batch_start(
        self,
        identity_count: int,
        algorithm: str,
        tenant_id: str,
    ) -> None:
        """Log the start of a clustering batch."""

    def log_batch_complete(self, report: BatchJobReport) -> None:
        """Log batch completion with summary metrics."""
```

#### 4.2 BatchJobReport Implementation

| Task | File                                   | Details                                                            |
| ---- | -------------------------------------- | ------------------------------------------------------------------ |
| 25a  | `recognition/observability/reports.py` | Complete dataclass with all metrics                                |
| 25b  | Same file                              | Implement `add_decision(decision: AssignmentDecision)` accumulator |
| 25c  | Same file                              | Implement `duration_ms() -> int`                                   |
| 25d  | Same file                              | Implement `success_rate() -> float` (accepts / total)              |
| 25e  | Same file                              | Implement `to_json() -> str` for persistence                       |

```python
# recognition/observability/reports.py
@dataclass
class BatchJobReport:
    job_id: str
    tenant_id: str
    algorithm: str  # "representative" | "centroid" | "hdbscan" | "chinese_whispers"
    started_at: datetime
    finished_at: datetime | None = None

    # Counters
    total_identities: int = 0
    accept_count: int = 0
    suggest_count: int = 0
    reject_count: int = 0
    clusters_created: int = 0
    clusters_updated: int = 0

    # Aggregates
    similarity_sum: float = 0.0
    similarity_count: int = 0

    def add_decision(self, decision: AssignmentDecision) -> None:
        """Accumulate a decision into the report."""
        match decision.outcome:
            case AssignmentOutcome.ACCEPT:
                self.accept_count += 1
            case AssignmentOutcome.SUGGEST:
                self.suggest_count += 1
            case AssignmentOutcome.REJECT:
                self.reject_count += 1

        if decision.candidate.discovery_similarity:
            self.similarity_sum += decision.candidate.discovery_similarity
            self.similarity_count += 1

    def duration_ms(self) -> int:
        """Calculate job duration in milliseconds."""
        if not self.finished_at:
            return 0
        return int((self.finished_at - self.started_at).total_seconds() * 1000)

    def success_rate(self) -> float:
        """Calculate acceptance rate (accepts / total processed)."""
        total = self.accept_count + self.suggest_count + self.reject_count
        return self.accept_count / total if total > 0 else 0.0

    def avg_similarity(self) -> float:
        """Calculate average similarity across all decisions."""
        return self.similarity_sum / self.similarity_count if self.similarity_count > 0 else 0.0

    def to_json(self) -> str:
        """Serialize report to JSON for persistence."""
```

#### 4.3 ClusterVisualizer Implementation

| Task | File                                         | Details                                                |
| ---- | -------------------------------------------- | ------------------------------------------------------ |
| 26a  | `recognition/observability/visualization.py` | Implement `generate_batch_report_chart()`              |
| 26b  | Same file                                    | Create stacked bar chart: accept/suggest/reject counts |
| 26c  | Same file                                    | Implement `generate_similarity_histogram()`            |
| 26d  | Same file                                    | Save charts to configurable `output_dir`               |
| 26e  | Same file                                    | Use matplotlib (already available in requirements)     |

```python
# recognition/observability/visualization.py
class ClusterVisualizer:
    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("./logs/charts")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_batch_report_chart(
        self,
        report: BatchJobReport,
        filename: str | None = None,
    ) -> Path:
        """Generate a bar chart showing accept/suggest/reject distribution.

        Returns:
            Path to the saved chart image.
        """
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 6))
        categories = ["Accept", "Suggest", "Reject"]
        counts = [report.accept_count, report.suggest_count, report.reject_count]
        colors = ["#4CAF50", "#FFC107", "#F44336"]

        ax.bar(categories, counts, color=colors)
        ax.set_title(f"Clustering Results - {report.algorithm}")
        ax.set_ylabel("Count")

        # Save
        fname = filename or f"batch_{report.job_id}_{report.started_at:%Y%m%d_%H%M%S}.png"
        path = self.output_dir / fname
        fig.savefig(path, dpi=100, bbox_inches="tight")
        plt.close(fig)

        return path

    def generate_similarity_histogram(
        self,
        similarities: list[float],
        cluster_id: str,
        filename: str | None = None,
    ) -> Path:
        """Generate a histogram of similarity scores for a cluster."""
```

#### 4.4 ClusterService Integration

| Task | File                                                       | Details                                                                                  |
| ---- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| 27a  | `recognition/application/orchestration/cluster_service.py` | Add `logger: ClusteringLogger` to constructor                                            |
| 27b  | Same file                                                  | Add `visualizer: ClusterVisualizer` to constructor                                       |
| 27c  | Same file                                                  | Call `logger.log_batch_start()` at workflow start                                        |
| 27d  | Same file                                                  | Call `logger.log_decision()` after each gate evaluation                                  |
| 27e  | Same file                                                  | Call `report.add_decision()` to accumulate metrics                                       |
| 27f  | Same file                                                  | Call `logger.log_batch_complete()` and `visualizer.generate_batch_report_chart()` at end |

```python
# In ClusterService.cluster_unclustered_identities()
async def cluster_unclustered_identities(self, tenant_id: str) -> ClusteringResult:
    report = BatchJobReport(
        job_id=generate_short_id(),
        tenant_id=tenant_id,
        algorithm="mixed",
        started_at=datetime.utcnow(),
        total_identities=len(identities),
    )

    self.logger.log_batch_start(len(identities), "mixed", tenant_id)

    # ... discovery and gate evaluation ...

    for candidate in all_candidates:
        decision = await self.gate.evaluate(candidate)

        # Log each decision
        self.logger.log_decision(
            identity_id=str(candidate.identity.id),
            cluster_id=str(candidate.cluster_id) if candidate.cluster_id else None,
            decision=DecisionType(decision.outcome.value),
            similarity=candidate.discovery_similarity,
            reason=decision.rejection_reason,
            checks_passed=decision.checks_passed,
            checks_failed=decision.checks_failed,
        )

        # Accumulate into report
        report.add_decision(decision)

        # Handle outcome
        match decision.outcome:
            case AssignmentOutcome.ACCEPT:
                await self.writer.assign(candidate)
            case AssignmentOutcome.SUGGEST:
                await self.suggestions.create(candidate, decision.suggestion_confidence)

    # Complete report
    report.finished_at = datetime.utcnow()
    self.logger.log_batch_complete(report)
    self.visualizer.generate_batch_report_chart(report)

    return ClusteringResult(report=report)
```

#### 4.5 Phase 4 Tests

| Test File                    | Test Case                                | Validates                       |
| ---------------------------- | ---------------------------------------- | ------------------------------- |
| `test_clustering_logger.py`  | `test_log_decision_creates_entry`        | Decision logged correctly       |
| `test_clustering_logger.py`  | `test_log_batch_start_format`            | Start log has required fields   |
| `test_clustering_logger.py`  | `test_log_batch_complete_format`         | Complete log has metrics        |
| `test_batch_job_report.py`   | `test_add_decision_increments_counters`  | Counters updated                |
| `test_batch_job_report.py`   | `test_duration_ms_calculation`           | Duration calculated correctly   |
| `test_batch_job_report.py`   | `test_success_rate_calculation`          | Rate = accepts / total          |
| `test_batch_job_report.py`   | `test_to_json_serialization`             | Valid JSON output               |
| `test_cluster_visualizer.py` | `test_generate_batch_chart_creates_file` | PNG file created                |
| `test_cluster_visualizer.py` | `test_generate_histogram_creates_file`   | PNG file created                |
| `test_cluster_service.py`    | `test_service_logs_decisions`            | Logger called for each decision |

---

> **⚠️ Section Order Note**: Phase 5 (Database Persistence) should be read BEFORE Phase 6 (API Integration), as the API depends on the repository implementations. Due to document history, the sections appear in reverse order below. **Read Phase 5 Details first**, then return here for Phase 6.
>
> - [Jump to Phase 5 Details: Database Persistence](#phase-5-details-database-persistence-blocking)

---

### Phase 6 Details: API Integration (depends on Phase 5)

**Goal**: Expose the unified recognition service via REST API with full endpoint coverage.

> **Dependency**: Requires Phase 5 repositories to wire real services.  
> **Reference**: [recognition_service_api_plan.md](./recognition_service_api_plan.md) — Full API specification  
> **Diagrams**: See `docs/agentic/diagrams/backend-uml/workflows/unified-assignment.mmd`  
> **Contract**: All IDs use UUIDv7 internally, displayed as 22-char base64 in responses

#### 6.1 Request/Response Schemas

| Task | File                                                       | Details                                     |
| ---- | ---------------------------------------------------------- | ------------------------------------------- |
| 36a  | `recognition/interface_adapters/http/schemas/requests.py`  | Create all request models                   |
| 36b  | `recognition/interface_adapters/http/schemas/responses.py` | Create all response models                  |
| 36c  | Both files                                                 | Use `UUID` for all IDs (base64 display)     |
| 36d  | Both files                                                 | Add Pydantic serializers for base64 display |

```python
# recognition/interface_adapters/http/schemas/requests.py
from pydantic import BaseModel, Field
from typing import Literal

class AnalyzeRequest(BaseModel):
    media_ids: list[str] = Field(..., min_length=1)
    tenant_id: str

class ClusteringJobRequest(BaseModel):
    tenant_id: str
    mode: Literal["sync", "async"] = "async"

class PatchClusterRequest(BaseModel):
    tenant_id: str
    label: str | None = None

class MergeClusterRequest(BaseModel):
    tenant_id: str
    target_label: str

class SuggestionActionRequest(BaseModel):
    tenant_id: str

# recognition/interface_adapters/http/schemas/responses.py
from pydantic import BaseModel
from datetime import datetime
from typing import Literal

class BboxResponse(BaseModel):
    w: int
    h: int

class IdentityResponse(BaseModel):
    id: str  # UUID as 22-char base64
    tenant_id: str
    media_id: str
    bbox: BboxResponse
    confidence: float

class RepresentativeResponse(BaseModel):
    id: str
    media_id: str
    thumb_url: str | None = None

class ClusterResponse(BaseModel):
    id: str  # UUID as 22-char base64
    tenant_id: str
    label: str | None
    is_labeled: bool
    member_count: int
    representatives: list[RepresentativeResponse]

class SuggestionResponse(BaseModel):
    id: str
    identity_id: str
    cluster_id: str
    rep_similarity: float
    member_similarity: float | None
    status: Literal["pending", "accepted", "rejected"]

class JobProgressResponse(BaseModel):
    completed: int
    total: int

class JobStatusResponse(BaseModel):
    id: str
    type: Literal["analyze", "clustering"]
    status: Literal["pending", "running", "completed", "failed"]
    progress: JobProgressResponse | None
    started_at: datetime
    finished_at: datetime | None

class HealthResponse(BaseModel):
    service: str = "recognition"
    status: str = "ok"
    version: str | None = None
```

#### 6.2 Router Implementation

| Task | File                                                         | Details                                                                                              |
| ---- | ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| 37a  | `recognition/interface_adapters/http/routers/analyze.py`     | `POST /analyze`, `GET /jobs/{job_id}`                                                                |
| 38a  | `recognition/interface_adapters/http/routers/clusters.py`    | `POST /clustering/jobs`, `GET /clusters`, `PATCH /clusters/{id}`, `POST /clusters/{id}/merge`        |
| 39a  | `recognition/interface_adapters/http/routers/suggestions.py` | `GET /identities/{id}/suggestions`, `POST /suggestions/{id}/accept`, `POST /suggestions/{id}/reject` |
| 40a  | `recognition/interface_adapters/http/routers/diagnostics.py` | `GET /diagnostics/decisions` (optional)                                                              |

```python
# recognition/interface_adapters/http/routers/analyze.py
from fastapi import APIRouter, Depends, HTTPException
from recognition.interface_adapters.http.schemas.requests import AnalyzeRequest
from recognition.interface_adapters.http.schemas.responses import JobStatusResponse
from recognition.interface_adapters.http.dependencies import get_scan_service, get_job_service

router = APIRouter(tags=["analyze"])

@router.post("/analyze", response_model=JobStatusResponse)
async def analyze_media(
    request: AnalyzeRequest,
    scan_service = Depends(get_scan_service),
    job_service = Depends(get_job_service),
):
    """Scan media for face identities. Returns a job ID for polling."""
    job_id = await job_service.create_scan_job(request.media_ids, request.tenant_id)
    return await job_service.get_job_status(job_id)

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    job_service = Depends(get_job_service),
):
    """Poll job status by ID."""
    job = await job_service.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

# recognition/interface_adapters/http/routers/clusters.py
from fastapi import APIRouter, Depends, HTTPException, Query
from recognition.interface_adapters.http.schemas.requests import ClusteringJobRequest, PatchClusterRequest, MergeClusterRequest
from recognition.interface_adapters.http.schemas.responses import JobStatusResponse, ClusterResponse
from recognition.interface_adapters.http.dependencies import get_cluster_service, get_job_service

router = APIRouter(tags=["clusters"])

@router.post("/clustering/jobs", response_model=JobStatusResponse)
async def create_clustering_job(
    request: ClusteringJobRequest,
    cluster_service = Depends(get_cluster_service),
    job_service = Depends(get_job_service),
):
    """Trigger clustering for unclustered identities."""
    if request.mode == "sync":
        result = await cluster_service.cluster_unclustered_identities(request.tenant_id)
        return JobStatusResponse(
            id=result.report.job_id,
            type="clustering",
            status="completed",
            progress=JobProgressResponse(completed=result.report.total_identities, total=result.report.total_identities),
            started_at=result.report.started_at,
            finished_at=result.report.finished_at,
        )
    else:
        job_id = await job_service.create_cluster_job(request.tenant_id)
        return await job_service.get_job_status(job_id)

@router.get("/clusters", response_model=list[ClusterResponse])
async def list_clusters(
    tenant_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cluster_service = Depends(get_cluster_service),
):
    """List clusters with paging."""
    return await cluster_service.list_clusters(tenant_id, limit=limit, offset=offset)

@router.patch("/clusters/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: str,
    request: PatchClusterRequest,
    cluster_service = Depends(get_cluster_service),
):
    """Update cluster label."""
    cluster = await cluster_service.update_cluster(cluster_id, request.tenant_id, label=request.label)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster

@router.post("/clusters/{cluster_id}/merge", response_model=ClusterResponse)
async def merge_cluster(
    cluster_id: str,
    request: MergeClusterRequest,
    cluster_service = Depends(get_cluster_service),
):
    """Merge cluster into target (by label)."""
    return await cluster_service.merge_cluster(cluster_id, request.tenant_id, request.target_label)

# recognition/interface_adapters/http/routers/suggestions.py
from fastapi import APIRouter, Depends, HTTPException
from recognition.interface_adapters.http.schemas.responses import SuggestionResponse
from recognition.interface_adapters.http.dependencies import get_suggestion_service

router = APIRouter(tags=["suggestions"])

@router.get("/identities/{identity_id}/suggestions", response_model=list[SuggestionResponse])
async def list_suggestions(
    identity_id: str,
    suggestion_service = Depends(get_suggestion_service),
):
    """List pending suggestions for an identity."""
    return await suggestion_service.list_for_identity(identity_id)

@router.post("/suggestions/{suggestion_id}/accept", response_model=SuggestionResponse)
async def accept_suggestion(
    suggestion_id: str,
    suggestion_service = Depends(get_suggestion_service),
):
    """Accept a suggestion, persisting the assignment."""
    suggestion = await suggestion_service.accept(suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return suggestion

@router.post("/suggestions/{suggestion_id}/reject", response_model=SuggestionResponse)
async def reject_suggestion(
    suggestion_id: str,
    suggestion_service = Depends(get_suggestion_service),
):
    """Reject a suggestion."""
    suggestion = await suggestion_service.reject(suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return suggestion
```

#### 6.3 Dependency Injection Factory

| Task | File                                                  | Details                                                                                          |
| ---- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| 41a  | `recognition/interface_adapters/http/dependencies.py` | Create service factory functions                                                                 |
| 41b  | Same file                                             | Wire all dependencies (Gate, Discovery, Repositories, Settings, Logger) — **blocked on Phase 5** |
| 41c  | Same file                                             | Use FastAPI `Depends()` pattern                                                                  |

```python
# recognition/interface_adapters/http/dependencies.py
from functools import lru_cache
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.assignment.gate import AssignmentGate
from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.discovery.centroid import CentroidDiscovery
from recognition.application.discovery.graph import GraphDiscovery
from recognition.application.orchestration.cluster_service import ClusterService
from recognition.application.orchestration.scan_service import ScanService
from recognition.application.orchestration.job_service import JobService
from recognition.application.suggestions.service import SuggestionService
from recognition.application.assignment.writer import AssignmentWriter
from recognition.application.cluster_repository import ClusterRepository
from recognition.application.settings import ClusteringSettings
from recognition.observability.logging import ClusteringLogger
from recognition.observability.visualization import ClusterVisualizer
from recognition.infrastructure.clustering.hdbscan import HDBSCANClustering
from recognition.infrastructure.clustering.chinese_whispers import ChineseWhispersClustering

@lru_cache
def get_settings() -> ClusteringSettings:
    return ClusteringSettings()

def get_cluster_repository(session: AsyncSession = Depends(get_db_session)) -> ClusterRepository:
    return ClusterRepository(session)

def get_assignment_gate(
    settings: ClusteringSettings = Depends(get_settings),
    repository: ClusterRepository = Depends(get_cluster_repository),
) -> AssignmentGate:
    return AssignmentGate(settings, repository)

def get_graph_discovery(settings: ClusteringSettings = Depends(get_settings)) -> GraphDiscovery:
    # Default to HDBSCAN; ClusterService will swap based on batch size
    return GraphDiscovery(settings, HDBSCANClustering())

def get_cluster_service(
    gate: AssignmentGate = Depends(get_assignment_gate),
    settings: ClusteringSettings = Depends(get_settings),
    repository: ClusterRepository = Depends(get_cluster_repository),
    graph_discovery: GraphDiscovery = Depends(get_graph_discovery),
) -> ClusterService:
    return ClusterService(
        gate=gate,
        representative_discovery=RepresentativeDiscovery(settings),
        centroid_discovery=CentroidDiscovery(settings),
        graph_discovery=graph_discovery,
        writer=AssignmentWriter(repository),
        suggestions=SuggestionService(repository),
        repository=repository,
        logger=ClusteringLogger(),
        visualizer=ClusterVisualizer(),
    )

def get_scan_service() -> ScanService:
    # Stub for now - return 501 if called
    return ScanService()

def get_job_service() -> JobService:
    return JobService()

def get_suggestion_service(
    repository: ClusterRepository = Depends(get_cluster_repository),
) -> SuggestionService:
    return SuggestionService(repository)
```

#### 6.4 Main Application Integration

| Task | File                                             | Details                                    |
| ---- | ------------------------------------------------ | ------------------------------------------ |
| 42a  | `apps/prototype-description-service/api/main.py` | Import all routers                         |
| 42b  | Same file                                        | Include routers with `/recognition` prefix |
| 42c  | Same file                                        | Add health check                           |

```python
# apps/prototype-description-service/api/main.py
from fastapi import FastAPI
from recognition.interface_adapters.http.routers import analyze, clusters, suggestions, diagnostics
from recognition.interface_adapters.http.router import router as health_router

app = FastAPI(title="Prototype Description Service")

# Recognition service routes
app.include_router(health_router)  # /recognition/health
app.include_router(analyze.router, prefix="/recognition")
app.include_router(clusters.router, prefix="/recognition")
app.include_router(suggestions.router, prefix="/recognition")
# Optional: app.include_router(diagnostics.router, prefix="/recognition")
```

#### 6.5 Phase 6 Tests

| Test File                 | Test Case                      | Validates                              |
| ------------------------- | ------------------------------ | -------------------------------------- |
| `test_api_analyze.py`     | `test_analyze_creates_job`     | POST /analyze returns job_id           |
| `test_api_analyze.py`     | `test_get_job_status`          | GET /jobs/{id} returns status          |
| `test_api_clusters.py`    | `test_clustering_job_sync`     | POST /clustering/jobs?mode=sync works  |
| `test_api_clusters.py`    | `test_list_clusters_paging`    | GET /clusters respects limit/offset    |
| `test_api_clusters.py`    | `test_patch_cluster_label`     | PATCH /clusters/{id} updates label     |
| `test_api_clusters.py`    | `test_merge_clusters`          | POST /clusters/{id}/merge works        |
| `test_api_suggestions.py` | `test_list_suggestions`        | GET /identities/{id}/suggestions works |
| `test_api_suggestions.py` | `test_accept_suggestion`       | POST /suggestions/{id}/accept persists |
| `test_api_suggestions.py` | `test_reject_suggestion`       | POST /suggestions/{id}/reject works    |
| `test_api_short_ids.py`   | `test_responses_use_short_ids` | No UUIDs with dashes in responses      |
| `test_api_health.py`      | `test_health_endpoint`         | GET /recognition/health returns ok     |

#### 6.6 Greenfield Notes (No Migration Required)

| Task           | Status | Reason                                        |
| -------------- | ------ | --------------------------------------------- |
| Feature flags  | N/A    | No gradual rollout needed                     |
| Data migration | N/A    | Fresh database schema                         |
| Legacy cleanup | N/A    | Old code already in `apps/archived-*` folders |

---

### Phase 5 Details: Database Persistence (BLOCKING)

> **Reading Order**: This section should be read BEFORE Phase 6 Details above.  
> After completing Phase 5, return to [Phase 6 Details: API Integration](#phase-6-details-api-integration-depends-on-phase-5).

**Goal**: Implement repository pattern for persisting cluster assignments to PostgreSQL using SQLAlchemy async.

> **Critical Path**: Without this phase, clustering results are lost and API cannot wire real services.  
> **Diagrams**: See `docs/agentic/diagrams/backend-uml/persistence.mmd`  
> **DB Reference**: `db/models.py` — Existing SQLAlchemy models

#### 5.1 Repository Protocol Definitions

| Task | File                                 | Details                                               |
| ---- | ------------------------------------ | ----------------------------------------------------- |
| 29a  | `recognition/domain/repositories.py` | Define `ClusterRepository` protocol                   |
| 29b  | Same file                            | Define `get_by_id`, `get_by_tenant`, `save`, `update` |
| 30a  | Same file                            | Define `MemberRepository` protocol                    |
| 30b  | Same file                            | Define `get_by_cluster`, `add_member`, `bulk_add`     |

```python
# recognition/domain/repositories.py
from typing import Protocol, Sequence
from uuid import UUID
from recognition.domain.models import IdentityCluster, IdentityMember, MemberData


class ClusterRepository(Protocol):
    """Abstract interface for cluster persistence.

    Implementation notes:
    - Use async/await for all methods
    - Return domain models, not SQLAlchemy models
    - Raise custom exceptions (ClusterNotFoundError, etc.)
    """

    async def get_by_id(self, cluster_id: UUID) -> IdentityCluster | None:
        """Fetch a single cluster by ID. Returns None if not found."""
        ...

    async def get_by_tenant(
        self,
        tenant_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IdentityCluster]:
        """Fetch all clusters for a tenant with pagination."""
        ...

    async def save(self, cluster: IdentityCluster) -> IdentityCluster:
        """Create a new cluster. Returns saved cluster with generated ID."""
        ...

    async def update(self, cluster: IdentityCluster) -> IdentityCluster:
        """Update an existing cluster's metadata (label, representative, etc.)."""
        ...

    async def delete(self, cluster_id: UUID) -> None:
        """Delete a cluster and all its members (cascade)."""
        ...


class MemberRepository(Protocol):
    """Abstract interface for cluster member persistence."""

    async def get_by_cluster(self, cluster_id: UUID) -> list[IdentityMember]:
        """Fetch all members belonging to a cluster."""
        ...

    async def add_member(
        self,
        cluster_id: UUID,
        identity_id: UUID,
        similarity: float,
    ) -> IdentityMember:
        """Add a single member to a cluster."""
        ...

    async def bulk_add_members(
        self,
        cluster_id: UUID,
        members: Sequence[MemberData],
    ) -> list[IdentityMember]:
        """Bulk insert members for efficiency. Use for graph clustering results."""
        ...

    async def remove_member(self, member_id: UUID) -> None:
        """Remove a member from a cluster."""
        ...


# Supporting types
@dataclass(frozen=True)
class MemberData:
    """Input data for bulk member creation."""
    identity_id: UUID
    similarity: float
```

#### 5.2 SqlAlchemy Repository Implementation

| Task | File                                                            | Details                                        |
| ---- | --------------------------------------------------------------- | ---------------------------------------------- |
| 31a  | `recognition/infrastructure/repositories/cluster_repository.py` | Create `SqlAlchemyClusterRepository`           |
| 31b  | Same file                                                       | Inject `AsyncSession` via constructor          |
| 31c  | Same file                                                       | Convert between domain ↔ SQLAlchemy models     |
| 32a  | `recognition/infrastructure/repositories/member_repository.py`  | Create `SqlAlchemyMemberRepository`            |
| 32b  | Same file                                                       | Use `insert(...).values(...)` for bulk inserts |

```python
# recognition/infrastructure/repositories/cluster_repository.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import IdentityCluster as ClusterModel
from recognition.domain.models import IdentityCluster
from recognition.domain.repositories import ClusterRepository


class SqlAlchemyClusterRepository(ClusterRepository):
    """SQLAlchemy async implementation of ClusterRepository.

    Dev Hints:
    - Always use `await session.flush()` instead of `await session.commit()`
      within service methods. Let the caller control transaction boundaries.
    - Use `selectinload()` for eager loading members to avoid N+1 queries.
    - Convert UUID ↔ str when needed for domain models.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, cluster_id: UUID) -> IdentityCluster | None:
        stmt = (
            select(ClusterModel)
            .where(ClusterModel.id == cluster_id)
            .options(selectinload(ClusterModel.members))
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_tenant(
        self,
        tenant_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IdentityCluster]:
        stmt = (
            select(ClusterModel)
            .where(ClusterModel.tenant_id == tenant_id)
            .options(selectinload(ClusterModel.members))
            .limit(limit)
            .offset(offset)
            .order_by(ClusterModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def save(self, cluster: IdentityCluster) -> IdentityCluster:
        model = self._to_model(cluster)
        self._session.add(model)
        await self._session.flush()  # Generate ID, don't commit
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, cluster: IdentityCluster) -> IdentityCluster:
        stmt = (
            select(ClusterModel)
            .where(ClusterModel.id == cluster.id)
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one()
        # Update mutable fields only
        model.label = cluster.label
        model.representative_identity_id = cluster.representative_identity_id
        model.identity_count = cluster.identity_count
        model.user_confirmed = cluster.user_confirmed
        await self._session.flush()
        return self._to_domain(model)

    async def delete(self, cluster_id: UUID) -> None:
        stmt = select(ClusterModel).where(ClusterModel.id == cluster_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()

    def _to_domain(self, model: ClusterModel) -> IdentityCluster:
        """Convert SQLAlchemy model to domain model."""
        return IdentityCluster(
            id=model.id,
            tenant_id=model.tenant_id,
            label=model.label,
            representative_identity_id=model.representative_identity_id,
            identity_count=model.identity_count,
            clustering_algorithm=model.clustering_algorithm,
            user_confirmed=model.user_confirmed,
            created_at=model.created_at,
        )

    def _to_model(self, domain: IdentityCluster) -> ClusterModel:
        """Convert domain model to SQLAlchemy model."""
        return ClusterModel(
            id=domain.id,  # May be None for new clusters
            tenant_id=domain.tenant_id,
            label=domain.label,
            representative_identity_id=domain.representative_identity_id,
            identity_count=domain.identity_count,
            clustering_algorithm=domain.clustering_algorithm,
            user_confirmed=domain.user_confirmed,
        )
```

```python
# recognition/infrastructure/repositories/member_repository.py
from sqlalchemy import select, insert, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityMember as MemberModel
from recognition.domain.models import IdentityMember, MemberData
from recognition.domain.repositories import MemberRepository


class SqlAlchemyMemberRepository(MemberRepository):
    """SQLAlchemy async implementation of MemberRepository.

    Dev Hints:
    - Use bulk_add_members() for graph clustering results (can be 100s of members)
    - Individual add_member() is fine for single assignment decisions
    - Always include tenant_id for multi-tenant safety
    """

    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def get_by_cluster(self, cluster_id: UUID) -> list[IdentityMember]:
        stmt = (
            select(MemberModel)
            .where(MemberModel.cluster_id == cluster_id)
            .order_by(MemberModel.assigned_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def add_member(
        self,
        cluster_id: UUID,
        identity_id: UUID,
        similarity: float,
    ) -> IdentityMember:
        model = MemberModel(
            tenant_id=self._tenant_id,
            cluster_id=cluster_id,
            identity_id=identity_id,
            similarity=similarity,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def bulk_add_members(
        self,
        cluster_id: UUID,
        members: Sequence[MemberData],
    ) -> list[IdentityMember]:
        """Bulk insert for efficiency. Use executemany pattern.

        Dev Hint: For very large batches (>1000), consider chunking to avoid
        memory issues and long transaction locks.
        """
        if not members:
            return []

        values = [
            {
                "tenant_id": self._tenant_id,
                "cluster_id": cluster_id,
                "identity_id": m.identity_id,
                "similarity": m.similarity,
            }
            for m in members
        ]

        stmt = insert(MemberModel).values(values).returning(MemberModel)
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    async def remove_member(self, member_id: UUID) -> None:
        stmt = delete(MemberModel).where(MemberModel.id == member_id)
        await self._session.execute(stmt)
        await self._session.flush()

    def _to_domain(self, model: MemberModel) -> IdentityMember:
        return IdentityMember(
            id=model.id,
            tenant_id=model.tenant_id,
            cluster_id=model.cluster_id,
            identity_id=model.identity_id,
            similarity=model.similarity,
            assigned_at=model.assigned_at,
        )
```

#### 5.3 AssignmentWriter Implementation

| Task | File                                                       | Details                                               |
| ---- | ---------------------------------------------------------- | ----------------------------------------------------- |
| 33a  | `recognition/application/persistence/assignment_writer.py` | Create `AssignmentWriter` class                       |
| 33b  | Same file                                                  | Inject repositories                                   |
| 33c  | Same file                                                  | Implement `persist_assignment()` for ACCEPT decisions |
| 33d  | Same file                                                  | Implement `persist_new_cluster()` for graph results   |

```python
# recognition/application/persistence/assignment_writer.py
from uuid import UUID
from datetime import datetime

from recognition.domain.models import IdentityCluster, MemberData, AssignmentDecision, AssignmentOutcome
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.shared.short_id import generate_short_id


class AssignmentWriter:
    """Orchestrates persistence of cluster assignment decisions.

    Dev Hints:
    - This class does NOT manage transaction boundaries. The caller
      (ClusterService) should wrap batch operations in a transaction.
    - Always update identity_count after adding members.
    - UUIDs are generated here, not in the repository layer.

    Transaction Pattern:
        async with session.begin():
            writer = AssignmentWriter(cluster_repo, member_repo)
            for decision in decisions:
                await writer.persist_assignment(decision)
            # Auto-commit on context exit
    """

    def __init__(
        self,
        cluster_repository: ClusterRepository,
        member_repository: MemberRepository,
    ) -> None:
        self._clusters = cluster_repository
        self._members = member_repository

    async def persist_assignment(self, decision: AssignmentDecision) -> None:
        """Persist a single ACCEPT decision.

        Args:
            decision: Must have outcome == ACCEPT, otherwise raises ValueError.

        Raises:
            ValueError: If decision is not ACCEPT.
            ClusterNotFoundError: If target cluster doesn't exist.
        """
        if decision.outcome != AssignmentOutcome.ACCEPT:
            raise ValueError(f"Cannot persist non-ACCEPT decision: {decision.outcome}")

        cluster = await self._clusters.get_by_id(decision.cluster_id)
        if not cluster:
            raise ClusterNotFoundError(decision.cluster_id)

        # Add member
        await self._members.add_member(
            cluster_id=decision.cluster_id,
            identity_id=decision.candidate.identity.id,
            similarity=decision.candidate.discovery_similarity,
        )

        # Update cluster member count
        cluster.identity_count += 1
        await self._clusters.update(cluster)

    async def persist_new_cluster(
        self,
        tenant_id: UUID,
        identities: list[MediaIdentity],
        similarities: list[float],
        algorithm: str = "graph",
    ) -> IdentityCluster:
        """Create a new cluster with initial members.

        Used when graph clustering (HDBSCAN/CW) creates a new cluster
        that doesn't match any existing anchor.

        Args:
            tenant_id: Tenant owning the cluster.
            identities: Identities to add as initial members.
            similarities: Similarity scores for each identity (same order).
            algorithm: Clustering algorithm used (for metadata).

        Returns:
            The newly created cluster.
        """
        if len(identities) != len(similarities):
            raise ValueError("identities and similarities must have same length")

        # Create cluster
        cluster = IdentityCluster(
            id=None,  # Will be generated
            tenant_id=tenant_id,
            label=None,  # Unlabeled initially
            identity_count=len(identities),
            clustering_algorithm=algorithm,
            user_confirmed=False,
            created_at=datetime.utcnow(),
        )
        saved_cluster = await self._clusters.save(cluster)

        # Bulk add members
        member_data = [
            MemberData(identity_id=ident.id, similarity=sim)
            for ident, sim in zip(identities, similarities)
        ]
        await self._members.bulk_add_members(saved_cluster.id, member_data)

        return saved_cluster

    async def update_cluster_metadata(
        self,
        cluster_id: UUID,
        *,
        label: str | None = None,
        representative_id: UUID | None = None,
    ) -> IdentityCluster:
        """Update cluster label and/or representative.

        Args:
            cluster_id: Cluster to update.
            label: New label (None to clear).
            representative_id: ID of representative identity.

        Returns:
            Updated cluster.
        """
        cluster = await self._clusters.get_by_id(cluster_id)
        if not cluster:
            raise ClusterNotFoundError(cluster_id)

        if label is not None:
            cluster.label = label
        if representative_id is not None:
            cluster.representative_identity_id = representative_id

        return await self._clusters.update(cluster)


class ClusterNotFoundError(Exception):
    """Raised when a cluster ID is not found in the database."""
    def __init__(self, cluster_id: UUID) -> None:
        self.cluster_id = cluster_id
        super().__init__(f"Cluster not found: {cluster_id}")
```

#### 5.4 ClusterService Integration

| Task | File                                                       | Details                                                  |
| ---- | ---------------------------------------------------------- | -------------------------------------------------------- |
| 34a  | `recognition/application/orchestration/cluster_service.py` | Add `assignment_writer: AssignmentWriter` to constructor |
| 34b  | Same file                                                  | Call `persist_assignment()` after each ACCEPT            |
| 34c  | Same file                                                  | Call `persist_new_cluster()` for new graph clusters      |
| 34d  | Same file                                                  | Wrap batch operations in transaction context             |

```python
# Integration example in ClusterService.cluster_unclustered_identities()

async def cluster_unclustered_identities(
    self,
    tenant_id: str,
    session: AsyncSession,
) -> ClusteringResult:
    """Run clustering pipeline and persist results.

    Dev Hints:
    - Use session.begin() for transaction boundary
    - Log before persist, not after (in case of rollback)
    - Update identity_count atomically with member inserts
    """
    # ... discovery phase (unchanged) ...

    # Persist phase - wrap in transaction
    async with session.begin():
        for decision in decisions:
            if decision.outcome == AssignmentOutcome.ACCEPT:
                await self.assignment_writer.persist_assignment(decision)
                self.logger.log_decision(
                    identity_id=str(decision.candidate.identity.id),
                    cluster_id=str(decision.cluster_id),
                    decision="ACCEPT",
                    similarity=decision.candidate.discovery_similarity,
                )
                report.add_decision(decision)

            elif decision.outcome == AssignmentOutcome.SUGGEST:
                # Suggestions are persisted separately (SuggestionService)
                await self.suggestions.create_suggestion(
                    identity_id=decision.candidate.identity.id,
                    cluster_id=decision.cluster_id,
                    confidence=decision.confidence,
                )

        # Persist new clusters from graph discovery
        for new_cluster_data in new_clusters_from_graph:
            await self.assignment_writer.persist_new_cluster(
                tenant_id=tenant_id,
                identities=new_cluster_data.members,
                similarities=new_cluster_data.similarities,
                algorithm=new_cluster_data.algorithm,
            )
            report.clusters_created += 1

    # Transaction auto-commits on context exit
    report.finished_at = datetime.utcnow()
    self.logger.log_batch_complete(report)
    return ClusteringResult(report=report)
```

#### 5.5 Phase 5 Tests

| Test File                         | Test Case                              | Validates                        |
| --------------------------------- | -------------------------------------- | -------------------------------- |
| `test_cluster_repository.py`      | `test_save_and_retrieve_cluster`       | Round-trip persistence           |
| `test_cluster_repository.py`      | `test_get_by_tenant_pagination`        | Limit/offset work correctly      |
| `test_cluster_repository.py`      | `test_update_cluster_label`            | Label updates persist            |
| `test_cluster_repository.py`      | `test_delete_cascades_members`         | Deleting cluster removes members |
| `test_member_repository.py`       | `test_add_single_member`               | Single insert works              |
| `test_member_repository.py`       | `test_bulk_add_members`                | Batch insert efficient           |
| `test_member_repository.py`       | `test_get_by_cluster`                  | Retrieves correct members        |
| `test_assignment_writer.py`       | `test_persist_accept_decision`         | Creates member, updates count    |
| `test_assignment_writer.py`       | `test_persist_new_cluster`             | Creates cluster with members     |
| `test_assignment_writer.py`       | `test_reject_non_accept_decision`      | Raises ValueError                |
| `test_cluster_service_persist.py` | `test_batch_persistence_transactional` | Rollback on failure              |
| `test_cluster_service_persist.py` | `test_identity_count_updated`          | Count matches actual members     |

#### 5.6 Dev Hints: SQLAlchemy Async Patterns

**Session Injection**:

```python
# Use Depends() for per-request session in FastAPI
async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session

@router.post("/clustering/jobs")
async def create_clustering_job(
    session: AsyncSession = Depends(get_db_session),
):
    ...
```

**Transaction Boundaries**:

```python
# Let the outermost caller control transactions
# Repository uses flush(), not commit()

# Good: Explicit transaction in service layer
async with session.begin():
    await repo.save(cluster)
    await repo.add_members(...)
    # Auto-commit on exit

# Bad: Commit inside repository
async def save(self, cluster):
    self._session.add(cluster)
    await self._session.commit()  # Don't do this!
```

**Eager Loading**:

```python
# Avoid N+1 queries with selectinload
stmt = (
    select(ClusterModel)
    .options(selectinload(ClusterModel.members))
    .where(ClusterModel.id == cluster_id)
)
```

**Bulk Inserts**:

```python
# For 100+ records, use insert().values() instead of add()
from sqlalchemy import insert

values = [{"cluster_id": cid, "identity_id": iid} for iid in ids]
stmt = insert(MemberModel).values(values)
await session.execute(stmt)
```

---

### Phase 7 Details: Production Readiness

> **Goal**: Replace all stubs with real implementations to bring the recognition service online.
> This phase is the final step before production deployment.
>
> **Prerequisites**: Phases 5 (persistence) and 6 (API scaffolding) must be complete.
> **Reference**: [recognition_service_api_plan.md](./recognition_service_api_plan.md) — Original API specification
>
> **TDD Approach**: Red → Green → Refactor for every subsection.
>
> 1. Write failing tests FIRST that define expected behavior
> 2. Implement minimal code to make tests pass
> 3. Refactor while keeping tests green

#### 7.1 Real Pipeline Wiring

**TDD First (Task 46)**: Write integration tests before implementing pipeline wiring.

| Test File                               | Test Case                                | Validates                                    |
| --------------------------------------- | ---------------------------------------- | -------------------------------------------- |
| `test_embedding_service_integration.py` | `test_detect_faces_returns_structure`    | `detect_faces()` returns `FaceDetection`     |
| `test_embedding_service_integration.py` | `test_generate_embeddings_valid`         | Embeddings are valid 1024D vectors           |
| `test_embedding_service_integration.py` | `test_end_to_end_flow`                   | media bytes → detection → embedding          |
| `test_clustering_integration.py`        | `test_clustering_job_calls_real_service` | Job calls `cluster_unclustered_identities()` |

**Implementation (Tasks 47-48)**: Replace stub services with real implementations.

| Task | File                                                           | Details                                                                                |
| ---- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| 46a  | `recognition/infrastructure/embeddings/insightface_adapter.py` | Create `InsightFaceAdapter` wrapping face detection + embedding                        |
| 46b  | `recognition/application/orchestration/scan_service.py`        | Implement real `scan_media()` calling embedding pipeline                               |
| 47a  | `recognition/interface_adapters/http/routers/clusters.py`      | Wire `POST /clustering/jobs` to real `ClusterService.cluster_unclustered_identities()` |
| 47b  | `recognition/interface_adapters/http/dependencies.py`          | Update DI factory to inject real services with session management                      |

```python
# recognition/infrastructure/embeddings/insightface_adapter.py
from insightface.app import FaceAnalysis

class InsightFaceAdapter:
    """Adapter for InsightFace detection and embedding generation."""

    def __init__(self, model_name: str = "buffalo_l") -> None:
        self.app = FaceAnalysis(name=model_name)
        self.app.prepare(ctx_id=0)  # Use GPU if available

    async def detect_faces(self, image_bytes: bytes) -> list[FaceDetection]:
        """Detect faces in an image, returning bounding boxes and confidence."""
        import numpy as np
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(image_bytes))
        img_array = np.array(img)
        faces = self.app.get(img_array)

        return [
            FaceDetection(
                bbox=BoundingBox(x=f.bbox[0], y=f.bbox[1], w=f.bbox[2]-f.bbox[0], h=f.bbox[3]-f.bbox[1]),
                confidence=f.det_score,
                embedding=f.embedding,  # 512D face embedding
            )
            for f in faces
        ]

    async def generate_extended_embedding(self, face: FaceDetection) -> np.ndarray:
        """Generate 1024D extended embedding (512D face + 512D metadata)."""
        # Face embedding is already 512D from detection
        face_embedding = face.embedding

        # Metadata embedding (pose, age, gender, quality) - varies by model
        metadata = np.zeros(512)  # Placeholder; real implementation extracts from face

        return np.concatenate([face_embedding, metadata])
```

#### 7.2 Session & Tenant Scoping

**TDD First (Task 49)**: Write tenant isolation tests before implementing scoping.

| Test File                  | Test Case                            | Validates                         |
| -------------------------- | ------------------------------------ | --------------------------------- |
| `test_tenant_isolation.py` | `test_tenant_a_cannot_see_tenant_b`  | Cross-tenant queries return empty |
| `test_tenant_isolation.py` | `test_missing_tenant_id_returns_400` | Proper error for missing header   |
| `test_tenant_isolation.py` | `test_invalid_tenant_format_400`     | Invalid short ID format rejected  |
| `test_tenant_isolation.py` | `test_session_cleanup`               | No leaked sessions after request  |

**Implementation (Tasks 50-52)**: Implement proper request-scoped database sessions and tenant isolation.

| Task | File                                                  | Details                                 |
| ---- | ----------------------------------------------------- | --------------------------------------- |
| 48a  | `recognition/interface_adapters/http/dependencies.py` | Add `get_tenant_id()` dependency        |
| 49a  | Same file                                             | Add `get_db_session()` async dependency |
| 50a  | `recognition/infrastructure/repositories/*.py`        | Add tenant_id filter to all queries     |

```python
# recognition/interface_adapters/http/dependencies.py

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import async_session_maker

async def get_db_session() -> AsyncSession:
    """Yield a database session for the request lifetime."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

def get_tenant_id(
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    tenant_id: str | None = Query(None),
) -> str:
    """Extract tenant ID from header or query parameter."""
    tid = x_tenant_id or tenant_id
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant ID required (X-Tenant-ID header or tenant_id query)")
    # Validate short ID format
    if len(tid) < 10 or len(tid) > 20:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    return tid
```

#### 7.3 Suggestion Persistence

**TDD First (Task 53)**: Write suggestion repository tests before implementing persistence.

| Test File                       | Test Case                   | Validates                              |
| ------------------------------- | --------------------------- | -------------------------------------- |
| `test_suggestion_repository.py` | `test_create_persists`      | Create stores suggestion with status   |
| `test_suggestion_repository.py` | `test_get_by_identity`      | Query returns suggestions for identity |
| `test_suggestion_repository.py` | `test_get_by_cluster`       | Query returns suggestions for cluster  |
| `test_suggestion_repository.py` | `test_update_status_accept` | PENDING → ACCEPTED transition works    |
| `test_suggestion_repository.py` | `test_update_status_reject` | PENDING → REJECTED transition works    |

**Implementation (Tasks 54-55)**: Replace the in-memory `SuggestionService` with a repository-backed implementation.

| Task | File                                                               | Details                                    |
| ---- | ------------------------------------------------------------------ | ------------------------------------------ |
| 51a  | `recognition/domain/repositories.py`                               | Add `SuggestionRepository` protocol        |
| 51b  | `recognition/infrastructure/repositories/suggestion_repository.py` | Implement `SqlAlchemySuggestionRepository` |
| 52a  | `recognition/application/suggestions/service.py`                   | Wire service to repository                 |

```python
# recognition/domain/repositories.py (additions)

class SuggestionRepository(Protocol):
    """Abstract interface for suggestion persistence."""

    async def create(
        self,
        identity_id: UUID,
        cluster_id: UUID,
        similarity: float,
        discovery_method: str,
    ) -> AssignmentSuggestion:
        """Create a new pending suggestion."""
        ...

    async def get_by_identity(
        self,
        identity_id: UUID,
        *,
        status: str | None = None,
    ) -> list[AssignmentSuggestion]:
        """Get all suggestions for an identity, optionally filtered by status."""
        ...

    async def get_by_cluster(
        self,
        cluster_id: UUID,
        *,
        status: str = "pending",
    ) -> list[AssignmentSuggestion]:
        """Get pending suggestions for a cluster."""
        ...

    async def update_status(
        self,
        suggestion_id: UUID,
        status: Literal["accepted", "rejected"],
    ) -> AssignmentSuggestion:
        """Accept or reject a suggestion."""
        ...
```

#### 7.4 ClusterService Completeness

**TDD First (Task 56)**: Write cluster operations tests before implementing completeness features.

| Test File                       | Test Case                      | Validates                              |
| ------------------------------- | ------------------------------ | -------------------------------------- |
| `test_cluster_service_merge.py` | `test_merge_moves_all_members` | All members reassigned to target       |
| `test_cluster_service_merge.py` | `test_merge_recalculates_reps` | Representatives recalculated           |
| `test_cluster_service_merge.py` | `test_merge_updates_centroid`  | Centroid updated                       |
| `test_cluster_service_merge.py` | `test_merge_creates_audit_log` | Audit entry created                    |
| `test_cluster_service_label.py` | `test_label_sets_confirmed`    | `is_labeled=True`, `is_confirmed=True` |
| `test_outlier_handling.py`      | `test_outliers_surfaced`       | Query returns outliers                 |

**Implementation (Tasks 57-59)**: Implement full merge, label update, and outlier handling logic.

| Task | File                                                       | Details                                                |
| ---- | ---------------------------------------------------------- | ------------------------------------------------------ |
| 53a  | `recognition/application/orchestration/cluster_service.py` | Implement `merge_clusters()`                           |
| 54a  | Same file                                                  | Implement `update_label()` with confirmation semantics |
| 55a  | Same file                                                  | Implement outlier listing and manual assignment        |

```python
# recognition/application/orchestration/cluster_service.py (additions)

async def merge_clusters(
    self,
    source_cluster_id: UUID,
    target_cluster_id: UUID,
    tenant_id: UUID,
) -> MergeResult:
    """Merge source cluster into target cluster.

    Steps:
    1. Validate both clusters exist and belong to tenant
    2. Move all members from source to target
    3. Recalculate representatives for merged cluster
    4. Update centroid
    5. Create audit log entry
    6. Delete source cluster
    """
    source = await self.repository.get_by_id(source_cluster_id)
    target = await self.repository.get_by_id(target_cluster_id)

    if not source or not target:
        raise ClusterNotFoundError("Source or target cluster not found")
    if source.tenant_id != tenant_id or target.tenant_id != tenant_id:
        raise TenantIsolationError("Cluster does not belong to tenant")

    # Move members
    members = await self.member_repository.get_by_cluster(source_cluster_id)
    for member in members:
        await self.member_repository.update_cluster(member.id, target_cluster_id)

    # Recalculate representatives
    await self._recalculate_representatives(target_cluster_id)

    # Update centroid
    await self._recompute_centroid(target_cluster_id)

    # Audit log
    self.logger.log_merge(source_cluster_id, target_cluster_id, len(members))

    # Delete source
    await self.repository.delete(source_cluster_id)

    return MergeResult(
        target_cluster_id=target_cluster_id,
        members_moved=len(members),
        new_member_count=target.member_count + len(members),
    )

async def update_label(
    self,
    cluster_id: UUID,
    label: str,
    tenant_id: UUID,
) -> IdentityCluster:
    """Update cluster label with confirmation semantics."""
    cluster = await self.repository.get_by_id(cluster_id)
    if not cluster:
        raise ClusterNotFoundError(f"Cluster {cluster_id} not found")
    if cluster.tenant_id != tenant_id:
        raise TenantIsolationError("Cluster does not belong to tenant")

    cluster.label = label
    cluster.is_labeled = True
    cluster.is_confirmed = True
    cluster.labeled_at = datetime.utcnow()

    return await self.repository.update(cluster)
```

#### 7.5 Job Orchestration

**TDD First (Task 60)**: Write job orchestration tests before implementing real job service.

| Test File                  | Test Case                       | Validates                            |
| -------------------------- | ------------------------------- | ------------------------------------ |
| `test_job_service.py`      | `test_create_returns_pending`   | Job created in `pending` state       |
| `test_job_service.py`      | `test_running_transition`       | `pending` → `running` works          |
| `test_job_service.py`      | `test_completed_transition`     | `running` → `completed` works        |
| `test_job_service.py`      | `test_failed_with_message`      | `running` → `failed` stores error    |
| `test_job_service.py`      | `test_progress_updates`         | Progress tracking updates correctly  |
| `test_background_tasks.py` | `test_analyze_queues_detection` | Analyze job queues detection work    |
| `test_background_tasks.py` | `test_clustering_queues_gate`   | Clustering job queues gate + persist |

**Implementation (Tasks 61-63)**: Implement real job tracking with background execution.

| Task | File                                                        | Details                             |
| ---- | ----------------------------------------------------------- | ----------------------------------- |
| 56a  | `recognition/domain/job.py`                                 | Create `Job` domain model           |
| 56b  | `recognition/infrastructure/repositories/job_repository.py` | Create `JobRepository`              |
| 57a  | `recognition/application/orchestration/job_service.py`      | Implement background task execution |

```python
# recognition/domain/job.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class JobType(str, Enum):
    ANALYZE = "analyze"
    CLUSTERING = "clustering"

@dataclass
class Job:
    id: str
    type: JobType
    tenant_id: str
    status: JobStatus = JobStatus.PENDING
    progress_completed: int = 0
    progress_total: int = 0
    error_message: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None

    def update_progress(self, completed: int, total: int) -> None:
        self.progress_completed = completed
        self.progress_total = total

    def complete(self) -> None:
        self.status = JobStatus.COMPLETED
        self.finished_at = datetime.utcnow()

    def fail(self, error: str) -> None:
        self.status = JobStatus.FAILED
        self.error_message = error
        self.finished_at = datetime.utcnow()
```

```python
# recognition/application/orchestration/job_service.py
from fastapi import BackgroundTasks

class JobService:
    def __init__(
        self,
        job_repository: JobRepository,
        cluster_service: ClusterService,
        scan_service: ScanService,
    ) -> None:
        self.job_repository = job_repository
        self.cluster_service = cluster_service
        self.scan_service = scan_service

    async def create_clustering_job(
        self,
        tenant_id: str,
        background_tasks: BackgroundTasks,
    ) -> Job:
        """Create a clustering job and queue background execution."""
        job = Job(
            id=generate_short_id(),
            type=JobType.CLUSTERING,
            tenant_id=tenant_id,
        )
        await self.job_repository.save(job)

        # Queue background execution
        background_tasks.add_task(self._run_clustering_job, job.id, tenant_id)

        return job

    async def _run_clustering_job(self, job_id: str, tenant_id: str) -> None:
        """Execute clustering job in background."""
        job = await self.job_repository.get_by_id(job_id)
        job.status = JobStatus.RUNNING
        await self.job_repository.update(job)

        try:
            result = await self.cluster_service.cluster_unclustered_identities(
                tenant_id=tenant_id,
                progress_callback=lambda c, t: self._update_progress(job_id, c, t),
            )
            job.complete()
        except Exception as e:
            job.fail(str(e))

        await self.job_repository.update(job)

    async def _update_progress(self, job_id: str, completed: int, total: int) -> None:
        """Update job progress during execution."""
        job = await self.job_repository.get_by_id(job_id)
        job.update_progress(completed, total)
        await self.job_repository.update(job)
```

#### 7.6 Embedding Acquisition

**TDD First (Task 64)**: Write embedding pipeline tests before implementing acquisition.

| Test File                     | Test Case                      | Validates                           |
| ----------------------------- | ------------------------------ | ----------------------------------- |
| `test_face_detector.py`       | `test_detection_returns_boxes` | Returns bounding boxes + confidence |
| `test_face_detector.py`       | `test_no_face_graceful`        | No faces returns empty list         |
| `test_embedding_generator.py` | `test_output_1024d`            | Embedding is 1024D vector           |
| `test_embedding_generator.py` | `test_embedding_normalized`    | Output is unit vector               |

**Implementation (Tasks 65-67)**: Wire the face detection and embedding generation pipeline.

| Task | File                                                           | Details                                  |
| ---- | -------------------------------------------------------------- | ---------------------------------------- |
| 59a  | `recognition/infrastructure/embeddings/face_detector.py`       | Create `FaceDetector` adapter            |
| 60a  | `recognition/infrastructure/embeddings/embedding_generator.py` | Create `EmbeddingGenerator` adapter      |
| 61a  | `recognition/application/orchestration/scan_service.py`        | Wire detection → embedding → persistence |

```python
# recognition/application/orchestration/scan_service.py
class ScanService:
    def __init__(
        self,
        face_detector: FaceDetector,
        embedding_generator: EmbeddingGenerator,
        identity_repository: IdentityRepository,
        media_fetcher: MediaFetcher,  # Fetches media bytes from WordPress or storage
    ) -> None:
        self.face_detector = face_detector
        self.embedding_generator = embedding_generator
        self.identity_repository = identity_repository
        self.media_fetcher = media_fetcher

    async def scan_media(
        self,
        media_ids: list[str],
        tenant_id: str,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> ScanResult:
        """Scan media for faces, generate embeddings, persist identities."""
        identities_created = []

        for i, media_id in enumerate(media_ids):
            # Fetch media bytes
            media_bytes = await self.media_fetcher.fetch(media_id)

            # Detect faces
            faces = await self.face_detector.detect(media_bytes)

            for face in faces:
                # Generate extended embedding
                embedding = await self.embedding_generator.generate(face)

                # Persist identity (unclustered)
                identity = MediaIdentity(
                    id=generate_short_id(),
                    tenant_id=tenant_id,
                    media_id=media_id,
                    bbox=face.bbox,
                    confidence=face.confidence,
                    embedding=embedding,
                    cluster_id=None,  # Unclustered
                )
                await self.identity_repository.save(identity)
                identities_created.append(identity)

            if progress_callback:
                progress_callback(i + 1, len(media_ids))

        return ScanResult(
            media_processed=len(media_ids),
            identities_created=len(identities_created),
        )
```

#### 7.6.5 Test Infrastructure Reorganization

> **Rationale**: Tests currently mix concerns (API contract + DB behavior) and use sync `TestClient` with async database operations, causing generator lifecycle errors and false confidence from stub drift.

**Target Directory Structure**:

```text
recognition/tests/
├── conftest.py                    # Shared fixtures (db_session, tenant, fakes)
├── unit/
│   ├── __init__.py
│   ├── test_assignment_gate.py    # Logic tests with fake repos
│   ├── test_checks.py
│   ├── test_discovery_algorithms.py
│   └── test_similarity.py
├── integration/
│   ├── __init__.py
│   ├── test_cluster_repository.py # Real DB tests
│   ├── test_member_repository.py
│   ├── test_suggestion_repository.py
│   ├── test_job_repository.py
│   ├── test_cluster_service.py
│   └── test_assignment_writer.py
└── api/
    ├── __init__.py
    ├── conftest.py                # API-specific fixtures (fake services, test client)
    ├── test_analyze_routes.py     # HTTP contract tests with fakes
    ├── test_cluster_routes.py
    ├── test_suggestion_routes.py
    └── test_tenant_validation.py
```

Test Type Contracts:

| Test Type    | Database | Services | Client     | Purpose                   |
| ------------ | -------- | -------- | ---------- | ------------------------- |
| Unit         | Fakes    | N/A      | N/A        | Test logic in isolation   |
| Integration  | Real DB  | Real     | N/A        | Test service + repository |
| API Contract | None     | Fakes    | TestClient | Test HTTP status, shapes  |

Fake Implementations (in conftest.py):

```python

class FakeClusterService:
    """Fake ClusterService for API contract tests."""

    def __init__(self, clusters: list[ClusterResponse] | None = None):
        self.clusters = clusters or []
        self.calls: list[dict[str, Any]] = []

    async def list_clusters(
        self, tenant_id: str, limit: int, offset: int, include_outliers: bool = False
    ) -> list[ClusterResponse]:
        self.calls.append({"method": "list_clusters", "tenant_id": tenant_id})
        return [c for c in self.clusters if c.tenant_id == tenant_id][offset:offset + limit]

    async def cluster_unclustered_identities(self, tenant_id: str):
        self.calls.append({"method": "cluster_unclustered_identities", "tenant_id": tenant_id})
        return type("Result", (), {
            "job_id": "job-fake", "started_at": datetime.utcnow(),
            "finished_at": datetime.utcnow(), "completed": 0, "total": 0,
        })()

    async def update_cluster(self, cluster_id: str, tenant_id: str, label: str | None) -> ClusterResponse | None:
        # ... implementation
        pass

    async def merge_cluster(self, source_cluster_id: str, tenant_id: str,
                            target_cluster_id: str, target_label: str | None) -> ClusterResponse | None:
        # ... implementation
        pass


class FakeJobService:
    """Fake JobService for API contract tests."""

    def __init__(self):
        self.jobs: dict[str, Job] = {}

    async def create_job(self, job_type: JobType, tenant_id: str) -> Job:
        job = Job(id=f"job-{len(self.jobs) + 1}", type=job_type, status=JobStatus.PENDING, ...)
        self.jobs[job.id] = job
        return job

    async def start_job(self, job_id: str) -> Job:
        job = self.jobs[job_id]
        job.status = JobStatus.RUNNING
        return job

    async def get_job_status(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

```

API Test Fixture (in tests/api/conftest.py):

```python

@pytest.fixture
def api_client(fake_cluster_service, fake_job_service):
    """Test client with all dependencies faked - no real DB."""
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def no_session():
        yield None

    def cluster_builder():
        async def _build(tenant_id: str):
            return fake_cluster_service
        return _build

    async def job_service_dep():
        return fake_job_service

    app.dependency_overrides[dependencies.get_session] = no_session
    app.dependency_overrides[dependencies.get_optional_session] = no_session
    app.dependency_overrides[dependencies.get_cluster_service_builder] = cluster_builder
    app.dependency_overrides[dependencies.get_job_service_dependency] = job_service_dep

    return TestClient(app)

```

Tenant Validation Fix (in deps/tenant.py):

```python

import uuid
from fastapi import HTTPException

def get_tenant_id(
    tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    query_tenant: str | None = Query(None, alias="tenant_id"),
) -> str:
    value = tenant_id or query_tenant
    if not value:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    try:
        uuid.UUID(value)  # Validate format
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant ID format")
    return value

```

Integration Test Transaction Fix (in conftest.py):

```python

@pytest.fixture
async def db_session():
    """Provide isolated test session with savepoint for rollback."""
    async with async_session_factory() as session:
        # Start outer transaction
        async with session.begin():
            # Create savepoint for test isolation
            await session.begin_nested()
            yield session
            # Rollback to savepoint (undo test changes)
            await session.rollback()
        # Outer transaction also rolled back

```

Failing Tests → Fix Mapping:

| Test                                                    | Root Cause                    | Fix                                    |
| ------------------------------------------------------- | ----------------------------- | -------------------------------------- |
| test_analyze_creates_job                                | Sync client + async generator | Use api_client fixture with fakes      |
| test_job_ids_use_short_format                           | Sync client + async generator | Use api_client fixture                 |
| test_cluster_and_suggestion_ids_use_short_format        | Stub missing include_outliers | Use FakeClusterService                 |
| test_merge_reassigns_members_and_deletes_source         | Nested transaction conflict   | Use savepoint fixture                  |
| test_merge_recomputes_representatives_and_centroid      | Nested transaction conflict   | Use savepoint fixture                  |
| test_analyze_router_uses_scan_service_builder           | Sync client + async generator | Use api_client fixture                 |
| test_clusters_router_invokes_cluster_service_dependency | KeyError on session           | Use proper dependency override         |
| test_invalid_tenant_format_returns_400                  | No UUID validation            | Add validation to get_tenant_id        |
| test_suggestions_require_tenant_header                  | 422 vs 400 status             | Add explicit 400 check before Pydantic |
| test_query_param_tenant_fallback                        | Stub missing include_outliers | Use FakeClusterService                 |
| test_session_context_cleared_after_request              | Stub missing execute          | Remove stub, use real pattern          |

#### 7.7 Observability Persistence

**TDD First (Task 68)**: Write observability tests before implementing persistence.

| Test File                           | Test Case                      | Validates                              |
| ----------------------------------- | ------------------------------ | -------------------------------------- |
| `test_observability_persistence.py` | `test_batch_report_persisted`  | `BatchJobReport` JSON stored correctly |
| `test_observability_persistence.py` | `test_decision_logs_queryable` | Decision logs can be queried           |
| `test_diagnostics_endpoints.py`     | `test_decisions_paginated`     | Returns paginated results              |
| `test_diagnostics_endpoints.py`     | `test_filters_tenant_outcome`  | Filters work correctly                 |

**Implementation (Tasks 69-70)**: Persist observability outputs for diagnostics and auditing.

| Task | File                                                         | Details                                                      |
| ---- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 62a  | `db/models.py`                                               | Add `ClusteringJobReport` and `AssignmentDecisionLog` tables |
| 62b  | `recognition/observability/logging.py`                       | Update `ClusteringLogger` to persist decision logs           |
| 63a  | `recognition/interface_adapters/http/routers/diagnostics.py` | Query persisted decision logs                                |

```python
# db/models.py (additions)
class ClusteringJobReport(Base):
    __tablename__ = "clustering_job_reports"

    id = Column(String(20), primary_key=True)
    tenant_id = Column(String(20), nullable=False, index=True)
    job_id = Column(String(20), nullable=False, index=True)
    total_identities = Column(Integer, nullable=False)
    accepted_count = Column(Integer, nullable=False)
    suggested_count = Column(Integer, nullable=False)
    rejected_count = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    report_json = Column(Text, nullable=False)  # Full BatchJobReport as JSON
    created_at = Column(DateTime, default=datetime.utcnow)

class AssignmentDecisionLog(Base):
    __tablename__ = "assignment_decision_logs"

    id = Column(String(20), primary_key=True)
    tenant_id = Column(String(20), nullable=False, index=True)
    job_id = Column(String(20), nullable=False, index=True)
    identity_id = Column(String(20), nullable=False)
    cluster_id = Column(String(20), nullable=True)
    outcome = Column(String(10), nullable=False)  # ACCEPT, SUGGEST, REJECT
    similarity = Column(Float, nullable=True)
    discovery_method = Column(String(20), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
```

#### 7.7.5 WordPress-Backend Contract Alignment

> **Priority**: HIGH — Frontend returning 404/422 errors blocks end-to-end testing.
>
> **Context**: The WordPress plugin proxy (`RecognitionProxyController`) expects different request schemas and endpoint paths than the current backend provides.

**API Contract Gap Summary:**

| Issue Type       | Frontend Expects                       | Backend Has                    | Impact         |
| ---------------- | -------------------------------------- | ------------------------------ | -------------- |
| Schema mismatch  | `media_items: [{media_id, media_url}]` | `media_ids: [string]`          | 422 on analyze |
| Missing endpoint | `GET /recognition/jobs/{id}`           | Not implemented                | 404 on polling |
| Missing endpoint | `GET /recognition/training-stage`      | Not implemented                | 404 on stage   |
| Wrong path       | `GET /recognition/suggestions`         | `/identities/{id}/suggestions` | 404 wrong path |
| Missing endpoint | `GET /recognition/media/identities`    | Not implemented                | 404 on fetch   |

**TDD First (Task 90-94)**: Write contract tests matching WordPress expectations.

| Test File                    | Test Case                          | Validates                       |
| ---------------------------- | ---------------------------------- | ------------------------------- |
| `test_wordpress_contract.py` | `test_analyze_accepts_media_items` | `media_items` array accepted    |
| `test_wordpress_contract.py` | `test_job_polling_endpoint`        | `GET /jobs/{id}` returns status |
| `test_wordpress_contract.py` | `test_training_stage_endpoint`     | Returns cluster/member counts   |
| `test_wordpress_contract.py` | `test_top_level_suggestions`       | `GET /suggestions` works        |
| `test_wordpress_contract.py` | `test_media_identities_grouped`    | Returns identities by media_id  |

**Implementation Details:**

##### Task 90: Fix `/analyze` Request Schema

The WordPress frontend sends `media_items` with integer IDs and URLs:

```python
# recognition/interface_adapters/http/schemas/requests.py

class MediaItem(BaseModel):
    """WordPress media library item."""
    media_id: int
    media_url: str

class AnalyzeRequest(BaseModel):
    """Accept both WordPress format and short-ID format."""
    tenant_id: str
    # WordPress format (preferred for new integrations)
    media_items: list[MediaItem] | None = None
    # Legacy short-ID format (backward compatibility)
    media_ids: list[str] | None = None
    site_url: str | None = None
    user_id: int | None = None

    @model_validator(mode="after")
    def require_media_source(self) -> "AnalyzeRequest":
        if not self.media_items and not self.media_ids:
            raise ValueError("Either media_items or media_ids is required")
        return self
```

ScanService transformation:

# recognition/application/orchestration/scan_service.py

```python
async def analyze_media(self, request: AnalyzeRequest) -> ScanJob:
    # Transform WordPress media_items to internal format
    if request.media_items:
        sources = [
            MediaSource(
                media_id=str(item.media_id),  # Convert int to string
                url=item.media_url,
                tenant_id=request.tenant_id,
            )
            for item in request.media_items
        ]
    else:
        # Legacy path: media_ids are already short-ID strings
        sources = [
            MediaSource(media_id=mid, url=None, tenant_id=request.tenant_id)
            for mid in request.media_ids
        ]

    return await self._process_sources(sources)
```

Task 91: Add Job Polling Endpoint

```python
# recognition/interface_adapters/http/routers/jobs.py

router = APIRouter(tags=["jobs"])

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    tenant_id: str = Depends(get_tenant_id),
    session=Depends(get_session),
) -> JobStatusResponse:
    """Get status of any job (scan or clustering)."""
    job_service = await get_job_service(session=session, tenant_id=tenant_id)
    job = await job_service.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)
```

Task 92: Add Training Stage Endpoint

```python
# recognition/interface_adapters/http/routers/clusters.py

@router.get("/training-stage", response_model=TrainingStageResponse)
async def get_training_stage(
    tenant_id: str = Depends(get_tenant_id),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> TrainingStageResponse:
    """Return curriculum learning stage info for adaptive thresholds."""
    cluster_service = await cluster_service_builder(tenant_id)
    stats = await cluster_service.get_training_stats(tenant_id)
    return TrainingStageResponse(
        cluster_count=stats.cluster_count,
        member_count=stats.member_count,
        labeled_count=stats.labeled_count,
        stage=_compute_stage(stats),  # "early", "growing", "mature"
        suggested_threshold=_adaptive_threshold(stats),
    )

# Response schema
class TrainingStageResponse(BaseModel):
    cluster_count: int
    member_count: int
    labeled_count: int
    stage: str  # "early" | "growing" | "mature"
    suggested_threshold: float
```

Task 93: Add Top-Level Suggestions Endpoint

```python
# recognition/interface_adapters/http/routers/suggestions.py

@router.get("/suggestions", response_model=list[SuggestionResponse])
async def list_all_suggestions(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),  # "pending", "accepted", "rejected"
    suggestion_service=Depends(get_suggestion_service),
) -> list[SuggestionResponse]:
    """List all pending suggestions for review queue."""
    suggestions = await suggestion_service.list_for_tenant(
        tenant_id, limit=limit, offset=offset, status=status
    )
    return [_to_response(s) for s in suggestions]
```

Task 94: Add Media Identities Endpoint

```python
# recognition/interface_adapters/http/routers/identities.py

router = APIRouter(tags=["identities"])

@router.get("/media/identities", response_model=dict[str, list[IdentityResponse]])
async def get_media_identities(
    media_ids: list[str] = Query(..., alias="media_ids[]"),
    tenant_id: str = Depends(get_tenant_id),
    include_debug: bool = Query(False),
    session=Depends(get_session),
) -> dict[str, list[IdentityResponse]]:
    """Get detected identities for specific media items, grouped by media_id."""
    identity_repo = SqlAlchemyIdentityRepository(session, tenant_id)
    identities = await identity_repo.get_by_media_ids(media_ids)

    # Group by media_id
    grouped: dict[str, list[IdentityResponse]] = {}
    for identity in identities:
        mid = identity.media_id
        if mid not in grouped:
            grouped[mid] = []
        grouped[mid].append(_to_response(identity, include_debug=include_debug))

    return grouped

# Response includes cluster info
class IdentityResponse(BaseModel):
    id: str
    media_id: str
    bbox: dict  # {"x": int, "y": int, "width": int, "height": int}
    confidence: float
    cluster_id: str | None
    cluster_label: str | None
    thumbnail_url: str | None
    # Debug fields (optional)
    embedding: list[float] | None = None
    similarity_to_centroid: float | None = None
```

Task 95: Update Contract Documentation

#### 7.8 Security & Validation

**TDD First (Task 71)**: Write security and validation tests before implementing.

| Test File                  | Test Case                              | Validates                           |
| -------------------------- | -------------------------------------- | ----------------------------------- |
| `test_authentication.py`   | `test_unauthenticated_401`             | Unauthenticated returns 401         |
| `test_authentication.py`   | `test_invalid_token_403`               | Invalid token returns 403           |
| `test_authentication.py`   | `test_tenant_permissions`              | Tenant access enforced              |
| `test_authentication.py`   | `test_token_tenant_mismatch_403`       | Token tenant must match request     |
| `test_input_validation.py` | `test_invalid_short_id_400`            | Bad ID format returns 400           |
| `test_input_validation.py` | `test_paging_bounds`                   | Invalid offset/limit rejected       |
| `test_input_validation.py` | `test_malicious_input_sanitized`       | XSS/injection sanitized             |
| `test_input_validation.py` | `test_label_html_stripped`             | Labels are normalized/escaped       |
| `test_error_handling.py`   | `test_domain_errors_mapped`            | Domain errors → HTTP status         |
| `test_error_handling.py`   | `test_error_payload_includes_trace_id` | Error schema includes path/trace_id |

**Implementation (Tasks 72-74)**: Add authentication, input validation, and error handling.

| Task | File                                                        | Details                                                                                                 |
| ---- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| 72.1 | `recognition/config/settings.py`                            | Add `SecuritySettings` (auth_enabled, allowed_tokens, admin_token, max_page_size) sourced from env.     |
| 72.2 | `recognition/interface_adapters/http/dependencies.py`       | Add `require_auth()` dependency returning `AuthContext`; register as router dependency (except health). |
| 72.3 | `recognition/interface_adapters/http/deps/tenant.py`        | Cross-check tenant in header vs body and normalize UUID/short-id formats.                               |
| 73.1 | `recognition/interface_adapters/http/schemas/requests.py`   | Centralize short ID validators, label sanitization, and paging bounds helpers.                          |
| 74.1 | `recognition/interface_adapters/http/exception_handlers.py` | Add global exception handler and error schema; register in `api/main.py`.                               |
| 74.2 | `recognition/interface_adapters/http/router.py`             | Apply `require_auth` and exception handler to all recognition routers by default.                       |

```python
# recognition/interface_adapters/http/exception_handlers.py
from fastapi import Request
from fastapi.responses import JSONResponse

class RecognitionError(Exception):
    """Base exception for recognition service errors."""
    def __init__(self, message: str, status_code: int = 500) -> None:
        self.message = message
        self.status_code = status_code

class ClusterNotFoundError(RecognitionError):
    def __init__(self, message: str = "Cluster not found") -> None:
        super().__init__(message, status_code=404)

class TenantIsolationError(RecognitionError):
    def __init__(self, message: str = "Access denied") -> None:
        super().__init__(message, status_code=403)

class ValidationError(RecognitionError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=400)

async def recognition_exception_handler(request: Request, exc: RecognitionError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "path": str(request.url),
        },
    )

# In main.py:
# app.add_exception_handler(RecognitionError, recognition_exception_handler)
```

**Security scope and invariants**

- All recognition routes except `/recognition/health` require `Authorization: Bearer <token>`; diagnostics endpoints require an admin token/scope.
- Tokens optionally encode a tenant claim; when present it must match `X-Tenant-ID` and request payload tenant_id before RLS is set.
- `get_session` must set `app.current_tenant` for every DB-backed request and clear it on exit; never allow `ALLOW_RLS_BYPASS_FOR_TESTS` outside CI/local.
- Max page size enforced via settings (default 200) across list endpoints; offsets must be non-negative.
- Labels, filters, and free-form strings must be stripped of HTML, trimmed, and length-limited to avoid injection.

**Endpoint coverage for auth/validation**

| Endpoint                                 | Auth Scope    | Validation Notes                                                 |
| ---------------------------------------- | ------------- | ---------------------------------------------------------------- |
| `POST /recognition/analyze`              | `write`       | tenant_id required, media_ids non-empty, short IDs only          |
| `GET /recognition/jobs/{id}`             | `read`        | short-id path param; tenant_id optional but checked when present |
| `POST /recognition/clustering/jobs`      | `write`       | mode must be `sync`/`async`, tenant header/body match            |
| `PATCH /recognition/clusters/{id}`       | `write`       | sanitize label, short-id path, tenant match                      |
| `POST /recognition/clusters/{id}/merge`  | `write`       | both cluster IDs validated, target_label sanitized               |
| `GET /recognition/suggestions`           | `read`        | paging bounds, tenant header required                            |
| `GET /recognition/diagnostics/decisions` | `diagnostics` | admin token required, paging bounds enforced                     |

**Error payload contract**

```json
{
  "error": "ValidationError",
  "message": "tenant_id is required",
  "path": "/recognition/clusters",
  "trace_id": "req-<uuid>"
}
```

#### 7.9 Domain Completeness

**TDD First (Task 75)**: Write domain completeness tests before implementing.

| Test File                          | Test Case                         | Validates                           |
| ---------------------------------- | --------------------------------- | ----------------------------------- |
| `test_representative_lifecycle.py` | `test_accept_evaluates_candidacy` | ACCEPT triggers rep evaluation      |
| `test_representative_lifecycle.py` | `test_new_rep_triggers_centroid`  | New rep triggers centroid recompute |
| `test_centroid_recomputation.py`   | `test_centroid_after_addition`    | Centroid updated after member add   |
| `test_centroid_recomputation.py`   | `test_centroid_after_merge`       | Centroid updated after merge        |

**Implementation (Tasks 76-77)**: Wire representative and centroid persistence on cluster updates.

| Task | File                                                       | Details                              |
| ---- | ---------------------------------------------------------- | ------------------------------------ |
| 67a  | `recognition/application/assignment/writer.py`             | Add representative persistence logic |
| 68a  | `recognition/application/orchestration/cluster_service.py` | Add centroid recomputation hooks     |

```python
# recognition/application/assignment/writer.py (additions)
async def persist_assignment(self, decision: AssignmentDecision) -> None:
    """Persist an ACCEPT decision and potentially add new representative."""
    if decision.outcome != AssignmentOutcome.ACCEPT:
        return

    # Add member to cluster
    await self.member_repository.add_member(
        cluster_id=decision.candidate.cluster_id,
        identity_id=decision.candidate.identity_id,
        similarity=decision.candidate.discovery_similarity,
    )

    # Evaluate if identity should become a representative
    if await self._should_add_representative(decision):
        await self.representative_repository.add(
            cluster_id=decision.candidate.cluster_id,
            identity_id=decision.candidate.identity_id,
            embedding=decision.candidate.identity_vector,
        )

        # Trigger centroid recomputation
        await self._recompute_centroid(decision.candidate.cluster_id)

async def _should_add_representative(self, decision: AssignmentDecision) -> bool:
    """Determine if the assigned identity should become a representative.

    Criteria:
    - Cluster has fewer than MAX_REPRESENTATIVES
    - Identity has high similarity to existing members (quality metric)
    - Identity provides diversity (not too similar to existing reps)
    """
    cluster_id = decision.candidate.cluster_id
    current_reps = await self.representative_repository.count(cluster_id)

    if current_reps >= self.settings.max_representatives_per_cluster:
        return False

    # Check diversity from existing representatives
    existing_reps = await self.representative_repository.get_embeddings(cluster_id)
    if not existing_reps:
        return True  # First representative

    # Ensure new rep is different enough from existing ones
    for rep_embedding in existing_reps:
        similarity = compute_face_similarity(
            decision.candidate.identity_vector,
            rep_embedding,
        )
        if similarity > self.settings.representative_diversity_threshold:
            return False  # Too similar to existing rep

    return True
```

#### 7.10 End-to-End Integration Tests

> **CRITICAL**: These tests MUST FAIL initially. Run the test suite to confirm RED state before implementing.
> If tests pass before implementation, either the test is wrong or the feature already exists.

**TDD First (Task 78)**: Write FAILING integration tests with real dependencies.

**Test Infrastructure (must be set up first)**:

- SQLAlchemy `AsyncSession` with test database (PostgreSQL or SQLite)
- Tenant scoping via `X-Tenant-ID` header injection
- Job tracking with real `JobRepository`
- `FakeDetector` returning deterministic bounding boxes
- `FakeEmbeddingGenerator` returning deterministic 1024D vectors

| Test File                         | Test Case                          | Validates                              |
| --------------------------------- | ---------------------------------- | -------------------------------------- |
| `test_integration_full_flow.py`   | `test_analyze_persists_identities` | POST /analyze → MediaIdentity in DB    |
| `test_integration_full_flow.py`   | `test_cluster_creates_clusters`    | POST /clustering/jobs → clusters       |
| `test_integration_full_flow.py`   | `test_full_analyze_cluster_flow`   | analyze → persist → cluster end-to-end |
| `test_integration_full_flow.py`   | `test_tenant_isolation`            | Tenant A cannot see tenant B data      |
| `test_integration_full_flow.py`   | `test_merge_clusters_persistence`  | Merge updates all related records      |
| `test_integration_jobs.py`        | `test_job_state_transitions`       | pending → running → completed          |
| `test_integration_jobs.py`        | `test_job_failure_handling`        | Error state with message               |
| `test_integration_suggestions.py` | `test_suggest_accept_persists`     | SUGGEST decision → accept → member     |
| `test_integration_suggestions.py` | `test_suggest_reject_persists`     | SUGGEST decision → reject → no change  |

**Implementation (Task 79)**: Optional performance/load tests (not TDD-gated).

```python
# recognition/tests/integration/conftest.py
import pytest
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from httpx import AsyncClient

# Fake implementations for deterministic testing
class FakeDetector:
    """Returns deterministic bounding boxes for testing."""
    def __init__(self, faces_per_image: int = 2):
        self.faces_per_image = faces_per_image

    async def detect(self, image_bytes: bytes) -> list:
        # Return deterministic fake detections
        return [
            {"bbox": [10*i, 10*i, 100, 100], "confidence": 0.95}
            for i in range(self.faces_per_image)
        ]

class FakeEmbeddingGenerator:
    """Returns deterministic 1024D vectors for testing."""
    def __init__(self, seed: int = 42):
        self.rng = np.random.default_rng(seed)

    async def generate(self, face) -> np.ndarray:
        # Deterministic 1024D unit vector
        vec = self.rng.random(1024)
        return vec / np.linalg.norm(vec)

@pytest.fixture
async def test_db():
    """Create test database with fresh schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # Create tables...
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

@pytest.fixture
async def client(test_db):
    """Create test client with real services but fake detector/embedder."""
    from api.main import create_app

    app = create_app(
        detector=FakeDetector(faces_per_image=2),
        embedding_generator=FakeEmbeddingGenerator(seed=42),
        db_engine=test_db,
    )
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

# recognition/tests/integration/test_integration_full_flow.py
@pytest.mark.asyncio
async def test_analyze_persists_identities(client: AsyncClient, test_db):
    """
    TEST MUST FAIL INITIALLY.
    Verify POST /analyze creates MediaIdentity records in database.
    """
    tenant_id = "25497test0001"

    response = await client.post(
        "/recognition/analyze",
        headers={"X-Tenant-ID": tenant_id},
        json={"media_ids": ["media1", "media2"]},
    )
    assert response.status_code == 200
    job_id = response.json()["id"]

    # Poll until complete
    for _ in range(100):
        response = await client.get(
            f"/recognition/jobs/{job_id}",
            headers={"X-Tenant-ID": tenant_id},
        )
        if response.json()["status"] == "completed":
            break
        await asyncio.sleep(0.05)

    # Verify identities were persisted (4 total: 2 media × 2 faces each)
    async with AsyncSession(test_db) as session:
        result = await session.execute(
            select(MediaIdentity).where(MediaIdentity.tenant_id == tenant_id)
        )
        identities = result.scalars().all()
        assert len(identities) == 4  # FakeDetector returns 2 faces per image

@pytest.mark.asyncio
async def test_full_analyze_cluster_flow(client: AsyncClient, test_db):
    """
    TEST MUST FAIL INITIALLY.
    Full flow: analyze → persist identities → cluster.
    """
    tenant_id = "25497test0001"

    # 1. Analyze media (creates identities)
    response = await client.post(
        "/recognition/analyze",
        headers={"X-Tenant-ID": tenant_id},
        json={"media_ids": ["media1", "media2"]},
    )
    assert response.status_code == 200
    job_id = response.json()["id"]

    # 2. Wait for analyze to complete
    # ... polling code ...

    # 3. Trigger clustering
    response = await client.post(
        "/recognition/clustering/jobs",
        headers={"X-Tenant-ID": tenant_id},
        json={},
    )
    assert response.status_code == 200
    cluster_job_id = response.json()["id"]

    # 4. Wait for clustering to complete
    # ... polling code ...

    # 5. Verify clusters exist
    response = await client.get(
        "/recognition/clusters",
        headers={"X-Tenant-ID": tenant_id},
    )
    clusters = response.json()
    assert len(clusters) > 0  # At least one cluster created
    assert all(c["member_count"] > 0 for c in clusters)
```

#### 7.11 Phase 7 Cross-Reference to API Plan

The following items from `recognition_service_api_plan.md` are addressed in Phase 7:

| API Plan Item                                        | Phase 7 Task     | Status |
| ---------------------------------------------------- | ---------------- | ------ |
| Wire analyze/clustering to real ClusterService       | 46 (TDD), 47, 48 | [ ]    |
| Session + tenant scoping in HTTP deps                | 49 (TDD), 50-52  | [ ]    |
| Suggestion persistence                               | 53 (TDD), 54, 55 | [ ]    |
| ClusterService completeness (merge, label, outliers) | 56 (TDD), 57-59  | [ ]    |
| Job orchestration (background tasks, progress)       | 60 (TDD), 61-63  | [ ]    |
| Embedding acquisition (detection, embedding gen)     | 64 (TDD), 65-67  | [ ]    |
| Observability integration (persist logs)             | 68 (TDD), 69, 70 | [ ]    |
| Security and validation                              | 71 (TDD), 72-74  | [ ]    |
| Domain completeness (representative/centroid hooks)  | 75 (TDD), 76, 77 | [ ]    |
| End-to-end integration tests                         | 78 (TDD), 79     | [ ]    |
| Scaffold cleanup (remove orphaned stubs)             | 80-82            | [ ]    |

#### 7.11 Scaffold Cleanup (Tasks 80-82)

> **Context**: Phase 0.5 scaffolds created `NotImplementedError` stubs in various files. Many have since been implemented elsewhere, leaving orphaned stubs that need cleanup.

**Task 80: Remove Orphaned `assignment/writer.py`**

The original scaffold at `recognition/application/assignment/writer.py` has been superseded by the real implementation at `recognition/application/persistence/assignment_writer.py`. The orphaned file should be deleted after verifying no imports reference it.

```bash
# Check for imports referencing the old location
grep -rn "from recognition.application.assignment.writer" recognition/
grep -rn "from recognition.application.assignment import.*writer" recognition/

# If no imports found, delete the orphaned file
rm recognition/application/assignment/writer.py
```

**Task 81: Domain Model Persistence Stubs**

Domain models (`IdentityCluster`, `AssignmentSuggestion`) have methods like `accept()`, `reject()`, `get_representatives()` that raise `NotImplementedError`. These violate the principle that domain models should be data-only.

**Options**:

1. **Remove stubs** — Callers use service/repository directly (recommended)
2. **Wire stubs** — Inject service into domain model (violates DDD principles)

```python
# BEFORE (domain/cluster.py)
@dataclass
class IdentityCluster:
    def get_representatives(self) -> list[ClusterRepresentative]:
        raise NotImplementedError("TODO: Load cluster representatives")

# AFTER (remove method, use repository directly)
@dataclass
class IdentityCluster:
    representatives: list[ClusterRepresentative] | None = None
    # No method — caller uses repository.get_representatives(cluster_id)
```

**Task 82: Consolidate Repository Interfaces**

Two files define `ClusterRepository`:

- `recognition/application/cluster_repository.py` — ABC with 7 stubs
- `recognition/domain/repositories.py` — Protocol used by SqlAlchemy implementations

**Resolution**: Keep `domain/repositories.py` (Protocol pattern), delete `application/cluster_repository.py` ABC.

```bash
# Update imports
sed -i 's/from recognition.application.cluster_repository import/from recognition.domain.repositories import/g' recognition/**/*.py

# Delete redundant file
rm recognition/application/cluster_repository.py
```

---

## Appendix: Bug Fix Details

### Schema Evaluation

**Result**: No schema changes required for AssignmentGate architecture.

The current schema (`001_identity_schema.py`) is fully compatible:

| Table                              | Purpose                               | Compatibility  |
| ---------------------------------- | ------------------------------------- | -------------- |
| `media_identities`                 | Store detected identities             | [x] No changes |
| `identity_clusters`                | Store cluster metadata                | [x] No changes |
| `identity_members`                 | Store identity-to-cluster assignments | [x] No changes |
| `identity_cluster_representatives` | Store representative embeddings       | [x] No changes |
| `identity_suggestions`             | Store suggestions for human review    | [x] No changes |
| `mv_identity_cluster_centroids`    | Materialized view for centroids       | [x] No changes |

The AssignmentGate is purely an **application layer refactor** that changes the decision logic, not the data model.

**Optional future enhancement** (not required):

```sql
ALTER TABLE identity_members ADD COLUMN discovery_method VARCHAR(20);
-- Values: 'representative', 'centroid', 'graph'
-- For debugging/analytics only
```

### Files Modified

- `recognition/application/clustering/centroid_utils.py`
  - Added `_to_face_embedding()` helper
  - Modified `compute_similarity()` to extract face portion before comparison
  - Added import for `extract_face_embedding` and layout constants

### Tests Added

- `recognition/tests/test_centroid_utils.py`
  - `TestMetadataDilutionFix.test_similarity_uses_face_embedding_only`
  - `TestMetadataDilutionFix.test_similarity_high_for_same_face_different_metadata`
  - `TestMetadataDilutionFix.test_512d_embeddings_still_work`

### UML Diagrams Created

| Diagram                           | Path                                                                   | Description                                          |
| --------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------- |
| Sequence: Assignment Gate Flow    | `docs/architecture/backend-uml/workflows/cluster_assignment_gate.mmd`  | Shows Discovery → Gate → Writer flow                 |
| Class: AssignmentGate Module      | `docs/architecture/backend-uml/components/assignment_gate.mmd`         | Classes and relationships                            |
| Component: Pipeline V2            | `docs/architecture/backend-uml/components/recognition_pipeline_v2.mmd` | High-level component diagram                         |
| Class: Observability Module       | `docs/architecture/backend-uml/components/observability_module.mmd`    | ClusteringLogger, ClusterVisualizer, BatchJobReport  |
| Sequence: Batch Job Observability | `docs/architecture/backend-uml/workflows/batch_job_observability.mmd`  | Shows logging and chart generation during batch jobs |

### Verification Script

- `scripts/verify_fix.py` — Demonstrates OLD vs NEW similarity computation
- `scripts/diagnose_metadata_dilution.py` — Diagnostic script for database analysis

---

## Appendix: ID Strategy — UUIDv7 + Base64 Display

### Decision: Replace Short ID (YYWWD) with UUIDv7

The original Short ID format (`YYWWDXXXXXXXX`) created complexity:

- DB models use `UUID`, API uses `str` → conversion at every boundary
- Custom validation logic for short ID format
- Tests pass short IDs but repositories expect UUID

**New approach**: Use UUIDv7 internally, display as 22-char base64 in API.

### Why UUIDv7?

| Feature           | UUIDv4      | UUIDv7      | Short ID (YYWWD) |
| ----------------- | ----------- | ----------- | ---------------- |
| PostgreSQL native | ✅ 16 bytes | ✅ 16 bytes | ❌ VARCHAR(20)   |
| Time-ordered      | ❌          | ✅          | ✅               |
| Sortable          | ❌          | ✅          | ✅               |
| Index locality    | Poor        | Excellent   | Good             |
| No conversion     | ✅          | ✅          | ❌               |

UUIDv7 embeds a Unix timestamp in the first 48 bits, giving chronological ordering while staying PostgreSQL-native.

### Implementation

```python
# recognition/shared/ids.py
import base64
import uuid
from uuid_extensions import uuid7

def generate_id() -> uuid.UUID:
    """Generate time-ordered UUID (v7).

    UUIDv7 embeds millisecond timestamp for chronological ordering,
    while remaining fully compatible with PostgreSQL UUID type.
    """
    return uuid7()

def id_to_display(u: uuid.UUID) -> str:
    """Convert UUID to 22-char URL-safe string for API responses.

    Examples:
        UUID: 018c5a2e-7c1a-7000-8000-1234567890ab
        Display: AYxaLnwaAACAACNFZ4kK
    """
    return base64.urlsafe_b64encode(u.bytes).rstrip(b'=').decode('ascii')

def display_to_id(s: str) -> uuid.UUID:
    """Parse 22-char display string back to UUID.

    Raises:
        ValueError: If string is not valid base64 or wrong length
    """
    if len(s) != 22:
        raise ValueError(f"Expected 22-char ID, got {len(s)}")
    return uuid.UUID(bytes=base64.urlsafe_b64decode(s + '=='))
```

### API Schema Integration

```python
# recognition/interface_adapters/http/schemas/responses.py
from pydantic import BaseModel, field_serializer
from uuid import UUID
from recognition.shared.ids import id_to_display

class ClusterResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    label: str | None
    member_count: int

    @field_serializer('id', 'tenant_id')
    def serialize_uuid(self, v: UUID) -> str:
        return id_to_display(v)

# API response:
# {"id": "AYxaLnwaAACAACNFZ4kK", "tenant_id": "AYxaLnwaAACABBBBBBBB", ...}
```

```python
# recognition/interface_adapters/http/schemas/requests.py
from pydantic import BaseModel, field_validator
from uuid import UUID
from recognition.shared.ids import display_to_id

class ClusterRequest(BaseModel):
    cluster_id: UUID

    @field_validator('cluster_id', mode='before')
    @classmethod
    def parse_display_id(cls, v):
        if isinstance(v, str) and len(v) == 22:
            return display_to_id(v)
        return v  # Already UUID or standard format
```

### Comparison

| Format             | Example                                | Length       | DB Storage |
| ------------------ | -------------------------------------- | ------------ | ---------- |
| UUID (standard)    | `652d50db-aa9e-4532-b159-f4261de679e8` | 36 chars     | 16 bytes   |
| UUID (no dashes)   | `652d50dbaa9e4532b159f4261de679e8`     | 32 chars     | 16 bytes   |
| **Base64 display** | `ZS1Q26qeRTKxWfQmHedn6A`               | **22 chars** | 16 bytes   |
| Short ID (old)     | `25497Kp2mNx7Q`                        | 13 chars     | 13+ bytes  |

### Benefits

1. **No schema changes**: DB stays `UUID`, fully indexed
2. **Minimal API change**: Just serialize/deserialize at boundary
3. **Time-ordered**: UUIDv7 sorts chronologically (like YYWWD prefix)
4. **Shorter display**: 22 chars vs 36 (39% shorter)
5. **URL-safe**: No special characters
6. **Deterministic CW tie-breaking**: Time-ordered IDs enable stable ordering

### Migration

Per Greenfield Policy, no migration needed. Update:

1. Add `uuid_extensions` to `pyproject.toml`
2. Create `recognition/shared/ids.py` with helpers
3. Update Pydantic schemas to use serializers
4. Update `generate_short_id()` calls to `generate_id()`
5. Remove Short ID validation logic
