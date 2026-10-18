VERDICT: REVISE
POR: {"file_count":267,"line_count":22855,"md5":"95253c630a3e6e0037ab936ee5cd2592","sample_lines":{"41":"-from recognition.interface_adapters.http.deps.portal_composition import install_portal_composition","173":"         mc_check, cache_dir, model_name = await _model_probe()"}}
## Findings
- H-1 (HIGH): apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_composition.py:1963 The admission dependency discards the ticket returned by `reserve` and has no commit or release path after the route completes. Failure: a successful metered analysis leaves its usage ticket `RESERVED`, leaking in-flight capacity on each request. Canon: RES-14, RLSE-05.
- M-1 (MEDIUM): apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_composition.py:1915 The multipart tenant lookup buffers the entire network body without a byte limit or deadline before the route's bounded parser runs. Failure: a large or slow multipart upload holds the request and allocates its full body before route-level bounds can reject it. Canon: RES-02.
- H-2 (HIGH): apps/prototype-description-service/recognition/interface_adapters/http/routers/suggestions.py:2196 The merge acceptance update filters only by tenant and suggestion ID, so a stale acceptance can overwrite a concurrent rejection or expiry. Failure: when a suggestion is rejected after the handler reads it but before this update, the handler still merges the clusters and marks the suggestion accepted. Canon: CON-05, CON-11.
## Coverage
- `apps/prototype-description-service/recognition/application/scan/service.py` patch lines 1009-1286: persist-lock registry, transaction release callbacks, deterministic media ordering, generator input handling, and identity persistence.
- `apps/prototype-description-service/recognition/application/services/usage_admission_service.py` patch lines 1287-1382: repository-operation timeout wrapper and reserve/commit/release calls.
- `apps/prototype-description-service/recognition/application/settings/clustering.py` patch lines 1383-1562: quality floor, structured abstention clauses, false-name acceptance validation, and calibration policy.
- `apps/prototype-description-service/recognition/application/suggestions/refresh_service.py` patch lines 1563-1581: expiration result handling.
- `apps/prototype-description-service/recognition/infrastructure/face_pipeline/aligner.py` patch lines 1582-1607: formatting-only changes.
- `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` patch lines 1608-1752: top unreverted receipt query and snapshot relationship population.
- `apps/prototype-description-service/recognition/infrastructure/repositories/portal_identity_repository.py` patch lines 1753-1767: formatting-only change.
- `apps/prototype-description-service/recognition/infrastructure/repositories/suggestion_repository.py` patch lines 1768-1803: conditional pending-to-expired update and current-state return.
- `apps/prototype-description-service/recognition/infrastructure/repositories/tenant_entitlement_repository.py` patch lines 1804-1851: formatting-only changes.
- `apps/prototype-description-service/recognition/infrastructure/repositories/tenant_repository.py` patch lines 1852-1860: trailing blank-line removal.
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_composition.py` patch lines 1861-1994: usage service dependency, tenant extraction, multipart body/form handling, and reservation call.
- `apps/prototype-description-service/recognition/interface_adapters/http/router.py` patch lines 1995-2045: analysis admission dependency mounting and deferred cluster router registration.
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters_snapshot.py` patch lines 2046-2073: explicit null quality-component export.
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters_topology.py` patch lines 2074-2165: tenant assertions before topology replay lookups.
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/suggestions.py` patch lines 2166-2226: merge-suggestion tenant validation/status update and confidence pagination.
