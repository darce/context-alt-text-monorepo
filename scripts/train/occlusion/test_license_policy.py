"""RED-capable fixtures for scripts/train/occlusion/license_policy.py (FIR-7 Slice 0a).

Each of the seven required behaviours has its own test. FAIL cases assert the
specific ``RejectionReason`` (TEST-15) — a denylist test that would still pass
with an empty denylist is worthless.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_MODULE_PATH = Path(__file__).resolve().parent / "license_policy.py"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_policy():
    # Prefer package import when scripts/ is on sys.path; fall back to file load.
    scripts_root = str(_REPO_ROOT / "scripts")
    if scripts_root not in sys.path:
        sys.path.insert(0, scripts_root)
    # Ensure parent packages exist for a clean import path under train.occlusion.
    train_root = _REPO_ROOT / "scripts" / "train"
    if str(train_root.parent) not in sys.path:
        sys.path.insert(0, str(train_root.parent))

    mod_name = "train.occlusion.license_policy"
    if mod_name in sys.modules:
        return sys.modules[mod_name]

    # Guarantee package parents for relative-looking imports.
    for pkg_name, pkg_path in (
        ("train", train_root / "__init__.py"),
        ("train.occlusion", train_root / "occlusion" / "__init__.py"),
    ):
        if pkg_name not in sys.modules:
            pkg_spec = importlib.util.spec_from_file_location(
                pkg_name,
                pkg_path,
                submodule_search_locations=[str(pkg_path.parent)],
            )
            assert pkg_spec is not None and pkg_spec.loader is not None
            pkg_mod = importlib.util.module_from_spec(pkg_spec)
            sys.modules[pkg_name] = pkg_mod
            pkg_spec.loader.exec_module(pkg_mod)

    spec = importlib.util.spec_from_file_location(mod_name, _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod  # required before exec for @dataclass
    spec.loader.exec_module(mod)
    return mod


policy = _load_policy()


# ---------------------------------------------------------------------------
# (1) buffalo weights AND output-derived data FAIL (NC pattern list)
# ---------------------------------------------------------------------------


class TestBuffaloAndNcModelDerivedFail:
    """Behaviour 1: buffalo weights / NC-derived outputs fail the audit."""

    def test_buffalo_l_derived_from_model_fails_with_nc_model_derived(self) -> None:
        result = policy.audit_derived_from_model("insightface/buffalo_l")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert "buffalo" in result.detail.lower() or "insightface" in result.detail.lower()

    def test_bare_buffalo_weights_tag_fails(self) -> None:
        result = policy.audit_derived_from_model("buffalo_l")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_insightface_prefix_pattern_is_pinned(self) -> None:
        # RED-capable: empty NC_MODEL_PATTERNS would not match; assert pattern hit.
        matched = policy.match_nc_model_pattern("insightface/buffalo_l")
        assert matched is not None
        assert matched in policy.NC_MODEL_PATTERNS or matched in {
            p.lower() for p in policy.NC_MODEL_IDS
        }

    def test_buffalo_star_pattern_is_pinned(self) -> None:
        matched = policy.match_nc_model_pattern("buffalo_sc")
        assert matched is not None
        assert any(p.startswith("buffalo") for p in policy.NC_MODEL_PATTERNS)

    def test_provenance_row_with_buffalo_output_fails(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "insightface/buffalo_l",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED


# ---------------------------------------------------------------------------
# (2) research-only sources FAIL
# ---------------------------------------------------------------------------


class TestResearchOnlySourcesFail:
    """Behaviour 2: research-only corpora fail when used as ``source``."""

    @pytest.mark.parametrize(
        "source",
        ["widerface", "mfr", "rmfrd", "casia", "ffhq", "webface260m", "vggface2"],
    )
    def test_research_source_fails_with_research_only_reason(self, source: str) -> None:
        result = policy.audit_source(source)
        assert result.ok is False, f"expected FAIL for research source {source!r}"
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE

    def test_research_only_license_tag_fails(self) -> None:
        result = policy.audit_spdx("research-only")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_LICENSE

    def test_provenance_row_research_source_fails(self) -> None:
        row = {
            "source": "widerface",
            "license": "research-only",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason in {
            policy.RejectionReason.RESEARCH_ONLY_SOURCE,
            policy.RejectionReason.RESEARCH_ONLY_LICENSE,
        }


# ---------------------------------------------------------------------------
# (3) Apache-2.0 self-generated PASSES
# ---------------------------------------------------------------------------


class TestApacheSelfGeneratedPasses:
    """Behaviour 3: Apache-2.0 self-generated training rows pass."""

    def test_apache_self_generated_row_passes(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is True
        assert result.verdict is policy.LicenseVerdict.PASS
        assert result.reason is None

    def test_self_generated_spdx_allowlisted(self) -> None:
        result = policy.audit_spdx("self-generated")
        assert result.ok is True

    def test_apache_spdx_allowlisted(self) -> None:
        result = policy.audit_spdx("Apache-2.0")
        assert result.ok is True
        assert "Apache-2.0" in policy.ALLOWED_SPDX_IDS


# ---------------------------------------------------------------------------
# (4) named ingest entries for Detector A/B + cascade; Ultralytics AGPL denied
# ---------------------------------------------------------------------------


class TestNamedIngestEntriesAndUltralyticsDeny:
    """Behaviour 4: Detector A/B + cascade person-detectors registered; AGPL banned."""

    def test_required_display_names_registered(self) -> None:
        registered_names = {
            entry.display_name for entry in policy.MODEL_INGEST_ENTRIES.values()
        }
        for name in policy.REQUIRED_MODEL_INGEST_DISPLAY_NAMES:
            assert name in registered_names, f"missing named ingest entry for {name!r}"

    def test_mediapipe_blazeface_ingest_passes(self) -> None:
        result = policy.audit_model_ingest("mediapipe_blazeface")
        assert result.ok is True
        entry = policy.get_model_ingest_entry("mediapipe_blazeface")
        assert entry.display_name == "MediaPipe BlazeFace"
        assert entry.verification.spdx_id == "Apache-2.0"

    def test_paddle_blazeface_fpn_ssh_ingest_passes(self) -> None:
        result = policy.audit_model_ingest("paddle_blazeface_fpn_ssh")
        assert result.ok is True
        entry = policy.get_model_ingest_entry("paddle_blazeface_fpn_ssh")
        assert entry.display_name == "Paddle BlazeFace-FPN-SSH"

    @pytest.mark.parametrize(
        ("model_id", "display_name"),
        [
            ("rt_detr", "RT-DETR"),
            ("d_fine", "D-FINE"),
            ("pp_picodet", "PP-PicoDet"),
        ],
    )
    def test_cascade_person_detector_ingest_passes(
        self, model_id: str, display_name: str
    ) -> None:
        result = policy.audit_model_ingest(model_id)
        assert result.ok is True, result.detail
        entry = policy.get_model_ingest_entry(model_id)
        assert entry.display_name == display_name
        assert entry.role == "person_detector"
        assert entry.verification.commercial_use is policy.CommercialUse.ALLOWED

    def test_ultralytics_agpl_is_denylisted(self) -> None:
        assert "ultralytics" in policy.PACKAGE_DENYLIST
        deny = policy.PACKAGE_DENYLIST["ultralytics"]
        assert deny.spdx_id.startswith("AGPL")
        result = policy.audit_model_ingest("ultralytics")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert "AGPL" in result.detail

    def test_yolov8_agpl_family_denied(self) -> None:
        result = policy.audit_model_ingest("yolov8")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_unknown_model_missing_ingest_entry_fails(self) -> None:
        result = policy.audit_model_ingest("totally_unknown_detector_xyz")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.MISSING_INGEST_ENTRY


# ---------------------------------------------------------------------------
# (5) occluder-asset license fields gated at pack-build
# ---------------------------------------------------------------------------


class TestOccluderAssetPackBuildGate:
    """Behaviour 5: uncleared occluder source photos FAIL pack-build."""

    def test_uncleared_source_photo_fails(self) -> None:
        asset = {
            "asset_id": "mask-atlas-01",
            "license": "CC0-1.0",
            "source": "operator-phone",
            "clearance": "uncleared",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNCLEARED_OCCLUDER_ASSET

    def test_missing_clearance_fails(self) -> None:
        asset = {
            "asset_id": "sam-source-photo-09",
            "license": "CC-BY-4.0",
            "source": "operator-photo",
            # no clearance field
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNCLEARED_OCCLUDER_ASSET

    def test_missing_license_field_fails(self) -> None:
        asset = {
            "asset_id": "sunglasses-01",
            "clearance": "allowed",
            "source": "self-generated",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.MISSING_LICENSE_FIELD

    def test_cleared_occluder_asset_passes(self) -> None:
        asset = {
            "asset_id": "mask-atlas-train-01",
            "license": "CC0-1.0",
            "source": "self-generated",
            "clearance": "allowed",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is True
        assert result.verdict is policy.LicenseVerdict.PASS


# ---------------------------------------------------------------------------
# (6) umap-learn (BSD-3-Clause) on TOOLING allowlist
# ---------------------------------------------------------------------------


class TestUmapLearnToolingAllowlist:
    """Behaviour 6: umap-learn is TOOLING-allowlisted (not training data)."""

    def test_umap_learn_on_tooling_allowlist(self) -> None:
        assert "umap-learn" in policy.TOOLING_ALLOWLIST
        entry = policy.TOOLING_ALLOWLIST["umap-learn"]
        assert entry.verification.spdx_id == "BSD-3-Clause"
        assert entry.category is policy.PolicyCategory.TOOLING

    def test_umap_learn_audit_passes(self) -> None:
        result = policy.audit_tooling_dependency("umap-learn")
        assert result.ok is True
        assert result.category is policy.PolicyCategory.TOOLING
        assert "BSD-3-Clause" in result.detail

    def test_is_tooling_allowlisted_helper(self) -> None:
        assert policy.is_tooling_allowlisted("umap-learn") is True
        assert policy.is_tooling_allowlisted("not-a-real-tooling-package") is False


# ---------------------------------------------------------------------------
# (7) DCFace operator-cleared; paired buffalo FAIL; generator_lineage exempt
# ---------------------------------------------------------------------------


class TestDcfaceOperatorClearanceAndLineageExempt:
    """Behaviour 7: DCFace clearance + lineage exemption + paired buffalo fail."""

    def _dcface_row(self, *, derived_from_model: str) -> dict[str, Any]:
        return {
            "source": "dcface",
            "license": "operator-cleared",
            "derived_from_model": derived_from_model,
            "clearance": policy.DCFACE_CLEARANCE_DECISION,
            # Informational only — must NOT trigger research-source rejection.
            "generator_lineage": "trained-on:FFHQ+CASIA (disclosed; not a training source)",
        }

    def test_dcface_clearance_decision_constant(self) -> None:
        assert policy.DCFACE_CLEARANCE_DECISION == "dcface_operator_clearance_20260723"
        entry = policy.SYNTHETIC_SOURCE_ENTRIES["dcface"]
        assert entry.verification.clearance_decision == policy.DCFACE_CLEARANCE_DECISION
        assert entry.verification.commercial_use is policy.CommercialUse.ALLOWED

    def test_dcface_derived_row_passes_with_ffhq_casia_lineage(self) -> None:
        row = self._dcface_row(derived_from_model="dcface/oversample_xid_0.5m")
        result = policy.audit_provenance_row(row)
        assert result.ok is True, result.detail
        assert result.verdict is policy.LicenseVerdict.PASS
        # Lineage present but ignored for rejection.
        assert "FFHQ" in row["generator_lineage"]
        assert "CASIA" in row["generator_lineage"]

    def test_same_dcface_row_with_buffalo_derived_fails(self) -> None:
        # Paired fixture from the plan: same row, swap only derived_from_model.
        row = self._dcface_row(derived_from_model="insightface/buffalo_l")
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_dcface_not_on_nc_pattern_list(self) -> None:
        assert policy.match_nc_model_pattern("dcface/oversample_xid_0.5m") is None
        assert not any(
            p.lower().startswith("dcface") for p in policy.NC_MODEL_PATTERNS
        )

    def test_generator_lineage_does_not_trigger_research_rejection(self) -> None:
        # source is clean; lineage names research corpora → still PASS.
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "generator_lineage": "upstream research refs: ffhq, casia (informational)",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is True, result.detail

    def test_vec2face_still_pending(self) -> None:
        result = policy.audit_synthetic_source("vec2face")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE


# ---------------------------------------------------------------------------
# Cross-cutting: enums + require_pass (sr-006 / sr-007)
# ---------------------------------------------------------------------------


class TestPolicyEnumsAndHardFail:
    def test_verdicts_are_strenum(self) -> None:
        assert issubclass(policy.LicenseVerdict, policy.StrEnum)
        assert policy.LicenseVerdict.PASS == "pass"
        assert policy.LicenseVerdict.FAIL == "fail"

    def test_rejection_reasons_are_strenum(self) -> None:
        assert issubclass(policy.RejectionReason, policy.StrEnum)
        assert policy.RejectionReason.NC_MODEL_DERIVED == "nc_model_derived"

    def test_require_pass_raises_on_fail(self) -> None:
        result = policy.audit_derived_from_model("insightface/buffalo_l")
        with pytest.raises(policy.LicensePolicyError) as exc_info:
            policy.require_pass(result)
        assert exc_info.value.result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_require_pass_returns_on_pass(self) -> None:
        result = policy.audit_spdx("Apache-2.0")
        assert policy.require_pass(result) is result
