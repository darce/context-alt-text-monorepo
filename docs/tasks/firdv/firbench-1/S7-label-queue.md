# S7 · Occlusion label queue generator and importer

- **Wave:** W3 batch B · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0
- **Owned paths:**
  - `benchmarks/tools/fir_occ_label_queue.py` (already allowlisted in `.gitignore`)
  - `apps/prototype-description-service/scripts/eval_harness/fir_occ_labels.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_fir_occ_labels.py`

## Goal

The operator labels real occlusion from pixels. Captions only choose what goes into the queue, never what the label is (MLDATA-03, HAI-11). The generator writes a private single-file HTML; the importer turns its export into fir-occ-v1 face-instance labels with quality checks (HITL-03).

## Read first

- Scope doc § "Real-occlusion ground truth" (queue sources, traps, effort tiers)
- `docs/assessments/current/fir-occlusion-corpus-and-metrics-2026-09-19.md` § annotation fields (the fir-occ-v1 field table)
- `benchmarks/tools/fir_corpus_population_draft_20260919.py` (style of a tracked generator that emits private files)
- The existing operator annotator is `benchmarks/tools/golden150-box-annotator.html`. It is local-only and is NOT on the VM. Its pattern: embedded images, `keydown` shortcuts, a download button for the export. Do not try to read it; this brief gives the behaviour.

## Build

1. Generator CLI: `python3 benchmarks/tools/fir_occ_label_queue.py --queue <private.json> --images <dir> --rule-id face-label-rule/v1 --repeat-fraction 0.10 --gold <private gold.json> --seed S --out benchmarks/private/fir-occ/queue-<stamp>.html`
   - The output path must pass `require_private_output_path`, or the CLI refuses.
   - Images are embedded as base64. No detector boxes, no captions, no model names appear in the HTML.
   - Existing confirmed GT boxes may be shown only when the queue entry carries `show_confirmed_boxes: true`.
   - Blind repeats (≈ 10%) are re-inserted under fresh item ids at shuffled positions, with the mapping held only in the export's hidden block. Gold items are inserted the same way.
   - Annotator-visible content carries no repeat or gold status. No visible text, label, attribute value or class name in the HTML contains `repeat`, `gold` or `blind`. The item header shows position and progress only. Repeat and gold roles are internal states of the export.
   - QC block: the queue file carries a `qc` block written before any import. It holds the gold share per queue, the per-field percent-agreement and kappa floors for blind repeats, and the per-annotator gold-accuracy floor. Each value is null until the operator sets it (task plan Open questions).
   - Gold composition and provenance: gold items are known-answer items whose answers come from an author independent of the labelling operator. Reuse the checks of `pilot_draw.GoldItem` (`scripts/eval_harness/pilot_draw.py:106-137`: independent SME authorship and non-caption answer source) rather than writing new ones.
   - Keyboard map, as in the L1 screen of the task plan:
     - occluder keys: `m` mask, `s` sunglasses, `h` hand, `o` object, `x` mixed, `n` none, `?` cannot tell
     - `v` cycles region visibility (eyes, nose, mouth): visible, occluded, out-of-frame, uncertain
     - `a` adds a missed face (draw a box), `u` marks an unknown person
     - `Enter` next, `Esc` undo, export button
     - Every control is also reachable by Tab and has a visible label.
   - Skips are recorded as nonresponse, never dropped.
   - Exact-duplicate groups are labelled once and propagated on import.
   - Union-delta mode (`--union-delta <proposals.json>`): the queue shows only proposal boxes from candidate detectors that are unmatched to GT, source-blind and shuffled. Each item asks "face / not a face / cannot tell".
2. Importer (`fir_occ_labels.py`):
   - `load_label_export(path)` validates the export schema `fir-occ-labels/v1` and raises `FrameContractError` at load time [rg-008].
   - `to_face_instances(export, queue)` produces fir-occ-v1 rows with stable unit id, identity status, box, multi-label occluder set, region visibility and rule id.
   - `repeat_agreement(export)` gives per-field percent agreement and Cohen's kappa over the blind repeats.
   - `gold_accuracy(export, gold)`.
   - `union_delta_counts(export)` returns the inputs `union_adjudication.detector_gap_bound` expects.
   - QC gate: `to_face_instances` and the import are refused with `FrameContractError` when any `qc` value is null, and when any field agreement, kappa or per-annotator gold accuracy is below its floor. A below-floor set is not imported as labels. Its item ids go to a repair list, and the annotator repairs and resubmits that set.
   - Every row carries `annotation_tier` (`a` for occluder labels with missed-face additions; `b` for exhaustive pixel labelling). Tier-(a) rows are never counted as exhaustive.
   - Process observation (MEAS-29) is an operator task, not this lane's: the operator observes a sample of tier-(a) labelling in context and records what the sample does and does not establish, before any tier-(a) label feeds analysis. The export carries `observation_ref` (string or null); the importer stores it and does not verify it.

## RED tests (synthetic numpy images only)

- The generator refuses `benchmarks/reports/q.html`.
- The generated HTML contains no `http://` or `https://` reference, no caption text from the queue file, and no detector box.
- With repeat fraction 0.10 on 50 items, exactly 5 repeats are inserted and reproducible from the seed.
- Import round-trip: a synthetic export maps to fir-occ-v1 rows. A skip stays a nonresponse row. A duplicate group propagates.
- Kappa on a constructed export matches a hand-computed value.
- Union-delta counts feed `detector_gap_bound` without error.
- The rendered HTML contains no `repeat`, `gold` or `blind` token in visible text, labels, attributes or class names.
- Import with any null `qc` value raises `FrameContractError`. An export with a repeat-agreement kappa below its floor is refused and its item ids go to the repair list.
- `to_face_instances` rows carry `annotation_tier`; a tier-(a) export never yields rows marked exhaustive.

## Done when

Tests pass on the VM. This slice is tooling only: labelling itself is the operator's tier-(a) task.
