# S7 · Occlusion label queue generator and importer

- **Wave:** W3 batch B · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0
- **Owned paths:**
  - `benchmarks/tools/fir_occ_label_queue.py` (already allowlisted in `.gitignore`)
  - `apps/prototype-description-service/scripts/eval_harness/fir_occ_labels.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_fir_occ_labels.py`
- **Policy basis:** Canon v0.26.2 and MCP 16734 (queue QC defaults). Those defaults are pre-data project policy, not source-established accuracy guarantees.

## Goal

The operator labels real occlusion from pixels. Captions only choose what goes into the queue, never what the label is (MLDATA-03, HAI-11). The generator writes a private single-file HTML; the importer turns its export into fir-occ-v1 face-instance labels with quality checks (HITL-03).

## Read first

- Scope doc § "Real-occlusion ground truth" (queue sources, traps, effort tiers)
- `docs/assessments/current/fir-occlusion-corpus-and-metrics-2026-09-19.md` § annotation fields (the fir-occ-v1 field table)
- `benchmarks/tools/fir_corpus_population_draft_20260919.py` (style of a tracked generator that emits private files)
- The existing operator annotator is `benchmarks/tools/golden150-box-annotator.html`. It is local-only and is NOT on the VM. Its pattern: embedded images, `keydown` shortcuts, a download button for the export. Do not try to read it; this brief gives the behaviour.

## Build

1. Generator CLI: `python3 benchmarks/tools/fir_occ_label_queue.py --queue <private.json> --images <dir> --rule-id face-label-rule/v1 --repeat-fraction 0.10 --gold <private gold.json> --seed S --out benchmarks/private/fir-occ/queue-<stamp>.html`
   - `--seed` defaults to the declared label-queue seed 336880394 (MCP 16733).
   - The output path must pass `require_private_output_path`, or the CLI refuses.
   - Images are embedded as base64. No detector boxes, no captions, no model names appear in the HTML.
   - Existing confirmed GT boxes may be shown only when the queue entry carries `show_confirmed_boxes: true`.
   - Blind repeats (≈ 10%) are re-inserted under fresh item ids at shuffled positions, with the mapping held only in the export's hidden block. Gold items are inserted the same way.
   - Gold mix: random, batch-matched and hard items (HITL-03). Gold answers come from an independent SME author, not the labelling operator, and are non-caption answers. Reuse the checks of `pilot_draw.GoldItem` (`scripts/eval_harness/pilot_draw.py:106-137`) rather than writing new ones.
   - Annotator-visible content carries no repeat or gold status. No visible text, label, attribute value or class name in the HTML contains `repeat`, `gold` or `blind`. The item header shows position and progress only. Repeat and gold roles are internal states of the export.
   - QC block: the queue file carries a `qc` block written before any import. It holds the delegated project policy from MCP 16734:
     - `gold_share` 0.10 and `repeat_fraction` 0.10;
     - per-field repeat percent-agreement floor 0.90;
     - per-field Cohen kappa floor 0.80;
     - per-annotator independent-gold accuracy floor 0.90;
     - `min_gold_decisions_per_annotator` 20 and `min_repeat_decisions_per_field` 20 (MCP 16736).
   - These are declared before any data. They are not accuracy guarantees, and alpha ≈ 0.8 guidance (HITL-05) is not a kappa equivalence. A `null` in any `qc` value still refuses import.
   - Keyboard map, as in the L1 screen of the task plan:
     - occluder keys: `m` mask, `s` sunglasses, `h` hand, `o` object, `x` mixed, `n` none, `?` cannot tell
     - `v` cycles region visibility (eyes, nose, mouth): visible, occluded, out-of-frame, uncertain
     - `a` adds a missed face (draw a box), `u` marks an unknown person
     - `Enter` next, `Esc` undo, export button
     - Every control is also reachable by Tab and has a visible label.
   - Shortcut and button parity: every shortcut key has a visible button with the same action. Tab reaches the button, Enter or Space activates it, and the result matches the key.
   - Focus: every focusable control shows a visible `:focus-visible` indicator. No `outline: none` without a replacement.
   - Draw mode (one mode at a time):
     - `a`, or its button, enters draw mode and shows a visible "drawing a box" banner.
     - While drawing, Enter (or its "Commit box" button) commits the box. Esc (or its "Cancel draw" button) cancels and restores the item unchanged.
     - Outside draw mode, Enter means next and Esc means undo.
     - `u` marks an unknown person as a face attribute. It never opens a second mode.
     - The banner disappears on leaving draw mode.
   - No timer advances or closes an item. Only Enter, skip or export moves the annotator on.
   - Skips are recorded as nonresponse, never dropped.
   - Exact-duplicate groups are labelled once and propagated on import.
   - Union-delta mode (`--union-delta <proposals.json>`): the queue shows only proposal boxes from candidate detectors that are unmatched to GT, source-blind and shuffled. Each item asks "face / not a face / cannot tell".
2. Importer (`fir_occ_labels.py`):
   - `load_label_export(path)` validates the export schema `fir-occ-labels/v1` and raises `FrameContractError` at load time [rg-008].
   - `to_face_instances(export, queue)` is the production importer and has no observation-bypass argument. It produces fir-occ-v1 rows with stable unit id, identity status, box, multi-label occluder set, region visibility and rule id. Each row keeps the annotator's pre-adjudication labels as they were exported, separately from any corrected label and its acceptance evidence.
   - `repeat_agreement(export)` gives per-field percent agreement and Cohen's kappa over the blind repeats, with the undefined-kappa handling below.
   - `gold_accuracy(export, gold)` gives per-annotator accuracy on known-answer items.
   - `union_delta_counts(export)` returns the inputs `union_adjudication.detector_gap_bound` expects.
   - **Undefined kappa.** Cohen's kappa is `(p_o − p_e) / (1 − p_e)`. When `p_e = 1` (both answers fall in one category across the field), the denominator is 0 and kappa is undefined. It returns `null` with reason `kappa_undefined`. It is never coerced to 0, 1 or a pass. Its field routes to SME adjudication. Percent agreement is still reported.
   - **Support floors.** A field with fewer than 20 repeat decisions returns `support_not_accrued`. An annotator with fewer than 20 gold decisions also returns `support_not_accrued`. Neither is a pass or a fail. Support is counted across the declared annotation run.
   - QC gate: evaluate the declared candidate export/run and its linked acceptance evidence. `to_face_instances` and the import are refused with `FrameContractError` when:
     - any `qc` value is null;
     - any support floor is unmet, so small batches can export but cannot import before support accrues;
     - any field agreement is below 0.90, any defined field kappa is below 0.80, or an undefined field kappa lacks the qualified SME resolution below;
     - any per-annotator gold accuracy is below 0.90.
   - A set that fails the gate is not imported as labels. Its routing:
     - **Repair list** (below-floor agreement, kappa or gold accuracy): preserve the failed set, diagnose the cause and repair under a versioned label/disagreement rule. Corrected labels are candidates, not automatically accepted on resubmission.
     - **SME list** (low-agreement, undefined-kappa, uncertain or eval-critical fields): routed to qualified SME adjudication ([HITL-07] SME adjudication escalation, Human-in-the-Loop ML). Repair may proceed alongside this review; disputed labels do not return to the worker pool as their final resolution.
     - The importer never deletes an annotator, drops labels or removes repeat items to raise agreement (HITL-05).
   - **Preservation.** Keep the original export, original answers and original QC results immutable, including support counts, failures and undefined metrics. Every repair or SME record references the item ids, original labels and prior export sha256. Corrected labels, reasons and their QC/disposition are separate records; no earlier answer or QC result is overwritten. This applies [MLDATA-03] Resolve label multiplicity in writing (Designing Machine Learning Systems).
   - **Resubmission and fresh QC.** A corrected export is a new version linked to the prior export sha256 and a new declared QC run. Freeze its scope, rule version, thresholds, support policy and validation assignment before evaluating it. An independent QC author supplies fresh known-answer gold (not repair examples or disclosed prior answers) and newly blinded repeat presentations; the evaluator is blinded to prior answers and outcomes. Evaluate corrected labels with that run's answers, not the old failed answers or edits to old repeats. Retain both runs and link each result to the exact candidate version. Accrue >=20 independent-gold decisions per evaluated annotator and >=20 repeat decisions per evaluated field within the new declared run, with the same 0.90 agreement, 0.80 defined-kappa and 0.90 gold-accuracy floors. Never carry forward old support as if it validated the correction or delete workers/items to reach a floor. The original failure remains historical evidence, not a permanent veto on a separately qualified corrected version ([HITL-03] Gold-embedded annotator QC; [HITL-05] Agreement is a diagnostic, not the truth; Human-in-the-Loop ML).
   - **Qualified SME resolution.** A resolution identifies the corrected candidate hash, item/field scope, expert, written disagreement rule, rationale and independent validation evidence. The SME is qualified by independent-gold accuracy >=0.90 on >=20 decisions in the declared validation run, not by title alone. Corrected fields still require >=20 blinded repeat decisions and agreement >=0.90; defined kappa must meet 0.80. For undefined kappa, retain `null`/`kappa_undefined` and record an explicit field-specific SME disposition supported by independent gold validation of the corrected field, with its method, denominator (>=20 decisions), accuracy (>=0.90), exceptions and limits declared. This resolves that diagnostic's inability to score the field; it never fabricates a passing kappa or waives missing support, failed numeric floors or observation evidence. Without the supported resolution, import stays blocked. Import cites the accepted version and new QC/SME evidence while keeping the original failed run inspectable.
   - **Multiplicity.** No set is called "gold" until the written label rule and disagreement rule exist (T-09, MLDATA-03).
   - Every row carries `annotation_tier` (`a` for occluder labels with missed-face additions; `b` for exhaustive pixel labelling). Tier-(a) rows are never counted as exhaustive.
   - Process observation is an operator task, not this lane's: [MEAS-29] Observe measurement production (Seeing with Fresh Eyes: Meaning, Space, Data, Truth, ch. 4). Before any real tier-(a) label feeds analysis, the operator observes a bounded sample of labelling in context and asks operators how values, exceptions and outliers are produced. The record states scope, method, exceptions, context and what the sample does and does not establish. One observation does not prove unbiased measurement.
   - The export carries `observation_ref` (string or null). Production import requires a nonempty reference to an available genuine observation record and a documented applicability assessment covering this export/run. Resolve the reference and validate the required record/context fields; a nonempty string alone is not evidence. Record validation does not itself prove a human observation occurred. The repository supplies no observation in this dispatch, and none is invented.
   - A real tier-(a) import with null, missing, unresolved or inapplicable observation evidence is always refused with `FrameContractError`, including after repair/SME resolution. Remove `allow_unobserved_fixture`; neither CLI nor production API exposes a generic override.
   - **Synthetic helper boundary.** Tests/tooling may use a separate `to_synthetic_face_instances(export, queue)` helper only for controlled generated numpy fixtures. Require `data_origin=generated_fixture`, an allowlisted generator id, fixed seed and generated-image sha256 for every queue item, bound to the export's queue hash and item ids. Regenerate the expected fixture pixels from that recipe and verify their hash; reject arbitrary image loaders, real source references and real, mixed or unknown-origin inputs. A caller flag or a relabelled real export is insufficient. Its output is fixture-only, persistently marked synthetic and `analysis_eligible=false`; production import and real-analysis consumers reject that output. It may leave `observation_ref=null` without asserting any human observation. All ordinary schema/QC checks remain, and the helper cannot turn the same real null-evidence tier-(a) import into an allowed one. These helper-only provenance fields do not add per-entry `annotation_mode` to persisted Golden manifests or upgrade tier-(a) to exhaustive (MCP 16763).
   - **Observation reuse.** Compare the observed and current measurement context: rule, instructions, operators, collection/adjudication workflow and relevant tool/UI behavior. Document changes and why the bounded record still covers how labels, exceptions and outliers are produced, with limits. A version-only or unrelated UI change does not automatically invalidate an applicable observation. A material change beyond its scope, or uncertain applicability, requires a new bounded observation before analysis; do not infer applicability from a matching version string alone.

## RED tests (synthetic numpy images only)

- The generator refuses `benchmarks/reports/q.html`.
- The generated HTML contains no `http://` or `https://` reference, no caption text from the queue file, and no detector box.
- With repeat fraction 0.10 on 50 items, exactly 5 repeats are inserted and reproducible from the seed.
- Import round-trip: a controlled synthetic export maps through the separate helper to fixture-only rows. A skip stays a nonresponse row. A duplicate group propagates. This is not production observation evidence.
- Kappa on a constructed export matches a hand-computed value.
- Undefined kappa: a field whose answers all fall in one category returns `kappa_undefined`, is not coerced to 0 or 1, and routes to the SME list.
- Support: 19 repeat decisions on a field returns `support_not_accrued`, and the import is refused. 20 decisions passes the support check only.
- Routing: a below-floor field goes to the repair list. An undefined-kappa field goes to the SME list. No annotator or label is removed. Pre-adjudication labels are preserved in the export and in both lists.
- Union-delta counts feed `detector_gap_bound` without error.
- The rendered HTML contains no `repeat`, `gold` or `blind` token in visible text, labels, attributes or class names.
- Import with any null `qc` value raises `FrameContractError`. An export with a repeat-agreement kappa below its floor is refused and its item ids go to the repair list.
- Planned production-boundary cases (documentation only): the same real tier-(a) export with `observation_ref=null` always raises `FrameContractError`; there is no production bypass argument. Missing/unresolved references or unsupported applicability also refuse. The synthetic helper rejects that real export and mixed/unknown-origin inputs; only bound generated fixtures can produce fixture-only output, which real-analysis consumers reject.
- Planned observation-reuse cases (documentation only): an unrelated version change with documented continuing applicability reuses the genuine record; a material measurement-context change or uncertain applicability blocks analysis pending a new bounded observation. No test fixture asserts that a real observation occurred.
- `to_face_instances` rows carry `annotation_tier`; a tier-(a) export never yields rows marked exhaustive.
- Planned, not yet written (documentation only):
  - Key parity: every keymap entry has a visible button, is in the Tab order, and produces the same export state when activated with Enter (and Space).
  - Focus: every focusable control has a visible `:focus-visible` indicator.
  - Draw mode: `a` enters draw mode and shows the banner. A second mode cannot open. Enter commits and Esc cancels, restoring the item. The button path matches the keys. The banner is absent outside draw mode.
  - No timer in the generated HTML changes an item.
  - Repair preserves the original answers, export and QC result. Corrected labels without fresh supported QC/qualified SME evidence stay blocked; fresh independently blinded QC can qualify a corrected version without rewriting the failed run. An undefined-kappa SME resolution remains null and carries its declared independent-gold support; deleting workers, changing old repeats or recycling old support cannot qualify it.

## Done when

Tests pass on the VM. This slice is tooling only: labelling itself is the operator's tier-(a) task. Real imports stay gated by a genuine observation reference and support floors, as in MCP 16734.
