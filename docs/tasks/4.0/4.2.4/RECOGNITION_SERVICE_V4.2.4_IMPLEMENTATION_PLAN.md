# Recognition Service V2 Implementation Plan

**Date**: December 1st 2025  
**Sprint**: 4.2.4  
**Status**: **REVISED** — Critical bug discovered  
**Author**: Generated from architecture analysis

---

## 🚨 CRITICAL UPDATE: Bug Persists After Service Restart + DB Reset

**Date**: December 1, 2025  
**Updated**: December 1, 2025 — **FIX DOES NOT WORK**

### The Problem

The "Cam Grant domination" problem **STILL OCCURS** even after:
1. ✅ Service restart with latest code
2. ✅ Database reset (fresh clustering)
3. ✅ `compute_similarity()` fix deployed

### 🚨 EVIDENCE: Bug Still Present (Post-Fix)

After service restart and DB reset, the UI still shows **multiple different people** matched to "Cam Grant" at 88-92%:

| Media | Filename | Age Estimate | Similarity | Status |
|-------|----------|--------------|------------|--------|
| #2802 | IMG_1916 — kelly | ~12y | 92% | ❌ Matched to Cam Grant |
| #2801 | IMG_1912 | ~9y | 91% | ❌ Matched to Cam Grant |
| #2800 | IMG_1911 | ~9y | 91% | ❌ Matched to Cam Grant |
| #2799 | IMG_1905 | ~10y | 89% | ❌ Matched to Cam Grant |
| #2798 | IMG_1903 | ~8y | 92% | ❌ Matched to Cam Grant |
| #2797 | IMG_1890 | ~9y | 92% | ❌ Matched to Cam Grant |
| #2796 | IMG_1888 | ~22y | 88% | ❌ Matched to Cam Grant |
| #2793 | IMG_1861 — hillary & kelly | ~17y | 90% | ❌ Matched to Cam Grant |

**Observation**: Ages range from ~8y to ~22y — these are clearly **different people** yet all match at 88-92%.

### Root Cause: UNKNOWN

The `compute_similarity()` fix that extracts face embedding (first 512D) is **NOT preventing false matches**. Possible causes:

1. **Fix not being called**: Another code path bypasses `compute_similarity()`
2. **Face embeddings are similar**: The face portion itself produces high similarity (unlikely for different people)
3. **Model issue**: InsightFace model produces similar embeddings for different faces
4. **Representative issue**: The cluster's representative embedding is generic/averaged

### MUST INVESTIGATE

- [ ] Add logging to `compute_similarity()` to confirm it's being called
- [ ] Log the embedding dimensions being compared (confirm 512D vs 1024D)
- [ ] Check if HDBSCAN anchor path bypasses the fix
- [ ] Examine the representative embedding for the Cam Grant cluster
- [ ] Test similarity between known-different faces directly

### The Metadata Dilution Bug (Original Hypothesis)

Our 1024D extended embeddings have this structure:

- **Dims 0-511**: Face identity embedding (L2 normalized, ~2.2 norm)
- **Dims 512-1023**: Metadata (pose, age, gender, detection score — ~15.2 norm)

`compute_similarity()` was comparing the **full 1024D vector**, meaning:

- **87% of similarity** came from metadata
- **13% of similarity** came from actual face identity

**Result**: Two completely different people with similar pose/age/detection scores showed 97%+ similarity!

### Bug Fix Applied (BUT NOT WORKING)

```python
# recognition/application/clustering/centroid_utils.py
def compute_similarity(embedding_a, embedding_b) -> float:
    # Extract face embedding only - critical for correct similarity!
    face_a = _to_face_embedding(vec_a)  # First 512D
    face_b = _to_face_embedding(vec_b)  # First 512D
    # ... normalize and dot product
```

**Expected Behavior**:

```text
Scenario: Different faces, identical metadata
OLD similarity (buggy): 0.9775  ← False match!
NEW similarity (fixed): 0.0000  ← Correct
```

**Actual Behavior**: Still seeing 88-92% similarity for different people.

---

## Revised Executive Summary

The metadata dilution bug was the **immediate cause** of the 97%+ false similarities, but the **three parallel assignment paths remain a significant architectural problem** that should still be addressed.

### Why Single-Path Consolidation is Still Needed

Even with the metadata dilution bug fixed, code analysis reveals:

| Issue | Paths Affected | Impact |
|-------|----------------|--------|
| **No complete-link check** | Centroid, HDBSCAN anchor | Assigns based on single-point similarity |
| **No immature cluster guard** | Centroid, HDBSCAN anchor | Can assign to clusters with <2 reps |
| **No suggestion tier** | Centroid, HDBSCAN anchor | Binary accept/reject, no human review |
| **HDBSCAN anchor gap** | HDBSCAN | Matches cluster centroid to ONE rep, not all |
| **Scattered thresholds** | All paths | 5+ files with different threshold logic |

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

1. ❌ **Phase 0**: Fix metadata dilution bug (**NOT DONE** — bug still present in logs)
2. ⏸️ **Phase 1**: Validate fix + reset corrupted data (BLOCKED)
3. ✅ **Phase 2**: Implement unified AssignmentGate (CONFIRMED NEEDED)
4. 📋 **Phase 3**: Migrate paths to use gate

---

## Root Cause Analysis (Revised)

### ✅ Actual Root Cause: Metadata Dilution Bug

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  THE REAL PROBLEM: SIMILARITY COMPUTED ON WRONG DATA                        │
│                                                                             │
│  Extended Embedding (1024D):                                                │
│    ├── Dims 0-511:   Face identity (norm ≈ 2.2, ~13% of energy)            │
│    └── Dims 512-1023: Metadata (norm ≈ 15.2, ~87% of energy)               │
│                                                                             │
│  compute_similarity() was:                                                  │
│    1. Normalizing FULL 1024D vector                                         │
│    2. Computing dot product on normalized 1024D                             │
│    3. Result: 87% metadata similarity + 13% face similarity                 │
│                                                                             │
│  CONSEQUENCE:                                                               │
│    - Different people with same pose/age/detection → 97% similarity!       │
│    - Same person with different pose → lower similarity than expected      │
│    - ALL paths affected equally (bug was in shared utility function)       │
│                                                                             │
│  FIX APPLIED: Extract face embedding (first 512D) before similarity        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Architectural Issues (Still Valid, **HIGH** Priority)

The three parallel paths are a **significant architectural problem** that should be addressed:

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

| Guard | RepMatcher | Centroid | HDBSCAN Anchor |
|-------|:----------:|:--------:|:--------------:|
| Base Threshold | ✅ 0.75 | ✅ 0.85 | ✅ adaptive |
| **Complete-Link (all reps)** | ✅ | ❌ | ❌ |
| **Immature Cluster Block** | ✅ | ❌ | ❌ |
| Member Validation (avg) | ✅ 0.85 | ✅ 0.85 | ❌ |
| Member Validation (min floor) | ✅ 0.82 | ✅ 0.82 | ❌ |
| Early Stage High-Conf Gate | ✅ 0.90 | ❌ | ❌ |
| **Suggestion Tier** | ✅ | ❌ | ❌ |
| Creates Suggestions | ✅ | ❌ | ❌ |

**Conclusion**: 6 of 8 guards are missing from at least one path.

### Symptoms Explained by Bug

| Symptom | Original Explanation | Actual Cause |
|---------|---------------------|---------------|
| 20+ people match one cluster at 88-92% | Guards bypassed | All had similar metadata |
| Guards "ineffective" | Wrong path | Guards checked metadata similarity |
| Snowball effect | Architecture | Correct — still a concern |
| Non-deterministic | Processing order | Likely still true |

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
            MaturityCheck(settings),      # Cluster has ≥2 diverse reps
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

## Revised Implementation Strategy

### Phase 0: Bug Fix (❌ NOT COMPLETE — False positive claim)

**Status**: The "Cam Grant domination" bug is **STILL PRESENT** as of December 1, 2025.

**Evidence from logs** (job `1a4b2cbc-4deb-40fe-9330-571ac44ccd50`, 15:11:34):
- Cluster `21beff5c-aa9e-4532-b159-f4261de679e8` is a SINGLETON (1 representative)
- **21+ different identities** matched to this singleton at 88-92% similarity
- This is the EXACT same "Cam Grant" pattern — one person's cluster absorbs everyone

**False positive identities matching singleton cluster `21beff5c`**:
| Identity | Similarity | Status |
|----------|------------|--------|
| 8d9bfc32-bc4a-468a... | 0.8964 | FALSE POSITIVE |
| 49262511-0e82-4b5a... | 0.9240 | FALSE POSITIVE |
| 00f2a2ef-1fe8-4827... | 0.9102 | FALSE POSITIVE |
| 7e198c44-c0a9-4d03... | 0.9195 | FALSE POSITIVE |
| 8e93c56f-dbbb-4e1f... | 0.8927 | FALSE POSITIVE |
| 302049c5-11df-4679... | 0.9128 | FALSE POSITIVE |
| 167fc908-3c41-43f2... | 0.9119 | FALSE POSITIVE |
| bb395bc9-61ee-4577... | 0.9220 | FALSE POSITIVE |
| df8e385a-cfd9-4d59... | 0.9003 | FALSE POSITIVE |
| f56c3337-dcfb-4120... | 0.8829 | FALSE POSITIVE |
| 6ff95848-c13e-4661... | 0.9187 | FALSE POSITIVE |
| 93bcd0a7-f6fb-4009... | 0.8895 | FALSE POSITIVE |
| e9732d76-a754-42ad... | 0.8972 | FALSE POSITIVE |
| 0840ee44-b63a-48d7... | 0.8865 | FALSE POSITIVE |
| a716456f-c930-489d... | 0.8991 | FALSE POSITIVE |
| 13a4ab6f-0342-491b... | 0.9122 | FALSE POSITIVE |
| 245ecde3-f86c-4994... | 0.9123 | FALSE POSITIVE |
| e566b85d-f18c-484e... | 0.9157 | FALSE POSITIVE |
| 1d1a655c-55f2-441a... | 0.9190 | FALSE POSITIVE |
| 43859677-69c7-4e4e... | 0.8831 | FALSE POSITIVE |
| + more via centroid matching | 0.85-0.91 | FALSE POSITIVE |

**Previous work claimed to fix this**:
1. ❌ Claimed: Identified metadata dilution bug in `compute_similarity()`
2. ❌ Claimed: Fixed `centroid_utils.py` to extract face embedding (first 512D) before similarity
3. ❌ Claimed: Verified fix with OLD similarity 97.75% → NEW similarity 0.00%

**The fix was either not deployed, not complete, or the root cause diagnosis was wrong.**

### Phase 0.5: Scaffolding (📋 MANDATORY — Before Any Implementation)

**Per instructions.md**: All interfaces and contracts MUST be scaffolded before writing implementation or tests.

#### Scaffolding Checklist

1. **AssignmentGate Module** — Create signatures with `raise NotImplementedError("TODO: ...")`
   - `AssignmentCandidate` dataclass (complete)
   - `AssignmentDecision` dataclass (complete)
   - `AssignmentOutcome` enum (complete)
   - `AssignmentGate.evaluate()` signature
   - `BaseCheck` abstract class
   - `CompleteLinkCheck`, `MaturityCheck`, `MemberDistributionCheck`, `ConfidenceCheck`

2. **Observability Module** — Extract logging and add visualization ✅ SCAFFOLDED
   - ✅ `DecisionType` enum — `recognition/observability/decisions.py`
   - ✅ `DecisionLog` dataclass — `recognition/observability/decisions.py`
   - ✅ `ClusteringLogger` class — `recognition/observability/logging.py`
   - ✅ `BatchJobReport` dataclass — `recognition/observability/reports.py`
   - ✅ `ClusterVisualizer` class — `recognition/observability/visualization.py`

3. **Discovery Module** — Interfaces for candidate generation
   - `RepresentativeDiscovery.discover()` signature
   - `CentroidDiscovery.discover()` signature
   - `GraphDiscovery.discover()` signature

4. **Commit after scaffolding each class/function** (incremental commits)

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

### Phase 1: Data Reset & Validation (⏸️ BLOCKED on Phase 0)

**Goal**: Reset corrupted data and verify the bug fix works in production.

1. **Reset corrupted cluster**:

   ```sql
   -- Dissolve the cluster with 16+ different people
   UPDATE media_identities 
   SET identity_cluster_id = NULL 
   WHERE identity_cluster_id = '652d50db-...';
   
   DELETE FROM identity_clusters WHERE id = '652d50db-...';
   ```

2. **Re-run clustering** on affected tenant
3. **Verify**: No single cluster matches 20+ identities

### Phase 1.5: Observability Module (📋 PLANNED)

**Goal**: Extract logging functions from main app logic into dedicated observability module, including cluster visualization.

#### Module Structure

```text
recognition/
├── observability/                    # NEW: Dedicated observability module
│   ├── __init__.py
│   ├── logging.py                    # ClusteringLogger - structured decision logs
│   ├── visualization.py              # ClusterVisualizer - cluster charts
│   ├── reports.py                    # BatchJobReport - job summary reports
│   └── decisions.py                  # DecisionLog dataclass
```

#### ClusteringLogger Design

```python
class ClusteringLogger:
    """Centralized logging for all cluster assignment decisions.
    
    Extracts 100+ scattered logger.info/debug/warning calls into
    a single, structured logging interface.
    """
    
    def __init__(self, algorithm: str, job_id: UUID | None = None):
        """Initialize logger with algorithm context.
        
        Args:
            algorithm: Name of clustering algorithm (HDBSCAN, ChineseWhispers, etc.)
            job_id: Optional job ID for correlation
        """
        self.algorithm = algorithm
        self.job_id = job_id
        
    def log_decision(
        self,
        identity_id: UUID,
        cluster_id: UUID | None,
        decision: DecisionType,  # ACCEPT | SUGGEST | REJECT
        similarity: float,
        reason: str | None = None,
    ) -> None:
        """Log an assignment decision with full context."""
        raise NotImplementedError("TODO: Structured decision logging")
    
    def log_batch_start(self, identity_count: int, algorithm: str) -> None:
        """Log start of a batch clustering job."""
        raise NotImplementedError("TODO: Implement")
    
    def log_batch_complete(self, report: BatchJobReport) -> None:
        """Log completion of a batch job with summary statistics."""
        raise NotImplementedError("TODO: Implement")
```

#### ClusterVisualizer Design

```python
class ClusterVisualizer:
    """Generate cluster distribution charts after batch jobs.
    
    Charts are saved to logs/ directory and include:
    - Cluster size distribution
    - Algorithm that generated the clustering
    - Decision breakdown (accept/suggest/reject counts)
    """
    
    def __init__(self, output_dir: Path = Path("logs")):
        self.output_dir = output_dir
        
    def generate_batch_report_chart(
        self,
        report: BatchJobReport,
        algorithm: str,
        timestamp: datetime | None = None,
    ) -> Path:
        """Generate and save a cluster distribution chart.
        
        Args:
            report: Batch job report with clustering statistics
            algorithm: Name of algorithm (displayed in chart title)
            timestamp: Optional timestamp for filename
            
        Returns:
            Path to the generated chart image.
            
        Chart includes:
        - Histogram of cluster sizes
        - Bar chart of accept/suggest/reject decisions
        - Algorithm name in title
        - Timestamp for correlation with logs
        """
        raise NotImplementedError("TODO: matplotlib chart generation")
    
    def generate_similarity_heatmap(
        self,
        cluster_id: UUID,
        member_similarities: np.ndarray,
        algorithm: str,
    ) -> Path:
        """Generate similarity heatmap for a single cluster."""
        raise NotImplementedError("TODO: heatmap for debugging")
```

#### BatchJobReport Design

```python
@dataclass
class BatchJobReport:
    """Summary of a batch clustering job for logging and visualization."""
    
    job_id: UUID
    algorithm: str                    # HDBSCAN | ChineseWhispers | RepresentativeMatcher
    started_at: datetime
    completed_at: datetime
    
    # Input
    total_identities: int
    
    # Outcomes (labeled as accept/suggest/reject per user request)
    accept_count: int                 # Assigned to cluster
    suggest_count: int                # Sent to human review
    reject_count: int                 # Stayed unclustered
    
    # Cluster statistics
    clusters_created: int
    clusters_expanded: int
    avg_cluster_size: float
    max_cluster_size: int
    singleton_count: int
    
    # Quality metrics
    avg_similarity: float             # Average intra-cluster similarity
    min_similarity: float             # Minimum intra-cluster similarity
    
    @property
    def duration_ms(self) -> float:
        """Calculate job duration in milliseconds."""
        return (self.completed_at - self.started_at).total_seconds() * 1000
    
    @property
    def success_rate(self) -> float:
        """Percentage of identities that were accepted or suggested."""
        total = self.accept_count + self.suggest_count + self.reject_count
        return (self.accept_count + self.suggest_count) / total if total > 0 else 0.0
```

#### Migration Strategy

The observability module will extract logging from these files (100+ logger calls):

| File | Logger Calls | Priority |
|------|-------------|----------|
| `representative_matcher.py` | 17+ | HIGH |
| `cluster_validation.py` | 14+ | HIGH |
| `identity_clustering_service.py` | 11+ | HIGH |
| `representative_only_clustering.py` | 11+ | HIGH |
| `cluster_management.py` | 9 | MEDIUM |
| `suggestion_service.py` | 8 | MEDIUM |
| `chinese_whispers.py` | 7 | MEDIUM |
| `clustering_job_service.py` | 5 | MEDIUM |
| `cluster_assignment.py` | 3 | LOW |
| Other files | ~20 | LOW |

#### Chart Generation Requirements

**After EVERY batch job**, the `ClusterVisualizer` must:

1. Generate a cluster distribution chart
2. Include the algorithm name in the chart title (e.g., "HDBSCAN Batch - 2025-12-01")
3. Label decision counts as "Accepted", "Suggested", "Rejected"
4. Save to `logs/charts/batch_{job_id}_{timestamp}.png`

Example chart title format:
```
[HDBSCAN] Batch Job Summary - Dec 1, 2025 14:32:15
Identities: 150 | Accepted: 120 | Suggested: 18 | Rejected: 12
```

### Phase 2: Implement AssignmentGate (✅ CONFIRMED NEEDED)

**Goal**: Create single validation point for all assignment paths.

#### Step 2.1: Create AssignmentGate Module

```
recognition/application/assignment/
├── __init__.py
├── gate.py              # AssignmentGate class
├── candidate.py         # AssignmentCandidate dataclass
├── decision.py          # AssignmentDecision, AssignmentOutcome
└── checks/
    ├── __init__.py
    ├── base.py          # BaseCheck abstract class
    ├── complete_link.py # CompleteLinkCheck
    ├── maturity.py      # MaturityCheck  
    ├── member_dist.py   # MemberDistributionCheck
    └── confidence.py    # ConfidenceCheck
```

#### Step 2.2: AssignmentGate Interface

```python
@dataclass
class AssignmentCandidate:
    identity: MediaIdentity
    identity_vector: np.ndarray
    cluster_id: UUID
    discovery_method: DiscoveryMethod  # REPRESENTATIVE | CENTROID | GRAPH
    discovery_similarity: float

class AssignmentOutcome(Enum):
    ACCEPT = "accept"      # Assign to cluster
    SUGGEST = "suggest"    # Create suggestion for human review
    REJECT = "reject"      # Do not assign

@dataclass  
class AssignmentDecision:
    outcome: AssignmentOutcome
    candidate: AssignmentCandidate
    checks_passed: list[str]
    checks_failed: list[str]
    rejection_reason: str | None = None
    suggestion_confidence: float | None = None

class AssignmentGate:
    """Single validation point for ALL cluster assignments."""
    
    async def evaluate(self, candidate: AssignmentCandidate) -> AssignmentDecision:
        """Run all enabled checks and return decision."""
```

#### Step 2.3: Migrate Paths to Use Gate

| Path | Current Code | Migration |
|------|--------------|-----------|
| RepresentativeMatcher | Inline guards | Extract to gate, call `gate.evaluate()` |
| Centroid matching | `validate_centroid_match()` | Replace with `gate.evaluate()` |
| HDBSCAN anchor | Direct assignment | Wrap each member in `gate.evaluate()` |

### Phase 3: Simplify Orchestration (📋 AFTER PHASE 2)

**Goal**: Reduce the three paths to: Discovery → Gate → Writer

1. **Discovery phase**: All algorithms return `list[AssignmentCandidate]`
2. **Evaluation phase**: All candidates go through `gate.evaluate()`
3. **Write phase**: Accepted → assign, Suggested → create suggestion, Rejected → skip

```python
# Simplified orchestration
async def cluster_identities(identities: list[MediaIdentity]) -> ClusteringResult:
    # Discovery (no assignments)
    candidates = []
    candidates.extend(await rep_discovery.discover(identities))
    candidates.extend(await centroid_discovery.discover(remaining))
    candidates.extend(await graph_discovery.discover(still_remaining))
    
    # Evaluation (single gate)
    for candidate in candidates:
        decision = await gate.evaluate(candidate)
        match decision.outcome:
            case ACCEPT: await writer.assign(candidate)
            case SUGGEST: await suggestions.create(candidate)
            case REJECT: pass  # stays unclustered
```

### ~~Phase 2: Evaluate Architecture Needs~~ (REMOVED)

The evaluation is complete. Consolidation is **confirmed needed** based on:
- 6 of 8 guards missing from at least one path
- HDBSCAN anchor matching has NO validation
- Centroid path has no suggestion tier

Based on Phase 2 evaluation:

#### Option A: Minimal Changes (NOT RECOMMENDED)

- Tune similarity thresholds
- Add complete-link guard to centroid path
- Monitor and adjust

#### Option B: Unified Gate (RECOMMENDED)

- Implement `AssignmentGate` as single validation point
- Refactor paths to use gate
- Full architectural cleanup

### ~~Phase 1-4: Full Rewrite~~ (SUPERSEDED)

The original four-phase rewrite plan is superseded by the streamlined Phase 1-3 above.

---

## Algorithm Evaluation Summary

See [ALGORITHM_EVALUATION.md](./ALGORITHM_EVALUATION.md) for detailed analysis.

### Clustering Algorithms

| Algorithm | Complexity | Deterministic | Outlier Handling | Recommendation |
|-----------|------------|---------------|------------------|----------------|
| Chinese Whispers | O(E) | No | Poor | Keep for >500 identities |
| HDBSCAN | O(n²) | Yes | Excellent | Primary for ≤500 |
| AHC (Ward) | O(n³) | Yes | None | Not recommended |
| K-means | O(nkt) | Mostly | None | Not recommended |
| Representative | O(n×r) | Yes | N/A | Keep for incremental |

### Embedding Models

| Model | Accuracy | Speed | Notes |
|-------|----------|-------|-------|
| InsightFace (buffalo_l) | High | Fast | Current, works well |
| ArcFace (sub-center) | Higher | Similar | Better noise handling |

**Recommendation**: Keep InsightFace for now. The clustering architecture is the primary issue, not embedding quality. Consider ArcFace for v3 if needed.

---

## Frontend Compatibility

The new service MUST maintain the same API contract:

- `POST /recognition/analyze` → Scan media for identities
- `GET /recognition/jobs/{id}` → Job status polling
- `POST /recognition/clustering/jobs` → Trigger clustering
- `GET /recognition/clusters` → List clusters with labels
- `GET /recognition/identities/{id}/suggestions` → Get suggestions
- `POST /recognition/suggestions/{id}/accept` → Accept suggestion
- `POST /recognition/suggestions/{id}/reject` → Reject suggestion

No frontend changes required. All changes are internal refactoring.

---

## Success Criteria (Revised)

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

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| New bugs in rewrite | High | Medium | Extensive test suite, parallel operation |
| Performance regression | Medium | Low | Benchmark critical paths |
| API incompatibility | Low | High | Contract tests against frontend |
| Delayed delivery | Medium | Medium | Phased approach, MVP first |

---

## Timeline Estimate (Revised)

| Phase | Duration | Deliverable | Status |
|-------|----------|-------------|--------|
| Phase 0: Bug fix | 0.5 day | Fixed `compute_similarity()` | ❌ **NOT DONE** — bug still present |
| Phase 0.5: Scaffolding | 0.5 day | All function/class signatures with `NotImplementedError` | 📋 **MANDATORY** |
| Phase 1: Data reset & validation | 0.5 day | Clean data, verified fix | ⏸️ BLOCKED on Phase 0 |
| Phase 1.5: Observability module | 1 day | Logging extraction + cluster visualization | 📋 PLANNED |
| Phase 2: AssignmentGate | 2-3 days | Single validation point | 📋 PLANNED |
| Phase 3: Simplify orchestration | 1-2 days | Discovery → Gate → Writer | 📋 PLANNED |
| **Total** | **5-7 days** | Unified assignment pipeline + observability | |

---

## Appendix: Files to Archive

The following files will be archived to `recognition_4_2_3/`:

- `recognition/application/clustering/batch_clustering.py`
- `recognition/application/clustering/cluster_validation.py`
- `recognition/application/representatives/representative_matcher.py`
- `recognition/application/clustering/hdbscan_clustering.py`
- `recognition/application/clustering/chinese_whispers.py`
- `recognition/application/clustering/centroid_utils.py`
- `recognition/application/clustering/cluster_management.py`
- `recognition/application/clustering/identity_clustering_service.py`
- All tests under `recognition/tests/`

---

## Next Steps

1. ✅ Create this implementation plan
2. ❌ Identify root cause (metadata dilution bug) — **HYPOTHESIS UNVERIFIED**
3. ❌ Fix `compute_similarity()` in `centroid_utils.py` — **NOT WORKING IN PRODUCTION**
4. ❌ Add tests verifying the fix — **Tests pass but bug persists**
5. ✅ Confirm architectural consolidation is needed (analysis complete)
6. ✅ Create UML diagrams (class + sequence + component)

### 🚨 IMMEDIATE: Fix Phase 0 Bug (MUST DO FIRST)

- 🔲 **Investigate WHY the fix isn't working** — check if fix was deployed, check all code paths
- 🔲 **Verify compute_similarity() is being called** on the actual matching path
- 🔲 **Check if centroid matching bypasses the fix** — multiple code paths exist
- 🔲 **Add logging to confirm which similarity function is used**
- 🔲 **Re-verify with production logs showing 0% false positives**

### Phase 0.5: Scaffolding (MANDATORY)

7. 🔲 **Scaffold AssignmentGate module** — signatures only, `NotImplementedError` bodies
8. 🔲 **Scaffold Observability module** — `ClusteringLogger`, `ClusterVisualizer`, `BatchJobReport`
9. 🔲 **Scaffold Discovery module** — `RepresentativeDiscovery`, `CentroidDiscovery`, `GraphDiscovery`
10. 🔲 **Commit scaffolding** before any implementation

### Phase 1: Data Reset

11. 🔲 **Reset corrupted cluster** (SQL commands in Phase 1)
12. 🔲 **Re-run clustering** on affected tenant

### Phase 1.5: Observability

13. 🔲 **Implement ClusteringLogger** — extract 100+ scattered logger calls
14. 🔲 **Implement ClusterVisualizer** — generate charts after each batch job
15. 🔲 **Implement BatchJobReport** — collect accept/suggest/reject counts
16. 🔲 **Add chart generation hook** to batch job completion

### Phase 2: AssignmentGate

17. 🔲 **Implement AssignmentGate.evaluate()** 
18. 🔲 **Implement checks** (complete-link, maturity, member distribution)
19. 🔲 **Migrate RepresentativeMatcher** to use gate
20. 🔲 **Migrate Centroid matching** to use gate
21. 🔲 **Migrate HDBSCAN anchor** to use gate

### Phase 3: Simplify

22. 🔲 **Simplify orchestration** (Discovery → Gate → Writer)

---

## Appendix: Bug Fix Details

### Schema Evaluation

**Result**: No schema changes required for AssignmentGate architecture.

The current schema (`001_identity_schema.py`) is fully compatible:

| Table | Purpose | Compatibility |
|-------|---------|---------------|
| `media_identities` | Store detected identities | ✅ No changes |
| `identity_clusters` | Store cluster metadata | ✅ No changes |
| `identity_members` | Store identity-to-cluster assignments | ✅ No changes |
| `identity_cluster_representatives` | Store representative embeddings | ✅ No changes |
| `identity_suggestions` | Store suggestions for human review | ✅ No changes |
| `mv_identity_cluster_centroids` | Materialized view for centroids | ✅ No changes |

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

| Diagram | Path | Description |
|---------|------|-------------|
| Sequence: Assignment Gate Flow | `docs/architecture/backend-uml/workflows/cluster_assignment_gate.mmd` | Shows Discovery → Gate → Writer flow |
| Class: AssignmentGate Module | `docs/architecture/backend-uml/components/assignment_gate.mmd` | Classes and relationships |
| Component: Pipeline V2 | `docs/architecture/backend-uml/components/recognition_pipeline_v2.mmd` | High-level component diagram |
| Class: Observability Module | `docs/architecture/backend-uml/components/observability_module.mmd` | ClusteringLogger, ClusterVisualizer, BatchJobReport |
| Sequence: Batch Job Observability | `docs/architecture/backend-uml/workflows/batch_job_observability.mmd` | Shows logging and chart generation during batch jobs |

### Verification Script

- `scripts/verify_fix.py` — Demonstrates OLD vs NEW similarity computation
- `scripts/diagnose_metadata_dilution.py` — Diagnostic script for database analysis
