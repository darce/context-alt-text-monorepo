VERDICT: REVISE
POR: {"file_count":267,"line_count":22855,"md5":"95253c630a3e6e0037ab936ee5cd2592","sample_lines":{"41":"-from recognition.interface_adapters.http.deps.portal_composition import install_portal_composition","173":"         mc_check, cache_dir, model_name = await _model_probe()"}}

## Findings
- H-1 (HIGH): scripts/deploy/recognition-service.sh:17640 The YAML secret-block matcher misses tagged or anchored headers and the supported Authorization field, leaving their indented scalar lines outside redaction. Failure: `password: !!str |\n  opaque-value-123` or `Authorization: |\n  opaque-value-123` -> diagnostic contains `opaque-value-123`. Canon: CARD-07.

## Coverage
- `scripts/deploy/recognition-service.sh` patch lines 17428-19223: read every changed hunk; checked diagnostic sanitization, model preflight, Vault-aware unit rendering, sticky repository handling, lease budgeting, convergence, restart/cutover, rollback, verification, and GPU lifecycle.
- `scripts/deploy/tests/test_dw2_recognitio_1.py` and `scripts/deploy/tests/test_dw2_recognitio_2.py` patch lines 20201-20575, plus `scripts/deploy/tests/test_dw2_recognitio_5.py` patch lines 20576-20653: skimmed YAML block redaction, lease TTL, diagnostic handling, and portability assertions.
