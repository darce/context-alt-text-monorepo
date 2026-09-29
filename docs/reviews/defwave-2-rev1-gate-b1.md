VERDICT: MERGE
POR: {"file_count":267,"line_count":22855,"md5":"95253c630a3e6e0037ab936ee5cd2592","sample_lines":{"41":"-from recognition.interface_adapters.http.deps.portal_composition import install_portal_composition","173":"         mc_check, cache_dir, model_name = await _model_probe()"}}
## Findings
- L-1 (LOW): apps/prototype-description-service/scene/application/describe_run_worker.py:6954 `first_ready_before` remains assigned in the locked-readiness path after the new repository return value replaced its last use. Failure: Ruff F841 reports the unused local and makes the configured lint check exit nonzero. Canon: RLSE-02.
## Coverage
- `apps/prototype-description-service/recognition/worker/scan_worker.py` patch lines 6715-6761: lock-timeout dialect guard, engine event installation, and worker initialization.
- `apps/prototype-description-service/scene/application/describe_operation_repository.py` patch lines 6762-6891: RLS bypass, active lease retention and stop-held filtering, parent-first batched purge.
- `apps/prototype-description-service/scene/application/describe_run_repository.py` patch lines 6892-6934: locked run lookup and first-readiness result.
- `apps/prototype-description-service/scene/application/describe_run_worker.py` patch lines 6935-7019: startup lookup after run lock, readiness recording, exception timing traversal.
- `apps/prototype-description-service/scene/application/identity_merge/merge.py` patch lines 7020-7061: finite dimensions and normalized box bounds.
- `apps/prototype-description-service/scene/application/visual_facts_service.py` patch lines 7062-7074: phrase span order validation.
- `apps/prototype-description-service/scene/interface_adapters/http/deps.py` patch lines 7075-7096: optional description profile resolution.
- `apps/prototype-description-service/scripts/bench/corpus.py` patch lines 8972-9002: append validation and per-row JSONL rejection.
- `apps/prototype-description-service/scripts/eval_harness/cli.py` patch lines 9003-9038: same run manifest passed through direct and cross-process scoring.
- `apps/prototype-description-service/scripts/eval_harness/experiment_manifest.py` patch lines 9039-9100: corpus SHA pin and aborted-state agreement.
- `apps/prototype-description-service/scripts/eval_harness/face_metrics.py` patch lines 9101-9256: nearest-rank percentile, human lineage allowlist, strict geometry and row refusal metadata.
- `apps/prototype-description-service/scripts/eval_harness/florence_describe.py` patch lines 9257-9271: formatting-only line change.
- `apps/prototype-description-service/scripts/eval_harness/judgment_pool.py` patch lines 9272-9330: human contributor family and contribution-count initialization.
- `apps/prototype-description-service/scripts/eval_harness/pilot_draw.py` patch lines 9331-9514: selection input validation and formatting-only changes.
- `apps/prototype-description-service/scripts/eval_harness/prepull_weights.py` patch lines 9515-9530: formatting-only output change.
