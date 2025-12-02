# Recognition Service v4.2.4 Implementation Plan

**Date**: December 1st 2025  
**Sprint**: 4.2.4  
**Status**: **GREENFIELD REWRITE** — Building correct implementation from the start  
**Author**: Generated from architecture analysis

---

## Why v4.2.4 is a Greenfield Rewrite

**Date**: December 1, 2025  
**Decision**: Abandon old code, build correctly from the start.

The v4.2.3 recognition service had a critical bug causing **21+ different people to match a single cluster at 88-92% similarity** (the "Cam Grant domination" problem). Multiple fix attempts failed because the old codebase had **compounding architectural issues** that made targeted fixes unreliable.

### Evidence of the Problem

| Media | Filename                   | Age Estimate | Similarity | Actual Person   |
| ----- | -------------------------- | ------------ | ---------- | --------------- |
| #2802 | IMG_1916                   | ~12y         | 92%        | Kelly (child)   |
| #2796 | IMG_1888                   | ~22y         | 88%        | Adult woman     |
| #2793 | IMG_1861                   | ~17y         | 90%        | Hillary & Kelly |
| ...   | 18+ more images            | 8y-22y       | 88-92%     | Different people|

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
2. [PLANNED] **Phase 0.5**: Scaffold new modules with correct design
3. [PLANNED] **Phase 1**: Implement AssignmentGate with face-only similarity
4. [PLANNED] **Phase 2**: Implement Discovery algorithms
5. [PLANNED] **Phase 3**: Full integration + deterministic CW

---

## Root Cause Analysis

The v4.2.3 bugs stemmed from **two compounding issues**: a data bug and an architectural bug.

### Issue 1: Metadata Dilution (Data Bug)

Our 1024D extended embeddings have this structure:

| Dimensions | Content                              | L2 Norm | Energy Share |
|------------|--------------------------------------|---------|-------------|
| 0-511      | Face identity embedding              | ~2.2    | ~13%        |
| 512-1023   | Metadata (pose, age, gender, score)  | ~15.2   | ~87%        |

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

| Root Cause | v4.2.4 Design |
|------------|---------------|
| Metadata Dilution | `compute_similarity()` extracts face embedding (first 512D) ALWAYS |
| Singleton Snowballing | `MaturityCheck` requires ≥2 diverse reps before accepting |
| Single-Point Matching | `CompleteLinkCheck` requires match to ALL representatives |
| No Suggestion Tier | `AssignmentGate` returns ACCEPT / SUGGEST / REJECT |
| Non-Deterministic CW | Short ID-sorted order + quality-weighted votes + ID tie-breaking |
| Scattered Thresholds | Single `ClusteringSettings` dataclass |

### Phase 0.5: Scaffolding (MANDATORY — Before Any Implementation)

**Per instructions.md**: All interfaces and contracts MUST be scaffolded before writing implementation or tests.

> **Scaffolding First Policy**: Add function/method signatures with complete type hints, write comprehensive docstrings (Args, Returns, Raises, Examples), use `raise NotImplementedError("TODO: ...")` as initial body, commit after scaffolding each class/function.

#### Scaffolding Checklist with File Paths

##### 1. AssignmentGate Module

| File                                                               | Classes/Functions                         | Status |
| ------------------------------------------------------------------ | ----------------------------------------- | ------ |
| `recognition/application/assignment/__init__.py`                   | Module exports                            | [ ]    |
| `recognition/application/assignment/candidate.py`                  | `AssignmentCandidate`, `DiscoveryMethod`  | [ ]    |
| `recognition/application/assignment/decision.py`                   | `AssignmentDecision`, `AssignmentOutcome` | [ ]    |
| `recognition/application/assignment/gate.py`                       | `AssignmentGate.evaluate()`               | [ ]    |
| `recognition/application/assignment/checks/__init__.py`            | Check exports                             | [ ]    |
| `recognition/application/assignment/checks/base.py`                | `AssignmentCheck` (ABC), `CheckResult`    | [ ]    |
| `recognition/application/assignment/checks/complete_link.py`       | `CompleteLinkCheck`                       | [ ]    |
| `recognition/application/assignment/checks/maturity.py`            | `MaturityCheck`                           | [ ]    |
| `recognition/application/assignment/checks/member_distribution.py` | `MemberDistributionCheck`                 | [ ]    |
| `recognition/application/assignment/checks/confidence.py`          | `ConfidenceCheck`                         | [ ]    |
| `recognition/application/assignment/writer.py`                     | `AssignmentWriter`                        | [ ]    |

##### 2. Observability Module

| File                                         | Classes/Functions             | Status |
| -------------------------------------------- | ----------------------------- | ------ |
| `recognition/observability/__init__.py`      | Module exports                | [ ]    |
| `recognition/observability/decisions.py`     | `DecisionType`, `DecisionLog` | [ ]    |
| `recognition/observability/logging.py`       | `ClusteringLogger`            | [ ]    |
| `recognition/observability/reports.py`       | `BatchJobReport`              | [ ]    |
| `recognition/observability/visualization.py` | `ClusterVisualizer`           | [ ]    |

##### 3. Discovery Module

| File                                                  | Classes/Functions                    | Status |
| ----------------------------------------------------- | ------------------------------------ | ------ |
| `recognition/application/discovery/__init__.py`       | Module exports                       | [ ]    |
| `recognition/application/discovery/base.py`           | `DiscoveryAlgorithm` (ABC)           | [ ]    |
| `recognition/application/discovery/representative.py` | `RepresentativeDiscovery.discover()` | [ ]    |
| `recognition/application/discovery/centroid.py`       | `CentroidDiscovery.discover()`       | [ ]    |
| `recognition/application/discovery/graph.py`          | `GraphDiscovery.discover()`          | [ ]    |

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

| Step | Test File                      | Test Case                            | Implementation            |
| ---- | ------------------------------ | ------------------------------------ | ------------------------- |
| 1    | `test_assignment_candidate.py` | `test_candidate_requires_all_fields` | `candidate.py` dataclass  |
| 2    | `test_assignment_decision.py`  | `test_outcome_enum_values`           | `decision.py` enums       |
| 3    | `test_check_result.py`         | `test_check_result_defaults`         | `checks/base.py`          |
| 4    | `test_complete_link_check.py`  | `test_rejects_low_min_similarity`    | `checks/complete_link.py` |
| 5    | `test_complete_link_check.py`  | `test_passes_all_reps_similar`       | `checks/complete_link.py` |
| 6    | `test_assignment_gate.py`      | `test_gate_runs_all_checks`          | `gate.py`                 |
| 7    | `test_assignment_gate.py`      | `test_gate_accepts_all_checks_pass`  | `gate.py`                 |

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

| Phase                      | Duration     | Deliverable                                              | Status    |
| -------------------------- | ------------ | -------------------------------------------------------- | --------- |
| Phase 0.5: Scaffolding     | 0.5 day      | All function/class signatures with `NotImplementedError` | PLANNED   |
| Phase 1: Happy Path        | 1-2 days     | Gate + CompleteLink + RepDiscovery (Correct Results)     | PLANNED   |
| Phase 2: Full Guards       | 1 day        | Maturity + MemberDist + Confidence Checks                | PLANNED   |
| Phase 3: Full Migration    | 1 day        | Centroid + Graph Discovery + Deterministic CW            | PLANNED   |
| Phase 4: Observability     | 1 day        | Logging + Visualization + Reports                        | PLANNED   |
| **Total**                  | **4-5 days** | Unified assignment pipeline + observability              |           |

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

1. [x] Create this implementation plan
2. [x] Document root cause analysis (metadata dilution + architectural gaps)
3. [x] Confirm architectural consolidation is needed (analysis complete)
4. [x] Create UML diagrams (class + sequence + component)
5. [x] Design Short ID format (YYWWD-XXXXXXXX)
6. [x] Design Deterministic CW algorithm

### Phase 0.5: Scaffolding (MANDATORY)

7. [ ] **Scaffold AssignmentGate module** — signatures only, `NotImplementedError` bodies
8. [ ] **Scaffold Observability module** — `ClusteringLogger`, `ClusterVisualizer`, `BatchJobReport`
9. [ ] **Scaffold Discovery module** — `RepresentativeDiscovery`, `CentroidDiscovery`, `GraphDiscovery`
10. [ ] **Commit scaffolding** before any implementation

### Phase 1: Happy Path Implementation (Minimal Service)

**Goal**: Implement the minimum service to arrive at a happy path implementation that returns correct results.

11. [ ] **Implement AssignmentGate.evaluate()** (Basic logic)
12. [ ] **Implement CompleteLinkCheck** (Critical guard for "Cam Grant" issue)
13. [ ] **Refactor RepresentativeMatcher** to use gate
14. [ ] **Verify "Cam Grant" issue is resolved** for new matches (Happy Path)

### Phase 2: Full Guard Implementation

**Goal**: Add remaining validation checks to the gate.

15. [ ] **Implement MaturityCheck**
16. [ ] **Implement MemberDistributionCheck**
17. [ ] **Implement ConfidenceCheck**
18. [ ] **Enable all checks in AssignmentGate**

### Phase 3: Full Path Migration

**Goal**: Ensure all discovery paths use the unified gate.

19. [ ] **Refactor Centroid matching** to use gate
20. [ ] **Refactor HDBSCAN anchor** to use gate

### Phase 4: Observability & Cleanup

**Goal**: Add visibility and clean up legacy code.

21. [ ] **Implement ClusteringLogger**
22. [ ] **Implement ClusterVisualizer**
23. [ ] **Implement BatchJobReport**
24. [ ] **Simplify orchestration** (Discovery → Gate → Writer)
25. [ ] **Reset corrupted cluster** (SQL commands)
26. [ ] **Re-run clustering** on affected tenant

---

## Appendix: Short ID Format (YYWWD)

### Motivation

Full UUIDs (36 characters) are overkill for a project with <100K identities per tenant. Shorter IDs improve:

- **Readability**: `25497-Kp2mNx7Q` vs `652d50db-aa9e-4532-b159-f4261de679e8`
- **Debugging**: Time prefix shows when record was created
- **Determinism**: Natural chronological ordering for CW tie-breaking
- **Logs**: Shorter IDs = more readable logs

### Format Specification

```text
YYWWD-XXXXXXXX (14 characters)

YY   = Year (24 = 2024, 25 = 2025)
WW   = ISO week number (01-53)
D    = Day of week (1 = Monday, 7 = Sunday)
-    = Separator
XXXXXXXX = 8 random base62 characters (62^8 ≈ 218 trillion combinations)

Examples:
  25491-a7Bx9kL2  → Monday of week 49, 2025
  25493-mN3pQ8Yz  → Wednesday of week 49, 2025
  25497-Kp2mNx7Q  → Sunday of week 49, 2025
  26015-Xm9nPq3R  → Friday of week 01, 2026
```

### Implementation

```python
# File: recognition/shared/short_id.py

import secrets
from datetime import datetime

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def generate_short_id(prefix: str = "") -> str:
    """Generate a short, time-prefixed ID with week and day resolution.
    
    Args:
        prefix: Optional prefix (e.g., "id", "clust", "rep")
        
    Returns:
        Short ID in format YYWWD-XXXXXXXX or prefix-YYWWD-XXXXXXXX
        
    Examples:
        >>> generate_short_id()
        '25497-Kp2mNx7Q'
        >>> generate_short_id("id")
        'id-25497-a7Bx9kL2'
    """
    now = datetime.now()
    time_prefix = f"{now.strftime('%y%V')}{now.isoweekday()}"
    random_part = ''.join(secrets.choice(ALPHABET) for _ in range(8))
    
    if prefix:
        return f"{prefix}-{time_prefix}-{random_part}"
    return f"{time_prefix}-{random_part}"


def decode_short_id(short_id: str) -> dict:
    """Decode a short ID to extract timestamp info.
    
    Args:
        short_id: ID in format YYWWD-XXXXXXXX or prefix-YYWWD-XXXXXXXX
        
    Returns:
        Dict with year, week, day (name), and random parts
        
    Examples:
        >>> decode_short_id("25491-a7Bx9kL2")
        {'year': 2025, 'week': 49, 'day': 'Monday', 'random': 'a7Bx9kL2'}
    """
    DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    parts = short_id.split("-")
    if len(parts) == 3:
        time_part, random_part = parts[1], parts[2]
    else:
        time_part, random_part = parts[0], parts[1]
    
    return {
        "year": 2000 + int(time_part[:2]),
        "week": int(time_part[2:4]),
        "day": DAYS[int(time_part[4]) - 1],
        "random": random_part,
    }
```

### Database Schema Change

```sql
-- Before: UUID (36 chars)
id UUID PRIMARY KEY DEFAULT gen_random_uuid()

-- After: Short ID (14-20 chars)
id VARCHAR(20) PRIMARY KEY
```

**Migration**: Per Greenfield Policy, no migration needed — reset tables.

### Benefits for Deterministic CW

The time prefix provides natural chronological ordering for UUID-based tie-breaking:

```python
# Older IDs sort first, providing stable tie-breaking
node_order = sorted(range(n), key=lambda i: identities[i].id)
# 25491-xxx sorts before 25493-xxx (Monday before Wednesday)
```

### Collision Analysis

| Random Part | Combinations | Collision Risk |
|-------------|--------------|----------------|
| 8 chars base62 | 62^8 = 2.18 × 10^14 | ~1 in 218 trillion per day-slot |
| Birthday paradox | ~14.7M IDs | 50% collision risk |

For a project with <100K identities, collision risk is negligible.

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
