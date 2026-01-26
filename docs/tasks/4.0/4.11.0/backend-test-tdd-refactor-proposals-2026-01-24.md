# Backend Test Refactor Proposals (TDD Focus)

Date: 2026-01-24

## Goals
- Reduce flaky tests (timing, randomness).
- Make tests assert behavior/outcomes over internal calls.
- Increase determinism and signal for regressions.

## Proposed Refactors (Concrete Changes)

### 1) Replace time-based sleeps with explicit synchronization
**Problem:** `asyncio.sleep()` introduces timing flakiness and slows tests.

**Files/tests to change:**
- `apps/prototype-description-service/recognition/tests/unit/test_event_broadcaster.py`
  - `test_subscribe_receives_broadcast`
  - `test_tenant_isolation`
  - `test_broadcast_without_tenant_goes_to_all`

**Proposed refactor:**
- Replace `await asyncio.sleep(0.05)` with explicit wait for subscription and event delivery.
- Use a queue or event to coordinate readiness and receipt.

**Example approach:**
- Create a helper in the test file:
  - `async def wait_for_subscriber(broadcaster, tenant_id)` that polls `broadcaster._subscribers` under the lock until the subscriber queue is registered (loop with `await asyncio.sleep(0)` and `asyncio.wait_for` timeout).
  - Use an `asyncio.Queue` for received events and `await asyncio.wait_for(queue.get(), timeout=1.0)` after broadcasting.

This removes hard sleeps and makes tests deterministic.

### 2) Make random vectors deterministic or explicit
**Problem:** `np.random` usage in tests makes outcomes harder to reproduce and can hide regressions.

**Files/tests to change (examples):**
- `apps/prototype-description-service/recognition/tests/unit/test_representative_lifecycle.py`
  - Replace `np.random.rand` with fixed vectors (e.g., unit vectors, `np.arange`, or seeded RNG).
- `apps/prototype-description-service/recognition/tests/unit/test_face_detector.py`
  - Replace `np.random.randn` with fixed arrays for `embedding_512`.
- `apps/prototype-description-service/recognition/tests/unit/test_embedding_generator.py`
  - Replace random embeddings with explicit vectors.
- `apps/prototype-description-service/recognition/tests/unit/test_insightface_adapter.py`
  - Replace random embeddings/landmarks with deterministic arrays.

**Proposed refactor:**
- Introduce a small helper in each file (or shared test utility) like:
  - `def fixed_embedding(dim=512, value=0.1) -> np.ndarray:`
  - `def unit_vector(dim, idx) -> np.ndarray:`
- If randomness is needed, seed once per test with `rng = np.random.default_rng(0)` and use it locally.

### 3) Prefer behavioral assertions over call-count coupling
**Problem:** Tests that assert internal call sequences are brittle to refactors.

**Files/tests to change (examples):**
- `apps/prototype-description-service/recognition/tests/unit/test_cluster_service_merge.py`
  - Instead of only asserting `recompute_*` calls, assert final cluster identity_count and repository state updates that matter to behavior.
- `apps/prototype-description-service/recognition/tests/unit/test_representative_lifecycle.py`
  - Validate changes to representatives/centroids or repository state rather than just call counts.

**Proposed refactor:**
- Keep one or two call assertions for critical side effects, but prefer state/return assertions that reflect user-visible behavior.

### 4) Strengthen broad integration assertions
**Problem:** Very broad assertions (">= 1") allow regressions to slip by.

**Files/tests to change (examples):**
- `apps/prototype-description-service/recognition/tests/integration/test_end_to_end.py`
  - Replace `>= 1` with expected counts based on controlled test fixtures.
  - If the clustering algorithm is non-deterministic, consider stubbing detection/embedding with fixed inputs.

**Proposed refactor:**
- Use deterministic embeddings (fixed vectors per identity) to make cluster counts stable.
- Assert exact counts where possible (e.g., `clusters_created == 1` when input is known).

## InsightFace Availability and Testing Guidance

### Availability confirmation (local)
- In `apps/prototype-description-service/` (which has `.python-version`), the check below reports InsightFace is available:
  - `pyenv exec python - <<'PY'` (returns `insightface_available True`).
- In the repo root, `python3` reports `insightface_available False`.
- Conclusion: InsightFace is available in the project’s pyenv environment, not the system Python.

### How to use InsightFace during tests
- The adapter tests are already guarded with:
  - `@pytest.mark.skipif(not HAS_ADAPTER, reason=...)` in `recognition/tests/unit/test_insightface_adapter.py`.
- To run those tests locally with InsightFace:
  1) `cd apps/prototype-description-service`
  2) Ensure pyenv uses the local version from `.python-version`.
  3) Run: `pyenv exec python -m pytest recognition/tests/unit/test_insightface_adapter.py`
- If InsightFace is missing, use the provided installer:
  - `apps/prototype-description-service/scripts/install_insightface_mac.sh`
  - Or install the extras from `pyproject.toml` (see README).

### Runtime mode notes
- `RECOGNITION_RUNTIME_MODE=production` uses real InsightFace adapters.
- `RECOGNITION_RUNTIME_MODE=test` uses stub detectors/generators.
- Adapter unit tests do not require runtime mode changes; they directly import the adapter and will skip if dependencies are missing.

## Suggested Next Steps
- Pick a single batch of changes (e.g., EventBroadcaster tests + deterministic embeddings) and update tests first.
- Re-run `make typecheck` and the specific test files to verify stability improvements.
