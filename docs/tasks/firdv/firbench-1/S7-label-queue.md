# S7 · Occlusion label queue generator and importer

- **Wave:** W3 batch B · **Depends on:** S0
- **Owned paths:**
  - `benchmarks/tools/fir_occ_label_queue.py` (already allowlisted in `.gitignore`)
  - `apps/prototype-description-service/scripts/eval_harness/fir_occ_labels.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_fir_occ_labels.py`
  - The S7 test surface also includes `test_eval_harness_fir_occ_labels_bundle.py`, `test_eval_harness_fir_occ_labels_evidence.py`, `test_eval_harness_fir_occ_label_queue_interaction.py` and `test_eval_harness_firbench_label_bundle_runtime.py`.
- **Policy basis:** Canon v0.26.2 rows HITL-03, HITL-05, HITL-07, MLDATA-03, MEAS-29 and the interaction rows cited below. MCP 16734 and 16736 QC defaults. Those defaults are pre-data project policy, not source-established accuracy guarantees.

## Goal

The operator labels real occlusion from pixels. Captions only choose what goes into the queue, never what the label is (MLDATA-03, HAI-11). The generator writes a private single-file HTML; the importer turns its export into fir-occ-v1 face-instance labels with quality checks (HITL-03).

## Status

Verified against the accepted source tree (tree `21408d43562ef2f49a3b27c53112bae0cc822605`). Static inspection and the named tests show what the code does. None of this is a real label, observation or QC result.

**Implemented**

- **Generator** (`benchmarks/tools/fir_occ_label_queue.py`, 590 lines). Output passes `require_private_output_path` (`:569`). Images are embedded as base64 data URIs (`:478`). The generator source contains no `http://` or `https://` reference. The visible template contains no `repeat`, `gold` or `blind` token. The generator contains no `setTimeout` or `setInterval`.
- **Draw mode.** The draw panel says "Drawing a box — enter pixel coordinates or drag on the image, then commit or cancel." It has `Commit box (Enter)` and `Cancel draw (Esc)` buttons (`:79–86`). `:focus-visible` is styled with a visible outline (`:52`).
- **Keymap** (implemented `data-key` values, `:85–115`). Occluders: `m` mask, `s` sunglasses, `h` hand, `o` object, `x` mixed, `n` none, `?` cannot tell. Region visibility: `v`. `a` adds a missed face (enters draw mode). `u` marks an unknown person. `f` is the face decision and `.` is next face. `k` skips and records a nonresponse. `Enter` is next (or commit, in draw mode). `Escape` is undo (or cancel, in draw mode). The page also provides a visible button for each action.
- **Union-delta mode** (`--union-delta`; schema `fir-occ-union-proposals/v1`). Shows only unmatched proposal boxes (`union_delta_counts`, `fir_occ_labels.py:919`).
- **Confirmed boxes.** Shown only when a queue item sets `show_confirmed_boxes: true` (`fir_occ_labels.py:441`).
- **Importer** (`fir_occ_labels.py`). `load_label_export` (`:286`, schema `fir-occ-labels/v1`), `load_queue` (`:400`), `to_face_instances` (`:1356`), `to_synthetic_face_instances` (`:1370`), `require_real_analysis_rows` (`:1379`), `repeat_agreement` (`:567`), `gold_accuracy` (`:585`), `union_delta_counts` (`:919`).
- **Undefined kappa and support.** An undefined kappa returns `kappa_undefined` and is not coerced (`:580`). A field or annotator below its support floor returns `support_not_accrued` and the import refuses (`:750–753`).
- **Observation gate.** `_require_observation` (`:1181`) requires an `fir-occ-observation/v1` record with `record_kind` `bounded_human_observation`, no fixture origin, and the keys `observer_id`, `observed_at`, `scope`, `method`, `operator_accounts`, `limits`, `exceptions`, `applicability` and `context`. `_require_applicability` compares six measurement-context keys: `rule`, `instructions`, `operators`, `collection_workflow`, `adjudication_workflow` and `tool_behavior`. No `allow_unobserved_fixture` parameter exists in production source; `test_production_has_no_bypass` asserts that passing the keyword raises `TypeError`.
- **Packaged label evidence** (`fir_occ_labels.py:1395–1767`). `LabelEvidenceBundle`, `freeze_label_evidence` and `requalify_label_evidence` are implemented with the signatures below. The closure is walked by `_closure` (`:1592`) and read through `_take_original` (`:1652`) and `_read_regular` (`:1638`). Duplicate JSON keys and non-finite numbers are refused by `_strict_json` (`:1535`).
- **Runtime wiring.** `PreparedRun.label_evidence` is the last field, defaults to `None`, and existing injected collaborators still work (`firbench_runtime.py:138–147`). When a binding carries `label_evidence`, the runtime calls `freeze_label_evidence` (`firbench_runtime.py:496–503`). The CLI validates the descriptor against the frame hash and the file bytes, then creates each bundle file with exclusive open (`xb`) before it writes `frame.json` and `manifest.json` (`firbench_cli.py:398–450`). `manifest.firbench.label_evidence` carries the descriptor.
- **Report consumer.** `_binding_label_evidence` in `firbench_report.py` (`:959–1027`) calls `requalify_label_evidence` and withholds analytics with a reason when it fails. See S5.

**Test surface present by name** (not re-run for this document). The browser-driven L1 tests need `FIR_OCC_PLAYWRIGHT` and `node` and skip otherwise (`test_eval_harness_fir_occ_label_queue_interaction.py:228–229`). The report and runtime tests are listed under RED tests.

**Prior verification receipt.** Recorded by the coordinator at an earlier revision and not re-run here: an earlier joined-label run of 284 tests. It overlaps the current suites and is not evidence for any test named in this brief.

**Not established**

- No genuine MEAS-29 observation record is supplied in this tree, so no real tier-(a) label feeds analysis. A real tier-(a) import with a null, missing, unresolved or inapplicable reference refuses (`_require_observation`, `to_face_instances`).
- No real gold, repeat or SME evidence is supplied, so no real import has passed its QC gate.
- No real labels, images or alias maps are in any bundle. The bundle contains only the export, queue, gold and acceptance records that the readers open.

**Open findings**

- **Role mapping in the page.** The generated page embeds the presented-item mapping as base64 JSON in `payload.hidden` (`fir_occ_label_queue.py:542`). The page decodes it at `JSON.parse(atob(payload.hidden))` (`:434`), so each item's role (`consistency` or `known_answer`) is recoverable from the page source. This meets the plain-text checks (the static template check and the browser `privacy` scenario), but base64 is encoding, not concealment. The brief's rule that repeat and gold roles are internal to the export is not met for a motivated annotator. Resolution is open: move the mapping out of the annotator page, or record the limitation with the QC evidence.
- **Export hidden block.** The export keeps the presented mapping in its hidden block, as the brief requires, and the bundle keeps that file's bytes unchanged. The finding above concerns the annotator page, not the export.

## Goal of the evidence contract (frozen for S5 and the runtime)

Module `scripts.eval_harness.fir_occ_labels`:

```python
@dataclass(frozen=True)
class LabelEvidenceBundle:
    descriptor: Mapping[str, Any]
    files: Mapping[str, bytes]

def freeze_label_evidence(
    export_path: Path,
    queue_path: Path,
    gold_path: Path,
    *,
    repo_root: Path,
    frame_sha256: str,
) -> LabelEvidenceBundle: ...

def requalify_label_evidence(
    run_dir: Path,
    descriptor: Mapping[str, Any],
    *,
    frame_sha256: str,
) -> tuple[dict[str, Any], ...]: ...
```

- **Read-only.** `freeze_label_evidence` writes nothing. It calls the actual `load_label_export`, `load_queue` and `to_face_instances` readers, and captures the exact immutable JSON bytes of the closure they open. It does not read images, a model, or an alias map. `requalify_label_evidence` validates the descriptor and frame hash, refuses symlinks, and calls the actual S7 readers on run-local copies only.
- **Descriptor keys (exact):** `schema` (`firbench-label-evidence/v1`), `frame_sha256`, `export_path`, `queue_path`, `gold_path`, and `files` (sorted list of `{path, sha256}`). Paths are run-relative `label-evidence/<original repo-relative private path>`, and every path must lie under `benchmarks/private/` before packaging.
- **Whitelisted edges only.** The closure follows `queue.acceptance_path`, the four acceptance links `prior_export`, `validation_queue`, `validation_gold` and `validation_export` (each an exact `{path, sha256}`), and `export.observation_ref` for tier (a). No other reference is followed, and no directory is copied.
- **Refusals.** Absolute, escaping, symlinked, ambiguous or cyclic links, duplicate or non-finite JSON, synthetic or mixed origins, and eligibility-claim keys are refused by name before writes.
- **Hash binding.** `frame_sha256` is `SHA256(ff.frame_json(prepared_frame) + "\n")` in UTF-8, matched against the immutable `frame.json` bytes.
- **Requalification.** A missing, corrupt or changed proof raises `FrameContractError`. A JSON boolean, a reference string or copied metadata never qualifies a row.

## Build

1. **Generator CLI:** `python3 benchmarks/tools/fir_occ_label_queue.py --queue <private.json> --images <dir> --gold <private gold.json> --repeat-fraction 0.10 --seed <S> --out benchmarks/private/fir-occ/queue-<stamp>.html`.
   - `--seed` is required in the implemented CLI (`fir_occ_label_queue.py:560`). The earlier default is not in source. The declared label-queue seed is `336880394`: the first 32 bits, big-endian, of SHA-256 `FIRBENCH-1/v1/label_queue` (verified).
   - `--rule-id` must equal `RUBRIC_VERSION` (imported from `gate_contract`; `:30`, `:482–483`).
   - `--repeat-fraction`, when supplied, must equal `queue.qc.repeat_fraction` (`:484–489`).
   - The output path must pass `require_private_output_path`, or the CLI refuses.
   - Images are embedded as base64. Requirement: no detector boxes, captions or model names appear in the HTML. The browser `privacy` scenario checks visible text and element attributes for the tokens `gold`, `repeat`, `blind`, `caption`, `detector` and `modelname`. It does not check for boxes.
   - Existing confirmed GT boxes are shown only when the queue item carries `show_confirmed_boxes: true`.
   - Blind repeats are re-inserted under opaque ids at shuffled positions. Repeat choice uses `random.Random(f"{seed}|{queue_id}|repeat")` (`:506`). Gold items are inserted the same way (`:509`). The roles are held in the hidden block (see Open findings).
   - Gold mix: random, batch-matched and hard items (HITL-03). Gold answers come from an independent SME author, not the labelling operator, and are non-caption answers. The gold checks reuse `GoldItem` (`scripts/eval_harness/pilot_draw.py:106`).
   - QC block: the queue carries a `qc` block written before any import. It holds the delegated project policy from MCP 16734:
     - `gold_share` 0.10 and `repeat_fraction` 0.10;
     - per-field repeat percent-agreement floor 0.90;
     - per-field Cohen kappa floor 0.80;
     - per-annotator independent-gold accuracy floor 0.90;
     - `min_gold_decisions_per_annotator` 20 and `min_repeat_decisions_per_field` 20 (MCP 16736).
   - These values are declared before any data. They are not accuracy guarantees, and alpha ≈ 0.8 guidance (HITL-05) is not a kappa equivalence. A `null` in any `qc` value still refuses import.
   - Keyboard map and buttons: see Status. Every shortcut has a visible button with the same action.
   - Focus: every focusable control shows a visible `:focus-visible` outline, and the browser `parity` scenario asserts a non-`none` outline on each focused button while Tab reaches every visible button.
   - Draw mode (one mode at a time): `a` or its button enters draw mode and shows the banner. While drawing, Enter (or Commit box) commits and Esc (or Cancel draw) cancels and restores the item. Outside draw mode, Enter means next and Esc means undo. `u` never opens a second mode. The banner disappears on leaving draw mode.
   - No timer advances or closes an item. The browser `privacy` scenario fast-forwards the clock by 24 hours and asserts the item position is unchanged.
   - Skips are recorded as nonresponse, never dropped.
   - Exact-duplicate groups are labelled once and propagated on import (`test_duplicate_group_labels_propagate_to_members`).
   - Union-delta mode (`--union-delta <proposals.json>`): shows only proposal boxes from candidate detectors that are unmatched to GT, source-blind and shuffled. Each item asks "face / not a face / cannot tell".
2. **Importer** (`fir_occ_labels.py`):
   - `load_label_export(path)` validates `fir-occ-labels/v1` and raises `FrameContractError` at load time [rg-008].
   - `to_face_instances(export, queue)` is the production importer and has no observation-bypass argument. It produces fir-occ-v1 rows with stable unit id, identity status, box, multi-label occluder set, region visibility and rule id. Each row keeps the annotator's pre-adjudication labels as exported, separately from any corrected label and its acceptance evidence.
   - `repeat_agreement(export)` gives per-field percent agreement and Cohen's kappa over blind repeats, with the undefined-kappa handling below.
   - `gold_accuracy(export, gold)` gives per-annotator accuracy on known-answer items.
   - `union_delta_counts(export, queue)` returns the inputs `union_adjudication.detector_gap_bound` expects.
   - **Undefined kappa.** Cohen's kappa is `(p_o − p_e) / (1 − p_e)`. When `p_e = 1`, kappa is undefined. It returns `null` with reason `kappa_undefined`. It is never coerced to 0, 1 or a pass. Its field routes to SME adjudication. Percent agreement is still reported.
   - **Support floors.** A field with fewer than 20 repeat decisions returns `support_not_accrued`. An annotator with fewer than 20 gold decisions also returns `support_not_accrued`. Neither is a pass or a fail. Support is counted across the declared annotation run.
   - **QC gate.** `to_face_instances` and the import are refused with `FrameContractError` when:
     - any `qc` value is null;
     - any support floor is unmet;
     - any field agreement is below 0.90, any defined field kappa is below 0.80, or an undefined field kappa lacks the qualified SME resolution below;
     - any per-annotator gold accuracy is below 0.90.
   - A set that fails the gate is not imported as labels. Its routing:
     - **Repair list** (below-floor agreement, kappa or gold accuracy): preserve the failed set, diagnose the cause and repair under a versioned label/disagreement rule. Corrected labels are candidates, not automatically accepted on resubmission.
     - **SME list** (low-agreement, undefined-kappa, uncertain or eval-critical fields): routed to qualified SME adjudication (HITL-07, *Human-in-the-Loop ML*). Repair may proceed alongside this review. Disputed labels do not return to the worker pool as their final resolution.
     - The importer never deletes an annotator, drops labels or removes repeat items to raise agreement (HITL-05).
   - **Preservation.** Keep the original export, original answers and original QC results immutable, including support counts, failures and undefined metrics. Every repair or SME record references the item ids, original labels and prior export sha256. Corrected labels, reasons and their QC or disposition are separate records. No earlier answer or QC result is overwritten (MLDATA-03).
   - **Resubmission and fresh QC.** A corrected export is a new version linked to the prior export sha256 and a new declared QC run. Scope, rule version, thresholds, support policy and validation assignment are frozen before evaluation. An independent QC author supplies fresh known-answer gold and newly blinded repeat presentations. The evaluator is blinded to prior answers and outcomes. Retain both runs and link each result to the exact candidate version. Accrue at least 20 independent-gold decisions per evaluated annotator and at least 20 repeat decisions per evaluated field within the new run, with the same floors. Old support never carries forward as if it validated the correction. The original failure stays historical evidence, not a permanent veto on a separately qualified corrected version (HITL-03; HITL-05).
   - **Qualified SME resolution.** A resolution identifies the corrected candidate hash, item/field scope, expert, written disagreement rule, rationale and independent validation evidence. The SME qualifies by independent-gold accuracy of at least 0.90 on at least 20 decisions in the declared validation run, not by title alone. Corrected fields still require at least 20 blinded repeat decisions with agreement at least 0.90. A defined kappa must meet 0.80. For undefined kappa, `null` and `kappa_undefined` are retained and an explicit field-specific SME disposition is recorded, supported by independent gold validation of the corrected field. This never fabricates a passing kappa or waives missing support, failed numeric floors or observation evidence. Without the supported resolution, import stays blocked.
   - **Multiplicity.** No set is called "gold" until the written label rule and disagreement rule exist (T-09, MLDATA-03).
   - Every row carries `annotation_tier` (`a` for occluder labels with missed-face additions; `b` for exhaustive pixel labelling). Tier-(a) rows are never counted as exhaustive.
   - **Process observation** is an operator task, not this lane's. Before any real tier-(a) label feeds analysis, the operator observes a bounded sample of labelling in context and asks operators how values, exceptions and outliers are produced. The record states scope, method, exceptions, context and what the sample does and does not establish. One observation does not prove unbiased measurement (MEAS-29, *Seeing with Fresh Eyes*, ch. 4).
   - The export carries `observation_ref` (string or null). Production import requires a nonempty reference to an available genuine observation record and a documented applicability assessment covering this export or run. The reference is resolved and its required record and context fields are validated. A nonempty string alone is not evidence. Record validation does not itself prove a human observation occurred. No observation is supplied in this tree, and none is invented.
   - A real tier-(a) import with null, missing, unresolved or inapplicable observation evidence is always refused with `FrameContractError`, including after repair or SME resolution. No production override exists in the CLI or the API.
3. **Synthetic helper boundary.** Tests and tooling may use `to_synthetic_face_instances(export, queue)` only for controlled generated numpy fixtures. It requires `data_origin=generated_fixture`, an allowlisted generator id, a fixed seed and a generated-image sha256 for every queue item, bound to the export's queue hash and item ids. It regenerates the expected pixels from that recipe and verifies their hash. It rejects arbitrary image loaders, real source references and real, mixed or unknown-origin inputs. Its output is fixture-only, persistently marked synthetic and `analysis_eligible=false`. Production import and real-analysis consumers reject it (`require_real_analysis_rows`, `:1379`). It may leave `observation_ref=null` without asserting any human observation. The helper cannot turn a real null-evidence tier-(a) import into an allowed one.
4. **Observation reuse.** Compare the observed and current measurement context: rule, instructions, operators, collection and adjudication workflow, and relevant tool/UI behaviour (`_require_applicability`). Document changes and why the bounded record still covers how labels, exceptions and outliers are produced, with limits. A version-only or unrelated UI change does not automatically invalidate an applicable observation. A material change beyond its scope, or uncertain applicability, requires a new bounded observation before analysis. Do not infer applicability from a matching version string alone.
5. **Packaged label evidence** (see Goal of the evidence contract). The runtime and CLI own persistence: they write exactly `bundle.files` bytes with exclusive create before query outcomes, and record `manifest.firbench.label_evidence = descriptor`. Static invalid evidence writes and spends nothing. The report requalifies the bundle through the actual readers before any row is displayed (S5).

## RED tests

Present by name. Not re-run for this document.

- **Generator:** `test_repeat_policy_comes_from_canonical_queue`, `test_configured_fraction_controls_presentations`, `test_production_has_no_bypass`, `test_canonical_seven_keys_and_old_alias_refusal`.
- **Synthetic boundary:** `test_synthetic_boundary_rejects_relabelled_real_unknown_and_tampered_inputs`, `test_synthetic_rows_are_persistently_ineligible_for_real_analysis`, `test_synthetic_queue_cannot_be_frozen_as_real_evidence`, `test_synthetic_helper_rows_stay_persistently_ineligible`.
- **Production observation gate:** `test_production_rejects_null_or_unresolved_observation`, `test_tier_a_without_observation_reference_is_refused`, `test_reference_string_without_a_record_is_refused`, `test_observation_marked_as_fixture_origin_is_refused`, `test_observation_that_is_a_bare_boolean_is_not_evidence`, `test_existing_non_observation_document_cannot_satisfy_production_gate`.
- **Observation reuse:** `test_context_applicability_refuses_unsupported_reuse`, `test_documented_context_comparison_is_not_human_observation_evidence`.
- **Support, undefined kappa and routing:** `test_direct_run_with_nineteen_decisions_is_neither_pass_nor_fail`, `test_real_readers_refuse_insufficient_support_before_any_bundle`, `test_supported_sme_resolves_undefined_diagnostic_without_fabricating_kappa`, `test_undefined_sme_cannot_waive_support_or_claim_expertise_by_title`, `test_separately_qualified_sme_can_resolve_a_corrected_version`, `test_null_occluders_remain_distinct_from_explicit_empty_set`.
- **Repair and resubmission:** `test_fresh_supported_qc_accepts_corrected_candidate_without_rewriting_failed_run`, `test_recovery_refuses_unqualified_evidence`, `test_missing_recovery_evidence_cannot_fall_back_to_old_repeats`, `test_loaded_answers_assignments_and_qc_cannot_change_under_the_same_hash`.
- **Skips, duplicates, union:** `test_skip_is_nonresponse_and_duplicate_group_propagates`, `test_duplicate_group_labels_propagate_to_members`, `test_union_delta_mode_shows_only_unmatched_proposals`, `test_union_delta_counts_feed_detector_gap_bound`.
- **Gold checks:** `test_gold_items_must_pass_pilot_draw_gold_checks`.
- **Evidence bundle:** `test_descriptor_has_exact_keys_and_sorted_bound_files`, `test_bundle_is_the_exact_read_closure_with_original_bytes`, `test_bundle_omits_observation_for_tier_b_because_no_reader_opens_it`, `test_freeze_writes_nothing_and_reads_no_pixels`, `test_copied_bytes_replay_through_actual_s7_after_originals_are_removed`, `test_requalify_is_readonly`, `test_tier_b_bundle_replays_without_observation`, `test_frame_hash_must_be_a_lowercase_sha256_string`, `test_eligibility_claim_keys_are_refused_even_when_false`.
- **Link and file refusals:** `test_absolute_acceptance_path_is_refused`, `test_absolute_observation_reference_is_refused`, `test_escaping_link_is_refused`, `test_ambiguous_non_canonical_link_is_refused`, `test_symlinked_support_record_is_refused`, `test_symlinked_directory_on_the_path_is_refused`, `test_cyclic_link_back_to_an_ancestor_is_refused`, `test_missing_closure_member_is_named`, `test_original_outside_benchmarks_private_is_refused`, `test_parent_segments_in_original_paths_are_refused`, `test_duplicate_json_is_refused_even_when_the_hash_is_rebound`, `test_duplicate_json_keys_are_refused_in_every_closure_document`.
- **Browser (env-gated; skip without `FIR_OCC_PLAYWRIGHT` and `node`):** scenarios `draw`, `keyboard`, `cancel`, `progress`, `recover`, `parity`, `image-error`, `empty`, `union` and `privacy`, in `test_eval_harness_fir_occ_label_queue_interaction.py`.

Open (documentation only):

- Role mapping outside the annotator page (Open findings). No test asserts the current base64 mapping is absent from the page, and none could, because the mapping is present by design.
- Real-data QC evidence, real observation references and real-run bundles. These remain external prerequisites.

## Done when

Tests pass on the VM, using the test command in the firbench-1 README with an isolated basetemp. The browser-gated L1 scenarios run in an environment with `FIR_OCC_PLAYWRIGHT` and `node`. This slice is tooling only: labelling itself is the operator's tier-(a) task. Real imports stay gated by a genuine observation reference and support floors, as in MCP 16734. No real tier-(a) label feeds analysis until both are supplied and verified.

## Policy, measured and unresolved

| Item | Policy (declared) | Measured here | Unresolved |
| --- | --- | --- | --- |
| QC floors (agreement 0.90, kappa 0.80, gold 0.90, support 20) | Declared (MCP 16734, 16736) | None | Any real QC result |
| Label-queue seed `336880394` | Declared (MCP 16733) | Derivation recomputed | Operator use of the seed |
| Observation | Gate in place | None recorded | Genuine MEAS-29 record |
| Evidence bundle | Software contract | Static reads only | Genuine persisted bundle from real evidence |
