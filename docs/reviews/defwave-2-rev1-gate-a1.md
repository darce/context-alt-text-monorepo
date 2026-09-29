VERDICT: REVISE
POR: {"file_count":267,"line_count":22855,"md5":"95253c630a3e6e0037ab936ee5cd2592","sample_lines":{"41":"-from recognition.interface_adapters.http.deps.portal_composition import install_portal_composition","173":"         mc_check, cache_dir, model_name = await _model_probe()"}}
## Findings

- M-1 (MEDIUM): apps/prototype-description-service/db/migrations/versions/001_identity_schema.py:355 `_repair_describe_demand_lease_retention` leaves leases whose `retain_until` is earlier than the parent operation's deadline unchanged. Failure: a legacy lease with `retain_until < describe_operations.retain_until` and `expires_at <= retain_until` bypasses the repair predicate, so adding the composite foreign key fails on that existing row and blocks migration. Canon: TIMING-M-02.

## Coverage

- `Makefile` patch lines 4-35: Python default and route-manifest check/export targets.
- `apps/prototype-description-service/api/main.py` patch lines 36-197: adapter readiness, middleware order, conditional admission composition, and bounded health probes.
- `apps/prototype-description-service/conftest.py` patch lines 198-234: skimmed pytest collection receipt fixture changes.
- `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` patch lines 235-408: constraint healing and parent-retention repair; migration test skimmed at patch lines 7200-7300.
- `apps/prototype-description-service/db/models/constraints.py` patch lines 409-422: merge-suggestion constraint.
- `apps/prototype-description-service/pyproject.toml` patch lines 423-438: pytest testpaths.
- `apps/prototype-description-service/recognition/application/assignment/quality.py` patch lines 439-622: finite input handling and independent representative area floor; quality tests skimmed at patch lines 4870-5010.
- `apps/prototype-description-service/recognition/application/orchestration/cluster_merge.py` patch lines 623-906: embedding-space checks, ordered cluster locks, receipt idempotency/persistence, and survivor refresh; merge tests skimmed at patch lines 3818-4590.
- `apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py` patch lines 907-920: representative provenance diagnostic.
- `apps/prototype-description-service/recognition/application/orchestration/clustering/recovery_merge.py` patch lines 921-996: recovery merge changes.
- `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py` patch lines 997-1008: quality settings passed to representative selection.
- API regression tests skimmed at patch lines 2380-2545 for upload rejection logging and bounded health probes.
- Usage admission composition tests skimmed at patch lines 4735-4859.
