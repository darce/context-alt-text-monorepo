# SUBJECT-EVIDENCE-1 test specification packet

Status: `test_spec_pending_review`. Logical input `cfdae990650393c5639131616b59bb91c1b46a8d`; tree `940b641b3a36c44a320e91ea37cdc0c9d1c79db0`; honest native base `1a2a66c1e26f74e2818fadfe886ab2317ef6d3d2`. Test commit `9fce963fec5e512127b7fec48cf7966154984b5e`.

The whole approved plan was read before edits and its blob remains `06033dd9869a3b9e6ec06a1e743568d922ad6107`. The historical PROPOSED status is unchanged; the dispatch cites independent planning PASS 1475 / decision 17814 as acceptance authority. Prior SUBJECT-GATE-03 and SUBJECT-PLAN-G2 PASS0 were read; no new finding closure is asserted. Image-level pseudonym adoption 17811 is not per-face/group truth, complete absence or cross-frame identity equivalence.

Only the three owned existing test modules and this JSON/Markdown packet change. Required first Ruff formatting changed two files but retained every AST. Final AST census retains all 161 old selectors and 187 old definitions, including every old assertion. The formatter accounts for changes to old formatting; two import blocks were sorted to satisfy existing Ruff policy. No production/source, accepted plan, corpus, manifest, metadata or identity truth was edited.

The six public specifications use the real `build_bakeoff_report.main` grammar through a small fixture protocol driver: repeated selections, actual expected rosters, candidate/incumbent, all four baseline arms, synthetic score-ok marker, manifest/out and media-ids 1. Fixture attestations are explicitly synthetic protocol data, never actual independent review, inference or scores. No identity resolver, registry, waiver, fake future consumer, module stub, production monkeypatch or private comparison helper oracle is introduced. `C` uses independent standard JSON sorting with existing default separators/escaping; a Unicode audit reference exercises escaping. Strict fixtures bind to the real validated model-dump projection; no recursive loader helper constructs their expected identity.

| Exact new selector ID | Final observed cases | Expected versus current source |
| --- | --- | --- |
| `test_subject_evidence_mixed_same_person_public_cli` | 3 fail | Mixed shared-person comparisons in both directions and distinct mixed pair must return 5/incomparable; current shared pairs return 5 with only legacy diagnostics, distinct pair returns 0. Legacy disjoint 0/shared 5 controls execute first. |
| `test_subject_evidence_namespace_comparison_public_cli` | 4 fail | Same/different frame/keyspace/token must remain 5/incomparable. Current noncolliding pairs return 0; numeric media-ID collision returns 5 without incomparable reason. |
| `test_subject_evidence_supported_empty_scene_public_cli` | 3 fail | Supported-empty raw selection in entries or items must pass 0; current returns 5. Empty reported keeps 5 for mandatory subject strata 99/100; current also emits obsolete missing-evidence reasons. |
| `test_subject_evidence_unknown_partial_depiction_public_cli` | 4 fail, 2 pass | Unknown/partial group/reflection/depiction must remain incomparable even opposite supported-empty, with no row drop. Current aliases ignore structured records and lack typed reasons. Missing legacy and zero-face-only controls remain refused 5. |
| `test_subject_evidence_foreign_binding_and_version_public_cli` | 20 fail | Both roles, repeated selection index 2, raw/strict profiles, null/version/shape/support/binding/order/hidden ordinals must return 4/no output with stable error code, even exploratory or allow-foreign. Current raw inputs mostly render 0 (hidden reported duplicate produces 5); reported strict/string-version paths reject 4 with the old generic error. |
| `test_subject_evidence_amendment_rejects_old_digest` | 6 fail | Present evidence must change canonical digest; stale candidate/incumbent/each of four baseline pins refuse 4/no output after matching-pin exploratory control 0. Current real GoldenManifest rejects the field before those assertions. |
| `test_subject_evidence_omission_preserves_canonical_dump` | 1 pass | Pinned full old canonical SHA 0fff9297b4c1d04eebaf41224e5eee0c51502895356aa294d2fc2dcdbc83494c, retained old nulls, no evidence alias, frozen v2 route and present-null v2 refusal. |
| `test_subject_evidence_state_consistency` | 4 fail, 28 pass | Four valid supported states must load; current rejects field extra_forbidden. Strict types, duplicates, recursive unknown fields, status/support/conflict/projection/order/profile corruptions reject today only because whole field is forbidden. Valid cases independently recompute support and projection hashes from actual validated dumps once implemented. |
| `test_subject_evidence_never_changes_identity_truth` | 1 fail | Actual extracted prompt/caller/digest AST nodes execute without importing image/model clients; baseline controls pass. New real model acceptance fails extra_forbidden; subsequent assertions preserve every old field, prompt text, digest parity and v2 restriction. |

The final combined run collected all nine names, 76 parameter cases: **45 expected failures / 31 passes**, exit 1. No final collection or setup failures occurred. The 28 invalid schema rejections passing because the whole field is forbidden do not establish future validation quality. The four required preexisting report selectors passed separately; ready gate, matching strict digest, missing-baseline refusal and omitted-field compatibility controls also passed separately. Amended strict digest and identity comparisons remain real schema-acceptance REDs, not fake future behavior. The actual prompt AST and face-bakeoff digest nodes run before the new-field rejection; their baseline execution succeeded without initializing clients.

Predictions were retained before first runs in `/tmp/s-evidence-tests/predictions.json` and `predictions-r2.txt`. Intermediate Ruff import-order failures and one author fixture ordinal KeyError were corrected and retained; the final supported-empty schema fixture uses the existing person-free second row and fails at actual field acceptance. An import of the preexisting manifest test dependency produced the documented ONNX telemetry `:memory:.ses` artifact before collection guards; its exact bytes/hash and ownership proof were preserved privately before removing only that proven-owned artifact. No original pixels, image decoding, inference or model clients were executed.

The private audit harness gives each test/check subprocess a 55-second wall deadline, 1 GiB address-space limit, one CPU affinity and a 50ms-running/50ms-stopped duty cycle. Every bounded subprocess exited normally; no foreign process was signaled and no worker/agent was spawned. Per-CLI receipts retain actual argv, stdout, stderr, returned exit and imported report-source SHA, alongside full fixture inputs and rendered reports. Six Canon 0.26.2 bodies and 12 fired rows were hash-verified; original research excerpts and prior findings were read. TEST-06/23 predictions precede real REDs, TEST-25 drives the public boundary, TEST-33 reserves independent review, and TEST-15 mutant discrimination remains a source-lane obligation after real implementation. GRPH-01/32 edges are approved contract → fixture data/predictions → public/specification failures → future source consumers; no concurrent schedule is inferred.

Supplied semantic receipts report verified gte-base-en-v1.5 embeddings. The supplied readiness codemap is for another scope; six production files matched the existing exact-checkout subject map, followed by targeted source/caller/AST reads. No fresh live handoff database, graph generation, release fetch or new ONNX inference is claimed. Native session custody verifies gpt-6.1-sol/low; service tier is not exposed. The logical commit object is unavailable; equal trees establish bytes without ancestry.

Exact commands and exits follow (the retained wrapper applies environment/resource controls):

```sh
.venv/bin/python /tmp/s-evidence-tests/baseline.py
```

Exit 0: Required first formatter: two files reformatted, one unchanged; all three before/after AST hashes identical.

```sh
.venv/bin/python /tmp/s-evidence-tests/run.py old-selectors .venv/bin/python -m pytest -q -c /tmp/s-evidence-tests/pytest.ini -p no:cacheprovider --confcutdir=apps/prototype-description-service/scene/tests --basetemp=/tmp/s-evidence-tests/old-pytest apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff_report.py::test_bakeoff_gate_rejects_selection_subject_or_image_overlap apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff_report.py::test_matching_manifest_sha_renders_unbadged apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff_report.py::test_foreign_manifest_sha_is_fatal_and_writes_nothing apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff_report.py::test_manifest_version_as_string_fails_closed
```

Exit 0: Four required existing overlap, matching-digest, foreign-digest and string-version selectors passed.

```sh
.venv/bin/python /tmp/s-evidence-tests/run.py controls-verified .venv/bin/python -m pytest -q -c /tmp/s-evidence-tests/pytest.ini -p no:cacheprovider --confcutdir=apps/prototype-description-service/scene/tests --basetemp=/tmp/s-evidence-tests/controls-verified-pytest apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff_report.py::test_bakeoff_gate_passes_only_with_roster_baselines_and_observability apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff_report.py::test_matching_manifest_sha_renders_unbadged apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff_report.py::test_bakeoff_gate_is_not_ready_for_a_serving_skip_or_missing_baselines apps/prototype-description-service/scene/tests/test_eval_harness_manifest.py::test_subject_evidence_omission_preserves_canonical_dump
```

Exit 0: Four separate controls passed: ready raw gate, matching strict digest, missing-baseline refusal and pinned omitted-field/v2 compatibility.

```sh
.venv/bin/python /tmp/s-evidence-tests/run.py all-nine-final .venv/bin/python -m pytest -q -c /tmp/s-evidence-tests/pytest.ini -p no:cacheprovider --confcutdir=apps/prototype-description-service --basetemp=/tmp/s-evidence-tests/all-nine-final-pytest apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff_report.py apps/prototype-description-service/scene/tests/test_eval_harness_manifest.py apps/prototype-description-service/scripts/eval_harness/tests/test_manifest_invariants.py -k subject_evidence --tb=short
```

Exit 1: All nine approved selector IDs collected: 76 cases; expected RED, observed 45 failed and 31 passed. Raw evidence is ignored; strict models reject subject_evidence. No collection/setup failure in this final run.

```sh
.venv/bin/python /tmp/s-evidence-tests/run.py invariant-verified .venv/bin/python -m pytest -q -c /tmp/s-evidence-tests/pytest.ini -p no:cacheprovider --confcutdir=apps/prototype-description-service/scripts/eval_harness/tests --basetemp=/tmp/s-evidence-tests/invariant-verified-pytest apps/prototype-description-service/scripts/eval_harness/tests/test_manifest_invariants.py::test_subject_evidence_never_changes_identity_truth --tb=short
```

Exit 1: Actual prompt/caller/digest AST controls executed; expected and observed RED at real GoldenManifest acceptance (extra_forbidden), before amended-input equality assertions.

```sh
.venv/bin/python /tmp/s-evidence-tests/run.py lint-verified .venv/bin/ruff check apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff_report.py apps/prototype-description-service/scene/tests/test_eval_harness_manifest.py apps/prototype-description-service/scripts/eval_harness/tests/test_manifest_invariants.py
```

Exit 0: Scoped Ruff lint passed.

```sh
.venv/bin/python /tmp/s-evidence-tests/run.py format-check-final .venv/bin/ruff format --check apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff_report.py apps/prototype-description-service/scene/tests/test_eval_harness_manifest.py apps/prototype-description-service/scripts/eval_harness/tests/test_manifest_invariants.py
```

Exit 0: All three owned test files already formatted.

```sh
.venv/bin/python /tmp/s-evidence-tests/run.py ast-census-final .venv/bin/python /tmp/s-evidence-tests/audit.py
```

Exit 0: All 161 old selectors and 187 existing definitions retain identical ASTs; exact nine new plan selectors; 41 actual CLI receipts retain output/exits/import SHA; production source and plan pins unchanged.

Full raw evidence: `/tmp/s-evidence-tests`, including `all-nine-final.stdout/.stderr/.exit/.receipt.json`, `all-nine-final-pytest/`, per-call `cli-receipt.json`, `cli-census.json`, `ast-census.json`, formatter before/after hashes, native-session custody, readonly source snapshots, and `artifact-inventory.json`. No owned runtime remains running; no shared cache cleanup occurred. The implementation commit is listed in JSON; the packet commit cannot include its own content-derived hash.

Root must independently review this test specification before dispatching the separately authorized source author. This lane grants no main merge, finding closure, quality adoption or actual bakeoff authorization.

Packet verification: `.venv/bin/python /tmp/s-evidence-tests/run.py packet-verify-final .venv/bin/python /tmp/s-evidence-tests/verify_packet.py`, exit 0. Its first pre-staging scope check omitted ignored packet files; exact authorized packet paths were then staged and the scope check passed. Raw failed/successful verifier receipts are retained separately.
