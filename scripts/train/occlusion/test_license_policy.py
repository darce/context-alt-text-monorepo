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
    # Always reload from disk so mutation_guard scratch copies stay honest.
    if mod_name in sys.modules:
        del sys.modules[mod_name]

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
        # RED-capable: must hit the exact pinned pattern, not any id fallback.
        matched = policy.match_nc_model_pattern("insightface/buffalo_l")
        assert matched == "insightface/*"

    def test_buffalo_star_pattern_drives_audit(self) -> None:
        # Must exercise audit logic, not merely assert a constant property.
        result = policy.audit_derived_from_model("buffalo_sc")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        matched = policy.match_nc_model_pattern("buffalo_sc")
        assert matched == "buffalo*"

    @pytest.mark.parametrize(
        "tag",
        [
            "deepinsight/insightface",
            "deepinsight/insightface/buffalo_l",
            "models/insightface/buffalo_l",
            "hf/insightface/buffalo_l",
            "insightface_buffalo_l",
            "insightface-buffalo-l",
            "insightface／buffalo_l",  # U+FF0F fullwidth solidus
        ],
    )
    def test_nested_and_separator_insightface_forms_fail(self, tag: str) -> None:
        result = policy.audit_derived_from_model(tag)
        assert result.ok is False, f"expected NC fail for {tag!r}, got {result}"
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_provenance_row_nested_insightface_fails(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "deepinsight/insightface/buffalo_l",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize(
        "tag",
        ["notdcface/x", "dcface/gen1", "mediapipe/blazeface"],
    )
    def test_non_nc_derived_tags_still_pass(self, tag: str) -> None:
        result = policy.audit_derived_from_model(tag)
        assert result.ok is True, f"over-blocked {tag!r}: {result.detail}"

    @pytest.mark.parametrize(
        "tag",
        ["retinaface/r50", "arcface/r100", "buffalo_sc"],
    )
    def test_nc_model_ids_layer_rejects_pinned_ids(self, tag: str) -> None:
        # Exercises NC_MODEL_IDS second matching layer (M3 discrimination).
        result = policy.audit_derived_from_model(tag)
        assert result.ok is False, f"expected NC fail for {tag!r}"
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_vec2face_forbidden_table_entry_drives_nc_ids(self) -> None:
        # A9: NC_MODEL_IDS derived from tables — vec2face is FORBIDDEN.
        assert "vec2face" in policy.NC_MODEL_IDS
        result = policy.audit_derived_from_model("vec2face/g1")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_new_nc_table_entry_changes_audit_outcome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Insert a fresh NC synthetic entry and re-derive the id set.
        entry = policy.SyntheticSourceEntry(
            source_id="brand_new_nc_synth",
            verification=policy.VerificationMetadata(
                spdx_id="PENDING-LEGAL-CLEARANCE",
                commercial_use=policy.CommercialUse.FORBIDDEN,
            ),
        )
        new_synth = dict(policy.SYNTHETIC_SOURCE_ENTRIES)
        new_synth["brand_new_nc_synth"] = entry
        monkeypatch.setattr(policy, "SYNTHETIC_SOURCE_ENTRIES", new_synth)
        # Recompute NC_MODEL_IDS the same way production does.
        derived = policy._derive_nc_model_ids()
        monkeypatch.setattr(policy, "NC_MODEL_IDS", derived)
        assert "brand_new_nc_synth" in policy.NC_MODEL_IDS
        result = policy.audit_derived_from_model("brand_new_nc_synth/v1")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

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
        [
            # Underscore / nested forms (A2) — the common on-disk names.
            "casia_webface",
            "CASIA_WebFace",
            "vggface2_train",
            "ms1m_v3",
            "glint360k_r100",
            "widerface_val",
            "ffhq_aligned",
            "celeba_hq",
            "dataset/ffhq",
            # Canonical bare tokens still fail.
            "ffhq",
            "casia-webface",
            "widerface",
            "mfr",
            "rmfrd",
            "webface260m",
            "vggface2",
        ],
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

    def test_spdx_case_insensitive_allow(self) -> None:
        result = policy.audit_spdx("apache-2.0")
        assert result.ok is True

    def test_spdx_case_insensitive_denylist(self) -> None:
        result = policy.audit_spdx("agpl-3.0")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE

    def test_operator_cleared_is_not_spdx_pass(self) -> None:
        result = policy.audit_spdx("operator-cleared")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX

    def test_operator_cleared_row_fails(self) -> None:
        row = {
            "source": "scraped_from_the_web",
            "license": "operator-cleared",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX

    def test_unknown_spdx_default_deny(self) -> None:
        # M1 discrimination: UNKNOWN_SPDX must FAIL (not silent pass).
        result = policy.audit_spdx("Totally-Made-Up-1.0")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX


# ---------------------------------------------------------------------------
# (4) named ingest entries for Detector A/B + cascade; Ultralytics AGPL denied
# ---------------------------------------------------------------------------


class TestNamedIngestEntriesAndUltralyticsDeny:
    """Behaviour 4: Detector A/B + cascade person-detectors registered; AGPL banned."""

    def test_required_display_names_registered(self) -> None:
        # Hard-code contract names in the TEST (M5) — do not drive the loop from
        # the production tuple (that let REQUIRED_MODEL_INGEST_DISPLAY_NAMES=()
        # run zero assertions). Still pin the production tuple so emptying it
        # is caught by mutation_guard.
        required = (
            "MediaPipe BlazeFace",
            "Paddle BlazeFace-FPN-SSH",
            "RT-DETR",
            "D-FINE",
            "PP-PicoDet",
        )
        registered_names = {
            entry.display_name for entry in policy.MODEL_INGEST_ENTRIES.values()
        }
        for name in required:
            assert name in registered_names, f"missing named ingest entry for {name!r}"
        assert tuple(policy.REQUIRED_MODEL_INGEST_DISPLAY_NAMES) == required

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
        assert entry.role is policy.DetectorRole.PERSON_DETECTOR
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

    def test_nc_tagged_ingest_entry_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # BR-14: NC-tagged ingest entry FAILS ingest.
        nc_entry = policy.ModelIngestEntry(
            model_id="nc_face_toy",
            display_name="NC Face Toy",
            role=policy.DetectorRole.FACE_DETECTOR,
            verification=policy.VerificationMetadata(
                spdx_id="Apache-2.0",
                commercial_use=policy.CommercialUse.NON_COMMERCIAL,
            ),
        )
        new_entries = dict(policy.MODEL_INGEST_ENTRIES)
        new_entries["nc_face_toy"] = nc_entry
        monkeypatch.setattr(policy, "MODEL_INGEST_ENTRIES", new_entries)
        result = policy.audit_model_ingest("nc_face_toy")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_denylisted_spdx_ingest_entry_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # BR-14: ingest entry with denylisted SPDX id fails.
        bad = policy.ModelIngestEntry(
            model_id="agpl_face_toy",
            display_name="AGPL Face Toy",
            role=policy.DetectorRole.FACE_DETECTOR,
            verification=policy.VerificationMetadata(
                spdx_id="AGPL-3.0",
                commercial_use=policy.CommercialUse.ALLOWED,
            ),
        )
        new_entries = dict(policy.MODEL_INGEST_ENTRIES)
        new_entries["agpl_face_toy"] = bad
        monkeypatch.setattr(policy, "MODEL_INGEST_ENTRIES", new_entries)
        result = policy.audit_model_ingest("agpl_face_toy")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE


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

    def test_missing_source_fails(self) -> None:
        asset = {
            "asset_id": "x",
            "license": "CC0-1.0",
            "clearance": "allowed",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SOURCE

    def test_unknown_source_fails(self) -> None:
        asset = {
            "asset_id": "x",
            "license": "CC0-1.0",
            "clearance": "cleared",
            "source": "random_flickr",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SOURCE

    def test_operator_cleared_license_not_accepted_on_occluder(self) -> None:
        asset = {
            "license": "operator-cleared",
            "clearance": "cleared",
            "source": "random_flickr",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is False
        assert result.reason in {
            policy.RejectionReason.UNKNOWN_SPDX,
            policy.RejectionReason.UNKNOWN_SOURCE,
        }


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

    def _dcface_row(
        self,
        *,
        derived_from_model: str,
        source: str = "dcface",
        clearance: str | None = None,
        generator_lineage: str = "ffhq",
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "source": source,
            "license": "Apache-2.0",
            "derived_from_model": derived_from_model,
            # Bare research token the matcher CAN hit (BR-12) — must not reject.
            "generator_lineage": generator_lineage,
        }
        if clearance is None:
            row["clearance"] = policy.DCFACE_CLEARANCE_DECISION
        elif clearance != "__omit__":
            row["clearance"] = clearance
        return row

    def test_dcface_clearance_decision_constant(self) -> None:
        assert policy.DCFACE_CLEARANCE_DECISION == "dcface_operator_clearance_20260723"
        entry = policy.SYNTHETIC_SOURCE_ENTRIES["dcface"]
        assert entry.verification.clearance_decision == policy.DCFACE_CLEARANCE_DECISION
        assert entry.verification.commercial_use is policy.CommercialUse.ALLOWED

    def test_dcface_derived_row_passes_with_ffhq_lineage(self) -> None:
        row = self._dcface_row(derived_from_model="dcface/oversample_xid_0.5m")
        result = policy.audit_provenance_row(row)
        assert result.ok is True, result.detail
        assert result.verdict is policy.LicenseVerdict.PASS

    def test_same_dcface_row_with_buffalo_derived_fails(self) -> None:
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
        # source is clean; lineage is a bare research token → still PASS.
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "generator_lineage": "ffhq",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is True, result.detail

    def test_same_row_with_source_ffhq_fails_research_only(self) -> None:
        # Paired negative (BR-12): lineage exemption is narrow, not blanket.
        row = self._dcface_row(
            derived_from_model="dcface/oversample_xid_0.5m",
            source="ffhq",
        )
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE

    def test_dcface_wrong_clearance_fails(self) -> None:
        row = self._dcface_row(
            derived_from_model="dcface/x",
            clearance="totally_made_up_9999",
        )
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_dcface_missing_clearance_fails(self) -> None:
        row = self._dcface_row(
            derived_from_model="dcface/x",
            clearance="__omit__",
        )
        assert "clearance" not in row
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_vec2face_still_pending(self) -> None:
        result = policy.audit_synthetic_source("vec2face")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE


# ---------------------------------------------------------------------------
# Synthetic fail-closed + structural validation + category caller-owned
# ---------------------------------------------------------------------------


class TestSyntheticFailClosedAndRowValidation:
    def test_unknown_synthetic_source_pending(self) -> None:
        row = {
            "source": "synthface3",
            "license": "Apache-2.0",
            "derived_from_model": "synthface3/g1",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_explicit_synthetic_category_unknown_source_pending(self) -> None:
        row = {
            "category": "synthetic_source",
            "source": "vec2face-successor",
            "license": "Apache-2.0",
            "derived_from_model": "vec2face-successor/v1",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_row_cannot_waive_source_via_tooling_category(self) -> None:
        row = {
            "license": "Apache-2.0",
            "derived_from_model": "",
            "category": "tooling",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SOURCE

    def test_row_cannot_waive_source_via_bogus_category(self) -> None:
        row = {
            "license": "Apache-2.0",
            "derived_from_model": "",
            "category": "bogus",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason in {
            policy.RejectionReason.INVALID_ROW,
            policy.RejectionReason.UNKNOWN_SOURCE,
        }

    def test_missing_derived_from_model_key_fails(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

    def test_list_derived_from_model_fails(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": ["insightface/buffalo_l"],
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

    def test_none_derived_from_model_fails(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": None,
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

    def test_caller_tooling_category_allows_missing_source_only_via_entry_point(
        self,
    ) -> None:
        # audit_tooling_row is the caller-owned entry point; still needs license.
        row = {
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        # Tooling provenance row without source: not research-tainted, no source req
        # under TOOLING category — but tooling deps go through audit_tooling_dependency.
        # Training path always requires source; tooling category skips source req.
        result = policy.audit_tooling_row(row)
        # license ok, no source required for TOOLING category
        assert result.ok is True, result.detail


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

    def test_detector_role_strenum(self) -> None:
        assert issubclass(policy.DetectorRole, policy.StrEnum)
        entry = policy.get_model_ingest_entry("yunet")
        assert entry.role is policy.DetectorRole.FACE_DETECTOR

    def test_clearance_status_includes_folded_literals(self) -> None:
        assert policy.ClearanceStatus.CLEARED == "cleared"
        assert policy.ClearanceStatus.LICENSE_CLEARED == "license_cleared"
        assert "cleared" in policy.OCCLUDER_ALLOWED_CLEARANCES
        assert "denied" == policy.ClearanceStatus.DENIED.value
        assert (
            "pending_legal_clearance"
            == policy.ClearanceStatus.PENDING_LEGAL_CLEARANCE.value
        )

    def test_require_pass_raises_on_fail(self) -> None:
        result = policy.audit_derived_from_model("insightface/buffalo_l")
        with pytest.raises(policy.LicensePolicyError) as exc_info:
            policy.require_pass(result)
        assert exc_info.value.result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_require_pass_returns_on_pass(self) -> None:
        result = policy.audit_spdx("Apache-2.0")
        assert policy.require_pass(result) is result
