#!/usr/bin/env python3
"""Permanent discrimination guard for license_policy tests (TEST-15 / BR-11 / BR-17).

Copies license_policy.py + test_license_policy.py into a scratch tree, applies
each known vacuity mutation, runs the suite, and classifies the outcome as
SURVIVED / KILLED / HARNESS-ERROR (never folds import/collection failures into
KILLED).

Green baseline is required first. A control mutation must SURVIVE to prove the
harness can report survivors. Defect mutations must be KILLED by at least one
named expected victim test.

Harness integrity (BR-49 / SECD-03 / SECD-05 / TEST-15):
  * Subprocess env is built from an explicit allowlist (not os.environ copy).
  * Results come from junitxml on disk, not stdout text parsing.
  * Every mutant run must execute the same number of testcases as baseline.

Mutations:
  CONTROL  inert comment (must SURVIVE — discrimination proof)
  M1  UNKNOWN_SPDX default-deny flipped to PASS
  M2  drop insightface family from NC_MODEL_IDS (verdict-flipping; B4b)
  M3  NC_MODEL_IDS = frozenset()
  M4  collapse _looks_like_research_source to exact frozenset membership
  M5  REQUIRED_MODEL_INGEST_DISPLAY_NAMES = ()  (suite must still hard-code names)
  M6  _synthetic_audit_targets: empty (source, derived) token loop
      (equivalent after GATE-11 floor clearance; expect_survived)
  M7  row-category ValueError handler → pass
  M8  research expand: drop unsplit compound forms (single site after B4b / BR-47)
  M9  audit_derived_from_model non-str guard → if False
  M10 disable has_generator_lineage synthetic routing branch
  M11 slash-component membership disabled (dataset/ffhq path hits)
  M12 get_model_ingest_entry primary raise → pass
  M13 PENDING-LEGAL-CLEARANCE SPDX branch → PASS (GATE-33)
  M14 _package_denylist_hit always returns None (GATE-34 / BR-51)
  M15 PENDING reason→UNKNOWN_SPDX (RF-02 reason-preserving; GATE-33)
  M16 denylist reason→UNREGISTERED_DERIVED_MODEL (RF-02; GATE-34)
  M17 unknown-category reason→UNKNOWN_SPDX (RF-02; M7 axis)
  M18 derived non-str reason→UNKNOWN_SPDX (RF-02; M9 axis)
  M19 PASS-path category leak on training_data (RF-01; GATE-27 pin)
  M20 force PASS→FAIL to pin GATE-32 pass-witness (RF-01)
  M21 denylist reason→RESEARCH_ONLY_SOURCE on BR-53 floor rows (RF-02)
  M22 research reason→DENYLISTED_LICENSE on BR-53 research rows (RF-02)
  M23 residual classify always legitimate (F11 A14-3 branch flip)
  M24 deny-reconstituting → legitimate (F11 A14-3 reconst flip)
  M25 unknown residual fail-closed default → legitimate (F11 A14-3)
  M26 B14-1 unbounded-defer residual deny steal skipped (F11 A14-3)

Also mediates a checked-in node-id baseline (subset: live ⊇ recorded),
reports per-mutant collateral (RF-03), strong-form victim attribution
(FIR-7-RV-07: non-smoke axis kills re-run with victims deselected), and
prints certification scope (RF-05).

FIR-7-A12-3 (Wave F9): ``audit_derived_from_model`` and ``audit_source``
share ``_audit_weights_lineage_token`` for the AGPL → NC membership →
research → NC-floor sequence. A source-door-only (or derived-door-only)
demotion of any branch is therefore **structurally impossible** — one
edit site feeds both doors. M16's derived-door reason-swap victims remain
sufficient; a parallel source-only mutant would be a no-op against the
shared helper.

Paths resolve from __file__ (never cwd) so this script runs as documented from
the repo root or from this directory (rg-006).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Resolve all inputs relative to this file — never the process cwd.
_HERE = Path(__file__).resolve().parent
_POLICY = _HERE / "license_policy.py"
_TEST = _HERE / "test_license_policy.py"
_TEST_HARDENING = _HERE / "test_license_policy_hardening.py"
_TEST_EQUIVALENCE = _HERE / "test_equivalence_claims.py"
# Node-id RF-01 floor covers these suite files (FIR-7-LR-03). Kill decisions
# still run against test_license_policy.py only (see SCOPE in main).
_FLOORED_TEST_FILES: tuple[Path, ...] = (
    _TEST,
    _TEST_HARDENING,
    _TEST_EQUIVALENCE,
)
# Checked-in node-id SET for RF-01 coverage mediation (subset semantics:
# live collect must be a superset of this fixture — coverage may grow, never
# shrink). Rewrite only via ``--record-baseline``.
_NODEID_BASELINE = _HERE / "mutation_guard_nodeid_baseline.txt"
# Live node-ids beyond the recorded floor are unprotected by the RF-01
# subset check. Growth requires a re-record of the baseline in the same
# commit that lands the new tests (FIR-7-LR-01).
MAX_LIVE_EXTRAS_TOLERANCE = 0
# Absolute count floor: live collect must not fall below this count.
# Editing both baseline copies in one commit must also edit this constant —
# a Python source diff a reviewer cannot miss (FIR-7-RV-05). Updated by
# --record-baseline to match the newly recorded set size.
ABSOLUTE_NODEID_FLOOR = 2350  # synced by --record-baseline; growth requires re-record
# Second, independent copy of the recorded node-id set for the embedded-baseline
# cross-check: an agent that edits the on-disk fixture alone is caught
# because this embedded set must still be a subset of the fixture.
# Bootstrap ONLY for --record-baseline drop accounting when the on-disk
# fixture is absent — never a runtime fallback (FIR-7-LR-02).
# Refresh both via: python mutation_guard.py --record-baseline
_EMBEDDED_NODEID_BASELINE: frozenset[str] = frozenset({
    'test_equivalence_claims.py::test_m6_grid_size_is_the_number_the_docstring_quotes',
    'test_equivalence_claims.py::test_m6_is_not_path_equivalent_one_layer_down',
    'test_equivalence_claims.py::test_m6_is_verdict_and_reason_equivalent_on_audit_provenance_row',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_dual_axis_rejects_both_doors_with_agpl_precedence[antelopev2_ultralytics]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_dual_axis_rejects_both_doors_with_agpl_precedence[arcface_ultralytics]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_dual_axis_rejects_both_doors_with_agpl_precedence[buffalo_l_ultralytics]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_dual_axis_rejects_both_doors_with_agpl_precedence[retinaface_yolov8]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_dual_axis_rejects_both_doors_with_agpl_precedence[yolo_nas_l_ultralytics]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_membership_path_dual_axis_agpl_precedence[arcface/yolov8]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_membership_path_dual_axis_agpl_precedence[buffalo_l/ultralytics]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_membership_path_dual_axis_agpl_precedence[ultralytics/buffalo_l]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_membership_path_dual_axis_agpl_precedence[yolop_arcface_ultralytics]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_membership_path_dual_axis_agpl_precedence[yolov8/arcface]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_membership_path_dual_axis_agpl_precedence[yolox_s_buffalo_l_ultralytics]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_nc_only_compounds_still_report_nc_model_derived[myprefix_antelopev2_trt]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_nc_only_compounds_still_report_nc_model_derived[org/buffalo_l]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_package_floor_still_sees_nc_axis[antelopev2_ultralytics]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_package_floor_still_sees_nc_axis[arcface_ultralytics]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_package_floor_still_sees_nc_axis[buffalo_l_ultralytics]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_package_floor_still_sees_nc_axis[retinaface_yolov8]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_package_floor_still_sees_nc_axis[yolo_nas_l_ultralytics]',
    'test_license_policy.py::TestA1001MultiAxisDoorPromotion::test_red_proof_cross_attributed_detail_fails_honesty_pin',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[hustvl_yolop]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[hustvl_yolos]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[hustvl_yolos_tiny]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[megvii_model_yolof]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[megvii_yolox]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[megvii_yolox_s]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[myyolo]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[ppyolo]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[ppyoloe]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[ppyolov2]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yolodummy]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yolof_r101]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yolof_r50]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yolop]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yolop_v3]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yolop_yolox]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yolopv2]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yolos-tiny]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yolos_base]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yolox_s]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yolox_yolop]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_exception_admit_pins_survive[yoloxs]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[YoloSeg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[checkpoints_yolo_free]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[checkpoints_yolo_seg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[checkpoints_yoloseg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[hub_yolo_x]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[org/yoloseg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[org_yolo_seg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[prefix_yoloseg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[repo_yolo_s_v8]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[weights_yolo_pose]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[yolo_free]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[yolo_pose]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[yolo_s]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[yolo_s_v8]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[yolo_seg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[yolo_x]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[yolofree]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[yolopose]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[yoloseg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[yoloseg_v8]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny[yolosg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[YoloSeg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[checkpoints_yolo_free]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[checkpoints_yolo_seg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[checkpoints_yoloseg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[hub_yolo_x]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[org/yoloseg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[org_yolo_seg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[prefix_yoloseg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[repo_yolo_s_v8]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[weights_yolo_pose]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[yolo_free]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[yolo_pose]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[yolo_s]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[yolo_s_v8]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[yolo_seg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[yolo_x]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[yolofree]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[yolopose]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[yoloseg]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[yoloseg_v8]',
    'test_license_policy.py::TestA1002DenyFirstOrdering::test_ultralytics_artifact_forms_deny_on_training_data_row[yolosg]',
    'test_license_policy.py::TestA123SharedWeightsDoorHelper::test_doors_agree_on_dual_axis_and_nc_only',
    'test_license_policy.py::TestA123SharedWeightsDoorHelper::test_helper_exists_and_both_doors_call_it',
    'test_license_policy.py::TestA301ToolingScalarDenylistFold::test_tooling_scalar_denylisted_package[ultralytics-yolo]',
    'test_license_policy.py::TestA301ToolingScalarDenylistFold::test_tooling_scalar_denylisted_package[yolo-v8]',
    'test_license_policy.py::TestA301ToolingScalarDenylistFold::test_tooling_scalar_denylisted_package[yolo_v8]',
    'test_license_policy.py::TestA301ToolingScalarDenylistFold::test_tooling_scalar_denylisted_package[yolov8]',
    'test_license_policy.py::TestA602ComponentSplitFirst::test_mixed_path_deny_component_wins[ultralytics/yolox]',
    'test_license_policy.py::TestA602ComponentSplitFirst::test_mixed_path_deny_component_wins[yolox/ultralytics]',
    'test_license_policy.py::TestA602ComponentSplitFirst::test_pypi_yolov5_still_denies',
    'test_license_policy.py::TestA602ComponentSplitFirst::test_yolo_nas_path_components_deny_nc_weights[deci/yolo-nas-l]',
    'test_license_policy.py::TestA602ComponentSplitFirst::test_yolo_nas_path_components_deny_nc_weights[yolo-nas/yolo-nas-l]',
    'test_license_policy.py::TestA602ComponentSplitFirst::test_yolo_nas_path_components_deny_nc_weights[yolo_nas/weights]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_red_proof_yolo_nas_deny_entry',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[tooling-YOLO-NAS]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[tooling-yolo-nas-s-seg]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[tooling-yolo-nas-s]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[tooling-yolo-nas]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[tooling-yolo_nas]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[tooling-yolo_nas_s]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[tooling-yolonas]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[training_data-YOLO-NAS]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[training_data-yolo-nas-s-seg]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[training_data-yolo-nas-s]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[training_data-yolo-nas]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[training_data-yolo_nas]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[training_data-yolo_nas_s]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_denies_on_row_doors[training_data-yolonas]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_nc_weights_denies[YOLO-NAS]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_nc_weights_denies[yolo-nas-s-seg]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_nc_weights_denies[yolo-nas-s]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_nc_weights_denies[yolo-nas]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_nc_weights_denies[yolo_nas]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_nc_weights_denies[yolo_nas_s]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_nc_weights_denies[yolonas]',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolo_nas_not_on_exception_allowlist',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolof_note_is_megvii_model_mit',
    'test_license_policy.py::TestA603YoloNasNcWeightsAndYolofNote::test_yolos_note_still_hustvl',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_red_proof_yolo_nas_m_pin',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_derived_from_model[yolo_nas_l]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_derived_from_model[yolo_nas_m]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_derived_from_model[yolo_nas_pose_l]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_derived_from_model[yolo_nas_pose_m]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_derived_from_model[yolo_nas_pose_n]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_derived_from_model[yolo_nas_pose_s]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_derived_from_model[yolo_nas_s]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_derived_from_model[yolonas_l]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_derived_from_model[yolonas_m]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_derived_from_model[yolonas_pose_l]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_derived_from_model[yolonas_s]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_source[yolo_nas_l]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_source[yolo_nas_m]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_source[yolo_nas_pose_l]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_source[yolo_nas_pose_m]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_source[yolo_nas_pose_n]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_source[yolo_nas_pose_s]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_source[yolo_nas_s]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_source[yolonas_l]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_source[yolonas_m]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_source[yolonas_pose_l]',
    'test_license_policy.py::TestA701YoloNasVariantNcPins::test_yolo_nas_variant_rejects_source[yolonas_s]',
    'test_license_policy.py::TestA804NcDetailNoteCleanup::test_no_redundant_yolo_nas_variant_note_keys',
    'test_license_policy.py::TestA804NcDetailNoteCleanup::test_vec2face_detail_names_lineage',
    'test_license_policy.py::TestA804NcDetailNoteCleanup::test_yolo_nas_variant_uses_prefix_note',
    'test_license_policy.py::TestA901FlagIndependence::test_each_flag_flip_alone_changes_a_pinned_outcome',
    'test_license_policy.py::TestA901FlagIndependence::test_no_generalized_suffix_flag_remains',
    'test_license_policy.py::TestApacheSelfGeneratedPasses::test_apache_self_generated_row_passes',
    'test_license_policy.py::TestApacheSelfGeneratedPasses::test_apache_spdx_allowlisted',
    'test_license_policy.py::TestApacheSelfGeneratedPasses::test_operator_cleared_is_not_spdx_pass',
    'test_license_policy.py::TestApacheSelfGeneratedPasses::test_operator_cleared_row_fails',
    'test_license_policy.py::TestApacheSelfGeneratedPasses::test_self_generated_is_not_an_spdx_pass',
    'test_license_policy.py::TestApacheSelfGeneratedPasses::test_spdx_case_insensitive_allow',
    'test_license_policy.py::TestApacheSelfGeneratedPasses::test_spdx_case_insensitive_denylist',
    'test_license_policy.py::TestApacheSelfGeneratedPasses::test_unknown_spdx_default_deny',
    'test_license_policy.py::TestB1001DerivedNcFloorSurface::test_anti_drift_full_generator_input_floor_sweep',
    'test_license_policy.py::TestB1001DerivedNcFloorSurface::test_bare_buffalo_excluded_from_floor',
    'test_license_policy.py::TestB1001DerivedNcFloorSurface::test_cosface_magface_deliberately_excluded',
    'test_license_policy.py::TestB1001DerivedNcFloorSurface::test_measured_admits_now_fail_closed_on_rows_and_doors[antelope_v2_int8]',
    'test_license_policy.py::TestB1001DerivedNcFloorSurface::test_measured_admits_now_fail_closed_on_rows_and_doors[buffalo_int8]',
    'test_license_policy.py::TestB1001DerivedNcFloorSurface::test_measured_admits_now_fail_closed_on_rows_and_doors[buffalo_l2_trt]',
    'test_license_policy.py::TestB1001DerivedNcFloorSurface::test_measured_admits_now_fail_closed_on_rows_and_doors[buffalo_trt]',
    'test_license_policy.py::TestB1001DerivedNcFloorSurface::test_measured_admits_now_fail_closed_on_rows_and_doors[myprefix_antelope_v2_int8]',
    'test_license_policy.py::TestB1001DerivedNcFloorSurface::test_measured_admits_now_fail_closed_on_rows_and_doors[myprefix_buffalo_l2_trt]',
    'test_license_policy.py::TestB1001DerivedNcFloorSurface::test_measured_admits_now_fail_closed_on_rows_and_doors[org_buffalo_l2_int8]',
    'test_license_policy.py::TestB1003MembershipOutranksCoveringGate::test_br28_counter_pins_still_admit_on_doors[buffalo_bill_detector]',
    'test_license_policy.py::TestB1003MembershipOutranksCoveringGate::test_br28_counter_pins_still_admit_on_doors[not-insightface]',
    'test_license_policy.py::TestB1003MembershipOutranksCoveringGate::test_br28_counter_pins_still_admit_on_doors[not_insightface]',
    'test_license_policy.py::TestB1003MembershipOutranksCoveringGate::test_br28_counter_pins_still_admit_on_doors[notdcface/x]',
    'test_license_policy.py::TestB1003MembershipOutranksCoveringGate::test_compact_head_membership_rejects_both_doors[buffalol2]',
    'test_license_policy.py::TestB1003MembershipOutranksCoveringGate::test_compact_head_membership_rejects_both_doors[buffalol2_trt]',
    'test_license_policy.py::TestB1003MembershipOutranksCoveringGate::test_compact_head_membership_rejects_both_doors[yolonas_int8]',
    'test_license_policy.py::TestB1003MembershipOutranksCoveringGate::test_compact_head_membership_rejects_both_doors[yolonas_onnx]',
    'test_license_policy.py::TestB1003MembershipOutranksCoveringGate::test_compact_head_membership_rejects_both_doors[yolonasl]',
    'test_license_policy.py::TestB1003MembershipOutranksCoveringGate::test_compact_head_membership_rejects_both_doors[yolonasl_trt]',
    'test_license_policy.py::TestB1004DoorPromotionShapes::test_c_shaped_door_promotion_via_monkeypatch',
    'test_license_policy.py::TestB1004DoorPromotionShapes::test_multi_segment_under_junk_prefix_rejects_rows_and_doors[myprefix_arcface_glint360k_r100]',
    'test_license_policy.py::TestB1004DoorPromotionShapes::test_multi_segment_under_junk_prefix_rejects_rows_and_doors[myprefix_buffalo_l2]',
    'test_license_policy.py::TestB1004DoorPromotionShapes::test_multi_segment_under_junk_prefix_rejects_rows_and_doors[myprefix_yolo_nas_l]',
    'test_license_policy.py::TestB1004DoorPromotionShapes::test_multi_segment_under_junk_prefix_rejects_rows_and_doors[myprefix_yolo_nas_pose_l]',
    'test_license_policy.py::TestB1004DoorPromotionShapes::test_not_insightface_door_admit_is_deliberate',
    'test_license_policy.py::TestB1004DoorPromotionShapes::test_tag_flood_seven_tags_rejects_rows_and_doors',
    'test_license_policy.py::TestB1005ScrfdNcSurface::test_scrfd_rejects_rows_and_doors[myprefix_scrfd_10g_kps]',
    'test_license_policy.py::TestB1005ScrfdNcSurface::test_scrfd_rejects_rows_and_doors[scrfd]',
    'test_license_policy.py::TestB1005ScrfdNcSurface::test_scrfd_rejects_rows_and_doors[scrfd_10g_kps]',
    'test_license_policy.py::TestB1005ScrfdNcSurface::test_scrfd_rejects_rows_and_doors[scrfd_2.5g]',
    'test_license_policy.py::TestB1104StructuralNcFlagDoorSolePath::test_red_proof_flag_alone_admits_sole_path',
    'test_license_policy.py::TestB1104StructuralNcFlagDoorSolePath::test_sole_path_rejects_only_via_structural_membership[yolo_nas_l_blah]',
    'test_license_policy.py::TestB1104StructuralNcFlagDoorSolePath::test_sole_path_rejects_only_via_structural_membership[yolo_nas_l_free]',
    'test_license_policy.py::TestB1105CompactMembershipNoteParity::test_compact_and_underscore_note_parity[arcfaceglint360kr100-arcface_glint360k_r100]',
    'test_license_policy.py::TestB1105CompactMembershipNoteParity::test_compact_and_underscore_note_parity[scrfd10gkps-scrfd_10g_kps]',
    'test_license_policy.py::TestB1105CompactMembershipNoteParity::test_compact_and_underscore_note_parity[yolonasposel-yolo_nas_pose_l]',
    'test_license_policy.py::TestB1106InsightfaceNoteWording::test_buffalo_l_keeps_historical_buffalo_wording',
    'test_license_policy.py::TestB1106InsightfaceNoteWording::test_insightface_note_names_model_zoo_not_buffalo_pack',
    'test_license_policy.py::TestB121ElevatedDenyCompactCloser::test_deny_has_folded_ab_claim_load_bearing_for_yolo_x',
    'test_license_policy.py::TestB121ElevatedDenyCompactCloser::test_elevated_deny_c_hits_pure_deny_compact',
    'test_license_policy.py::TestB121ElevatedDenyCompactCloser::test_red_proof_elevated_c_alone_turns_pure_deny_pins_red',
    'test_license_policy.py::TestB121ElevatedDenyCompactCloser::test_red_proof_residual_classify_alone_turns_debris_pins_red',
    'test_license_policy.py::TestB121ElevatedDenyCompactCloser::test_residual_classify_owns_exception_debris',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[hustvl_yolos]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[hustvl_yolos_tiny]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[megvii_yolox_s]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[myyolo]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[ppyolo]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[ppyoloe]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[ppyolov2]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[yolodummy]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[yolof_r101]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[yolof_r50]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[yolop]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[yolop_v3]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[yolopv2]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[yolos-tiny]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[yolos_base]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_admit_pins_survive_reconstitution[yolos_small]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_full_row_and_doors_deny_separator_twins',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_separator_twins_deny[checkpoints_yolos_eg]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_separator_twins_deny[hustvl_yolos_eg]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_separator_twins_deny[megvii_yolos_eg]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_separator_twins_deny[yolof_ree]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_separator_twins_deny[yolop_ose]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_separator_twins_deny[yolos_eg]',
    'test_license_policy.py::TestB122SeparatorTwinReconstitution::test_separator_twins_deny[yolos_eg_v8]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[org/yolosv8]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[weights_yolosv8]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[yolofv2]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[yolopv8]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[yolos0g]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[yolos1eg]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[yolos8]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[yolos_v8]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[yoloseg1]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[yolosv8]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[yoloxs2]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_digit_laundering_denies[yoloxv8]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_no_global_digit_wildcard',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_real_family_tags_admit[hustvl/yolos-small]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_real_family_tags_admit[ppyoloe]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_real_family_tags_admit[yolof_r50]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_real_family_tags_admit[yolopv2]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_real_family_tags_admit[yolos-tiny]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_real_family_tags_admit[yolos_base]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_real_family_tags_admit[yolox_darknet]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_real_family_tags_admit[yolox_nano]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_real_family_tags_admit[yolox_s]',
    'test_license_policy.py::TestB123PerFamilyCompactTags::test_real_family_tags_admit[yoloxs]',
    'test_license_policy.py::TestB124YolosSizeLetterTwins::test_family_compact_tag_table_pin',
    'test_license_policy.py::TestB124YolosSizeLetterTwins::test_yolos_letter_twins_deny[yolos_x]',
    'test_license_policy.py::TestB124YolosSizeLetterTwins::test_yolos_letter_twins_deny[yolosb]',
    'test_license_policy.py::TestB124YolosSizeLetterTwins::test_yolos_letter_twins_deny[yolose]',
    'test_license_policy.py::TestB124YolosSizeLetterTwins::test_yolos_letter_twins_deny[yolosl]',
    'test_license_policy.py::TestB124YolosSizeLetterTwins::test_yolos_letter_twins_deny[yolosm]',
    'test_license_policy.py::TestB124YolosSizeLetterTwins::test_yolos_letter_twins_deny[yolosn]',
    'test_license_policy.py::TestB124YolosSizeLetterTwins::test_yolos_letter_twins_deny[yolost]',
    'test_license_policy.py::TestB124YolosSizeLetterTwins::test_yolos_letter_twins_deny[yolosx]',
    'test_license_policy.py::TestB124YolosSizeLetterTwins::test_yoloxs_real_size_admits',
    'test_license_policy.py::TestB125CarveOutTest15Debts::test_causal_free_in_shield_admits_exception_residual',
    'test_license_policy.py::TestB125CarveOutTest15Debts::test_free_and_blah_outside_nc_trailing_shield_tags',
    'test_license_policy.py::TestB125CarveOutTest15Debts::test_red_proof_elevated_c_flag_is_load_bearing',
    'test_license_policy.py::TestB125CarveOutTest15Debts::test_red_proof_residual_classify_flag_is_load_bearing',
    'test_license_policy.py::TestB126AgplAdjacentGluePrefix::test_bare_buffalo_l_stays_nc_model_derived',
    'test_license_policy.py::TestB126AgplAdjacentGluePrefix::test_exact_ultralytics_buffalo_still_agpl_precedence',
    'test_license_policy.py::TestB126AgplAdjacentGluePrefix::test_red_proof_compact_prefix_glue_flag',
    'test_license_policy.py::TestB126AgplAdjacentGluePrefix::test_ultralyticsplus_buffalo_l_agpl_precedence',
    'test_license_policy.py::TestB126AgplAdjacentGluePrefix::test_ultralyticsplus_denies_agpl',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[model_ingest-bytes]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[model_ingest-dict]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[model_ingest-empty-list]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[model_ingest-false]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[model_ingest-list]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[model_ingest-none]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[model_ingest-true]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[model_ingest-zero]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[occluder_asset-bytes]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[occluder_asset-dict]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[occluder_asset-empty-list]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[occluder_asset-false]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[occluder_asset-list]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[occluder_asset-none]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[occluder_asset-true]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[occluder_asset-zero]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[synthetic_source-bytes]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[synthetic_source-dict]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[synthetic_source-empty-list]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[synthetic_source-false]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[synthetic_source-list]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[synthetic_source-none]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[synthetic_source-true]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[synthetic_source-zero]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[tooling-bytes]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[tooling-dict]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[tooling-empty-list]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[tooling-false]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[tooling-list]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[tooling-none]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[tooling-true]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[tooling-zero]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[training_data-bytes]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[training_data-dict]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[training_data-empty-list]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[training_data-false]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[training_data-list]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[training_data-none]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[training_data-true]',
    'test_license_policy.py::TestB201PackageIdentityNonStringFailClosed::test_non_string_package_invalid_row_every_door[training_data-zero]',
    'test_license_policy.py::TestB202PackageIdentityKeyAliasNormalisation::test_alias_key_with_denylisted_value_fails[Model-Id]',
    'test_license_policy.py::TestB202PackageIdentityKeyAliasNormalisation::test_alias_key_with_denylisted_value_fails[PACKAGE]',
    'test_license_policy.py::TestB202PackageIdentityKeyAliasNormalisation::test_alias_key_with_denylisted_value_fails[Package]',
    'test_license_policy.py::TestB202PackageIdentityKeyAliasNormalisation::test_alias_key_with_denylisted_value_fails[package_Name]',
    'test_license_policy.py::TestB202PackageIdentityKeyAliasNormalisation::test_disagreeing_package_alias_is_invalid_row',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[fastsam]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[ultralytics-yolo]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo-11]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo-v10]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo-v3]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo-v5]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo-v6]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo-v7]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo-v8]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo-v9]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo-world]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo11]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo12]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo_11]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo_v10]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo_v3]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo_v5]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo_v6]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo_v7]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo_v8]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo_v9]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolo_world]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov10]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov11]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov3]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov5]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov6]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov7]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov8]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov8l]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov8m]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov8n]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov8s]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov8x]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_family_token_fails_package_floor[yolov9]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_substring_adjacent_tokens_do_not_hit[myyolo]',
    'test_license_policy.py::TestB203UltralyticsAgplFamilyDenylistVocabulary::test_substring_adjacent_tokens_do_not_hit[yolodummy]',
    'test_license_policy.py::TestB206SpdxExpressionEmptyComponentFailClosed::test_empty_component_expressions_fail_closed[() OR MIT]',
    'test_license_policy.py::TestB206SpdxExpressionEmptyComponentFailClosed::test_empty_component_expressions_fail_closed[MIT AND]',
    'test_license_policy.py::TestB206SpdxExpressionEmptyComponentFailClosed::test_empty_component_expressions_fail_closed[MIT OR ()]',
    'test_license_policy.py::TestB302HonestLineageNotes::test_yolov10_is_thumig_fail_closed',
    'test_license_policy.py::TestB302HonestLineageNotes::test_yolov3_is_darknet_fail_closed',
    'test_license_policy.py::TestB302HonestLineageNotes::test_yolov6_is_meituan_gpl',
    'test_license_policy.py::TestB302HonestLineageNotes::test_yolov7_is_wongkinyiu_gpl',
    'test_license_policy.py::TestB304A302SpdxExpressionHygieneCompleteness::test_unbalanced_parens_fail_expression_hygiene[close-only]',
    'test_license_policy.py::TestB304A302SpdxExpressionHygieneCompleteness::test_unbalanced_parens_fail_expression_hygiene[open-only]',
    'test_license_policy.py::TestB304A302SpdxExpressionHygieneCompleteness::test_unbalanced_parens_fail_expression_hygiene[reversed]',
    'test_license_policy.py::TestB304A302SpdxExpressionHygieneCompleteness::test_unicode_dash_fails_expression_hygiene[em-dash]',
    'test_license_policy.py::TestB304A302SpdxExpressionHygieneCompleteness::test_unicode_dash_fails_expression_hygiene[en-dash-id]',
    'test_license_policy.py::TestB304A302SpdxExpressionHygieneCompleteness::test_unicode_dash_fails_expression_hygiene[en-dash-or]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_model_ingest_scalar_confusable_invalid_row[en_dash]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_model_ingest_scalar_confusable_invalid_row[greek_omicron]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_model_ingest_scalar_confusable_invalid_row[unicode_hyphen]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[tooling-model_id-en_dash]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[tooling-model_id-greek_omicron]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[tooling-model_id-unicode_hyphen]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[tooling-package-en_dash]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[tooling-package-greek_omicron]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[tooling-package-unicode_hyphen]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[tooling-package_name-en_dash]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[tooling-package_name-greek_omicron]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[tooling-package_name-unicode_hyphen]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[training_data-model_id-en_dash]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[training_data-model_id-greek_omicron]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[training_data-model_id-unicode_hyphen]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[training_data-package-en_dash]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[training_data-package-greek_omicron]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[training_data-package-unicode_hyphen]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[training_data-package_name-en_dash]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[training_data-package_name-greek_omicron]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_row_confusable_package_identity_invalid_row[training_data-package_name-unicode_hyphen]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_tooling_scalar_confusable_invalid_row[en_dash]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_tooling_scalar_confusable_invalid_row[greek_omicron]',
    'test_license_policy.py::TestB401PackageIdentityCanonicalNoneFailClosed::test_tooling_scalar_confusable_invalid_row[unicode_hyphen]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_deny_and_exception_seed_sets_are_disjoint',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_exception_family_admits[yolof]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_exception_family_admits[yolof_r50]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_exception_family_admits[yolop]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_exception_family_admits[yolopv2]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_exception_family_admits[yolos-tiny]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_exception_family_admits[yolos]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_exception_family_admits[yolox]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_exception_family_admits[yolox_s]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[tooling-YOLOv9T-SEG]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[tooling-yolo11n-pose]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[tooling-yolo11n_pose]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[tooling-yolov8nn-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[tooling-yolov9c-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[tooling-yolov9e-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[tooling-yolov9t-seg.pt]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[tooling-yolov9t-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[training_data-YOLOv9T-SEG]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[training_data-yolo11n-pose]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[training_data-yolo11n_pose]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[training_data-yolov8nn-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[training_data-yolov9c-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[training_data-yolov9e-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[training_data-yolov9t-seg.pt]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_row_doors[training_data-yolov9t-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_scalar_doors[YOLOv9T-SEG]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_scalar_doors[yolo11n-pose]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_scalar_doors[yolo11n_pose]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_scalar_doors[yolov8nn-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_scalar_doors[yolov9c-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_scalar_doors[yolov9e-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_scalar_doors[yolov9t-seg.pt]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_head_segment_denylisted_on_scalar_doors[yolov9t-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_red_proof_boundary_prefix_branch',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_red_proof_compact_remainder_branch',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_red_proof_head_segment_branch',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_admit_counterexamples[myyolo-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_admit_counterexamples[myyolo]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_admit_counterexamples[numba-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_admit_counterexamples[numba]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_admit_counterexamples[sam]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_admit_counterexamples[timm]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_admit_counterexamples[yolodummy-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_admit_counterexamples[yolodummy]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[YOLOv9T-SEG]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[YOLOv9T]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[fastsamx.pt]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[fastsamx]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolo-world-s]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolo-worldv2-s]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolo11n-pose]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolo11n]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolo11n_pose]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolo11s]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolo12n]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolo_worldv2_s]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolor]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolor_s]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov3_tiny]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov5n6]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov5n]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov5nu]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov5s6]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov7_tiny]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8l-obb]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8m-pose]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8n-oiv7]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8n-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8n.engine]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8n_engine]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8n_mlpackage]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8n_oiv7]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8n_p2]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8n_p6]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8n_torchscript]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8n_world]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8nn-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8nn]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8s-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8s_worldv2]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov8x-cls]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov9_e]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov9_t]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov9c-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov9c]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov9e-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov9e]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov9t-seg.pt]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov9t-seg]',
    'test_license_policy.py::TestB501StructuralFamilyBoundary::test_structural_family_token_denylisted_package[yolov9t]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_model_ingest_scalar_format_only_invalid_row[bom]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_model_ingest_scalar_format_only_invalid_row[word_joiner]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_model_ingest_scalar_format_only_invalid_row[zwsp]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_red_proof_empty_canonical_floor_skip',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[tooling-model_id-bom]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[tooling-model_id-word_joiner]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[tooling-model_id-zwsp]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[tooling-package-bom]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[tooling-package-word_joiner]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[tooling-package-zwsp]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[tooling-package_name-bom]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[tooling-package_name-word_joiner]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[tooling-package_name-zwsp]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[training_data-model_id-bom]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[training_data-model_id-word_joiner]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[training_data-model_id-zwsp]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[training_data-package-bom]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[training_data-package-word_joiner]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[training_data-package-zwsp]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[training_data-package_name-bom]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[training_data-package_name-word_joiner]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_row_format_only_package_identity_invalid_row[training_data-package_name-zwsp]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_tooling_scalar_format_only_invalid_row[bom]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_tooling_scalar_format_only_invalid_row[word_joiner]',
    'test_license_policy.py::TestB504PackageIdentityCanonicalEmptyFailClosed::test_tooling_scalar_format_only_invalid_row[zwsp]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_exception_and_counterexample_admit_pins[myyolo]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_exception_and_counterexample_admit_pins[yolodummy]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_exception_and_counterexample_admit_pins[yolof]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_exception_and_counterexample_admit_pins[yolof_r50]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_exception_and_counterexample_admit_pins[yolop]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_exception_and_counterexample_admit_pins[yolopv2]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_exception_and_counterexample_admit_pins[yolos-tiny]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_exception_and_counterexample_admit_pins[yolos]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_exception_and_counterexample_admit_pins[yolox]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_exception_and_counterexample_admit_pins[yolox_s]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_red_proof_exception_residual_rescan',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_agpl_witness_is_denylisted_package[vendor/yolox_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_agpl_witness_is_denylisted_package[yolos-yolov5]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_agpl_witness_is_denylisted_package[yolos_yolov8]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_agpl_witness_is_denylisted_package[yolox-ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_agpl_witness_is_denylisted_package[yolox-yolov8]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_agpl_witness_is_denylisted_package[yolox_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_agpl_witness_is_denylisted_package[yolox_ultralytics_port]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_agpl_witness_is_denylisted_package[yolox_yolov8_distill]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[tooling-vendor/yolox_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[tooling-yolo-nas-yolov8-distill]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[tooling-yolo_nas_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[tooling-yolos-yolov5]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[tooling-yolos_yolov8]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[tooling-yolox-ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[tooling-yolox-yolov8]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[tooling-yolox_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[tooling-yolox_ultralytics_port]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[tooling-yolox_yolov8_distill]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[training_data-vendor/yolox_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[training_data-yolo-nas-yolov8-distill]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[training_data-yolo_nas_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[training_data-yolos-yolov5]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[training_data-yolos_yolov8]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[training_data-yolox-ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[training_data-yolox-yolov8]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[training_data-yolox_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[training_data-yolox_ultralytics_port]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_row_doors[training_data-yolox_yolov8_distill]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_scalar_doors[vendor/yolox_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_scalar_doors[yolo-nas-yolov8-distill]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_scalar_doors[yolo_nas_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_scalar_doors[yolos-yolov5]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_scalar_doors[yolos_yolov8]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_scalar_doors[yolox-ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_scalar_doors[yolox-yolov8]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_scalar_doors[yolox_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_scalar_doors[yolox_ultralytics_port]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_denylisted_on_scalar_doors[yolox_yolov8_distill]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_hits_package_denylist[vendor/yolox_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_hits_package_denylist[yolo-nas-yolov8-distill]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_hits_package_denylist[yolo_nas_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_hits_package_denylist[yolos-yolov5]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_hits_package_denylist[yolos_yolov8]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_hits_package_denylist[yolox-ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_hits_package_denylist[yolox-yolov8]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_hits_package_denylist[yolox_ultralytics]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_hits_package_denylist[yolox_ultralytics_port]',
    'test_license_policy.py::TestB601BoundedExceptionResidualRescan::test_residual_witness_hits_package_denylist[yolox_yolov8_distill]',
    'test_license_policy.py::TestB602HonestLineageYolopDarknet::test_darknet_era_own_deny_entry[YOLOv4-yolov4]',
    'test_license_policy.py::TestB602HonestLineageYolopDarknet::test_darknet_era_own_deny_entry[yolo-v2-yolov2]',
    'test_license_policy.py::TestB602HonestLineageYolopDarknet::test_darknet_era_own_deny_entry[yolov2-yolov2]',
    'test_license_policy.py::TestB602HonestLineageYolopDarknet::test_darknet_era_own_deny_entry[yolov4-yolov4]',
    'test_license_policy.py::TestB602HonestLineageYolopDarknet::test_yolop_family_admits[yolop]',
    'test_license_policy.py::TestB602HonestLineageYolopDarknet::test_yolop_family_admits[yolopv2]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[myyolo]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[numba]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[sam]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[timm]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[yolodummy]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[yolof_r50]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[yolop]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[yolopv2]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[yolos-tiny]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[yolox]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[yolox_s]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_admit_pins_still_hold[yoloxs]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_double_exception_compounds_admit[yolop_yolox]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_double_exception_compounds_admit[yolox_yolop]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_red_proof_exception_residual_suffix_scan',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_agpl_witness_is_denylisted_package[vendor/yolox_s_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_agpl_witness_is_denylisted_package[yolof_r50_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_agpl_witness_is_denylisted_package[yolopv2_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_agpl_witness_is_denylisted_package[yolos_tiny_yolov8n]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_agpl_witness_is_denylisted_package[yolox_s_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_agpl_witness_is_denylisted_package[yolox_tiny_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_agpl_witness_is_denylisted_package[yoloxs_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_nc_witness_is_nc_model_derived[yolox_s_buffalo_l]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_nc_witness_is_nc_model_derived[yolox_s_yolo_nas]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[tooling-vendor/yolox_s_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[tooling-yolof_r50_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[tooling-yolopv2_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[tooling-yolos_tiny_yolov8n]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[tooling-yolox_s_buffalo_l]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[tooling-yolox_s_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[tooling-yolox_s_yolo_nas]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[tooling-yolox_tiny_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[tooling-yoloxs_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[training_data-vendor/yolox_s_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[training_data-yolof_r50_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[training_data-yolopv2_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[training_data-yolos_tiny_yolov8n]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[training_data-yolox_s_buffalo_l]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[training_data-yolox_s_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[training_data-yolox_s_yolo_nas]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[training_data-yolox_tiny_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_row_doors[training_data-yoloxs_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_scalar_doors[vendor/yolox_s_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_scalar_doors[yolof_r50_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_scalar_doors[yolopv2_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_scalar_doors[yolos_tiny_yolov8n]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_scalar_doors[yolox_s_buffalo_l]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_scalar_doors[yolox_s_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_scalar_doors[yolox_s_yolo_nas]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_scalar_doors[yolox_tiny_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_denies_on_scalar_doors[yoloxs_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_hits_package_denylist[vendor/yolox_s_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_hits_package_denylist[yolof_r50_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_hits_package_denylist[yolopv2_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_hits_package_denylist[yolos_tiny_yolov8n]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_hits_package_denylist[yolox_s_buffalo_l]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_hits_package_denylist[yolox_s_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_hits_package_denylist[yolox_s_yolo_nas]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_hits_package_denylist[yolox_tiny_ultralytics]',
    'test_license_policy.py::TestB701ResidualSuffixDenyScan::test_suffix_witness_hits_package_denylist[yoloxs_ultralytics]',
    'test_license_policy.py::TestB704PerEntryNcDetailText::test_buffalo_detail_keeps_historical_wording',
    'test_license_policy.py::TestB704PerEntryNcDetailText::test_nc_detail_names_own_lineage[buffalo_l-buffalo-must_not0]',
    'test_license_policy.py::TestB704PerEntryNcDetailText::test_nc_detail_names_own_lineage[buffalo_s-buffalo-must_not1]',
    'test_license_policy.py::TestB704PerEntryNcDetailText::test_nc_detail_names_own_lineage[insightface/buffalo_l-buffalo-must_not2]',
    'test_license_policy.py::TestB704PerEntryNcDetailText::test_nc_detail_names_own_lineage[yolo-nas-deci-must_not4]',
    'test_license_policy.py::TestB704PerEntryNcDetailText::test_nc_detail_names_own_lineage[yolo_nas-deci-must_not3]',
    'test_license_policy.py::TestB704PerEntryNcDetailText::test_nc_detail_names_own_lineage[yolo_nas_m-deci-must_not6]',
    'test_license_policy.py::TestB704PerEntryNcDetailText::test_nc_detail_names_own_lineage[yolonas-deci-must_not5]',
    'test_license_policy.py::TestB704PerEntryNcDetailText::test_red_proof_yolo_nas_detail_not_buffalo',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[hustvl_yolop]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[hustvl_yolos]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[megvii_model_yolof]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[megvii_yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[myyolo]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[numba]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[sam]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[timm]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[vendor/yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[yolodummy]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[yolof_r50]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[yolop]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[yolop_yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[yolopv2]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[yolos-tiny]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[yolox_s]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[yolox_yolop]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_admit_pins_still_hold[yoloxs]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_agpl_uniform_bypass_is_denylisted_package[yolos/tiny_yolov8n]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_agpl_uniform_bypass_is_denylisted_package[yolox/s_ultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_agpl_uniform_bypass_is_denylisted_package[yolox/tiny_ultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_agpl_uniform_bypass_is_denylisted_package[yolox_xultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_agpl_uniform_bypass_is_denylisted_package[yolox_xultralytics_yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_agpl_uniform_bypass_is_denylisted_package[yoloxsultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_agpl_uniform_bypass_is_denylisted_package[yoloxultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_deci_yolo_nas_l_still_denies_nc',
    'test_license_policy.py::TestB801UniformSuffixScan::test_myyolo_admits_under_compact_suffix_floor',
    'test_license_policy.py::TestB801UniformSuffixScan::test_nc_uniform_bypass_is_nc_model_derived[yolox/s_buffalo_l-buffalo_l]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_nc_uniform_bypass_is_nc_model_derived[yolox/s_yolo_nas-yolo_nas]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_red_proof_compact_suffix_rule_e',
    'test_license_policy.py::TestB801UniformSuffixScan::test_red_proof_outer_residual_suffix_scan',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[tooling-yolos/tiny_yolov8n]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[tooling-yolox/s_buffalo_l]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[tooling-yolox/s_ultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[tooling-yolox/s_yolo_nas]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[tooling-yolox/tiny_ultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[tooling-yolox_xultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[tooling-yolox_xultralytics_yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[tooling-yoloxsultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[tooling-yoloxultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[training_data-yolos/tiny_yolov8n]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[training_data-yolox/s_buffalo_l]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[training_data-yolox/s_ultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[training_data-yolox/s_yolo_nas]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[training_data-yolox/tiny_ultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[training_data-yolox_xultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[training_data-yolox_xultralytics_yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[training_data-yoloxsultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_row_doors[training_data-yoloxultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_scalar_doors[yolos/tiny_yolov8n]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_scalar_doors[yolox/s_buffalo_l]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_scalar_doors[yolox/s_ultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_scalar_doors[yolox/s_yolo_nas]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_scalar_doors[yolox/tiny_ultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_scalar_doors[yolox_xultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_scalar_doors[yolox_xultralytics_yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_scalar_doors[yoloxsultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_denies_on_scalar_doors[yoloxultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_hits_package_denylist[yolos/tiny_yolov8n]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_hits_package_denylist[yolox/s_buffalo_l]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_hits_package_denylist[yolox/s_ultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_hits_package_denylist[yolox/s_yolo_nas]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_hits_package_denylist[yolox/tiny_ultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_hits_package_denylist[yolox_xultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_hits_package_denylist[yolox_xultralytics_yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_hits_package_denylist[yoloxsultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_uniform_bypass_hits_package_denylist[yoloxultralytics]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_row_doors[tooling-hustvl_yolop]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_row_doors[tooling-hustvl_yolos]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_row_doors[tooling-megvii_model_yolof]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_row_doors[tooling-megvii_yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_row_doors[training_data-hustvl_yolop]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_row_doors[training_data-hustvl_yolos]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_row_doors[training_data-megvii_model_yolof]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_row_doors[training_data-megvii_yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_scalar_doors[hustvl_yolop]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_scalar_doors[hustvl_yolos]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_scalar_doors[megvii_model_yolof]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_on_scalar_doors[megvii_yolox]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_package_floor[hustvl_yolop]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_package_floor[hustvl_yolos]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_package_floor[megvii_model_yolof]',
    'test_license_policy.py::TestB801UniformSuffixScan::test_vendor_prefix_exception_admits_package_floor[megvii_yolox]',
    'test_license_policy.py::TestB802IterativeFailClosedBounds::test_deep_chain_denies_on_all_four_doors',
    'test_license_policy.py::TestB802IterativeFailClosedBounds::test_deep_chain_denies_without_recursion_error',
    'test_license_policy.py::TestB802IterativeFailClosedBounds::test_non_shrinking_strip_denies',
    'test_license_policy.py::TestB802IterativeFailClosedBounds::test_red_proof_fail_closed_bounds_neuter',
    'test_license_policy.py::TestB802IterativeFailClosedBounds::test_synthetic_overflow_bound_invariant_probe',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_row_doors[tooling-yolop_yolox_yolov8]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_row_doors[tooling-yolox_s_yolop_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_row_doors[tooling-yolox_yolop_s_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_row_doors[tooling-yolox_yolop_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_row_doors[training_data-yolop_yolox_yolov8]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_row_doors[training_data-yolox_s_yolop_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_row_doors[training_data-yolox_yolop_s_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_row_doors[training_data-yolox_yolop_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_scalar_doors[yolop_yolox_yolov8]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_scalar_doors[yolox_s_yolop_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_scalar_doors[yolox_yolop_s_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_denies_on_scalar_doors[yolox_yolop_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_hits_package_denylist[yolop_yolox_yolov8]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_hits_package_denylist[yolox_s_yolop_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_hits_package_denylist[yolox_yolop_s_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_multi_strip_hits_package_denylist[yolox_yolop_ultralytics]',
    'test_license_policy.py::TestB804MultiStripContinuationPins::test_red_proof_multi_strip_continuation',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[antelopev2_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[buffalo_l_int8]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[buffalo_l_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[insightface_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[vec2face_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[yolo_nas_l_coreml]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[yolo_nas_l_int8]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[yolo_nas_l_int8_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[yolo_nas_l_ncnn]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[yolo_nas_l_onnx]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[yolo_nas_l_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_derived_from_model[yolo_nas_pose_n_onnx]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[antelopev2_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[buffalo_l_int8]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[buffalo_l_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[insightface_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[vec2face_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[yolo_nas_l_coreml]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[yolo_nas_l_int8]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[yolo_nas_l_int8_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[yolo_nas_l_ncnn]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[yolo_nas_l_onnx]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[yolo_nas_l_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_export_tag_rejects_source[yolo_nas_pose_n_onnx]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_mixed_order_export_tags_reject_both_doors[buffalo_l_trt_int8]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_mixed_order_export_tags_reject_both_doors[yolo_nas_l_fp16_onnx_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_mixed_order_export_tags_reject_both_doors[yolo_nas_l_int8_trt]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_mixed_order_export_tags_reject_both_doors[yolo_nas_l_trt_int8]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_derived[blazeface_int8]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_derived[dcface/gen1]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_derived[mediapipe/blazeface]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_derived[notdcface/x]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_derived[sam]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_derived[sam_onnx]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_derived[timm]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_derived[yolox_s]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_source[blazeface_int8]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_source[dcface/gen1]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_source[mediapipe/blazeface]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_source[notdcface/x]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_source[sam]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_source[sam_onnx]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_source[timm]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_non_nc_counter_pins_pass_source[yolox_s]',
    'test_license_policy.py::TestB806StructuralNcDoors::test_red_proof_structural_nc_export_tag',
    'test_license_policy.py::TestB806StructuralNcDoors::test_three_tag_bound_does_not_over_admit_naked_nc',
    'test_license_policy.py::TestB807DerivedDoorResidualNcParity::test_derived_rejects_residual_nc_compound[yolox_s_buffalo_l]',
    'test_license_policy.py::TestB807DerivedDoorResidualNcParity::test_derived_rejects_residual_nc_compound[yolox_s_yolo_nas]',
    'test_license_policy.py::TestB807DerivedDoorResidualNcParity::test_tooling_ingest_still_nc_package_floor[yolox_s_buffalo_l]',
    'test_license_policy.py::TestB807DerivedDoorResidualNcParity::test_tooling_ingest_still_nc_package_floor[yolox_s_yolo_nas]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_buffalo_bill_admits_on_training_data_package_row',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_counter_pins_still_admit_on_weights_doors[blazeface_int8]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_counter_pins_still_admit_on_weights_doors[buffalo_bill_detector]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_counter_pins_still_admit_on_weights_doors[dcface/gen1]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_counter_pins_still_admit_on_weights_doors[mediapipe/blazeface]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_counter_pins_still_admit_on_weights_doors[not-insightface]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_counter_pins_still_admit_on_weights_doors[not_insightface]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_counter_pins_still_admit_on_weights_doors[notdcface/x]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_counter_pins_still_admit_on_weights_doors[sam]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_counter_pins_still_admit_on_weights_doors[sam_onnx]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_counter_pins_still_admit_on_weights_doors[timm]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_myarcface_compact_suffix_overblock_is_deliberate',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_new_floor_entry_note_names_own_lineage[antelopev2]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_new_floor_entry_note_names_own_lineage[arcface]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_new_floor_entry_note_names_own_lineage[buffalo_s]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_new_floor_entry_note_names_own_lineage[buffalo_sc]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_new_floor_entry_note_names_own_lineage[retinaface]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_new_floor_entry_note_names_own_lineage[vec2face]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_not_insightface_row_rejection_unchanged',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_hits_package_floor_and_whole_component[checkpoints_vec2face_trt]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_hits_package_floor_and_whole_component[myprefix_antelopev2]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_hits_package_floor_and_whole_component[myprefix_arcface]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_hits_package_floor_and_whole_component[myprefix_buffalo_s]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_hits_package_floor_and_whole_component[myprefix_buffalo_sc]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_hits_package_floor_and_whole_component[myprefix_retinaface]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_hits_package_floor_and_whole_component[myprefix_vec2face]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_hits_package_floor_and_whole_component[org_antelopev2_int8]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_training_data_row[checkpoints_vec2face_trt]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_training_data_row[myprefix_antelopev2]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_training_data_row[myprefix_arcface]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_training_data_row[myprefix_buffalo_s]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_training_data_row[myprefix_buffalo_sc]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_training_data_row[myprefix_retinaface]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_training_data_row[myprefix_vec2face]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_training_data_row[org_antelopev2_int8]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_weights_doors[checkpoints_vec2face_trt]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_weights_doors[myprefix_antelopev2]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_weights_doors[myprefix_arcface]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_weights_doors[myprefix_buffalo_s]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_weights_doors[myprefix_buffalo_sc]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_weights_doors[myprefix_retinaface]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_weights_doors[myprefix_vec2face]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_prefix_witness_rejects_weights_doors[org_antelopev2_int8]',
    'test_license_policy.py::TestB902PrefixShieldedNcFloor::test_red_proof_prefix_shield_component_suffix_flag',
    'test_license_policy.py::TestB903PpYoloHonestLineage::test_darknet_yolov2_still_denies_with_darknet_note[xyolov2]',
    'test_license_policy.py::TestB903PpYoloHonestLineage::test_darknet_yolov2_still_denies_with_darknet_note[yolov2]',
    'test_license_policy.py::TestB903PpYoloHonestLineage::test_darknet_yolov2_still_denies_with_darknet_note[yolov2_food]',
    'test_license_policy.py::TestB903PpYoloHonestLineage::test_pp_yolo_detail_not_darknet[ppyolo]',
    'test_license_policy.py::TestB903PpYoloHonestLineage::test_pp_yolo_detail_not_darknet[ppyoloe]',
    'test_license_policy.py::TestB903PpYoloHonestLineage::test_pp_yolo_detail_not_darknet[ppyolov2]',
    'test_license_policy.py::TestB903PpYoloHonestLineage::test_pp_yolo_family_admits[ppyolo]',
    'test_license_policy.py::TestB903PpYoloHonestLineage::test_pp_yolo_family_admits[ppyoloe]',
    'test_license_policy.py::TestB903PpYoloHonestLineage::test_pp_yolo_family_admits[ppyolov2]',
    'test_license_policy.py::TestBr38NcIngestDerivationAndHelpers::test_br38_nc_tagged_ingest_entry_joins_nc_model_ids',
    'test_license_policy.py::TestBr38NcIngestDerivationAndHelpers::test_br38_require_string_field_used_for_missing_derived',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[derived-None]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[derived-dict]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[derived-empty]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[derived-int]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[derived-list]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[ingest-None]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[ingest-dict]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[ingest-empty]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[ingest-int]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[ingest-list]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[source-None]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[source-dict]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[source-empty]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[source-int]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[source-list]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[spdx-None]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[spdx-dict]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[spdx-empty]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[spdx-int]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[spdx-list]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[synth-None]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[synth-dict]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[synth-empty]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[synth-int]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[synth-list]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[tooling-None]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[tooling-dict]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[tooling-empty]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[tooling-int]',
    'test_license_policy.py::TestBr46EntryPointTypeContract::test_br46_type_contract_table[tooling-list]',
    'test_license_policy.py::TestBr48NoDeadPrivateHelpers::test_br48_named_helpers_are_gone',
    'test_license_policy.py::TestBr48NoDeadPrivateHelpers::test_no_private_module_function_with_zero_load_refs',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_clearance_does_not_waive_license_floor[model_ingest]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_clearance_does_not_waive_license_floor[occluder_asset]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_clearance_does_not_waive_license_floor[synthetic_source]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_clearance_does_not_waive_license_floor[tooling]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_clearance_does_not_waive_license_floor[training_data]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_denylisted_license_rejected_by_every_door[model_ingest]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_denylisted_license_rejected_by_every_door[occluder_asset]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_denylisted_license_rejected_by_every_door[synthetic_source]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_denylisted_license_rejected_by_every_door[tooling]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_denylisted_license_rejected_by_every_door[training_data]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_legitimate_model_ingest_still_passes',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_license_floor_reason_is_exact',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_research_source_rejected_by_every_door[model_ingest]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_research_source_rejected_by_every_door[occluder_asset]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_research_source_rejected_by_every_door[synthetic_source]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_research_source_rejected_by_every_door[tooling]',
    'test_license_policy.py::TestBr53CategoryIndependentFloor::test_research_source_rejected_by_every_door[training_data]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_clean_source_still_passes_every_door_that_admits_it',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_confusable_nc_source_fails_closed_on_every_door[model_ingest]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_confusable_nc_source_fails_closed_on_every_door[occluder_asset]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_confusable_nc_source_fails_closed_on_every_door[tooling]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_confusable_nc_source_fails_closed_on_every_door[training_data]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_nc_source_reason_is_exact_on_every_door[model_ingest]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_nc_source_reason_is_exact_on_every_door[occluder_asset]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_nc_source_reason_is_exact_on_every_door[tooling]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_nc_source_reason_is_exact_on_every_door[training_data]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_research_source_reason_is_exact_on_every_door[model_ingest]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_research_source_reason_is_exact_on_every_door[occluder_asset]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_research_source_reason_is_exact_on_every_door[tooling]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_research_source_reason_is_exact_on_every_door[training_data]',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_synthetic_door_keeps_clearance_reason_for_registry_heads',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_synthetic_door_reports_source_taint_for_non_registry_heads',
    'test_license_policy.py::TestBr53SourceAxisClosedOnEveryDoor::test_synthetic_exemption_cannot_pass_a_tainted_source',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[acme/commercial_pack_v1-True-None]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[acme/ffhq-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[acme/ffhq/replacement-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[acme/ffhq/replacement_v1-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[acme/ffhq/train-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[acme/ffhq_replacement_v1-True-None]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[casia-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[dataset/ffhq-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[dataset/ffhq/aligned-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[ffhq-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[ffhq/tools-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[internal/mfr/not_research-True-None]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[org/casia/webface-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[org/ffhq/reimpl-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[vendor/casia-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[vendor/casia/commercial_repack-False-research_only_source]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[vendor/casia_commercial_repack-True-None]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_br56_shape_table[vendor/tools/internal-True-None]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[casia-assets]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[casia-clone]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[casia-derived]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[casia-eval]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[casia-mirror]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[casia-pack]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[casia-subset]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[celeba-assets]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[celeba-clone]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[celeba-derived]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[celeba-eval]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[celeba-mirror]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[celeba-pack]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[celeba-subset]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[ffhq-assets]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[ffhq-clone]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[ffhq-derived]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[ffhq-eval]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[ffhq-mirror]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[ffhq-pack]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[ffhq-subset]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[widerface-assets]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[widerface-clone]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[widerface-derived]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[widerface-eval]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[widerface-mirror]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[widerface-pack]',
    'test_license_policy.py::TestBr56SlashUnderscoreAsymmetryIsDeliberate::test_laundering_leaf_under_research_component_still_fails[widerface-subset]',
    'test_license_policy.py::TestBr62GetModelIngestEntryPrimaryRaise::test_denylisted_package_raises_with_exact_reason',
    'test_license_policy.py::TestBr62GetModelIngestEntryPrimaryRaise::test_nc_denylisted_package_raises_with_exact_reason',
    'test_license_policy.py::TestBr62GetModelIngestEntryPrimaryRaise::test_registered_nc_entry_raises_from_the_primary_site',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_clean_derived_still_passes',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_nc_precedence_preserved[buffalo_l]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_nc_precedence_preserved[insightface/buffalo_l]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_nc_wins_when_input_matches_both_registries[buffalo_l/ffhq]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_nc_wins_when_input_matches_both_registries[deepinsight/insightface/ms1m]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_nc_wins_when_input_matches_both_registries[insightface/glint360k]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_nc_wins_when_input_matches_both_registries[insightface/ms1m]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_research_corpus_rejected_by_scalar_door[casia_webface]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_research_corpus_rejected_by_scalar_door[ffhq]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_research_corpus_rejected_by_scalar_door[glint360k]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_research_corpus_rejected_by_scalar_door[ms1m]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_research_corpus_rejected_by_scalar_door[vggface2_train]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_research_corpus_rejected_by_scalar_door[widerface]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_self_generated_row_cannot_launder_research_corpus[casia_webface]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_self_generated_row_cannot_launder_research_corpus[ffhq]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_self_generated_row_cannot_launder_research_corpus[glint360k]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_self_generated_row_cannot_launder_research_corpus[ms1m]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_self_generated_row_cannot_launder_research_corpus[vggface2_train]',
    'test_license_policy.py::TestBr64ResearchCorpusDerivedFromModel::test_self_generated_row_cannot_launder_research_corpus[widerface]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_correct_token_never_rejected_as_lineage_miss',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-DCFACE-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-DCFACE-cleared-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-None-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-None-allowed-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-None-cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-None-license_cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-None-operator_cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-allowed-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-bogus_token_xyz-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-license_cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[model_ingest-operator_cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-DCFACE-None-uncleared_occluder_asset]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-DCFACE-cleared-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-None-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-None-allowed-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-None-cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-None-license_cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-None-operator_cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-allowed-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-bogus_token_xyz-cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-license_cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[occluder_asset-operator_cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-DCFACE-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-DCFACE-cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-None-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-None-allowed-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-None-cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-None-license_cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-None-operator_cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-allowed-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-bogus_token_xyz-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-license_cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[synthetic_source-operator_cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-DCFACE-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-DCFACE-cleared-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-None-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-None-allowed-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-None-cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-None-license_cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-None-operator_cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-allowed-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-bogus_token_xyz-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-license_cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[tooling-operator_cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-DCFACE-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-DCFACE-cleared-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-None-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-None-allowed-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-None-cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-None-license_cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-None-operator_cleared-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-allowed-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-bogus_token_xyz-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-license_cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_door_token_matrix[training_data-operator_cleared-None-pending_legal_clearance]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_generic_token_cannot_clear_lineage_on_occluder',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[model_ingest-False-None-False-pending_legal_clearance-requires clearance_decision=]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[model_ingest-True-None-True-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[model_ingest-True-cleared-True-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[occluder_asset-False-cleared-False-pending_legal_clearance-requires clearance_decision=]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[occluder_asset-True-None-False-uncleared_occluder_asset-uncleared]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[occluder_asset-True-cleared-False-unknown_source-not a registered]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[synthetic_source-False-None-False-pending_legal_clearance-requires clearance_decision=]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[synthetic_source-True-None-True-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[synthetic_source-True-cleared-True-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[synthetic_source-True-operator_cleared-True-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[tooling-False-None-False-pending_legal_clearance-requires clearance_decision=]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[tooling-True-None-True-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[tooling-True-cleared-True-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[training_data-False-None-False-pending_legal_clearance-requires clearance_decision=]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[training_data-True-None-True-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[training_data-True-allowed-True-None-None]',
    'test_license_policy.py::TestBr65ClearanceAxesSeparated::test_br65_real_synth_head_dual_axis_matrix[training_data-True-cleared-True-None-None]',
    'test_license_policy.py::TestBr66RegistrationFloorOnEveryDoor::test_operator_owned_source_exempts_unregistered_renderer',
    'test_license_policy.py::TestBr66RegistrationFloorOnEveryDoor::test_registered_lineage_still_passes_where_source_admits',
    'test_license_policy.py::TestBr66RegistrationFloorOnEveryDoor::test_unregistered_derived_fails_every_door[model_ingest]',
    'test_license_policy.py::TestBr66RegistrationFloorOnEveryDoor::test_unregistered_derived_fails_every_door[occluder_asset]',
    'test_license_policy.py::TestBr66RegistrationFloorOnEveryDoor::test_unregistered_derived_fails_every_door[synthetic_source]',
    'test_license_policy.py::TestBr66RegistrationFloorOnEveryDoor::test_unregistered_derived_fails_every_door[tooling]',
    'test_license_policy.py::TestBr66RegistrationFloorOnEveryDoor::test_unregistered_derived_fails_every_door[training_data]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[model_ingest-derived_from_model-1.5-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[model_ingest-derived_from_model-123-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[model_ingest-derived_from_model-dcface-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[model_ingest-derived_from_model-value35-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[model_ingest-derived_from_model-value38-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[model_ingest-source-1.5-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[model_ingest-source-123-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[model_ingest-source-dcface-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[model_ingest-source-value10-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[model_ingest-source-value13-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[occluder_asset-derived_from_model-1.5-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[occluder_asset-derived_from_model-123-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[occluder_asset-derived_from_model-dcface-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[occluder_asset-derived_from_model-value40-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[occluder_asset-derived_from_model-value43-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[occluder_asset-source-1.5-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[occluder_asset-source-123-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[occluder_asset-source-dcface-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[occluder_asset-source-value15-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[occluder_asset-source-value18-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[synthetic_source-derived_from_model-1.5-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[synthetic_source-derived_from_model-123-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[synthetic_source-derived_from_model-dcface-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[synthetic_source-derived_from_model-value45-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[synthetic_source-derived_from_model-value48-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[synthetic_source-source-1.5-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[synthetic_source-source-123-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[synthetic_source-source-dcface-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[synthetic_source-source-value20-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[synthetic_source-source-value23-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[tooling-derived_from_model-1.5-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[tooling-derived_from_model-123-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[tooling-derived_from_model-dcface-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[tooling-derived_from_model-value30-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[tooling-derived_from_model-value33-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[tooling-source-1.5-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[tooling-source-123-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[tooling-source-dcface-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[tooling-source-value5-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[tooling-source-value8-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[training_data-derived_from_model-1.5-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[training_data-derived_from_model-123-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[training_data-derived_from_model-dcface-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[training_data-derived_from_model-value25-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[training_data-derived_from_model-value28-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[training_data-source-1.5-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[training_data-source-123-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[training_data-source-dcface-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[training_data-source-value0-invalid_row]',
    'test_license_policy.py::TestBr68NonStringFloorFields::test_non_string_field_invalid_row_every_door[training_data-source-value3-invalid_row]',
    'test_license_policy.py::TestBr69FloorNotSubtractCapable::test_common_provenance_checks_has_no_axis_disable_param',
    'test_license_policy.py::TestBr69FloorNotSubtractCapable::test_floor_licenses_half_trips_licence_only_row',
    'test_license_policy.py::TestBr69FloorNotSubtractCapable::test_floor_taint_half_trips_taint_only_row',
    'test_license_policy.py::TestBr70MissingClearanceKeyDistinctFromWrongToken::test_matching_token_passes_tooling',
    'test_license_policy.py::TestBr70MissingClearanceKeyDistinctFromWrongToken::test_missing_clearance_key_is_pending_not_pass',
    'test_license_policy.py::TestBr70MissingClearanceKeyDistinctFromWrongToken::test_wrong_clearance_token_is_pending',
    'test_license_policy.py::TestBr73AllowlistedPackageDeferredLicenseStillRuns::test_allowlisted_package_plus_bogus_row_spdx',
    'test_license_policy.py::TestBr73AllowlistedPackageDeferredLicenseStillRuns::test_allowlisted_package_plus_denylisted_row_spdx',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_bare_buffalo_weights_tag_fails',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_buffalo_l_derived_from_model_fails_with_nc_model_derived',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_buffalo_star_pattern_drives_audit',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_insightface_prefix_pattern_is_pinned',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_nc_model_ids_layer_rejects_pinned_ids[arcface/r100]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_nc_model_ids_layer_rejects_pinned_ids[buffalo_sc]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_nc_model_ids_layer_rejects_pinned_ids[retinaface/r50]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_nested_and_separator_insightface_forms_fail[deepinsight/insightface/buffalo_l]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_nested_and_separator_insightface_forms_fail[deepinsight/insightface]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_nested_and_separator_insightface_forms_fail[hf/insightface/buffalo_l]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_nested_and_separator_insightface_forms_fail[insightface-buffalo-l]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_nested_and_separator_insightface_forms_fail[insightface\\uff0fbuffalo_l]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_nested_and_separator_insightface_forms_fail[insightface_buffalo_l]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_nested_and_separator_insightface_forms_fail[models/insightface/buffalo_l]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_new_nc_table_entry_changes_audit_outcome',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_non_nc_derived_tags_still_pass[dcface/gen1]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_non_nc_derived_tags_still_pass[mediapipe/blazeface]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_non_nc_derived_tags_still_pass[notdcface/x]',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_provenance_row_nested_insightface_fails',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_provenance_row_with_buffalo_output_fails',
    'test_license_policy.py::TestBuffaloAndNcModelDerivedFail::test_vec2face_forbidden_table_entry_drives_nc_ids',
    'test_license_policy.py::TestDcfaceClearanceSegmentResolve::test_br36_dcface_forms_fail_without_clearance[dcface_v2]',
    'test_license_policy.py::TestDcfaceClearanceSegmentResolve::test_br36_dcface_forms_fail_without_clearance[myorg/dcface]',
    'test_license_policy.py::TestDcfaceClearanceSegmentResolve::test_br36_dcface_forms_pass_with_clearance[False-dcface/v2]',
    'test_license_policy.py::TestDcfaceClearanceSegmentResolve::test_br36_dcface_forms_pass_with_clearance[False-dcface]',
    'test_license_policy.py::TestDcfaceClearanceSegmentResolve::test_br36_dcface_forms_pass_with_clearance[False-dcface_v2]',
    'test_license_policy.py::TestDcfaceClearanceSegmentResolve::test_br36_dcface_forms_pass_with_clearance[False-myorg/dcface]',
    'test_license_policy.py::TestDcfaceClearanceSegmentResolve::test_br36_dcface_forms_pass_with_clearance[True-dcface/v2]',
    'test_license_policy.py::TestDcfaceClearanceSegmentResolve::test_br36_dcface_forms_pass_with_clearance[True-dcface]',
    'test_license_policy.py::TestDcfaceClearanceSegmentResolve::test_br36_dcface_forms_pass_with_clearance[True-dcface_v2]',
    'test_license_policy.py::TestDcfaceClearanceSegmentResolve::test_br36_dcface_forms_pass_with_clearance[True-myorg/dcface]',
    'test_license_policy.py::TestDcfaceClearanceSegmentResolve::test_br36_dcface_v2_no_lineage_still_requires_clearance',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_br16_lineage_sole_cause_of_synthetic_pending',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_br29_dcface_no_lineage_correct_clearance_passes',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_br29_dcface_no_lineage_missing_clearance_fails',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_br29_dcface_no_lineage_wrong_clearance_fails',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_dcface_derived_row_passes_with_ffhq_lineage',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_dcface_missing_clearance_fails',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_dcface_not_on_nc_pattern_list',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_dcface_wrong_clearance_fails',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_generator_lineage_does_not_trigger_research_rejection',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_same_dcface_row_with_buffalo_derived_fails',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_same_row_with_source_ffhq_fails_research_only',
    'test_license_policy.py::TestDcfaceOperatorClearanceAndLineageExempt::test_vec2face_still_pending',
    'test_license_policy.py::TestEntryPointParityAndCommonNcGate::test_br23_model_ingest_parity_vendor_missing',
    'test_license_policy.py::TestEntryPointParityAndCommonNcGate::test_br23_model_ingest_parity_yunet_pass',
    'test_license_policy.py::TestEntryPointParityAndCommonNcGate::test_br23_occluder_parity_cleared_pass',
    'test_license_policy.py::TestEntryPointParityAndCommonNcGate::test_br23_occluder_parity_uncleared',
    'test_license_policy.py::TestEntryPointParityAndCommonNcGate::test_br23_synthetic_parity_with_audit_synthetic_source',
    'test_license_policy.py::TestEntryPointParityAndCommonNcGate::test_br23_synthetic_requires_nonempty_source',
    'test_license_policy.py::TestEntryPointParityAndCommonNcGate::test_br26_occluder_rejects_nc_derived',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_admit_clean[yolof_bin]',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_admit_clean[yolop_trt]',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_admit_clean[yolos_pt]',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_admit_clean[yolox_bin]',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_admit_clean[yolox_fp16]',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_admit_clean[yolox_int8]',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_admit_clean[yolox_onnx]',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_admit_clean[yolox_pt]',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_admit_clean[yolox_s_trt]',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_admit_clean[yolox_tensorrt]',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_admit_clean[yolox_trt]',
    'test_license_policy.py::TestF10ExportTagAdmit::test_export_tags_are_shield_inventory_members',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_clean_family_tags_admit[yolof_r50]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_clean_family_tags_admit[yolof_r50_c5]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_clean_family_tags_admit[yolopv2]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_clean_family_tags_admit[yolos_tiny]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_clean_family_tags_admit[yolox_nano]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_clean_family_tags_admit[yolox_s]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_tag_glue_denies[yolof_r50_pose]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_tag_glue_denies[yolop_v2_free]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_tag_glue_denies[yolos_eg_tiny]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_tag_glue_denies[yolos_tiny_eg]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_tag_glue_denies[yolox_nano_seg]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_tag_glue_denies[yolox_s_free]',
    'test_license_policy.py::TestF10LegitTagGlueLaundering::test_tag_glue_denies[yolox_s_seg]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies[yolos_egmentation]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies[yolos_free]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies[yolos_pose]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies[yolos_segment]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies[yolosegme]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies[yolosegv8]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies[yolosfree]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies[yolospose]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies[yolossegment]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies_on_doors_and_row[yolos_egmentation]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies_on_doors_and_row[yolos_free]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies_on_doors_and_row[yolos_pose]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies_on_doors_and_row[yolos_segment]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies_on_doors_and_row[yolosegme]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies_on_doors_and_row[yolosegv8]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies_on_doors_and_row[yolosfree]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies_on_doors_and_row[yolospose]',
    'test_license_policy.py::TestF10LongDebrisFailClosed::test_long_debris_denies_on_doors_and_row[yolossegment]',
    'test_license_policy.py::TestF10MaxReconstSegmentsPin::test_max_reconst_segments_is_module_level',
    'test_license_policy.py::TestF10MaxReconstSegmentsPin::test_red_proof_max_reconst_exact_value_is_load_bearing',
    'test_license_policy.py::TestF10MaxReconstSegmentsPin::test_red_proof_max_reconst_segments_perturbation',
    'test_license_policy.py::TestF10ResidualClassifyMechanism::test_export_shield_is_legitimate_residual_segment',
    'test_license_policy.py::TestF10ResidualClassifyMechanism::test_prior_admit_set_still_holds',
    'test_license_policy.py::TestF10ResidualClassifyMechanism::test_prior_deny_set_still_holds',
    'test_license_policy.py::TestF10ResidualClassifyMechanism::test_separator_tag_inventory_pins',
    'test_license_policy.py::TestF10ResidualClassifyMechanism::test_unknown_residual_honest_note_not_fabricated_ultralytics[ppyolo-zzzwombat]',
    'test_license_policy.py::TestF10ResidualClassifyMechanism::test_unknown_residual_honest_note_not_fabricated_ultralytics[yolof-zqx]',
    'test_license_policy.py::TestF10ResidualClassifyMechanism::test_unknown_residual_honest_note_not_fabricated_ultralytics[yolop-zqx]',
    'test_license_policy.py::TestF10ResidualClassifyMechanism::test_unknown_residual_honest_note_not_fabricated_ultralytics[yolos-blorp]',
    'test_license_policy.py::TestF10ResidualClassifyMechanism::test_unknown_residual_honest_note_not_fabricated_ultralytics[yolox-zqx]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_allowlist_is_ppyolo_eplus_only',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yolofc5]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yolospt]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yolosseg]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yolossmall]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yolostiny]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yolostrt]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yoloxbin]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yoloxdarknet]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yoloxnano]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yoloxonnx]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yoloxpretrained]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yoloxpt]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yoloxpttrt]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yoloxsafetensors]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yoloxtensorrt]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yoloxtiny]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_tags_deny[yoloxtrt]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yolofc5-yolof_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yolospt-yolos_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yolosseg-yolos_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yolossmall-yolos_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yolostiny-yolos_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yolostrt-yolos_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yoloxbin-yolox_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yoloxdarknet-yolox_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yoloxnano-yolox_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yoloxonnx-yolox_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yoloxpretrained-yolox_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yoloxpt-yolox_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yoloxpttrt-yolox_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yoloxsafetensors-yolox_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yoloxtensorrt-yolox_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yoloxtiny-yolox_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_compact_glue_unknown_path_package_id[yoloxtrt-yolox_unknown_residual]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_red_proof_steal_flag_turns_compact_glue_red',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[ppyoloe]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yolof_c5]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yolof_r50]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yolofr50]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yolopv2]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yolos_tiny]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yolox_bin]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yolox_darknet]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yolox_nano]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yolox_onnx]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yolox_pt]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yolox_trt]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_separator_and_family_compact_admit[yoloxs]',
    'test_license_policy.py::TestF11A141CompactGlueTagDeny::test_unicode_fullwidth_compact_glue_denies',
    'test_license_policy.py::TestF11A142DeadBranchCleanup::test_classify_fail_closed_default_is_unknown',
    'test_license_policy.py::TestF11A142DeadBranchCleanup::test_no_deny_seed_underlying_exception_helper',
    'test_license_policy.py::TestF11A142DeadBranchCleanup::test_steal_returns_entry_for_unknown_compact_glue',
    'test_license_policy.py::TestF11A145TagInventorySingleSource::test_compact_tags_subset_of_separator_tags',
    'test_license_policy.py::TestF11A145TagInventorySingleSource::test_separator_tags_derived_from_canonical_sources',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_doors_and_row_deny_unbounded_defer[ppyoloultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_doors_and_row_deny_unbounded_defer[yolofultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_doors_and_row_deny_unbounded_defer[yolopultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_doors_and_row_deny_unbounded_defer[yolosultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_doors_and_row_deny_unbounded_defer[yoloxultralyticshub-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_doors_and_row_deny_unbounded_defer[yoloxultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_doors_and_row_deny_unbounded_defer[yoloxyolov8seg-yolov8]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_red_proof_steal_flag_turns_unbounded_defer_red',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_separator_twin_and_bare_still_deny',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_unbounded_defer_compact_denies_honest[ppyoloultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_unbounded_defer_compact_denies_honest[yolofultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_unbounded_defer_compact_denies_honest[yolopultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_unbounded_defer_compact_denies_honest[yolosultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_unbounded_defer_compact_denies_honest[yoloxultralyticshub-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_unbounded_defer_compact_denies_honest[yoloxultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF11B141UnboundedDeferCompactResidual::test_unbounded_defer_compact_denies_honest[yoloxyolov8seg-yolov8]',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_red_proof_seg_in_inventory_would_admit',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_seg_absent_from_yolos_inventories',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_yolos_seg_forms_deny[yolos-tiny-seg]',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_yolos_seg_forms_deny[yolos.seg]',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_yolos_seg_forms_deny[yolos_bin_seg]',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_yolos_seg_forms_deny[yolos_pt_seg]',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_yolos_seg_forms_deny[yolos_seg]',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_yolos_seg_forms_deny[yolos_seg_bin]',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_yolos_seg_forms_deny[yolos_seg_pt]',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_yolos_seg_forms_deny[yolos_seg_trt]',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_yolos_seg_forms_deny[yolos_tiny_seg]',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_yolos_seg_forms_deny[yolos_trt_seg]',
    'test_license_policy.py::TestF11B143YolosSegDeny::test_yolos_seg_forms_deny[yolosseg]',
    'test_license_policy.py::TestF11ConverseExportAdmit::test_export_separator_admits_without_agpl_lineage[yolof_bin]',
    'test_license_policy.py::TestF11ConverseExportAdmit::test_export_separator_admits_without_agpl_lineage[yolop_trt]',
    'test_license_policy.py::TestF11ConverseExportAdmit::test_export_separator_admits_without_agpl_lineage[yolos_pt]',
    'test_license_policy.py::TestF11ConverseExportAdmit::test_export_separator_admits_without_agpl_lineage[yolox_bin]',
    'test_license_policy.py::TestF11ConverseExportAdmit::test_export_separator_admits_without_agpl_lineage[yolox_pt]',
    'test_license_policy.py::TestF11ConverseExportAdmit::test_export_separator_admits_without_agpl_lineage[yolox_trt]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_agpl_exact_residual_denies_on_doors[ppyoloyolo-yolo]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_agpl_exact_residual_denies_on_doors[yolofyolo-yolo]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_agpl_exact_residual_denies_on_doors[yolopyolo-yolo]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_agpl_exact_residual_denies_on_doors[yolosyolo-yolo]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_agpl_exact_residual_denies_on_doors[yolosyolo_v8-yolov8]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_agpl_exact_residual_denies_on_doors[yoloxyolo-yolo]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_agpl_exact_residual_denies_on_doors[yoloxyolo_v8-yolov8]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_controls_keep_current_behavior',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_exact_residual_unbounded_denies_honest[ppyoloyolo-yolo]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_exact_residual_unbounded_denies_honest[yolofyolo-yolo]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_exact_residual_unbounded_denies_honest[yolopyolo-yolo]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_exact_residual_unbounded_denies_honest[yolosyolo-yolo]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_exact_residual_unbounded_denies_honest[yolosyolo_v8-yolov8]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_exact_residual_unbounded_denies_honest[yoloxyolo-yolo]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_exact_residual_unbounded_denies_honest[yoloxyolo_nas-yolonas]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_exact_residual_unbounded_denies_honest[yoloxyolo_v8-yolov8]',
    'test_license_policy.py::TestF12ExactResidualDeferSteal::test_red_proof_steal_flag_turns_exact_residual_red',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_half_separated_compact_glue_denies[yolofc5_onnx]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_half_separated_compact_glue_denies[yolofc5_pt]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_half_separated_compact_glue_denies[yoloxbin_onnx]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_half_separated_compact_glue_denies[yoloxpt_fp16]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_half_separated_compact_glue_denies[yoloxpt_int8]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_half_separated_compact_glue_denies[yoloxpt_onnx]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_half_separated_compact_glue_denies[yoloxpt_trt]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_half_separated_compact_glue_denies[yoloxpth_onnx]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_half_separated_compact_glue_denies[yoloxtrt_onnx]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_red_proof_steal_flag_turns_half_separated_red',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_separator_and_family_compact_controls_admit[yolofr50]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_separator_and_family_compact_controls_admit[yolox_pt]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_separator_and_family_compact_controls_admit[yolox_pt_trt]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_separator_and_family_compact_controls_admit[yolox_s_pt]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_separator_and_family_compact_controls_admit[yolox_trt]',
    'test_license_policy.py::TestF12HalfSeparatedCompactGlue::test_separator_and_family_compact_controls_admit[yoloxs]',
    'test_license_policy.py::TestF12NcDoorPromotionUnboundedCompact::test_controls_exception_clean_and_existing_nc_compound',
    'test_license_policy.py::TestF12NcDoorPromotionUnboundedCompact::test_red_proof_token_has_exception_family_unbounded',
    'test_license_policy.py::TestF12NcDoorPromotionUnboundedCompact::test_unbounded_exception_nc_denies_on_doors[yoloxantelopev2-antelopev2]',
    'test_license_policy.py::TestF12NcDoorPromotionUnboundedCompact::test_unbounded_exception_nc_denies_on_doors[yoloxarcface-arcface]',
    'test_license_policy.py::TestF12NcDoorPromotionUnboundedCompact::test_unbounded_exception_nc_denies_on_doors[yoloxinsightface-insightface]',
    'test_license_policy.py::TestF12NcDoorPromotionUnboundedCompact::test_unbounded_exception_nc_denies_on_doors[yoloxyolo_nas-yolonas]',
    'test_license_policy.py::TestF12NcDoorPromotionUnboundedCompact::test_unbounded_exception_nc_denies_on_floor[yoloxantelopev2-antelopev2]',
    'test_license_policy.py::TestF12NcDoorPromotionUnboundedCompact::test_unbounded_exception_nc_denies_on_floor[yoloxarcface-arcface]',
    'test_license_policy.py::TestF12NcDoorPromotionUnboundedCompact::test_unbounded_exception_nc_denies_on_floor[yoloxinsightface-insightface]',
    'test_license_policy.py::TestF12NcDoorPromotionUnboundedCompact::test_unbounded_exception_nc_denies_on_floor[yoloxyolo_nas-yolonas]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_compact_orthography_of_separator_tags_stays_deny',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_catalog_admits[PaddleDetection/ppyoloe_crn_s_300e_coco]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_catalog_admits[ppyolo_r50vd_dcn_1x_coco]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_catalog_admits[ppyoloe_crn_s_300e_coco]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_catalog_admits[ppyoloe_l]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_catalog_admits[ppyoloe_m]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_catalog_admits[ppyoloe_plus]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_catalog_admits[ppyoloe_plus_crn_s_80e_coco]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_catalog_admits[ppyoloe_s]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_catalog_admits[ppyoloe_x]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_catalog_admits[ppyoloeplus]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_catalog_admits[ppyolov2_r50vd_dcn_365e_coco]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_deny_stems_still_deny[ppyoloultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_ppyolo_deny_stems_still_deny[ppyoloyolo-yolo]',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_red_proof_inventory_drop_turns_catalog_red',
    'test_license_policy.py::TestF12PpyoloCatalogAndResidualSplit::test_underscore_token_prefers_head_segment_residual',
    'test_license_policy.py::TestF12ReasonHonesty::test_f12_1_witnesses_keep_true_entries',
    'test_license_policy.py::TestF12ReasonHonesty::test_red_proof_reconst_suppression_is_load_bearing',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_not_fabricated_yolo[yolof_z-yolof_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_not_fabricated_yolo[yolofc5-yolof_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_not_fabricated_yolo[yolop_z-yolop_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_not_fabricated_yolo[yolos_ti-yolos_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_not_fabricated_yolo[yolospt-yolos_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_not_fabricated_yolo[yolox_ab-yolox_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_not_fabricated_yolo[yolox_z-yolox_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_not_fabricated_yolo[yoloxpt-yolox_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_on_doors_exact_entry[yolof_z-yolof_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_on_doors_exact_entry[yolofc5-yolof_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_on_doors_exact_entry[yolop_z-yolop_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_on_doors_exact_entry[yolos_ti-yolos_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_on_doors_exact_entry[yolospt-yolos_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_on_doors_exact_entry[yolox_ab-yolox_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_on_doors_exact_entry[yolox_z-yolox_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_short_residual_unknown_on_doors_exact_entry[yoloxpt-yolox_unknown_residual]',
    'test_license_policy.py::TestF12ReasonHonesty::test_strongest_hit_names_ultralytics_in_compound',
    'test_license_policy.py::TestF12ReasonHonesty::test_yoloseg_reconst_path_still_yolo',
    'test_license_policy.py::TestF12YolofDetectron2ScheduleTags::test_red_proof_schedule_tag_drop_turns_yolof_red',
    'test_license_policy.py::TestF12YolofDetectron2ScheduleTags::test_yolof_deny_stems_still_deny[yolofultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF12YolofDetectron2ScheduleTags::test_yolof_deny_stems_still_deny[yolofyolo-yolo]',
    'test_license_policy.py::TestF12YolofDetectron2ScheduleTags::test_yolof_schedule_catalog_admits[YOLOF_R_50_C5_1x]',
    'test_license_policy.py::TestF12YolofDetectron2ScheduleTags::test_yolof_schedule_catalog_admits[facebookresearch/detectron2/yolof_r50_c5_1x]',
    'test_license_policy.py::TestF12YolofDetectron2ScheduleTags::test_yolof_schedule_catalog_admits[yolof_r101_c5_1x]',
    'test_license_policy.py::TestF12YolofDetectron2ScheduleTags::test_yolof_schedule_catalog_admits[yolof_r50_c5_1x]',
    'test_license_policy.py::TestF12YolofDetectron2ScheduleTags::test_yolof_schedule_catalog_admits[yolof_r50_c5_3x]',
    'test_license_policy.py::TestF12YoloxDarknet53::test_red_proof_darknet53_drop_turns_admit_red',
    'test_license_policy.py::TestF12YoloxDarknet53::test_yolox_darknet53_admits[YOLOX-DarkNet53]',
    'test_license_policy.py::TestF12YoloxDarknet53::test_yolox_darknet53_admits[yolox-darknet53]',
    'test_license_policy.py::TestF12YoloxDarknet53::test_yolox_darknet53_admits[yolox_darknet53]',
    'test_license_policy.py::TestF12bYolofDatasetTag::test_red_proof_coco_tag_drop_turns_yolof_red',
    'test_license_policy.py::TestF12bYolofDatasetTag::test_yolof_dataset_catalog_admits[YOLOF_R_50_C5_1x_coco]',
    'test_license_policy.py::TestF12bYolofDatasetTag::test_yolof_dataset_catalog_admits[yolof_r101_c5_1x_coco]',
    'test_license_policy.py::TestF12bYolofDatasetTag::test_yolof_dataset_catalog_admits[yolof_r50_c5_1x_coco]',
    'test_license_policy.py::TestF12bYolofDatasetTag::test_yolof_dataset_catalog_admits[yolof_r50_c5_3x_coco]',
    'test_license_policy.py::TestF12bYolofDatasetTag::test_yolof_dataset_deny_stems_still_deny[yolof_z-yolof_unknown_residual]',
    'test_license_policy.py::TestF12bYolofDatasetTag::test_yolof_dataset_deny_stems_still_deny[yolofc5_pt-yolof_unknown_residual]',
    'test_license_policy.py::TestF12bYolofDatasetTag::test_yolof_dataset_deny_stems_still_deny[yolofultralyticsplus-ultralytics]',
    'test_license_policy.py::TestF12bYolofDatasetTag::test_yolof_dataset_deny_stems_still_deny[yolofyolo-yolo]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[ppyolo_mbv3_large_coco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[ppyolo_r18vd_coco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[ppyolo_r50vd_dcn_2x_coco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[ppyolo_tiny_650e_coco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[ppyoloe_plus_sod_crn_l_80e_coco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[ppyolov2_r101vd_dcn_365e_coco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[yolof_r50-c5_8xb8-1x_coco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[yolox_s_8x8_300e_coco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[yolox_s_8xb8-300e_coco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[yolox_s_coco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[yolox_tiny_8xb8-300e_coco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_catalog_admits[yolox_voc_s]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_compact_glue_of_new_tags_stays_deny[ppyolo650e]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_compact_glue_of_new_tags_stays_deny[ppyoloes]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_compact_glue_of_new_tags_stays_deny[ppyolotiny]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_compact_glue_of_new_tags_stays_deny[yolofcoco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_compact_glue_of_new_tags_stays_deny[yolox8xb8]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_compact_glue_of_new_tags_stays_deny[yoloxcoco]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_compact_glue_of_new_tags_stays_deny[yoloxtiny]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_cross_family_tags_stay_deny[yolos_8xb8]',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_red_proof_ppyolo_tiny_tag_drop',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_red_proof_yolof_8xb8_tag_drop',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_red_proof_yolox_8xb8_tag_drop',
    'test_license_policy.py::TestF13CatalogSeparatorTags::test_red_proof_yolox_voc_tag_drop',
    'test_license_policy.py::TestF13EplusHeadPeel::test_ppyoloeplus_and_separator_twin_still_admit',
    'test_license_policy.py::TestF13EplusHeadPeel::test_ppyoloeplus_trt_admits',
    'test_license_policy.py::TestF13EplusHeadPeel::test_ppyoloes_still_denies',
    'test_license_policy.py::TestF13EplusHeadPeel::test_red_proof_eplus_allowlist_drop',
    'test_license_policy.py::TestF13HeadPositionDenyNcCompactGlue::test_agpl_head_exception_rem_denies_honest[yolov8yolox-yolov8]',
    'test_license_policy.py::TestF13HeadPositionDenyNcCompactGlue::test_agpl_head_exception_rem_denies_honest[yolov8yolox_s-yolov8]',
    'test_license_policy.py::TestF13HeadPositionDenyNcCompactGlue::test_mirrors_still_deny[yoloxarcface-arcface]',
    'test_license_policy.py::TestF13HeadPositionDenyNcCompactGlue::test_mirrors_still_deny[yoloxyolov8-yolov8]',
    'test_license_policy.py::TestF13HeadPositionDenyNcCompactGlue::test_nc_head_exception_rem_denies_on_doors[antelopev2yolox-antelopev2]',
    'test_license_policy.py::TestF13HeadPositionDenyNcCompactGlue::test_nc_head_exception_rem_denies_on_doors[arcfaceyolox-arcface]',
    'test_license_policy.py::TestF13HeadPositionDenyNcCompactGlue::test_red_proof_head_known_rem_glue',
    'test_license_policy.py::TestF13JunkPrefixExceptionDenyAdjacency::test_admit_controls_hold[yolodummy]',
    'test_license_policy.py::TestF13JunkPrefixExceptionDenyAdjacency::test_admit_controls_hold[yolox]',
    'test_license_policy.py::TestF13JunkPrefixExceptionDenyAdjacency::test_admit_controls_hold[yoloxs]',
    'test_license_policy.py::TestF13JunkPrefixExceptionDenyAdjacency::test_existing_deny_controls_hold[my_yoloxyolo-yolo]',
    'test_license_policy.py::TestF13JunkPrefixExceptionDenyAdjacency::test_existing_deny_controls_hold[myyoloxultralytics-ultralytics]',
    'test_license_policy.py::TestF13JunkPrefixExceptionDenyAdjacency::test_existing_deny_controls_hold[yoloxyolo-yolo]',
    'test_license_policy.py::TestF13JunkPrefixExceptionDenyAdjacency::test_junk_prefix_exception_deny_denies_honest[abcyoloxyolo-yolo]',
    'test_license_policy.py::TestF13JunkPrefixExceptionDenyAdjacency::test_junk_prefix_exception_deny_denies_honest[myyoloxyolo-yolo]',
    'test_license_policy.py::TestF13JunkPrefixExceptionDenyAdjacency::test_junk_prefix_exception_deny_denies_honest[xyoloxyolo-yolo]',
    'test_license_policy.py::TestF13JunkPrefixExceptionDenyAdjacency::test_red_proof_mid_exception_adjacency',
    'test_license_policy.py::TestF13NcDoorPromotionTrailingException::test_br28_floor_only_precision_preserved[myarcface]',
    'test_license_policy.py::TestF13NcDoorPromotionTrailingException::test_br28_floor_only_precision_preserved[not-insightface]',
    'test_license_policy.py::TestF13NcDoorPromotionTrailingException::test_compact_short_seed_head_is_exception_family[antelopev2yolox]',
    'test_license_policy.py::TestF13NcDoorPromotionTrailingException::test_compact_short_seed_head_is_exception_family[arcfaceyolox]',
    'test_license_policy.py::TestF13NcDoorPromotionTrailingException::test_prefix_exception_nc_still_denies',
    'test_license_policy.py::TestF13NcDoorPromotionTrailingException::test_red_proof_non_prefix_exception_helper',
    'test_license_policy.py::TestF13NcDoorPromotionTrailingException::test_trailing_exception_nc_denies_on_doors[arcface_yolox-arcface]',
    'test_license_policy.py::TestF13NcDoorPromotionTrailingException::test_trailing_exception_nc_denies_on_doors[buffalo_l_yolox_s-buffalo_l]',
    'test_license_policy.py::TestF13NcDoorPromotionTrailingException::test_trailing_exception_nc_denies_on_doors[insightface_yolox-insightface]',
    'test_license_policy.py::TestF13NcDoorPromotionTrailingException::test_trailing_exception_nc_denies_on_doors[insightfaceyolox-insightface]',
    'test_license_policy.py::TestF13NcDoorPromotionTrailingException::test_trailing_exception_nc_denies_on_doors[yolonas_yolox-yolonas]',
    'test_license_policy.py::TestF13StealRankingAndMultiStack::test_multi_stack_names_inner_yolo',
    'test_license_policy.py::TestF13StealRankingAndMultiStack::test_red_proof_honesty_bonus',
    'test_license_policy.py::TestF13StealRankingAndMultiStack::test_red_proof_multi_stack_recurse',
    'test_license_policy.py::TestF13StealRankingAndMultiStack::test_yoloxyolov8seg_names_yolov8_not_yolov8s',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_myarcface_stays_floor_only_door_pass',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_official_separator_and_f12_admits_unchanged[ppyoloe_s]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_official_separator_and_f12_admits_unchanged[ppyoloeplus]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_official_separator_and_f12_admits_unchanged[yolodummy]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_official_separator_and_f12_admits_unchanged[yolof_r50_c5_1x_coco]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_official_separator_and_f12_admits_unchanged[yolox_pt_trt]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_official_separator_and_f12_admits_unchanged[yolox_s]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_official_separator_and_f12_admits_unchanged[yoloxs]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_red_proof_unofficial_separator_charset_neuter',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_agpl_denies_honest[yolox+yolo-yolo]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_agpl_denies_honest[yolox:yolo-yolo]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_agpl_denies_honest[yolox=yolo-yolo]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_agpl_denies_honest[yolox@yolo-yolo]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_agpl_denies_honest[yolox\\uff0byolo-yolo]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_agpl_denies_honest[yoloxyolo+v8-yolov8]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_nc_denies_on_doors[yolox+arcface-arcface]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_nc_denies_on_doors[yolox+insightface-insightface]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_nc_denies_on_doors[yolox+yolo_nas-yolo_nas]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_nc_denies_on_doors[yolox\\uff0binsightface-insightface]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_unknown_residual_denies[yolofc5+pt]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_unknown_residual_denies[yoloxpt+trt]',
    'test_license_policy.py::TestF13UnofficialSeparatorFolding::test_unofficial_sep_unknown_residual_denies[yoloxpt\\uff0btrt]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_junk_nc_without_exception_stays_floor_only[aaayolonas]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_junk_nc_without_exception_stays_floor_only[aabuffalo_l]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_junk_nc_without_exception_stays_floor_only[aainsightface]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_junk_nc_without_exception_stays_floor_only[myarcface]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_junk_nc_without_exception_stays_floor_only[not-insightface]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_mid_exception_nc_denies_on_doors[abcyoloxinsightface-insightface]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_mid_exception_nc_denies_on_doors[myyoloxinsightface-insightface]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_mid_exception_nc_denies_on_doors[xyoloxantelopev2-antelopev2]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_mid_exception_nc_denies_on_doors[xyoloxarcface-arcface]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_mid_exception_nc_denies_on_doors[xyoloxinsightface-insightface]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_mid_exception_nc_denies_on_doors[xyoloxsarcface-arcface]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_prefix_and_trailing_exception_still_deny[insightface_yolox-insightface]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_prefix_and_trailing_exception_still_deny[yoloxinsightface-insightface]',
    'test_license_policy.py::TestF14DoorPromotionMidException::test_red_proof_mid_exception_occurrence_neuter',
    'test_license_policy.py::TestF14FourCharHeadExceptionRem::test_existing_yolo_and_yolov8_landings_hold[yolo-yolo]',
    'test_license_policy.py::TestF14FourCharHeadExceptionRem::test_existing_yolo_and_yolov8_landings_hold[yolov8yolox-yolov8]',
    'test_license_policy.py::TestF14FourCharHeadExceptionRem::test_non_exception_rem_and_suffix_yolo_still_admit[myyolo]',
    'test_license_policy.py::TestF14FourCharHeadExceptionRem::test_non_exception_rem_and_suffix_yolo_still_admit[yolodummy]',
    'test_license_policy.py::TestF14FourCharHeadExceptionRem::test_red_proof_four_char_head_min_len_neuter',
    'test_license_policy.py::TestF14FourCharHeadExceptionRem::test_yolo_head_exception_rem_denies[yoloyolox-yolo]',
    'test_license_policy.py::TestF14FourCharHeadExceptionRem::test_yolo_head_exception_rem_denies[yoloyoloxs-yolo]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_compact_glue_of_new_paddle_tags_denies[ppyolo30e]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_compact_glue_of_new_paddle_tags_denies[ppyolo320]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_compact_glue_of_new_paddle_tags_denies[ppyolo416]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_compact_glue_of_new_paddle_tags_denies[ppyolo60e]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_compact_glue_of_new_paddle_tags_denies[ppyolo640]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_compact_glue_of_new_paddle_tags_denies[ppyoloauxhead]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_compact_glue_of_new_paddle_tags_denies[ppyolodistill]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_compact_glue_of_new_paddle_tags_denies[ppyoloobjects365]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_compact_glue_of_new_paddle_tags_denies[ppyolorelu]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_compact_glue_of_new_paddle_tags_denies[ppyolovoc]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_new_tags_do_not_leak_across_families[yolof_distill]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_new_tags_do_not_leak_across_families[yolos_voc]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_new_tags_do_not_leak_across_families[yolox_auxhead]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_paddle_catalog_admits[ppyolo_r50vd_dcn_voc]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_paddle_catalog_admits[ppyolo_voc]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_paddle_catalog_admits[ppyoloe_plus_crn_l_30e_voc]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_paddle_catalog_admits[ppyoloe_plus_crn_l_80e_coco_distill]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_paddle_catalog_admits[ppyoloe_plus_crn_m_80e_coco_distill]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_paddle_catalog_admits[ppyoloe_plus_crn_s_30e_voc]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_paddle_catalog_admits[ppyoloe_plus_crn_s_60e_objects365]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_paddle_catalog_admits[ppyoloe_plus_crn_t_auxhead_300e_coco]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_paddle_catalog_admits[ppyoloe_plus_crn_t_auxhead_320_300e_coco]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_paddle_catalog_admits[ppyoloe_plus_crn_t_auxhead_relu_300e_coco]',
    'test_license_policy.py::TestF14PaddleCatalogTags::test_red_proof_ppyolo_auxhead_tag_drop',
    'test_license_policy.py::TestF14PpYoloTitlePathMerge::test_pp_without_yolo_segment_unaffected[pp]',
    'test_license_policy.py::TestF14PpYoloTitlePathMerge::test_pp_without_yolo_segment_unaffected[pp_x]',
    'test_license_policy.py::TestF14PpYoloTitlePathMerge::test_pp_yolo_title_path_admits[PP-YOLOE+]',
    'test_license_policy.py::TestF14PpYoloTitlePathMerge::test_pp_yolo_title_path_admits[PP-YOLOE+_crn_s_80e_coco]',
    'test_license_policy.py::TestF14PpYoloTitlePathMerge::test_pp_yolo_title_path_admits[PaddlePaddle/PP-YOLOE+]',
    'test_license_policy.py::TestF14PpYoloTitlePathMerge::test_pp_yolo_title_path_admits[pp-yoloe+]',
    'test_license_policy.py::TestF14PpYoloTitlePathMerge::test_pp_yolo_title_path_admits[pp_yolo]',
    'test_license_policy.py::TestF14PpYoloTitlePathMerge::test_pp_yolov8_fail_closed[pp_yolov8-ppyolo_unknown_residual]',
    'test_license_policy.py::TestF14PpYoloTitlePathMerge::test_red_proof_pp_yolo_merge_neuter',
    'test_license_policy.py::TestF14RegistryTrailingTagStrip::test_official_size_tag_is_not_a_registry_tag[yolox:s]',
    'test_license_policy.py::TestF14RegistryTrailingTagStrip::test_red_proof_registry_tag_strip_neuter',
    'test_license_policy.py::TestF14RegistryTrailingTagStrip::test_registry_tag_strip_does_not_launder_deny[yolo:latest-yolo]',
    'test_license_policy.py::TestF14RegistryTrailingTagStrip::test_registry_tag_strips_to_family_admit[megvii/yolox:latest]',
    'test_license_policy.py::TestF14RegistryTrailingTagStrip::test_registry_tag_strips_to_family_admit[ppyoloe:latest]',
    'test_license_policy.py::TestF14RegistryTrailingTagStrip::test_registry_tag_strips_to_family_admit[yolox:latest]',
    'test_license_policy.py::TestF14RegistryTrailingTagStrip::test_registry_tag_strips_to_family_admit[yolox:v0.3.0]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_agpl_head_or_mid_plus_residual_denies[xyoloxyoloextra-yolo]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_agpl_head_or_mid_plus_residual_denies[yolov8yoloxcoco-yolov8]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_agpl_head_or_mid_plus_residual_denies[yolov8yoloxextra-yolov8]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_catalog_admits_unaffected[ppyoloe_s]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_catalog_admits_unaffected[yolox_pt_trt]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_catalog_admits_unaffected[yolox_s_8xb8-300e_coco]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_exact_exception_rem_still_denies[arcfaceyoloxx-arcface]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_junk_plus_legit_compact_still_admits[ayoloxs]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_junk_plus_legit_compact_still_admits[myyoloxs]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_junk_plus_legit_compact_still_admits[xyoloxs]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_nc_head_exception_plus_residual_denies[arcfaceyoloxcoco-arcface]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_nc_head_exception_plus_residual_denies[arcfaceyoloxextra-arcface]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_nc_head_exception_plus_residual_denies[arcfaceyoloxinsight-arcface]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_nc_head_exception_plus_residual_denies[insightfaceyoloxextra-insightface]',
    'test_license_policy.py::TestF14SuffixTolerantGlue::test_red_proof_suffix_tolerant_glue_neuter',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_control_char_is_invalid_row[yolo\\x00v8]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_control_char_is_invalid_row[yolox\\x00yolo]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_non_nfkc_dashes_still_invalid_row',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_red_proof_total_ascii_punct_fold_neuter',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_admit_controls_hold[ppyoloe+]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_admit_controls_hold[ppyoloe+_crn_s_80e_coco]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_admit_controls_hold[yolodummy]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_admit_controls_hold[yolox:s]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_admit_controls_hold[yolox_s+trt]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_agpl_denies_honest[(yolov8)-yolov8]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_agpl_denies_honest[yolo,v8-yolo_v8]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_agpl_denies_honest[yolo\\uff0cv8-yolo_v8]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_agpl_denies_honest[yolov8,-yolov8]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_agpl_denies_honest[yolov8;seg-yolov8]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_agpl_denies_honest[yolox!yolo-yolo]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_agpl_denies_honest[yolox\\uff5eyolo-yolo]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_agpl_denies_honest[yolox~yolo-yolo]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_br28_floor_only_unchanged',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_existing_deny_controls_hold[yolox+yolo-yolo]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_nc_denies_on_doors[arcface,r100-arcface_r100]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_nc_denies_on_doors[arcface~yolox-arcface]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_nc_denies_on_doors[buffalo,l-buffalo_l]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_nc_denies_on_doors[buffalo_l~yolox-buffalo_l]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_nc_denies_on_doors[insightface~yolox-insightface]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_nc_denies_on_doors[scrfd,10g-scrfd_10g]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_nc_denies_on_doors[yolox&buffalo_l-buffalo_l]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_nc_denies_on_doors[yolox(insightface)-insightface]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_nc_denies_on_doors[yolox[insightface]-insightface]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_nc_denies_on_doors[yolox~insightface-insightface]',
    'test_license_policy.py::TestF14TotalAsciiPunctFold::test_total_fold_unknown_residual_denies[yoloxpt~trt]',
    'test_license_policy.py::TestF15AsciiWhitespaceAndControlDetail::test_nul_invalid_row_names_control_character',
    'test_license_policy.py::TestF15AsciiWhitespaceAndControlDetail::test_red_proof_whitespace_fold_neuter',
    'test_license_policy.py::TestF15AsciiWhitespaceAndControlDetail::test_tab_and_lf_fold_as_separators',
    'test_license_policy.py::TestF15CompactRemCoverage::test_deny_head_long_rem_denies[vendor/yolov4tiny-yolov4]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_deny_head_long_rem_denies[yolov3tiny-yolov3]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_deny_head_long_rem_denies[yolov4tiny-yolov4]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_deny_head_long_rem_denies[yolov4tiny.pt-yolov4]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_deny_head_long_rem_denies[yolov7tiny-yolov7]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_existing_compact_and_separator_denies_hold[yolov4_tiny-yolov4]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_existing_compact_and_separator_denies_hold[yolov8seg-yolov8]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_existing_compact_and_separator_denies_hold[yoloyolox-yolo]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_four_char_head_suffix_tolerant_denies[yoloyolo-yolo]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_four_char_head_suffix_tolerant_denies[yoloyolosextra-yolo]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_four_char_head_suffix_tolerant_denies[yoloyoloxcoco-yolo]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_four_char_head_suffix_tolerant_denies[yoloyoloxextra-yolo]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_four_char_head_suffix_tolerant_denies[yoloyoloxpt-yolo]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_four_char_head_suffix_tolerant_denies[yoloyoloxtiny-yolo]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_four_char_head_suffix_tolerant_denies[yoloyoloxv8-yolo]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_four_char_unknown_rem_still_admits[myyolo]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_four_char_unknown_rem_still_admits[yolodummy]',
    'test_license_policy.py::TestF15CompactRemCoverage::test_red_proof_four_char_suffix_tolerant_neuter',
    'test_license_policy.py::TestF15CompactRemCoverage::test_red_proof_long_rem_neuter',
    'test_license_policy.py::TestF15CompactRemCoverage::test_yolobuffalo_l_is_yolo_head_plus_known_rem',
    'test_license_policy.py::TestF15DenyReasonHonesty::test_paddlepaddle_pp_yoloe_admits_via_vendor_merge',
    'test_license_policy.py::TestF15DenyReasonHonesty::test_pp_yolo_and_pp_yolov8_unchanged',
    'test_license_policy.py::TestF15DenyReasonHonesty::test_pp_yolo_nas_is_deci_nc_not_ppyolo_residual',
    'test_license_policy.py::TestF15DenyReasonHonesty::test_red_proof_exception_spelling_glue_neuter',
    'test_license_policy.py::TestF15DenyReasonHonesty::test_red_proof_ppyolo_nas_residual_neuter',
    'test_license_policy.py::TestF15DenyReasonHonesty::test_yoloppyoloe_is_yolo_plus_exception_spelling',
    'test_license_policy.py::TestF15DenyReasonHonesty::test_yoloppyoloeplus_is_yolo_plus_exception_spelling',
    'test_license_policy.py::TestF15EmptyCanonicalIdentity::test_empty_canonical_identity_is_invalid_row[...:latest]',
    'test_license_policy.py::TestF15EmptyCanonicalIdentity::test_empty_canonical_identity_is_invalid_row[///]',
    'test_license_policy.py::TestF15EmptyCanonicalIdentity::test_empty_canonical_identity_is_invalid_row[/:latest]',
    'test_license_policy.py::TestF15EmptyCanonicalIdentity::test_empty_canonical_identity_is_invalid_row[/]',
    'test_license_policy.py::TestF15EmptyCanonicalIdentity::test_empty_canonical_identity_is_invalid_row[:latest:latest]',
    'test_license_policy.py::TestF15EmptyCanonicalIdentity::test_empty_canonical_identity_is_invalid_row[:latest]',
    'test_license_policy.py::TestF15EmptyCanonicalIdentity::test_red_proof_empty_canonical_identity_neuter',
    'test_license_policy.py::TestF15EmptyCanonicalIdentity::test_whitespace_only_keeps_existing_empty_field_behaviour',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_bare_buffalo_exclusions_still_admit[aabuffalo]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_bare_buffalo_exclusions_still_admit[buffalo_bill_detector]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_bare_buffalo_exclusions_still_admit[buffalo_lakes]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_both_sides_junk_nc_floor_denies[aaarcfaceaa-arcface]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_both_sides_junk_nc_floor_denies[aainsightfaceaa-insightface]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_f15_1_must_list_same_path_still_floor_denies',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_junk_multi_seg_nc_floor_denies[aaantelope_v2-antelope_v2]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_junk_multi_seg_nc_floor_denies[aabuffalo_l-buffalo_l]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_junk_multi_seg_nc_floor_denies[aabuffalo_trt-buffalo_trt]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_junk_multi_seg_nc_floor_denies[aayolo_nas-yolo_nas]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_junk_multi_seg_nc_floor_denies[aayolo_nas_l-yolo_nas_l]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_junk_multi_seg_nc_floor_denies[xyolo_nas_pose_l-yolo_nas_pose_l]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_my_buffalo_l_still_denies_on_doors',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_no_exception_stays_door_pass[aaayolonas]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_no_exception_stays_door_pass[aabuffalo_l]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_no_exception_stays_door_pass[aainsightface]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_no_exception_stays_door_pass[myarcface]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_no_exception_stays_door_pass[not-insightface]',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_red_proof_compact_joined_rule_e_neuter',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_red_proof_mid_nc_occurrence_neuter',
    'test_license_policy.py::TestF15JunkMultiSegmentNcFloor::test_trailing_exception_promotes_junk_nc_to_door[aabuffalo_l_yolox-buffalo_l]',
    'test_license_policy.py::TestF15MidExceptionUnknownRem::test_mid_exception_legit_tag_still_admits[ayoloxs]',
    'test_license_policy.py::TestF15MidExceptionUnknownRem::test_mid_exception_legit_tag_still_admits[xyoloxs]',
    'test_license_policy.py::TestF15MidExceptionUnknownRem::test_mid_exception_unknown_rem_denies[myyoloxsextra]',
    'test_license_policy.py::TestF15MidExceptionUnknownRem::test_mid_exception_unknown_rem_denies[xyoloxsextra]',
    'test_license_policy.py::TestF15MidExceptionUnknownRem::test_offset0_unknown_still_denies',
    'test_license_policy.py::TestF15MidExceptionUnknownRem::test_red_proof_mid_exception_unknown_rem_neuter',
    'test_license_policy.py::TestF15PaddleModelFileExtensions::test_compact_glue_controls_stay_deny',
    'test_license_policy.py::TestF15PaddleModelFileExtensions::test_deny_seed_plus_pd_extension_still_denies[fastsam.pdparams-fastsam]',
    'test_license_policy.py::TestF15PaddleModelFileExtensions::test_deny_seed_plus_pd_extension_still_denies[yolov8.pdmodel-yolov8]',
    'test_license_policy.py::TestF15PaddleModelFileExtensions::test_deny_seed_plus_pd_extension_still_denies[yolov8.pdparams-yolov8]',
    'test_license_policy.py::TestF15PaddleModelFileExtensions::test_pdparams_pdmodel_strip_admits[ppyolo_r50vd_dcn_1x_coco.pdparams]',
    'test_license_policy.py::TestF15PaddleModelFileExtensions::test_pdparams_pdmodel_strip_admits[ppyoloe_plus_crn_s_80e_coco.pdmodel]',
    'test_license_policy.py::TestF15PaddleModelFileExtensions::test_pdparams_pdmodel_strip_admits[ppyoloe_plus_crn_s_80e_coco.pdparams]',
    'test_license_policy.py::TestF15PaddleModelFileExtensions::test_pdparams_pdmodel_strip_admits[weights/ppyoloe_plus_crn_s_80e_coco.pdparams]',
    'test_license_policy.py::TestF15PaddleModelFileExtensions::test_red_proof_pd_extensions_dropped',
    'test_license_policy.py::TestF15PpYoloeRRotateFamily::test_compact_glue_stays_deny[ppyolodota]',
    'test_license_policy.py::TestF15PpYoloeRRotateFamily::test_compact_glue_stays_deny[ppyoloer]',
    'test_license_policy.py::TestF15PpYoloeRRotateFamily::test_ppyoloe_r_catalog_admits[PP-YOLOE-R]',
    'test_license_policy.py::TestF15PpYoloeRRotateFamily::test_ppyoloe_r_catalog_admits[ppyoloe_r_crn_l_3x_dota]',
    'test_license_policy.py::TestF15PpYoloeRRotateFamily::test_ppyoloe_r_catalog_admits[ppyoloe_r_crn_s_3x_dota]',
    'test_license_policy.py::TestF15PpYoloeRRotateFamily::test_ppyoloe_r_catalog_admits[ppyoloe_r_crn_x_3x_dota]',
    'test_license_policy.py::TestF15PpYoloeRRotateFamily::test_red_proof_dota_tag_drop',
    'test_license_policy.py::TestF15PpYoloeRRotateFamily::test_yolof_3x_stays_native_admit',
    'test_license_policy.py::TestF15PpYoloeRRotateFamily::test_yolox_dota_does_not_leak',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_deny_seed_plus_registry_tag_still_denies[yolo:latest-yolo]',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_deny_seed_plus_registry_tag_still_denies[yolov8:v8-yolov8]',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_latest_and_dotted_versions_still_admit[megvii/yolox:v0.3.0]',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_latest_and_dotted_versions_still_admit[paddledetection/ppyoloe:latest]',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_latest_and_dotted_versions_still_admit[yolox:latest]',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_latest_and_dotted_versions_still_admit[yolox:v2.1]',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_red_proof_single_number_strip_restored',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_single_number_tag_fail_closes[ppyolo:v8-ppyolo_unknown_residual]',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_single_number_tag_fail_closes[yolox:8-yolox_unknown_residual]',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_single_number_tag_fail_closes[yolox:v2-yolox_unknown_residual]',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_single_number_tag_fail_closes[yolox:v5-yolox_unknown_residual]',
    'test_license_policy.py::TestF15RegistrySingleNumberTag::test_single_number_tag_fail_closes[yolox:v8-yolox_unknown_residual]',
    'test_license_policy.py::TestF16EmptyIdentityHonestyAndStackedTags::test_ingest_tooling_floor_use_empty_identity_wording',
    'test_license_policy.py::TestF16EmptyIdentityHonestyAndStackedTags::test_red_proof_stacked_tag_single_strip',
    'test_license_policy.py::TestF16EmptyIdentityHonestyAndStackedTags::test_stacked_latest_tags_are_empty_identity',
    'test_license_policy.py::TestF16EmptyIdentityHonestyAndStackedTags::test_yolox_stacked_latest_still_admits',
    'test_license_policy.py::TestF16NasResidualAttribution::test_english_nas_prefix_is_not_deci[pp_yolo_nasal]',
    'test_license_policy.py::TestF16NasResidualAttribution::test_english_nas_prefix_is_not_deci[pp_yolo_nashville]',
    'test_license_policy.py::TestF16NasResidualAttribution::test_english_nas_prefix_is_not_deci[pp_yolo_nasls]',
    'test_license_policy.py::TestF16NasResidualAttribution::test_english_nas_prefix_is_not_deci[pp_yolo_naso]',
    'test_license_policy.py::TestF16NasResidualAttribution::test_known_nas_residual_is_deci_nc[pp_yolo_nas]',
    'test_license_policy.py::TestF16NasResidualAttribution::test_known_nas_residual_is_deci_nc[pp_yolo_nas_l]',
    'test_license_policy.py::TestF16NasResidualAttribution::test_known_nas_residual_is_deci_nc[pp_yolo_nass]',
    'test_license_policy.py::TestF16NasResidualAttribution::test_known_nas_residual_is_deci_nc[ppyoloenas]',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_non_vendor_pp_yoloe_still_denies[model_pp_yoloe-yolo]',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_non_vendor_pp_yoloe_still_denies[paddles_pp_yoloe-yolo]',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_non_vendor_pp_yoloe_still_denies[v2_pp_yoloe-yolo]',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_non_vendor_pp_yoloe_still_denies[weights_pp_yoloe-yolo]',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_paddle_vendor_segment_set_is_pinned',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_vendor_pp_yoloe_admits[baidu_pp_yoloe]',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_vendor_pp_yoloe_admits[paddle_pp_yoloe]',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_vendor_pp_yoloe_admits[paddledet_pp_yoloe]',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_vendor_pp_yoloe_admits[paddledetection_pp_yoloe]',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_vendor_pp_yoloe_admits[paddlepaddle_pp_yoloe]',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_vendor_pp_yoloe_admits[pp_yoloe]',
    'test_license_policy.py::TestF16PaddleVendorMerge::test_vendor_pp_yoloe_admits[ppdet_pp_yoloe]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_agpl_stem_junk_infix_exception_denies[fastsamxppyoloeextra-fastsam]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_agpl_stem_junk_infix_exception_denies[fastsamxyolox-fastsam]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_agpl_stem_junk_infix_exception_denies[fastsamxyoloxextra-fastsam]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_agpl_stem_junk_infix_exception_denies[fastsamxyoloxs-fastsam]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_agpl_stem_junk_infix_exception_denies[yolo11xyoloxextra-yolo11]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_agpl_stem_junk_infix_exception_denies[yolorxyoloxextra-yolor]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_agpl_stem_junk_infix_exception_denies[yolov5zyoloxsfoo-yolov5]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_agpl_stem_junk_infix_exception_denies[yoloworldxyoloxextra-yolo_world]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_classify_owned_unknown_rem_controls_hold[buffalo_lxyoloxextra-yolox_unknown_residual]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_classify_owned_unknown_rem_controls_hold[buffalo_lxyoloxlatest-yolox_unknown_residual]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_classify_owned_unknown_rem_controls_hold[xyoloxsextra-yolox_unknown_residual]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_classify_owned_unknown_rem_controls_hold[yoloyoloxextra-yolo]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_elevated_and_exact_prefix_controls_hold[arcfaceyoloxextra-arcface]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_elevated_and_exact_prefix_controls_hold[fastsamx-fastsam]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_legit_f15_5_admits_hold[ayoloxs]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_legit_f15_5_admits_hold[xyoloxs]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_nc_stem_junk_infix_exception_denies[arcfacexyoloxextra-arcface]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_nc_stem_junk_infix_exception_denies[retinafacexyoloxextra-retinaface]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_nc_stem_junk_infix_exception_denies[scrfdxyoloxextra-scrfd]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_nc_stem_junk_infix_exception_denies[vec2facexyoloxextra-vec2face]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_nc_stem_junk_infix_exception_denies[yolonasxyoloxextra-yolo_nas]',
    'test_license_policy.py::TestF16PrefixDenyLaundering::test_red_proof_mid_exception_unknown_rem_neuter_gadgets',
    'test_license_policy.py::TestF16StealHonestyPin::test_red_proof_steal_flag_turns_fastsam_residual_red',
    'test_license_policy.py::TestF16StealHonestyPin::test_steal_names_fastsam_residual_honest',
    'test_license_policy.py::TestF17StackedExceptionStemAttribution::test_fastsam_stacked_exception_names_stem',
    'test_license_policy.py::TestF17StackedExceptionStemAttribution::test_junk_prefix_stacked_exception_stays_yolo',
    'test_license_policy.py::TestF17StackedExceptionStemAttribution::test_red_proof_stem_over_exc_rem_neuter',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_a3_must_stay_deny_fence',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_a4_must_stay_admit_fence',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_four_plus_suffix_junk_without_exception_is_floor_miss',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_full_cross_product_sweep_denies',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_full_rem_tail_cross_product_sweep_denies',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_glued_rem_stays_unknown_residual',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_listed_rem_tail_gadgets_deny[buffalo_lx_yolox_tiny-buffalo_l-nc]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_listed_rem_tail_gadgets_deny[buffalo_lxyolox:v8-buffalo_l-nc]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_listed_rem_tail_gadgets_deny[buffalo_lxyolox_extra-buffalo_l-nc]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_listed_rem_tail_gadgets_deny[buffalo_lxyolox_onnx-buffalo_l-nc]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_listed_rem_tail_gadgets_deny[buffalo_lxyolox_tiny-buffalo_l-nc]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_listed_rem_tail_gadgets_deny[buffalo_lxyolox_v8-buffalo_l-nc]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_listed_rem_tail_gadgets_deny[buffalolxyolox:v8-buffalo_l-nc]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_listed_rem_tail_gadgets_deny[fastsamxyolox:v8-fastsam-agpl]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_red_proof_mid_exception_unknown_rem_neuter_underscore',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_red_proof_separate_rem_owner_neuter',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_red_proof_underscore_glued_owner_neuter',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_glued_axes_deny[antelope_v2-abc-yolox-:v8]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_glued_axes_deny[buffalo_l-x-yolox-_v8]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_glued_axes_deny[buffalo_l2-v9-yoloxs-:v8]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_glued_axes_deny[buffalo_pt-abc-yolop-_tiny]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_glued_axes_deny[buffalo_s-abcd-yolos-_extra]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_glued_axes_deny[buffalo_sc-x-yolof-_onnx]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_glued_axes_deny[buffalo_trt-v9-ppyoloe-_v8]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_separator_twin_axes_deny[antelope_v2-abc-yolox-_onnx]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_separator_twin_axes_deny[buffalo_l-x-yolox-_tiny]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_separator_twin_axes_deny[buffalo_l2-v9-yoloxs-_v8]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_separator_twin_axes_deny[buffalo_pt-abc-yolop-:v8]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_separator_twin_axes_deny[buffalo_s-abcd-yolos-_onnx]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_separator_twin_axes_deny[buffalo_sc-x-yolof-_extra]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_rem_tail_separator_twin_axes_deny[buffalo_trt-v9-ppyoloe-_tiny]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_representative_seed_junk_spelling_denies[antelope_v2-abc-yolox]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_representative_seed_junk_spelling_denies[buffalo_l-x-yolox]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_representative_seed_junk_spelling_denies[buffalo_l2-v9-yoloxs]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_representative_seed_junk_spelling_denies[buffalo_pt-abc-yolop]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_representative_seed_junk_spelling_denies[buffalo_s-abcd-yolos]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_representative_seed_junk_spelling_denies[buffalo_sc-x-yolof]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_representative_seed_junk_spelling_denies[buffalo_trt-v9-ppyoloe]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_variant_shapes_deny[BUFFALO_TRTXYOLOX-buffalo_trt]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_variant_shapes_deny[Buffalo_LXYoloX-buffalo_l]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_variant_shapes_deny[antelope_v2x_yolox-antelope_v2]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_variant_shapes_deny[antelope_v2xyolox_s-antelope_v2]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_variant_shapes_deny[buffalo-lxyolox-buffalo_l]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_variant_shapes_deny[buffalo_lx_yolox-buffalo_l]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_variant_shapes_deny[buffalo_lxyolox:latest-buffalo_l]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_variant_shapes_deny[buffalo_lxyolox_s-buffalo_l]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_variant_shapes_deny[buffalo_scabcyolox:v0.3.0-buffalo_sc]',
    'test_license_policy.py::TestF17UnderscoreNcSeedGluedException::test_variant_shapes_deny[buffalo_sx_yoloxs-buffalo_s]',
    'test_license_policy.py::TestFloorLicenceIsOptionalNotWaived::test_absent_license_does_not_waive_the_denylist',
    'test_license_policy.py::TestFloorLicenceIsOptionalNotWaived::test_registry_sourced_row_without_license_key_passes',
    'test_license_policy.py::TestFloorLicenceIsOptionalNotWaived::test_unregistered_id_without_license_still_fails_closed',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_allowlisted_licence_under_a_variant_spelling_still_passes',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[model_ingest-LICENSE]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[model_ingest-Licence]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[model_ingest-License]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[model_ingest-SPDX-ID]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[model_ingest-licence]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[model_ingest-license]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[model_ingest-spdx]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[model_ingest-spdx_id]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[tooling-LICENSE]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[tooling-Licence]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[tooling-License]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[tooling-SPDX-ID]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[tooling-licence]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[tooling-license]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[tooling-spdx]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_denylisted_licence_caught_under_every_spelling[tooling-spdx_id]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_non_licence_keys_are_untouched[model_family]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_non_licence_keys_are_untouched[notes]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_non_licence_keys_are_untouched[verified_at]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_non_string_under_an_alias_is_invalid',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_unrecognised_licence_shaped_key_fails_closed[licence_url]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_unrecognised_licence_shaped_key_fails_closed[license_notes]',
    'test_license_policy.py::TestGate04LicenceKeySpellingAndCasing::test_unrecognised_licence_shaped_key_fails_closed[spdx_comment]',
    'test_license_policy.py::TestGate06FloorCategoryPropagatedOnEveryDoor::test_floor_rejection_carries_requested_category[model_ingest]',
    'test_license_policy.py::TestGate06FloorCategoryPropagatedOnEveryDoor::test_floor_rejection_carries_requested_category[occluder_asset]',
    'test_license_policy.py::TestGate06FloorCategoryPropagatedOnEveryDoor::test_floor_rejection_carries_requested_category[synthetic_source]',
    'test_license_policy.py::TestGate06FloorCategoryPropagatedOnEveryDoor::test_floor_rejection_carries_requested_category[tooling]',
    'test_license_policy.py::TestGate06FloorCategoryPropagatedOnEveryDoor::test_floor_rejection_carries_requested_category[training_data]',
    'test_license_policy.py::TestGate07PathShapedResearchDerived::test_non_research_path_shaped_derived_is_not_research',
    'test_license_policy.py::TestGate07PathShapedResearchDerived::test_path_shaped_research_derived_fails[ffhq/dcface]',
    'test_license_policy.py::TestGate07PathShapedResearchDerived::test_path_shaped_research_derived_fails[myorg/ffhq]',
    'test_license_policy.py::TestGate07PathShapedResearchDerived::test_path_shaped_research_derived_fails[widerface/yunet]',
    'test_license_policy.py::TestGate08OccluderLicenseDetailContext::test_missing_and_invalid_share_detail_prefix_shape',
    'test_license_policy.py::TestGate08OccluderLicenseDetailContext::test_missing_license_field_detail_has_occluder_prefix',
    'test_license_policy.py::TestGate08OccluderLicenseDetailContext::test_present_but_invalid_license_detail_has_occluder_prefix',
    'test_license_policy.py::TestGate09MultiFaultPrecedencePinned::test_multi_fault_reports_documented_winner[model_ingest-row0-unknown_spdx]',
    'test_license_policy.py::TestGate09MultiFaultPrecedencePinned::test_multi_fault_reports_documented_winner[occluder_asset-row4-unknown_spdx]',
    'test_license_policy.py::TestGate09MultiFaultPrecedencePinned::test_multi_fault_reports_documented_winner[tooling-row1-denylisted_package]',
    'test_license_policy.py::TestGate09MultiFaultPrecedencePinned::test_multi_fault_reports_documented_winner[tooling-row6-unregistered_derived_model]',
    'test_license_policy.py::TestGate09MultiFaultPrecedencePinned::test_multi_fault_reports_documented_winner[training_data-row2-pending_legal_clearance]',
    'test_license_policy.py::TestGate09MultiFaultPrecedencePinned::test_multi_fault_reports_documented_winner[training_data-row3-nc_model_derived]',
    'test_license_policy.py::TestGate09MultiFaultPrecedencePinned::test_multi_fault_reports_documented_winner[training_data-row5-pending_legal_clearance]',
    'test_license_policy.py::TestGate10CompoundSpdxDenylistReason::test_gate10_bare_allowlisted_still_passes',
    'test_license_policy.py::TestGate10CompoundSpdxDenylistReason::test_gate10_or_with_denylisted_component_cannot_pass',
    'test_license_policy.py::TestGate10CompoundSpdxDenylistReason::test_gate10_verified_repro_reasons[AGPL-3.0 WITH Classpath-exception-2.0-denylisted_license]',
    'test_license_policy.py::TestGate10CompoundSpdxDenylistReason::test_gate10_verified_repro_reasons[AGPL-3.0+-denylisted_license]',
    'test_license_policy.py::TestGate10CompoundSpdxDenylistReason::test_gate10_verified_repro_reasons[AGPL-3.0-denylisted_license]',
    'test_license_policy.py::TestGate10CompoundSpdxDenylistReason::test_gate10_verified_repro_reasons[Apache-2.0 OR AGPL-3.0-denylisted_license]',
    'test_license_policy.py::TestGate10CompoundSpdxDenylistReason::test_gate10_verified_repro_reasons[MIT OR CC-BY-NC-4.0-research_only_license]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_cleared_dcface_passes_admitting_doors[model_ingest]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_cleared_dcface_passes_admitting_doors[synthetic_source]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_cleared_dcface_passes_admitting_doors[tooling]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_cleared_dcface_passes_admitting_doors[training_data]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_cleared_dcface_still_fails_occluder_without_photo_clearance',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_cleared_dcface_with_photo_clearance_passes_occluder',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_derived_from_model_dcface_also_triggers_floor[model_ingest]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_derived_from_model_dcface_also_triggers_floor[tooling]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_source_without_clearance_decision_unaffected[model_ingest]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_source_without_clearance_decision_unaffected[occluder_asset]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_source_without_clearance_decision_unaffected[synthetic_source]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_source_without_clearance_decision_unaffected[tooling]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_source_without_clearance_decision_unaffected[training_data]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_uncleared_dcface_fails_every_door_with_exact_reason[model_ingest]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_uncleared_dcface_fails_every_door_with_exact_reason[occluder_asset]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_uncleared_dcface_fails_every_door_with_exact_reason[synthetic_source]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_uncleared_dcface_fails_every_door_with_exact_reason[tooling]',
    'test_license_policy.py::TestGate11ClearanceFloorOnEveryDoor::test_uncleared_dcface_fails_every_door_with_exact_reason[training_data]',
    'test_license_policy.py::TestGate16ClearanceAxesNotInterchangeable::test_dcface_token_on_photo_clearance_does_not_satisfy_lineage[model_ingest]',
    'test_license_policy.py::TestGate16ClearanceAxesNotInterchangeable::test_dcface_token_on_photo_clearance_does_not_satisfy_lineage[occluder_asset]',
    'test_license_policy.py::TestGate16ClearanceAxesNotInterchangeable::test_dcface_token_on_photo_clearance_does_not_satisfy_lineage[synthetic_source]',
    'test_license_policy.py::TestGate16ClearanceAxesNotInterchangeable::test_dcface_token_on_photo_clearance_does_not_satisfy_lineage[tooling]',
    'test_license_policy.py::TestGate16ClearanceAxesNotInterchangeable::test_dcface_token_on_photo_clearance_does_not_satisfy_lineage[training_data]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[DCFACE-model_ingest]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[DCFACE-occluder_asset]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[DCFACE-synthetic_source]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[DCFACE-tooling]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[DCFACE-training_data]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[allowed-model_ingest]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[allowed-occluder_asset]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[allowed-synthetic_source]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[allowed-tooling]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[allowed-training_data]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[cleared-model_ingest]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[cleared-occluder_asset]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[cleared-synthetic_source]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[cleared-tooling]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[cleared-training_data]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[operator_cleared-model_ingest]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[operator_cleared-occluder_asset]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[operator_cleared-synthetic_source]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[operator_cleared-tooling]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_lineage[operator_cleared-training_data]',
    'test_license_policy.py::TestGate17RetiredClearanceKeyInert::test_legacy_clearance_key_never_satisfies_photo_axis',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[1.5-derived_from_model-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[1.5-derived_from_model-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[1.5-derived_from_model-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[1.5-derived_from_model-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[1.5-derived_from_model-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[1.5-source-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[1.5-source-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[1.5-source-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[1.5-source-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[1.5-source-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[123-derived_from_model-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[123-derived_from_model-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[123-derived_from_model-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[123-derived_from_model-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[123-derived_from_model-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[123-source-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[123-source-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[123-source-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[123-source-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[123-source-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[None-derived_from_model-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[None-derived_from_model-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[None-derived_from_model-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[None-derived_from_model-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[None-derived_from_model-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[None-source-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[None-source-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[None-source-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[None-source-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[None-source-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[dcface-derived_from_model-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[dcface-derived_from_model-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[dcface-derived_from_model-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[dcface-derived_from_model-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[dcface-derived_from_model-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[dcface-source-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[dcface-source-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[dcface-source-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[dcface-source-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[dcface-source-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value0-derived_from_model-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value0-derived_from_model-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value0-derived_from_model-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value0-derived_from_model-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value0-derived_from_model-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value0-source-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value0-source-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value0-source-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value0-source-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value0-source-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value3-derived_from_model-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value3-derived_from_model-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value3-derived_from_model-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value3-derived_from_model-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value3-derived_from_model-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value3-source-model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value3-source-occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value3-source-synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value3-source-tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_floor_rejects_non_string_field[value3-source-training_data]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_well_typed_clean_row_is_not_invalid_row[model_ingest]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_well_typed_clean_row_is_not_invalid_row[occluder_asset]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_well_typed_clean_row_is_not_invalid_row[synthetic_source]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_well_typed_clean_row_is_not_invalid_row[tooling]',
    'test_license_policy.py::TestGate19Br68FloorTypeCheckPinned::test_well_typed_clean_row_is_not_invalid_row[training_data]',
    'test_license_policy.py::TestGate20FloorPrecedenceAdjacentPairs::test_clearance_outranks_package_denylist',
    'test_license_policy.py::TestGate20FloorPrecedenceAdjacentPairs::test_clearance_outranks_registration',
    'test_license_policy.py::TestGate20FloorPrecedenceAdjacentPairs::test_derived_taint_outranks_source_taint',
    'test_license_policy.py::TestGate20FloorPrecedenceAdjacentPairs::test_package_denylist_outranks_registration',
    'test_license_policy.py::TestGate20FloorPrecedenceAdjacentPairs::test_registration_outranks_licence',
    'test_license_policy.py::TestGate20FloorPrecedenceAdjacentPairs::test_source_taint_outranks_clearance',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_gate32_every_door_has_at_least_one_pass_witness[model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_gate32_every_door_has_at_least_one_pass_witness[occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_gate32_every_door_has_at_least_one_pass_witness[synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_gate32_every_door_has_at_least_one_pass_witness[tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_gate32_every_door_has_at_least_one_pass_witness[training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[0-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[0-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[0-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[0-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[0-training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[1-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[1-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[1-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[1-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[1-training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[10-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[10-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[10-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[10-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[10-training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[11-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[11-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[11-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[11-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[11-training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[2-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[2-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[2-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[2-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[2-training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[3-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[3-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[3-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[3-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[3-training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[4-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[4-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[4-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[4-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[4-training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[5-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[5-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[5-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[5-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[5-training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[6-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[6-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[6-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[6-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[6-training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[7-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[7-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[7-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[7-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[7-training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[8-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[8-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[8-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[8-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[8-training_data]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[9-model_ingest]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[9-occluder_asset]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[9-synthetic_source]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[9-tooling]',
    'test_license_policy.py::TestGate27FiveDoorCategoryInvariant::test_result_category_equals_asked_door[9-training_data]',
    'test_license_policy.py::TestGate27SyntheticBackstopCategoryLeak::test_clean_training_data_row_still_reports_training_data',
    'test_license_policy.py::TestGate27SyntheticBackstopCategoryLeak::test_floor_nc_rejection_still_reports_training_data',
    'test_license_policy.py::TestGate27SyntheticBackstopCategoryLeak::test_generator_lineage_backstop_keeps_training_data_category',
    'test_license_policy.py::TestGate28AllowedSpdxIdsPassWitnesses::test_isc_near_miss_still_rejected',
    'test_license_policy.py::TestGate28AllowedSpdxIdsPassWitnesses::test_isc_spdx_passes_training_data',
    'test_license_policy.py::TestGate28AllowedSpdxIdsPassWitnesses::test_unlicense_near_miss_still_rejected',
    'test_license_policy.py::TestGate28AllowedSpdxIdsPassWitnesses::test_unlicense_spdx_passes_training_data',
    'test_license_policy.py::TestGate28AllowedSpdxIdsPassWitnesses::test_zlib_near_miss_still_rejected',
    'test_license_policy.py::TestGate28AllowedSpdxIdsPassWitnesses::test_zlib_spdx_passes_training_data',
    'test_license_policy.py::TestGate29ToolingAllowlistPassWitnesses::test_llvmlite_near_miss_still_rejected',
    'test_license_policy.py::TestGate29ToolingAllowlistPassWitnesses::test_llvmlite_tooling_package_passes',
    'test_license_policy.py::TestGate29ToolingAllowlistPassWitnesses::test_tensorflow_near_miss_still_rejected',
    'test_license_policy.py::TestGate29ToolingAllowlistPassWitnesses::test_tensorflow_tooling_package_passes',
    'test_license_policy.py::TestGate30SfaceIngestPassWitness::test_sface_model_ingest_passes',
    'test_license_policy.py::TestGate30SfaceIngestPassWitness::test_sface_near_miss_opencv_sface_still_rejected',
    'test_license_policy.py::TestGate30SfaceIngestPassWitness::test_sface_near_miss_sface_v2_still_rejected',
    'test_license_policy.py::TestGate31OperatorOwnedSourcePassWitnesses::test_operator_phone_source_passes_training_data',
    'test_license_policy.py::TestGate31OperatorOwnedSourcePassWitnesses::test_operator_phone_underscore_form_rejected',
    'test_license_policy.py::TestGate31OperatorOwnedSourcePassWitnesses::test_operator_phone_v2_variant_rejected',
    'test_license_policy.py::TestGate31OperatorOwnedSourcePassWitnesses::test_operator_render_prefix_neighbour_rejected',
    'test_license_policy.py::TestGate31OperatorOwnedSourcePassWitnesses::test_operator_render_source_passes_training_data',
    'test_license_policy.py::TestGate31OperatorOwnedSourcePassWitnesses::test_operator_render_v2_variant_rejected',
    'test_license_policy.py::TestGate33PendingLegalClearanceSpdxBranch::test_gate33_audit_spdx_pending_legal_clearance_fails[PENDING-LEGAL-CLEARANCE]',
    'test_license_policy.py::TestGate33PendingLegalClearanceSpdxBranch::test_gate33_audit_spdx_pending_legal_clearance_fails[Pending-Legal-Clearance]',
    'test_license_policy.py::TestGate33PendingLegalClearanceSpdxBranch::test_gate33_audit_spdx_pending_legal_clearance_fails[pending-legal-clearance]',
    'test_license_policy.py::TestGate33PendingLegalClearanceSpdxBranch::test_gate33_model_ingest_row_pending_license_fails',
    'test_license_policy.py::TestGate33PendingLegalClearanceSpdxBranch::test_gate33_occluder_asset_row_pending_license_fails',
    'test_license_policy.py::TestGate33PendingLegalClearanceSpdxBranch::test_gate33_synthetic_source_row_pending_license_fails',
    'test_license_policy.py::TestGate33PendingLegalClearanceSpdxBranch::test_gate33_tooling_row_pending_license_fails',
    'test_license_policy.py::TestGate33PendingLegalClearanceSpdxBranch::test_gate33_training_data_row_pending_license_fails',
    'test_license_policy.py::TestGate34DerivedFromModelPackageDenylist::test_gate34_audit_derived_from_model_denylisted_package[path/ultralytics]',
    'test_license_policy.py::TestGate34DerivedFromModelPackageDenylist::test_gate34_audit_derived_from_model_denylisted_package[ultralytics]',
    'test_license_policy.py::TestGate34DerivedFromModelPackageDenylist::test_gate34_audit_derived_from_model_denylisted_package[yolo]',
    'test_license_policy.py::TestGate34DerivedFromModelPackageDenylist::test_gate34_audit_derived_from_model_denylisted_package[yolov8]',
    'test_license_policy.py::TestGate34DerivedFromModelPackageDenylist::test_gate34_training_data_row_derived_ultralytics_reason',
    'test_license_policy.py::TestLr04OccluderResearchSourceReasonPreservation::test_occluder_ffhq_reports_research_only_source',
    'test_license_policy.py::TestMultiLicenseFieldResolution::test_br35_agreeing_license_keys_pass',
    'test_license_policy.py::TestMultiLicenseFieldResolution::test_br35_disagreeing_license_and_spdx_id_fails',
    'test_license_policy.py::TestMultiLicenseFieldResolution::test_br35_secondary_only_agpl_still_fails',
    'test_license_policy.py::TestNamedIngestEntriesAndUltralyticsDeny::test_cascade_person_detector_ingest_passes[d_fine-D-FINE]',
    'test_license_policy.py::TestNamedIngestEntriesAndUltralyticsDeny::test_cascade_person_detector_ingest_passes[pp_picodet-PP-PicoDet]',
    'test_license_policy.py::TestNamedIngestEntriesAndUltralyticsDeny::test_cascade_person_detector_ingest_passes[rt_detr-RT-DETR]',
    'test_license_policy.py::TestNamedIngestEntriesAndUltralyticsDeny::test_denylisted_spdx_ingest_entry_fails',
    'test_license_policy.py::TestNamedIngestEntriesAndUltralyticsDeny::test_mediapipe_blazeface_ingest_passes',
    'test_license_policy.py::TestNamedIngestEntriesAndUltralyticsDeny::test_nc_tagged_ingest_entry_fails',
    'test_license_policy.py::TestNamedIngestEntriesAndUltralyticsDeny::test_paddle_blazeface_fpn_ssh_ingest_passes',
    'test_license_policy.py::TestNamedIngestEntriesAndUltralyticsDeny::test_required_display_names_registered',
    'test_license_policy.py::TestNamedIngestEntriesAndUltralyticsDeny::test_ultralytics_agpl_is_denylisted',
    'test_license_policy.py::TestNamedIngestEntriesAndUltralyticsDeny::test_unknown_model_missing_ingest_entry_fails',
    'test_license_policy.py::TestNamedIngestEntriesAndUltralyticsDeny::test_yolov8_agpl_family_denied',
    'test_license_policy.py::TestNcModelAlsoGatesSourceField::test_br20_nc_string_fails_from_either_field[arcface]',
    'test_license_policy.py::TestNcModelAlsoGatesSourceField::test_br20_nc_string_fails_from_either_field[buffalo_l]',
    'test_license_policy.py::TestNcModelAlsoGatesSourceField::test_br20_nc_string_fails_from_either_field[deepinsight/insightface]',
    'test_license_policy.py::TestNcModelAlsoGatesSourceField::test_br20_nc_string_fails_from_either_field[insightface/buffalo_l]',
    'test_license_policy.py::TestNcModelAlsoGatesSourceField::test_br20_nc_string_fails_from_either_field[retinaface]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_slash_form_controls_still_fail[arcface/r100]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_slash_form_controls_still_fail[insightface/buffalo_l]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_slash_form_controls_still_fail[retinaface/r50]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_slash_form_controls_still_fail[vec2face/g1]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_versioned_nc_ids_fail[arcface-r100]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_versioned_nc_ids_fail[arcface_glint360k_r100]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_versioned_nc_ids_fail[arcface_r100]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_versioned_nc_ids_fail[retinaface-r50]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_versioned_nc_ids_fail[retinaface_mnet025_v2]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_versioned_nc_ids_fail[retinaface_r50]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_versioned_nc_ids_fail[vec2face_g1]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_versioned_nc_ids_fail_in_composite_row[rt_detr/vec2face_g1]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br19_versioned_nc_ids_fail_in_composite_row[yunet/retinaface_r50]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_buffalo_version_suffixes_still_fail',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_controls_still_pass[arcface_alternative_v2]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_controls_still_pass[insightfaces-r-us/model]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_controls_still_pass[not-retinaface]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_controls_still_pass[retinaface-free-reimpl]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_controls_still_pass[sface/v1]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_legitimate_names_not_swept_as_nc[buffalo-wings-detector]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_legitimate_names_not_swept_as_nc[buffalo_bill_detector]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_legitimate_names_not_swept_as_nc[buffalos-eye/v1]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_legitimate_names_not_swept_as_nc[insightface-free]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_legitimate_names_not_swept_as_nc[my-buffalo-free]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_legitimate_names_not_swept_as_nc[not-insightface]',
    'test_license_policy.py::TestNcModelMatcherPrecision::test_br28_legitimate_names_not_swept_as_nc[sface/buffalo-wings-detector]',
    'test_license_policy.py::TestOccluderAssetPackBuildGate::test_cleared_occluder_asset_passes',
    'test_license_policy.py::TestOccluderAssetPackBuildGate::test_missing_clearance_fails',
    'test_license_policy.py::TestOccluderAssetPackBuildGate::test_missing_license_field_fails',
    'test_license_policy.py::TestOccluderAssetPackBuildGate::test_missing_source_fails',
    'test_license_policy.py::TestOccluderAssetPackBuildGate::test_operator_cleared_license_not_accepted_on_occluder',
    'test_license_policy.py::TestOccluderAssetPackBuildGate::test_uncleared_source_photo_fails',
    'test_license_policy.py::TestOccluderAssetPackBuildGate::test_unknown_source_fails',
    'test_license_policy.py::TestPolicyEnumsAndHardFail::test_clearance_status_includes_folded_literals',
    'test_license_policy.py::TestPolicyEnumsAndHardFail::test_detector_role_strenum',
    'test_license_policy.py::TestPolicyEnumsAndHardFail::test_rejection_reasons_are_strenum',
    'test_license_policy.py::TestPolicyEnumsAndHardFail::test_require_pass_raises_on_fail',
    'test_license_policy.py::TestPolicyEnumsAndHardFail::test_require_pass_returns_on_pass',
    'test_license_policy.py::TestPolicyEnumsAndHardFail::test_verdicts_are_strenum',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[123-model_ingest]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[123-occluder_asset]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[123-synthetic_source]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[123-tooling]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[123-training_data]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[bad_cat1-model_ingest]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[bad_cat1-occluder_asset]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[bad_cat1-synthetic_source]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[bad_cat1-tooling]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[bad_cat1-training_data]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[bad_cat2-model_ingest]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[bad_cat2-occluder_asset]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[bad_cat2-synthetic_source]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[bad_cat2-tooling]',
    'test_license_policy.py::TestRd01NonStringRowCategory::test_non_string_row_category_is_invalid_row[bad_cat2-training_data]',
    'test_license_policy.py::TestRd02CategoryParameterTypeGuard::test_non_policy_category_type_is_invalid_row[123]',
    'test_license_policy.py::TestRd02CategoryParameterTypeGuard::test_non_policy_category_type_is_invalid_row[bad_category1]',
    'test_license_policy.py::TestRd02CategoryParameterTypeGuard::test_non_policy_category_type_is_invalid_row[bad_category2]',
    'test_license_policy.py::TestRd02CategoryParameterTypeGuard::test_string_category_value_is_invalid_row[model_ingest]',
    'test_license_policy.py::TestRd02CategoryParameterTypeGuard::test_string_category_value_is_invalid_row[occluder_asset]',
    'test_license_policy.py::TestRd02CategoryParameterTypeGuard::test_string_category_value_is_invalid_row[synthetic_source]',
    'test_license_policy.py::TestRd02CategoryParameterTypeGuard::test_string_category_value_is_invalid_row[tooling]',
    'test_license_policy.py::TestRd02CategoryParameterTypeGuard::test_string_category_value_is_invalid_row[training_data]',
    'test_license_policy.py::TestRd03LicenseFieldNoneArm::test_none_license_field_is_invalid_row[license-model_ingest]',
    'test_license_policy.py::TestRd03LicenseFieldNoneArm::test_none_license_field_is_invalid_row[license-occluder_asset]',
    'test_license_policy.py::TestRd03LicenseFieldNoneArm::test_none_license_field_is_invalid_row[license-synthetic_source]',
    'test_license_policy.py::TestRd03LicenseFieldNoneArm::test_none_license_field_is_invalid_row[license-tooling]',
    'test_license_policy.py::TestRd03LicenseFieldNoneArm::test_none_license_field_is_invalid_row[license-training_data]',
    'test_license_policy.py::TestRd03LicenseFieldNoneArm::test_none_license_field_is_invalid_row[spdx_id-model_ingest]',
    'test_license_policy.py::TestRd03LicenseFieldNoneArm::test_none_license_field_is_invalid_row[spdx_id-occluder_asset]',
    'test_license_policy.py::TestRd03LicenseFieldNoneArm::test_none_license_field_is_invalid_row[spdx_id-synthetic_source]',
    'test_license_policy.py::TestRd03LicenseFieldNoneArm::test_none_license_field_is_invalid_row[spdx_id-tooling]',
    'test_license_policy.py::TestRd03LicenseFieldNoneArm::test_none_license_field_is_invalid_row[spdx_id-training_data]',
    'test_license_policy.py::TestRd04OccluderNonMappingAndAsymmetry::test_non_mapping_returns_invalid_row[42]',
    'test_license_policy.py::TestRd04OccluderNonMappingAndAsymmetry::test_non_mapping_returns_invalid_row[None]',
    'test_license_policy.py::TestRd04OccluderNonMappingAndAsymmetry::test_non_mapping_returns_invalid_row[a-string]',
    'test_license_policy.py::TestRd04OccluderNonMappingAndAsymmetry::test_non_mapping_returns_invalid_row[bad_asset1]',
    'test_license_policy.py::TestRd04OccluderNonMappingAndAsymmetry::test_raise_vs_return_asymmetry_across_entry_points',
    'test_license_policy.py::TestRd05OccluderPhotoClearanceType::test_non_string_photo_clearance_is_invalid_row[123]',
    'test_license_policy.py::TestRd05OccluderPhotoClearanceType::test_non_string_photo_clearance_is_invalid_row[bad_pc1]',
    'test_license_policy.py::TestRd05OccluderPhotoClearanceType::test_non_string_photo_clearance_is_invalid_row[bad_pc2]',
    'test_license_policy.py::TestRd05OccluderPhotoClearanceType::test_none_photo_clearance_is_not_type_rejected',
    'test_license_policy.py::TestRd06LicensePolicyErrorPayload::test_audit_provenance_row_non_mapping_payload',
    'test_license_policy.py::TestRd06LicensePolicyErrorPayload::test_audit_tooling_row_non_mapping_payload',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_controls_still_fail_research[casia_webface]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_controls_still_fail_research[dataset/ffhq]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_controls_still_fail_research[ffhq]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_controls_still_fail_research[vggface2_train]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_controls_still_pass[dcface]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_controls_still_pass[notffhq]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_controls_still_pass[operator-photo]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_controls_still_pass[self-generated]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_controls_still_pass[umap-learn]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_legitimate_sources_pass[casiaset-detector]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_legitimate_sources_pass[celebase]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_legitimate_sources_pass[commercial-ffhq-alternative]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_legitimate_sources_pass[dataset_not_ffhq]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_legitimate_sources_pass[ffhq-tools]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_legitimate_sources_pass[ffhq_free_internal]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_legitimate_sources_pass[glint360k_free]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_legitimate_sources_pass[mfrx-vendor]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_legitimate_sources_pass[our_widerface_replacement]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_legitimate_sources_pass[webfaces-r-us]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_unsplit_compounds_still_fail[casiawebfaceextra]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_unsplit_compounds_still_fail[ffhq256]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_unsplit_compounds_still_fail[vggface2train]',
    'test_license_policy.py::TestResearchMatcherPrecision::test_br27_unsplit_compounds_still_fail[widerfacehd]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_provenance_row_research_source_fails',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_only_license_tag_fails',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[CASIA_WebFace]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[casia-webface]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[casia_webface]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[celeba_hq]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[dataset/ffhq]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[ffhq]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[ffhq_aligned]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[glint360k_r100]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[mfr]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[ms1m_v3]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[rmfrd]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[vggface2]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[vggface2_train]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[webface260m]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[widerface]',
    'test_license_policy.py::TestResearchOnlySourcesFail::test_research_source_fails_with_research_only_reason[widerface_val]',
    'test_license_policy.py::TestRowDeclaredCategoryNonDispatching::test_br34_caller_category_still_dispatches',
    'test_license_policy.py::TestRowDeclaredCategoryNonDispatching::test_br34_contract3_passes_with_and_without_row_category',
    'test_license_policy.py::TestRv03RepresentativeRowsDiscriminationFloor::test_representative_rows_discriminate_rejection_axes',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_measured_escape_witnesses_fail[model-id-wins-package]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_measured_escape_witnesses_fail[tooling-shadow-package_name]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_measured_escape_witnesses_fail[training-package]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w1-model_ingest]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w1-occluder_asset]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w1-synthetic_source]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w1-tooling]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w1-training_data]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w2-model_ingest]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w2-occluder_asset]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w2-synthetic_source]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w2-tooling]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w2-training_data]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w3-model_ingest]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w3-occluder_asset]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w3-synthetic_source]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w3-tooling]',
    'test_license_policy.py::TestRv10PackageDenylistFloorAcrossIdentityFields::test_witness_fails_every_door[w3-training_data]',
    'test_license_policy.py::TestRv11SyntheticSourceAxisTaintReasonFidelity::test_synthetic_door_reports_source_axis_taint[buffalo-nc_model_derived]',
    'test_license_policy.py::TestRv11SyntheticSourceAxisTaintReasonFidelity::test_synthetic_door_reports_source_axis_taint[ffhq-research_only_source]',
    'test_license_policy.py::TestRv12CompoundSpdxAllowlistTokenisation::test_all_allowlisted_compounds_pass[(MIT)]',
    'test_license_policy.py::TestRv12CompoundSpdxAllowlistTokenisation::test_all_allowlisted_compounds_pass[Apache-2.0+]',
    'test_license_policy.py::TestRv12CompoundSpdxAllowlistTokenisation::test_all_allowlisted_compounds_pass[MIT AND Apache-2.0]',
    'test_license_policy.py::TestRv12CompoundSpdxAllowlistTokenisation::test_all_allowlisted_compounds_pass[MIT+]',
    'test_license_policy.py::TestRv12CompoundSpdxAllowlistTokenisation::test_denylisted_component_named',
    'test_license_policy.py::TestRv12CompoundSpdxAllowlistTokenisation::test_unknown_component_named',
    'test_license_policy.py::TestRv13ClearanceAxesExactMatchNormalisation::test_both_axes_side_by_side_normalisation',
    'test_license_policy.py::TestRv13ClearanceAxesExactMatchNormalisation::test_clearance_decision_exact_canonical_admits',
    'test_license_policy.py::TestRv13ClearanceAxesExactMatchNormalisation::test_clearance_decision_uppercase_refused',
    'test_license_policy.py::TestRv13ClearanceAxesExactMatchNormalisation::test_photo_clearance_lowercase_canonical_admits',
    'test_license_policy.py::TestRv13ClearanceAxesExactMatchNormalisation::test_photo_clearance_uppercase_refused',
    'test_license_policy.py::TestSelfGeneratedIsSourceNotLicense::test_br25_contract3_self_generated_apache_still_passes',
    'test_license_policy.py::TestSelfGeneratedIsSourceNotLicense::test_br25_scraped_with_self_generated_license_fails',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_br37_audit_derived_from_model_none_is_empty_opt_out',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_br37_audit_derived_from_model_rejects_non_string[123]',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_br37_audit_derived_from_model_rejects_non_string[bad0]',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_br37_audit_derived_from_model_rejects_non_string[bad2]',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_explicit_synthetic_category_unknown_source_pending',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_list_derived_from_model_fails',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_missing_derived_from_model_key_fails',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_none_derived_from_model_fails',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_row_cannot_waive_source_via_bogus_category',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_row_cannot_waive_source_via_tooling_category',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_tooling_row_requires_package_identifier',
    'test_license_policy.py::TestSyntheticFailClosedAndRowValidation::test_unknown_synthetic_source_pending',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_floor_still_runs_when_derived_key_absent[model_ingest]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_floor_still_runs_when_derived_key_absent[occluder_asset]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_floor_still_runs_when_derived_key_absent[synthetic_source]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_floor_still_runs_when_derived_key_absent[tooling]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_nc_derivation_outranks_denylisted_license[model_ingest]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_nc_derivation_outranks_denylisted_license[occluder_asset]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_nc_derivation_outranks_denylisted_license[synthetic_source]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_nc_derivation_outranks_denylisted_license[tooling]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_nc_derivation_outranks_denylisted_license[training_data]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_research_derivation_outranks_denylisted_license[model_ingest]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_research_derivation_outranks_denylisted_license[occluder_asset]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_research_derivation_outranks_denylisted_license[synthetic_source]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_research_derivation_outranks_denylisted_license[tooling]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_research_derivation_outranks_denylisted_license[training_data]',
    'test_license_policy.py::TestTaintOutranksLicenseFloor::test_training_data_requires_derived_key_before_floor',
    'test_license_policy.py::TestToolingRowDenylist::test_br24_ultralytics_dep_parity',
    'test_license_policy.py::TestToolingRowDenylist::test_br24_ultralytics_package_name_fails_denylisted',
    'test_license_policy.py::TestToolingRowDenylist::test_br24_ultralytics_source_field_fails_denylisted',
    'test_license_policy.py::TestToolingRowDenylist::test_br24_umap_learn_tooling_row_passes',
    'test_license_policy.py::TestToolingRowDenylist::test_br39_tooling_row_unknown_package_fails',
    'test_license_policy.py::TestUmapLearnToolingAllowlist::test_br39_denylisted_tooling_dependency_fails',
    'test_license_policy.py::TestUmapLearnToolingAllowlist::test_br39_unknown_tooling_package_fails',
    'test_license_policy.py::TestUmapLearnToolingAllowlist::test_is_tooling_allowlisted_helper',
    'test_license_policy.py::TestUmapLearnToolingAllowlist::test_umap_learn_audit_passes',
    'test_license_policy.py::TestUnicodeNormalisationSharedByMatchers::test_br21_cyrillic_casia_fails_closed',
    'test_license_policy.py::TestUnicodeNormalisationSharedByMatchers::test_br21_cyrillic_insightface_fails_closed',
    'test_license_policy.py::TestUnicodeNormalisationSharedByMatchers::test_br21_literal_casia_still_research_only',
    'test_license_policy.py::TestUnicodeNormalisationSharedByMatchers::test_br21_space_and_dot_insightface_fail_nc',
    'test_license_policy.py::TestUnicodeNormalisationSharedByMatchers::test_br21_yunet_insightface_control_fails_nc',
    'test_license_policy.py::TestUnicodeNormalisationSharedByMatchers::test_br21_yunet_zwsp_insightface_row_fails',
    'test_license_policy.py::TestUnicodeNormalisationSharedByMatchers::test_br21_zwsp_insightface_fails_nc',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_br33_nc_precedence_over_synthetic',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_br33_operator_renderer_passes',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_br33_registered_rt_detr_passes',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_br33_retinaface_r50_is_nc_not_pending',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_br33_unregistered_derived_on_ingest_source_fails',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate21_registration_verdict_independent_of_source[operator-render]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate21_registration_verdict_independent_of_source[rt-detr]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate21_registration_verdict_independent_of_source[self-generated]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate21_registration_verdict_independent_of_source[yunet]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_operator_lineage_registry_is_exact_only[acx/occluder-renderer-v1/evil]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_operator_lineage_registry_is_exact_only[acx/occluder_renderer_v1_hd]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_operator_lineage_registry_is_exact_only[acx]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_operator_lineage_registry_is_exact_only[acx_internal_projector_r50]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_operator_lineage_registry_is_exact_only[acx_internal_projector_train]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_operator_lineage_registry_is_exact_only[acx_internal_projector_v2]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_operator_lineage_registry_is_exact_only[evilcorp/acx_internal_projector]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_operator_lineage_registry_is_exact_only[occluder-renderer-v1]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_operator_lineage_registry_is_exact_only[otherorg/acx_internal_projector]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_registered_lineage_still_resolves[  acx/occluder-renderer-v1  ]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_registered_lineage_still_resolves[ACX/OCCLUDER-RENDERER-V1]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_registered_lineage_still_resolves[ACX_Internal_Projector]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_registered_lineage_still_resolves[acx/occluder-renderer-v1]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_registered_lineage_still_resolves[acx/occluder_renderer_v1]',
    'test_license_policy.py::TestUnregisteredDerivedModel::test_gate24_registered_lineage_still_resolves[acx_internal_projector]',
    'test_license_policy.py::TestUnregisteredSourceFailClosed::test_br22_control_with_derived_also_pending',
    'test_license_policy.py::TestUnregisteredSourceFailClosed::test_br22_unregistered_sources_pending[my-synthetic-gan]',
    'test_license_policy.py::TestUnregisteredSourceFailClosed::test_br22_unregistered_sources_pending[mysteryganv2]',
    'test_license_policy.py::TestUnregisteredSourceFailClosed::test_br22_unregistered_sources_pending[synthface3]',
    'test_license_policy.py::TestUnregisteredSourceFailClosed::test_br22_unregistered_sources_pending[unknown-synthetic-gan-v9]',
    'test_license_policy.py::TestUnregisteredSourceFailClosed::test_br22_vec2face_successor_is_nc_package_floor',
    'test_license_policy_hardening.py::TestGate15StrSubclassMethodLaundering::test_forged_clearance_decision_rejected',
    'test_license_policy_hardening.py::TestGate15StrSubclassMethodLaundering::test_forged_license_agpl_rejected',
    'test_license_policy_hardening.py::TestGate15StrSubclassMethodLaundering::test_forged_license_on_tooling_rejected',
    'test_license_policy_hardening.py::TestGate15StrSubclassMethodLaundering::test_forged_license_research_only_rejected',
    'test_license_policy_hardening.py::TestGate15StrSubclassMethodLaundering::test_forged_photo_clearance_rejected',
    'test_license_policy_hardening.py::TestGate15StrSubclassMethodLaundering::test_hide_derived_nc_still_caught',
    'test_license_policy_hardening.py::TestGate15StrSubclassMethodLaundering::test_honest_subclass_still_evaluates_correctly',
    'test_license_policy_hardening.py::TestGate15StrSubclassMethodLaundering::test_toop_source_research_still_caught',
    'test_license_policy_hardening.py::TestGate21OperatorOwnedLineageRegistry::test_provenance_token_in_source_no_longer_required',
    'test_license_policy_hardening.py::TestGate21OperatorOwnedLineageRegistry::test_tooling_internal_lineage_clears_without_provenance_in_source',
    'test_license_policy_hardening.py::TestGate21OperatorOwnedLineageRegistry::test_tooling_source_is_package_shape_also_clears',
    'test_license_policy_hardening.py::TestGate21OperatorOwnedLineageRegistry::test_unregistered_lineage_fails_every_door[model_ingest]',
    'test_license_policy_hardening.py::TestGate21OperatorOwnedLineageRegistry::test_unregistered_lineage_fails_every_door[occluder_asset]',
    'test_license_policy_hardening.py::TestGate21OperatorOwnedLineageRegistry::test_unregistered_lineage_fails_every_door[synthetic_source]',
    'test_license_policy_hardening.py::TestGate21OperatorOwnedLineageRegistry::test_unregistered_lineage_fails_every_door[tooling]',
    'test_license_policy_hardening.py::TestGate21OperatorOwnedLineageRegistry::test_unregistered_lineage_fails_every_door[training_data]',
    'test_license_policy_hardening.py::TestGate22PackageDenylistOutranksRegistration::test_denylisted_package_plus_any_junk_lineage_reports_package',
    'test_license_policy_hardening.py::TestGate22PackageDenylistOutranksRegistration::test_denylisted_package_plus_unregistered_lineage_reports_package',
    'test_license_policy_hardening.py::TestGate22PackageDenylistOutranksRegistration::test_precedence_inverted_order_would_surface_registration',
    'test_license_policy_hardening.py::TestGate23SyntheticExemptionRechecksCommercialUse::test_forbidden_synthetic_derived_fails_every_door[model_ingest]',
    'test_license_policy_hardening.py::TestGate23SyntheticExemptionRechecksCommercialUse::test_forbidden_synthetic_derived_fails_every_door[occluder_asset]',
    'test_license_policy_hardening.py::TestGate23SyntheticExemptionRechecksCommercialUse::test_forbidden_synthetic_derived_fails_every_door[synthetic_source]',
    'test_license_policy_hardening.py::TestGate23SyntheticExemptionRechecksCommercialUse::test_forbidden_synthetic_derived_fails_every_door[tooling]',
    'test_license_policy_hardening.py::TestGate23SyntheticExemptionRechecksCommercialUse::test_forbidden_synthetic_derived_fails_every_door[training_data]',
    'test_license_policy_hardening.py::TestRv14UnreadableNodeidBaseline::test_non_utf8_baseline_returns_harness_error',
    'test_license_policy_hardening.py::TestRv14UnreadableNodeidBaseline::test_unreadable_baseline_returns_harness_error',
})
_REPO_ROOT = _HERE.parents[2]

# Explicit env allowlist for child pytest (BR-49). Blocklist would rot.
_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "LC_NUMERIC",
        "LC_TIME",
        "LC_COLLATE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "COMSPEC",
        "WINDIR",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
    }
)

# Must never reach the child, even if somehow present on the allowlist later.
_ENV_DENY_EXACT = frozenset(
    {
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "PYTHONWARNINGS",
        "PYTEST_CURRENT_TEST",
    }
)


class Verdict(str, Enum):
    SURVIVED = "SURVIVED"
    KILLED = "KILLED"
    HARNESS_ERROR = "HARNESS-ERROR"


# Mutants permitted to ship require_kill=False. Adding a new weak flag
# requires editing this named constant with a review-bar comment
# (FIR-7-RV-04). CONTROL is the discrimination probe (must SURVIVE);
# M6 is verdict-equivalent on audit_provenance_row — canonical derivation
# in test_equivalence_claims.py (FIR-7-LR-05).
#
# FIR-7-C2-02: the frozenset blocks .add but not rebind. The startup check
# also asserts KNOWN_GAP_ALLOWED == frozenset({"CONTROL", "M6"}) against an
# inline literal at the check site so a rebind must edit that site too
# (same review-visibility bar as ABSOLUTE_NODEID_FLOOR).
KNOWN_GAP_ALLOWED: frozenset[str] = frozenset({"CONTROL", "M6"})


@dataclass(frozen=True)
class Mutation:
    name: str
    description: str
    apply: str  # key into _APPLIERS
    # Exact test-name components (or base name before [param]); at least one
    # must appear among FAILED tests on KILLED.
    expected_victims: tuple[str, ...] = ()
    # CONTROL: True — must SURVIVE. Defect mutants: False — must be KILLED.
    expect_survived: bool = False
    # When True, a SURVIVED result fails the guard. False for known open gaps
    # that stay green until a companion lane lands; they are still registered
    # and reported so they cannot rot invisibly. require_kill=False is only
    # legal for names in KNOWN_GAP_ALLOWED (FIR-7-RV-04).
    require_kill: bool = True
    # When True, the mutant is labelled role=smoke in the discrimination
    # report and the collateral WARN is suppressed (kill-presence only,
    # not axis-tight evidence). Smoke mutants are excluded from the headline
    # killed count and skip strong-form victim attribution (FIR-7-RV-04 /
    # FIR-7-RV-07).
    smoke_level: bool = False


@dataclass(frozen=True)
class SuiteReport:
    """Machine-readable suite outcome from junitxml + process rc."""

    rc: int
    executed: int
    failed_names: tuple[str, ...]  # test-name components that failed/errored
    summary: str
    raw_out: str
    junit_path: Path | None
    parse_error: str | None = None


# ---------------------------------------------------------------------------
# Anchor helpers (BR-17)
# ---------------------------------------------------------------------------


class AnchorError(RuntimeError):
    """Raised when a mutation anchor is missing or not unique."""


def _assert_unique_anchor(src: str, anchor: str, mut_name: str) -> None:
    """Require ``anchor`` to occur exactly once in pristine source (BR-17)."""
    n = src.count(anchor)
    if n != 1:
        raise AnchorError(
            f"ANCHOR-ERROR {mut_name}: anchor occurs {n} time(s), expected exactly 1"
        )


def _replace_unique(src: str, old: str, new: str, mut_name: str) -> str:
    _assert_unique_anchor(src, old, mut_name)
    return src.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Appliers — each verifies its anchor and raises if missing / non-unique.
# ---------------------------------------------------------------------------


def _m_control_inert_comment(src: str) -> str:
    """Semantically inert comment above a real function (must SURVIVE)."""
    old = "def _looks_like_research_source(value: str) -> bool:"
    new = (
        "# MUTATION CONTROL: inert comment — harness discrimination probe\n"
        "def _looks_like_research_source(value: str) -> bool:"
    )
    return _replace_unique(src, old, new, "CONTROL")


def _m1_unknown_spdx_pass(src: str) -> str:
    """Flip UNKNOWN_SPDX default-deny to PASS.

    Anchor is the per-token UNKNOWN_SPDX fail-closed return in ``audit_spdx``
    (structure/symbol, not comment prose — BR-17). Post FIR-7-RV-12 compound
    SPDX tokenisation, unknown licenses fail on this loop body rather than the
    empty-token trailing return; re-pointed so the smoke mutant stays live
    against the post-wave-A tree.
    """
    old = (
        "            return _fail(\n"
        "                RejectionReason.UNKNOWN_SPDX,\n"
        "                detail=(\n"
        '                    f"license {tag!r} contains unknown component {tok!r}; "\n'
        '                    "not on the allowlist"\n'
        "                ),\n"
        "            )"
    )
    new = (
        "            # MUTATION M1: unknown SPDX component incorrectly PASSes\n"
        '            return _pass(detail=f"license {tag!r} unknown component mutated to pass")'
    )
    return _replace_unique(src, old, new, "M1")


def _m2_drop_insightface_patterns(src: str) -> str:
    """Drop insightface family from NC seed set (verdict-flipping; B4b re-point).

    After B4b, matching is exact expanded-id membership. Removing every
    insightface-bearing seed from ``NC_MODEL_IDS`` flips
    ``insightface_buffalo_l`` / nested ``…/insightface/…`` from FAIL→PASS
    while buffalo_* pack ids remain denied.
    """
    old = "NC_MODEL_IDS: frozenset[str] = _derive_nc_model_ids()"
    new = (
        "NC_MODEL_IDS: frozenset[str] = frozenset(  # MUTATION M2: drop insightface family\n"
        '    x for x in _derive_nc_model_ids() if "insightface" not in x\n'
        ")"
    )
    return _replace_unique(src, old, new, "M2")



def _m3_empty_nc_ids(src: str) -> str:
    """Force NC_MODEL_IDS to empty frozenset (disable second matching layer)."""
    pattern = re.compile(
        r"NC_MODEL_IDS:\s*frozenset\[str\]\s*=\s*_derive_nc_model_ids\(\)"
    )
    matches = pattern.findall(src)
    if len(matches) != 1:
        raise AnchorError(
            f"ANCHOR-ERROR M3: NC_MODEL_IDS assignment occurs {len(matches)} time(s), "
            "expected exactly 1"
        )
    updated, n = pattern.subn(
        "NC_MODEL_IDS: frozenset[str] = frozenset()", src, count=1
    )
    if n != 1:
        raise AnchorError("ANCHOR-ERROR M3: could not locate NC_MODEL_IDS assignment")
    return updated


def _m4_exact_research_only(src: str) -> str:
    """Collapse _looks_like_research_source to exact frozenset membership."""
    pattern = re.compile(
        r"def _looks_like_research_source\(value: str\) -> bool:.*?(?=\ndef )",
        re.DOTALL,
    )
    found = pattern.findall(src)
    if len(found) != 1:
        raise AnchorError(
            f"ANCHOR-ERROR M4: _looks_like_research_source occurs {len(found)} time(s), "
            "expected exactly 1"
        )
    replacement = (
        "def _looks_like_research_source(value: str) -> bool:\n"
        '    """MUTATION M4: exact frozenset membership only."""\n'
        "    token = _normalize_token(value)\n"
        "    return token in RESEARCH_ONLY_SOURCES\n\n\n"
    )
    updated, n = pattern.subn(replacement, src, count=1)
    if n != 1:
        raise AnchorError("ANCHOR-ERROR M4: could not locate _looks_like_research_source")
    return updated


def _m5_empty_required_names(src: str) -> str:
    """Empty REQUIRED_MODEL_INGEST_DISPLAY_NAMES production tuple."""
    pattern = re.compile(
        r"REQUIRED_MODEL_INGEST_DISPLAY_NAMES:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\("
        r"\s*\*REQUIRED_DETECTOR_AB_DISPLAY_NAMES,\s*"
        r"\*REQUIRED_CASCADE_PERSON_DETECTOR_DISPLAY_NAMES,\s*\)",
        re.DOTALL,
    )
    found = pattern.findall(src)
    if len(found) != 1:
        raise AnchorError(
            f"ANCHOR-ERROR M5: REQUIRED_MODEL_INGEST_DISPLAY_NAMES occurs "
            f"{len(found)} time(s), expected exactly 1"
        )
    updated, n = pattern.subn(
        "REQUIRED_MODEL_INGEST_DISPLAY_NAMES: tuple[str, ...] = ()",
        src,
        count=1,
    )
    if n != 1:
        raise AnchorError(
            "ANCHOR-ERROR M5: could not locate REQUIRED_MODEL_INGEST_DISPLAY_NAMES"
        )
    return updated


def _m6_empty_synthetic_token_loop(src: str) -> str:
    """Disable SYNTHETIC_SOURCE_ENTRIES routing via (source, derived) loop.

    Equivalence is **verdict-level on ``audit_provenance_row`` only**, not
    path-level (RF-04 / SECD-06 layer masking). Canonical re-derivation is
    ``test_equivalence_claims.py`` (``EXPECTED_GRID_ROWS`` / the three
    ``test_m6_*`` pins): any-delta=0 on ``(ok, reason)`` across the
    deterministic grid; nonzero intermediate deltas on
    ``_synthetic_audit_targets`` are allowed and expected. Do **not** re-quote
    grid sizes here — re-run that suite (FIR-7-LR-05). Downstream arms
    (content-triggered clearance floor, registration / NC derivation for
    FORBIDDEN heads such as vec2face) mask intermediate target changes into
    a verdict-identical result. If the masking arm is removed, this mutant
    may flip from expect_survived to a real kill. Retained as a
    discrimination control with ``expect_survived=True`` (RESULT-J.md /
    BRIEF-P RF-04).
    """
    old = "    for token in (source, derived):"
    new = "    for token in ():  # MUTATION M6: skip synthetic entry token audit"
    return _replace_unique(src, old, new, "M6")


def _m7_category_valueerror_pass(src: str) -> str:
    """Row-category parse ValueError handler returns nothing (pass)."""
    old = (
        "    except ValueError:\n"
        "        return None, _fail(\n"
        "            RejectionReason.INVALID_ROW,\n"
        "            detail=f\"unknown policy category {raw_cat!r}\",\n"
        "            category=audit_category,\n"
        "        )"
    )
    new = (
        "    except ValueError:\n"
        "        return None, None  # MUTATION M7: invalid category silently ignored"
    )
    return _replace_unique(src, old, new, "M7")


def _m8_research_exact_only(src: str) -> str:
    """Drop unsplit compound forms from registry-side expansion (B4b / BR-47).

    Single surviving implementation: import-time ``_expand_id_forms`` adds
    unsplit ``base+suffix`` forms (ffhq256, widerfacehd). Disabling that line
    flips ``test_br27_unsplit_compounds_still_fail``.
    """
    old = '        unsplit = f"{_compact_canonical(c)}{suf}"  # unsplit compound startswith-equivalent'
    new = '        unsplit = ""  # MUTATION M8: no unsplit compound expansion'
    return _replace_unique(src, old, new, "M8")



def _m9_skip_derived_type_guard(src: str) -> str:
    """Disable non-str type guard on ``audit_derived_from_model`` only.

    BR-46/BR-68 folded the inline ``isinstance`` into shared
    ``_reject_non_string``. Anchor on the unique call site that names
    ``field="derived_from_model"`` so a naive ``if type_err is not None:``
    multi-hit raises ANCHOR-ERROR rather than mutating the wrong door.
    """
    old = (
        "    type_err = _reject_non_string(\n"
        "        derived_from_model,\n"
        '        field="derived_from_model",\n'
        "        category=PolicyCategory.TRAINING_DATA,\n"
        "    )\n"
        "    if type_err is not None:\n"
        "        return type_err"
    )
    new = (
        "    type_err = _reject_non_string(\n"
        "        derived_from_model,\n"
        '        field="derived_from_model",\n'
        "        category=PolicyCategory.TRAINING_DATA,\n"
        "    )\n"
        "    if False:  # MUTATION M9: skip non-str type guard on audit_derived_from_model\n"
        "        return type_err"
    )
    return _replace_unique(src, old, new, "M9")


def _m10_disable_generator_lineage_branch(src: str) -> str:
    """Disable has_generator_lineage synthetic routing (FIR-7-BR-16)."""
    old = "    if has_generator_lineage and source:"
    new = "    if False and has_generator_lineage and source:  # MUTATION M10"
    return _replace_unique(src, old, new, "M10")


def _m11_collapse_separator_parity(src: str) -> str:
    """Disable slash-component exact membership (B4b re-point of M11).

    Under exact enumeration, separator parity lives in :func:`canonical`.
    Slash-component hits such as ``dataset/ffhq`` are the remaining
    path-shape branch; dropping them flips research slash-form controls.
    """
    old = (
        "    # Slash components only — never progressive underscore prefixes (BR-50/52).\n"
        '    if "/" in c:\n'
        '        for part in c.split("/"):'
    )
    new = (
        "    # MUTATION M11: slash-component membership disabled\n"
        '    if False and "/" in c:\n'
        '        for part in c.split("/"):'
    )
    return _replace_unique(src, old, new, "M11")



def _m12_ingest_entry_raise_pass(src: str) -> str:
    """Primary raise LicensePolicyError(result) in get_model_ingest_entry → pass.

    BR-62 closed the gap: a registered non-ALLOWED ingest entry is the only
    load-bearing path for the primary raise (unregistered misses are absorbed
    by the second site). Victim:
    ``test_registered_nc_entry_raises_from_the_primary_site``.
    """
    old = (
        "    result = audit_model_ingest(model_id)\n"
        "    if not result.ok:\n"
        "        raise LicensePolicyError(result)"
    )
    new = (
        "    result = audit_model_ingest(model_id)\n"
        "    if not result.ok:\n"
        "        pass  # MUTATION M12: swallow primary LicensePolicyError"
    )
    return _replace_unique(src, old, new, "M12")


def _m13_pending_legal_clearance_pass(src: str) -> str:
    """Flip PENDING-LEGAL-CLEARANCE SPDX branch from _fail to _pass (GATE-33).

    Anchor is the unique pending-legal-clearance fail-closed return in
    ``audit_spdx`` (structure/symbol, not comment prose — BR-17). M1 only
    covers the later UNKNOWN_SPDX default-deny, so this branch was unguarded.
    """
    old = (
        '    if tag_cf == "pending-legal-clearance":\n'
        "        return _fail(\n"
        "            RejectionReason.PENDING_LEGAL_CLEARANCE,\n"
        '            detail="license is PENDING-LEGAL-CLEARANCE",\n'
        "        )"
    )
    new = (
        '    if tag_cf == "pending-legal-clearance":\n'
        "        # MUTATION M13: pending-legal-clearance incorrectly PASSes\n"
        "        return _pass(\n"
        '            detail="license is PENDING-LEGAL-CLEARANCE",\n'
        "        )"
    )
    return _replace_unique(src, old, new, "M13")


def _m14_package_denylist_always_miss(src: str) -> str:
    """Force ``_package_denylist_hit`` to always return None (GATE-34 / BR-51).

    Anchor is the unique function body start after the FIR-7 Wave F structural
    family-boundary rewrite (replaces B3-01 folded + B4-02 tag-strip). model
    ingest also uses ``_package_denylist_hit`` (folded), so the blast radius is
    the public derived API, model_ingest, tooling scalar door, plus reason
    demotion on the row path. Victim set re-anchored for the structural-family
    test rename (``test_structural_family_token_denylisted_package``).
    """
    # Anchor re-shaped for Wave F7: signature gained ``reasons=`` (A10-01
    # multi-axis door collection) and docstring names deny-first (A10-02).
    # Return type still PackageDenylistEntry | None; early-return None kills
    # the whole floor. Re-anchored in the same commit as the F7 baseline.
    old = (
        "def _package_denylist_hit(\n"
        "    value: str,\n"
        "    *,\n"
        "    reasons: frozenset[RejectionReason] | None = None,\n"
        ") -> PackageDenylistEntry | None:\n"
        '    """Structural family-boundary PACKAGE_DENYLIST lookup '
        "(BR-51 / Wave F6/F7).\n"
        "\n"
        "    Fold via :func:`canonical` (NFKC, casefold, unify "
        "``-``/``_``/``.``/space).\n"
        "    When ``/`` is present, test **only** slash components (never "
        "the joined\n"
        "    full token — FIR-7-A6-02). Each component is matched by the "
        "**uniform\n"
        "    iterative scanner** (FIR-7-B8-01 / B8-02 / A9-01 / A10-02): "
        "folded deny\n"
        "    (a)/(b) first, then exception-family strip with residual "
        "re-scan, then\n"
        "    deny-family via whole-suffix (c)/(d)/(e). Outer "
        "separator-aligned suffix\n"
        "    walk supplies path-split coverage; there is no inner (d') "
        "walk. A\n"
        "    component hits a deny family seed under any of:\n"
        "\n"
        "      (a) exact folded/compact match;\n"
        "      (b) separator-boundary prefix (``seed_`` + rest);\n"
        "      (c) bounded compact remainder (1–3 alnum after seed compact "
        "form);\n"
        "      (d) head-segment (leading segment hits via (a) or (c));\n"
        "      (e) compact segment-suffix (seed ≥ 5 compact chars, "
        "non-empty lead).\n"
        "\n"
        "    ``yolo-v5`` / ``yolov8n_oiv7`` / ``yolov9t`` / ``yolov9t-seg`` /\n"
        "    ``yolox_ultralytics`` / ``yolox_s_ultralytics`` / "
        "``yolox/s_ultralytics`` /\n"
        "    ``yoloxultralytics`` / ``checkpoints_yolo_seg`` deny; "
        "``yolodummy`` /\n"
        "    ``myyolo`` / pure exception-family tokens (``yolox``, "
        "``yolos``,\n"
        "    ``yolop_yolox``, ``megvii_yolox``, ``ppyolov2``) do not. "
        "Empty / None\n"
        "    / slash-only canonical → no denylist hit (doors treat empty/None/\n"
        "    slash-only as ``invalid_row`` separately — FIR-7-B4-01 / B5-04 /\n"
        "    F15-4).\n"
        "\n"
        "    ``reasons`` (FIR-7-A10-01): when set, only return hits whose "
        "reason is\n"
        "    in the set — lets door promotion collect AGPL-axis hits even "
        "when a\n"
        "    longer NC seed ranks first on the unfiltered scan.\n"
        '    """\n'
        "    c = canonical(value)"
    )
    new = (
        "def _package_denylist_hit(\n"
        "    value: str,\n"
        "    *,\n"
        "    reasons: frozenset[RejectionReason] | None = None,\n"
        ") -> PackageDenylistEntry | None:\n"
        '    """MUTATION M14: package denylist always misses."""\n'
        "    return None  # MUTATION M14: BR-51 derived denylist disabled\n"
        "    c = canonical(value)"
    )
    return _replace_unique(src, old, new, "M14")


def _m15_pending_reason_swap(src: str) -> str:
    """RF-02: keep PENDING-LEGAL-CLEARANCE FAIL, demote only the reason.

    Killed only by a reason assertion (GATE-33 axis). Gutting victims to bare
    ``ok is False`` turns this into SURVIVED (TEST-15 / TEST-17).
    """
    old = (
        "        return _fail(\n"
        "            RejectionReason.PENDING_LEGAL_CLEARANCE,\n"
        '            detail="license is PENDING-LEGAL-CLEARANCE",\n'
    )
    new = (
        "        return _fail(\n"
        "            RejectionReason.UNKNOWN_SPDX,  # MUTATION M15: reason swap\n"
        '            detail="license is PENDING-LEGAL-CLEARANCE",\n'
    )
    return _replace_unique(src, old, new, "M15")


def _m16_denylist_reason_swap(src: str) -> str:
    """RF-02: denylist still hits, reason demoted (GATE-34 axis).

    Wave F8 (B11-02) split floor promotion into an AGPL-first branch and an
    NC-floor branch (both use ``floor.reason``). Wave F9 (A12-3) extracted
    both into the shared ``_audit_weights_lineage_token`` helper (detail
    uses ``{field}=`` so one edit site feeds both doors). Mutate **both**
    branches in that helper; derived-door GATE-34 victims remain sufficient
    (a source-only twin mutant is structurally impossible — FIR-7-A12-3).
    """
    # AGPL-first membership-path precedence branch (FIR-7-B11-02 / A12-3).
    old_agpl = (
        "    if (\n"
        "        floor is not None\n"
        "        and floor.reason is RejectionReason.DENYLISTED_PACKAGE\n"
        "    ):\n"
        "        return _fail(\n"
        "            floor.reason,\n"
        "            detail=(\n"
        '                f"{field}={text!r} hits PACKAGE_DENYLIST entry "\n'
    )
    new_agpl = (
        "    if (\n"
        "        floor is not None\n"
        "        and floor.reason is RejectionReason.DENYLISTED_PACKAGE\n"
        "    ):\n"
        "        return _fail(\n"
        "            RejectionReason.UNREGISTERED_DERIVED_MODEL,  # MUTATION M16: reason swap\n"
        "            detail=(\n"
        '                f"{field}={text!r} hits PACKAGE_DENYLIST entry "\n'
    )
    src = _replace_unique(src, old_agpl, new_agpl, "M16")
    # NC-axis floor branch (comment + shared-helper {field}= form).
    old_nc = (
        "    # NC-axis floor promotion (no AGPL hit; membership missed).\n"
        "    if floor is not None:\n"
        "        return _fail(\n"
        "            floor.reason,\n"
        "            detail=(\n"
        '                f"{field}={text!r} hits PACKAGE_DENYLIST entry "\n'
    )
    new_nc = (
        "    # NC-axis floor promotion (no AGPL hit; membership missed).\n"
        "    if floor is not None:\n"
        "        return _fail(\n"
        "            RejectionReason.UNREGISTERED_DERIVED_MODEL,  # MUTATION M16: reason swap\n"
        "            detail=(\n"
        '                f"{field}={text!r} hits PACKAGE_DENYLIST entry "\n'
    )
    return _replace_unique(src, old_nc, new_nc, "M16")


def _m17_invalid_category_reason_swap(src: str) -> str:
    """RF-02: unknown row-category still FAILs, reason demoted (M7 axis)."""
    old = (
        "        return None, _fail(\n"
        "            RejectionReason.INVALID_ROW,\n"
        '            detail=f"unknown policy category {raw_cat!r}",\n'
        "            category=audit_category,\n"
        "        )"
    )
    new = (
        "        return None, _fail(\n"
        "            RejectionReason.UNKNOWN_SPDX,  # MUTATION M17: reason swap\n"
        '            detail=f"unknown policy category {raw_cat!r}",\n'
        "            category=audit_category,\n"
        "        )"
    )
    return _replace_unique(src, old, new, "M17")


def _m18_derived_type_reason_swap(src: str) -> str:
    """RF-02: non-str derived_from_model still FAILs, reason demoted (M9 axis)."""
    old = (
        "    type_err = _reject_non_string(\n"
        "        derived_from_model,\n"
        '        field="derived_from_model",\n'
        "        category=PolicyCategory.TRAINING_DATA,\n"
        "    )\n"
        "    if type_err is not None:\n"
        "        return type_err"
    )
    new = (
        "    type_err = _reject_non_string(\n"
        "        derived_from_model,\n"
        '        field="derived_from_model",\n'
        "        category=PolicyCategory.TRAINING_DATA,\n"
        "    )\n"
        "    if type_err is not None:\n"
        "        # MUTATION M18: keep FAIL, demote reason only\n"
        "        return _fail(\n"
        "            RejectionReason.UNKNOWN_SPDX,\n"
        "            detail=type_err.detail,\n"
        "            category=PolicyCategory.TRAINING_DATA,\n"
        "        )"
    )
    return _replace_unique(src, old, new, "M18")


def _m19_leak_category_training_data(src: str) -> str:
    """RF-01: restamp only PASSing training_data results with wrong category.

    Appended wrapper (Lane M validated). Invisible to FAIL-path tests; killed
    by the five-door category-stamping invariant (GATE-27). Pins
    ``test_result_category_equals_asked_door`` as a mediated victim.
    """
    return src + """

_orig_apr_m19 = audit_provenance_row


def audit_provenance_row(row, category=PolicyCategory.TRAINING_DATA):  # type: ignore[no-redef]
    r = _orig_apr_m19(row, category=category)
    if r.ok and str(getattr(category, "value", category)) == "training_data":
        return LicenseAuditResult(
            verdict=r.verdict, reason=r.reason, detail=r.detail,
            category="tooling",  # MUTATION M19: PASS-path category leak
        )
    return r
"""


def _m20_gate32_pass_witness_probe(src: str) -> str:
    """RF-01: force every PASS on audit_provenance_row to FAIL.

    Pins ``test_gate32_every_door_has_at_least_one_pass_witness`` as the sole
    expected victim. High collateral by construction; a hollowed GATE-32 body
    (e.g. ``pass_count = 1``) yields suite-red with zero victim hits →
    HARNESS-ERROR rather than a certified kill (TEST-15).
    """
    return src + """

_orig_apr_m20 = audit_provenance_row


def audit_provenance_row(row, category=PolicyCategory.TRAINING_DATA):  # type: ignore[no-redef]
    r = _orig_apr_m20(row, category=category)
    if r.ok:
        return _fail(
            RejectionReason.UNKNOWN_SPDX,
            detail="MUTATION M20: force FAIL to probe GATE-32 pass witness",
            category=category,
        )
    return r
"""


def _m21_br53_denylist_reason_to_research(src: str) -> str:
    """RF-02: keep DENYLISTED_LICENSE FAIL, swap reason only on BR-53 floor rows.

    Surgical wrapper so only ``TestBr53CategoryIndependentFloor`` denylist
    exact-reason pins carry the kill. A global reason swap would be killed by
    off-axis denylist pins and would not prove the BR-53 floor axis
    (FIR-7-RV-02 / TEST-15 / TEST-17).
    """
    return src + """

_orig_apr_m21 = audit_provenance_row


def _m21_is_br53_denylist_floor_row(row) -> bool:
    # Require the derived key present-as-empty so key-absent AGPL rows
    # (test_floor_still_runs_when_derived_key_absent) stay off-axis.
    if "derived_from_model" not in row or row.get("derived_from_model") not in ("", None):
        return False
    lic = str(row.get("license", "") or "").casefold()
    if lic != "agpl-3.0":
        return False
    package = row.get("package", "")
    if package != "numba":
        return False
    # DENYLISTED_LICENSE_ROW: model_id=yunet, source=self-generated.
    if row.get("model_id") == "yunet" and row.get("source") == "self-generated":
        return True
    # CLEARED_SYNTHETIC_ROW: source=dcface + operator clearance token.
    if (
        row.get("source") == "dcface"
        and "clearance_decision" in row
        and "model_id" not in row
    ):
        return True
    return False


def audit_provenance_row(row, category=PolicyCategory.TRAINING_DATA):  # type: ignore[no-redef]
    r = _orig_apr_m21(row, category=category)
    if (
        not r.ok
        and r.reason is RejectionReason.DENYLISTED_LICENSE
        and _m21_is_br53_denylist_floor_row(row)
    ):
        return LicenseAuditResult(
            verdict=r.verdict,
            reason=RejectionReason.RESEARCH_ONLY_SOURCE,  # MUTATION M21
            detail=r.detail,
            category=r.category,
        )
    return r
"""


def _m23_residual_classify_always_legitimate(src: str) -> str:
    """Force residual classifier to always return legitimate (F11 A14-3).

    Flips legitimate↔deny-reconstituting/unknown: exception+debris and
    compact-glue witnesses admit when residual classification is neutered
    to the admit branch.
    """
    old = (
        "    if compact_glue:\n"
        "        # Compact glue: only per-family compact tags / ppyolo-eplus\n"
        "        # allowlist. Forced also by an illegitimate head peel (F12-2 /\n"
        "        # F13-5). Shield tags (pt/trt/…) and separator-only tags\n"
        "        # (tiny/darknet/…) require separator-joined form\n"
        "        # (FIR-7 A14-1 / B12-4).\n"
        "        if len(parts) == 1 and _is_legitimate_compact_glue_residual(\n"
        "            parts[0], seed_c\n"
        "        ):\n"
        "            return _RESIDUAL_LEGITIMATE, None"
    )
    new = (
        "    # MUTATION M23: residual classification always legitimate\n"
        "    return _RESIDUAL_LEGITIMATE, None\n"
        "    if compact_glue:\n"
        "        # Compact glue: only per-family compact tags / ppyolo-eplus\n"
        "        # allowlist. Forced also by an illegitimate head peel (F12-2 /\n"
        "        # F13-5). Shield tags (pt/trt/…) and separator-only tags\n"
        "        # (tiny/darknet/…) require separator-joined form\n"
        "        # (FIR-7 A14-1 / B12-4).\n"
        "        if len(parts) == 1 and _is_legitimate_compact_glue_residual(\n"
        "            parts[0], seed_c\n"
        "        ):\n"
        "            return _RESIDUAL_LEGITIMATE, None"
    )
    return _replace_unique(src, old, new, "M23")


def _m24_deny_reconst_to_legitimate(src: str) -> str:
    """Flip deny-reconstituting branch to legitimate (F11 A14-3).

    ``yolos_eg`` / ``yoloseg`` / separator twins that only close via
    progressive reconst admit instead of deny-reconstituting.
    """
    old = (
        "    # (b) progressive re-glue reconstitutes a deny claim.\n"
        "    reconst = _residual_progressive_reconst_deny(seed_c, seed_k, residual)\n"
        "    if reconst is not None:\n"
        "        return _RESIDUAL_DENY_RECONST, reconst"
    )
    new = (
        "    # MUTATION M24: deny-reconstituting flipped to legitimate admit\n"
        "    reconst = _residual_progressive_reconst_deny(seed_c, seed_k, residual)\n"
        "    if reconst is not None:\n"
        "        return _RESIDUAL_LEGITIMATE, None"
    )
    return _replace_unique(src, old, new, "M24")


def _m25_unknown_default_to_legitimate(src: str) -> str:
    """Flip fail-closed unknown default to legitimate (F11 A14-3).

    Compact-glue shield residuals and pure-nonsense residuals that reach
    the unknown path admit instead of fail-closed deny.
    """
    old = (
        "    if non_tags or compact_glue:\n"
        "        return _RESIDUAL_UNKNOWN, _unknown_exception_residual_entry(\n"
        "            seed_c, residual\n"
        "        )\n"
        "\n"
        "    # Fail-closed default (A14-2): every segment-legit non-compact path\n"
        "    # already returned above; never silently admit on fall-through.\n"
        "    return _RESIDUAL_UNKNOWN, _unknown_exception_residual_entry(\n"
        "        seed_c, residual\n"
        "    )"
    )
    new = (
        "    # MUTATION M25: unknown fail-closed default → legitimate admit\n"
        "    if non_tags or compact_glue:\n"
        "        return _RESIDUAL_LEGITIMATE, None\n"
        "\n"
        "    # Fail-closed default (A14-2) mutated to legitimate.\n"
        "    return _RESIDUAL_LEGITIMATE, None"
    )
    return _replace_unique(src, old, new, "M25")


def _m26_b141_unbounded_defer_steal_skip(src: str) -> str:
    """Skip B14-1 unbounded-defer residual deny steal (F11 A14-3).

    ``yoloxultralyticsplus`` and siblings admit again (DEFER granted,
    re-queue never runs, trailing (e) does not fire).
    """
    old = (
        "    if residual and structural != residual:\n"
        "        residual_deny = _deny_folded_ab_hit(residual)\n"
        "        if residual_deny is None:\n"
        "            residual_deny = _contained_long_deny_seed_hit(residual)\n"
        "        # F13-6 / R15-G1-5: recurse steal on the residual so a\n"
        "        # multi-stack compact (yoloxyoloxyolo) names the inner deny\n"
        "        # seed (yolo) instead of landing on unknown residual.\n"
        "        if residual_deny is None and residual != token:\n"
        "            residual_deny = _exception_illegitimate_deny_steal(residual)\n"
        "        if residual_deny is not None:\n"
        "            return residual_deny"
    )
    new = (
        "    # MUTATION M26: B14-1/F12-1 unbounded-defer steal skipped\n"
        "    if residual and structural != residual:\n"
        "        residual_deny = _deny_folded_ab_hit(residual)\n"
        "        if residual_deny is None:\n"
        "            residual_deny = _contained_long_deny_seed_hit(residual)\n"
        "        # F13-6 / R15-G1-5: recurse steal on the residual so a\n"
        "        # multi-stack compact (yoloxyoloxyolo) names the inner deny\n"
        "        # seed (yolo) instead of landing on unknown residual.\n"
        "        if residual_deny is None and residual != token:\n"
        "            residual_deny = _exception_illegitimate_deny_steal(residual)\n"
        "        if residual_deny is not None:\n"
        "            pass  # mutated: do not return residual deny"
    )
    return _replace_unique(src, old, new, "M26")


def _m22_br53_research_reason_to_denylist(src: str) -> str:
    """RF-02: keep RESEARCH_ONLY_SOURCE FAIL, swap reason on BR-53 research rows.

    Surgical wrapper targeting the BR-53 research-source exact-reason pin only
    (FIR-7-RV-02 / TEST-15 / TEST-17).
    """
    return src + """

_orig_apr_m22 = audit_provenance_row


def _m22_is_br53_research_floor_row(row) -> bool:
    return (
        row.get("model_id") == "rt-detr"
        and row.get("package") == "numba"
        and row.get("source") == "self-generated"
        and row.get("license") == "Apache-2.0"
        and row.get("derived_from_model") == "ffhq"
        and row.get("photo_clearance") == "cleared"
    )


def audit_provenance_row(row, category=PolicyCategory.TRAINING_DATA):  # type: ignore[no-redef]
    r = _orig_apr_m22(row, category=category)
    if (
        not r.ok
        and r.reason is RejectionReason.RESEARCH_ONLY_SOURCE
        and _m22_is_br53_research_floor_row(row)
    ):
        return LicenseAuditResult(
            verdict=r.verdict,
            reason=RejectionReason.DENYLISTED_LICENSE,  # MUTATION M22
            detail=r.detail,
            category=r.category,
        )
    return r
"""


MUTATIONS: list[Mutation] = [
    Mutation(
        name="CONTROL",
        description="inert comment above _looks_like_research_source (discrimination)",
        apply="control",
        expected_victims=(),
        expect_survived=True,
        require_kill=False,
    ),
    Mutation(
        name="M1",
        description="UNKNOWN_SPDX default-deny → PASS (smoke — high collateral)",
        apply="m1",
        expected_victims=(
            "test_unknown_spdx_default_deny",
            "test_operator_cleared_is_not_spdx_pass",
            "test_operator_cleared_row_fails",
        ),
        smoke_level=True,
    ),
    Mutation(
        name="M2",
        description="drop insightface family from NC_MODEL_IDS (smoke — high collateral)",
        apply="m2",
        expected_victims=(
            "test_nested_and_separator_insightface_forms_fail",
            "test_insightface_prefix_pattern_is_pinned",
        ),
        smoke_level=True,
    ),
    Mutation(
        name="M3",
        description="NC_MODEL_IDS = frozenset() (smoke — high collateral)",
        apply="m3",
        expected_victims=(
            "test_nc_model_ids_layer_rejects_pinned_ids",
            "test_vec2face_forbidden_table_entry_drives_nc_ids",
        ),
        smoke_level=True,
    ),
    Mutation(
        name="M4",
        description="_looks_like_research_source → exact membership (smoke — high collateral)",
        apply="m4",
        expected_victims=(
            "test_research_source_fails_with_research_only_reason",
        ),
        smoke_level=True,
    ),
    Mutation(
        name="M5",
        description="REQUIRED_MODEL_INGEST_DISPLAY_NAMES = ()",
        apply="m5",
        expected_victims=(
            "test_required_display_names_registered",
        ),
    ),
    Mutation(
        name="M6",
        description=(
            "_synthetic_audit_targets: for token in () — verdict-equivalent "
            "on audit_provenance_row only (NOT path-equivalent; RF-04; "
            "canonical derivation: test_equivalence_claims.py)"
        ),
        apply="m6",
        # Verdict-level equivalence only (RF-04 / FIR-7-LR-05): re-derive via
        # test_equivalence_claims.py. Intermediate _synthetic_audit_targets
        # still differ; downstream floor/registration arms mask them. Not a
        # test gap — do not invent a victim (TEST-15).
        expected_victims=(),
        expect_survived=True,
        require_kill=False,
    ),
    Mutation(
        name="M7",
        description="row-category except ValueError → pass (invalid category ignored)",
        apply="m7",
        expected_victims=("test_row_cannot_waive_source_via_bogus_category",),
    ),
    Mutation(
        name="M8",
        description="research expand: drop unsplit-compound forms (B4b single site)",
        apply="m8",
        expected_victims=("test_br27_unsplit_compounds_still_fail",),
    ),
    Mutation(
        name="M9",
        description="audit_derived_from_model type guard → if False",
        apply="m9",
        # True kill set (FIR-7-RV-07): br37 alone is collateral-carried by the
        # BR-46 derived non-str contract pins; name the full set so strong-form
        # attribution (victims deselected → must SURVIVE) holds.
        expected_victims=(
            "test_br37_audit_derived_from_model_rejects_non_string",
            "test_br46_type_contract_table[derived-int]",
            "test_br46_type_contract_table[derived-list]",
            "test_br46_type_contract_table[derived-dict]",
        ),
    ),
    Mutation(
        name="M10",
        description="disable has_generator_lineage synthetic routing (BR-16)",
        apply="m10",
        # True kill set (FIR-7-RV-07): lineage pending pin + GATE-27 category
        # backstop both carry the kill.
        expected_victims=(
            "test_br16_lineage_sole_cause_of_synthetic_pending",
            "test_generator_lineage_backstop_keeps_training_data_category",
        ),
    ),
    Mutation(
        name="M11",
        description="slash-component membership disabled (smoke — high collateral)",
        apply="m11",
        expected_victims=(
            "test_research_source_fails_with_research_only_reason",
            "test_br27_controls_still_fail_research",
        ),
        smoke_level=True,
    ),
    Mutation(
        name="M12",
        description="get_model_ingest_entry primary raise → pass",
        apply="m12",
        expected_victims=(
            "test_registered_nc_entry_raises_from_the_primary_site",
        ),
        require_kill=True,
    ),
    Mutation(
        name="M13",
        description="PENDING-LEGAL-CLEARANCE SPDX branch → PASS (GATE-33)",
        apply="m13",
        expected_victims=(
            "test_gate33_audit_spdx_pending_legal_clearance_fails",
            "test_gate33_training_data_row_pending_license_fails",
            "test_gate33_tooling_row_pending_license_fails",
            "test_gate33_model_ingest_row_pending_license_fails",
            "test_gate33_occluder_asset_row_pending_license_fails",
            "test_gate33_synthetic_source_row_pending_license_fails",
        ),
    ),
    Mutation(
        name="M14",
        description="_package_denylist_hit always returns None (GATE-34)",
        apply="m14",
        # True kill set (FIR-7-RV-07): GATE-34 pins plus the package-denylist
        # escape/witness matrix and FIR-7-B2/B3 package-identity pins — those
        # also die when the denylist always misses. After FIR-7-B3-01/A3-01,
        # model_ingest + tooling scalar also route through the folded hit
        # helper, so their denylist pins join the victim set.
        expected_victims=(
            "test_gate34_audit_derived_from_model_denylisted_package",
            "test_gate34_training_data_row_derived_ultralytics_reason",
            "test_measured_escape_witnesses_fail",
            "test_witness_fails_every_door",
            "test_package_denylist_outranks_registration",
            "test_alias_key_with_denylisted_value_fails",
            "test_family_token_fails_package_floor",
            # FIR-7 Wave F: structural family-boundary witnesses also die when
            # the hit helper always misses (must pin for attribution; RV-07).
            "test_structural_family_token_denylisted_package",
            # Wave F2 head-segment multi-door pins (row + scalar).
            "test_head_segment_denylisted_on_row_doors",
            "test_head_segment_denylisted_on_scalar_doors",
            # Wave F red-proofs precondition on a deny hit before flipping a
            # branch flag — they die when the hit helper always misses.
            "test_red_proof_boundary_prefix_branch",
            "test_red_proof_compact_remainder_branch",
            "test_red_proof_head_segment_branch",
            # Wave F3: residual re-scan / component-split / lineage / NC-weights
            # pins also die when the hit helper always misses (RV-07).
            "test_residual_witness_hits_package_denylist",
            "test_residual_witness_denylisted_on_row_doors",
            "test_residual_witness_denylisted_on_scalar_doors",
            "test_residual_agpl_witness_is_denylisted_package",
            "test_red_proof_exception_residual_rescan",
            "test_yolo_nas_path_components_deny_nc_weights",
            "test_mixed_path_deny_component_wins",
            "test_pypi_yolov5_still_denies",
            "test_darknet_era_own_deny_entry",
            "test_yolo_nas_nc_weights_denies",
            "test_yolo_nas_denies_on_row_doors",
            "test_red_proof_yolo_nas_deny_entry",
            # Wave F4: residual segment-suffix deny scan pins (B7-01/02/03).
            # Shape of _package_denylist_hit unchanged; new deny witnesses join
            # the M14 victim set so attribution stays strong-form (RV-07).
            "test_suffix_witness_hits_package_denylist",
            "test_suffix_witness_denies_on_row_doors",
            "test_suffix_witness_denies_on_scalar_doors",
            "test_suffix_agpl_witness_is_denylisted_package",
            "test_suffix_nc_witness_is_nc_model_derived",
            "test_red_proof_exception_residual_suffix_scan",
            # Wave F5/F6: uniform outer-suffix/(e) scan, multi-strip pins,
            # iterative bounds (B8-01/02/03/04 / A9-01). Shape of
            # _package_denylist_hit unchanged; new deny witnesses + multi-
            # strip continuation pins join the M14 victim set (RV-07).
            # Re-anchored same commit as baseline growth. (d') red-proof
            # deleted; outer-suffix red-proof + vendor admit pins added.
            "test_uniform_bypass_hits_package_denylist",
            "test_uniform_bypass_denies_on_row_doors",
            "test_uniform_bypass_denies_on_scalar_doors",
            "test_agpl_uniform_bypass_is_denylisted_package",
            "test_nc_uniform_bypass_is_nc_model_derived",
            "test_red_proof_outer_residual_suffix_scan",
            "test_red_proof_compact_suffix_rule_e",
            "test_deep_chain_denies_without_recursion_error",
            "test_deep_chain_denies_on_all_four_doors",
            "test_non_shrinking_strip_denies",
            "test_multi_strip_hits_package_denylist",
            "test_multi_strip_denies_on_row_doors",
            "test_multi_strip_denies_on_scalar_doors",
            "test_red_proof_multi_strip_continuation",
            "test_deci_yolo_nas_l_still_denies_nc",
            "test_red_proof_fail_closed_bounds_neuter",
            # B8-07 residual NC compounds route through package-floor hit
            # (and derived-door promotion); die when hit always misses.
            "test_derived_rejects_residual_nc_compound",
            "test_tooling_ingest_still_nc_package_floor",
            # Wave F6: PP-YOLO Darknet-deny pins die when hit always misses.
            "test_darknet_yolov2_still_denies_with_darknet_note",
            # Wave F6: synthetic overflow probe + flag-independence pins
            # also die when the hit helper always misses (RV-07).
            "test_synthetic_overflow_bound_invariant_probe",
            "test_each_flag_flip_alone_changes_a_pinned_outcome",
            # Wave F6b (B9-02 follow-up): prefix-shielded NC floor witnesses
            # die when the hit helper always misses. Shape of
            # _package_denylist_hit unchanged; new deny witnesses join the
            # M14 victim set so attribution stays strong-form (RV-07).
            # Re-anchored same commit as baseline growth.
            "test_prefix_witness_hits_package_floor_and_whole_component",
            "test_prefix_witness_rejects_training_data_row",
            "test_myarcface_compact_suffix_overblock_is_deliberate",
            "test_not_insightface_row_rejection_unchanged",
            "test_br22_vec2face_successor_is_nc_package_floor",
            "test_br23_synthetic_parity_with_audit_synthetic_source",
            "test_red_proof_prefix_shield_component_suffix_flag",
            # model_ingest / tooling scalar / BR-24 package-floor pins
            # (expanded blast radius after folded lookup; FIR-7-B3-01/A3-01)
            "test_ultralytics_agpl_is_denylisted",
            "test_yolov8_agpl_family_denied",
            "test_br39_denylisted_tooling_dependency_fails",
            "test_br24_ultralytics_source_field_fails_denylisted",
            "test_br24_ultralytics_package_name_fails_denylisted",
            "test_br24_ultralytics_dep_parity",
            "test_multi_fault_reports_documented_winner",
            "test_denylisted_package_raises_with_exact_reason",
            "test_nc_denylisted_package_raises_with_exact_reason",
            "test_tooling_scalar_denylisted_package",
            # Wave F7 (A10-01/02 / B10-01): deny-first artifact pins, multi-
            # axis door promotion, derived NC floor surface, door-promotion
            # shapes, SCRFD surface, and the yolo_nas_m red-proof die when
            # the hit helper always misses. Signature gained reasons=;
            # victims re-anchored same commit as F7 baseline growth (RV-07).
            "test_red_proof_yolo_nas_m_pin",
            "test_ultralytics_artifact_forms_deny",
            "test_ultralytics_artifact_forms_deny_on_training_data_row",
            "test_dual_axis_rejects_both_doors_with_agpl_precedence",
            "test_package_floor_still_sees_nc_axis",
            # Wave F8 (B11-02): membership-path dual-axis pins die when the
            # hit helper always misses (AGPL residue becomes invisible).
            "test_membership_path_dual_axis_agpl_precedence",
            "test_measured_admits_now_fail_closed_on_rows_and_doors",
            # Wave F8 (B11-03): renamed + expanded to full generator input.
            "test_anti_drift_full_generator_input_floor_sweep",
            "test_multi_segment_under_junk_prefix_rejects_rows_and_doors",
            "test_tag_flood_seven_tags_rejects_rows_and_doors",
            "test_c_shaped_door_promotion_via_monkeypatch",
            "test_not_insightface_door_admit_is_deliberate",
            "test_scrfd_rejects_rows_and_doors",
            # Wave F9/F10 (B12-1..B13-5 / A12-3 / F10): elevated deny-(c) /
            # residual-classify red-proofs, separator-twin reconstitution,
            # per-family digit laundering / YOLOS letter twins, B12-5 flag
            # load-bearing pins, shared-door helper parity, AGPL compact-
            # glue pins, and F10 long-debris / tag-glue / export-tag pins
            # all die when the hit helper always misses. Shape of
            # _package_denylist_hit unchanged; renamed F9 victims
            # re-anchored and F10 witnesses join the M14 victim set so
            # attribution stays strong-form (RV-07).
            # F10 renames of F9 elevated/steal band-split pins:
            "test_elevated_deny_c_hits_pure_deny_compact",
            "test_residual_classify_owns_exception_debris",
            "test_red_proof_elevated_c_alone_turns_pure_deny_pins_red",
            "test_red_proof_residual_classify_alone_turns_debris_pins_red",
            "test_deny_has_folded_ab_claim_load_bearing_for_yolo_x",
            "test_separator_twins_deny",
            "test_full_row_and_doors_deny_separator_twins",
            "test_digit_laundering_denies",
            "test_yolos_letter_twins_deny",
            "test_yoloxs_real_size_admits",
            "test_red_proof_elevated_c_flag_is_load_bearing",
            "test_red_proof_residual_classify_flag_is_load_bearing",
            "test_doors_agree_on_dual_axis_and_nc_only",
            "test_exact_ultralytics_buffalo_still_agpl_precedence",
            # F10 B13-5 / A13 compact glue + residual classification pins.
            "test_ultralyticsplus_denies_agpl",
            "test_ultralyticsplus_buffalo_l_agpl_precedence",
            "test_bare_buffalo_l_stays_nc_model_derived",
            "test_red_proof_compact_prefix_glue_flag",
            "test_long_debris_denies",
            "test_long_debris_denies_on_doors_and_row",
            "test_tag_glue_denies",
            "test_prior_deny_set_still_holds",
            "test_prior_admit_set_still_holds",  # also pins yolop_s_ultralytics deny
            "test_causal_free_in_shield_admits_exception_residual",
            "test_red_proof_max_reconst_segments_perturbation",
            # Wave F11: compact-glue / unbounded-defer / yolos-seg / honesty pins.
            "test_unbounded_defer_compact_denies_honest",
            "test_doors_and_row_deny_unbounded_defer",
            "test_compact_glue_tags_deny",
            "test_yolos_seg_forms_deny",
            "test_unknown_residual_honest_note_not_fabricated_ultralytics",
            "test_unicode_fullwidth_compact_glue_denies",
            "test_steal_returns_entry_for_unknown_compact_glue",
            # F11 red-proofs / controls that also die when hit always misses
            # (RV-07: must be named so attribution is not collateral).
            "test_separator_twin_and_bare_still_deny",
            "test_red_proof_steal_flag_turns_unbounded_defer_red",
            "test_red_proof_steal_flag_turns_compact_glue_red",
            "test_red_proof_seg_in_inventory_would_admit",
            # Wave F12: exact-residual steal, half-separated compact glue,
            # NC door promotion, honesty pins, catalog deny stems.
            "test_exact_residual_unbounded_denies_honest",
            "test_agpl_exact_residual_denies_on_doors",
            "test_controls_keep_current_behavior",
            "test_red_proof_steal_flag_turns_exact_residual_red",
            "test_half_separated_compact_glue_denies",
            "test_red_proof_steal_flag_turns_half_separated_red",
            "test_unbounded_exception_nc_denies_on_floor",
            "test_unbounded_exception_nc_denies_on_doors",
            "test_red_proof_token_has_exception_family_unbounded",
            "test_compact_glue_unknown_path_package_id",
            "test_ppyolo_deny_stems_still_deny",
            "test_compact_orthography_of_separator_tags_stays_deny",
            "test_yolof_deny_stems_still_deny",
            "test_short_residual_unknown_not_fabricated_yolo",
            "test_short_residual_unknown_on_doors_exact_entry",
            "test_f12_1_witnesses_keep_true_entries",
            "test_yoloseg_reconst_path_still_yolo",
            "test_strongest_hit_names_ultralytics_in_compound",
            "test_red_proof_reconst_suppression_is_load_bearing",
            "test_controls_exception_clean_and_existing_nc_compound",
            "test_red_proof_inventory_drop_turns_catalog_red",
            "test_red_proof_schedule_tag_drop_turns_yolof_red",
            "test_red_proof_darknet53_drop_turns_admit_red",
            # F12b-1: YOLOF coco dataset-tag deny controls + red-proof.
            "test_yolof_dataset_deny_stems_still_deny",
            "test_red_proof_coco_tag_drop_turns_yolof_red",
            # Wave F13: unofficial-sep / trailing-NC / head-glue / catalog
            # deny / steal-ranking pins die when the hit helper always
            # misses. Red-proofs precondition on a deny hit (RV-07).
            "test_unofficial_sep_agpl_denies_honest",
            "test_unofficial_sep_unknown_residual_denies",
            "test_unofficial_sep_nc_denies_on_doors",
            "test_red_proof_unofficial_separator_charset_neuter",
            "test_myarcface_stays_floor_only_door_pass",
            # Wave F14: total-fold / registry-tag / pp-merge / mid-exception
            # / 4-char head / suffix-tolerant / paddle-catalog deny pins.
            "test_total_fold_agpl_denies_honest",
            "test_total_fold_unknown_residual_denies",
            "test_total_fold_nc_denies_on_doors",
            "test_total_fold_existing_deny_controls_hold",
            "test_total_fold_br28_floor_only_unchanged",
            "test_red_proof_total_ascii_punct_fold_neuter",
            "test_registry_tag_strip_does_not_launder_deny",
            "test_red_proof_registry_tag_strip_neuter",
            "test_pp_yolov8_fail_closed",
            "test_red_proof_pp_yolo_merge_neuter",
            "test_mid_exception_nc_denies_on_doors",
            "test_prefix_and_trailing_exception_still_deny",
            "test_red_proof_mid_exception_occurrence_neuter",
            "test_yolo_head_exception_rem_denies",
            "test_existing_yolo_and_yolov8_landings_hold",
            "test_red_proof_four_char_head_min_len_neuter",
            "test_nc_head_exception_plus_residual_denies",
            "test_agpl_head_or_mid_plus_residual_denies",
            "test_exact_exception_rem_still_denies",
            "test_red_proof_suffix_tolerant_glue_neuter",
            "test_compact_glue_of_new_paddle_tags_denies",
            "test_new_tags_do_not_leak_across_families",
            "test_red_proof_ppyolo_auxhead_tag_drop",
            "test_trailing_exception_nc_denies_on_doors",
            "test_red_proof_non_prefix_exception_helper",
            "test_br28_floor_only_precision_preserved",
            "test_prefix_exception_nc_still_denies",
            "test_nc_head_exception_rem_denies_on_doors",
            "test_agpl_head_exception_rem_denies_honest",
            "test_mirrors_still_deny",
            "test_red_proof_head_known_rem_glue",
            "test_junk_prefix_exception_deny_denies_honest",
            "test_existing_deny_controls_hold",
            "test_red_proof_mid_exception_adjacency",
            "test_compact_glue_of_new_tags_stays_deny",
            "test_cross_family_tags_stay_deny",
            "test_red_proof_ppyolo_tiny_tag_drop",
            "test_red_proof_yolox_8xb8_tag_drop",
            "test_red_proof_yolof_8xb8_tag_drop",
            "test_red_proof_yolox_voc_tag_drop",
            "test_ppyoloes_still_denies",
            "test_red_proof_eplus_allowlist_drop",
            "test_yoloxyolov8seg_names_yolov8_not_yolov8s",
            "test_multi_stack_names_inner_yolo",
            "test_red_proof_honesty_bonus",
            "test_red_proof_multi_stack_recurse",
            # Wave F15: new floor/deny pins die when the hit helper misses.
            "test_junk_multi_seg_nc_floor_denies",
            "test_both_sides_junk_nc_floor_denies",
            "test_trailing_exception_promotes_junk_nc_to_door",
            "test_four_char_head_suffix_tolerant_denies",
            "test_deny_head_long_rem_denies",
            "test_existing_compact_and_separator_denies_hold",
            "test_yolobuffalo_l_is_yolo_head_plus_known_rem",
            "test_single_number_tag_fail_closes",
            "test_deny_seed_plus_registry_tag_still_denies",
            "test_mid_exception_unknown_rem_denies",
            "test_offset0_unknown_still_denies",
            "test_compact_glue_controls_stay_deny",
            "test_compact_glue_stays_deny",
            "test_yolox_dota_does_not_leak",
            "test_yoloppyoloe_is_yolo_plus_exception_spelling",
            "test_pp_yolo_nas_is_deci_nc_not_ppyolo_residual",
            "test_pp_yolo_and_pp_yolov8_unchanged",
            "test_junk_nc_without_exception_stays_floor_only",
            "test_red_proof_compact_joined_rule_e_neuter",
            "test_red_proof_mid_nc_occurrence_neuter",
            "test_red_proof_four_char_suffix_tolerant_neuter",
            "test_red_proof_long_rem_neuter",
            "test_red_proof_single_number_strip_restored",
            "test_red_proof_mid_exception_unknown_rem_neuter",
            "test_red_proof_pd_extensions_dropped",
            "test_red_proof_dota_tag_drop",
            "test_red_proof_exception_spelling_glue_neuter",
            "test_red_proof_ppyolo_nas_residual_neuter",
            "test_no_exception_stays_door_pass",
            "test_my_buffalo_l_still_denies_on_doors",
            # Wave F16: new deny pins (R18-01/04/06/09/02).
            "test_agpl_stem_junk_infix_exception_denies",
            "test_nc_stem_junk_infix_exception_denies",
            "test_elevated_and_exact_prefix_controls_hold",
            "test_classify_owned_unknown_rem_controls_hold",
            "test_known_nas_residual_is_deci_nc",
            "test_english_nas_prefix_is_not_deci",
            "test_non_vendor_pp_yoloe_still_denies",
            "test_yoloppyoloeplus_is_yolo_plus_exception_spelling",
            "test_deny_seed_plus_pd_extension_still_denies",
            "test_steal_names_fastsam_residual_honest",
            "test_f15_1_must_list_same_path_still_floor_denies",
            # Wave F17: underscore-NC gadgets + stacked-exception stem.
            "test_representative_seed_junk_spelling_denies",
            "test_variant_shapes_deny",
            "test_full_cross_product_sweep_denies",
            "test_a3_must_stay_deny_fence",
            "test_fastsam_stacked_exception_names_stem",
            "test_junk_prefix_stacked_exception_stays_yolo",
            # Wave F18 R20-01: rem-tail owner pins die when hit misses.
            "test_rem_tail_glued_axes_deny",
            "test_rem_tail_separator_twin_axes_deny",
            "test_listed_rem_tail_gadgets_deny",
            "test_full_rem_tail_cross_product_sweep_denies",
            "test_glued_rem_stays_unknown_residual",
            "test_red_proof_separate_rem_owner_neuter",
            # Wave F18 R20-02: F17 red-proofs / floor-miss contrast plus
            # two pre-F17 red-proofs that also die when hit always misses.
            "test_four_plus_suffix_junk_without_exception_is_floor_miss",
            "test_red_proof_mid_exception_unknown_rem_neuter_underscore",
            "test_red_proof_underscore_glued_owner_neuter",
            "test_red_proof_stem_over_exc_rem_neuter",
            "test_red_proof_mid_exception_unknown_rem_neuter_gadgets",
            "test_red_proof_steal_flag_turns_fastsam_residual_red",
        ),
    ),
    Mutation(
        name="M15",
        description="PENDING-LEGAL-CLEARANCE reason→UNKNOWN_SPDX (RF-02 / GATE-33)",
        apply="m15",
        expected_victims=(
            "test_gate33_audit_spdx_pending_legal_clearance_fails",
            "test_gate33_training_data_row_pending_license_fails",
            "test_gate33_tooling_row_pending_license_fails",
            "test_gate33_model_ingest_row_pending_license_fails",
            "test_gate33_occluder_asset_row_pending_license_fails",
            "test_gate33_synthetic_source_row_pending_license_fails",
        ),
    ),
    Mutation(
        name="M16",
        description="denylist reason→UNREGISTERED_DERIVED_MODEL (RF-02 / GATE-34)",
        apply="m16",
        # Wave F9 (A12-3): both AGPL-first and NC-floor floor.reason sites
        # live in shared _audit_weights_lineage_token (one edit, both doors).
        # Kill set is GATE-34 plus every pin that asserts the honest
        # denylisted_package / nc_model_derived reason on either door-
        # promotion path (RV-07). Source-door BR-24 / B12-6 AGPL pins join
        # because the shared helper is the sole reason-emission site.
        expected_victims=(
            "test_gate34_audit_derived_from_model_denylisted_package",
            "test_gate34_training_data_row_derived_ultralytics_reason",
            # Wave F7/F8 derived-path reason pins (A10-01 / B10 / B11-02).
            "test_red_proof_yolo_nas_m_pin",
            "test_prefix_witness_rejects_weights_doors",
            "test_dual_axis_rejects_both_doors_with_agpl_precedence",
            "test_membership_path_dual_axis_agpl_precedence",
            # Floor-path NC-only counters (B11-02) assert nc_model_derived
            # via the NC-axis floor.reason branch mutated here.
            "test_nc_only_compounds_still_report_nc_model_derived",
            "test_measured_admits_now_fail_closed_on_rows_and_doors",
            "test_multi_segment_under_junk_prefix_rejects_rows_and_doors",
            "test_c_shaped_door_promotion_via_monkeypatch",
            "test_scrfd_rejects_rows_and_doors",
            # Wave F9 (A12-3): source-door reason pins now share the helper.
            "test_br24_ultralytics_source_field_fails_denylisted",
            "test_exact_ultralytics_buffalo_still_agpl_precedence",
            # Wave F10: door-reason pins that hit denylisted_package via the
            # shared helper (compact glue + long-debris door surface).
            "test_ultralyticsplus_denies_agpl",
            "test_ultralyticsplus_buffalo_l_agpl_precedence",
            "test_long_debris_denies_on_doors_and_row",
            # Wave F11: B14-1 unbounded-defer door pins assert denylisted
            # package reason via the same shared helper (RV-07).
            "test_doors_and_row_deny_unbounded_defer",
            # Wave F12: door-reason pins (AGPL exact residual, NC doors,
            # honesty exact-entry).
            "test_agpl_exact_residual_denies_on_doors",
            "test_unbounded_exception_nc_denies_on_doors",
            "test_short_residual_unknown_on_doors_exact_entry",
            "test_strongest_hit_names_ultralytics_in_compound",
        ),
    ),
    Mutation(
        name="M17",
        description="unknown-category reason→UNKNOWN_SPDX (RF-02 / M7 axis)",
        apply="m17",
        expected_victims=("test_row_cannot_waive_source_via_bogus_category",),
    ),
    Mutation(
        name="M18",
        description="derived non-str reason→UNKNOWN_SPDX (RF-02 / M9 axis)",
        apply="m18",
        # Same true kill set as M9 (FIR-7-RV-07): br37 + BR-46 derived trio.
        expected_victims=(
            "test_br37_audit_derived_from_model_rejects_non_string",
            "test_br46_type_contract_table[derived-int]",
            "test_br46_type_contract_table[derived-list]",
            "test_br46_type_contract_table[derived-dict]",
        ),
    ),
    Mutation(
        name="M19",
        description="PASS-path category leak on training_data (RF-01 / GATE-27)",
        apply="m19",
        # True kill set (FIR-7-RV-07): five-door invariant plus every
        # clean/ISC/Zlib/Unlicense/operator training_data category pin that
        # asserts result.category on the PASS path.
        expected_victims=(
            "test_result_category_equals_asked_door",
            "test_clean_training_data_row_still_reports_training_data",
            "test_isc_spdx_passes_training_data",
            "test_zlib_spdx_passes_training_data",
            "test_unlicense_spdx_passes_training_data",
            "test_operator_phone_source_passes_training_data",
            "test_operator_render_source_passes_training_data",
        ),
    ),
    Mutation(
        name="M20",
        description="force PASS→FAIL to pin GATE-32 pass-witness (RF-01)",
        apply="m20",
        expected_victims=("test_gate32_every_door_has_at_least_one_pass_witness",),
        # High collateral by design — pins the pass-witness test as mediated
        # evidence, not an axis-tight kill (RF-03 smoke rationale applies).
        smoke_level=True,
    ),
    Mutation(
        name="M21",
        description=(
            "BR-53 denylist floor reason→RESEARCH_ONLY_SOURCE "
            "(RF-02 / FIR-7-RV-02)"
        ),
        apply="m21",
        expected_victims=(
            "test_denylisted_license_rejected_by_every_door",
            "test_clearance_does_not_waive_license_floor",
            "test_license_floor_reason_is_exact",
        ),
    ),
    Mutation(
        name="M22",
        description=(
            "BR-53 research floor reason→DENYLISTED_LICENSE "
            "(RF-02 / FIR-7-RV-02)"
        ),
        apply="m22",
        expected_victims=(
            "test_research_source_rejected_by_every_door",
        ),
    ),
    # FIR-7 F11 A14-3: residual-classification branch flips.
    # expected_victims = full kill-run failure bases (RV-07 strong-form).
    Mutation(
        name="M23",
        description=(
            "residual classify always legitimate "
            "(F11 A14-3 legitimate↔deny/unknown flip)"
        ),
        apply="m23",
        expected_victims=(
            # Core residual-classify / compact-glue / unknown pins.
            "test_compact_glue_tags_deny",
            "test_long_debris_denies",
            "test_long_debris_denies_on_doors_and_row",
            "test_tag_glue_denies",
            "test_yolos_seg_forms_deny",
            "test_unknown_residual_honest_note_not_fabricated_ultralytics",
            "test_red_proof_residual_classify_flag_is_load_bearing",
            "test_residual_classify_owns_exception_debris",
            "test_prior_deny_set_still_holds",
            "test_steal_returns_entry_for_unknown_compact_glue",
            "test_classify_fail_closed_default_is_unknown",
            "test_unicode_fullwidth_compact_glue_denies",
            # Reconst / debris / letter-twin surfaces that also die when
            # residual classification always returns legitimate.
            "test_digit_laundering_denies",
            "test_yolos_letter_twins_deny",
            "test_separator_twins_deny",
            "test_full_row_and_doors_deny_separator_twins",
            "test_ultralytics_artifact_forms_deny",
            "test_ultralytics_artifact_forms_deny_on_training_data_row",
            "test_each_flag_flip_alone_changes_a_pinned_outcome",
            "test_red_proof_elevated_c_alone_turns_pure_deny_pins_red",
            "test_red_proof_residual_classify_alone_turns_debris_pins_red",
            "test_causal_free_in_shield_admits_exception_residual",
            "test_red_proof_elevated_c_flag_is_load_bearing",
            "test_red_proof_max_reconst_segments_perturbation",
            "test_red_proof_steal_flag_turns_compact_glue_red",
            "test_red_proof_seg_in_inventory_would_admit",
            "test_half_separated_compact_glue_denies",
            "test_red_proof_steal_flag_turns_half_separated_red",
            "test_short_residual_unknown_not_fabricated_yolo",
            "test_short_residual_unknown_on_doors_exact_entry",
            "test_compact_glue_unknown_path_package_id",
            "test_yoloseg_reconst_path_still_yolo",
            "test_compact_orthography_of_separator_tags_stays_deny",
            "test_red_proof_inventory_drop_turns_catalog_red",
            "test_red_proof_schedule_tag_drop_turns_yolof_red",
            "test_red_proof_darknet53_drop_turns_admit_red",
            "test_red_proof_reconst_suppression_is_load_bearing",
            # F12b-1: coco drop / unknown-residual honesty die when
            # residual classify always returns legitimate.
            "test_yolof_dataset_deny_stems_still_deny",
            "test_red_proof_coco_tag_drop_turns_yolof_red",
            # Wave F13: unknown-residual / catalog-drop / eplus-drop
            # pins die when classify is forced legitimate.
            "test_unofficial_sep_unknown_residual_denies",
            "test_red_proof_unofficial_separator_charset_neuter",
            "test_red_proof_total_ascii_punct_fold_neuter",
            "test_compact_glue_of_new_tags_stays_deny",
            "test_cross_family_tags_stay_deny",
            "test_red_proof_ppyolo_tiny_tag_drop",
            "test_red_proof_yolox_8xb8_tag_drop",
            "test_red_proof_yolof_8xb8_tag_drop",
            "test_red_proof_yolox_voc_tag_drop",
            "test_ppyoloes_still_denies",
            "test_red_proof_eplus_allowlist_drop",
            "test_red_proof_multi_stack_recurse",
            # Wave F14: unknown-residual / classify-owned pins.
            "test_total_fold_unknown_residual_denies",
            "test_red_proof_registry_tag_strip_neuter",
            "test_pp_yolov8_fail_closed",
            "test_compact_glue_of_new_paddle_tags_denies",
            "test_new_tags_do_not_leak_across_families",
            "test_red_proof_ppyolo_auxhead_tag_drop",
            # Wave F15: unknown-residual / classify-owned pins.
            "test_single_number_tag_fail_closes",
            "test_mid_exception_unknown_rem_denies",
            "test_offset0_unknown_still_denies",
            "test_compact_glue_stays_deny",
            "test_yolox_dota_does_not_leak",
            "test_red_proof_single_number_strip_restored",
            "test_pp_yolo_and_pp_yolov8_unchanged",
            "test_four_char_head_suffix_tolerant_denies",
            "test_red_proof_four_char_suffix_tolerant_neuter",
            "test_red_proof_long_rem_neuter",
            "test_red_proof_mid_exception_unknown_rem_neuter",
            "test_compact_glue_controls_stay_deny",
            "test_red_proof_pd_extensions_dropped",
            "test_red_proof_dota_tag_drop",
            "test_red_proof_exception_spelling_glue_neuter",
            "test_red_proof_ppyolo_nas_residual_neuter",
            # Wave F16/F17: classify-owned NAS / unknown-rem pins.
            # R18-01 gadgets are prefix-owner, not classify (R19-09);
            # the gadget red-proof still dies here via classify-owned
            # siblings (yoloxsextra / yoloyoloxextra). R19-10 lists
            # only the classify-owned split, not the elevated/(c) rows.
            "test_known_nas_residual_is_deci_nc",
            "test_english_nas_prefix_is_not_deci",
            "test_classify_owned_unknown_rem_controls_hold",
            "test_red_proof_mid_exception_unknown_rem_neuter_gadgets",
        ),
    ),
    Mutation(
        name="M24",
        description=(
            "deny-reconstituting branch → legitimate "
            "(F11 A14-3 reconst↔legitimate flip)"
        ),
        apply="m24",
        expected_victims=(
            "test_prior_deny_set_still_holds",
            "test_yolos_letter_twins_deny",
            "test_digit_laundering_denies",
            "test_separator_twins_deny",
            "test_residual_classify_owns_exception_debris",
            # Full kill-run bases (RV-07): reconst flip also admits
            # artifact-form / compact-glue / tag-glue reconst paths.
            "test_ultralytics_artifact_forms_deny",
            "test_ultralytics_artifact_forms_deny_on_training_data_row",
            "test_compact_glue_tags_deny",
            "test_tag_glue_denies",
            "test_full_row_and_doors_deny_separator_twins",
            "test_red_proof_residual_classify_alone_turns_debris_pins_red",
            "test_red_proof_residual_classify_flag_is_load_bearing",
            "test_red_proof_max_reconst_segments_perturbation",
            "test_yolos_seg_forms_deny",
            # F12-7: unicode yoloxpt / compact-glue pt/c5 / half-separated
            # peel now land on unknown, not reconst. Honest reconst
            # (yoloseg / yolos_eg) still dies here.
            "test_yoloseg_reconst_path_still_yolo",
            "test_red_proof_reconst_suppression_is_load_bearing",
        ),
    ),
    Mutation(
        name="M25",
        description=(
            "unknown residual fail-closed default → legitimate "
            "(F11 A14-3 fail-open unknown default)"
        ),
        apply="m25",
        expected_victims=(
            "test_compact_glue_tags_deny",
            "test_unknown_residual_honest_note_not_fabricated_ultralytics",
            "test_yolos_seg_forms_deny",
            "test_unicode_fullwidth_compact_glue_denies",
            "test_steal_returns_entry_for_unknown_compact_glue",
            "test_classify_fail_closed_default_is_unknown",
            "test_long_debris_denies",
            "test_long_debris_denies_on_doors_and_row",
            "test_tag_glue_denies",
            # Full kill-run bases (RV-07): unknown→legitimate also opens
            # reconst / debris / artifact-form surfaces.
            "test_ultralytics_artifact_forms_deny",
            "test_ultralytics_artifact_forms_deny_on_training_data_row",
            "test_residual_classify_owns_exception_debris",
            "test_red_proof_elevated_c_alone_turns_pure_deny_pins_red",
            "test_red_proof_residual_classify_alone_turns_debris_pins_red",
            "test_separator_twins_deny",
            "test_full_row_and_doors_deny_separator_twins",
            "test_digit_laundering_denies",
            "test_causal_free_in_shield_admits_exception_residual",
            "test_red_proof_residual_classify_flag_is_load_bearing",
            "test_red_proof_elevated_c_flag_is_load_bearing",
            "test_red_proof_max_reconst_segments_perturbation",
            "test_prior_deny_set_still_holds",
            "test_red_proof_steal_flag_turns_compact_glue_red",
            "test_red_proof_seg_in_inventory_would_admit",
            # F12-7: short rem + compact glue + half-separated peel land here.
            "test_short_residual_unknown_not_fabricated_yolo",
            "test_short_residual_unknown_on_doors_exact_entry",
            "test_compact_glue_unknown_path_package_id",
            "test_half_separated_compact_glue_denies",
            "test_red_proof_steal_flag_turns_half_separated_red",
            "test_yolos_letter_twins_deny",
            "test_compact_orthography_of_separator_tags_stays_deny",
            "test_red_proof_inventory_drop_turns_catalog_red",
            "test_red_proof_schedule_tag_drop_turns_yolof_red",
            "test_red_proof_darknet53_drop_turns_admit_red",
            "test_red_proof_reconst_suppression_is_load_bearing",
            # F12b-1: unknown residual + coco-drop red-proof land here.
            "test_yolof_dataset_deny_stems_still_deny",
            "test_red_proof_coco_tag_drop_turns_yolof_red",
            # Wave F13: unknown-residual deny pins + catalog/eplus
            # red-proofs whose fail-closed landing is unknown-default.
            "test_unofficial_sep_unknown_residual_denies",
            "test_red_proof_unofficial_separator_charset_neuter",
            "test_red_proof_total_ascii_punct_fold_neuter",
            "test_compact_glue_of_new_tags_stays_deny",
            "test_cross_family_tags_stay_deny",
            "test_red_proof_ppyolo_tiny_tag_drop",
            "test_red_proof_yolox_8xb8_tag_drop",
            "test_red_proof_yolof_8xb8_tag_drop",
            "test_red_proof_yolox_voc_tag_drop",
            "test_ppyoloes_still_denies",
            "test_red_proof_eplus_allowlist_drop",
            "test_red_proof_multi_stack_recurse",
            # Wave F14: unknown-residual / classify-owned pins.
            "test_total_fold_unknown_residual_denies",
            "test_red_proof_registry_tag_strip_neuter",
            "test_pp_yolov8_fail_closed",
            "test_compact_glue_of_new_paddle_tags_denies",
            "test_new_tags_do_not_leak_across_families",
            "test_red_proof_ppyolo_auxhead_tag_drop",
            # Wave F15: unknown-residual fail-closed pins.
            "test_single_number_tag_fail_closes",
            "test_mid_exception_unknown_rem_denies",
            "test_offset0_unknown_still_denies",
            "test_compact_glue_stays_deny",
            "test_yolox_dota_does_not_leak",
            "test_red_proof_single_number_strip_restored",
            "test_pp_yolo_and_pp_yolov8_unchanged",
            "test_four_char_head_suffix_tolerant_denies",
            "test_red_proof_four_char_suffix_tolerant_neuter",
            "test_red_proof_long_rem_neuter",
            "test_red_proof_mid_exception_unknown_rem_neuter",
            "test_compact_glue_controls_stay_deny",
            "test_red_proof_pd_extensions_dropped",
            "test_red_proof_dota_tag_drop",
            "test_red_proof_exception_spelling_glue_neuter",
            "test_red_proof_ppyolo_nas_residual_neuter",
            # Wave F16/F17: unknown-default pins. R18-01 gadgets are
            # prefix-owner, not classify (R19-09). R19-10: only the
            # classify-owned split is a mutant witness here.
            "test_english_nas_prefix_is_not_deci",
            "test_classify_owned_unknown_rem_controls_hold",
            "test_red_proof_mid_exception_unknown_rem_neuter_gadgets",
        ),
    ),
    Mutation(
        name="M26",
        description=(
            "B14-1 unbounded-defer residual deny steal skipped "
            "(F11 A14-3 defer re-queue hole)"
        ),
        apply="m26",
        expected_victims=(
            "test_unbounded_defer_compact_denies_honest",
            "test_doors_and_row_deny_unbounded_defer",
            "test_red_proof_steal_flag_turns_unbounded_defer_red",
            # F12-1: exact residual steal is the same unbounded-defer branch.
            "test_exact_residual_unbounded_denies_honest",
            "test_agpl_exact_residual_denies_on_doors",
            "test_red_proof_steal_flag_turns_exact_residual_red",
            "test_strongest_hit_names_ultralytics_in_compound",
            "test_controls_keep_current_behavior",
            "test_unbounded_exception_nc_denies_on_floor",
            "test_unbounded_exception_nc_denies_on_doors",
            "test_ppyolo_deny_stems_still_deny",
            "test_yolof_deny_stems_still_deny",
            "test_f12_1_witnesses_keep_true_entries",
            # F12b-1: yolofultralyticsplus / yolofyolo still need steal.
            "test_yolof_dataset_deny_stems_still_deny",
            # Wave F13: unofficial-sep AGPL / multi-stack / honest-rem
            # steal pins need the unbounded-defer steal branch.
            "test_unofficial_sep_agpl_denies_honest",
            "test_yoloxyolov8seg_names_yolov8_not_yolov8s",
            "test_multi_stack_names_inner_yolo",
            "test_red_proof_honesty_bonus",
            "test_red_proof_multi_stack_recurse",
            # Wave F14: steal-owned fold / honesty pins that die once M26
            # actually applies (post-F13-6 re-anchor).
            "test_existing_deny_controls_hold",
            "test_mirrors_still_deny",
            "test_red_proof_four_char_head_min_len_neuter",
            "test_red_proof_head_known_rem_glue",
            "test_red_proof_mid_exception_adjacency",
            "test_red_proof_total_ascii_punct_fold_neuter",
            "test_red_proof_unofficial_separator_charset_neuter",
            # Wave F16: steal-path pins that actually die under M26
            # (R18-02: the six F15 names were immune).
            "test_steal_names_fastsam_residual_honest",
            "test_red_proof_steal_flag_turns_fastsam_residual_red",
        ),
    ),
]

_APPLIERS = {
    "control": _m_control_inert_comment,
    "m1": _m1_unknown_spdx_pass,
    "m2": _m2_drop_insightface_patterns,
    "m3": _m3_empty_nc_ids,
    "m4": _m4_exact_research_only,
    "m5": _m5_empty_required_names,
    "m6": _m6_empty_synthetic_token_loop,
    "m7": _m7_category_valueerror_pass,
    "m8": _m8_research_exact_only,
    "m9": _m9_skip_derived_type_guard,
    "m10": _m10_disable_generator_lineage_branch,
    "m11": _m11_collapse_separator_parity,
    "m12": _m12_ingest_entry_raise_pass,
    "m13": _m13_pending_legal_clearance_pass,
    "m14": _m14_package_denylist_always_miss,
    "m15": _m15_pending_reason_swap,
    "m16": _m16_denylist_reason_swap,
    "m17": _m17_invalid_category_reason_swap,
    "m18": _m18_derived_type_reason_swap,
    "m19": _m19_leak_category_training_data,
    "m20": _m20_gate32_pass_witness_probe,
    "m21": _m21_br53_denylist_reason_to_research,
    "m22": _m22_br53_research_reason_to_denylist,
    "m23": _m23_residual_classify_always_legitimate,
    "m24": _m24_deny_reconst_to_legitimate,
    "m25": _m25_unknown_default_to_legitimate,
    "m26": _m26_b141_unbounded_defer_steal_skip,
}


# ---------------------------------------------------------------------------
# Subprocess env + junitxml (BR-49)
# ---------------------------------------------------------------------------


def _scrubbed_env() -> dict[str, str]:
    """Build child env from an allowlist; pytest/python injection vars excluded."""
    env: dict[str, str] = {}
    for key, val in os.environ.items():
        if key in _ENV_DENY_EXACT:
            continue
        if key.startswith("PYTEST_DEBUG"):
            continue
        if key.startswith("PYTEST_"):
            continue
        if key in _ENV_ALLOWLIST or key.startswith("LC_"):
            env[key] = val
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # Belt: ensure injection vectors are absent even if allowlist grows.
    for bad in _ENV_DENY_EXACT:
        env.pop(bad, None)
    for key in list(env):
        if key.startswith("PYTEST_DEBUG") or (
            key.startswith("PYTEST_") and key != "PYTEST_DISABLE_PLUGIN_AUTOLOAD"
        ):
            env.pop(key, None)
    return env


def _parse_junitxml(junit_path: Path) -> tuple[int, list[str], str | None]:
    """Return (executed_count, failed_test_names, parse_error).

    Failed names are the pytest test-name component (``name`` attribute),
    including parametrised ``name[param]`` form when present.
    """
    if not junit_path.is_file():
        return 0, [], f"junitxml missing: {junit_path}"
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError as exc:
        return 0, [], f"junitxml parse error: {exc}"
    root = tree.getroot()
    # pytest may emit <testsuites><testsuite>… or a bare <testsuite>.
    cases = root.findall(".//testcase")
    failed: list[str] = []
    for case in cases:
        name = case.get("name") or ""
        # failure / error children mark a non-pass (skip is neither).
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(name)
    return len(cases), failed, None


def classify_suite_result(
    report: SuiteReport,
    *,
    baseline_executed: int | None = None,
) -> Verdict:
    """Three-way classification (FIR-7-BR-17 / BR-49 / TEST-15).

    - rc == 0 → SURVIVED
    - executed count ≠ baseline → HARNESS-ERROR (forgery / collection miss)
    - rc == 1 and ≥1 failed testcase in junit → KILLED
    - anything else (rc >= 2, import/collection errors, missing junit,
      rc==1 without failed testcases) → HARNESS-ERROR
    """
    if report.parse_error:
        return Verdict.HARNESS_ERROR
    if report.executed < 1:
        return Verdict.HARNESS_ERROR
    if baseline_executed is not None and report.executed != baseline_executed:
        return Verdict.HARNESS_ERROR
    if report.rc == 0:
        return Verdict.SURVIVED
    if report.rc == 1 and report.failed_names:
        return Verdict.KILLED
    return Verdict.HARNESS_ERROR


def _test_name_from_nodeid(node: str) -> str:
    """Last ``::`` component of a nodeid (``name`` or ``name[param]``)."""
    return node.rsplit("::", 1)[-1]


def _name_component_matches(observed: str, expected: str) -> bool:
    """Match a pinned victim name against a collected/junit test name (BR-17).

    Parametrised ids use ``name[param]``. A pinned victim may be either the
    full ``name[param]`` or the bare function name (matches any param). A
    victim that is only a prefix of another test name does **not** match.
    Shared by kill discrimination and GATE-14 existence (one matcher).
    """
    tname = _test_name_from_nodeid(observed)
    base = tname.split("[", 1)[0]
    return expected == tname or expected == base


def _victims_matched(failed_names: list[str], expected: tuple[str, ...]) -> list[str]:
    """Exact test-name match (BR-17) — no substring/prefix matching.

    Parametrised failures use the ``name[param]`` form from junit. An expected
    victim may be either the full ``name[param]`` or the bare function name
    (matches any param of that test). A victim that is only a prefix of another
    test name does **not** match.
    """
    if not expected:
        return []
    hits: list[str] = []
    for exp in expected:
        for raw in failed_names:
            if _name_component_matches(raw, exp):
                if exp not in hits:
                    hits.append(exp)
                break
    return hits


def _normalize_nodeid(line: str) -> str:
    """Canonicalise a pytest nodeid to ``basename.py::...`` form.

    Strips any leading path components so collect-only output that includes
    a directory prefix still matches the recorded floor ids.
    """
    line = line.strip()
    if "::" not in line:
        return line
    left, right = line.split("::", 1)
    base = left.rsplit("/", 1)[-1]
    if base.endswith(".py"):
        return f"{base}::{right}"
    return line


def _collect_nodeids(test_path: Path) -> tuple[tuple[str, ...], str | None]:
    """Collect full normalised nodeids from one unmutated suite file (RF-01)."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_path.name),
        "--collect-only",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    env = _scrubbed_env()
    proc = subprocess.run(
        cmd,
        cwd=str(test_path.parent),
        capture_output=True,
        text=True,
        env=env,
    )
    raw = (proc.stdout or "") + (proc.stderr or "")
    # pytest rc=5 means "no tests collected" — treat as empty set so the
    # RF-01 subset / absolute-floor checks report the coverage loss rather
    # than a collect harness error (FIR-7-LR-03 gutting red-prove).
    if proc.returncode not in (0, 1, 5):
        return (), (
            f"pytest --collect-only failed rc={proc.returncode}: "
            f"{raw.strip().splitlines()[-3:] if raw.strip() else '(no output)'}"
        )
    nodeids: list[str] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        if line.startswith("="):
            continue
        # Skip summary lines ("756 tests collected in 0.08s").
        if " " in line and not line.split("::", 1)[0].endswith(".py"):
            continue
        nid = _normalize_nodeid(line)
        if nid.count("::") < 1:
            continue
        nodeids.append(nid)
    if not nodeids:
        # Empty is a valid collect outcome (gutted file, deselected suite).
        # Callers merge across floored files and apply subset / absolute floor.
        return (), None
    return tuple(sorted(set(nodeids))), None


def _floored_test_files() -> tuple[Path, ...]:
    """Return the floored suite files that currently exist on disk."""
    return tuple(p for p in _FLOORED_TEST_FILES if p.is_file())


def _collect_floored_nodeids(
    test_paths: tuple[Path, ...] | None = None,
) -> tuple[tuple[str, ...], str | None]:
    """Collect + merge normalised nodeids from all floored suite files.

    Covers test_license_policy.py, test_license_policy_hardening.py, and
    test_equivalence_claims.py when present (FIR-7-LR-03).
    """
    paths = test_paths if test_paths is not None else _floored_test_files()
    if not paths:
        return (), "no floored test files present on disk"
    all_ids: set[str] = set()
    for path in paths:
        nodeids, err = _collect_nodeids(path)
        if err is not None:
            return (), f"{path.name}: {err}"
        all_ids.update(nodeids)
    if not all_ids:
        return (), "pytest --collect-only produced zero nodeids across floored files"
    return tuple(sorted(all_ids)), None


def _name_components_from_nodeids(nodeids: tuple[str, ...]) -> frozenset[str]:
    """Derive GATE-14 name components (bare + parametrised) from full nodeids."""
    names: set[str] = set()
    for nid in nodeids:
        tname = _test_name_from_nodeid(nid)
        if not tname or tname.startswith("["):
            continue
        names.add(tname)
        names.add(tname.split("[", 1)[0])
    return frozenset(names)


def _load_nodeid_baseline(path: Path) -> tuple[frozenset[str], str | None]:
    """Load node-id baseline from the on-disk fixture only (fail-closed).

    An absent, non-file (directory), broken-symlink, empty, or unreadable
    fixture is a HARNESS-ERROR. The embedded set is a bootstrap for
    ``--record-baseline`` drop accounting only — never a runtime fallback
    (FIR-7-LR-02 / SECD-03).

    When the fixture loads successfully it is cross-checked against the
    embedded set: the file must be a *superset* of the embedded set so an
    agent that edits the on-disk fixture alone cannot silently shrink the
    floor (SECD-03, TEST-15).
    """
    # Fail closed: missing path, broken symlink, directory, or non-file.
    # Do not fall back to the embedded copy at runtime (FIR-7-LR-02).
    try:
        is_symlink = path.is_symlink()
    except OSError as exc:
        return frozenset(), f"node-id baseline fixture unreadable: {path}: {exc}"
    if is_symlink and not path.exists():
        return frozenset(), (
            f"node-id baseline fixture unreadable: {path} (broken symlink)"
        )
    if not path.exists():
        return frozenset(), f"node-id baseline fixture missing: {path}"
    if not path.is_file():
        kind = "directory" if path.is_dir() else "not a regular file"
        return frozenset(), (
            f"node-id baseline fixture unreadable: {path} ({kind})"
        )

    recorded: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError subclasses ValueError, not OSError: a readable
        # but non-UTF-8 fixture would otherwise escape as a raw traceback
        # while every sibling malformed-fixture branch reports HARNESS-ERROR.
        errno = getattr(exc, "errno", None)
        errno_part = f" [errno {errno}]" if errno is not None else ""
        return frozenset(), (
            f"node-id baseline fixture unreadable: {path}{errno_part}: {exc}"
        )
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        recorded.add(_normalize_nodeid(line))
    if not recorded:
        return frozenset(), f"node-id baseline fixture empty: {path}"
    dropped = frozenset(_EMBEDDED_NODEID_BASELINE) - recorded
    if dropped:
        sample = ", ".join(sorted(dropped)[:3])
        return frozenset(), (
            f"node-id baseline fixture {path} is missing "
            f"{len(dropped)} id(s) still present in "
            "_EMBEDDED_NODEID_BASELINE, e.g. "
            f"{sample}. The fixture may only grow. If the coverage loss "
            "is real, fix it; if it is intentional, run "
            "'python mutation_guard.py --record-baseline', which rewrites "
            "both copies -- regenerating after an unexplained loss is "
            "exactly the mistake this gate exists to catch."
        )
    return frozenset(recorded), None


def _write_nodeid_baseline(path: Path, nodeids: tuple[str, ...]) -> None:
    """Rewrite the node-id fixture (explicit operator action only).

    Also rewrites ``_EMBEDDED_NODEID_BASELINE`` and ``ABSOLUTE_NODEID_FLOOR``
    in this module so the embedded-baseline cross-check and absolute-count
    floor remain consistent (review-visible Python source; FIR-7-RV-05).

    Refuses to write through a symlink (FIR-7-C2-03): the operator must
    replace a symlink path with a regular file before re-recording.
    """
    if path.is_symlink():
        raise OSError(
            f"node-id baseline path is a symlink (refusing to write through it): {path}"
        )
    header = (
        "# mutation_guard node-id baseline (subset semantics: live ⊇ recorded)\n"
        "# Coverage may grow; it must never shrink.\n"
        "# Floored files: test_license_policy.py, "
        "test_license_policy_hardening.py, test_equivalence_claims.py\n"
        "# Regenerate ONLY via: python mutation_guard.py --record-baseline\n"
        "# Regenerating this file after a coverage *loss* is exactly the\n"
        "# mistake this gate exists to catch (RF-01 / TEST-15 / SECD-03).\n"
        "# Drops require --allow-drop (FIR-7-RV-06).\n"
    )
    body = "\n".join(sorted(nodeids))
    path.write_text(header + body + "\n", encoding="utf-8")

    # Keep the embedded copy identical so the embedded-baseline cross-check continues to
    # catch agents that edit only the on-disk fixture.
    guard_path = Path(__file__).resolve()
    src = guard_path.read_text(encoding="utf-8")
    begin = src.find("_EMBEDDED_NODEID_BASELINE: frozenset[str] = frozenset({")
    if begin < 0:
        print(
            "WARN: could not locate _EMBEDDED_NODEID_BASELINE to rewrite; "
            "fixture file updated only.",
            flush=True,
        )
        return
    end = src.find("})", begin)
    if end < 0:
        print("WARN: malformed _EMBEDDED_NODEID_BASELINE; fixture file updated only.", flush=True)
        return
    end = end + 2  # include closing })
    new_block_lines = ["_EMBEDDED_NODEID_BASELINE: frozenset[str] = frozenset({"]
    for nid in sorted(nodeids):
        new_block_lines.append(f"    {nid!r},")
    new_block_lines.append("})")
    new_src = src[:begin] + "\n".join(new_block_lines) + src[end:]
    # Sync absolute count floor to the newly recorded set size (FIR-7-RV-05).
    floor_re = re.compile(
        r"^ABSOLUTE_NODEID_FLOOR\s*=\s*\d+[^\n]*$",
        re.MULTILINE,
    )
    floor_line = (
        f"ABSOLUTE_NODEID_FLOOR = {len(nodeids)}  "
        "# synced by --record-baseline; growth requires re-record"
    )
    if floor_re.search(new_src):
        new_src = floor_re.sub(floor_line, new_src, count=1)
    else:
        print(
            "WARN: could not locate ABSOLUTE_NODEID_FLOOR to rewrite; "
            "embedded set updated without absolute-floor sync.",
            flush=True,
        )
    guard_path.write_text(new_src, encoding="utf-8")
    print(
        f"NODEID-BASELINE: also rewrote embedded bootstrap + "
        f"ABSOLUTE_NODEID_FLOOR={len(nodeids)} in {guard_path.name}",
        flush=True,
    )


def _nodeid_subset_errors(
    recorded: frozenset[str],
    live: frozenset[str],
) -> list[str]:
    """RF-01: live collect must be a superset of the recorded node-id set.

    Equality is deliberately rejected: another lane may add tests; growth must
    stay green. Shrinkage (hollowed parametrisation, deselected victims) is a
    HARNESS-ERROR. Do **not** regenerate the fixture to silence a loss.
    """
    missing = sorted(recorded - live)
    if not missing:
        return []
    sample = missing[:12]
    more = f" (+{len(missing) - len(sample)} more)" if len(missing) > len(sample) else ""
    return [
        "HARNESS-ERROR RF-01: live collect is missing "
        f"{len(missing)} recorded node-id(s) (subset check: live must be "
        "superset of mutation_guard_nodeid_baseline.txt). "
        "Coverage may grow; it must never shrink. "
        "If this fired after a real intentional expansion of the suite you "
        "may run --record-baseline; regenerating after a coverage *loss* is "
        "exactly the mistake this gate exists to catch.\n"
        f"  missing sample: {sample}{more}"
    ]


def _count_failed_matching_victims(
    failed_names: list[str],
    expected: tuple[str, ...],
) -> int:
    """Count failed test names that match any expected victim (param-expanded)."""
    if not expected:
        return 0
    n = 0
    for raw in failed_names:
        if any(_name_component_matches(raw, exp) for exp in expected):
            n += 1
    return n


def _collateral_count(failed_names: list[str], expected: tuple[str, ...]) -> int:
    """RF-03: |failed| − |victims_matched, parametrisation-expanded|."""
    return max(0, len(failed_names) - _count_failed_matching_victims(failed_names, expected))


def _pinned_victim_existence_errors(
    mutations: list[Mutation],
    collected: frozenset[str],
) -> list[str]:
    """GATE-14: every expected_victims name must exist in the unmutated suite.

    A renamed/deleted pinned victim must be HARNESS-ERROR, never SURVIVED or
    KILLED (SECD-03 complete mediation of the guard's own config; TEST-15).
    """
    errors: list[str] = []
    for mutation in mutations:
        for victim in mutation.expected_victims:
            # collected already holds bare + parametrised components; exact
            # membership is enough because both forms were inserted. Also
            # accept via the shared matcher against every collected id so a
            # bare pin matches a parametrised-only collection entry.
            if victim in collected:
                continue
            if any(_name_component_matches(obs, victim) for obs in collected):
                continue
            errors.append(
                f"HARNESS-ERROR {mutation.name}: pinned victim {victim!r} "
                "does not exist in unmutated test_license_policy.py "
                "(GATE-14 — renamed/deleted victim must not degrade to "
                "SURVIVED/KILLED)"
            )
    return errors


def _require_kill_allowlist_errors(
    mutations: list[Mutation],
) -> tuple[list[str], list[str]]:
    """FIR-7-RV-04 / FIR-7-C2-02 / FIR-7-C3-02: require_kill allowlist check.

    Startup structural alarm — fires before any pytest run so a new weak
    flag cannot ship as a silent known_gap. Iterates the **full** mutations
    table (selection-independent): ``require_kill`` is a static table
    property, not a per-run filter (FIR-7-C2-02).

    Also pins ``KNOWN_GAP_ALLOWED`` against an inline literal so a rebind of
    the module-level frozenset must edit this check site too (frozenset
    blocks ``.add`` but not rebind — same review-visibility bar as
    ``ABSOLUTE_NODEID_FLOOR``).

    Returns ``(pin_errors, mutant_errors)`` so the FAIL footer can name
    constant-pin failures separately from unauthorised known_gap mutants
    (FIR-7-C3-02) — a pin-only rebind must not be mislabelled as a mutant
    allowlist violation.
    """
    pin_errors: list[str] = []
    mutant_errors: list[str] = []
    # Inline literal pin (FIR-7-C2-02): rebind of KNOWN_GAP_ALLOWED alone is
    # not enough — the expected set is duplicated here on purpose.
    _KNOWN_GAP_ALLOWED_PIN = frozenset({"CONTROL", "M6"})
    if KNOWN_GAP_ALLOWED != _KNOWN_GAP_ALLOWED_PIN:
        pin_errors.append(
            "HARNESS-ERROR: KNOWN_GAP_ALLOWED was rebound to "
            f"{sorted(KNOWN_GAP_ALLOWED)!r}; expected "
            f"{sorted(_KNOWN_GAP_ALLOWED_PIN)!r}. Update the inline pin in "
            "_require_kill_allowlist_errors in the same commit (FIR-7-C2-02)."
        )
    allowed = ", ".join(sorted(KNOWN_GAP_ALLOWED))
    for mutation in mutations:
        if mutation.require_kill:
            continue
        if mutation.name in KNOWN_GAP_ALLOWED:
            continue
        mutant_errors.append(
            f"HARNESS-ERROR {mutation.name}: require_kill=False is not in "
            f"KNOWN_GAP_ALLOWED={{{allowed}}}; a new known_gap requires "
            "editing that named constant with a comment explaining the "
            "review bar (FIR-7-RV-04)"
        )
    return pin_errors, mutant_errors


def _resolve_victim_nodeids(
    victims: tuple[str, ...],
    live_nodeids: tuple[str, ...],
    *,
    kill_file: str | None = None,
) -> list[str]:
    """Map expected_victims name components to full kill-file nodeids.

    Used by strong-form attribution (FIR-7-RV-07) to build ``--deselect``
    arguments. Bare victim names expand to every matching parametrisation.
    """
    kill = kill_file if kill_file is not None else _TEST.name
    prefix = f"{kill}::"
    resolved: list[str] = []
    seen: set[str] = set()
    for nid in live_nodeids:
        if not nid.startswith(prefix):
            continue
        tname = _test_name_from_nodeid(nid)
        for victim in victims:
            if _name_component_matches(tname, victim):
                if nid not in seen:
                    resolved.append(nid)
                    seen.add(nid)
                break
    return resolved


def _run_suite(
    scratch_dir: Path,
    *,
    deselect: list[str] | None = None,
) -> SuiteReport:
    """Run the license_policy suite against a scratch copy; parse junitxml.

    ``deselect`` is an optional list of full nodeids passed as
    ``--deselect=`` (FIR-7-RV-07 strong-form attribution re-run).
    """
    test_path = scratch_dir / "test_license_policy.py"
    junit_path = scratch_dir / "report.xml"
    if junit_path.exists():
        junit_path.unlink()
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_path),
        "-q",
        "--tb=no",
        "-p",
        "no:cacheprovider",
        f"--junitxml={junit_path}",
    ]
    if deselect:
        for nid in deselect:
            cmd.append(f"--deselect={nid}")
    env = _scrubbed_env()
    proc = subprocess.run(
        cmd,
        cwd=str(scratch_dir),
        capture_output=True,
        text=True,
        env=env,
    )
    raw = (proc.stdout or "") + (proc.stderr or "")
    executed, failed_names, parse_error = _parse_junitxml(junit_path)
    # Build summary from the same fields the dataclass will hold.
    if parse_error:
        summary = f"HARNESS-ERROR ({parse_error})"
    else:
        n_fail = len(failed_names)
        n_ok = executed - n_fail
        if proc.returncode == 0:
            summary = f"{executed} passed (junit executed={executed})"
        else:
            summary = (
                f"{n_fail} failed, {n_ok} passed "
                f"(junit executed={executed}, rc={proc.returncode})"
            )
    return SuiteReport(
        rc=proc.returncode,
        executed=executed,
        failed_names=tuple(failed_names),
        summary=summary,
        raw_out=raw,
        junit_path=junit_path if junit_path.is_file() else None,
        parse_error=parse_error,
    )


def _prepare_scratch(base: Path) -> Path:
    """Layout a mini tree the test loader can resolve (parents[3] = repo root)."""
    # test uses Path(__file__).resolve().parents[3] as repo root.
    # __file__ = <scratch>/scripts/train/occlusion/test_license_policy.py
    # parents[0]=occlusion, [1]=train, [2]=scripts, [3]=scratch root
    occ = base / "scripts" / "train" / "occlusion"
    occ.mkdir(parents=True, exist_ok=True)
    (base / "scripts" / "train" / "__init__.py").write_text("", encoding="utf-8")
    (occ / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(_POLICY, occ / "license_policy.py")
    shutil.copy2(_TEST, occ / "test_license_policy.py")
    return occ


def _apply_mutation(policy_src: str, mutation: Mutation) -> str:
    applier = _APPLIERS[mutation.apply]
    return applier(policy_src)


def _run_baseline() -> tuple[bool, str, int]:
    """Unmutated suite must be green before any mutant verdict is meaningful.

    Returns (ok, info, baseline_executed).
    """
    with tempfile.TemporaryDirectory(prefix="licpol-baseline-") as tmp:
        occ = _prepare_scratch(Path(tmp))
        report = _run_suite(occ)
        if (
            report.rc == 0
            and report.parse_error is None
            and report.executed >= 1
            and classify_suite_result(report) is Verdict.SURVIVED
        ):
            return True, report.summary, report.executed
        return (
            False,
            f"rc={report.rc} executed={report.executed} "
            f"summary={report.summary!r}\n{report.raw_out}",
            report.executed,
        )


def _parent_env_injection_vars() -> list[str]:
    """Return ambient injection vars that must not be present when the guard runs.

    Child scrub is necessary but not sufficient if an operator (or CI wrapper)
    believes exporting PYTEST_ADDOPTS is harmless. Refuse to certify under a
    tainted parent env (SECD-03 complete mediation).
    """
    bad: list[str] = []
    for key in (
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONSTARTUP",
        "PYTHONHOME",
    ):
        if os.environ.get(key):
            bad.append(key)
    # PYTHONPATH is the load path for `-p certify_nothing`-style plugins.
    if os.environ.get("PYTHONPATH"):
        bad.append("PYTHONPATH")
    for key in os.environ:
        if key.startswith("PYTEST_DEBUG") and os.environ.get(key):
            bad.append(key)
    return bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mutation",
        choices=[m.name for m in MUTATIONS] + ["all"],
        default="all",
        help="Run a single mutation or all (default: all)",
    )
    parser.add_argument(
        "--record-baseline",
        action="store_true",
        help=(
            "Rewrite mutation_guard_nodeid_baseline.txt from the live collect "
            "set and exit. Use only when coverage intentionally grew; "
            "regenerating after a coverage loss defeats RF-01. Drops require "
            "--allow-drop (FIR-7-RV-06)."
        ),
    )
    parser.add_argument(
        "--allow-drop",
        action="store_true",
        help=(
            "With --record-baseline: permit writing a baseline that drops "
            "previously recorded node-ids. Without this flag any drop is "
            "EXIT=2 and no files are written (FIR-7-RV-06)."
        ),
    )
    args = parser.parse_args(argv)

    if not _POLICY.is_file() or not _TEST.is_file():
        print(
            "ERROR: license_policy.py / test_license_policy.py missing "
            f"(looked under {_HERE})",
            file=sys.stderr,
        )
        return 2

    injected = _parent_env_injection_vars()
    if injected:
        print(
            "HARNESS-ERROR: refusing to run mutation guard under injected "
            f"pytest/python env: {', '.join(injected)}\n"
            "Unset these variables before certifying (BR-49 / SECD-03). "
            "Child subprocesses also scrub via an allowlist; parent refusal "
            "closes the 'export and forget' path.",
            flush=True,
        )
        return 2

    selected = (
        MUTATIONS
        if args.mutation == "all"
        else [m for m in MUTATIONS if m.name == args.mutation]
    )

    # --- FIR-7-RV-04 / FIR-7-C2-02 / FIR-7-C3-02: require_kill allowlist --
    # Structural alarm at STARTUP — before any pytest / collect / baseline.
    # Walk the ENTIRE MUTATIONS table (selection-independent): require_kill
    # is a static table property. Running `--mutation CONTROL` must still
    # alarm on M15.require_kill=False if that flag is unauthorised.
    # FIR-7-C3-02: pin/rebind failures and mutant allowlist violations are
    # counted and footered separately so a pin-only rebind is not mislabelled
    # as an unauthorised known_gap mutant.
    pin_errors, mutant_errors = _require_kill_allowlist_errors(MUTATIONS)
    if pin_errors or mutant_errors:
        for line in pin_errors + mutant_errors:
            print(line, flush=True)
        footer_parts: list[str] = []
        if pin_errors:
            n = len(pin_errors)
            footer_parts.append(
                f"{n} constant-pin failure" if n == 1 else f"{n} constant-pin failures"
            )
        if mutant_errors:
            footer_parts.append(
                f"{len(mutant_errors)} unauthorised known_gap mutant(s)"
            )
        print(
            f"FAIL: require_kill allowlist "
            f"({'; '.join(footer_parts)}; "
            "FIR-7-RV-04 / FIR-7-C2-02 / FIR-7-C3-02)",
            flush=True,
        )
        return 2

    # --- RF-05: explicit certification scope (silence was the defect) -----
    # Kill decisions run against test_license_policy.py only; the node-id
    # floor additionally covers hardening + equivalence (FIR-7-LR-03).
    floored_names = [p.name for p in _floored_test_files()]
    floored_note = (
        f"node-id floor covers {{{', '.join(floored_names)}}}"
        if floored_names
        else "node-id floor has no floored files present"
    )
    kill_note = (
        f"kill decisions certify against {_TEST.name} only "
        f"({_TEST_HARDENING.name} / {_TEST_EQUIVALENCE.name} are "
        "floored for coverage mediation but EXCLUDED from kill decisions)"
    )
    print(
        f"SCOPE: {kill_note}; {floored_note}. "
        "Suite evidence outside the kill file is not load-bearing for "
        "mutant verdicts (RF-05 / SECD-02 / FIR-7-LR-03).",
        flush=True,
    )
    print(flush=True)

    # --- RF-01: record or mediate the collected node-id SET -----------------
    print("NODEID-BASELINE: collecting live node-ids...", flush=True)
    live_nodeids, nodeid_err = _collect_floored_nodeids()
    if nodeid_err is not None:
        print(f"HARNESS-ERROR NODEID-BASELINE: collect failed: {nodeid_err}", flush=True)
        return 2
    live_nodeid_set = frozenset(live_nodeids)
    print(
        f"NODEID-BASELINE: live collect has {len(live_nodeid_set)} node-id(s) "
        f"from {len(floored_names)} floored file(s)",
        flush=True,
    )

    if args.record_baseline:
        # FIR-7-C2-03: fixture path that EXISTS but is not a regular readable
        # file (directory, broken symlink, unreadable) is HARNESS-ERROR EXIT=2
        # — same fail-closed contract as the runtime load. Only a genuinely
        # absent path is the bootstrap case. Never write through a symlink.
        try:
            rec_is_symlink = _NODEID_BASELINE.is_symlink()
        except OSError as exc:
            print(
                f"HARNESS-ERROR NODEID-BASELINE: fixture path unreadable: "
                f"{_NODEID_BASELINE}: {exc}",
                flush=True,
            )
            return 2
        if rec_is_symlink and not _NODEID_BASELINE.exists():
            print(
                f"HARNESS-ERROR NODEID-BASELINE: fixture path exists as a "
                f"broken symlink (not a regular file): {_NODEID_BASELINE}",
                flush=True,
            )
            return 2
        if rec_is_symlink:
            print(
                f"HARNESS-ERROR NODEID-BASELINE: fixture path is a symlink "
                f"(refusing to write through it): {_NODEID_BASELINE}",
                flush=True,
            )
            return 2
        if _NODEID_BASELINE.exists() and not _NODEID_BASELINE.is_file():
            kind = "directory" if _NODEID_BASELINE.is_dir() else "not a regular file"
            print(
                f"HARNESS-ERROR NODEID-BASELINE: fixture path exists but is "
                f"{kind} (not a regular readable file): {_NODEID_BASELINE}",
                flush=True,
            )
            return 2

        # Drop accounting: compare live against prior floor. Prefer the on-disk
        # fixture; if absent, the embedded bootstrap is used for comparison
        # only (never as a runtime fallback — FIR-7-LR-02 / FIR-7-RV-06).
        if _NODEID_BASELINE.is_file():
            prev_recorded, prev_err = _load_nodeid_baseline(_NODEID_BASELINE)
            if prev_err is not None:
                print(
                    f"HARNESS-ERROR NODEID-BASELINE: cannot load prior floor "
                    f"for drop accounting: {prev_err}",
                    flush=True,
                )
                return 2
            print(
                f"NODEID-BASELINE: source={_NODEID_BASELINE} "
                f"count={len(prev_recorded)} (prior floor for drop check)",
                flush=True,
            )
        else:
            prev_recorded = frozenset(_EMBEDDED_NODEID_BASELINE)
            print(
                f"NODEID-BASELINE: on-disk fixture missing; using embedded "
                f"bootstrap for drop accounting "
                f"(count={len(prev_recorded)})",
                flush=True,
            )
        dropped = sorted(prev_recorded - live_nodeid_set)
        print(f"dropped from recorded floor: {len(dropped)} ids", flush=True)
        for did in dropped:
            print(did, flush=True)
        if dropped and not args.allow_drop:
            print(
                "HARNESS-ERROR NODEID-BASELINE: refusing to write — "
                f"{len(dropped)} id(s) would be dropped from the recorded "
                "floor. Re-add the tests, or pass --allow-drop to accept the "
                "shrink (FIR-7-RV-06). No files written.",
                flush=True,
            )
            return 2
        if dropped and args.allow_drop:
            print(
                f"ALLOW-DROP: writing baseline despite {len(dropped)} "
                "dropped id(s) (FIR-7-RV-06) — review this carefully.",
                flush=True,
            )
        try:
            _write_nodeid_baseline(_NODEID_BASELINE, live_nodeids)
        except OSError as exc:
            print(
                f"HARNESS-ERROR NODEID-BASELINE: write failed: {exc}",
                flush=True,
            )
            return 2
        print(
            f"NODEID-BASELINE: wrote {len(live_nodeids)} node-id(s) → "
            f"{_NODEID_BASELINE.name}\n"
            "Remember: regenerating after a coverage *loss* is exactly the "
            "mistake this gate exists to catch.",
            flush=True,
        )
        return 0

    recorded_nodeids, rec_err = _load_nodeid_baseline(_NODEID_BASELINE)
    if rec_err is not None:
        print(f"HARNESS-ERROR NODEID-BASELINE: {rec_err}", flush=True)
        return 2
    # Always report which source backed the floor (FIR-7-LR-02).
    print(
        f"NODEID-BASELINE: source={_NODEID_BASELINE} "
        f"count={len(recorded_nodeids)}",
        flush=True,
    )
    subset_errors = _nodeid_subset_errors(recorded_nodeids, live_nodeid_set)
    if subset_errors:
        for line in subset_errors:
            print(line, flush=True)
        print(
            f"FAIL: RF-01 node-id subset check "
            f"(recorded={len(recorded_nodeids)} live={len(live_nodeid_set)} "
            f"missing={len(recorded_nodeids - live_nodeid_set)})",
            flush=True,
        )
        return 2
    extra = len(live_nodeid_set - recorded_nodeids)
    print(
        f"NODEID-BASELINE: ok (recorded={len(recorded_nodeids)} ⊆ "
        f"live={len(live_nodeid_set)}; live extras={extra} (unprotected))",
        flush=True,
    )
    if extra > MAX_LIVE_EXTRAS_TOLERANCE:
        print(
            f"HARNESS-ERROR RF-01: live extras={extra} exceed "
            f"MAX_LIVE_EXTRAS_TOLERANCE={MAX_LIVE_EXTRAS_TOLERANCE}. "
            "New tests outside the recorded floor are unprotected; re-record "
            "the baseline in the same commit that lands the growth "
            "(FIR-7-LR-01).",
            flush=True,
        )
        return 2
    # FIR-7-C2-04: ABSOLUTE_NODEID_FLOOR must equal the recorded baseline
    # count EXACTLY (not <=). Mismatch either direction → EXIT=2 so the
    # constant cannot be silently lowered while live still passes a soft
    # floor. Update the constant in the same commit as a re-record.
    recorded_count = len(recorded_nodeids)
    if ABSOLUTE_NODEID_FLOOR != recorded_count:
        print(
            f"HARNESS-ERROR RF-01: ABSOLUTE_NODEID_FLOOR="
            f"{ABSOLUTE_NODEID_FLOOR} != recorded baseline count "
            f"{recorded_count}. Pin the constant to the recorded count in "
            "the same commit as a re-record (FIR-7-C2-04 / FIR-7-RV-05).",
            flush=True,
        )
        return 2
    # FIR-7-C3-01: the former soft-floor branch
    # ``len(live) < ABSOLUTE_NODEID_FLOOR`` is unreachable here — recorded⊆live
    # + extras≤0 (or extras allowed) + floor==len(recorded) already imply
    # live >= floor; with extras==0 they imply live==floor.
    print(
        f"NODEID-BASELINE: absolute floor ok "
        f"(ABSOLUTE_NODEID_FLOOR={ABSOLUTE_NODEID_FLOOR} == "
        f"recorded={recorded_count}; live={len(live_nodeid_set)})",
        flush=True,
    )
    print(flush=True)

    # --- Green baseline first (FIR-7-BR-17) ---------------------------------
    print("BASELINE: running unmutated suite...", flush=True)
    ok, baseline_info, baseline_executed = _run_baseline()
    if not ok:
        print(
            "ERROR: baseline suite is not green; aborting mutation guard.\n"
            "Every downstream verdict is meaningless if the unmutated suite fails.\n"
            f"{baseline_info}",
            flush=True,
        )
        return 2
    print(
        f"BASELINE: green ({baseline_info}; baseline_executed={baseline_executed})",
        flush=True,
    )
    print(flush=True)

    # --- GATE-14: pinned expected_victims must exist in the unmutated suite -
    # A renamed/deleted victim silently turns KILLED into SURVIVED. Mediate
    # every configured name against the live collect set before any mutant
    # runs (SECD-03 / TEST-15). Failures are HARNESS-ERROR, never verdicts.
    print("GATE-14: verifying pinned expected_victims exist...", flush=True)
    collected_names = _name_components_from_nodeids(live_nodeids)
    if not collected_names:
        print(
            "HARNESS-ERROR GATE-14: zero name components from live node-ids",
            flush=True,
        )
        return 2
    pin_errors = _pinned_victim_existence_errors(selected, collected_names)
    if pin_errors:
        for line in pin_errors:
            print(line, flush=True)
        print(
            f"FAIL: GATE-14 pinned-victim existence ({len(pin_errors)} missing)",
            flush=True,
        )
        return 2
    pinned_count = sum(len(m.expected_victims) for m in selected)
    print(
        f"GATE-14: ok ({pinned_count} pinned victim name(s) present in "
        f"{len(collected_names)} collected name components)",
        flush=True,
    )
    print(flush=True)

    survivors: list[str] = []
    killed: list[str] = []
    # Kill taxonomy (FIR-7-LR-09 / FIR-7-C2-01): after RV-07 strong-form
    # attribution, a certified kill requires rc==0 with victims deselected,
    # so every certified axis kill has collateral==0 by construction during
    # the attribution check (any remaining failures → ATTRIBUTION-FAIL). The
    # weak bucket (collateral dominates victim_failures) is therefore
    # structurally unreachable for certified kills and is NOT reported as
    # kill-quality evidence. Headline: killed=N (attributed=N smoke=Z).
    # Per-mutant collateral observed on the *kill run* (before deselection)
    # is still printed as a diagnostic line — labelled diagnostic, not gate.
    killed_attributed: list[str] = []
    killed_smoke: list[str] = []
    errors: list[str] = []
    unexpected: list[str] = []  # wrong expect_survived / require_kill mismatch
    known_gaps: list[str] = []

    # Pristine bytes — never leave the tree dirty (restore via scratch only;
    # original path is never written).
    original = _POLICY.read_text(encoding="utf-8")
    original_bytes = _POLICY.read_bytes()

    try:
        for mutation in selected:
            with tempfile.TemporaryDirectory(prefix=f"licpol-{mutation.name}-") as tmp:
                base = Path(tmp)
                occ = _prepare_scratch(base)
                policy_path = occ / "license_policy.py"
                try:
                    mutated = _apply_mutation(original, mutation)
                except AnchorError as exc:
                    errors.append(mutation.name)
                    print(f"HARNESS-ERROR {mutation.name}: {exc}")
                    print(
                        "  detail: non-unique or missing anchor must never be "
                        "reported as SURVIVED/KILLED"
                    )
                    continue
                except RuntimeError as exc:
                    errors.append(mutation.name)
                    print(f"HARNESS-ERROR {mutation.name}: anchor/apply failure: {exc}")
                    print(
                        "  detail: missing anchor must never be reported as SURVIVED"
                    )
                    continue
                if mutated == original:
                    errors.append(mutation.name)
                    print(
                        f"HARNESS-ERROR {mutation.name}: mutation was a no-op "
                        "(anchor miss)"
                    )
                    continue
                policy_path.write_text(mutated, encoding="utf-8")
                report = _run_suite(occ)
                verdict = classify_suite_result(
                    report, baseline_executed=baseline_executed
                )
                summary = report.summary
                failed_names = list(report.failed_names)

                # Explicit discrimination invariant message for count mismatch.
                if (
                    report.parse_error is None
                    and report.executed != baseline_executed
                    and report.executed >= 0
                ):
                    errors.append(mutation.name)
                    print(f"HARNESS-ERROR {mutation.name}: {mutation.description}")
                    print(f"  suite: {summary}")
                    print(
                        f"  reason: executed count {report.executed} != "
                        f"baseline_executed {baseline_executed} "
                        "(forgery / collection error / body no-op plugin)"
                    )
                    continue

                if verdict is Verdict.HARNESS_ERROR:
                    errors.append(mutation.name)
                    print(f"HARNESS-ERROR {mutation.name}: {mutation.description}")
                    print(f"  suite: {summary}")
                    print(
                        f"  rc={report.rc} executed={report.executed} "
                        "(not a clean test failure — refusing to count as KILLED)"
                    )
                    if report.parse_error:
                        print(f"  parse: {report.parse_error}")
                    tail = (
                        "\n".join(report.raw_out.strip().splitlines()[-5:])
                        if report.raw_out.strip()
                        else ""
                    )
                    if tail:
                        print(f"  diag: {tail}")
                    continue

                if verdict is Verdict.SURVIVED:
                    survivors.append(mutation.name)
                    print(f"SURVIVED {mutation.name}: {mutation.description}")
                    print(f"  suite: {summary}")
                    if mutation.expect_survived:
                        print("  expect: SURVIVED (control / discrimination OK)")
                    elif mutation.require_kill:
                        unexpected.append(mutation.name)
                        print("  expect: KILLED — defect mutant survived (FAIL)")
                    else:
                        known_gaps.append(mutation.name)
                        print(
                            "  expect: tracked open gap (require_kill=False); "
                            "reported honestly, not failing the gate yet"
                        )
                    continue

                # verdict is KILLED
                hits = _victims_matched(failed_names, mutation.expected_victims)
                if mutation.expect_survived:
                    errors.append(mutation.name)
                    print(
                        f"HARNESS-ERROR {mutation.name}: expected SURVIVED but "
                        "suite went red"
                    )
                    print(f"  suite: {summary}")
                    print(
                        "  reason: discrimination failure — harness cannot report a "
                        "true survivor (TEST-15)"
                    )
                    continue
                # Mutants with no named victims cannot certify a kill (BR-43 M12).
                if not mutation.expected_victims:
                    errors.append(mutation.name)
                    print(
                        f"HARNESS-ERROR {mutation.name}: suite red but no named "
                        "victims registered — refusing to count as KILLED"
                    )
                    print(f"  suite: {summary}")
                    print(f"  failed: {failed_names[:12]}")
                    continue
                if not hits:
                    errors.append(mutation.name)
                    print(f"HARNESS-ERROR {mutation.name}: {mutation.description}")
                    print(f"  suite: {summary}")
                    print(
                        "  reason: suite went red but NONE of the expected victims "
                        f"failed: {mutation.expected_victims}"
                    )
                    print(f"  failed: {failed_names[:12]}")
                    print(
                        "  a kill by an unrelated test does not prove the branch "
                        "under test is guarded"
                    )
                    continue

                # FIR-7-RV-07 strong-form victim attribution (TEST-17): for every
                # non-smoke AXIS mutant, re-run with named victims DESELECTED.
                # If the mutant still dies, the kill was collateral — refuse to
                # certify. Smoke mutants skip (kill-presence only).
                n_deselected = 0
                if not mutation.smoke_level and mutation.expected_victims:
                    deselect_ids = _resolve_victim_nodeids(
                        mutation.expected_victims, live_nodeids
                    )
                    n_deselected = len(deselect_ids)
                    if not deselect_ids:
                        errors.append(mutation.name)
                        print(
                            f"HARNESS-ERROR {mutation.name}: could not resolve "
                            "any expected_victims to live node-ids for "
                            "strong-form attribution (FIR-7-RV-07)"
                        )
                        print(f"  expected_victims: {mutation.expected_victims}")
                        continue
                    attr_report = _run_suite(occ, deselect=deselect_ids)
                    # Attribution re-run intentionally executes fewer tests —
                    # do NOT compare against baseline_executed.
                    if attr_report.parse_error:
                        errors.append(mutation.name)
                        print(
                            f"HARNESS-ERROR {mutation.name}: attribution re-run "
                            f"parse failure: {attr_report.parse_error}"
                        )
                        continue
                    if attr_report.rc == 1 and attr_report.failed_names:
                        errors.append(mutation.name)
                        print(
                            f"ATTRIBUTION-FAIL {mutation.name}: dies without "
                            "its victims (collateral kill)"
                        )
                        print(f"  suite: {attr_report.summary}")
                        print(
                            f"  deselected={n_deselected} "
                            f"remaining_failures="
                            f"{list(attr_report.failed_names)[:12]}"
                        )
                        print(
                            "  expected_victims must include every test that "
                            "actually carries the kill (FIR-7-RV-07 / TEST-17)"
                        )
                        continue
                    if attr_report.rc != 0:
                        errors.append(mutation.name)
                        print(
                            f"HARNESS-ERROR {mutation.name}: attribution re-run "
                            f"unexpected rc={attr_report.rc} "
                            f"executed={attr_report.executed}"
                        )
                        if attr_report.raw_out.strip():
                            tail = "\n".join(
                                attr_report.raw_out.strip().splitlines()[-5:]
                            )
                            print(f"  diag: {tail}")
                        continue
                    # rc==0: mutant SURVIVES when victims are gone — attribution OK.

                # Certified kill (victims hit; strong-form attribution held).
                n_failed = len(failed_names)
                n_victim_fail = _count_failed_matching_victims(
                    failed_names, mutation.expected_victims
                )
                # Collateral observed on the kill run BEFORE deselection —
                # diagnostic only (FIR-7-C2-01). Post-RV-07, certified axis
                # kills cannot have residual collateral under attribution
                # (rc==0 with victims gone); the weak bucket is unreachable.
                collateral_on_kill_run = _collateral_count(
                    failed_names, mutation.expected_victims
                )
                if mutation.smoke_level:
                    killed_smoke.append(mutation.name)
                    tax = "smoke"
                else:
                    killed_attributed.append(mutation.name)
                    killed.append(mutation.name)
                    tax = "attributed"
                print(f"KILLED   {mutation.name}: {mutation.description}")
                print(f"  suite: {summary}")
                print(f"  victims: {', '.join(hits)}")
                role = "smoke" if mutation.smoke_level else "axis"
                print(
                    f"  discrimination: role={role} tax={tax} failed={n_failed} "
                    f"victim_failures={n_victim_fail}"
                )
                print(
                    f"  diagnostic: collateral_on_kill_run="
                    f"{collateral_on_kill_run} (failures not matching "
                    "expected_victims during the kill run, BEFORE "
                    "deselection; not gate evidence — FIR-7-C2-01 / "
                    "FIR-7-LR-09)"
                )
                if mutation.smoke_level:
                    print(
                        "  note: smoke-level mutant — kill-presence only; "
                        "not counted as axis evidence / headline killed "
                        "(RF-03 / FIR-7-RV-04)"
                    )
                else:
                    print(
                        "  attribution: OK (survives when "
                        f"{n_deselected} victim node-id(s) deselected; "
                        "FIR-7-RV-07)"
                    )
    finally:
        # Byte-identical restore guarantee for the real tree (scratch-only writes).
        if _POLICY.read_bytes() != original_bytes:
            _POLICY.write_bytes(original_bytes)

    print()
    # Headline killed = attributed axis kills only. Smoke kill-presence
    # probes are reported separately so they are not axis evidence
    # (FIR-7-RV-04 / FIR-7-LR-09 / FIR-7-C2-01). The weak bucket is omitted:
    # post-RV-07 strong-form attribution makes is_weak unreachable for any
    # certified kill (collateral residual → ATTRIBUTION-FAIL, not KILLED).
    print(
        f"killed={len(killed)} (attributed={len(killed_attributed)} "
        f"smoke={len(killed_smoke)}) survivors={len(survivors)} "
        f"errors={len(errors)} total={len(selected)}"
    )
    if survivors:
        print("survivors: " + ", ".join(survivors))
    if errors:
        print("errors: " + ", ".join(errors))
    if known_gaps:
        print("known_gaps: " + ", ".join(known_gaps))

    # Exit policy:
    # 1. Any HARNESS-ERROR → non-zero (never certify on broken harness / anchor).
    # 2. CONTROL (expect_survived) not SURVIVED → already in errors.
    # 3. require_kill mutants that SURVIVED → non-zero.
    # 4. Tracked open gaps (require_kill=False) may SURVIVE.
    if errors:
        print(
            "FAIL: guard errors (import/collection/anchor/victim/discrimination/"
            "executed-count)"
        )
        return 2
    if unexpected:
        print("FAIL: required-kill mutants survived: " + ", ".join(unexpected))
        return 1

    control_selected = any(m.name == "CONTROL" for m in selected)
    if control_selected and "CONTROL" not in survivors:
        print("FAIL: CONTROL did not SURVIVE — harness not discriminating (TEST-15)")
        return 1

    if known_gaps or (
        survivors
        and any(
            m.name in survivors and not m.expect_survived and not m.require_kill
            for m in selected
        )
    ):
        open_gaps = sorted(
            set(known_gaps)
            | {
                m.name
                for m in selected
                if m.name in survivors
                and not m.expect_survived
                and not m.require_kill
            }
        )
        print(
            "OK: required mutants killed; control survived; "
            f"open-gap survivors (not gated yet): {', '.join(open_gaps)}"
        )
        return 0

    print("OK: all required mutants killed; control survived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
