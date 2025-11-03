Integration tests for the recognition service

These integration tests are intentionally skipped by default to avoid CI flakiness. To run them locally you must:

- Have a running recognition service (e.g. `uvicorn app:app --reload` or via docker-compose)
- Ensure the service database is in a testable state (see `docs/` for dev bootstrap steps)
- Export the following environment variables before running:
  - RUN_INTEGRATION=1
  - RECOGNITION_BASE_URL (defaults to http://localhost:8000)

Run a single integration test module:

```bash
RUN_INTEGRATION=1 RECOGNITION_BASE_URL=http://localhost:8000 pytest tests/integration/test_progressive_learning.py -q
```

Notes:
- Tests are guarded with `pytest.mark.skipif` and will be skipped unless `RUN_INTEGRATION` is truthy.
- These tests are intended as smoke/integration checks, not exhaustive unit tests.
