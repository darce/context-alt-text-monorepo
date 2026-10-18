VERDICT: REVISE
POR: {"file_count":267,"line_count":22855,"md5":"95253c630a3e6e0037ab936ee5cd2592","sample_lines":{"41":"-from recognition.interface_adapters.http.deps.portal_composition import install_portal_composition","173":"         mc_check, cache_dir, model_name = await _model_probe()"}}
## Findings
- M-1 (MEDIUM): `apps/prototype-wp-alt-context/src/sovereign/repositories/class-roster-entry-projection-repository.php`:13853 only copies representative quality and components when a representative identity resolves, so a stored projection with no resolved identity silently omits both values from the roster response. Failure: a cluster row has `representative_quality=0.82`, `quality_components={...}`, and an empty or unresolved `representative_id` -> `representative_identity` is null and neither quality field is returned, despite the roster regression expecting both. Canon: RLSE-05.
## Coverage
`apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` patch lines 13511-13583: typed detail-key allowlist, circuit-open response, Retry-After bounds, and breaker duration.
`apps/prototype-wp-alt-context/src/api/services/class-person-merge-service.php` patch lines 13584-13613: undo-record integer bounds for local revision and unsigned cluster count.
`apps/prototype-wp-alt-context/src/public/class-public-guide-route.php` patch lines 13614-13670: manifest failure telemetry and action dispatch.
`apps/prototype-wp-alt-context/src/sovereign/mappers/class-cluster-response-mapper.php` patch lines 13671-13729: cluster export metadata normalization and response mapping.
`apps/prototype-wp-alt-context/src/sovereign/repositories/class-cluster-projection-writer.php` patch lines 13730-13786: strict snapshot-version upsert guard and paired quality-field validation.
`apps/prototype-wp-alt-context/src/sovereign/repositories/class-cluster-snapshot-merger.php` patch lines 13787-13837: version-gated snapshot updates and completeness-envelope gating.
`apps/prototype-wp-alt-context/src/sovereign/repositories/class-roster-entry-projection-repository.php` patch lines 13838-13910: roster projection mapping, metadata normalization, and unresolved-representative omission.
`apps/prototype-wp-alt-context/src/sovereign/sync/class-reclaimer-liveness.php` patch lines 13911-14031: lease-read fencing and option-cache invalidation/publication.
`apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` patch lines 14032-14052: TEXT default and tenant-leading outbox index schema changes.
