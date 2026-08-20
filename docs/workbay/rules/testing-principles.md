# Testing Principles

> Universal testing concepts that apply across all languages and test frameworks in the monorepo. Load this document first, then consult language-specific guides: [testing-typescript.md](testing-typescript.md), [testing-python.md](testing-python.md), [testing-php.md](testing-php.md).

---

## Test Pyramid

```text
          ^
         / \
        /E2E\       <- Few, slow, high confidence
       /-----\
      /Integr-\     <- Some, medium speed
     /--ation--\
    /-----------\
   /    Unit     \  <- Many, fast, isolated
  /_______________\
```

Most tests at the bottom (fast unit tests), fewer at the top (slow E2E tests).

---

## Universal Test Writing Rules

### 1. Deterministic Data Over Randomness

Use fixed fixtures or seeded random generators. Tests must produce identical results on every run.

```python
# BAD: Random vectors make failures hard to reproduce
embedding = np.random.rand(512)

# GOOD: Fixed vectors with explicit values
def fixed_embedding(dim: int = 512, value: float = 0.1) -> np.ndarray:
    return np.full(dim, value, dtype=np.float32)

# GOOD: If randomness is needed, seed locally
rng = np.random.default_rng(seed=42)
embedding = rng.random(512, dtype=np.float32)
```

### 2. Behavioral Assertions Over Call Counts

Assert observable outcomes, not implementation details.

```python
# BAD: Brittle coupling to internal calls
mock_repo.recompute_centroid.assert_called_once()

# GOOD: Assert observable outcomes
assert cluster.identity_count == 5
assert cluster.centroid_updated_at > original_timestamp

# ACCEPTABLE: One or two critical side-effect assertions
mock_event_bus.emit.assert_called_with(ClusterMergedEvent(...))
```

### 3. Import Settings, Don't Hardcode

Reference configuration values from their source of truth.

```python
# BAD: Magic numbers that can diverge from production
assert result.threshold == 0.65

# GOOD: Reference the source of truth
from recognition.application.settings import ClusteringSettings

settings = ClusteringSettings()
assert result.threshold == settings.suggestion_floor
```

### 4. No Permanently Skipped Tests

Skip annotations without a linked issue or TODO date are dead code. Remove, complete, or add an issue reference. Empty test bodies that run green are worse -- they inflate pass counts.

### 5. Test Removed Surfaces Explicitly

When a route, hook, export, or runtime surface is intentionally removed, add a test asserting its absence to prevent accidental re-introduction.

---

## Hierarchical TDD: Fake vs Real Resources

Use the fastest feedback loop that validates the behavior under test.

| Resource      | Unit Test       | Service Test    | Integration Test  | E2E Test |
| ------------- | --------------- | --------------- | ----------------- | -------- |
| Database      | Fake repository | Fake repository | Real test DB      | Real DB  |
| HTTP/Network  | Never           | Fake client     | Mock server (MSW) | Real     |
| File System   | Never           | In-memory       | Temp directory    | Real     |
| Time/Clock    | Injected clock  | Injected clock  | Injected clock    | Real     |
| Random/UUID   | Seeded/fixed    | Seeded/fixed    | Seeded/fixed      | Real     |
| External APIs | Never           | Fake client     | Mock server       | Sandbox  |

## Stub and Fake Fidelity

- Stubs must reproduce the real implementation's error-raising behavior for invalid inputs.
- Null stubs are acceptable only when the dependency's behavior is irrelevant to the assertion. Use a behavioral fake when the test depends on success, failure, or state transitions.
- Inline per-test doubles should extend the canonical shared null stub or fake, not re-implement the interface from scratch.
- New fakes must be checked against the real implementation's constructor expectations, state transitions, and negative-path behavior before becoming shared utilities.

## Runtime-Parity Verification

- Each high-risk boundary class needs at least one test exercising real runtime behavior, or an explicit note on why that is not locally verifiable.
- Runtime parity covers: bootstrap/load path, dependency injection, transaction lifecycle, header/protocol forwarding, and error-shape preservation across adapters.
- Boundary changes require golden payload tests and malformed-shape tests, not just happy-path fixtures.
- If runtime parity cannot be verified locally, record a `GAP` finding in MCP.

---

## Test Organization

### Directory Structure

```text
recognition/
  tests/
    unit/           # Layer 1: Pure functions, no I/O
    service/        # Layer 2: Fake repositories
    integration/    # Layer 3: Real database
    api/            # Layer 3: HTTP endpoints with test client
    e2e/            # Layer 4: Full stack (if applicable)
```

### Shared Test Utilities

Extract Protocol stubs/fakes copy-pasted across 3+ test files to a shared module (`tests/fakes.py`, `tests/stubs.py`, `tests/helpers.ts`, etc.).

```python
# BAD: 100-line ClusterRepoStub defined independently in 4 test files

# GOOD: Shared null implementation in tests/stubs.py
class NullClusterRepository:
    """No-op implementation of ClusterRepository for unit tests."""
    async def get(self, cluster_id): return None
    async def save(self, cluster): pass
    # full Protocol surface in one place
```

### One Canonical Fake Per Protocol

One configurable fake per Protocol. No divergent implementations across test files.

### 7. Fixture Data Over Live Config

Generic infrastructure tests (manifest loaders, config readers, serializers) must use temporary fixture data, not hardcoded references to live task configs.

```python
# BAD: Coupled to a specific live config file
def test_load_manifest():
    data = load_manifest("phase-5-retention-export-and-audit-controls")
    assert data["merge_order"] == ["backend-domain", ...]

# GOOD: Fixture manifest in tmp_path
def test_load_manifest(tmp_path):
    manifest = {"task_ref": "test-task", "merge_order": ["a", "b"], ...}
    (tmp_path / "test-task.json").write_text(json.dumps(manifest))
    data = load_manifest("test-task", manifest_dir=tmp_path)
    assert data["merge_order"] == ["a", "b"]
```

Keep at most one smoke test asserting the real config file loads without error.

---

## Performance Targets

- Synchronous endpoints: < 150ms response time
- Frontend: Lighthouse score > 90
- Core Web Vitals: LCP < 2.5s, FID < 100ms, CLS < 0.1

## Performance Evidence Requirements

- Performance claims must include `p50`, `p95`, `p99` latency distributions, not only averages.
- Queue depth, connection-pool wait time, and retry counts must be observable for shared-resource flows.
- Document backpressure and saturation behavior, not just steady-state success.
- Attach concrete numbers to MCP test results or handoff decisions, not narrative claims.
- Distinguish average-latency improvements from tail-latency or saturation improvements.

---

## Verification Tiers (which check fires when)

Three different questions, three different phases. None substitutes for another.

| Phase | Question | Instrument | Canon |
| --- | --- | --- | --- |
| **Write** (every turn) | Can this assertion ever fail? | Predict the exact failure message, run RED, confirm it failed for the intended reason. `make slice-start` pins the evidence. | `TEST-06` |
| **Slice close** | Does it pass at this HEAD? | `record_event(test_result, passed=true)` bound to the current commit SHA. | `AGT-04` |
| **Review gate** | Would a real regression turn this green test red? | Targeted single-point mutation, **only** on tests guarding an invariant, single-source count, security property, or state property. | `TEST-15` |
| **Feature intake** | Is the model/pipeline output any good? | An eval set defined at `/scope`, before the task plan. | `EVAL-01`, `EVAL-10` |

Mutation testing is a review-gate lens, not a per-turn practice: `TEST-15` is phase-tagged review, and a blanket per-turn mutation score becomes exactly the gameable target `TEST-11` warns about. Reviewers emit `mutants_to_prove` (file, line, old → new, the test that must go red); remote lanes execute them. See [branch-review-guide.md](branch-review-guide.md) § Mutation Lens.

---

## ML Evaluation Gates

Deterministic unit tests cannot gate a generated caption, a ranked candidate list, or an identification threshold. Those surfaces — the description service, recognition, and retrieval — are gated by an **eval set**, and the eval set is a construction, not a leftover sample. Rules are cited by ID against the `ml-systems` lexicon in the private heuristics canon; resolve bodies there, never copy them into this repo.

**Define at `/scope`, before the plan exists.** A feature that produces any of the following owes an eval-set section in its scope note:

| If the feature produces… | Owe | Canon |
| --- | --- | --- |
| a ranked list a human scans | a test collection: corpus + real information needs + relevance judgments, gated at the depth the operator actually reads — not top-1 or EER | `EVAL-24`, `EVAL-21` |
| pooled relevance labels over a large corpus | a multi-strategy pool protocol with disclosed pool depth; unjudged ≠ nonrelevant | `EVAL-25` |
| generated open-ended text | a scorer that is not sole exact-match: functional/oracle check, rubric, or multiple references | `EVAL-11` |
| an LLM-as-judge score | judge validated against blinded human labels, and a pinned judge model/prompt/rubric/decoding/seed/order protocol | `EVAL-12`, `EVAL-13`, `EVAL-14` |
| an accept/reject threshold | an **entity-disjoint** calibration split (subject/account/source, not record or pair) | `CAL-07`, `EVAL-07` |
| identification against a gallery that may not contain the subject | non-mated probes and a score threshold, not rank metrics | `EVAL-18` |
| a multi-stage detect → associate → compare path | at least one metric where an upstream miss counts as an end-to-end failure | `EVAL-16` |

**Always, for any eval set:**

- [ ] **Baselines named** — Δ versus random, zero-rule, a simple heuristic, and current production, on the same split. Without them the number is uninterpretable. (`EVAL-01`)
- [ ] **Test set frozen before iteration 0** — sealed random + out-of-distribution split, never reachable from the tuning loop. (`EVAL-10`, `EVAL-07`)
- [ ] **Slices, not one number** — report and floor per critical slice; watch for the aggregate flipping the within-slice ranking. (`EVAL-04`, `FAIR-*`)
- [ ] **Perturbation matches production** — score on inputs carrying production's noise, not clean capture. (`EVAL-06`)
- [ ] **Readiness is the weakest category** — data, model, infrastructure, monitoring scored separately; report the minimum, not the average. (`EVAL-23`)
- [ ] **Determinism** — same version, N runs, identical results, or the evaluation certifies nothing. (`TEST-08`)

Existing instrument: `apps/prototype-description-service/scripts/eval_harness/` (open-set identification, gallery split, face and caption metrics, perf budgets). A scope-defined eval set should be expressible as a run of that harness.

---

## Next Steps

Consult your language-specific testing guide:

- **TypeScript/React** → [testing-typescript.md](testing-typescript.md)
- **Python/FastAPI** → [testing-python.md](testing-python.md)
- **PHP/WordPress** → [testing-php.md](testing-php.md)
