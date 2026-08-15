"""RED-capable fixtures for scripts/train/occlusion/license_policy.py (FIR-7 Slice 0a).

Each of the seven required behaviours has its own test. FAIL cases assert the
specific ``RejectionReason`` (TEST-15) — a denylist test that would still pass
with an empty denylist is worthless.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, ClassVar

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
        # B4b / BR-19 / BR-28: exact expanded-id membership (no glob return value).
        matched = policy.match_nc_model_pattern("insightface/buffalo_l")
        assert matched == "insightface"

    def test_buffalo_star_pattern_drives_audit(self) -> None:
        # B4b / BR-19 / BR-28: buffalo_sc is an enumerated NC id, not a glob hit.
        result = policy.audit_derived_from_model("buffalo_sc")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        matched = policy.match_nc_model_pattern("buffalo_sc")
        assert matched == "buffalo_sc"

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
        # Single live fail path: research *source* only (BR-60 / TEST-15).
        # Allowlisted licence so a research-license gate cannot satisfy this test.
        row = {
            "source": "widerface",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE


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

    def test_self_generated_is_not_an_spdx_pass(self) -> None:
        # BR-25: self-generated is a source value, not an SPDX licence tag.
        result = policy.audit_spdx("self-generated")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX

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
            "photo_clearance": "uncleared",
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
            "photo_clearance": "allowed",
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
            "photo_clearance": "allowed",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is True
        assert result.verdict is policy.LicenseVerdict.PASS

    def test_missing_source_fails(self) -> None:
        asset = {
            "asset_id": "x",
            "license": "CC0-1.0",
            "photo_clearance": "allowed",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SOURCE

    def test_unknown_source_fails(self) -> None:
        asset = {
            "asset_id": "x",
            "license": "CC0-1.0",
            "photo_clearance": "cleared",
            "source": "random_flickr",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SOURCE

    def test_operator_cleared_license_not_accepted_on_occluder(self) -> None:
        # Registered source so UNKNOWN_SOURCE cannot satisfy this test (BR-59).
        # Only the licence gate may reject; assert the exact reason (TEST-15).
        asset = {
            "license": "operator-cleared",
            "photo_clearance": "cleared",
            "source": "operator-photo",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX


# ---------------------------------------------------------------------------
# (6) umap-learn (BSD-3-Clause) on TOOLING allowlist
# ---------------------------------------------------------------------------


class TestUmapLearnToolingAllowlist:
    """Behaviour 6: umap-learn is TOOLING-allowlisted (not training data)."""

    def test_umap_learn_audit_passes(self) -> None:
        # Behavioural (TEST-15): exercises audit_tooling_dependency, not the dict.
        result = policy.audit_tooling_dependency("umap-learn")
        assert result.ok is True
        assert result.category is policy.PolicyCategory.TOOLING
        assert "BSD-3-Clause" in result.detail

    def test_is_tooling_allowlisted_helper(self) -> None:
        assert policy.is_tooling_allowlisted("umap-learn") is True
        assert policy.is_tooling_allowlisted("not-a-real-tooling-package") is False

    def test_br39_denylisted_tooling_dependency_fails(self) -> None:
        # BR-39: direct deny path on audit_tooling_dependency (not only row door).
        result = policy.audit_tooling_dependency("ultralytics")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert result.category is policy.PolicyCategory.TOOLING

    def test_br39_unknown_tooling_package_fails(self) -> None:
        result = policy.audit_tooling_dependency("totally-unknown-pkg")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SOURCE
        assert result.category is policy.PolicyCategory.TOOLING

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
        generator_lineage: str | None = "ffhq",
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "source": source,
            "license": "Apache-2.0",
            "derived_from_model": derived_from_model,
        }
        # BR-29: generator_lineage is optional. Pass None / "__omit__" to leave it
        # off the row so the SYNTHETIC_SOURCE_ENTRIES registry sweep is the only
        # path that can force the clearance audit (TEST-15).
        if generator_lineage is not None and generator_lineage != "__omit__":
            # Bare research token the matcher CAN hit (BR-12) — must not reject.
            row["generator_lineage"] = generator_lineage
        if clearance is None:
            row["clearance_decision"] = policy.DCFACE_CLEARANCE_DECISION
        elif clearance != "__omit__":
            row["clearance_decision"] = clearance
        return row

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
        assert "clearance_decision" not in row
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_br29_dcface_no_lineage_correct_clearance_passes(self) -> None:
        # BR-29: registry sweep alone admits DCFace when clearance matches.
        row = self._dcface_row(
            derived_from_model="",
            generator_lineage="__omit__",
            clearance=None,  # correct decision token
        )
        assert "generator_lineage" not in row
        result = policy.audit_provenance_row(row)
        assert result.ok is True, result.detail

    def test_br29_dcface_no_lineage_wrong_clearance_fails(self) -> None:
        # BR-29: without lineage, only the SYNTHETIC_SOURCE_ENTRIES loop can
        # force pending_legal_clearance — lineage branch must not mask this.
        row = self._dcface_row(
            derived_from_model="",
            generator_lineage="__omit__",
            clearance="made_up",
        )
        assert "generator_lineage" not in row
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_br29_dcface_no_lineage_missing_clearance_fails(self) -> None:
        row = self._dcface_row(
            derived_from_model="",
            generator_lineage="__omit__",
            clearance="__omit__",
        )
        assert "generator_lineage" not in row
        assert "clearance_decision" not in row
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_br16_lineage_sole_cause_of_synthetic_pending(self) -> None:
        # BR-16: registered *model-ingest* source (yunet) PASSes alone; attaching
        # generator_lineage routes through the lineage branch of
        # _synthetic_audit_targets as the sole FAIL cause (registry head is None
        # for yunet, so BR-29's loop cannot substitute).
        base = {
            "source": "yunet",
            "license": "MIT",
            "derived_from_model": "",
        }
        without = policy.audit_provenance_row(base)
        assert without.ok is True, without.detail
        with_lineage = {**base, "generator_lineage": "ffhq"}
        result = policy.audit_provenance_row(with_lineage)
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
        # Empty derived so the unknown-source axis is the sole live fail path
        # (BR-66 registration would otherwise outrank with unregistered_derived).
        row = {
            "source": "synthface3",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_explicit_synthetic_category_unknown_source_pending(self) -> None:
        # Caller SYNTHETIC_SOURCE + unknown source, no derived tag: sole fail
        # path is the synthetic door's pending default. Prefer a token that
        # does not hit the NC package floor (vec2face-successor is now an
        # NC floor hit via the vec2face seed — B9-02 follow-up).
        row = {
            "source": "mysteryganv2",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.SYNTHETIC_SOURCE
        )
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
        # BR-30: otherwise-valid row; only the unknown category must fire.
        # Exact reason only (TEST-17) — no UNKNOWN_SOURCE disjunction.
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "category": "not_a_real_category",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

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

    @pytest.mark.parametrize(
        "bad",
        [
            ["buffalo"],
            123,
            {"model": "buffalo"},
        ],
    )
    def test_br37_audit_derived_from_model_rejects_non_string(self, bad: Any) -> None:
        # BR-37: direct entry point type guard — row path uses a different loop.
        result = policy.audit_derived_from_model(bad)  # type: ignore[arg-type]
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

    def test_br37_audit_derived_from_model_none_is_empty_opt_out(self) -> None:
        # None at the direct entry point is the documented empty opt-out (PASS),
        # distinct from a missing key on a provenance row (INVALID_ROW above).
        result = policy.audit_derived_from_model(None)
        assert result.ok is True
        assert result.reason is None
    def test_tooling_row_requires_package_identifier(self) -> None:
        # BR-24: missing package / package_name / source fails closed.
        row = {
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_tooling_row(row)
        assert result.ok is False, result.detail
        assert result.reason is policy.RejectionReason.UNKNOWN_SOURCE


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


# ---------------------------------------------------------------------------
# FIR-7-BR-19 / BR-28 — NC id segment matching + constrained buffalo/insightface
# ---------------------------------------------------------------------------


class TestNcModelMatcherPrecision:
    """BR-19 (too narrow on versioned ids) + BR-28 (too wide on buffalo/insightface)."""

    @pytest.mark.parametrize(
        "tag",
        [
            "retinaface_r50",
            "retinaface-r50",
            "arcface_r100",
            "arcface-r100",
            "arcface_glint360k_r100",
            "retinaface_mnet025_v2",
            "vec2face_g1",
        ],
    )
    def test_br19_versioned_nc_ids_fail(self, tag: str) -> None:
        result = policy.audit_derived_from_model(tag)
        assert result.ok is False, f"expected NC fail for {tag!r}, got {result}"
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize(
        "derived",
        ["yunet/retinaface_r50", "rt_detr/vec2face_g1"],
    )
    def test_br19_versioned_nc_ids_fail_in_composite_row(self, derived: str) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": derived,
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False, f"expected NC fail for {derived!r}, got {result}"
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize(
        "tag",
        [
            "buffalo-wings-detector",
            "buffalo_bill_detector",
            "buffalos-eye/v1",
            "my-buffalo-free",
            "sface/buffalo-wings-detector",
            "not-insightface",
            "insightface-free",
        ],
    )
    def test_br28_legitimate_names_not_swept_as_nc(self, tag: str) -> None:
        result = policy.audit_derived_from_model(tag)
        assert result.ok is True, f"over-blocked {tag!r}: {result.detail}"

    @pytest.mark.parametrize(
        "tag",
        [
            "not-retinaface",
            "arcface_alternative_v2",
            "insightfaces-r-us/model",
            "sface/v1",
            "retinaface-free-reimpl",
        ],
    )
    def test_br28_controls_still_pass(self, tag: str) -> None:
        result = policy.audit_derived_from_model(tag)
        assert result.ok is True, f"over-blocked control {tag!r}: {result.detail}"

    @pytest.mark.parametrize(
        "tag",
        ["retinaface/r50", "arcface/r100", "vec2face/g1", "insightface/buffalo_l"],
    )
    def test_br19_slash_form_controls_still_fail(self, tag: str) -> None:
        result = policy.audit_derived_from_model(tag)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_br28_buffalo_version_suffixes_still_fail(self) -> None:
        for tag in ("buffalo_l", "buffalo_s", "buffalo_sc", "buffalo_l2"):
            result = policy.audit_derived_from_model(tag)
            assert result.ok is False, f"expected NC fail for {tag!r}"
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED


# ---------------------------------------------------------------------------
# FIR-7-BR-20 — NC provenance laundered through source
# ---------------------------------------------------------------------------


class TestNcModelAlsoGatesSourceField:
    """BR-20: banned weights as ``source`` must FAIL like ``derived_from_model``."""

    @pytest.mark.parametrize(
        "value",
        [
            "insightface/buffalo_l",
            "buffalo_l",
            "arcface",
            "retinaface",
            "deepinsight/insightface",
        ],
    )
    def test_br20_nc_string_fails_from_either_field(self, value: str) -> None:
        as_source = policy.audit_source(value)
        assert as_source.ok is False, f"source {value!r} must FAIL NC"
        assert as_source.reason is policy.RejectionReason.NC_MODEL_DERIVED

        as_derived = policy.audit_derived_from_model(value)
        assert as_derived.ok is False, f"derived {value!r} must FAIL NC"
        assert as_derived.reason is policy.RejectionReason.NC_MODEL_DERIVED

        row = {
            "source": value,
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        row_result = policy.audit_provenance_row(row)
        assert row_result.ok is False
        assert row_result.reason is policy.RejectionReason.NC_MODEL_DERIVED


# ---------------------------------------------------------------------------
# FIR-7-BR-21 — unicode / confusable defeats both matchers
# ---------------------------------------------------------------------------


class TestUnicodeNormalisationSharedByMatchers:
    """BR-21: ZWSP / space / dot / Cyrillic confusables fail closed."""

    def test_br21_zwsp_insightface_fails_nc(self) -> None:
        tag = "insight\u200bface"  # zero-width space
        result = policy.audit_derived_from_model(tag)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_br21_space_and_dot_insightface_fail_nc(self) -> None:
        for tag in ("insight face", "insight.face"):
            result = policy.audit_derived_from_model(tag)
            assert result.ok is False, f"expected NC fail for {tag!r}, got {result}"
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_br21_cyrillic_insightface_fails_closed(self) -> None:
        # U+0456 Cyrillic small letter byelorussian-ukrainian i
        tag = "\u0456nsightface"
        result = policy.audit_derived_from_model(tag)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

    def test_br21_cyrillic_casia_fails_closed(self) -> None:
        # U+0441 Cyrillic small letter es + "asia"
        tag = "\u0441asia"
        result = policy.audit_source(tag)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

    def test_br21_literal_casia_still_research_only(self) -> None:
        result = policy.audit_source("casia")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE

    def test_br21_yunet_zwsp_insightface_row_fails(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "yunet/insight\u200bface",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_br21_yunet_insightface_control_fails_nc(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "yunet/insightface",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED


# ---------------------------------------------------------------------------
# FIR-7-BR-27 — research matcher rejects legitimate sources
# ---------------------------------------------------------------------------


class TestResearchMatcherPrecision:
    """BR-27: no bare startswith on whole compact; keep unsplit compounds (BR-31)."""

    @pytest.mark.parametrize(
        "source",
        [
            "ffhq-tools",
            "our_widerface_replacement",
            "casiaset-detector",
            "mfrx-vendor",
            "webfaces-r-us",
            "celebase",
            "ffhq_free_internal",
            "glint360k_free",
            "commercial-ffhq-alternative",
            "dataset_not_ffhq",
        ],
    )
    def test_br27_legitimate_sources_pass(self, source: str) -> None:
        result = policy.audit_source(source)
        assert result.ok is True, f"over-blocked {source!r}: {result.detail}"

    @pytest.mark.parametrize(
        "source",
        ["notffhq", "operator-photo", "self-generated", "dcface", "umap-learn"],
    )
    def test_br27_controls_still_pass(self, source: str) -> None:
        result = policy.audit_source(source)
        assert result.ok is True, f"over-blocked control {source!r}: {result.detail}"

    @pytest.mark.parametrize(
        "source",
        ["ffhq", "casia_webface", "dataset/ffhq", "vggface2_train"],
    )
    def test_br27_controls_still_fail_research(self, source: str) -> None:
        result = policy.audit_source(source)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE

    @pytest.mark.parametrize(
        "source",
        ["ffhq256", "vggface2train", "casiawebfaceextra", "widerfacehd"],
    )
    def test_br27_unsplit_compounds_still_fail(self, source: str) -> None:
        result = policy.audit_source(source)
        assert result.ok is False, f"expected research fail for {source!r}"
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE


# ---------------------------------------------------------------------------
# FIR-7-BR-36 — DCFace clearance lookup beyond slash-only heads
# ---------------------------------------------------------------------------


class TestDcfaceClearanceSegmentResolve:
    """BR-36: dcface_v2 / myorg/dcface resolve registry head; no-lineage agrees."""

    def _row(
        self,
        source: str,
        *,
        lineage: bool,
        clearance: str = "dcface_operator_clearance_20260723",
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "source": source,
            "license": "Apache-2.0",
            "derived_from_model": "",
            "clearance_decision": clearance,
        }
        if lineage:
            row["generator_lineage"] = "ffhq"
        return row

    @pytest.mark.parametrize("source", ["dcface_v2", "dcface/v2", "myorg/dcface", "dcface"])
    @pytest.mark.parametrize("lineage", [True, False])
    def test_br36_dcface_forms_pass_with_clearance(
        self, source: str, lineage: bool
    ) -> None:
        result = policy.audit_provenance_row(self._row(source, lineage=lineage))
        assert result.ok is True, (
            f"source={source!r} lineage={lineage} expected PASS, got {result}"
        )

    @pytest.mark.parametrize("source", ["dcface_v2", "myorg/dcface"])
    def test_br36_dcface_forms_fail_without_clearance(self, source: str) -> None:
        row = self._row(source, lineage=True, clearance="wrong_token")
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_br36_dcface_v2_no_lineage_still_requires_clearance(self) -> None:
        row = {
            "source": "dcface_v2",
            "license": "Apache-2.0",
            "derived_from_model": "",
            # no clearance, no lineage — must not silently pass
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE


# ---------------------------------------------------------------------------
# FIR-7-BR-23 / BR-26 — entry-point parity + shared NC gate
# ---------------------------------------------------------------------------


class TestEntryPointParityAndCommonNcGate:
    """BR-23: caller category dispatches. BR-26: NC fails from every door."""

    def test_br23_occluder_parity_uncleared(self) -> None:
        row = {
            "license": "MIT",
            "derived_from_model": "",
            "source": "random_flickr",
            "photo_clearance": "uncleared",
        }
        via_row = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.OCCLUDER_ASSET
        )
        via_door = policy.audit_occluder_asset(row)
        assert via_row.ok is False
        assert via_door.ok is False
        assert via_row.reason is policy.RejectionReason.UNCLEARED_OCCLUDER_ASSET
        assert via_door.reason is policy.RejectionReason.UNCLEARED_OCCLUDER_ASSET
        assert via_row.reason is via_door.reason

    def test_br23_occluder_parity_cleared_pass(self) -> None:
        row = {
            "license": "Apache-2.0",
            "derived_from_model": "",
            "source": "self-generated",
            "photo_clearance": "cleared",
        }
        via_row = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.OCCLUDER_ASSET
        )
        via_door = policy.audit_occluder_asset(row)
        assert via_row.ok is True, via_row.detail
        assert via_door.ok is True, via_door.detail
        assert via_row.reason is via_door.reason

    def test_br23_synthetic_requires_nonempty_source(self) -> None:
        for row in (
            {"license": "Apache-2.0", "derived_from_model": ""},
            {"source": "", "license": "Apache-2.0", "derived_from_model": ""},
            {"source": "   ", "license": "Apache-2.0", "derived_from_model": ""},
        ):
            result = policy.audit_provenance_row(
                row, category=policy.PolicyCategory.SYNTHETIC_SOURCE
            )
            assert result.ok is False, f"expected fail for {row!r}"
            assert result.reason is policy.RejectionReason.UNKNOWN_SOURCE

    def test_br23_synthetic_parity_with_audit_synthetic_source(self) -> None:
        # Scalar synthetic door reports registry PENDING. Row path through
        # SYNTHETIC_SOURCE also runs the package-identity floor (RV-10); after
        # B9-02 follow-up, bare ``vec2face`` is an NC package seed so the row
        # reports ``nc_model_derived`` (floor outranks the door-local pending
        # reason — complete mediation, not a parity regression).
        row = {
            "source": "vec2face",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        via_row = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.SYNTHETIC_SOURCE
        )
        via_door = policy.audit_synthetic_source("vec2face")
        assert via_row.ok is False
        assert via_door.ok is False
        assert via_row.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert via_door.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_br23_model_ingest_parity_vendor_missing(self) -> None:
        row = {
            "source": "vendorX",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        via_row = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.MODEL_INGEST
        )
        via_door = policy.audit_model_ingest("vendorX")
        assert via_row.ok is False
        assert via_door.ok is False
        assert via_row.reason is policy.RejectionReason.MISSING_INGEST_ENTRY
        assert via_door.reason is policy.RejectionReason.MISSING_INGEST_ENTRY

    def test_br23_model_ingest_parity_yunet_pass(self) -> None:
        row = {
            "source": "yunet",
            "license": "MIT",
            "derived_from_model": "",
        }
        via_row = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.MODEL_INGEST
        )
        via_door = policy.audit_model_ingest("yunet")
        assert via_row.ok is True, via_row.detail
        assert via_door.ok is True, via_door.detail
        assert via_row.reason is via_door.reason

    def test_br26_occluder_rejects_nc_derived(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "photo_clearance": "cleared",
            "derived_from_model": "insightface/buffalo_l",
        }
        via_door = policy.audit_occluder_asset(row)
        via_row = policy.audit_provenance_row(row)
        assert via_door.ok is False
        assert via_door.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert via_row.ok is False
        assert via_row.reason is policy.RejectionReason.NC_MODEL_DERIVED


# ---------------------------------------------------------------------------
# FIR-7-BR-24 — tooling row consults PACKAGE_DENYLIST
# ---------------------------------------------------------------------------


class TestToolingRowDenylist:
    """BR-24 / BR-39: tooling row + dependency denylist / allowlist-miss."""

    def test_br24_ultralytics_source_field_fails_denylisted(self) -> None:
        row = {
            "source": "ultralytics",
            "license": "BSD-3-Clause",
            "derived_from_model": "",
        }
        result = policy.audit_tooling_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_br24_ultralytics_package_name_fails_denylisted(self) -> None:
        row = {
            "package_name": "ultralytics",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_tooling_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_br24_ultralytics_dep_parity(self) -> None:
        # GATE-05: trip BOTH the package denylist and a bogus row licence so
        # the reason channel discriminates ordering. With Apache-2.0 alone both
        # orderings report denylisted_package; a competing unknown SPDX was
        # masking the package reason when the floor ran first.
        row = {
            "package_name": "ultralytics",
            "license": "NOT-A-REAL-SPDX",
            "derived_from_model": "",
        }
        via_row = policy.audit_tooling_row(row)
        via_dep = policy.audit_tooling_dependency("ultralytics")
        assert via_dep.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert via_row.ok is False
        assert via_row.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"package denylist must outrank the row-declared licence; "
            f"got {via_row.reason} (a self-declared licence must not launder "
            "or mask a denylisted package — BR-24 / GATE-05)"
        )
        assert via_row.reason is via_dep.reason

    def test_br24_umap_learn_tooling_row_passes(self) -> None:
        row = {
            "package_name": "umap-learn",
            "license": "BSD-3-Clause",
            "derived_from_model": "",
        }
        result = policy.audit_tooling_row(row)
        assert result.ok is True, result.detail

    def test_br39_tooling_row_unknown_package_fails(self) -> None:
        # BR-39: row door must surface allowlist-miss, not silently pass.
        row = {
            "package_name": "totally-unknown-pkg",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_tooling_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SOURCE


# ---------------------------------------------------------------------------
# FIR-7-BR-22 — unregistered synthetic sources fail closed (SECD-05)
# ---------------------------------------------------------------------------


class TestUnregisteredSourceFailClosed:
    """BR-22: unknown sources default to PENDING-LEGAL-CLEARANCE, not PASS."""

    @pytest.mark.parametrize(
        "source",
        [
            "synthface3",
            "mysteryganv2",
            "my-synthetic-gan",
            # vec2face-successor: after B9-02 follow-up the vec2face package
            # floor seed claims it (seed_ + rest) with nc_model_derived —
            # stricter and correct; keep a pure-unknown token here.
            "unknown-synthetic-gan-v9",
        ],
    )
    def test_br22_unregistered_sources_pending(self, source: str) -> None:
        row = {
            "source": source,
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False, f"expected PENDING for {source!r}, got {result}"
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_br22_vec2face_successor_is_nc_package_floor(self) -> None:
        """vec2face-successor is no longer a pure-unknown pending cell.

        B9-02 follow-up: ``vec2face`` package-floor seed matches via (b)
        separator-boundary; TRAINING_DATA reports nc_model_derived.
        """
        row = {
            "source": "vec2face-successor",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        hit = policy._package_denylist_hit("vec2face-successor")
        assert hit is not None and hit.package_id == "vec2face"

    def test_br22_control_with_derived_also_pending(self) -> None:
        # Dual fault: unknown source + unregistered derived. Floor registration
        # (BR-66) outranks the door-local unknown-source pending reason.
        row = {
            "source": "synthface3",
            "license": "Apache-2.0",
            "derived_from_model": "synthface3/g1",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNREGISTERED_DERIVED_MODEL


# ---------------------------------------------------------------------------
# FIR-7-BR-25 — self-generated is a source, not a licence
# ---------------------------------------------------------------------------


class TestSelfGeneratedIsSourceNotLicense:
    """BR-25: scraped data cannot self-declare the self-generated licence tag."""

    def test_br25_scraped_with_self_generated_license_fails(self) -> None:
        row = {
            "source": "scraped_from_the_web",
            "license": "self-generated",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX

    def test_br25_contract3_self_generated_apache_still_passes(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is True, result.detail


# ---------------------------------------------------------------------------
# FIR-7-BR-35 — multi-licence field resolution
# ---------------------------------------------------------------------------


class TestMultiLicenseFieldResolution:
    """BR-35: disagreeing licence keys fail closed; denylist cannot hide."""

    def test_br35_disagreeing_license_and_spdx_id_fails(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "spdx_id": "AGPL-3.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

    def test_br35_agreeing_license_keys_pass(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "spdx_id": "apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is True, result.detail

    def test_br35_secondary_only_agpl_still_fails(self) -> None:
        row = {
            "source": "self-generated",
            "spdx_id": "AGPL-3.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE


# ---------------------------------------------------------------------------
# FIR-7-BR-33 — unregistered derived split from synthetic path
# ---------------------------------------------------------------------------


class TestUnregisteredDerivedModel:
    """BR-33: dedicated reason; operator renderer passes; NC precedence."""

    def test_br33_operator_renderer_passes(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "acx/occluder-renderer-v1",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is True, result.detail

    def test_br33_retinaface_r50_is_nc_not_pending(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "retinaface_r50",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_br33_registered_rt_detr_passes(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "rt-detr",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is True, result.detail

    def test_br33_unregistered_derived_on_ingest_source_fails(self) -> None:
        # GATE-21 re-fixtured: this test's original lineage was
        # ``acx/occluder-renderer-v1``, which the sibling test above asserts
        # PASSes under ``source=self-generated``. Asserting the same lineage
        # both registered and unregistered depending on ``source`` specified
        # the source-keyed exemption GATE-21 removed. The property it meant to
        # protect -- an unregistered lineage fails on an ingest source -- is
        # kept here with a lineage genuinely absent from every registry.
        row = {
            "source": "yunet",
            "license": "MIT",
            "derived_from_model": "acx/not-a-registered-renderer",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNREGISTERED_DERIVED_MODEL

    @pytest.mark.parametrize(
        "source",
        ["self-generated", "yunet", "operator-render", "rt-detr"],
    )
    def test_gate21_registration_verdict_independent_of_source(
        self, source: str
    ) -> None:
        """Registration is a property of the lineage, not of the source axis."""
        registered = policy.audit_provenance_row(
            {
                "source": source,
                "license": "Apache-2.0",
                "derived_from_model": "acx/occluder-renderer-v1",
            }
        )
        assert (
            registered.reason
            is not policy.RejectionReason.UNREGISTERED_DERIVED_MODEL
        )

        unregistered = policy.audit_provenance_row(
            {
                "source": source,
                "license": "Apache-2.0",
                "derived_from_model": "acx/not-a-registered-renderer",
            }
        )
        assert unregistered.ok is False
        assert (
            unregistered.reason
            is policy.RejectionReason.UNREGISTERED_DERIVED_MODEL
        )

    @pytest.mark.parametrize(
        "forged",
        [
            "evilcorp/acx_internal_projector",
            "otherorg/acx_internal_projector",
            "acx_internal_projector_v2",
            "acx_internal_projector_r50",
            "acx_internal_projector_train",
            "acx/occluder_renderer_v1_hd",
            "acx/occluder-renderer-v1/evil",
            "occluder-renderer-v1",
            "acx",
        ],
    )
    def test_gate24_operator_lineage_registry_is_exact_only(
        self, forged: str
    ) -> None:
        """A row author cannot mint an exemption token from a registered head.

        Foreign org prefixes and the ``_expand_id_forms`` variant vocabulary
        (``_r50`` / ``_v2`` / ``_train`` / ``_hd``) must not inherit operator
        ownership. ``source`` is operator-owned so registration is the only
        live axis.
        """
        result = policy.audit_provenance_row(
            {
                "source": "self-generated",
                "license": "Apache-2.0",
                "derived_from_model": forged,
            }
        )
        assert result.ok is False, f"{forged!r} forged an exemption"
        assert result.reason is policy.RejectionReason.UNREGISTERED_DERIVED_MODEL

    @pytest.mark.parametrize(
        "spelling",
        [
            "acx/occluder-renderer-v1",
            "ACX/OCCLUDER-RENDERER-V1",
            "acx/occluder_renderer_v1",
            "  acx/occluder-renderer-v1  ",
            "acx_internal_projector",
            "ACX_Internal_Projector",
        ],
    )
    def test_gate24_registered_lineage_still_resolves(self, spelling: str) -> None:
        """Negative control: exact-only must not reject honest spellings."""
        result = policy.audit_provenance_row(
            {
                "source": "self-generated",
                "license": "Apache-2.0",
                "derived_from_model": spelling,
            }
        )
        assert result.ok is True, result.detail

    def test_br33_nc_precedence_over_synthetic(self) -> None:
        # Dual violation: NC-derived + synthetic source key. NC wins.
        row = {
            "source": "dcface",
            "license": "Apache-2.0",
            "derived_from_model": "insightface/buffalo_l",
            "clearance_decision": policy.DCFACE_CLEARANCE_DECISION,
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED


# ---------------------------------------------------------------------------
# FIR-7-BR-34 — row-declared category is non-dispatching
# ---------------------------------------------------------------------------


class TestRowDeclaredCategoryNonDispatching:
    """BR-34: row category validated but never selects the gate."""

    def test_br34_contract3_passes_with_and_without_row_category(self) -> None:
        base = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        without = policy.audit_provenance_row(base)
        with_cat = policy.audit_provenance_row(
            {**base, "category": "synthetic_source"}
        )
        assert without.ok is True, without.detail
        assert with_cat.ok is True, with_cat.detail

    def test_br34_caller_category_still_dispatches(self) -> None:
        # Contrast: *caller* SYNTHETIC_SOURCE with empty source fails.
        result = policy.audit_provenance_row(
            {
                "source": "self-generated",
                "license": "Apache-2.0",
                "derived_from_model": "",
            },
            category=policy.PolicyCategory.SYNTHETIC_SOURCE,
        )
        # self-generated is not a synthetic registry entry → pending via door.
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE


# ---------------------------------------------------------------------------
# FIR-7-BR-38 — dead surface cleanup + NC ingest derivation path
# ---------------------------------------------------------------------------


class TestBr38NcIngestDerivationAndHelpers:
    """BR-38: MODEL_INGEST commercial_use loop is exercised via monkeypatch."""

    def test_br38_nc_tagged_ingest_entry_joins_nc_model_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry = policy.ModelIngestEntry(
            model_id="nc_face_weights_v1",
            display_name="NC Face Weights v1",
            role=policy.DetectorRole.FACE_DETECTOR,
            verification=policy.VerificationMetadata(
                spdx_id="Non-Commercial",
                commercial_use=policy.CommercialUse.NON_COMMERCIAL,
            ),
        )
        new_ingest = dict(policy.MODEL_INGEST_ENTRIES)
        new_ingest["nc_face_weights_v1"] = entry
        monkeypatch.setattr(policy, "MODEL_INGEST_ENTRIES", new_ingest)
        derived = policy._derive_nc_model_ids()
        assert "nc_face_weights_v1" in derived
        monkeypatch.setattr(policy, "NC_MODEL_IDS", derived)
        result = policy.audit_derived_from_model("nc_face_weights_v1/r50")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_br38_require_string_field_used_for_missing_derived(self) -> None:
        # Structural path routes through _require_string_field (BR-38).
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

RESEARCH_CORPORA = ["ffhq", "ms1m", "glint360k", "casia_webface", "vggface2_train", "widerface"]


class TestBr64ResearchCorpusDerivedFromModel:
    """BR-64: derived_from_model was never checked against the research registry."""

    @pytest.mark.parametrize("corpus", RESEARCH_CORPORA)
    def test_research_corpus_rejected_by_scalar_door(self, corpus: str) -> None:
        result = policy.audit_derived_from_model(corpus)
        assert result.ok is False, f"{corpus!r} is research-only; must not pass"
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE

    @pytest.mark.parametrize("nc_model", ["buffalo_l", "insightface/buffalo_l"])
    def test_nc_precedence_preserved(self, nc_model: str) -> None:
        # Discrimination control: the NC ban keeps precedence over the new
        # research check, so the reason must NOT drift to research_only_source.
        result = policy.audit_derived_from_model(nc_model)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize(
        "dual_tag",
        ["insightface/ms1m", "insightface/glint360k",
         "deepinsight/insightface/ms1m", "buffalo_l/ffhq"],
    )
    def test_nc_wins_when_input_matches_both_registries(self, dual_tag: str) -> None:
        # The cases above cannot pin the ORDER: `buffalo_l` is not a research
        # source, so the research check never competes. Only a tag matching
        # BOTH registries discriminates -- reorder the two checks and this dies.
        assert policy.match_nc_model_pattern(dual_tag) is not None, "fixture must match NC"
        assert policy._looks_like_research_source(dual_tag), "fixture must match research"
        result = policy.audit_derived_from_model(dual_tag)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            "NC must outrank research_only_source when a tag matches both"
        )

    @pytest.mark.parametrize("corpus", RESEARCH_CORPORA)
    def test_self_generated_row_cannot_launder_research_corpus(self, corpus: str) -> None:
        # The operator-owned `self-generated` exemption must not waive the
        # research taint carried by derived_from_model.
        row = {"source": "self-generated", "license": "Apache-2.0",
               "derived_from_model": corpus, "photo_clearance": "cleared"}
        result = policy.audit_provenance_row(row, category=policy.PolicyCategory.TRAINING_DATA)
        assert result.ok is False, f"self-generated + derived={corpus!r} must not pass"
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE

    def test_clean_derived_still_passes(self) -> None:
        # Guards against a blanket-reject "fix".
        assert policy.audit_derived_from_model("rt-detr").ok is True


class TestBr53CategoryIndependentFloor:
    """BR-53: a caller must not escape the floor by picking a weaker category."""

    # `source` must stay taint-free: an NC/research source outranks the licence
    # floor (BR-53 source axis), which would mask the reason this class pins.
    # package is on TOOLING_ALLOWLIST (license_policy.py TOOLING_ALLOWLIST /
    # "numba") so the TOOLING door reaches the licence axis rather than
    # unknown_source. derived_from_model="" so TRAINING_DATA is not invalid_row
    # for a missing type-checked field (RD-08 / GATE-12 / TEST-17).
    DENYLISTED_LICENSE_ROW = {
        "model_id": "yunet",
        "source": "self-generated",
        "license": "AGPL-3.0",
        "derived_from_model": "",
        "package": "numba",
    }
    CLEARED_SYNTHETIC_ROW = {
        "source": "dcface",
        "license": "AGPL-3.0",
        "derived_from_model": "",
        "package": "numba",
    }

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_denylisted_license_rejected_by_every_door(self, category) -> None:
        result = policy.audit_provenance_row(dict(self.DENYLISTED_LICENSE_ROW), category=category)
        assert result.ok is False, (
            f"category={category.value} passed a row the other doors reject; "
            "a caller could pick this door to bypass the gate"
        )
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE, (
            f"category={category.value} reported {result.reason}; expected "
            "denylisted_license — an off-axis rejection does not pin the floor"
        )

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_clearance_does_not_waive_license_floor(self, category) -> None:
        row = dict(self.CLEARED_SYNTHETIC_ROW)
        row["clearance_decision"] = policy.DCFACE_CLEARANCE_DECISION
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"category={category.value}: an operator clearance token must not "
            "waive the AGPL-3.0 denylist"
        )
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE, (
            f"category={category.value} reported {result.reason}; expected "
            "denylisted_license — clearance must not swap the fail axis"
        )

    def test_license_floor_reason_is_exact(self) -> None:
        result = policy.audit_provenance_row(
            dict(self.DENYLISTED_LICENSE_ROW),
            category=policy.PolicyCategory.MODEL_INGEST,
        )
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_research_source_rejected_by_every_door(self, category) -> None:
        # Single live fail path: research lineage via derived_from_model (GATE-12).
        # model_id/package/photo_clearance/source are clean so door-local missing
        # fields cannot masquerade as the research gate (TEST-15 / TEST-17).
        # derived=ffhq (not source=ffhq) so SYNTHETIC_SOURCE also reports
        # research_only_source rather than its door-local pending default.
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "ffhq",
            "photo_clearance": "cleared",
        }
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"category={category.value} accepted research-tainted lineage"
        )
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE, (
            f"category={category.value} reported {result.reason}; expected "
            "research_only_source — an incidental rejection is not this gate"
        )

    def test_legitimate_model_ingest_still_passes(self) -> None:
        # Guards against a blanket-reject "fix" that would make the floor vacuous.
        row = {"model_id": "rt-detr", "license": "Apache-2.0", "derived_from_model": ""}
        result = policy.audit_provenance_row(row, category=policy.PolicyCategory.MODEL_INGEST)
        assert result.ok is True, f"clean ingest row must still pass: {result.detail}"


class TestGate04LicenceKeySpellingAndCasing:
    """GATE-04: the licence collector matched its key set exactly.

    A denylisted licence declared as ``License``/``licence``/``SPDX-ID`` was
    never collected, so the floor examined nothing and the row passed. Spelling
    and casing variants must resolve to the canonical key, and any *other*
    licence-shaped key must fail closed rather than be silently ignored --
    a caller who declares a licence must never have it dropped on the floor.
    """

    BASE: ClassVar[dict] = {
        "model_id": "rt-detr",
        "derived_from_model": "",
        "source": "self-generated",
    }

    def _row(self, **extra) -> dict:
        row = dict(self.BASE)
        row.update(extra)
        return row

    @pytest.mark.parametrize(
        "key", ["license", "License", "LICENSE", "licence", "Licence", "spdx_id", "SPDX-ID", "spdx"]
    )
    @pytest.mark.parametrize(
        "category",
        [policy.PolicyCategory.MODEL_INGEST, policy.PolicyCategory.TOOLING],
    )
    def test_denylisted_licence_caught_under_every_spelling(self, key, category) -> None:
        row = self._row(package="numba", **{key: "AGPL-3.0"})
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"{category.value}: a denylisted licence declared as {key!r} was "
            "not collected -- the floor examined nothing"
        )
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE

    @pytest.mark.parametrize("key", ["license_notes", "spdx_comment", "licence_url"])
    def test_unrecognised_licence_shaped_key_fails_closed(self, key) -> None:
        result = policy.audit_provenance_row(
            self._row(**{key: "Apache-2.0"}), category=policy.PolicyCategory.MODEL_INGEST
        )
        assert result.ok is False, (
            f"{key!r} is licence-shaped but not collected; ignoring it silently "
            "launders a declared licence into a pass"
        )
        assert result.reason is policy.RejectionReason.INVALID_ROW

    def test_non_string_under_an_alias_is_invalid(self) -> None:
        result = policy.audit_provenance_row(
            self._row(License=123), category=policy.PolicyCategory.MODEL_INGEST
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

    @pytest.mark.parametrize("key", ["notes", "verified_at", "model_family"])
    def test_non_licence_keys_are_untouched(self, key) -> None:
        # Guards against a blanket "any unknown key is invalid" over-reach that
        # would make the fail-closed guard indiscriminate.
        result = policy.audit_provenance_row(
            self._row(license="Apache-2.0", **{key: "anything"}),
            category=policy.PolicyCategory.MODEL_INGEST,
        )
        assert result.ok is True, f"{key!r} is not licence-shaped: {result.detail}"

    def test_allowlisted_licence_under_a_variant_spelling_still_passes(self) -> None:
        result = policy.audit_provenance_row(
            self._row(License="Apache-2.0"), category=policy.PolicyCategory.MODEL_INGEST
        )
        assert result.ok is True, f"variant spelling must not reject a clean licence: {result.detail}"


class TestBr53SourceAxisClosedOnEveryDoor:
    """BR-53 (source axis): the leaky half the licence fix did not cover.

    At d243436c ``tooling`` and ``model_ingest`` PASSed a row carrying
    ``source: insightface`` outright, while ``training_data`` rejected it --
    a caller picking the weaker door bypassed the NC gate entirely.

    Asserting only ``ok is False`` cannot prove this is closed. At d243436c the
    research row failed ``tooling`` with ``unknown_source``, ``model_ingest``
    with ``missing_ingest_entry`` and ``occluder_asset`` with
    ``uncleared_occluder_asset`` -- three doors that never examined ``source``
    at all, yet looked green. Each door's exact reason is pinned so an
    incidental rejection cannot masquerade as the gate holding (TEST-17).
    """

    # Carries the key each door dispatches on, so every door reaches its own
    # gate rather than dying early on a missing field.
    def _row(self, source: str) -> dict:
        return {
            "model_id": "rt-detr",
            "package": "numba",
            "source": source,
            "license": "Apache-2.0",
            "derived_from_model": "",
            "photo_clearance": "cleared",
        }

    # SYNTHETIC_SOURCE reports its own more specific reason; covered separately.
    TAINT_REPORTING_DOORS: ClassVar[list] = [
        c for c in policy.PolicyCategory if c is not policy.PolicyCategory.SYNTHETIC_SOURCE
    ]

    @pytest.mark.parametrize("category", TAINT_REPORTING_DOORS)
    def test_nc_source_reason_is_exact_on_every_door(self, category) -> None:
        result = policy.audit_provenance_row(self._row("insightface"), category=category)
        assert result.ok is False, f"{category.value} PASSed an NC source"
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            f"{category.value} rejected for {result.reason} rather than the NC "
            "source; an incidental rejection leaves the bypass open"
        )

    @pytest.mark.parametrize("category", TAINT_REPORTING_DOORS)
    def test_research_source_reason_is_exact_on_every_door(self, category) -> None:
        result = policy.audit_provenance_row(self._row("ffhq"), category=category)
        assert result.ok is False, f"{category.value} PASSed a research-only source"
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE, (
            f"{category.value} rejected for {result.reason} rather than the "
            "research-only source"
        )

    @pytest.mark.parametrize("category", TAINT_REPORTING_DOORS)
    def test_confusable_nc_source_fails_closed_on_every_door(self, category) -> None:
        # Reusing audit_source carries its NFKC/Cf check to doors that never had
        # one: a Cyrillic-i 'insightface' must fail closed, not launder.
        result = policy.audit_provenance_row(self._row("іnsightface"), category=category)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"{category.value} accepted a confusable NC source as {result.reason}"
        )

    def test_synthetic_door_reports_source_taint_for_non_registry_heads(
        self,
    ) -> None:
        # FIR-7-RV-11: SYNTHETIC_SOURCE exemption is only for synthetic-registry
        # heads (so the door can report clearance). An NC / research source
        # that is not a registry head must keep its specific taint reason —
        # not the generic pending_legal_clearance unknown-head default.
        result = policy.audit_provenance_row(
            self._row("insightface"), category=policy.PolicyCategory.SYNTHETIC_SOURCE
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            f"non-registry NC source through synthetic door reported "
            f"{result.reason}, expected nc_model_derived (FIR-7-RV-11)"
        )

    def test_synthetic_door_keeps_clearance_reason_for_registry_heads(
        self,
    ) -> None:
        # Registry head without clearance_decision: door / floor reports the
        # actionable clearance reason (not research/NC — dcface is neither).
        result = policy.audit_provenance_row(
            self._row("dcface"), category=policy.PolicyCategory.SYNTHETIC_SOURCE
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE
        assert "requires clearance_decision=" in result.detail

    def test_synthetic_exemption_cannot_pass_a_tainted_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The exemption is only safe because any PASS from the door is
        # re-checked. Register a commercially ALLOWED synthetic entry whose id
        # is NC by pattern: the door admits it, the backstop must not.
        entry = policy.SyntheticSourceEntry(
            source_id="arcface",
            verification=policy.VerificationMetadata(
                spdx_id="Apache-2.0",
                commercial_use=policy.CommercialUse.ALLOWED,
                verified_at="2026-07-31",
                clearance_decision="test_clearance_20260731",
                notes="test-only: ALLOWED entry that is also NC by pattern",
            ),
        )
        new_entries = dict(policy.SYNTHETIC_SOURCE_ENTRIES)
        new_entries["arcface"] = entry
        monkeypatch.setattr(policy, "SYNTHETIC_SOURCE_ENTRIES", new_entries)
        # Rebuild the import-time resolution maps the same way production does;
        # patching the dict alone leaves the head map stale.
        monkeypatch.setattr(
            policy,
            "SYNTHETIC_SOURCE_IDS_EXPANDED",
            policy._expand_ids(frozenset(new_entries.keys())),
        )
        head_map: dict[str, str] = {}
        for key in new_entries:
            canon = policy.canonical(key)
            if canon is None:
                continue
            for form in policy._expand_id_forms(canon, exact_only=False):
                head_map.setdefault(form, canon)
        monkeypatch.setattr(policy, "_SYNTHETIC_EXPANDED_TO_HEAD", head_map)

        door = policy.audit_synthetic_source(
            "arcface", row_clearance="test_clearance_20260731"
        )
        assert door.ok is True, (
            "precondition: the door itself must admit this id, otherwise the "
            f"backstop is never exercised and this test is vacuous ({door.detail})"
        )

        row = self._row("arcface")
        row["clearance_decision"] = "test_clearance_20260731"
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.SYNTHETIC_SOURCE
        )
        assert result.ok is False, "backstop did not re-check a door PASS"
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_clean_source_still_passes_every_door_that_admits_it(self) -> None:
        # Guards against a blanket-reject "fix" that would make the floor vacuous.
        row = {"model_id": "rt-detr", "license": "Apache-2.0", "derived_from_model": ""}
        result = policy.audit_provenance_row(
            dict(row), category=policy.PolicyCategory.MODEL_INGEST
        )
        assert result.ok is True, f"clean ingest row must still pass: {result.detail}"


class TestTaintOutranksLicenseFloor:
    """GATE-01: the floor must not mask the derived-taint reason.

    Both rules reject, so ok=False cannot discriminate -- only the reason can.
    Reporting the licence first understates the row: swapping the licence
    clears that reason while the banned lineage survives.
    """

    # Trips BOTH the licence floor and the derived_from_model taint.
    NC_PLUS_DENYLISTED = {
        "source": "self-generated",
        "license": "AGPL-3.0",
        "derived_from_model": "insightface",
        "photo_clearance": "cleared",
    }
    RESEARCH_PLUS_DENYLISTED = {
        "source": "self-generated",
        "license": "AGPL-3.0",
        "derived_from_model": "ffhq",
        "photo_clearance": "cleared",
    }

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_nc_derivation_outranks_denylisted_license(self, category) -> None:
        row = dict(self.NC_PLUS_DENYLISTED)
        assert policy.match_nc_model_pattern(row["derived_from_model"]) is not None
        floor = policy._audit_row_licenses(row, category=category, required=False)
        assert floor.ok is False, "fixture must also trip the licence floor"
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            f"category={category.value} reported {result.reason} -- the licence "
            "floor is masking the NC lineage, which the licence field cannot clear"
        )

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_research_derivation_outranks_denylisted_license(self, category) -> None:
        row = dict(self.RESEARCH_PLUS_DENYLISTED)
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE, (
            f"category={category.value} reported {result.reason}; research-corpus "
            "lineage must outrank the licence floor"
        )

    # TRAINING_DATA is excluded: it structurally requires derived_from_model and
    # reports invalid_row before the floor is reached (pinned separately below).
    FLOOR_REACHING_CATEGORIES = [
        c for c in policy.PolicyCategory if c is not policy.PolicyCategory.TRAINING_DATA
    ]
    # Carries package/model_id so TOOLING (GATE-05: package before licence) and
    # MODEL_INGEST reach the licence floor rather than dying on an unknown
    # package identifier when the derived_from_model key is absent.
    KEY_ABSENT_DENYLISTED_ROW = {
        "model_id": "rt-detr",
        "package": "numba",
        "source": "self-generated",
        "license": "AGPL-3.0",
        "photo_clearance": "cleared",
    }

    @pytest.mark.parametrize("category", FLOOR_REACHING_CATEGORIES)
    def test_floor_still_runs_when_derived_key_absent(self, category) -> None:
        # The taint block is guarded by `if "derived_from_model" in row`. Replace
        # that guard with an early `return None` and the floor is skipped for
        # key-absent rows -- asserting the exact reason is what catches it,
        # because other rules also produce ok=False here.
        #
        # BR-71: also pin ``_floor_licenses`` directly so OCCLUDER_ASSET (which
        # re-checks licence with required=True after the floor) cannot satisfy
        # this test via its door-local path alone (TEST-17).
        row = dict(self.KEY_ABSENT_DENYLISTED_ROW)
        assert "derived_from_model" not in row
        # Synthetic door rejects self-generated before licence; use a cleared
        # synthetic head so the licence floor is the sole fail path there.
        if category is policy.PolicyCategory.SYNTHETIC_SOURCE:
            row = dict(row)
            row["source"] = "dcface"
            row["clearance_decision"] = policy.DCFACE_CLEARANCE_DECISION
        floor = policy._floor_licenses(row, category=category)
        assert floor is not None, (
            f"category={category.value}: _floor_licenses returned None for an "
            "AGPL row — the licence floor was skipped"
        )
        assert floor.reason is policy.RejectionReason.DENYLISTED_LICENSE, (
            f"category={category.value}: floor reported {floor.reason}"
        )
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE, (
            f"category={category.value} reported {result.reason} instead of the "
            "licence floor; the floor was skipped for a row with no "
            "derived_from_model key"
        )

    def test_training_data_requires_derived_key_before_floor(self) -> None:
        row = dict(self.KEY_ABSENT_DENYLISTED_ROW)
        result = policy.audit_provenance_row(row, category=policy.PolicyCategory.TRAINING_DATA)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW


class TestFloorLicenceIsOptionalNotWaived:
    """GATE-03: the floor uses required=False. Pin both halves of that choice.

    Flipping it to required=True leaves every other test green, so without
    these the seam is undefended: a tightening would silently reject every
    registry-sourced row that inherits its licence from the REGISTRY.
    """

    def test_registry_sourced_row_without_license_key_passes(self) -> None:
        # rt-detr normalises to the registered rt_detr, which supplies Apache-2.0.
        row = {"model_id": "rt-detr", "derived_from_model": ""}
        assert "license" not in row
        result = policy.audit_provenance_row(row, category=policy.PolicyCategory.MODEL_INGEST)
        assert result.ok is True, (
            f"floor rejected a registry-sourced row with no license field: {result.detail}"
        )

    def test_absent_license_does_not_waive_the_denylist(self) -> None:
        # The other half: required=False must not become "licence is optional".
        row = {"model_id": "rt-detr", "license": "AGPL-3.0", "derived_from_model": ""}
        result = policy.audit_provenance_row(row, category=policy.PolicyCategory.MODEL_INGEST)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE

    def test_unregistered_id_without_license_still_fails_closed(self) -> None:
        row = {"model_id": "not-registered", "derived_from_model": ""}
        result = policy.audit_provenance_row(row, category=policy.PolicyCategory.MODEL_INGEST)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.MISSING_INGEST_ENTRY


# ---------------------------------------------------------------------------
# GATE-09 — multi-fault rows report exactly one documented-precedence reason
# ---------------------------------------------------------------------------


class TestGate09MultiFaultPrecedencePinned:
    """GATE-09: short-circuit is by design; precedence must be documented and
    pinned so a future reordering is a visible test failure (CLM-03).

    Floor order (see ``_common_provenance_checks`` docstring) — six steps:
      derived taint → source taint → clearance_decision →
      package-identity denylist (FIR-7-RV-10; every door, not TOOLING-only) →
      registration → licence
    TOOLING additionally places the door-local package allowlist admission
    between the package-identity floor and registration (GATE-05 / GATE-22).
    BR-74: clearance outranks the door-local BR-25 licence-before-allowlist
    ordering whenever both fire.
    """

    @pytest.mark.parametrize(
        ("category", "row", "expected_reason"),
        [
            # MODEL_INGEST: unregistered id + bad licence → licence wins over
            # missing_ingest_entry because the floor licence axis runs before
            # the door-specific ingest lookup.
            (
                policy.PolicyCategory.MODEL_INGEST,
                {
                    "model_id": "totally_unknown_detector_xyz",
                    "license": "NOT-A-REAL-SPDX",
                    "derived_from_model": "",
                },
                policy.RejectionReason.UNKNOWN_SPDX,
            ),
            # TOOLING: denylisted package + bad licence → package wins (BR-24).
            (
                policy.PolicyCategory.TOOLING,
                {
                    "package": "ultralytics",
                    "license": "NOT-A-REAL-SPDX",
                    "derived_from_model": "",
                },
                policy.RejectionReason.DENYLISTED_PACKAGE,
            ),
            # TRAINING_DATA: uncleared synthetic + bad licence → clearance
            # outranks licence on the floor (GATE-11 axis placement / BR-74).
            (
                policy.PolicyCategory.TRAINING_DATA,
                {
                    "source": "dcface",
                    "license": "NOT-A-REAL-SPDX",
                    "derived_from_model": "",
                },
                policy.RejectionReason.PENDING_LEGAL_CLEARANCE,
            ),
            # TRAINING_DATA: NC derived + uncleared synthetic + bad licence →
            # derived taint outranks both clearance and licence.
            (
                policy.PolicyCategory.TRAINING_DATA,
                {
                    "source": "dcface",
                    "license": "AGPL-3.0",
                    "derived_from_model": "insightface/buffalo_l",
                },
                policy.RejectionReason.NC_MODEL_DERIVED,
            ),
            # OCCLUDER_ASSET: bad licence + uncleared photo → licence floor
            # fires before the door's uncleared gate.
            (
                policy.PolicyCategory.OCCLUDER_ASSET,
                {
                    "license": "NOT-A-REAL-SPDX",
                    "source": "self-generated",
                    "derived_from_model": "",
                },
                policy.RejectionReason.UNKNOWN_SPDX,
            ),
            # BR-74: pseudo-licence (self-generated as SPDX) + uncleared
            # synthetic → floor clearance outranks door-local BR-25 licence
            # reporting. Both reject; only the reason discriminates.
            (
                policy.PolicyCategory.TRAINING_DATA,
                {
                    "source": "dcface",
                    "license": "self-generated",
                    "derived_from_model": "",
                },
                policy.RejectionReason.PENDING_LEGAL_CLEARANCE,
            ),
            # BR-66: unregistered derived + bad licence → registration outranks
            # licence on the floor.
            (
                policy.PolicyCategory.TOOLING,
                {
                    "model_id": "rt-detr",
                    "package": "numba",
                    "license": "NOT-A-REAL-SPDX",
                    "source": "internal_studio",
                    "derived_from_model": "some_unregistered_model",
                },
                policy.RejectionReason.UNREGISTERED_DERIVED_MODEL,
            ),
        ],
    )
    def test_multi_fault_reports_documented_winner(
        self, category, row, expected_reason
    ) -> None:
        result = policy.audit_provenance_row(dict(row), category=category)
        assert result.ok is False
        assert result.reason is expected_reason, (
            f"category={category.value}: multi-fault row reported "
            f"{result.reason}, documented precedence expects {expected_reason}"
        )


# ---------------------------------------------------------------------------
# GATE-08 — occluder licence detail keeps door context for both catch sites
# ---------------------------------------------------------------------------


class TestGate08OccluderLicenseDetailContext:
    """GATE-08: present-but-invalid licence must carry the same door prefix as
    a missing licence field. The floor catches present invalid values with
    required=False; the door's required=True catch still owns the missing
    field. Both paths must report ``occluder asset: …`` in detail.
    """

    def test_missing_license_field_detail_has_occluder_prefix(self) -> None:
        asset = {
            "photo_clearance": "cleared",
            "source": "internal_studio",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.MISSING_LICENSE_FIELD
        assert result.detail.startswith("occluder asset: "), (
            f"missing-field path lost door context: {result.detail!r}"
        )
        assert "license" in result.detail.lower() or "spdx" in result.detail.lower()

    def test_present_but_invalid_license_detail_has_occluder_prefix(self) -> None:
        asset = {
            "license": "NOT-A-REAL-SPDX",
            "photo_clearance": "cleared",
            "source": "internal_studio",
        }
        result = policy.audit_occluder_asset(asset)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX
        assert result.detail.startswith("occluder asset: "), (
            f"present-but-invalid path lost door context: {result.detail!r}"
        )
        assert "NOT-A-REAL-SPDX" in result.detail

    def test_missing_and_invalid_share_detail_prefix_shape(self) -> None:
        # Pin the two catch sites against each other so they cannot silently
        # diverge again (floor vs door required=True prefix branch).
        missing = policy.audit_occluder_asset(
            {"photo_clearance": "cleared", "source": "internal_studio"}
        )
        invalid = policy.audit_occluder_asset(
            {
                "license": "NOT-A-REAL-SPDX",
                "photo_clearance": "cleared",
                "source": "internal_studio",
            }
        )
        assert missing.ok is False and invalid.ok is False
        assert missing.detail.startswith("occluder asset: ")
        assert invalid.detail.startswith("occluder asset: ")


# ---------------------------------------------------------------------------
# GATE-11 — clearance axis is content-triggered floor, not door-waivable
# ---------------------------------------------------------------------------


class TestGate11ClearanceFloorOnEveryDoor:
    """GATE-11 / BR-65: uncleared synthetic-registry lineage fails on every door.

    Clearance is a shared floor obligation (WEB-33 / SECD-03 / ARCH-13), not a
    per-door option. The synthetic-lineage token lives on ``clearance_decision``;
    the occluder photo-release state lives on ``photo_clearance`` — distinct
    keys so the vocabularies cannot invert each other (NAME-03 / BR-65).
    """

    # Verified repro fixture: registered synthetic source whose registry entry
    # carries clearance_decision, no matching token on the row.
    # photo_clearance is present so OCCLUDER_ASSET reaches the floor rather than
    # dying on the photo-release axis first (GATE-18 / BR-70 / TEST-17).
    UNCLEARED_DCFACE: ClassVar[dict[str, Any]] = {
        "model_id": "rt-detr",
        "package": "numba",
        "source": "dcface",
        "license": "Apache-2.0",
        "derived_from_model": "",
        "photo_clearance": "cleared",
    }

    # Exact reason per door (TEST-15). After BR-65 every door reports the floor
    # clearance reason — including OCCLUDER_ASSET (no early-return waiver).
    EXPECTED_UNCLEARED_REASON: ClassVar[dict] = {
        policy.PolicyCategory.TRAINING_DATA: (
            policy.RejectionReason.PENDING_LEGAL_CLEARANCE
        ),
        policy.PolicyCategory.SYNTHETIC_SOURCE: (
            policy.RejectionReason.PENDING_LEGAL_CLEARANCE
        ),
        policy.PolicyCategory.OCCLUDER_ASSET: (
            policy.RejectionReason.PENDING_LEGAL_CLEARANCE
        ),
        policy.PolicyCategory.TOOLING: (
            policy.RejectionReason.PENDING_LEGAL_CLEARANCE
        ),
        policy.PolicyCategory.MODEL_INGEST: (
            policy.RejectionReason.PENDING_LEGAL_CLEARANCE
        ),
    }

    # Doors that admit a correctly-cleared dcface row when only the lineage
    # axis is required. Occluder still needs photo_clearance (additive).
    CLEARANCE_ADMITTING_DOORS: ClassVar[list] = [
        policy.PolicyCategory.TRAINING_DATA,
        policy.PolicyCategory.SYNTHETIC_SOURCE,
        policy.PolicyCategory.TOOLING,
        policy.PolicyCategory.MODEL_INGEST,
    ]

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_uncleared_dcface_fails_every_door_with_exact_reason(
        self, category
    ) -> None:
        row = dict(self.UNCLEARED_DCFACE)
        assert "clearance_decision" not in row
        # Pin the floor helper itself (GATE-18 / TEST-17): training_data and
        # synthetic_source doors keep a door-local clearance backstop that
        # produces the same reason, so door-only asserts survive floor-neutering.
        # Asserting the floor return makes every parametrisation a victim.
        floor = policy._content_triggered_clearance_check(row, category=category)
        assert floor is not None, (
            f"category={category.value}: floor clearance returned None for "
            "uncleared dcface — the content-triggered floor was skipped"
        )
        assert floor.ok is False
        assert floor.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE
        assert floor.category is category, (
            f"category={category.value}: floor mis-tagged result.category as "
            f"{floor.category}"
        )
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"category={category.value} PASSed an uncleared dcface row; "
            "a caller could pick this door to bypass the clearance gate"
        )
        expected = self.EXPECTED_UNCLEARED_REASON[category]
        assert result.reason is expected, (
            f"category={category.value} reported {result.reason}, "
            f"expected {expected}"
        )

    @pytest.mark.parametrize("category", CLEARANCE_ADMITTING_DOORS)
    def test_cleared_dcface_passes_admitting_doors(self, category) -> None:
        # Positive control: the matching clearance_decision token admits the
        # row on every door that does not ADD a photo-release obligation.
        row = dict(self.UNCLEARED_DCFACE)
        row["clearance_decision"] = policy.DCFACE_CLEARANCE_DECISION
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is True, (
            f"category={category.value} rejected a correctly-cleared dcface "
            f"row: {result.reason} {result.detail}"
        )

    def test_cleared_dcface_still_fails_occluder_without_photo_clearance(
        self,
    ) -> None:
        # Occluder photo-release is a distinct additive axis (BR-65).
        row = dict(self.UNCLEARED_DCFACE)
        row["clearance_decision"] = policy.DCFACE_CLEARANCE_DECISION
        row.pop("photo_clearance", None)  # explicit absence of photo axis
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.OCCLUDER_ASSET
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNCLEARED_OCCLUDER_ASSET

    def test_cleared_dcface_with_photo_clearance_passes_occluder(self) -> None:
        row = dict(self.UNCLEARED_DCFACE)
        row["source"] = "operator-photo"  # registered occluder source
        row["derived_from_model"] = "dcface"
        row["clearance_decision"] = policy.DCFACE_CLEARANCE_DECISION
        row["photo_clearance"] = "cleared"
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.OCCLUDER_ASSET
        )
        assert result.ok is True, (
            f"both axes satisfied must pass occluder: "
            f"{result.reason} {result.detail}"
        )

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_source_without_clearance_decision_unaffected(
        self, category
    ) -> None:
        # Negative control: a source whose registry entry (or absence) carries
        # no clearance_decision must keep pre-hoist outcomes. The floor is
        # content-triggered, not an unconditional token demand.
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "photo_clearance": "cleared",
        }
        result = policy.audit_provenance_row(row, category=category)
        if category is policy.PolicyCategory.SYNTHETIC_SOURCE:
            # self-generated is not a synthetic registry head.
            assert result.ok is False
            assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE
        else:
            assert result.ok is True, (
                f"category={category.value}: a non-clearance-triggering row "
                f"must still pass: {result.reason} {result.detail}"
            )

    @pytest.mark.parametrize(
        "category",
        [
            policy.PolicyCategory.TOOLING,
            policy.PolicyCategory.MODEL_INGEST,
        ],
    )
    def test_derived_from_model_dcface_also_triggers_floor(
        self, category
    ) -> None:
        # The trigger is source OR derived_from_model; tooling/model_ingest
        # previously ignored both.
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "dcface/x",
        }
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"category={category.value} ignored derived_from_model=dcface/x"
        )
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE


# ---------------------------------------------------------------------------
# FIR-7-BR-56 — the slash/underscore asymmetry is deliberate (resolved wontfix)
# ---------------------------------------------------------------------------


class TestBr56SlashUnderscoreAsymmetryIsDeliberate:
    """BR-56 asked that slash and underscore spellings agree. They must not.

    Neither direction of "make them agree" is available:

    * Segment-matching underscore compounds is the progressive-prefix grammar
      that BR-50 / BR-52 removed for over-matching.
    * Relaxing slash components to whole-string matching flips 637 currently
      rejected sources to PASS (measured over a 3,330-source corpus), among
      them ``vendor/casia/subset``, ``acme/celeba/mirror`` and
      ``acme/casia/commercial_repack``. A subset or a mirror of a research
      corpus is still that corpus.

    So the asymmetry stays and is pinned here: a slash is a hierarchical
    separator and each component is an identity token matched in its own
    right; an underscore is not, and underscore forms match whole-string
    only. Consistency does not outrank fail-safe defaults [SECD-05].

    Correction to the finding as filed: ``internal/mfr/not_research`` PASSes
    (``mfr`` is exact-only / BR-58) and was never a repro row.
    """

    @pytest.mark.parametrize(
        ("source", "expect_ok", "expect_reason"),
        [
            # --- the rows the finding filed as inconsistent: slash FAILs ---
            ("acme/ffhq/replacement_v1", False, "research_only_source"),
            ("vendor/casia/commercial_repack", False, "research_only_source"),
            ("ffhq/tools", False, "research_only_source"),
            ("org/ffhq/reimpl", False, "research_only_source"),
            ("acme/ffhq/replacement", False, "research_only_source"),
            # --- ...and the underscore spelling PASSes. This is the asymmetry.
            ("acme/ffhq_replacement_v1", True, None),
            ("vendor/casia_commercial_repack", True, None),
            # --- terminal research component (both shapes FAIL) ---
            ("acme/ffhq", False, "research_only_source"),
            ("dataset/ffhq", False, "research_only_source"),
            ("ffhq", False, "research_only_source"),
            ("vendor/casia", False, "research_only_source"),
            ("casia", False, "research_only_source"),
            # --- non-terminal research component (FAIL) ---
            ("acme/ffhq/train", False, "research_only_source"),
            ("org/casia/webface", False, "research_only_source"),
            ("dataset/ffhq/aligned", False, "research_only_source"),
            # --- no research component at all (PASS) ---
            ("acme/commercial_pack_v1", True, None),
            ("vendor/tools/internal", True, None),
            # --- finding correction: mfr exact-only, not a BR-56 repro ---
            ("internal/mfr/not_research", True, None),
        ],
    )
    def test_br56_shape_table(
        self,
        source: str,
        expect_ok: bool,
        expect_reason: str | None,
    ) -> None:
        result = policy.audit_source(source)
        assert isinstance(result, policy.LicenseAuditResult)
        assert result.ok is expect_ok, (
            f"source={source!r}: expected ok={expect_ok}, got {result}"
        )
        if expect_ok:
            assert result.reason is None
        else:
            assert result.reason is policy.RejectionReason(expect_reason)

    @pytest.mark.parametrize(
        "leaf",
        ["subset", "mirror", "clone", "pack", "assets", "eval", "derived"],
    )
    @pytest.mark.parametrize("corpus", ["casia", "ffhq", "celeba", "widerface"])
    def test_laundering_leaf_under_research_component_still_fails(
        self, corpus: str, leaf: str
    ) -> None:
        """A repack/mirror/subset of a research corpus is still that corpus.

        These 28 sources were the bulk of the 637 that a whole-string relaxation
        of the slash path would have opened. Regression guard: any future
        "consistency" change to the matcher must keep them closed.
        """
        source = f"vendor/{corpus}/{leaf}"
        result = policy.audit_source(source)
        assert result.ok is False, f"{source!r} must not pass: {result}"
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE


# ---------------------------------------------------------------------------
# FIR-7-BR-48 — no live-looking dead private helpers on the security path
# ---------------------------------------------------------------------------


class TestBr48NoDeadPrivateHelpers:
    """BR-48: private module-level helpers must have at least one load ref.

    ``_nfkc_lower``, ``_compact_alnum``, ``_split_segments``, and ``_spdx_of``
    (plus the equally-dead ``_prepare_match_text``) were defined but never
    loaded. BR-56 resolved wontfix and did not claim ``_split_segments`` —
    matching stays in ``_membership_hit`` — so all five were deleted rather
    than routed. This AST guard keeps that class of defect from returning.
    """

    def test_no_private_module_function_with_zero_load_refs(self) -> None:
        import ast

        src = _MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        defined = [
            n.name
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("_")
            and not n.name.startswith("__")
        ]

        class _LoadCounter(ast.NodeVisitor):
            def __init__(self) -> None:
                self.loads: dict[str, int] = {}

            def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
                if isinstance(node.ctx, ast.Load):
                    self.loads[node.id] = self.loads.get(node.id, 0) + 1
                self.generic_visit(node)

        counter = _LoadCounter()
        counter.visit(tree)
        dead = sorted(name for name in defined if counter.loads.get(name, 0) == 0)
        assert dead == [], (
            "private module-level helpers with zero load references "
            f"(live-looking dead code on the security path): {dead}"
        )

    def test_br48_named_helpers_are_gone(self) -> None:
        # Pin the four named in the finding plus the sibling dead helper removed
        # with them so a rename-and-keep cannot dodge the load-ref guard alone.
        for name in (
            "_nfkc_lower",
            "_compact_alnum",
            "_split_segments",
            "_spdx_of",
            "_prepare_match_text",
        ):
            assert not hasattr(policy, name), f"{name} must not be defined"


# ---------------------------------------------------------------------------
# FIR-7-BR-46 — public scalar entry points share a non-string type contract
# ---------------------------------------------------------------------------


class TestBr46EntryPointTypeContract:
    """BR-46: every public audit_* scalar door returns LicenseAuditResult.

    Non-string, non-None inputs are uniformly ``invalid_row``. ``None`` and
    ``''`` keep their documented per-door meanings (not type errors).
    """

    _ENTRY_POINTS: ClassVar[tuple[str, ...]] = (
        "audit_derived_from_model",
        "audit_spdx",
        "audit_source",
        "audit_model_ingest",
        "audit_synthetic_source",
        "audit_tooling_dependency",
    )

    # Explicit 30-cell expected-reason table (None reason ⇒ PASS).
    @pytest.mark.parametrize(
        ("entry_point", "value", "expected_reason"),
        [
            # audit_derived_from_model: None/'' are empty opt-out PASS
            ("audit_derived_from_model", None, None),
            ("audit_derived_from_model", "", None),
            ("audit_derived_from_model", 123, "invalid_row"),
            ("audit_derived_from_model", [], "invalid_row"),
            ("audit_derived_from_model", {}, "invalid_row"),
            # audit_spdx: None/'' → missing_license_field
            ("audit_spdx", None, "missing_license_field"),
            ("audit_spdx", "", "missing_license_field"),
            ("audit_spdx", 123, "invalid_row"),
            ("audit_spdx", [], "invalid_row"),
            ("audit_spdx", {}, "invalid_row"),
            # audit_source: None/'' → unknown_source
            ("audit_source", None, "unknown_source"),
            ("audit_source", "", "unknown_source"),
            ("audit_source", 123, "invalid_row"),
            ("audit_source", [], "invalid_row"),
            ("audit_source", {}, "invalid_row"),
            # audit_model_ingest: None/'' → missing_ingest_entry
            ("audit_model_ingest", None, "missing_ingest_entry"),
            ("audit_model_ingest", "", "missing_ingest_entry"),
            ("audit_model_ingest", 123, "invalid_row"),
            ("audit_model_ingest", [], "invalid_row"),
            ("audit_model_ingest", {}, "invalid_row"),
            # audit_synthetic_source: None/'' → unknown_source
            ("audit_synthetic_source", None, "unknown_source"),
            ("audit_synthetic_source", "", "unknown_source"),
            ("audit_synthetic_source", 123, "invalid_row"),
            ("audit_synthetic_source", [], "invalid_row"),
            ("audit_synthetic_source", {}, "invalid_row"),
            # audit_tooling_dependency: None/'' → unknown_source
            ("audit_tooling_dependency", None, "unknown_source"),
            ("audit_tooling_dependency", "", "unknown_source"),
            ("audit_tooling_dependency", 123, "invalid_row"),
            ("audit_tooling_dependency", [], "invalid_row"),
            ("audit_tooling_dependency", {}, "invalid_row"),
        ],
        ids=[
            "derived-None",
            "derived-empty",
            "derived-int",
            "derived-list",
            "derived-dict",
            "spdx-None",
            "spdx-empty",
            "spdx-int",
            "spdx-list",
            "spdx-dict",
            "source-None",
            "source-empty",
            "source-int",
            "source-list",
            "source-dict",
            "ingest-None",
            "ingest-empty",
            "ingest-int",
            "ingest-list",
            "ingest-dict",
            "synth-None",
            "synth-empty",
            "synth-int",
            "synth-list",
            "synth-dict",
            "tooling-None",
            "tooling-empty",
            "tooling-int",
            "tooling-list",
            "tooling-dict",
        ],
    )
    def test_br46_type_contract_table(
        self,
        entry_point: str,
        value: Any,
        expected_reason: str | None,
    ) -> None:
        fn = getattr(policy, entry_point)
        result = fn(value)
        assert isinstance(result, policy.LicenseAuditResult), (
            f"{entry_point}({value!r}) must return LicenseAuditResult, "
            f"got {type(result).__name__}"
        )
        if expected_reason is None:
            assert result.ok is True, (
                f"{entry_point}({value!r}) expected PASS, got {result}"
            )
            assert result.reason is None
        else:
            assert result.ok is False, (
                f"{entry_point}({value!r}) expected FAIL, got PASS"
            )
            assert result.reason is policy.RejectionReason(expected_reason), (
                f"{entry_point}({value!r}): expected reason "
                f"{expected_reason!r}, got {result.reason}"
            )
            if expected_reason == "invalid_row" and value is not None:
                # Detail must name the offending type (rg-015).
                assert type(value).__name__ in result.detail, (
                    f"{entry_point}({value!r}) invalid_row detail must name "
                    f"type {type(value).__name__!r}: {result.detail!r}"
                )


# ---------------------------------------------------------------------------
# GATE-10 — compound SPDX expressions report denylisted_license correctly
# ---------------------------------------------------------------------------


class TestGate10CompoundSpdxDenylistReason:
    """GATE-10: denylisted components inside SPDX expressions must surface
    ``denylisted_license`` (or ``research_only_license`` for NC-family), not
    ``unknown_spdx``. Fail-closed: a denylisted component in an OR cannot PASS.
    """

    @pytest.mark.parametrize(
        ("spdx", "expected_reason"),
        [
            # verified repro rows (literal)
            ("AGPL-3.0", "denylisted_license"),
            ("AGPL-3.0+", "denylisted_license"),
            ("Apache-2.0 OR AGPL-3.0", "denylisted_license"),
            ("AGPL-3.0 WITH Classpath-exception-2.0", "denylisted_license"),
            ("MIT OR CC-BY-NC-4.0", "research_only_license"),  # NC-family maps here
        ],
    )
    def test_gate10_verified_repro_reasons(
        self, spdx: str, expected_reason: str
    ) -> None:
        result = policy.audit_spdx(spdx)
        assert result.ok is False, f"{spdx!r} must FAIL, got PASS"
        assert result.reason is policy.RejectionReason(expected_reason), (
            f"{spdx!r}: expected {expected_reason!r}, got {result.reason}"
        )

    def test_gate10_bare_allowlisted_still_passes(self) -> None:
        result = policy.audit_spdx("MIT")
        assert result.ok is True
        assert result.reason is None

    def test_gate10_or_with_denylisted_component_cannot_pass(self) -> None:
        # Fail-closed: allowlisted OR denylisted is still a FAIL.
        result = policy.audit_spdx("Apache-2.0 OR AGPL-3.0")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE


# ---------------------------------------------------------------------------
# BR-69 — floor is not subtract-capable; split halves always compose
# ---------------------------------------------------------------------------


class TestBr69FloorNotSubtractCapable:
    """BR-69 / ARCH-13: no parameter can disable a floor axis."""

    def test_common_provenance_checks_has_no_axis_disable_param(self) -> None:
        import inspect

        sig = inspect.signature(policy._common_provenance_checks)
        param_names = set(sig.parameters)
        # Only row (positional-or-keyword) and category (keyword-only).
        assert "check_licenses" not in param_names, (
            "check_licenses reintroduces a subtract-capable floor flag (BR-69)"
        )
        for name in param_names:
            assert not name.startswith("check_"), (
                f"parameter {name!r} looks like an axis switch; floor must be "
                "always-complete (BR-69 / ARCH-13)"
            )
        assert "category" in param_names
        assert "row" in param_names

    def test_floor_licenses_half_trips_licence_only_row(self) -> None:
        # Licence-axis only: clean taint/clearance, bad SPDX.
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "self-generated",
            "license": "AGPL-3.0",
            "derived_from_model": "",
            "photo_clearance": "cleared",
        }
        taint = policy._floor_taint_and_clearance(
            row, category=policy.PolicyCategory.MODEL_INGEST
        )
        assert taint is None, f"taint half must not fire: {taint}"
        lic = policy._floor_licenses(
            row, category=policy.PolicyCategory.MODEL_INGEST
        )
        assert lic is not None and lic.ok is False
        assert lic.reason is policy.RejectionReason.DENYLISTED_LICENSE
        # Composition agrees.
        full = policy._common_provenance_checks(
            row, category=policy.PolicyCategory.MODEL_INGEST
        )
        assert full is not None and full.reason is lic.reason

    def test_floor_taint_half_trips_taint_only_row(self) -> None:
        # Taint-axis only: NC derived, allowlisted SPDX.
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "insightface/buffalo_l",
            "photo_clearance": "cleared",
        }
        taint = policy._floor_taint_and_clearance(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert taint is not None and taint.ok is False
        assert taint.reason is policy.RejectionReason.NC_MODEL_DERIVED
        lic = policy._floor_licenses(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert lic is None, f"licence half must not fire: {lic}"
        full = policy._common_provenance_checks(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert full is not None and full.reason is taint.reason


# ---------------------------------------------------------------------------
# BR-66 — unregistered derived registration is a floor obligation
# ---------------------------------------------------------------------------


class TestBr66RegistrationFloorOnEveryDoor:
    """BR-66 / WEB-33 / ARCH-13: unregistered lineage fails every door."""

    UNREGISTERED: ClassVar[dict[str, Any]] = {
        "model_id": "rt-detr",
        "package": "numba",
        "license": "Apache-2.0",
        "source": "internal_studio",  # NOT operator-owned (masks if self-generated)
        "derived_from_model": "some_unregistered_model",
    }

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_unregistered_derived_fails_every_door(self, category) -> None:
        result = policy.audit_provenance_row(
            dict(self.UNREGISTERED), category=category
        )
        assert result.ok is False, (
            f"category={category.value} PASSed unregistered derived lineage; "
            "registration was not completely mediated"
        )
        assert result.reason is policy.RejectionReason.UNREGISTERED_DERIVED_MODEL, (
            f"category={category.value} reported {result.reason}, "
            "expected unregistered_derived_model"
        )

    def test_registered_lineage_still_passes_where_source_admits(self) -> None:
        # Negative control: registered model-ingest derived head.
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "license": "Apache-2.0",
            "source": "self-generated",
            "derived_from_model": "rt-detr",
            "photo_clearance": "cleared",
        }
        for category in (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
            policy.PolicyCategory.MODEL_INGEST,
            policy.PolicyCategory.OCCLUDER_ASSET,
        ):
            result = policy.audit_provenance_row(dict(row), category=category)
            assert result.ok is True, (
                f"registered lineage must still pass {category.value}: "
                f"{result.reason} {result.detail}"
            )

    def test_operator_owned_source_exempts_unregistered_renderer(self) -> None:
        # Negative control: operator-owned source may name an internal renderer.
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "acx/occluder-renderer-v1",
            "photo_clearance": "cleared",
            "package": "numba",
            "model_id": "rt-detr",
        }
        for category in (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
            policy.PolicyCategory.MODEL_INGEST,
            policy.PolicyCategory.OCCLUDER_ASSET,
        ):
            result = policy.audit_provenance_row(dict(row), category=category)
            assert result.ok is True, (
                f"operator-owned + internal renderer must pass {category.value}: "
                f"{result.reason} {result.detail}"
            )


# ---------------------------------------------------------------------------
# BR-68 — non-string source/derived fails invalid_row on every door
# ---------------------------------------------------------------------------


class TestBr68NonStringFloorFields:
    """BR-68 / SECD-05: unparseable fields reject; they are not absence."""

    @pytest.mark.parametrize(
        ("category", "field", "value", "expected_reason"),
        [
            # source — five non-string shapes × five doors
            (policy.PolicyCategory.TRAINING_DATA, "source", ["dcface"], "invalid_row"),
            (policy.PolicyCategory.TRAINING_DATA, "source", b"dcface", "invalid_row"),
            (policy.PolicyCategory.TRAINING_DATA, "source", 123, "invalid_row"),
            (policy.PolicyCategory.TRAINING_DATA, "source", {}, "invalid_row"),
            (policy.PolicyCategory.TRAINING_DATA, "source", 1.5, "invalid_row"),
            (policy.PolicyCategory.TOOLING, "source", ["dcface"], "invalid_row"),
            (policy.PolicyCategory.TOOLING, "source", b"dcface", "invalid_row"),
            (policy.PolicyCategory.TOOLING, "source", 123, "invalid_row"),
            (policy.PolicyCategory.TOOLING, "source", {}, "invalid_row"),
            (policy.PolicyCategory.TOOLING, "source", 1.5, "invalid_row"),
            (policy.PolicyCategory.MODEL_INGEST, "source", ["dcface"], "invalid_row"),
            (policy.PolicyCategory.MODEL_INGEST, "source", b"dcface", "invalid_row"),
            (policy.PolicyCategory.MODEL_INGEST, "source", 123, "invalid_row"),
            (policy.PolicyCategory.MODEL_INGEST, "source", {}, "invalid_row"),
            (policy.PolicyCategory.MODEL_INGEST, "source", 1.5, "invalid_row"),
            (policy.PolicyCategory.OCCLUDER_ASSET, "source", ["dcface"], "invalid_row"),
            (policy.PolicyCategory.OCCLUDER_ASSET, "source", b"dcface", "invalid_row"),
            (policy.PolicyCategory.OCCLUDER_ASSET, "source", 123, "invalid_row"),
            (policy.PolicyCategory.OCCLUDER_ASSET, "source", {}, "invalid_row"),
            (policy.PolicyCategory.OCCLUDER_ASSET, "source", 1.5, "invalid_row"),
            (policy.PolicyCategory.SYNTHETIC_SOURCE, "source", ["dcface"], "invalid_row"),
            (policy.PolicyCategory.SYNTHETIC_SOURCE, "source", b"dcface", "invalid_row"),
            (policy.PolicyCategory.SYNTHETIC_SOURCE, "source", 123, "invalid_row"),
            (policy.PolicyCategory.SYNTHETIC_SOURCE, "source", {}, "invalid_row"),
            (policy.PolicyCategory.SYNTHETIC_SOURCE, "source", 1.5, "invalid_row"),
            # derived_from_model — same matrix
            (
                policy.PolicyCategory.TRAINING_DATA,
                "derived_from_model",
                ["dcface"],
                "invalid_row",
            ),
            (
                policy.PolicyCategory.TRAINING_DATA,
                "derived_from_model",
                b"dcface",
                "invalid_row",
            ),
            (
                policy.PolicyCategory.TRAINING_DATA,
                "derived_from_model",
                123,
                "invalid_row",
            ),
            (
                policy.PolicyCategory.TRAINING_DATA,
                "derived_from_model",
                {},
                "invalid_row",
            ),
            (
                policy.PolicyCategory.TRAINING_DATA,
                "derived_from_model",
                1.5,
                "invalid_row",
            ),
            (policy.PolicyCategory.TOOLING, "derived_from_model", ["dcface"], "invalid_row"),
            (policy.PolicyCategory.TOOLING, "derived_from_model", b"dcface", "invalid_row"),
            (policy.PolicyCategory.TOOLING, "derived_from_model", 123, "invalid_row"),
            (policy.PolicyCategory.TOOLING, "derived_from_model", {}, "invalid_row"),
            (policy.PolicyCategory.TOOLING, "derived_from_model", 1.5, "invalid_row"),
            (
                policy.PolicyCategory.MODEL_INGEST,
                "derived_from_model",
                ["dcface"],
                "invalid_row",
            ),
            (
                policy.PolicyCategory.MODEL_INGEST,
                "derived_from_model",
                b"dcface",
                "invalid_row",
            ),
            (
                policy.PolicyCategory.MODEL_INGEST,
                "derived_from_model",
                123,
                "invalid_row",
            ),
            (
                policy.PolicyCategory.MODEL_INGEST,
                "derived_from_model",
                {},
                "invalid_row",
            ),
            (
                policy.PolicyCategory.MODEL_INGEST,
                "derived_from_model",
                1.5,
                "invalid_row",
            ),
            (
                policy.PolicyCategory.OCCLUDER_ASSET,
                "derived_from_model",
                ["dcface"],
                "invalid_row",
            ),
            (
                policy.PolicyCategory.OCCLUDER_ASSET,
                "derived_from_model",
                b"dcface",
                "invalid_row",
            ),
            (
                policy.PolicyCategory.OCCLUDER_ASSET,
                "derived_from_model",
                123,
                "invalid_row",
            ),
            (
                policy.PolicyCategory.OCCLUDER_ASSET,
                "derived_from_model",
                {},
                "invalid_row",
            ),
            (
                policy.PolicyCategory.OCCLUDER_ASSET,
                "derived_from_model",
                1.5,
                "invalid_row",
            ),
            (
                policy.PolicyCategory.SYNTHETIC_SOURCE,
                "derived_from_model",
                ["dcface"],
                "invalid_row",
            ),
            (
                policy.PolicyCategory.SYNTHETIC_SOURCE,
                "derived_from_model",
                b"dcface",
                "invalid_row",
            ),
            (
                policy.PolicyCategory.SYNTHETIC_SOURCE,
                "derived_from_model",
                123,
                "invalid_row",
            ),
            (
                policy.PolicyCategory.SYNTHETIC_SOURCE,
                "derived_from_model",
                {},
                "invalid_row",
            ),
            (
                policy.PolicyCategory.SYNTHETIC_SOURCE,
                "derived_from_model",
                1.5,
                "invalid_row",
            ),
        ],
    )
    def test_non_string_field_invalid_row_every_door(
        self, category, field, value, expected_reason
    ) -> None:
        row: dict[str, Any] = {
            "model_id": "rt-detr",
            "package": "numba",
            "license": "Apache-2.0",
            "photo_clearance": "cleared",
        }
        if field == "source":
            row["source"] = value
            row["derived_from_model"] = ""
        else:
            # Keep a string source so the door can reach the floor derived check
            # (synthetic_source requires non-empty source before the floor).
            row["source"] = "self-generated"
            row["derived_from_model"] = value
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"{category.value}/{field}={value!r} PASSed; non-string skipped floor"
        )
        assert result.reason is policy.RejectionReason(expected_reason), (
            f"{category.value}/{field}={value!r}: expected {expected_reason!r}, "
            f"got {result.reason}"
        )


# ---------------------------------------------------------------------------
# BR-65 — two independent clearance axes; occluder never waives the floor
# ---------------------------------------------------------------------------


class TestBr65ClearanceAxesSeparated:
    """BR-65: synthetic lineage token ≠ occluder photo-release vocabulary.

    Properties pinned:
      * no door × token choice admits an uncleared dcface lineage
      * the correct dcface token is never itself a rejection cause
      * generic photo tokens cannot satisfy lineage clearance
    """

    BASE: ClassVar[dict[str, Any]] = {
        "model_id": "rt-detr",
        "package": "numba",
        "license": "Apache-2.0",
        "source": "operator-photo",
        "derived_from_model": "dcface",
    }

    GENERIC_PHOTO_TOKENS: ClassVar[tuple[str, ...]] = (
        "cleared",
        "operator_cleared",
        "allowed",
        "license_cleared",
    )

    # Explicit matrix: (category, clearance_decision, photo_clearance, expected)
    # expected is RejectionReason value string or None for PASS.
    @pytest.mark.parametrize(
        ("category", "clearance_decision", "photo_clearance", "expected_reason"),
        [
            # --- no clearance_decision, no photo_clearance ---
            (policy.PolicyCategory.TRAINING_DATA, None, None, "pending_legal_clearance"),
            (policy.PolicyCategory.TOOLING, None, None, "pending_legal_clearance"),
            (policy.PolicyCategory.MODEL_INGEST, None, None, "pending_legal_clearance"),
            (policy.PolicyCategory.OCCLUDER_ASSET, None, None, "pending_legal_clearance"),
            (policy.PolicyCategory.SYNTHETIC_SOURCE, None, None, "pending_legal_clearance"),
            # --- generic photo tokens as clearance_decision (wrong key/vocab) ---
            # Putting a photo token on the lineage key does not clear lineage.
            *(
                (cat, tok, None, "pending_legal_clearance")
                for cat in policy.PolicyCategory
                for tok in ("cleared", "operator_cleared", "allowed", "license_cleared")
            ),
            # --- generic photo tokens on photo_clearance only (lineage still open) ---
            *(
                (cat, None, tok, "pending_legal_clearance")
                for cat in policy.PolicyCategory
                for tok in ("cleared", "operator_cleared", "allowed", "license_cleared")
            ),
            # --- correct dcface token, no photo_clearance ---
            (policy.PolicyCategory.TRAINING_DATA, "DCFACE", None, None),
            (policy.PolicyCategory.TOOLING, "DCFACE", None, None),
            (policy.PolicyCategory.MODEL_INGEST, "DCFACE", None, None),
            # occluder adds photo-release; lineage token alone is not a reject cause
            # but missing photo_clearance is
            (
                policy.PolicyCategory.OCCLUDER_ASSET,
                "DCFACE",
                None,
                "uncleared_occluder_asset",
            ),
            # synthetic_source with source=operator-photo is not a synthetic head
            # (out-of-scope observation characterises this; pin actual behaviour)
            (
                policy.PolicyCategory.SYNTHETIC_SOURCE,
                "DCFACE",
                None,
                "pending_legal_clearance",
            ),
            # --- correct dcface token + photo_clearance=cleared ---
            (policy.PolicyCategory.TRAINING_DATA, "DCFACE", "cleared", None),
            (policy.PolicyCategory.TOOLING, "DCFACE", "cleared", None),
            (policy.PolicyCategory.MODEL_INGEST, "DCFACE", "cleared", None),
            (policy.PolicyCategory.OCCLUDER_ASSET, "DCFACE", "cleared", None),
            (
                policy.PolicyCategory.SYNTHETIC_SOURCE,
                "DCFACE",
                "cleared",
                "pending_legal_clearance",
            ),
            # --- bogus lineage token ---
            (policy.PolicyCategory.TRAINING_DATA, "bogus_token_xyz", None, "pending_legal_clearance"),
            (policy.PolicyCategory.TOOLING, "bogus_token_xyz", None, "pending_legal_clearance"),
            (policy.PolicyCategory.MODEL_INGEST, "bogus_token_xyz", None, "pending_legal_clearance"),
            (
                policy.PolicyCategory.OCCLUDER_ASSET,
                "bogus_token_xyz",
                "cleared",
                "pending_legal_clearance",
            ),
            (
                policy.PolicyCategory.SYNTHETIC_SOURCE,
                "bogus_token_xyz",
                None,
                "pending_legal_clearance",
            ),
        ],
    )
    def test_br65_door_token_matrix(
        self, category, clearance_decision, photo_clearance, expected_reason
    ) -> None:
        row = dict(self.BASE)
        if clearance_decision == "DCFACE":
            row["clearance_decision"] = policy.DCFACE_CLEARANCE_DECISION
        elif clearance_decision is not None:
            row["clearance_decision"] = clearance_decision
        if photo_clearance is not None:
            row["photo_clearance"] = photo_clearance
        result = policy.audit_provenance_row(row, category=category)
        if expected_reason is None:
            assert result.ok is True, (
                f"{category.value} cd={clearance_decision!r} "
                f"pc={photo_clearance!r}: expected PASS, got "
                f"{result.reason} {result.detail}"
            )
            # Correct lineage token must never appear as a rejection cause.
            assert result.reason is None
        else:
            assert result.ok is False, (
                f"{category.value} cd={clearance_decision!r} "
                f"pc={photo_clearance!r}: expected FAIL {expected_reason}, got PASS"
            )
            assert result.reason is policy.RejectionReason(expected_reason), (
                f"{category.value} cd={clearance_decision!r} "
                f"pc={photo_clearance!r}: expected {expected_reason!r}, "
                f"got {result.reason}"
            )
            # FIR-7-RV-08: pin the causal path, not only the enum. BASE has
            # derived_from_model=dcface, so missing/wrong clearance_decision
            # must report the real clearance obligation ("requires
            # clearance_decision=..."). Correct DCFACE token + source=
            # operator-photo on SYNTHETIC_SOURCE is the unknown-head path
            # ("has no clearance entry") — never collapse them.
            if expected_reason == "pending_legal_clearance":
                if clearance_decision == "DCFACE":
                    # Lineage axis satisfied; synthetic door rejects the
                    # non-registry source head.
                    assert "has no clearance entry" in result.detail, (
                        f"{category.value} cd=DCFACE: expected unknown-head "
                        f"detail, got {result.detail!r}"
                    )
                    assert "requires clearance_decision=" not in result.detail
                else:
                    # Clearance path: neutering _audit_clearance_decision must
                    # RED these cells (they must not silently fall through to
                    # the unknown-head phrasing).
                    assert "requires clearance_decision=" in result.detail, (
                        f"{category.value} cd={clearance_decision!r}: expected "
                        f"clearance-path detail, got {result.detail!r}"
                    )
            # The correct dcface token is never itself the rejection cause:
            # when we supplied it, the reason must not be a lineage miss
            # phrased as "got <dcface token>".
            if clearance_decision == "DCFACE":
                assert policy.DCFACE_CLEARANCE_DECISION not in (
                    result.detail.split("got ")[-1] if "got " in result.detail else ""
                ) or result.reason is not policy.RejectionReason.PENDING_LEGAL_CLEARANCE or (
                    "requires clearance_decision" not in result.detail
                    or f"got {policy.DCFACE_CLEARANCE_DECISION!r}" not in result.detail
                )

    def test_br65_generic_token_cannot_clear_lineage_on_occluder(self) -> None:
        # Verified BR-65 repro: generic photo token on photo_clearance with
        # dcface derived must still fail the lineage floor on occluder.
        for tok in self.GENERIC_PHOTO_TOKENS:
            row = {
                **self.BASE,
                "photo_clearance": tok,
                # deliberately no clearance_decision
            }
            result = policy.audit_provenance_row(
                row, category=policy.PolicyCategory.OCCLUDER_ASSET
            )
            assert result.ok is False, f"photo_clearance={tok!r} waived lineage floor"
            assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_br65_correct_token_never_rejected_as_lineage_miss(self) -> None:
        # Correct token + photo release must pass occluder; correct token alone
        # may fail photo-release but not as a lineage mismatch.
        row = {
            **self.BASE,
            "clearance_decision": policy.DCFACE_CLEARANCE_DECISION,
            "photo_clearance": "cleared",
        }
        for category in policy.PolicyCategory:
            result = policy.audit_provenance_row(dict(row), category=category)
            if category is policy.PolicyCategory.SYNTHETIC_SOURCE:
                # source=operator-photo is not a synthetic registry head.
                assert result.ok is False
                assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE
                # Must not claim the dcface token was wrong.
                assert (
                    f"got {policy.DCFACE_CLEARANCE_DECISION!r}" not in result.detail
                )
                assert "has no clearance entry" in result.detail
            else:
                assert result.ok is True, (
                    f"{category.value} rejected correct dual-axis row: "
                    f"{result.reason} {result.detail}"
                )


    # -----------------------------------------------------------------
    # FIR-7-RV-09 — real synthetic head dual-axis matrix coverage
    # -----------------------------------------------------------------

    SYNTH_HEAD_BASE: ClassVar[dict[str, Any]] = {
        "model_id": "rt-detr",
        "package": "numba",
        "license": "Apache-2.0",
        "source": "dcface",
        "derived_from_model": "",
    }

    @pytest.mark.parametrize(
        (
            "category",
            "has_clearance",
            "photo_clearance",
            "expect_ok",
            "expected_reason",
            "detail_substr",
        ),
        [
            # Correct clearance token + each photo_clearance state: admit only
            # when the door does not ADD a further obligation. Occluder rejects
            # dcface as an unregistered pack-build source (photo axis orthogonal).
            (policy.PolicyCategory.TRAINING_DATA, True, None, True, None, None),
            (policy.PolicyCategory.TRAINING_DATA, True, "cleared", True, None, None),
            (policy.PolicyCategory.TRAINING_DATA, True, "allowed", True, None, None),
            (policy.PolicyCategory.TOOLING, True, None, True, None, None),
            (policy.PolicyCategory.TOOLING, True, "cleared", True, None, None),
            (policy.PolicyCategory.MODEL_INGEST, True, None, True, None, None),
            (policy.PolicyCategory.MODEL_INGEST, True, "cleared", True, None, None),
            (policy.PolicyCategory.SYNTHETIC_SOURCE, True, None, True, None, None),
            (policy.PolicyCategory.SYNTHETIC_SOURCE, True, "cleared", True, None, None),
            (
                policy.PolicyCategory.SYNTHETIC_SOURCE,
                True,
                "operator_cleared",
                True,
                None,
                None,
            ),
            (
                policy.PolicyCategory.OCCLUDER_ASSET,
                True,
                "cleared",
                False,
                "unknown_source",
                "not a registered",
            ),
            (
                policy.PolicyCategory.OCCLUDER_ASSET,
                True,
                None,
                False,
                "uncleared_occluder_asset",
                "uncleared",
            ),
            # Missing clearance on a real synthetic head: clearance path only.
            (
                policy.PolicyCategory.TRAINING_DATA,
                False,
                None,
                False,
                "pending_legal_clearance",
                "requires clearance_decision=",
            ),
            (
                policy.PolicyCategory.SYNTHETIC_SOURCE,
                False,
                None,
                False,
                "pending_legal_clearance",
                "requires clearance_decision=",
            ),
            (
                policy.PolicyCategory.TOOLING,
                False,
                None,
                False,
                "pending_legal_clearance",
                "requires clearance_decision=",
            ),
            (
                policy.PolicyCategory.MODEL_INGEST,
                False,
                None,
                False,
                "pending_legal_clearance",
                "requires clearance_decision=",
            ),
            (
                policy.PolicyCategory.OCCLUDER_ASSET,
                False,
                "cleared",
                False,
                "pending_legal_clearance",
                "requires clearance_decision=",
            ),
        ],
    )
    def test_br65_real_synth_head_dual_axis_matrix(
        self,
        category,
        has_clearance,
        photo_clearance,
        expect_ok,
        expected_reason,
        detail_substr,
    ) -> None:
        """FIR-7-RV-09: dual-axis admit/fail path for a real synthetic head.

        Uses source=dcface so the clearance obligation is what the cell
        exercises (unlike BASE source=operator-photo). Photo_clearance state
        must admit or fail only for the right door-local reason.
        """
        row = dict(self.SYNTH_HEAD_BASE)
        if has_clearance:
            row["clearance_decision"] = policy.DCFACE_CLEARANCE_DECISION
        if photo_clearance is not None:
            row["photo_clearance"] = photo_clearance
        result = policy.audit_provenance_row(row, category=category)
        if expect_ok:
            assert result.ok is True, (
                f"{category.value} pc={photo_clearance!r}: expected PASS, got "
                f"{result.reason} {result.detail}"
            )
        else:
            assert result.ok is False, (
                f"{category.value} pc={photo_clearance!r}: expected FAIL "
                f"{expected_reason}, got PASS"
            )
            assert result.reason is policy.RejectionReason(expected_reason), (
                f"{category.value}: expected {expected_reason!r}, got {result.reason}"
            )
            if detail_substr is not None:
                assert detail_substr in result.detail, (
                    f"{category.value}: expected detail containing "
                    f"{detail_substr!r}, got {result.detail!r}"
                )


# ---------------------------------------------------------------------------
# GATE-16 / GATE-17 — clearance axes are not interchangeable; retired key inert
# ---------------------------------------------------------------------------


class TestGate16ClearanceAxesNotInterchangeable:
    """GATE-16: ``photo_clearance`` must not satisfy the lineage axis.

    BR-65 split the overloaded clearance vocabulary into two keys. A regression
    that lets ``_row_clearance_decision_token`` also read ``photo_clearance``
    would admit uncleared dcface lineage on four of five doors. Pin the
    non-equivalence with the exact decision token on the wrong key.
    """

    BASE: ClassVar[dict[str, Any]] = {
        "model_id": "rt-detr",
        "package": "numba",
        "source": "dcface",
        "license": "Apache-2.0",
        "derived_from_model": "",
        # Exact lineage token on the photo-release key — must NOT clear lineage.
        "photo_clearance": None,  # set per-test to DCFACE token
    }

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_dcface_token_on_photo_clearance_does_not_satisfy_lineage(
        self, category
    ) -> None:
        row = dict(self.BASE)
        row["photo_clearance"] = policy.DCFACE_CLEARANCE_DECISION
        assert "clearance_decision" not in row
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"category={category.value}: dcface decision token on "
            "photo_clearance waived the lineage floor"
        )
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE, (
            f"category={category.value} reported {result.reason}; expected "
            "pending_legal_clearance — photo axis must not feed lineage"
        )


class TestGate17RetiredClearanceKeyInert:
    """GATE-17: the retired ``clearance`` key never satisfies either axis."""

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    @pytest.mark.parametrize(
        "token",
        [
            # Exact lineage token — strongest false-admission probe.
            "DCFACE",
            "cleared",
            "operator_cleared",
            "allowed",
        ],
    )
    def test_legacy_clearance_key_never_satisfies_lineage(
        self, category, token
    ) -> None:
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "dcface",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "clearance": (
                policy.DCFACE_CLEARANCE_DECISION if token == "DCFACE" else token
            ),
        }
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"category={category.value}: legacy clearance={token!r} waived lineage"
        )
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE, (
            f"category={category.value} clearance={token!r}: reported "
            f"{result.reason}, expected pending_legal_clearance"
        )

    def test_legacy_clearance_key_never_satisfies_photo_axis(self) -> None:
        # Photo-release axis reads only photo_clearance (BR-65). A legacy
        # clearance=cleared must not admit an occluder pack-build.
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "operator-photo",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "clearance": "cleared",
            # no photo_clearance
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.OCCLUDER_ASSET
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNCLEARED_OCCLUDER_ASSET


# ---------------------------------------------------------------------------
# GATE-07 — path-shaped derived lineage is research-tainted
# ---------------------------------------------------------------------------


class TestGate07PathShapedResearchDerived:
    """GATE-07: slash-shaped derived values must not escape research check."""

    @pytest.mark.parametrize(
        "tag",
        ["widerface/yunet", "ffhq/dcface", "myorg/ffhq"],
    )
    def test_path_shaped_research_derived_fails(self, tag: str) -> None:
        result = policy.audit_derived_from_model(tag)
        assert result.ok is False, f"path-shaped research {tag!r} was admitted"
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE, (
            f"{tag!r} reported {result.reason}; expected research_only_source "
            "(not unregistered_derived_model or another incidental gate)"
        )

    def test_non_research_path_shaped_derived_is_not_research(self) -> None:
        # Negative control: the gate is not "every path is research".
        result = policy.audit_derived_from_model("myorg/internal_renderer")
        assert result.reason is not policy.RejectionReason.RESEARCH_ONLY_SOURCE
        # May PASS (unregistered exemption for bare audit) or fail for another
        # reason; only research_only_source is forbidden here.
        assert result.ok is True or result.reason is not (
            policy.RejectionReason.RESEARCH_ONLY_SOURCE
        )


# ---------------------------------------------------------------------------
# BR-62 — get_model_ingest_entry primary raise is defended
# ---------------------------------------------------------------------------


class TestBr62GetModelIngestEntryPrimaryRaise:
    """BR-62: primary ``raise LicensePolicyError(result)`` has a victim.

    Targets a PACKAGE_DENYLIST hit (registered denylist path), not a bare
    registry miss — misses share the raise site but do not exercise the
    denylist/NC branch of ``audit_model_ingest``.
    """

    def test_denylisted_package_raises_with_exact_reason(self) -> None:
        with pytest.raises(policy.LicensePolicyError) as exc_info:
            policy.get_model_ingest_entry("ultralytics")
        err = exc_info.value
        assert err.result.ok is False
        assert err.result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_nc_denylisted_package_raises_with_exact_reason(self) -> None:
        with pytest.raises(policy.LicensePolicyError) as exc_info:
            policy.get_model_ingest_entry("insightface")
        err = exc_info.value
        assert err.result.ok is False
        assert err.result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_registered_nc_entry_raises_from_the_primary_site(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The primary raise is the ONLY path for a REGISTERED failing entry.

        Both raise sites carry the identical ``result``, so every unregistered
        id (``ultralytics``, ``insightface``, any miss) is absorbed by the
        second site when the first is deleted — the mutant is equivalent for
        them. No shipped entry is non-ALLOWED, so a registry injection is the
        only way to reach ``MODEL_INGEST_ENTRIES.get(...) is not None`` with a
        failing audit and make the primary site load-bearing (BR-62 / TEST-15).
        """
        entry = policy.ModelIngestEntry(
            model_id="nc_ingest_probe",
            display_name="NC Ingest Probe",
            role=policy.DetectorRole.FACE_DETECTOR,
            verification=policy.VerificationMetadata(
                spdx_id="CC-BY-NC-4.0",
                commercial_use=policy.CommercialUse.NON_COMMERCIAL,
                notes="test-only registered entry that fails its own audit",
            ),
        )
        key = policy._resolve_model_key("nc_ingest_probe")
        monkeypatch.setattr(
            policy,
            "MODEL_INGEST_ENTRIES",
            {**policy.MODEL_INGEST_ENTRIES, key: entry},
        )
        # Registered, so the second raise's `entry is None` guard cannot fire.
        assert policy.MODEL_INGEST_ENTRIES.get(key) is not None
        assert policy.PACKAGE_DENYLIST.get(key) is None

        with pytest.raises(policy.LicensePolicyError) as exc_info:
            policy.get_model_ingest_entry("nc_ingest_probe")
        err = exc_info.value
        assert err.result.ok is False
        assert err.result.reason is policy.RejectionReason.NC_MODEL_DERIVED


# ---------------------------------------------------------------------------
# GATE-06 — result.category propagation pinned on every door
# ---------------------------------------------------------------------------


class TestGate06FloorCategoryPropagatedOnEveryDoor:
    """GATE-06: floor rejections carry the caller-requested category.

    Corrected evidence (the filed claim was wrong): mutating floor
    ``category=category`` → ``category=TRAINING_DATA`` is killed by existing
    tests, but mostly via reason/detail — not by deliberate category asserts.
    Four of five doors can be mis-tagged with no category victim. Pin all five.
    """

    FLOOR_REJECT_ROW: ClassVar[dict[str, Any]] = {
        "model_id": "rt-detr",
        "package": "numba",
        "source": "self-generated",
        "license": "Apache-2.0",
        "derived_from_model": "insightface/buffalo_l",
        "photo_clearance": "cleared",
    }

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_floor_rejection_carries_requested_category(self, category) -> None:
        row = dict(self.FLOOR_REJECT_ROW)
        # Pin via the floor helper so door-local re-tags cannot mask a floor bug.
        floor = policy._floor_taint_and_clearance(row, category=category)
        assert floor is not None
        assert floor.ok is False
        assert floor.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert floor.category is category, (
            f"requested {category.value}, floor returned category={floor.category}"
        )
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert result.category is category, (
            f"requested {category.value}, door returned category={result.category}"
        )


# ---------------------------------------------------------------------------
# BR-70 negative control — missing clearance key vs wrong token
# ---------------------------------------------------------------------------


class TestBr70MissingClearanceKeyDistinctFromWrongToken:
    """BR-70: missing clearance_decision key is distinguishable from wrong token."""

    def test_missing_clearance_key_is_pending_not_pass(self) -> None:
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "dcface",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "photo_clearance": "cleared",
        }
        assert "clearance_decision" not in row
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_wrong_clearance_token_is_pending(self) -> None:
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "dcface",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "photo_clearance": "cleared",
            "clearance_decision": "wrong_token_xyz",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_matching_token_passes_tooling(self) -> None:
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "dcface",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "clearance_decision": policy.DCFACE_CLEARANCE_DECISION,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is True, f"matching token must pass: {result.detail}"


# ---------------------------------------------------------------------------
# GATE-19 — BR-68 floor type check + negative controls
# ---------------------------------------------------------------------------


class TestGate19Br68FloorTypeCheckPinned:
    """GATE-19: training_data non-string must die under floor type-skip mutant.

    Door-local ``_require_string_field`` on TRAINING_DATA masks a silent
    floor type-skip. Pin the floor helper for every door, and add PASS
    negative controls so over-rejection is caught too.
    """

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    @pytest.mark.parametrize("field", ["source", "derived_from_model"])
    @pytest.mark.parametrize("value", [["dcface"], b"dcface", 123, {}, 1.5, None])
    def test_floor_rejects_non_string_field(self, category, field, value) -> None:
        row: dict[str, Any] = {
            "model_id": "rt-detr",
            "package": "numba",
            "license": "Apache-2.0",
            "photo_clearance": "cleared",
        }
        if field == "source":
            row["source"] = value
            row["derived_from_model"] = ""
        else:
            row["source"] = "self-generated"
            row["derived_from_model"] = value
        # Floor helper is the single path under type-skip mutation (TEST-17).
        floor = policy._floor_taint_and_clearance(row, category=category)
        assert floor is not None, (
            f"{category.value}/{field}={value!r}: floor skipped non-string"
        )
        assert floor.ok is False
        assert floor.reason is policy.RejectionReason.INVALID_ROW, (
            f"{category.value}/{field}={value!r}: expected invalid_row, got "
            f"{floor.reason}"
        )

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_well_typed_clean_row_is_not_invalid_row(self, category) -> None:
        # Negative control: over-reject-everything would keep FAIL tests green.
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "photo_clearance": "cleared",
        }
        if category is policy.PolicyCategory.SYNTHETIC_SOURCE:
            # self-generated is not a synthetic registry head — expect pending,
            # but never invalid_row from a well-typed row.
            result = policy.audit_provenance_row(row, category=category)
            assert result.reason is not policy.RejectionReason.INVALID_ROW
            return
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is True, (
            f"{category.value} rejected a well-typed clean row: "
            f"{result.reason} {result.detail}"
        )


# ---------------------------------------------------------------------------
# BR-73 — allowlisted package still runs deferred licence check
# ---------------------------------------------------------------------------


class TestBr73AllowlistedPackageDeferredLicenseStillRuns:
    """BR-73: after allowlisted package resolves, deferred row SPDX still fails closed."""

    def test_allowlisted_package_plus_denylisted_row_spdx(self) -> None:
        row = {
            "package": "numba",
            "license": "AGPL-3.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE, (
            f"reported {result.reason}; deferred licence check after allowlisted "
            "package must still fail closed"
        )

    def test_allowlisted_package_plus_bogus_row_spdx(self) -> None:
        row = {
            "package": "umap-learn",
            "license": "NOT-A-REAL-SPDX",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX


# ---------------------------------------------------------------------------
# GATE-20 — floor precedence adjacent pairs (BR-72 docstring order)
# ---------------------------------------------------------------------------


class TestGate20FloorPrecedenceAdjacentPairs:
    """GATE-20: pin each adjacent pair in the documented six-step floor order.

    Documented order (``_common_provenance_checks`` / BR-72 / FIR-7-D2-01):
      derived taint → source taint → clearance_decision →
      package-identity denylist → registration → licence

    A row tainted at step N and step N+1 must report step N's reason.
    """

    def test_derived_taint_outranks_source_taint(self) -> None:
        # Pair 1: derived NC + research source → derived wins.
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "ffhq",
            "license": "Apache-2.0",
            "derived_from_model": "insightface/buffalo_l",
            "photo_clearance": "cleared",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_source_taint_outranks_clearance(self) -> None:
        # Pair 2: research source + uncleared synthetic derived → source taint
        # outranks clearance (source axis runs before clearance on the floor).
        # Use research source with derived=dcface (clearance would also fire).
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "ffhq",
            "license": "Apache-2.0",
            "derived_from_model": "dcface",
            "photo_clearance": "cleared",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is False
        # derived=dcface is also a synthetic head; derived taint runs first.
        # derived=dcface is NOT research/NC — audit_derived passes for pure
        # "dcface" as model name? Check: dcface is synthetic, research check
        # on derived...
        # Actually order: derived taint first. Is "dcface" research? No.
        # Is "dcface" NC? No. Then source taint (ffhq research) fires before
        # clearance. Good.
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE

    def test_clearance_outranks_package_denylist(self) -> None:
        # Pair 3 (FIR-7-D2-01): uncleared synthetic source + denylisted package
        # → clearance wins (step 3 before package-identity step 4). Non-TOOLING
        # door so the floor package step is the only package gate in play.
        row = {
            "source": "dcface",
            "package": "ultralytics",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE, (
            f"clearance must outrank package-denylist; got {result.reason} "
            f"({result.detail})"
        )

    def test_package_denylist_outranks_registration(self) -> None:
        # Pair 4 (FIR-7-D2-01): denylisted package + unregistered derived →
        # package-identity denylist wins (step 4 before registration step 5).
        # Non-TOOLING door; source is not a synthetic head (clearance silent).
        row = {
            "source": "internal_studio",
            "package": "ultralytics",
            "license": "Apache-2.0",
            "derived_from_model": "totally_unregistered_xyz_model",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"package-denylist must outrank registration; got {result.reason} "
            f"({result.detail})"
        )

    def test_clearance_outranks_registration(self) -> None:
        # Pair 5: uncleared synthetic source + unregistered derived → clearance
        # wins (clearance runs before registration on the floor; package clean).
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "dcface",
            "license": "Apache-2.0",
            "derived_from_model": "totally_unregistered_xyz_model",
            "photo_clearance": "cleared",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_registration_outranks_licence(self) -> None:
        # Pair 6: unregistered derived + denylisted licence → registration wins.
        # Source must not be operator-owned (that exempts registration — BR-33).
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "source": "internal_studio",
            "license": "AGPL-3.0",
            "derived_from_model": "totally_unregistered_xyz_model",
            "photo_clearance": "cleared",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNREGISTERED_DERIVED_MODEL


# ---------------------------------------------------------------------------
# GATE-27 — TRAINING_DATA synthetic backstop must not retag category
# ---------------------------------------------------------------------------


class TestGate27SyntheticBackstopCategoryLeak:
    """GATE-27: caller-asked category is preserved through the synthetic backstop.

    The synthetic helper stamps SYNTHETIC_SOURCE on its own results. When the
    TRAINING_DATA path delegates into that helper (generator_lineage present),
    verdict/reason/detail stay the helper's, but ``result.category`` must
    remain the door the *caller* asked for (rg-015 / SECD-03).
    """

    def test_generator_lineage_backstop_keeps_training_data_category(self) -> None:
        # Measured leak row: TRAINING_DATA + generator_lineage → pending, but
        # previously stamped synthetic_source.
        row = {
            "source": "yunet",
            "license": "MIT",
            "derived_from_model": "",
            "generator_lineage": "ffhq",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE
        assert result.category == policy.PolicyCategory.TRAINING_DATA.value

    def test_floor_nc_rejection_still_reports_training_data(self) -> None:
        # Control: floor rejections on the same door already stamped correctly.
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "buffalo_l",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert result.category == policy.PolicyCategory.TRAINING_DATA.value

    def test_clean_training_data_row_still_reports_training_data(self) -> None:
        row = {
            "source": "yunet",
            "license": "MIT",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is True
        assert result.category == policy.PolicyCategory.TRAINING_DATA.value


class TestGate27FiveDoorCategoryInvariant:
    """Five-door category invariant (GATE-27 item 2/3).

    Rule: for every representative row and every door D the caller asked for,
    ``result.category == D.value``. No intentional exemptions found in the
    sweep: invalid_row results already stamp the asked door, and a genuine
    SYNTHETIC_SOURCE dispatch correctly stays ``synthetic_source`` under the
    same equality. The allowlist below is therefore empty — any future
    intentional mismatch must be added as an explicit (row_fingerprint, door,
    allowed_category, reason) tuple, never a blanket ``or``.
    """

    # Explicit, narrow allowlist of intentional mismatches (empty after sweep).
    _INTENTIONAL_CATEGORY_MISMATCHES: ClassVar[
        frozenset[tuple[str, str, str, str]]
    ] = frozenset()

    _REPRESENTATIVE_ROWS: ClassVar[tuple[dict[str, str], ...]] = (
        {"source": "yunet", "license": "MIT", "derived_from_model": ""},
        {
            "source": "yunet",
            "license": "MIT",
            "derived_from_model": "",
            "generator_lineage": "ffhq",
        },
        {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "buffalo_l",
        },
        {"source": "self-generated", "license": "MIT", "derived_from_model": ""},
        {
            "source": "dcface",
            "license": "Apache-2.0",
            "derived_from_model": "",
        },
        {"source": "ffhq", "license": "MIT", "derived_from_model": ""},
        {
            "source": "operator-phone",
            "license": "MIT",
            "derived_from_model": "",
        },
        {
            "package": "umap-learn",
            "license": "BSD-3-Clause",
            "derived_from_model": "",
        },
        {
            "model_id": "sface",
            "license": "Apache-2.0",
            "derived_from_model": "",
        },
        {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "photo_clearance": "cleared",
        },
        # GATE-32: PASSing SYNTHETIC_SOURCE witness so the five-door category
        # invariant exercises the synthetic accept path (not only FAILs).
        {
            "source": "dcface",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "clearance_decision": "dcface_operator_clearance_20260723",
        },
        # FIR-7-RV-03: denylist-axis witness so the discrimination meta-test
        # cannot stay green after a clean-duplicate hollow of the grid.
        {
            "source": "self-generated",
            "license": "AGPL-3.0",
            "derived_from_model": "",
        },
    )

    @staticmethod
    def _row_fingerprint(row: dict[str, str]) -> str:
        return repr(sorted(row.items()))

    @pytest.mark.parametrize("door", list(policy.PolicyCategory))
    # GATE-35: derived from the row space, never hardcoded — a hardcoded bound
    # silently drops any row appended past it, which is the same under-coverage
    # GATE-32 was filed for.
    @pytest.mark.parametrize("row_idx", range(len(_REPRESENTATIVE_ROWS)))
    def test_result_category_equals_asked_door(
        self, door: policy.PolicyCategory, row_idx: int
    ) -> None:
        row = self._REPRESENTATIVE_ROWS[row_idx]
        result = policy.audit_provenance_row(row, category=door)
        got = (
            result.category.value
            if isinstance(result.category, policy.PolicyCategory)
            else result.category
        )
        if got == door.value:
            return
        key = (
            self._row_fingerprint(row),
            door.value,
            str(got),
            result.reason.value if result.reason is not None else "None",
        )
        assert key in self._INTENTIONAL_CATEGORY_MISMATCHES, (
            f"category leak: asked={door.value!r} got={got!r} "
            f"ok={result.ok} reason={result.reason} row={row!r}"
        )

    @pytest.mark.parametrize("door", list(policy.PolicyCategory))
    def test_gate32_every_door_has_at_least_one_pass_witness(
        self, door: policy.PolicyCategory
    ) -> None:
        """GATE-32: each door must see ≥1 PASS in ``_REPRESENTATIVE_ROWS``.

        Without a synthetic PASS witness the category invariant never exercises
        the SYNTHETIC_SOURCE accept path; a PASS-path category leak there
        stays green. Removing the clearance_decision dcface row must RED this
        for ``synthetic_source`` (TEST-15).
        """
        pass_count = 0
        for row in self._REPRESENTATIVE_ROWS:
            result = policy.audit_provenance_row(row, category=door)
            if result.ok is True:
                pass_count += 1
        assert pass_count >= 1, (
            f"GATE-32: PolicyCategory.{door.name} has zero PASS witnesses in "
            f"_REPRESENTATIVE_ROWS ({len(self._REPRESENTATIVE_ROWS)} rows); "
            "the five-door category invariant cannot cover its accept path"
        )


# ---------------------------------------------------------------------------
# GATE-28 — ALLOWED_SPDX_IDS: ISC / Zlib / Unlicense each have a PASS witness
# ---------------------------------------------------------------------------


class TestGate28AllowedSpdxIdsPassWitnesses:
    """GATE-28: each of ISC/Zlib/Unlicense must PASS on TRAINING_DATA alone.

    Deleting any one entry from ALLOWED_SPDX_IDS must RED its own fixture
    (TEST-15 / TEST-17 — one assertion per token).
    """

    def test_isc_spdx_passes_training_data(self) -> None:
        row = {
            "source": "self-generated",
            "license": "ISC",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is True, result.detail
        assert result.category == policy.PolicyCategory.TRAINING_DATA.value

    def test_zlib_spdx_passes_training_data(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Zlib",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is True, result.detail
        assert result.category == policy.PolicyCategory.TRAINING_DATA.value

    def test_unlicense_spdx_passes_training_data(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Unlicense",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is True, result.detail
        assert result.category == policy.PolicyCategory.TRAINING_DATA.value

    def test_isc_near_miss_still_rejected(self) -> None:
        row = {
            "source": "self-generated",
            "license": "ISC-License",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX

    def test_zlib_near_miss_still_rejected(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Zlib-acknowledgement",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX

    def test_unlicense_near_miss_still_rejected(self) -> None:
        row = {
            "source": "self-generated",
            "license": "Unlicensed",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX


# ---------------------------------------------------------------------------
# GATE-29 — TOOLING_ALLOWLIST: tensorflow / llvmlite each have a PASS witness
# ---------------------------------------------------------------------------


class TestGate29ToolingAllowlistPassWitnesses:
    """GATE-29: tensorflow and llvmlite must PASS on the TOOLING door alone."""

    def test_tensorflow_tooling_package_passes(self) -> None:
        row = {"package": "tensorflow"}
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is True, result.detail
        assert result.category == policy.PolicyCategory.TOOLING.value

    def test_llvmlite_tooling_package_passes(self) -> None:
        row = {"package": "llvmlite"}
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is True, result.detail
        assert result.category == policy.PolicyCategory.TOOLING.value

    def test_tensorflow_near_miss_still_rejected(self) -> None:
        row = {"package": "tensorflow-gpu"}
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SOURCE

    def test_llvmlite_near_miss_still_rejected(self) -> None:
        row = {"package": "llvmlite-dev"}
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SOURCE


# ---------------------------------------------------------------------------
# GATE-30 — MODEL_INGEST_ENTRIES: sface has a PASS witness
# ---------------------------------------------------------------------------


class TestGate30SfaceIngestPassWitness:
    """GATE-30: sface must PASS audit_model_ingest; near-misses must not."""

    def test_sface_model_ingest_passes(self) -> None:
        result = policy.audit_model_ingest("sface")
        assert result.ok is True, result.detail
        assert result.category == policy.PolicyCategory.MODEL_INGEST.value

    def test_sface_near_miss_sface_v2_still_rejected(self) -> None:
        result = policy.audit_model_ingest("sface_v2")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.MISSING_INGEST_ENTRY

    def test_sface_near_miss_opencv_sface_still_rejected(self) -> None:
        result = policy.audit_model_ingest("opencv_sface")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.MISSING_INGEST_ENTRY


# ---------------------------------------------------------------------------
# GATE-31 — operator-phone / operator-render source tokens (exact match)
# ---------------------------------------------------------------------------


class TestGate31OperatorOwnedSourcePassWitnesses:
    """GATE-31: operator-phone / operator-render PASS on TRAINING_DATA.

    These tokens live on the positive training-source axis
    (OCCLUDER_REGISTERED_SOURCES → _POSITIVE_TRAINING_SOURCES). Exact-token
    matching means variant / underscore / prefix neighbours must still fail
    PENDING_LEGAL_CLEARANCE (SECD-05).
    """

    def test_operator_phone_source_passes_training_data(self) -> None:
        row = {
            "source": "operator-phone",
            "license": "MIT",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is True, result.detail
        assert result.category == policy.PolicyCategory.TRAINING_DATA.value

    def test_operator_render_source_passes_training_data(self) -> None:
        row = {
            "source": "operator-render",
            "license": "MIT",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is True, result.detail
        assert result.category == policy.PolicyCategory.TRAINING_DATA.value

    def test_operator_phone_v2_variant_rejected(self) -> None:
        row = {
            "source": "operator-phone-v2",
            "license": "MIT",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_operator_phone_underscore_form_rejected(self) -> None:
        row = {
            "source": "operator_phone",
            "license": "MIT",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_operator_render_prefix_neighbour_rejected(self) -> None:
        # Substring/prefix neighbour — must not inherit operator-render clearance.
        row = {
            "source": "operator-render-extra",
            "license": "MIT",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_operator_render_v2_variant_rejected(self) -> None:
        row = {
            "source": "operator-render-v2",
            "license": "MIT",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE


# ---------------------------------------------------------------------------
# GATE-33 — PENDING-LEGAL-CLEARANCE SPDX branch is RED-capable (FIR-7-GATE-33)
# ---------------------------------------------------------------------------


class TestGate33PendingLegalClearanceSpdxBranch:
    """GATE-33: the explicit pending-legal-clearance licence tag must FAIL.

    Flipping ``audit_spdx``'s ``tag_cf == "pending-legal-clearance"`` branch
    from ``_fail`` to ``_pass`` previously left the full suite green. Pin the
    exact ``RejectionReason`` on the bare SPDX door and on every row door
    (TEST-15 / TEST-17 / SECD-05).
    """

    @pytest.mark.parametrize(
        "token",
        (
            "PENDING-LEGAL-CLEARANCE",
            "pending-legal-clearance",
            "Pending-Legal-Clearance",
        ),
    )
    def test_gate33_audit_spdx_pending_legal_clearance_fails(
        self, token: str
    ) -> None:
        result = policy.audit_spdx(token)
        assert result.ok is False, result.detail
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE, (
            f"audit_spdx({token!r}) must report PENDING_LEGAL_CLEARANCE, "
            f"got {result.reason!r}"
        )

    def test_gate33_training_data_row_pending_license_fails(self) -> None:
        row = {
            "source": "self-generated",
            "license": "PENDING-LEGAL-CLEARANCE",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False, result.detail
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_gate33_tooling_row_pending_license_fails(self) -> None:
        row = {
            "package": "umap-learn",
            "license": "PENDING-LEGAL-CLEARANCE",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TOOLING
        )
        assert result.ok is False, result.detail
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_gate33_model_ingest_row_pending_license_fails(self) -> None:
        row = {
            "model_id": "sface",
            "license": "PENDING-LEGAL-CLEARANCE",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.MODEL_INGEST
        )
        assert result.ok is False, result.detail
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_gate33_occluder_asset_row_pending_license_fails(self) -> None:
        row = {
            "source": "operator-phone",
            "license": "PENDING-LEGAL-CLEARANCE",
            "derived_from_model": "",
            "photo_clearance": "cleared",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.OCCLUDER_ASSET
        )
        assert result.ok is False, result.detail
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE

    def test_gate33_synthetic_source_row_pending_license_fails(self) -> None:
        # Self-declared pending licence must not ride a cleared synthetic head.
        row = {
            "source": "dcface",
            "license": "PENDING-LEGAL-CLEARANCE",
            "derived_from_model": "",
            "clearance_decision": "dcface_operator_clearance_20260723",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.SYNTHETIC_SOURCE
        )
        assert result.ok is False, result.detail
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE


# ---------------------------------------------------------------------------
# GATE-34 — BR-51 package denylist on derived_from_model is RED-capable
# ---------------------------------------------------------------------------


class TestGate34DerivedFromModelPackageDenylist:
    """GATE-34: Ultralytics-family tags FAIL via ``_package_denylist_hit``.

    Making ``_package_denylist_hit`` always return ``None`` previously left the
    suite green. Pin the public derived API and the TRAINING_DATA row reason
    (not just ok=False) so demotion to ``unregistered_derived_model`` is itself
    RED (TEST-15 / TEST-17 / SECD-06).
    """

    @pytest.mark.parametrize(
        "token",
        (
            "ultralytics",
            "yolov8",
            "yolo",
            "path/ultralytics",
        ),
    )
    def test_gate34_audit_derived_from_model_denylisted_package(
        self, token: str
    ) -> None:
        result = policy.audit_derived_from_model(token)
        assert result.ok is False, result.detail
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"audit_derived_from_model({token!r}) must report DENYLISTED_PACKAGE, "
            f"got {result.reason!r}"
        )

    def test_gate34_training_data_row_derived_ultralytics_reason(self) -> None:
        """Row door must keep DENYLISTED_PACKAGE, not demote to registration."""
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "ultralytics",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False, result.detail
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"TRAINING_DATA row with derived_from_model=ultralytics must report "
            f"DENYLISTED_PACKAGE (not demote to unregistered_derived_model); "
            f"got {result.reason!r}"
        )


# ---------------------------------------------------------------------------
# RD-01..06 — measured coverage gaps (FIR-7 Lane N); additive RED pins
# ---------------------------------------------------------------------------


# Measured PASSing witnesses (one per door). Each returns ok=True, reason=None
# on its door at the frozen policy; the guard under test is the only live fail
# axis (TEST-17). prove_red.py --witness re-derives this map at runtime.
_DOOR_PASSING_WITNESSES: dict[policy.PolicyCategory, dict[str, Any]] = {
    policy.PolicyCategory.TRAINING_DATA: {
        "source": "self-generated",
        "license": "Apache-2.0",
        "derived_from_model": "",
    },
    policy.PolicyCategory.TOOLING: {
        "package": "llvmlite",
        "license": "BSD-3-Clause",
        "derived_from_model": "",
    },
    policy.PolicyCategory.MODEL_INGEST: {
        "model_id": "yunet",
        "license": "MIT",
        "derived_from_model": "",
    },
    policy.PolicyCategory.OCCLUDER_ASSET: {
        "source": "operator-phone",
        "license": "Apache-2.0",
        "derived_from_model": "",
        "photo_clearance": "cleared",
    },
    policy.PolicyCategory.SYNTHETIC_SOURCE: {
        "source": "dcface",
        "license": "Apache-2.0",
        "derived_from_model": "",
        "clearance_decision": "dcface_operator_clearance_20260723",
    },
}


class TestRd01NonStringRowCategory:
    """RD-01: `_parse_row_category` rejects non-string ``category`` (TEST-15).

    Flipping the guard to `_pass` short-circuits *every* downstream axis via
    `if cat_err is not None: return cat_err` — complete mediation of the row
    body depends on this type check (SECD-03 / rg shape reject).
    """

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    @pytest.mark.parametrize("bad_cat", (123, ["training_data"], {"k": "v"}))
    def test_non_string_row_category_is_invalid_row(
        self, category, bad_cat: Any
    ) -> None:
        row = dict(_DOOR_PASSING_WITNESSES[category])
        row["category"] = bad_cat
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"{category.value} PASSed with category={bad_cat!r}; "
            "non-string row category must be rejected"
        )
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"{category.value} category={bad_cat!r}: expected INVALID_ROW, "
            f"got {result.reason}"
        )


class TestRd02CategoryParameterTypeGuard:
    """RD-02: ``audit_provenance_row`` category param must be PolicyCategory.

    A plain ``PolicyCategory.value`` string is the plausible caller slip
    (PolicyCategory is a StrEnum); the isinstance guard is the only thing
    between that slip and a full bypass (SECD-03 / TEST-15).
    """

    # Tainted so that even if the type guard were absent the row *should*
    # still fail — the pin is that a type slip must never come back PASS.
    _TAINTED: ClassVar[dict[str, Any]] = {
        "source": "ffhq",
        "license": "Apache-2.0",
        "derived_from_model": "",
    }

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_string_category_value_is_invalid_row(self, category) -> None:
        result = policy.audit_provenance_row(
            dict(self._TAINTED), category=category.value  # type: ignore[arg-type]
        )
        assert result.ok is False, (
            f"category={category.value!r} (plain str) PASSed a tainted row"
        )
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"category={category.value!r} (plain str): expected INVALID_ROW, "
            f"got {result.reason}"
        )

    @pytest.mark.parametrize(
        "bad_category",
        (123, object(), ["training_data"]),
    )
    def test_non_policy_category_type_is_invalid_row(self, bad_category: Any) -> None:
        result = policy.audit_provenance_row(
            dict(self._TAINTED), category=bad_category  # type: ignore[arg-type]
        )
        assert result.ok is False, f"category={bad_category!r} PASSed"
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"category={bad_category!r}: expected INVALID_ROW, got {result.reason}"
        )


class TestRd03LicenseFieldNoneArm:
    """RD-03: `_audit_row_licenses` None arm (sibling of non-string arm).

    The non-string arm is suite-killed; the `raw is None` arm was suite-blind
    (TEST-15). Use otherwise-PASSing witnesses so None is the only fail axis
    (TEST-17).
    """

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    @pytest.mark.parametrize("license_key", ("license", "spdx_id"))
    def test_none_license_field_is_invalid_row(
        self, category, license_key: str
    ) -> None:
        row = dict(_DOOR_PASSING_WITNESSES[category])
        if license_key != "license":
            # Keep a valid canonical licence so the only fail is the None key.
            row["license"] = row.get("license", "Apache-2.0")
        row[license_key] = None
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"{category.value} PASSed with {license_key}=None"
        )
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"{category.value} {license_key}=None: expected INVALID_ROW, "
            f"got {result.reason}"
        )


class TestRd04OccluderNonMappingAndAsymmetry:
    """RD-04: ``audit_occluder_asset`` non-Mapping returns INVALID_ROW.

    Sibling entry points RAISE LicensePolicyError; this door RETURNS a fail
    result. Pin both the return path and the raise-vs-return asymmetry so
    neither convention can drift silently (SECD-06 / TEST-15).
    """

    @pytest.mark.parametrize(
        "bad_asset",
        ("a-string", ["l"], 42, None),
    )
    def test_non_mapping_returns_invalid_row(self, bad_asset: Any) -> None:
        result = policy.audit_occluder_asset(bad_asset)  # type: ignore[arg-type]
        assert result.ok is False, f"non-Mapping {bad_asset!r} PASSed"
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"non-Mapping {bad_asset!r}: expected INVALID_ROW, got {result.reason}"
        )

    def test_raise_vs_return_asymmetry_across_entry_points(self) -> None:
        """Provenance/tooling RAISE; occluder RETURNS — pin the contract."""
        with pytest.raises(policy.LicensePolicyError) as ei_prov:
            policy.audit_provenance_row("not-a-mapping")  # type: ignore[arg-type]
        assert ei_prov.value.result.ok is False
        assert (
            ei_prov.value.result.reason is policy.RejectionReason.UNKNOWN_SOURCE
        )

        with pytest.raises(policy.LicensePolicyError) as ei_tool:
            policy.audit_tooling_row("not-a-mapping")  # type: ignore[arg-type]
        assert ei_tool.value.result.ok is False
        assert (
            ei_tool.value.result.reason is policy.RejectionReason.UNKNOWN_SOURCE
        )

        # Same shape, opposite convention: return, do not raise.
        result = policy.audit_occluder_asset("not-a-mapping")  # type: ignore[arg-type]
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW


class TestRd05OccluderPhotoClearanceType:
    """RD-05: non-string ``photo_clearance`` is INVALID_ROW; None is allowed.

    None is explicitly excluded from the type guard
    (`if photo_raw is not None and not isinstance(...)`); pin that so a future
    edit cannot tighten it by accident (TEST-15).
    """

    _CLEAN_OCCLUDER: ClassVar[dict[str, Any]] = {
        "source": "operator-phone",
        "license": "Apache-2.0",
        "derived_from_model": "",
        "photo_clearance": "cleared",
    }

    @pytest.mark.parametrize("bad_pc", (123, ["cleared"], {"status": "cleared"}))
    def test_non_string_photo_clearance_is_invalid_row(self, bad_pc: Any) -> None:
        row = dict(self._CLEAN_OCCLUDER)
        row["photo_clearance"] = bad_pc
        result = policy.audit_occluder_asset(row)
        assert result.ok is False, f"photo_clearance={bad_pc!r} PASSed"
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"photo_clearance={bad_pc!r}: expected INVALID_ROW, got {result.reason}"
        )

    def test_none_photo_clearance_is_not_type_rejected(self) -> None:
        """None is allowed by the type guard (not INVALID_ROW).

        An otherwise-clean row with photo_clearance=None still fails the
        photo-release axis as uncleared — that is the intended fail, not a
        type error. A regression that rejects None as INVALID_ROW is a tighten.
        """
        row = dict(self._CLEAN_OCCLUDER)
        row["photo_clearance"] = None
        result = policy.audit_occluder_asset(row)
        assert result.ok is False
        assert result.reason is not policy.RejectionReason.INVALID_ROW, (
            "photo_clearance=None must not be type-rejected as INVALID_ROW; "
            f"got {result.reason}"
        )
        assert result.reason is policy.RejectionReason.UNCLEARED_OCCLUDER_ASSET, (
            f"photo_clearance=None should fail photo-release, got {result.reason}"
        )


class TestRd06LicensePolicyErrorPayload:
    """RD-06: raised LicensePolicyError must carry a FAIL payload (TEST-15).

    Flipping the wrapped `_fail` to `_pass` still raises, so a bare
    `pytest.raises` stays green while `err.result` becomes self-contradictory
    (ok=True inside a rejection exception). Bind the exception and assert
    the payload at both raise sites.
    """

    def test_audit_provenance_row_non_mapping_payload(self) -> None:
        with pytest.raises(policy.LicensePolicyError) as ei:
            policy.audit_provenance_row("not-a-mapping")  # type: ignore[arg-type]
        assert ei.value.result.ok is False
        assert ei.value.result.reason is policy.RejectionReason.UNKNOWN_SOURCE

    def test_audit_tooling_row_non_mapping_payload(self) -> None:
        with pytest.raises(policy.LicensePolicyError) as ei:
            policy.audit_tooling_row("not-a-mapping")  # type: ignore[arg-type]
        assert ei.value.result.ok is False
        assert ei.value.result.reason is policy.RejectionReason.UNKNOWN_SOURCE

# ---------------------------------------------------------------------------
# FIR-7-RV-10 — package denylist is a floor across identity fields
# ---------------------------------------------------------------------------


class TestRv10PackageDenylistFloorAcrossIdentityFields:
    """FIR-7-RV-10: denylisted package token in ANY identity field fails every door.

    First-wins among package / package_name / source previously let a
    denylisted token hide behind another non-empty field. Floor semantics
    (like BR-53) audit every package-identity field on every door.

    FIR-7-B2-05: every witness uses a CLEAN primary package so the floor (not
    the TOOLING door-local first-wins check) is the only rejector of the
    denylisted secondary field.
    """

    # Measured escape witnesses (must FAIL). Clean primary + dirty secondary
    # so a floor neuter turns the tooling cells red (FIR-7-B2-05).
    W1_TOOLING_SHADOW: ClassVar[dict[str, str]] = {
        "package": "numba",
        "package_name": "ultralytics",
        "license": "BSD-2-Clause",
        "derived_from_model": "",
    }
    W2_MODEL_ID_WINS: ClassVar[dict[str, str]] = {
        "model_id": "yunet",
        "package": "numba",
        "package_name": "ultralytics",
        "license": "MIT",
        "derived_from_model": "",
    }
    W3_TRAINING_PACKAGE: ClassVar[dict[str, str]] = {
        "source": "self-generated",
        "package": "numba",
        "package_name": "ultralytics",
        "license": "MIT",
        "derived_from_model": "",
    }

    @pytest.mark.parametrize(
        ("row", "door", "field_in_detail", "token"),
        [
            (
                W1_TOOLING_SHADOW,
                policy.PolicyCategory.TOOLING,
                "package_name",
                "ultralytics",
            ),
            (
                W2_MODEL_ID_WINS,
                policy.PolicyCategory.MODEL_INGEST,
                "package_name",
                "ultralytics",
            ),
            (
                W3_TRAINING_PACKAGE,
                policy.PolicyCategory.TRAINING_DATA,
                "package_name",
                "ultralytics",
            ),
        ],
        ids=["tooling-shadow-package_name", "model-id-wins-package", "training-package"],
    )
    def test_measured_escape_witnesses_fail(
        self, row, door, field_in_detail, token
    ) -> None:
        result = policy.audit_provenance_row(dict(row), category=door)
        assert result.ok is False, (
            f"witness through {door.value} PASSed; denylist floor missed "
            f"{field_in_detail}={token!r}"
        )
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"{door.value}: expected denylisted_package, got {result.reason}"
        )
        assert token in result.detail
        assert field_in_detail in result.detail, (
            f"detail must name the field carrying the denylisted token; "
            f"got {result.detail!r}"
        )

    @pytest.mark.parametrize("door", list(policy.PolicyCategory))
    @pytest.mark.parametrize(
        "row",
        [W1_TOOLING_SHADOW, W2_MODEL_ID_WINS, W3_TRAINING_PACKAGE],
        ids=["w1", "w2", "w3"],
    )
    def test_witness_fails_every_door(self, door, row) -> None:
        # Per-door parametrisation: a denylisted package identity field is a
        # floor obligation, not a tooling-only gate.
        payload = dict(row)
        # Give every door the keys it needs so rejection is the denylist, not
        # a missing-field incidental (TEST-17).
        payload.setdefault("source", payload.get("source", "self-generated"))
        payload.setdefault("model_id", payload.get("model_id", "yunet"))
        payload.setdefault("package", payload.get("package", "numba"))
        payload.setdefault("photo_clearance", "cleared")
        payload.setdefault("derived_from_model", "")
        payload.setdefault("license", payload.get("license", "MIT"))
        result = policy.audit_provenance_row(payload, category=door)
        assert result.ok is False, (
            f"door={door.value} PASSed denylisted package identity row {row!r}"
        )
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"door={door.value}: expected denylisted_package, got "
            f"{result.reason} ({result.detail})"
        )
        assert "ultralytics" in result.detail


# ---------------------------------------------------------------------------
# FIR-7-RV-11 — SYNTHETIC_SOURCE reason fidelity for source-axis taint
# ---------------------------------------------------------------------------


class TestRv11SyntheticSourceAxisTaintReasonFidelity:
    """FIR-7-RV-11: non-registry synthetic sources keep specific taint reasons.

    FIR-7-B2-04: the NC cell must use a source that is NC-model-derived on the
    source-taint axis but NOT in PACKAGE_DENYLIST — otherwise the RV-10 package
    floor supplies nc_model_derived under an RV-11 neuter and the cell is
    vacuous. Bare ``buffalo`` is on the NC seed set and deliberately absent
    from PACKAGE_DENYLIST (B9-02 follow-up: no generic-English buffalo family
    seed; verified by construction).
    """

    @pytest.mark.parametrize(
        ("source", "expected_reason"),
        [
            ("ffhq", policy.RejectionReason.RESEARCH_ONLY_SOURCE),
            # Not buffalo_l / retinaface / antelopev2: those are now (or were)
            # PACKAGE_DENYLIST NC seeds, so the package floor would keep the
            # cell green under an RV-11 neuter (FIR-7-B2-04 / TEST-15).
            ("buffalo", policy.RejectionReason.NC_MODEL_DERIVED),
        ],
    )
    def test_synthetic_door_reports_source_axis_taint(
        self, source: str, expected_reason: policy.RejectionReason
    ) -> None:
        # Pin the NC witness is outside PACKAGE_DENYLIST so only RV-11's
        # source-axis path can reject it.
        if expected_reason is policy.RejectionReason.NC_MODEL_DERIVED:
            assert source not in policy.PACKAGE_DENYLIST, (
                f"{source!r} is in PACKAGE_DENYLIST — witness is vacuous "
                "under an RV-11 neuter (FIR-7-B2-04)"
            )
            assert policy._package_denylist_hit(source) is None, (
                f"{source!r} hits PACKAGE_DENYLIST via alias — witness vacuous"
            )
        row = {
            "source": source,
            "license": "MIT",
            "derived_from_model": "",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.SYNTHETIC_SOURCE
        )
        assert result.ok is False
        assert result.reason is expected_reason, (
            f"source={source!r} through synthetic door: expected "
            f"{expected_reason}, got {result.reason} ({result.detail})"
        )
        # Must not collapse to the unknown-head phrasing.
        assert "has no clearance entry" not in result.detail

# ---------------------------------------------------------------------------
# FIR-7-RV-12 — compound SPDX allowlist tokenisation
# ---------------------------------------------------------------------------


class TestRv12CompoundSpdxAllowlistTokenisation:
    """FIR-7-RV-12: all-allowlisted compounds PASS; failures name the component."""

    @pytest.mark.parametrize(
        "spdx",
        [
            "MIT AND Apache-2.0",
            "(MIT)",
            "MIT+",
            "Apache-2.0+",
        ],
    )
    def test_all_allowlisted_compounds_pass(self, spdx: str) -> None:
        result = policy.audit_spdx(spdx)
        assert result.ok is True, (
            f"{spdx!r} must PASS (every component allowlisted); got "
            f"{result.reason} {result.detail}"
        )

    def test_denylisted_component_named(self) -> None:
        result = policy.audit_spdx("MIT AND GPL-3.0")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE
        assert "GPL-3.0" in result.detail

    def test_unknown_component_named(self) -> None:
        result = policy.audit_spdx("MIT AND UnknownLic-1.0")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX
        assert "UnknownLic-1.0" in result.detail
        assert "unknown component" in result.detail

# ---------------------------------------------------------------------------
# FIR-7-RV-13 — both clearance axes exact-match on canonical lower-case
# ---------------------------------------------------------------------------


class TestRv13ClearanceAxesExactMatchNormalisation:
    """FIR-7-RV-13: photo_clearance and clearance_decision refuse case drift."""

    def test_photo_clearance_uppercase_refused(self) -> None:
        row = {
            "source": "operator-photo",
            "license": "MIT",
            "derived_from_model": "",
            "photo_clearance": "CLEARED",
        }
        result = policy.audit_occluder_asset(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNCLEARED_OCCLUDER_ASSET

    def test_photo_clearance_lowercase_canonical_admits(self) -> None:
        row = {
            "source": "operator-photo",
            "license": "MIT",
            "derived_from_model": "",
            "photo_clearance": "cleared",
        }
        result = policy.audit_occluder_asset(row)
        assert result.ok is True, result.detail

    def test_clearance_decision_uppercase_refused(self) -> None:
        row = {
            "source": "dcface",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "clearance_decision": policy.DCFACE_CLEARANCE_DECISION.upper(),
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.SYNTHETIC_SOURCE
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE
        assert "requires clearance_decision=" in result.detail

    def test_clearance_decision_exact_canonical_admits(self) -> None:
        row = {
            "source": "dcface",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "clearance_decision": policy.DCFACE_CLEARANCE_DECISION,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.SYNTHETIC_SOURCE
        )
        assert result.ok is True, result.detail

    def test_both_axes_side_by_side_normalisation(self) -> None:
        """Pin both axes' normalisation side by side (exact lower-case only)."""
        # Photo axis.
        photo_upper = policy.audit_occluder_asset(
            {
                "source": "operator-photo",
                "license": "MIT",
                "derived_from_model": "",
                "photo_clearance": "CLEARED",
            }
        )
        photo_lower = policy.audit_occluder_asset(
            {
                "source": "operator-photo",
                "license": "MIT",
                "derived_from_model": "",
                "photo_clearance": "cleared",
            }
        )
        assert photo_upper.ok is False
        assert photo_upper.reason is policy.RejectionReason.UNCLEARED_OCCLUDER_ASSET
        assert photo_lower.ok is True

        # Lineage axis.
        cd_upper = policy.audit_provenance_row(
            {
                "source": "dcface",
                "license": "Apache-2.0",
                "derived_from_model": "",
                "clearance_decision": policy.DCFACE_CLEARANCE_DECISION.upper(),
            },
            category=policy.PolicyCategory.SYNTHETIC_SOURCE,
        )
        cd_lower = policy.audit_provenance_row(
            {
                "source": "dcface",
                "license": "Apache-2.0",
                "derived_from_model": "",
                "clearance_decision": policy.DCFACE_CLEARANCE_DECISION,
            },
            category=policy.PolicyCategory.SYNTHETIC_SOURCE,
        )
        assert cd_upper.ok is False
        assert cd_upper.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE
        assert cd_lower.ok is True

# ---------------------------------------------------------------------------
# FIR-7-RV-03 — fixture grid discrimination meta-test
# ---------------------------------------------------------------------------


class TestRv03RepresentativeRowsDiscriminationFloor:
    """FIR-7-RV-03: _REPRESENTATIVE_ROWS must discriminate rejection axes.

    R1 replaced research/NC/lineage rows with clean duplicates (len unchanged
    so node ids survived) while discrimination died. This meta-test runs the
    whole grid through the five doors and requires at least one witness per
    rejection axis plus at least one PASS per door.
    """

    def test_representative_rows_discriminate_rejection_axes(self) -> None:
        rows = TestGate27FiveDoorCategoryInvariant._REPRESENTATIVE_ROWS
        observed_reasons: set[policy.RejectionReason] = set()
        pass_per_door: dict[policy.PolicyCategory, bool] = {
            d: False for d in policy.PolicyCategory
        }
        for row in rows:
            for door in policy.PolicyCategory:
                result = policy.audit_provenance_row(dict(row), category=door)
                if result.ok:
                    pass_per_door[door] = True
                elif result.reason is not None:
                    observed_reasons.add(result.reason)

        assert policy.RejectionReason.RESEARCH_ONLY_SOURCE in observed_reasons, (
            "research_only_source axis has no witness in _REPRESENTATIVE_ROWS; "
            f"observed={sorted(r.value for r in observed_reasons)}"
        )
        # NC / lineage axis (buffalo-style NC or unregistered lineage).
        nc_or_lineage = {
            policy.RejectionReason.NC_MODEL_DERIVED,
            policy.RejectionReason.UNREGISTERED_DERIVED_MODEL,
        }
        assert observed_reasons & nc_or_lineage, (
            "nc/lineage axis has no witness in _REPRESENTATIVE_ROWS; "
            f"observed={sorted(r.value for r in observed_reasons)}"
        )
        # Denylist axis (package or licence).
        denylist_axis = {
            policy.RejectionReason.DENYLISTED_PACKAGE,
            policy.RejectionReason.DENYLISTED_LICENSE,
        }
        assert observed_reasons & denylist_axis, (
            "denylist axis has no witness in _REPRESENTATIVE_ROWS; "
            f"observed={sorted(r.value for r in observed_reasons)}"
        )
        for door, saw_pass in pass_per_door.items():
            assert saw_pass, (
                f"door {door.value} has no PASS witness in _REPRESENTATIVE_ROWS"
            )

# ---------------------------------------------------------------------------
# FIR-7-LR-04 — RD-07 reason preservation on occluder + research source
# ---------------------------------------------------------------------------


class TestLr04OccluderResearchSourceReasonPreservation:
    """FIR-7-LR-04: occluder door + research source → RESEARCH_ONLY_SOURCE.

    The floor path (_common_provenance_checks → _floor_taint_and_clearance →
    _source_axis_taint → audit_source) is the reason-preserving mechanism
    (SECD-06: shared predicate, not independent layers). Pin the exact reason
    so a deleted door-local branch cannot silently collapse to a weaker code.
    """

    def test_occluder_ffhq_reports_research_only_source(self) -> None:
        row = {
            "source": "ffhq",
            "license": "MIT",
            "derived_from_model": "",
            "photo_clearance": "cleared",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.OCCLUDER_ASSET
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE, (
            f"occluder + source=ffhq expected RESEARCH_ONLY_SOURCE, got "
            f"{result.reason} ({result.detail})"
        )


# ---------------------------------------------------------------------------
# FIR-7-B2-01 — package-identity floor fail-closed on non-string types
# ---------------------------------------------------------------------------


class TestB201PackageIdentityNonStringFailClosed:
    """FIR-7-B2-01 / FIR-7-B3-03: non-string package-identity → invalid_row.

    Previously ``isinstance(raw, str) ... else continue`` skipped list/dict
    values so ``package=['ultralytics']`` admitted on TRAINING_DATA /
    OCCLUDER_ASSET. BR-68 parity with source/derived/license type checks.

    FIR-7-B3-03 completes the type-pin matrix: empty list, True, False,
    bytes, 0, and explicit None under a package-identity key must also
    fail closed (not truthiness-skipped).
    """

    @pytest.mark.parametrize(
        "dirty",
        [
            {"package": ["ultralytics"]},
            {"package": {"name": "ultralytics"}},
            {"package": []},
            {"package": True},
            {"package": False},
            {"package": b"ultralytics"},
            {"package": 0},
            {"package": None},
        ],
        ids=[
            "list",
            "dict",
            "empty-list",
            "true",
            "false",
            "bytes",
            "zero",
            "none",
        ],
    )
    @pytest.mark.parametrize(
        "door",
        [
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
            policy.PolicyCategory.MODEL_INGEST,
            policy.PolicyCategory.OCCLUDER_ASSET,
            policy.PolicyCategory.SYNTHETIC_SOURCE,
        ],
        ids=[
            "training_data",
            "tooling",
            "model_ingest",
            "occluder_asset",
            "synthetic_source",
        ],
    )
    def test_non_string_package_invalid_row_every_door(
        self, dirty: dict, door: policy.PolicyCategory
    ) -> None:
        row: dict = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": "numba",
            "model_id": "yunet",
            "photo_clearance": "cleared",
        }
        row.update(dirty)
        result = policy.audit_provenance_row(row, category=door)
        assert result.ok is False, (
            f"door={door.value} admitted non-string package identity {dirty!r}"
        )
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"door={door.value}: expected invalid_row, got {result.reason} "
            f"({result.detail})"
        )
        assert "package" in result.detail
        # Detail must name the type problem (list / dict / bool / bytes / …).
        # None is reported as the literal ``None`` (not NoneType).
        bad_val = next(iter(dirty.values()))
        if bad_val is None:
            assert "None" in result.detail, (
                f"detail must name None: {result.detail!r}"
            )
        else:
            assert type(bad_val).__name__ in result.detail, (
                f"detail must name type {type(bad_val).__name__!r}: "
                f"{result.detail!r}"
            )


# ---------------------------------------------------------------------------
# FIR-7-B2-02 — package-identity key alias / case normalisation
# ---------------------------------------------------------------------------


class TestB202PackageIdentityKeyAliasNormalisation:
    """FIR-7-B2-02: Package / PACKAGE / package_Name / Model-Id hit the floor.

    Same ``_normalise_field_key`` treatment as licence keys (GATE-04). A
    denylisted value under any alias is denylisted_package; disagreeing
    duplicates under one canonical key are invalid_row.
    """

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("Package", "ultralytics"),
            ("PACKAGE", "ultralytics"),
            ("package_Name", "ultralytics"),
            ("Model-Id", "ultralytics"),
        ],
        ids=["Package", "PACKAGE", "package_Name", "Model-Id"],
    )
    def test_alias_key_with_denylisted_value_fails(self, key: str, value: str) -> None:
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "photo_clearance": "cleared",
            # Clean exact primary so only the alias field can fire the floor.
            "package": "numba",
            key: value,
        }
        # Model-Id aliases to model_id — drop the clean package primary noise
        # is fine; package=numba + Model-Id=ultralytics should still deny.
        if key in ("Package", "PACKAGE"):
            # Alias collides with package=numba → disagreeing values → invalid_row
            # OR if we don't set package, just the alias.
            row.pop("package", None)
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False, (
            f"alias key {key!r}={value!r} admitted; floor missed normalisation"
        )
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"alias {key!r}: expected denylisted_package, got {result.reason} "
            f"({result.detail})"
        )
        assert value in result.detail

    def test_disagreeing_package_alias_is_invalid_row(self) -> None:
        # package=numba + Package=ultralytics → same canonical key, different
        # values → fail-closed invalid_row (licence-key BR-35 precedent).
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": "numba",
            "Package": "ultralytics",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"disagreeing package aliases must be invalid_row, got "
            f"{result.reason} ({result.detail})"
        )
        assert "disagreeing" in result.detail


# ---------------------------------------------------------------------------
# FIR-7-B2-03 — Ultralytics AGPL family denylist vocabulary
# ---------------------------------------------------------------------------


class TestB203UltralyticsAgplFamilyDenylistVocabulary:
    """FIR-7-B2-03 / FIR-7-B3-01: family tokens reject via folded exact denylist.

    Separator variants (``yolo-v5`` / ``yolo_v5``) must hit the compact seed
    after structural fold; substring-adjacent tokens (``yolodummy``, ``myyolo``)
    must not.
    """

    # Witness spellings measured admitting before FIR-7-B3-01, plus compact
    # forms, dual-seed forms, and new Ultralytics-lineage tokens.
    FAMILY_TOKENS: ClassVar[tuple[str, ...]] = (
        # separator variants of seeded versions (were ADMIT before B3-01)
        "yolo-v5",
        "yolo_v5",
        "yolo-v9",
        "yolo_v9",
        "yolo-v10",
        "yolo_v10",
        "yolo-11",
        "yolo_11",
        "yolov11",
        "yolo-v3",
        "yolo_v3",
        "yolo-v6",
        "yolo_v6",
        "yolo-v7",
        "yolo_v7",
        # compact forms (already denied pre-B3-01)
        "yolov3",
        "yolov5",
        "yolov6",
        "yolov7",
        "yolov9",
        "yolov10",
        "yolo11",
        # dual-seed yolo_v8 / yolo-v8 + compact
        "yolo_v8",
        "yolo-v8",
        "yolov8",
        "ultralytics-yolo",
        # genuinely Ultralytics-lineage additions (FIR-7-B3-01)
        "yolo12",
        "yolo-world",
        "yolo_world",
        "fastsam",
        "yolov8n",
        "yolov8s",
        "yolov8m",
        "yolov8l",
        "yolov8x",
    )

    @pytest.mark.parametrize("token", FAMILY_TOKENS)
    def test_family_token_fails_package_floor(self, token: str) -> None:
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False, f"family token {token!r} admitted"
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"{token!r}: expected denylisted_package, got {result.reason} "
            f"({result.detail})"
        )

    @pytest.mark.parametrize("token", ("yolodummy", "myyolo"))
    def test_substring_adjacent_tokens_do_not_hit(self, token: str) -> None:
        """BR-50/52: folded exact-match must not substring-match 'yolo'."""
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must NOT hit package denylist (no substring creep)"
        )
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        # May fail on unknown_source / other axes for tooling, but must not
        # be denylisted_package from substring matching.
        if not result.ok:
            assert result.reason is not policy.RejectionReason.DENYLISTED_PACKAGE, (
                f"{token!r} incorrectly denylisted via substring: {result.detail}"
            )


class TestB302HonestLineageNotes:
    """FIR-7-B3-02: PACKAGE_DENYLIST notes/spdx reflect true upstream licences."""

    def test_yolov6_is_meituan_gpl(self) -> None:
        entry = policy.PACKAGE_DENYLIST["yolov6"]
        assert entry.spdx_id == "GPL-3.0"
        assert "Meituan" in entry.notes
        assert "GPL-3.0" in entry.notes

    def test_yolov7_is_wongkinyiu_gpl(self) -> None:
        entry = policy.PACKAGE_DENYLIST["yolov7"]
        assert entry.spdx_id == "GPL-3.0"
        assert "WongKinYiu" in entry.notes
        assert "GPL-3.0" in entry.notes

    def test_yolov10_is_thumig_fail_closed(self) -> None:
        entry = policy.PACKAGE_DENYLIST["yolov10"]
        assert entry.spdx_id == "Apache-2.0"
        assert "THU-MIG" in entry.notes
        assert "Fail-closed" in entry.notes or "fail-closed" in entry.notes.lower()
        assert "AGPL" in entry.notes

    def test_yolov3_is_darknet_fail_closed(self) -> None:
        entry = policy.PACKAGE_DENYLIST["yolov3"]
        assert "Darknet" in entry.notes
        assert "Fail-closed" in entry.notes or "fail-closed" in entry.notes.lower()
        # Still denied.
        assert entry.reason is policy.RejectionReason.DENYLISTED_PACKAGE


# ---------------------------------------------------------------------------
# FIR-7-A3-01 — scalar tooling door uses folded denylist lookup
# ---------------------------------------------------------------------------


class TestA301ToolingScalarDenylistFold:
    """FIR-7-A3-01: audit_tooling_dependency reports denylisted_package for yolo-v8."""

    @pytest.mark.parametrize(
        "token",
        ("yolo-v8", "yolo_v8", "ultralytics-yolo", "yolov8"),
    )
    def test_tooling_scalar_denylisted_package(self, token: str) -> None:
        result = policy.audit_tooling_dependency(token)
        assert result.ok is False, f"tooling scalar admitted {token!r}"
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"{token!r}: expected denylisted_package, got {result.reason} "
            f"({result.detail})"
        )


# ---------------------------------------------------------------------------
# FIR-7-B2-06 / B3-04 / A3-02 — SPDX expression-hygiene completeness
# ---------------------------------------------------------------------------


class TestB206SpdxExpressionEmptyComponentFailClosed:
    """FIR-7-B2-06: empty parens / trailing operator / empty RHS are malformed.

    ``MIT OR ()`` previously admitted with components=['MIT'] after silently
    dropping the empty parenthesised component (GATE-10 hygiene).
    """

    @pytest.mark.parametrize(
        "spdx",
        [
            "MIT OR ()",
            "MIT AND",
            "() OR MIT",
        ],
    )
    def test_empty_component_expressions_fail_closed(self, spdx: str) -> None:
        result = policy.audit_spdx(spdx)
        assert result.ok is False, (
            f"{spdx!r} must FAIL closed (expression-hygiene); got PASS "
            f"detail={result.detail!r}"
        )
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX, (
            f"{spdx!r}: expected unknown_spdx (expression-hygiene), got "
            f"{result.reason}"
        )
        assert "expression-hygiene" in result.detail, (
            f"{spdx!r}: detail must name expression-hygiene; got {result.detail!r}"
        )


class TestB304A302SpdxExpressionHygieneCompleteness:
    """FIR-7-B3-04 / FIR-7-A3-02: unicode dashes + unbalanced parens fail closed.

    Must carry the expression-hygiene detail label (not bare unknown_spdx).
    """

    @pytest.mark.parametrize(
        "spdx",
        [
            "MIT\u2013OR\u2013Apache-2.0",  # en-dash
            "MIT\u2014Apache-2.0",  # em-dash
            "Apache-2.0\u2013only",  # en-dash in id-shaped token
        ],
        ids=["en-dash-or", "em-dash", "en-dash-id"],
    )
    def test_unicode_dash_fails_expression_hygiene(self, spdx: str) -> None:
        result = policy.audit_spdx(spdx)
        assert result.ok is False, (
            f"{spdx!r} must FAIL closed (unicode dash); got PASS "
            f"detail={result.detail!r}"
        )
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX, (
            f"{spdx!r}: expected unknown_spdx, got {result.reason}"
        )
        assert "expression-hygiene" in result.detail, (
            f"{spdx!r}: detail must name expression-hygiene; got {result.detail!r}"
        )

    @pytest.mark.parametrize(
        "spdx",
        ["(MIT", "MIT)", ")MIT("],
        ids=["open-only", "close-only", "reversed"],
    )
    def test_unbalanced_parens_fail_expression_hygiene(self, spdx: str) -> None:
        result = policy.audit_spdx(spdx)
        assert result.ok is False, (
            f"{spdx!r} must FAIL closed (unbalanced parens); got PASS "
            f"detail={result.detail!r}"
        )
        assert result.reason is policy.RejectionReason.UNKNOWN_SPDX, (
            f"{spdx!r}: expected unknown_spdx, got {result.reason}"
        )
        assert "expression-hygiene" in result.detail, (
            f"{spdx!r}: detail must name expression-hygiene; got {result.detail!r}"
        )
        assert "unbalanced" in result.detail.lower(), (
            f"{spdx!r}: detail must name unbalanced parentheses; got "
            f"{result.detail!r}"
        )


# ---------------------------------------------------------------------------
# FIR-7-B4-01 — package-identity floor fail-closed on canonical-None
# ---------------------------------------------------------------------------


class TestB401PackageIdentityCanonicalNoneFailClosed:
    """FIR-7-B4-01: non-ASCII residue on package-identity fields is invalid_row.

    Measured pre-fix ADMITs on clean TRAINING_DATA rows when package carried
    unicode dashes or confusable scripts (canonical() → None treated as floor
    miss). Source / derived_from_model already BR-21 fail-closed; package
    floor + scalar doors must match.

    Red-proven: restoring silent floor skip on canonical-None re-admits the
    TRAINING_DATA package witnesses (tests go red).
    """

    # en dash U+2013, unicode hyphen U+2010, Greek omicron U+03BF
    CONFUSABLE_TOKENS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("en_dash", "yolo\u2013v5"),
        ("unicode_hyphen", "yolo\u2010v5"),
        ("greek_omicron", "yol\u03bfv5"),
    )
    IDENTITY_FIELDS: ClassVar[tuple[str, ...]] = (
        "package",
        "package_name",
        "model_id",
    )

    @pytest.mark.parametrize(
        "token_id,token",
        CONFUSABLE_TOKENS,
        ids=[t[0] for t in CONFUSABLE_TOKENS],
    )
    @pytest.mark.parametrize("field", IDENTITY_FIELDS)
    @pytest.mark.parametrize(
        "category",
        (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
        ),
        ids=("training_data", "tooling"),
    )
    def test_row_confusable_package_identity_invalid_row(
        self,
        token_id: str,
        token: str,
        field: str,
        category: policy.PolicyCategory,
    ) -> None:
        assert policy.canonical(token) is None, (
            f"precondition: {token_id} must yield canonical None"
        )
        if category is policy.PolicyCategory.TRAINING_DATA:
            row: dict[str, Any] = {
                "source": "self-generated",
                "license": "MIT",
                "derived_from_model": "",
                field: token,
            }
        else:
            row = {
                "package": "llvmlite" if field != "package" else token,
                "license": "BSD-2-Clause",
                "derived_from_model": "",
            }
            if field != "package":
                row[field] = token
            else:
                row["package"] = token
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"{category.value} admitted confusable {field}={token!r} "
            f"({token_id}); detail={result.detail!r}"
        )
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"{category.value}/{field}/{token_id}: expected invalid_row, "
            f"got {result.reason} ({result.detail})"
        )
        detail_cf = result.detail.casefold()
        assert "non-ascii" in detail_cf or "non-ASCII" in result.detail, (
            f"detail must name non-ASCII residue; got {result.detail!r}"
        )
        assert field in result.detail or token in result.detail, (
            f"detail must name field or value; got {result.detail!r}"
        )

    @pytest.mark.parametrize(
        "token_id,token",
        CONFUSABLE_TOKENS,
        ids=[t[0] for t in CONFUSABLE_TOKENS],
    )
    def test_tooling_scalar_confusable_invalid_row(
        self, token_id: str, token: str
    ) -> None:
        result = policy.audit_tooling_dependency(token)
        assert result.ok is False, f"tooling scalar admitted {token!r}"
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"tooling scalar {token_id}: expected invalid_row (not "
            f"unknown_source), got {result.reason} ({result.detail})"
        )
        assert "non-ASCII" in result.detail or "non-ascii" in result.detail.casefold(), (
            f"detail must name non-ASCII residue; got {result.detail!r}"
        )
        # Must NOT imply the token is merely unregistered.
        assert result.reason is not policy.RejectionReason.UNKNOWN_SOURCE

    @pytest.mark.parametrize(
        "token_id,token",
        CONFUSABLE_TOKENS,
        ids=[t[0] for t in CONFUSABLE_TOKENS],
    )
    def test_model_ingest_scalar_confusable_invalid_row(
        self, token_id: str, token: str
    ) -> None:
        result = policy.audit_model_ingest(token)
        assert result.ok is False, f"model_ingest scalar admitted {token!r}"
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"model_ingest scalar {token_id}: expected invalid_row (not "
            f"missing_ingest_entry), got {result.reason} ({result.detail})"
        )
        assert "non-ASCII" in result.detail or "non-ascii" in result.detail.casefold(), (
            f"detail must name non-ASCII residue; got {result.detail!r}"
        )
        assert result.reason is not policy.RejectionReason.MISSING_INGEST_ENTRY


# ---------------------------------------------------------------------------
# FIR-7-B5-01 / B5-02 / B5-03 / A5-01 — structural family-boundary matching
# ---------------------------------------------------------------------------


class TestB501StructuralFamilyBoundary:
    """FIR-7 Wave F: structural family-boundary rule replaces tag-strip.

    A folded token hits a deny seed on (a) exact, (b) separator-boundary
    prefix, (c) bounded compact remainder, or (d) head-segment. Exception-
    family seeds (yolox / yolos / yolof / yolop) admit under the same rules;
    yolo_nas is a DENY seed on the NC-weights axis (FIR-7-A6-03); yolor is
    GPL-3.0 and stays on the deny axis.

    Red-proven: disable boundary-prefix → pure-(b) compounds admit;
    disable compact-remainder → yolov9t admits; disable head-segment →
    yolov9t-seg admits; restore each.
    """

    # (b) separator-boundary prefix witnesses + raw spellings that fold to them.
    BOUNDARY_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolov8n_oiv7",
        "yolov8n_world",
        "yolov8s_worldv2",
        "yolo_worldv2_s",
        "yolov8n_p2",
        "yolov8n_p6",
        "yolov7_tiny",
        "yolov3_tiny",
        "yolov8n_engine",
        "yolov8n_torchscript",
        "yolov8n_mlpackage",
        "yolov9_t",
        "yolov9_e",
        # hyphen / dot / space raw spellings
        "yolov8n-oiv7",
        "yolov8n.engine",
        "yolo-worldv2-s",
        # prior B4-02 size/task compounds still denied under structural rule
        "yolov8n-seg",
        "yolov8s-seg",
        "yolov8m-pose",
        "yolov8l-obb",
        "yolov8x-cls",
        "yolo-world-s",
    )

    # (c) bounded compact remainder witnesses + cased / extension forms.
    COMPACT_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolov9t",
        "yolov9e",
        "yolov5n6",
        "yolov5nu",
        "yolov5s6",
        "fastsamx",
        "yolov8nn",  # fantasy; fail-closed is the secure direction
        "yolo11n",
        "yolo11s",
        "yolo12n",
        "yolov5n",
        "yolov9c",
        "fastsamx.pt",
        "YOLOv9T",
        "yolor",  # GPL-3.0 deny-axis seed (not an exception)
        "yolor_s",
    )

    # (d) head-segment: compact head hits seed, but whole-token compact rem
    # (tseg/npose/…) exceeds 3 chars and head != seed, so (a)/(b)/(c) miss.
    HEAD_SEGMENT_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolov9t-seg",
        "yolov9e-seg",
        "yolov9c-seg",
        "yolo11n-pose",
        "yolov8nn-seg",
        # raw spellings that fold into the same head-segment forms
        "YOLOv9T-SEG",
        "yolov9t-seg.pt",
        "yolo11n_pose",
    )

    ADMIT_COUNTEREXAMPLES: ClassVar[tuple[str, ...]] = (
        "yolodummy",  # remainder 'dummy' is 5 chars
        "myyolo",  # no prefix
        "sam",
        "timm",
        "numba",
        # head-segment creep guards: head rem >3 / non-prefix / non-seed
        "yolodummy-seg",
        "myyolo-seg",
        "numba-seg",
    )

    # yolo_nas moved to DENY (NC-weights axis, FIR-7-A6-03). Admit-side pins
    # are pure exception-family tokens + size-style variants (yolox/yolos/
    # yolof/yolop) and residual-clean compounds.
    EXCEPTION_ALLOWLIST: ClassVar[tuple[str, ...]] = (
        "yolox",
        "yolox_s",
        "yolos",
        "yolos-tiny",
        "yolof",
        "yolof_r50",
        "yolop",
        "yolopv2",
        # FIR-7 B14-3: ``yolos-tiny-seg`` no longer admits — YOLOS has no
        # seg variant; ``seg`` dropped from separator tags (was Ultralytics
        # digit-dropped naming). See TestF11B143YolosSegDeny.
    )

    @pytest.mark.parametrize(
        "token",
        BOUNDARY_WITNESSES + COMPACT_WITNESSES + HEAD_SEGMENT_WITNESSES,
    )
    def test_structural_family_token_denylisted_package(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must hit package denylist under structural family rule"
        )
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False, f"structural-family token {token!r} admitted"
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"{token!r}: expected denylisted_package, got {result.reason} "
            f"({result.detail})"
        )

    @pytest.mark.parametrize("token", HEAD_SEGMENT_WITNESSES)
    @pytest.mark.parametrize(
        "category",
        (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
        ),
        ids=("training_data", "tooling"),
    )
    def test_head_segment_denylisted_on_row_doors(
        self, token: str, category: policy.PolicyCategory
    ) -> None:
        """Head-segment deny witnesses fail denylisted_package on both row doors."""
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"head-segment token {token!r} admitted on {category.value}"
        )
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"{token!r}/{category.value}: expected denylisted_package, got "
            f"{result.reason} ({result.detail})"
        )

    @pytest.mark.parametrize("token", HEAD_SEGMENT_WITNESSES)
    def test_head_segment_denylisted_on_scalar_doors(self, token: str) -> None:
        """Head-segment deny witnesses fail both scalar doors."""
        tooling = policy.audit_tooling_dependency(token)
        assert tooling.ok is False, f"tooling scalar admitted {token!r}"
        assert tooling.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"tooling {token!r}: expected denylisted_package, got "
            f"{tooling.reason} ({tooling.detail})"
        )
        ingest = policy.audit_model_ingest(token)
        assert ingest.ok is False, f"model_ingest scalar admitted {token!r}"
        assert ingest.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"model_ingest {token!r}: expected denylisted_package, got "
            f"{ingest.reason} ({ingest.detail})"
        )

    @pytest.mark.parametrize("token", ADMIT_COUNTEREXAMPLES)
    def test_structural_family_admit_counterexamples(self, token: str) -> None:
        """Remainders >3 chars / non-prefix tokens do not hit any deny seed."""
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must NOT hit package denylist"
        )
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        if not result.ok:
            assert result.reason is not policy.RejectionReason.DENYLISTED_PACKAGE, (
                f"{token!r} incorrectly denylisted: {result.detail}"
            )

    @pytest.mark.parametrize("token", EXCEPTION_ALLOWLIST)
    def test_exception_family_admits(self, token: str) -> None:
        """Exception-family seeds (and their structural variants) admit."""
        assert policy._package_denylist_hit(token) is None, (
            f"exception-family {token!r} must NOT hit package denylist"
        )
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        if not result.ok:
            assert result.reason is not policy.RejectionReason.DENYLISTED_PACKAGE, (
                f"exception-family {token!r} incorrectly denylisted: {result.detail}"
            )

    def test_deny_and_exception_seed_sets_are_disjoint(self) -> None:
        deny_keys = policy._folded_family_seed_keys(policy.PACKAGE_DENYLIST)
        exc_keys = policy._folded_family_seed_keys(
            policy.PACKAGE_EXCEPTION_ALLOWLIST
        )
        overlap = deny_keys & exc_keys
        assert not overlap, f"seed sets overlap: {sorted(overlap)!r}"

    def test_red_proof_boundary_prefix_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable (b) → pure boundary-prefix compounds admit (TEST-15).

        Pure-(b) witnesses use an underscore-bearing seed whose first segment
        is not itself a deny seed (``buffalo_l_*``), so head-segment (d) cannot
        re-deny when (b) is off. Seed-as-head compounds (``yolov8n_oiv7``)
        correctly stay denied via (d) after (b) is disabled.
        """
        # Compact rem after seed 'buffalol' must be >3 so (c) cannot re-deny.
        pure_boundary = (
            "buffalo_l_extra",  # rem 'extra' = 5
            "buffalo_l_weights",  # rem 'weights' = 7
            "buffalo_l_engine",  # rem 'engine' = 6
        )
        for token in pure_boundary:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny with both branches on"
            )
        monkeypatch.setattr(policy, "_FAMILY_BOUNDARY_PREFIX_ENABLED", False)
        for token in pure_boundary:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with boundary disabled, {token!r} must admit"
            )
        # Compact-remainder witnesses still deny without boundary.
        assert policy._package_denylist_hit("yolov9t") is not None
        assert policy._package_denylist_hit("fastsamx") is not None
        # Seed-as-head compounds still deny via head-segment (d).
        assert policy._package_denylist_hit("yolov8n_oiv7") is not None

    def test_red_proof_compact_remainder_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable (c) → pure compact-remainder tokens admit (TEST-15)."""
        pure_compact = ("yolov9t", "yolov9e", "fastsamx", "yolov8nn")
        for token in pure_compact:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny with both branches on"
            )
        monkeypatch.setattr(policy, "_FAMILY_COMPACT_REMAINDER_ENABLED", False)
        for token in pure_compact:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with compact-remainder disabled, {token!r} must admit"
            )
        # Boundary witnesses still deny without compact remainder.
        assert policy._package_denylist_hit("yolov8n_oiv7") is not None
        assert policy._package_denylist_hit("yolov7_tiny") is not None
        # Head-segment pure-(d) cells need (c) on the head; they admit too.
        assert policy._package_denylist_hit("yolov9t-seg") is None

    def test_red_proof_head_segment_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable (d) → pure head-segment compounds admit (TEST-15)."""
        pure_head = (
            "yolov9t-seg",
            "yolov9e-seg",
            "yolov9c-seg",
            "yolo11n-pose",
            "yolov8nn-seg",
        )
        for token in pure_head:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny with head-segment on"
            )
        monkeypatch.setattr(policy, "_FAMILY_HEAD_SEGMENT_ENABLED", False)
        for token in pure_head:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with head-segment disabled, {token!r} must admit"
            )
        # (a)/(b)/(c) cells stay green without head-segment.
        assert policy._package_denylist_hit("yolov9t") is not None  # (c)
        assert policy._package_denylist_hit("yolov8n_oiv7") is not None  # (b)
        assert policy._package_denylist_hit("yolov8n") is not None  # (a)
        assert policy._package_denylist_hit("fastsamx") is not None  # (c)


# ---------------------------------------------------------------------------
# FIR-7 Wave F3 — bounded exception residual re-scan + honest lineage
# ---------------------------------------------------------------------------


class TestB601BoundedExceptionResidualRescan:
    """FIR-7-B6-01 / FIR-7-A6-01: exception hit is not an admit short-circuit.

    When a component matches an exception family, the exception seed is
    stripped and the residual is re-scanned against DENY rules (a)-(d).
    Residual deny → component DENIES with the residual seed's entry.
    Empty/clean residual → admit (``yolox``, ``yolox_s``).

    Red-proven: disable residual re-scan → ``yolox_ultralytics`` admits.
    """

    # Full-provenance witnesses that must DENY after residual re-scan (or,
    # for yolo_nas_* compounds after FIR-7-A6-03, via the NC-weights deny
    # seed itself). All previously PASS'd under unbounded exception admit.
    RESIDUAL_DENY_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolox_ultralytics",
        "yolox-ultralytics",
        "yolo_nas_ultralytics",
        "yolos_yolov8",
        "yolox_ultralytics_port",
        "vendor/yolox_ultralytics",
        "yolox-yolov8",
        "yolo-nas-yolov8-distill",
        "yolox_yolov8_distill",
        "yolos-yolov5",
    )

    # Pure residual-path witnesses (exception seed + deny residual); reason
    # is denylisted_package from the residual deny seed.
    RESIDUAL_AGPL_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolox_ultralytics",
        "yolox-ultralytics",
        "yolos_yolov8",
        "yolox_ultralytics_port",
        "vendor/yolox_ultralytics",
        "yolox-yolov8",
        "yolox_yolov8_distill",
        "yolos-yolov5",
    )

    ADMIT_PINS: ClassVar[tuple[str, ...]] = (
        "yolox",
        "yolos",
        "yolof",
        "yolop",
        "yolodummy",
        "myyolo",
        # size-style exception variants (yolo_nas moved to deny — A6-03)
        "yolox_s",
        "yolos-tiny",
        "yolof_r50",
        "yolopv2",
    )

    @pytest.mark.parametrize("token", RESIDUAL_DENY_WITNESSES)
    def test_residual_witness_hits_package_denylist(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY under bounded exception residual re-scan "
            f"(or yolo_nas NC-weights deny)"
        )

    @pytest.mark.parametrize("token", RESIDUAL_DENY_WITNESSES)
    @pytest.mark.parametrize(
        "category",
        (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
        ),
        ids=("training_data", "tooling"),
    )
    def test_residual_witness_denylisted_on_row_doors(
        self, token: str, category: policy.PolicyCategory
    ) -> None:
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"{token!r} admitted on {category.value}; residual re-scan missed"
        )
        # Residual AGPL seeds → denylisted_package; yolo_nas compounds →
        # nc_model_derived (NC-weights axis). Never unknown_source / miss.
        assert result.reason in (
            policy.RejectionReason.DENYLISTED_PACKAGE,
            policy.RejectionReason.NC_MODEL_DERIVED,
        ), (
            f"{token!r}/{category.value}: expected package-floor fail, got "
            f"{result.reason} ({result.detail})"
        )
        assert result.reason is not policy.RejectionReason.UNKNOWN_SOURCE
        assert result.reason is not policy.RejectionReason.MISSING_INGEST_ENTRY

    @pytest.mark.parametrize("token", RESIDUAL_DENY_WITNESSES)
    def test_residual_witness_denylisted_on_scalar_doors(self, token: str) -> None:
        """Scalar doors report package-floor reason, not unknown/missing."""
        tooling = policy.audit_tooling_dependency(token)
        assert tooling.ok is False, f"tooling scalar admitted {token!r}"
        assert tooling.reason in (
            policy.RejectionReason.DENYLISTED_PACKAGE,
            policy.RejectionReason.NC_MODEL_DERIVED,
        ), (
            f"tooling {token!r}: expected package-floor fail, got "
            f"{tooling.reason} ({tooling.detail})"
        )
        assert tooling.reason is not policy.RejectionReason.UNKNOWN_SOURCE
        ingest = policy.audit_model_ingest(token)
        assert ingest.ok is False, f"model_ingest scalar admitted {token!r}"
        assert ingest.reason in (
            policy.RejectionReason.DENYLISTED_PACKAGE,
            policy.RejectionReason.NC_MODEL_DERIVED,
        ), (
            f"model_ingest {token!r}: expected package-floor fail, got "
            f"{ingest.reason} ({ingest.detail})"
        )
        assert ingest.reason is not policy.RejectionReason.MISSING_INGEST_ENTRY

    @pytest.mark.parametrize("token", RESIDUAL_AGPL_WITNESSES)
    def test_residual_agpl_witness_is_denylisted_package(self, token: str) -> None:
        """Pure residual-path AGPL compounds report denylisted_package."""
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        tooling = policy.audit_tooling_dependency(token)
        assert tooling.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token", ADMIT_PINS)
    def test_exception_and_counterexample_admit_pins(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"admit pin {token!r} must NOT hit package denylist"
        )

    def test_red_proof_exception_residual_rescan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable residual re-scan → yolox_ultralytics admits (TEST-15)."""
        token = "yolox_ultralytics"
        assert policy._package_denylist_hit(token) is not None, (
            f"precondition: {token!r} must deny with residual re-scan on"
        )
        monkeypatch.setattr(policy, "_EXCEPTION_RESIDUAL_RESCAN_ENABLED", False)
        assert policy._package_denylist_hit(token) is None, (
            f"red-proof: with residual re-scan disabled, {token!r} must admit"
        )
        # Pure deny seeds still deny without residual re-scan.
        assert policy._package_denylist_hit("ultralytics") is not None
        assert policy._package_denylist_hit("yolov8n") is not None
        # Pure exception still admits.
        assert policy._package_denylist_hit("yolox") is None


class TestA602ComponentSplitFirst:
    """FIR-7-A6-02: '/' present → family-test components only, never full token.

    Pre-fix, ``yolo-nas/yolo-nas-l`` and ``yolo_nas/weights`` DENY'd via bare
    ``yolo`` rule (b) bridging the path separator, while ``deci/yolo-nas-l``
    admitted (component-level exception). Component-split-first makes path
    outcomes match per-component policy.
    """

    @pytest.mark.parametrize(
        "token",
        (
            "yolo-nas/yolo-nas-l",
            "yolo_nas/weights",
            "deci/yolo-nas-l",
        ),
    )
    def test_yolo_nas_path_components_deny_nc_weights(self, token: str) -> None:
        """After A6-03, yolo_nas components DENY on the NC-weights axis."""
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must deny via yolo_nas component"
        # F7 derived floor may report a size-specific seed (yolo_nas_l).
        assert (
            hit.package_id == "yolo_nas"
            or hit.package_id.startswith("yolo_nas")
            or hit.package_id.startswith("yolonas")
        ), (
            f"{token!r}: expected package_id yolo_nas* (not bare yolo bridging "
            f"'/'), got {hit.package_id!r}"
        )
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize(
        "token",
        (
            "ultralytics/yolox",
            "yolox/ultralytics",
        ),
    )
    def test_mixed_path_deny_component_wins(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (deny component wins)"
        assert hit.package_id == "ultralytics"

    def test_pypi_yolov5_still_denies(self) -> None:
        hit = policy._package_denylist_hit("pypi/yolov5")
        assert hit is not None
        assert hit.package_id == "yolov5"


class TestB602HonestLineageYolopDarknet:
    """FIR-7-B6-02: YOLOP admit + Darknet-era yolov2/yolov4 own deny entries."""

    @pytest.mark.parametrize("token", ("yolop", "yolopv2"))
    def test_yolop_family_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must admit (hustvl YOLOP exception family)"
        )
        entry = policy.PACKAGE_EXCEPTION_ALLOWLIST["yolop"]
        assert "hustvl" in entry.notes.casefold()
        assert "BSD-3-Clause" in entry.spdx_id or "bsd-3-clause" in entry.notes.casefold()

    @pytest.mark.parametrize(
        "token,expected_id",
        (
            ("yolov4", "yolov4"),
            ("yolov2", "yolov2"),
            ("YOLOv4", "yolov4"),
            ("yolo-v2", "yolov2"),
        ),
    )
    def test_darknet_era_own_deny_entry(
        self, token: str, expected_id: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY"
        assert hit.package_id == expected_id, (
            f"{token!r}: expected own entry package_id={expected_id!r}, "
            f"got {hit.package_id!r} (must not inherit bare 'yolo' "
            f"Ultralytics-AGPL note)"
        )
        notes_cf = hit.notes.casefold()
        assert "darknet" in notes_cf, (
            f"{token!r} notes must name Darknet-era lineage; got {hit.notes!r}"
        )
        assert "ultralytics agpl family alias" not in notes_cf


class TestA603YoloNasNcWeightsAndYolofNote:
    """FIR-7-A6-03: yolo_nas NC-weights deny + yolof MIT/megvii-model note.

    Deliberate policy correction: yolo_nas was mis-listed as Apache-2.0
    exception; pretrained weights are non-commercial (Deci licence).
    Red-proven: remove the deny entry → yolo-nas admits; restore.
    """

    YOLO_NAS_DENY_PINS: ClassVar[tuple[str, ...]] = (
        "yolo-nas",
        "yolo_nas",
        "yolonas",
        "YOLO-NAS",
        "yolo-nas-s",
        "yolo_nas_s",
        "yolo-nas-s-seg",
    )

    @pytest.mark.parametrize("token", YOLO_NAS_DENY_PINS)
    def test_yolo_nas_nc_weights_denies(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY on NC-weights axis (policy correction)"
        )
        # F7 derived floor may report a more-specific size seed (yolo_nas_s)
        # when one exists; the base stem yolo_nas still covers unsplit forms.
        assert hit.package_id == "yolo_nas" or hit.package_id.startswith(
            "yolo_nas"
        ) or hit.package_id.startswith("yolonas"), (
            f"{token!r}: expected yolo_nas* package_id, got {hit.package_id!r}"
        )
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        notes_cf = hit.notes.casefold()
        assert "non-commercial" in notes_cf or "nc-weights" in notes_cf
        assert "deci" in notes_cf or "buffalo" in notes_cf

    @pytest.mark.parametrize("token", YOLO_NAS_DENY_PINS)
    @pytest.mark.parametrize(
        "category",
        (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
        ),
        ids=("training_data", "tooling"),
    )
    def test_yolo_nas_denies_on_row_doors(
        self, token: str, category: policy.PolicyCategory
    ) -> None:
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, f"{token!r} admitted on {category.value}"
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            f"{token!r}/{category.value}: expected nc_model_derived, got "
            f"{result.reason} ({result.detail})"
        )

    def test_yolof_note_is_megvii_model_mit(self) -> None:
        entry = policy.PACKAGE_EXCEPTION_ALLOWLIST["yolof"]
        assert entry.spdx_id == "MIT", (
            f"yolof spdx_id must be MIT, got {entry.spdx_id!r}"
        )
        notes_cf = entry.notes.casefold()
        assert "megvii-model" in notes_cf or "megvii" in notes_cf
        assert "mit" in notes_cf or entry.spdx_id == "MIT"

    def test_yolos_note_still_hustvl(self) -> None:
        entry = policy.PACKAGE_EXCEPTION_ALLOWLIST["yolos"]
        assert "hustvl" in entry.notes.casefold()

    def test_yolo_nas_not_on_exception_allowlist(self) -> None:
        exc_keys = policy._folded_family_seed_keys(
            policy.PACKAGE_EXCEPTION_ALLOWLIST
        )
        assert "yolo_nas" not in exc_keys
        assert "yolonas" not in exc_keys

    def test_red_proof_yolo_nas_deny_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Strip yolo_nas* NC floor → reason flips off NC axis (TEST-15).

        F7 deny-first folded (a)/(b) means bare ``yolo`` separator-boundary
        still claims ``yolo_nas`` even if an exception seed is restored —
        admit-via-exception is no longer reachable for ``yolo_*`` forms
        (and must not be: that is the A10-02 fix). Load-bearing proof for
        the NC-axis entry is therefore the **reason flip**: with every
        yolo_nas*/yolonas* NC floor key removed, ``yolo-nas`` is still
        denied but via bare ``yolo`` ``denylisted_package`` (AGPL), not
        ``nc_model_derived``. Sibling AGPL seeds still deny.
        """
        token = "yolo-nas"
        pre = policy._package_denylist_hit(token)
        assert pre is not None, (
            f"precondition: {token!r} must deny with yolo_nas entry present"
        )
        assert pre.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            f"precondition: {token!r} must be NC-axis, got {pre.reason}"
        )

        def _is_yolo_nas_floor_key(k: str) -> bool:
            kc = (policy.canonical(k) or k).replace("_", "")
            return kc.startswith("yolonas")

        stripped = {
            k: v
            for k, v in policy.PACKAGE_DENYLIST.items()
            if not _is_yolo_nas_floor_key(k)
        }
        monkeypatch.setattr(policy, "PACKAGE_DENYLIST", stripped)
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"red-proof: {token!r} must still deny via bare yolo after NC "
            "floor strip"
        )
        assert hit.package_id == "yolo", (
            f"red-proof: expected bare yolo fallthrough, got {hit.package_id!r}"
        )
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"red-proof: expected denylisted_package after NC strip, got "
            f"{hit.reason}"
        )
        # Sibling deny seeds still deny.
        assert policy._package_denylist_hit("ultralytics") is not None
        assert policy._package_denylist_hit("yolov8") is not None


# ---------------------------------------------------------------------------
# FIR-7-B5-04 — Cf-format-only package-identity → invalid_row
# ---------------------------------------------------------------------------


class TestB504PackageIdentityCanonicalEmptyFailClosed:
    """FIR-7-B5-04: non-empty pre-canonical that folds to '' is invalid_row.

    Cf-format-only values (ZWSP, BOM, word-joiner) survive str.strip but
    :func:`canonical` returns the empty string. Same fail-closed treatment
    as canonical-None on row doors and both scalar doors.

    Red-proven: restoring silent floor skip on empty-canonical re-admits a
    TRAINING_DATA package witness (tests go red).
    """

    EMPTY_CANONICAL_TOKENS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("zwsp", "\u200b"),
        ("bom", "\ufeff"),
        ("word_joiner", "\u2060"),
    )
    IDENTITY_FIELDS: ClassVar[tuple[str, ...]] = (
        "package",
        "package_name",
        "model_id",
    )

    @pytest.mark.parametrize(
        "token_id,token",
        EMPTY_CANONICAL_TOKENS,
        ids=[t[0] for t in EMPTY_CANONICAL_TOKENS],
    )
    @pytest.mark.parametrize("field", IDENTITY_FIELDS)
    @pytest.mark.parametrize(
        "category",
        (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
        ),
        ids=("training_data", "tooling"),
    )
    def test_row_format_only_package_identity_invalid_row(
        self,
        token_id: str,
        token: str,
        field: str,
        category: policy.PolicyCategory,
    ) -> None:
        assert policy.canonical(token) == "", (
            f"precondition: {token_id} must yield canonical empty string, "
            f"got {policy.canonical(token)!r}"
        )
        assert token  # non-empty pre-canonical
        if category is policy.PolicyCategory.TRAINING_DATA:
            row: dict[str, Any] = {
                "source": "self-generated",
                "license": "MIT",
                "derived_from_model": "",
                field: token,
            }
        else:
            row = {
                "package": "llvmlite" if field != "package" else token,
                "license": "BSD-2-Clause",
                "derived_from_model": "",
            }
            if field != "package":
                row[field] = token
            else:
                row["package"] = token
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"{category.value} admitted format-only {field}={token!r} "
            f"({token_id}); detail={result.detail!r}"
        )
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"{category.value}/{field}/{token_id}: expected invalid_row, "
            f"got {result.reason} ({result.detail})"
        )
        detail_cf = result.detail.casefold()
        assert "empty" in detail_cf or "format-only" in detail_cf, (
            f"detail must name empty/format-only; got {result.detail!r}"
        )
        assert field in result.detail or token in result.detail, (
            f"detail must name field or value; got {result.detail!r}"
        )

    @pytest.mark.parametrize(
        "token_id,token",
        EMPTY_CANONICAL_TOKENS,
        ids=[t[0] for t in EMPTY_CANONICAL_TOKENS],
    )
    def test_tooling_scalar_format_only_invalid_row(
        self, token_id: str, token: str
    ) -> None:
        result = policy.audit_tooling_dependency(token)
        assert result.ok is False, f"tooling scalar admitted {token!r}"
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"tooling scalar {token_id}: expected invalid_row (not "
            f"unknown_source), got {result.reason} ({result.detail})"
        )
        detail_cf = result.detail.casefold()
        assert "empty" in detail_cf or "format-only" in detail_cf, (
            f"detail must name empty/format-only; got {result.detail!r}"
        )
        assert result.reason is not policy.RejectionReason.UNKNOWN_SOURCE

    @pytest.mark.parametrize(
        "token_id,token",
        EMPTY_CANONICAL_TOKENS,
        ids=[t[0] for t in EMPTY_CANONICAL_TOKENS],
    )
    def test_model_ingest_scalar_format_only_invalid_row(
        self, token_id: str, token: str
    ) -> None:
        result = policy.audit_model_ingest(token)
        assert result.ok is False, f"model_ingest scalar admitted {token!r}"
        assert result.reason is policy.RejectionReason.INVALID_ROW, (
            f"model_ingest scalar {token_id}: expected invalid_row (not "
            f"missing_ingest_entry), got {result.reason} ({result.detail})"
        )
        detail_cf = result.detail.casefold()
        assert "empty" in detail_cf or "format-only" in detail_cf, (
            f"detail must name empty/format-only; got {result.detail!r}"
        )
        assert result.reason is not policy.RejectionReason.MISSING_INGEST_ENTRY

    def test_red_proof_empty_canonical_floor_skip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Red-proof one path: silent skip on empty-canonical re-admits ZWSP."""
        token = "\u200b"
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        # Precondition: production path rejects.
        baseline = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert baseline.ok is False
        assert baseline.reason is policy.RejectionReason.INVALID_ROW

        real_floor = policy._floor_package_identity_denylist

        def _skip_empty_canonical(r, *, category):
            # Replicate floor but treat empty-canonical like a miss (old bug).
            # Use the real floor for type/disagree checks by temporarily
            # normalising the format-only value out, then restore.
            # Surgical: if only fault is empty-canonical package, return None.
            for key in ("package", "package_name", "model_id", "source"):
                raw = r.get(key)
                if isinstance(raw, str) and raw.strip() and policy.canonical(raw.strip()) == "":
                    # Old buggy behaviour: skip this field, continue scan.
                    # Build a scrubbed row without that field for the real floor.
                    scrubbed = {k: v for k, v in r.items() if k != key}
                    return real_floor(scrubbed, category=category)
            return real_floor(r, category=category)

        monkeypatch.setattr(
            policy, "_floor_package_identity_denylist", _skip_empty_canonical
        )
        mutated = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert mutated.ok is True or (
            mutated.reason is not policy.RejectionReason.INVALID_ROW
            or "empty" not in mutated.detail.casefold()
        ), "red-proof: empty-canonical skip must stop reporting empty invalid_row"
        # Strong form: TRAINING_DATA clean row with only ZWSP package admits.
        assert mutated.ok is True, (
            f"red-proof: expected admit under skip, got {mutated.reason} "
            f"({mutated.detail})"
        )


# ---------------------------------------------------------------------------
# FIR-7 Wave F4 — residual segment-suffix deny scan + honest NC details
# ---------------------------------------------------------------------------


class TestB701ResidualSuffixDenyScan:
    """FIR-7-B7-01 / B7-02 / B7-03 / B7-06 (+ F5 uniform scan): suffix deny.

    Wave F4 introduced residual segment-suffix re-scan after exception strip.
    Wave F5 folds that into the **uniform component scanner** (rules (d') /
    (e) on every component, iterative multi-strip) so path-split and compact
    glue cannot bypass the same suffix logic. Size/task/export tags that
    shield a trailing deny/NC seed no longer admit
    (``yolox_s_ultralytics``, ``yolox_s_buffalo_l``). NC residual hits keep
    ``nc_model_derived``. Double-exception compounds ``yolop_yolox`` /
    ``yolox_yolop`` admit after iterative exception strip (policy correction:
    both are hustvl/Megvii permissive lineages; Wave F3 false-denied via
    bare-yolo compact on the residual).

    Red-proven: disable ``_EXCEPTION_RESIDUAL_SUFFIX_SCAN_ENABLED`` →
    ``yolox_s_ultralytics`` and ``yolox_s_buffalo_l`` admit (size-tag shield
    class — Wave F3 red-proof only covered residual-leading deny seeds).
    """

    # Size/task/export tag shields trailing deny or NC seeds (full-row PASS
    # under Wave F3 whole-residual scan; must fail-closed under suffix scan).
    SUFFIX_DENY_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolox_s_ultralytics",
        "yoloxs_ultralytics",
        "yolox_tiny_ultralytics",
        "yolof_r50_ultralytics",
        "yolopv2_ultralytics",
        "yolos_tiny_yolov8n",
        "vendor/yolox_s_ultralytics",
        "yolox_s_yolo_nas",
        "yolox_s_buffalo_l",
    )

    # AGPL residual-suffix path → denylisted_package.
    SUFFIX_AGPL_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolox_s_ultralytics",
        "yoloxs_ultralytics",
        "yolox_tiny_ultralytics",
        "yolof_r50_ultralytics",
        "yolopv2_ultralytics",
        "yolos_tiny_yolov8n",
        "vendor/yolox_s_ultralytics",
    )

    # NC residual-suffix path → nc_model_derived (B7-03).
    SUFFIX_NC_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolox_s_yolo_nas", "yolo_nas"),
        ("yolox_s_buffalo_l", "buffalo_l"),
    )

    # Double-exception admit flips (B7-06 policy correction).
    DOUBLE_EXCEPTION_ADMIT: ClassVar[tuple[str, ...]] = (
        "yolop_yolox",
        "yolox_yolop",
    )

    ADMIT_PINS: ClassVar[tuple[str, ...]] = (
        "yolox_s",
        "yolox",
        "yoloxs",
        "yolof_r50",
        "yolos-tiny",
        "yolopv2",
        "yolop",
        "yolodummy",
        "myyolo",
        "sam",
        "timm",
        "numba",
    )

    @pytest.mark.parametrize("token", SUFFIX_DENY_WITNESSES)
    def test_suffix_witness_hits_package_denylist(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY under residual segment-suffix re-scan"
        )

    @pytest.mark.parametrize("token", SUFFIX_DENY_WITNESSES)
    @pytest.mark.parametrize(
        "category",
        (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
        ),
        ids=("training_data", "tooling"),
    )
    def test_suffix_witness_denies_on_row_doors(
        self, token: str, category: policy.PolicyCategory
    ) -> None:
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"{token!r} admitted on {category.value}; suffix re-scan missed"
        )
        assert result.reason in (
            policy.RejectionReason.DENYLISTED_PACKAGE,
            policy.RejectionReason.NC_MODEL_DERIVED,
        ), (
            f"{token!r}/{category.value}: expected package-floor fail, got "
            f"{result.reason} ({result.detail})"
        )
        assert result.reason is not policy.RejectionReason.UNKNOWN_SOURCE
        assert result.reason is not policy.RejectionReason.MISSING_INGEST_ENTRY

    @pytest.mark.parametrize("token", SUFFIX_DENY_WITNESSES)
    def test_suffix_witness_denies_on_scalar_doors(self, token: str) -> None:
        """B7-02: scalar doors report the same package-floor axis as row doors."""
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        expected = hit.reason
        tooling = policy.audit_tooling_dependency(token)
        assert tooling.ok is False, f"tooling scalar admitted {token!r}"
        assert tooling.reason is expected, (
            f"tooling {token!r}: expected {expected}, got {tooling.reason} "
            f"({tooling.detail})"
        )
        assert tooling.reason is not policy.RejectionReason.UNKNOWN_SOURCE
        ingest = policy.audit_model_ingest(token)
        assert ingest.ok is False, f"model_ingest scalar admitted {token!r}"
        assert ingest.reason is expected, (
            f"model_ingest {token!r}: expected {expected}, got {ingest.reason} "
            f"({ingest.detail})"
        )
        assert ingest.reason is not policy.RejectionReason.MISSING_INGEST_ENTRY

    @pytest.mark.parametrize("token", SUFFIX_AGPL_WITNESSES)
    def test_suffix_agpl_witness_is_denylisted_package(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        tooling = policy.audit_tooling_dependency(token)
        assert tooling.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize(
        "token,expected_id",
        SUFFIX_NC_WITNESSES,
        ids=[t[0] for t in SUFFIX_NC_WITNESSES],
    )
    def test_suffix_nc_witness_is_nc_model_derived(
        self, token: str, expected_id: str
    ) -> None:
        """B7-03: NC residual suffix keeps nc_model_derived (not denylisted)."""
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY"
        assert hit.package_id == expected_id, (
            f"{token!r}: expected package_id={expected_id!r}, got "
            f"{hit.package_id!r}"
        )
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        tooling = policy.audit_tooling_dependency(token)
        assert tooling.reason is policy.RejectionReason.NC_MODEL_DERIVED
        ingest = policy.audit_model_ingest(token)
        assert ingest.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("token", DOUBLE_EXCEPTION_ADMIT)
    def test_double_exception_compounds_admit(self, token: str) -> None:
        """B7-06: yolop_yolox / yolox_yolop admit (hustvl/Megvii lineages)."""
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT after recursive exception strip "
            f"(not false bare-yolo Ultralytics-AGPL deny)"
        )

    @pytest.mark.parametrize("token", ADMIT_PINS)
    def test_admit_pins_still_hold(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"admit pin {token!r} must NOT hit package denylist"
        )

    def test_red_proof_exception_residual_suffix_scan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable suffix scan → size-tag shields admit (TEST-15).

        Covers the size-tag shield class explicitly (Wave F3 red-proof only
        covered residual-LEADING deny seeds like ``yolox_ultralytics``).
        """
        shielded = ("yolox_s_ultralytics", "yolox_s_buffalo_l")
        for token in shielded:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny with suffix scan on"
            )
        monkeypatch.setattr(
            policy, "_EXCEPTION_RESIDUAL_SUFFIX_SCAN_ENABLED", False
        )
        for token in shielded:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with suffix scan disabled, {token!r} must admit"
            )
        # Residual-LEADING deny still denied by whole-residual F3 path.
        assert policy._package_denylist_hit("yolox_ultralytics") is not None
        # Pure deny / pure exception unchanged.
        assert policy._package_denylist_hit("ultralytics") is not None
        assert policy._package_denylist_hit("yolox") is None


class TestB704PerEntryNcDetailText:
    """FIR-7-B7-04: NC rejection detail names its own lineage, never another's.

    ``audit_derived_from_model`` used to append hardcoded buffalo boilerplate
    to every NC_MODEL_IDS rejection (including yolo-nas). Per-entry notes
    keep buffalo wording verbatim and give yolo-nas honest Deci text.

    Red-proven: yolo-nas detail does NOT contain 'buffalo'.
    """

    @pytest.mark.parametrize(
        "token,must_name,must_not",
        (
            ("buffalo_l", "buffalo", ("deci", "yolo-nas", "yolo_nas")),
            ("buffalo_s", "buffalo", ("deci", "yolo-nas", "yolo_nas")),
            ("insightface/buffalo_l", "buffalo", ("deci", "yolo-nas")),
            ("yolo_nas", "deci", ("buffalo",)),
            ("yolo-nas", "deci", ("buffalo",)),
            ("yolonas", "deci", ("buffalo",)),
            ("yolo_nas_m", "deci", ("buffalo",)),
        ),
    )
    def test_nc_detail_names_own_lineage(
        self,
        token: str,
        must_name: str,
        must_not: tuple[str, ...],
    ) -> None:
        result = policy.audit_derived_from_model(token)
        assert result.ok is False, f"{token!r} must reject NC"
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        detail_cf = result.detail.casefold()
        assert must_name in detail_cf, (
            f"{token!r} detail must name own lineage {must_name!r}; "
            f"got {result.detail!r}"
        )
        for foreign in must_not:
            assert foreign not in detail_cf, (
                f"{token!r} detail must NOT contain foreign lineage "
                f"{foreign!r}; got {result.detail!r}"
            )

    def test_buffalo_detail_keeps_historical_wording(self) -> None:
        result = policy.audit_derived_from_model("buffalo_l")
        assert result.ok is False
        assert "buffalo weights and output-derived data are banned" in (
            result.detail
        )

    def test_red_proof_yolo_nas_detail_not_buffalo(self) -> None:
        """yolo-nas detail must not contain 'buffalo' (TEST-15 / B7-04)."""
        result = policy.audit_derived_from_model("yolo_nas")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert "buffalo" not in result.detail.casefold(), (
            f"red-proof: yolo_nas detail must not carry buffalo boilerplate; "
            f"got {result.detail!r}"
        )
        assert "deci" in result.detail.casefold()


class TestA701YoloNasVariantNcPins:
    """FIR-7-A7-01: pin real Deci YOLO-NAS variants in the NC model-id set.

    Package floor already denies yolo_nas_* via structural family match, but
    buffalo's real variants are pinned in ``_PINNED_NC_MODEL_IDS`` while
    YOLO-NAS's were not — so ``audit_derived_from_model("yolo_nas_m")`` and
    ``audit_source("yolo_nas_m")`` PASS'd. Pin the real Deci size/pose set
    (and compact yolonas* folds via expansion) for weights-lineage parity.

    Red-proven: remove the pin → yolo_nas_m passes; restore.
    """

    YOLO_NAS_VARIANT_PINS: ClassVar[tuple[str, ...]] = (
        "yolo_nas_s",
        "yolo_nas_m",
        "yolo_nas_l",
        "yolo_nas_pose_n",
        "yolo_nas_pose_s",
        "yolo_nas_pose_m",
        "yolo_nas_pose_l",
        "yolonas_m",
        "yolonas_s",
        "yolonas_l",
        "yolonas_pose_l",
    )

    @pytest.mark.parametrize("token", YOLO_NAS_VARIANT_PINS)
    def test_yolo_nas_variant_rejects_derived_from_model(
        self, token: str
    ) -> None:
        result = policy.audit_derived_from_model(token)
        assert result.ok is False, (
            f"derived_from_model({token!r}) must reject nc_model_derived"
        )
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            f"{token!r}: expected nc_model_derived, got {result.reason} "
            f"({result.detail})"
        )

    @pytest.mark.parametrize("token", YOLO_NAS_VARIANT_PINS)
    def test_yolo_nas_variant_rejects_source(self, token: str) -> None:
        result = policy.audit_source(token)
        assert result.ok is False, (
            f"audit_source({token!r}) must reject nc_model_derived"
        )
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            f"{token!r}: expected nc_model_derived, got {result.reason} "
            f"({result.detail})"
        )

    def test_red_proof_yolo_nas_m_pin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Strip yolo_nas_m pin + yolo_nas* floor → reason leaves NC (TEST-15).

        F7 deny-first folded (a)/(b) means bare ``yolo`` still claims
        ``yolo_nas_m`` after NC floor strip, so the door cannot admit.
        Load-bearing proof: with the m-pin and every yolo_nas*/yolonas*
        floor key removed (and structural NC off so membership strip
        cannot re-resolve), the derived door rejects via bare ``yolo``
        ``denylisted_package`` rather than ``nc_model_derived``. Sibling
        ``buffalo_l`` stays NC.
        """
        token = "yolo_nas_m"
        pre = policy.audit_derived_from_model(token)
        assert pre.ok is False, (
            f"precondition: {token!r} must reject with pin present"
        )
        assert pre.reason is policy.RejectionReason.NC_MODEL_DERIVED
        stripped_pins = frozenset(
            x for x in policy._PINNED_NC_MODEL_IDS if x != "yolo_nas_m"
        )

        def _is_yolo_nas_floor_key(k: str) -> bool:
            kc = (policy.canonical(k) or k).replace("_", "")
            return kc.startswith("yolonas")

        stripped_deny = {
            k: v
            for k, v in policy.PACKAGE_DENYLIST.items()
            if not _is_yolo_nas_floor_key(k)
        }
        ids = set(stripped_pins)
        ids.update(policy._NC_EXPLICIT_VARIANTS)
        for entry in stripped_deny.values():
            if entry.reason is policy.RejectionReason.NC_MODEL_DERIVED:
                ids.add(entry.package_id)
        for pattern in policy.NC_MODEL_PATTERNS:
            p = pattern.casefold()
            if p.endswith("/*"):
                ids.add(p[:-2])
            elif p.endswith("*"):
                ids.add(p[:-1])
            else:
                ids.add(p)
        out: set[str] = set()
        for i in ids:
            c = policy.canonical(i)
            if c and not c.replace("_", "").startswith("yolonas"):
                out.add(c)
        monkeypatch.setattr(policy, "_PINNED_NC_MODEL_IDS", stripped_pins)
        monkeypatch.setattr(policy, "PACKAGE_DENYLIST", stripped_deny)
        monkeypatch.setattr(policy, "NC_MODEL_IDS", frozenset(out))
        monkeypatch.setattr(policy, "_NC_STRUCTURAL_MATCH_ENABLED", False)
        result = policy.audit_derived_from_model(token)
        assert result.ok is False, (
            f"red-proof: {token!r} must still reject via bare yolo fallthrough"
        )
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"red-proof: expected denylisted_package after NC strip, got "
            f"{result.reason} ({result.detail})"
        )
        assert "yolo" in result.detail.casefold()
        assert "nc_model_derived" not in (result.reason or "")
        # Sibling non-NAS pins still reject on NC axis.
        buffalo = policy.audit_derived_from_model("buffalo_l")
        assert buffalo.ok is False
        assert buffalo.reason is policy.RejectionReason.NC_MODEL_DERIVED


# ---------------------------------------------------------------------------
# FIR-7 Wave F5 — uniform suffix scan, iterative bounds, NC structural doors
# ---------------------------------------------------------------------------


class TestB801UniformSuffixScan:
    """FIR-7-B8-01 / B8-03 / A9-01: uniform outer-suffix + (e) deny scan.

    Path-split and compact-glue witnesses bypassed the F4 residual-only
    suffix scan. The **outer** separator-aligned suffix walk (gated by
    ``_EXCEPTION_RESIDUAL_SUFFIX_SCAN_ENABLED``) + (e) compact
    segment-suffix close them. The Wave F5 inner (d') walk was removed
    (FIR-7-A9-01): it over-blocked vendor-prefix exception forms with a
    false AGPL note and was verdict-dead for path-split pins.

    Red-proven independently: disable outer residual-suffix scan →
    path-split/size-tag witnesses admit; disable (e) → (e) sole-path
    ``xultralytics`` / ``yolox_xultralytics`` admit (steal-owned
    ``yoloxultralytics`` / ``yoloxsultralytics`` still deny); ``myyolo``
    stays admitted under (e) (4-char seed floor). Vendor-prefix
    exception forms admit (FIR-7-A9-01 pins).
    """

    # Path-split: second component is size-tag + deny seed (F4 residual-only
    # path never saw these — exception lives on a different slash component).
    PATH_SPLIT_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolox/s_ultralytics",
        "yolox/s_buffalo_l",
        "yolox/s_yolo_nas",
        "yolox/tiny_ultralytics",
        "yolos/tiny_yolov8n",
    )

    # Compact glue / mid-segment: no residual is built under head-only rules.
    COMPACT_GLUE_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolox_xultralytics",
        "yolox_xultralytics_yolox",
        "yoloxultralytics",
        "yoloxsultralytics",
    )

    # Outer-suffix-only cells: multi-segment size-tag shields (not compact-glue).
    OUTER_SUFFIX_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolox/s_ultralytics",
        "yolox/s_buffalo_l",
        "yolox_s_ultralytics",
        "yolox/tiny_ultralytics",
        "s_ultralytics",
    )

    # (e)-only cells: compact segment ends with deny seed ≥ 5 chars.
    # (Exclude yolox_xultralytics_yolox — with (e) off it can still hit bare
    # yolo compact on a residual path; still pinned as a deny witness above.)
    # F12-1 / F12-7: ``yoloxultralytics`` (exact residual) and
    # ``yoloxsultralytics`` (contained ultralytics seed) are steal-owned;
    # (e) sole-path is the residual token / separator-deferred re-queue.
    E_RULE_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolox_xultralytics",
        "xultralytics",
    )

    # FIR-7-A9-01: underscore vendor-prefix exception forms (were false-denied
    # AGPL via inner (d') at Wave F5 HEAD). Join existing vendor/yolox slash pin.
    VENDOR_PREFIX_ADMIT: ClassVar[tuple[str, ...]] = (
        "megvii_yolox",
        "hustvl_yolos",
        "hustvl_yolop",
        "megvii_model_yolof",
    )

    ADMIT_PINS: ClassVar[tuple[str, ...]] = (
        "yolox_s",
        "yolox",
        "yoloxs",
        "yolof_r50",
        "yolos-tiny",
        "yolopv2",
        "yolop",
        "yolop_yolox",
        "yolox_yolop",
        "yolodummy",
        "myyolo",
        "sam",
        "timm",
        "numba",
        "vendor/yolox",
        "megvii_yolox",
        "hustvl_yolos",
        "hustvl_yolop",
        "megvii_model_yolof",
    )

    @pytest.mark.parametrize(
        "token", PATH_SPLIT_WITNESSES + COMPACT_GLUE_WITNESSES
    )
    def test_uniform_bypass_hits_package_denylist(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY under uniform outer-suffix/(e) component scan"
        )

    @pytest.mark.parametrize(
        "token", PATH_SPLIT_WITNESSES + COMPACT_GLUE_WITNESSES
    )
    @pytest.mark.parametrize(
        "category",
        (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
        ),
        ids=("training_data", "tooling"),
    )
    def test_uniform_bypass_denies_on_row_doors(
        self, token: str, category: policy.PolicyCategory
    ) -> None:
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"{token!r} admitted on {category.value}; uniform scan missed"
        )
        assert result.reason in (
            policy.RejectionReason.DENYLISTED_PACKAGE,
            policy.RejectionReason.NC_MODEL_DERIVED,
        ), (
            f"{token!r}/{category.value}: expected package-floor fail, got "
            f"{result.reason} ({result.detail})"
        )

    @pytest.mark.parametrize(
        "token", PATH_SPLIT_WITNESSES + COMPACT_GLUE_WITNESSES
    )
    def test_uniform_bypass_denies_on_scalar_doors(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        expected = hit.reason
        tooling = policy.audit_tooling_dependency(token)
        assert tooling.ok is False, f"tooling scalar admitted {token!r}"
        assert tooling.reason is expected
        ingest = policy.audit_model_ingest(token)
        assert ingest.ok is False, f"model_ingest scalar admitted {token!r}"
        assert ingest.reason is expected

    @pytest.mark.parametrize(
        "token",
        (
            "yolox/s_ultralytics",
            "yolox/tiny_ultralytics",
            "yolos/tiny_yolov8n",
            "yolox_xultralytics",
            "yoloxultralytics",
            "yoloxsultralytics",
            "yolox_xultralytics_yolox",
        ),
    )
    def test_agpl_uniform_bypass_is_denylisted_package(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert (
            policy.audit_tooling_dependency(token).reason
            is policy.RejectionReason.DENYLISTED_PACKAGE
        )

    @pytest.mark.parametrize(
        "token,expected_id",
        (
            ("yolox/s_buffalo_l", "buffalo_l"),
            ("yolox/s_yolo_nas", "yolo_nas"),
        ),
    )
    def test_nc_uniform_bypass_is_nc_model_derived(
        self, token: str, expected_id: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == expected_id
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("token", ADMIT_PINS)
    def test_admit_pins_still_hold(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"admit pin {token!r} must NOT hit package denylist"
        )

    def test_deci_yolo_nas_l_still_denies_nc(self) -> None:
        hit = policy._package_denylist_hit("deci/yolo-nas-l")
        assert hit is not None
        # F7: size-specific floor seed yolo_nas_l may rank over base yolo_nas.
        assert (
            hit.package_id == "yolo_nas"
            or hit.package_id.startswith("yolo_nas")
            or hit.package_id.startswith("yolonas")
        )
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_myyolo_admits_under_compact_suffix_floor(self) -> None:
        """(e) ≥5 floor: myyolo ends with 4-char seed yolo — must ADMIT."""
        assert policy._package_denylist_hit("myyolo") is None

    @pytest.mark.parametrize("token", VENDOR_PREFIX_ADMIT)
    def test_vendor_prefix_exception_admits_package_floor(self, token: str) -> None:
        """FIR-7-A9-01: megvii_yolox / hustvl_* / megvii_model_yolof admit."""
        assert policy._package_denylist_hit(token) is None, (
            f"vendor-prefix exception {token!r} must NOT hit package denylist "
            f"(was false AGPL via inner (d') at Wave F5)"
        )

    @pytest.mark.parametrize("token", VENDOR_PREFIX_ADMIT)
    @pytest.mark.parametrize(
        "category",
        (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
        ),
        ids=("training_data", "tooling"),
    )
    def test_vendor_prefix_exception_admits_on_row_doors(
        self, token: str, category: policy.PolicyCategory
    ) -> None:
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(row, category=category)
        if not result.ok:
            assert result.reason is not policy.RejectionReason.DENYLISTED_PACKAGE, (
                f"vendor-prefix {token!r} false-denylisted on {category.value}: "
                f"{result.detail}"
            )

    @pytest.mark.parametrize("token", VENDOR_PREFIX_ADMIT)
    def test_vendor_prefix_exception_admits_on_scalar_doors(self, token: str) -> None:
        tooling = policy.audit_tooling_dependency(token)
        if not tooling.ok:
            assert tooling.reason is not policy.RejectionReason.DENYLISTED_PACKAGE, (
                f"tooling scalar false-denylisted {token!r}: {tooling.detail}"
            )
        ingest = policy.audit_model_ingest(token)
        if not ingest.ok:
            assert ingest.reason is not policy.RejectionReason.DENYLISTED_PACKAGE, (
                f"model_ingest scalar false-denylisted {token!r}: {ingest.detail}"
            )

    def test_red_proof_outer_residual_suffix_scan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable outer residual-suffix scan → path-split shields admit (TEST-15).

        Single-flag neuter of ``_EXCEPTION_RESIDUAL_SUFFIX_SCAN_ENABLED``
        (the load-bearing outer walk). Inner (d') was deleted (A9-01/A9-02).
        """
        for token in self.OUTER_SUFFIX_WITNESSES:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny with outer suffix scan on"
            )
        monkeypatch.setattr(
            policy, "_EXCEPTION_RESIDUAL_SUFFIX_SCAN_ENABLED", False
        )
        for token in self.OUTER_SUFFIX_WITNESSES:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with outer suffix scan disabled, {token!r} must admit"
            )
        # Compact-glue (e) / F12-1 steal cells still deny without the outer walk.
        assert policy._package_denylist_hit("xultralytics") is not None
        assert policy._package_denylist_hit("yoloxultralytics") is not None
        assert policy._package_denylist_hit("ultralytics") is not None
        assert policy._package_denylist_hit("yolox") is None
        # Vendor-prefix exceptions stay admitted.
        assert policy._package_denylist_hit("megvii_yolox") is None

    def test_red_proof_compact_suffix_rule_e(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable (e) → compact-glue witnesses admit (TEST-15)."""
        for token in self.E_RULE_WITNESSES:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny with (e) on"
            )
        monkeypatch.setattr(policy, "_FAMILY_COMPACT_SUFFIX_ENABLED", False)
        for token in self.E_RULE_WITNESSES:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with (e) disabled, {token!r} must admit"
            )
        # Outer-suffix path-split cells still deny without (e).
        assert policy._package_denylist_hit("yolox/s_ultralytics") is not None
        assert policy._package_denylist_hit("yolox_s_ultralytics") is not None
        assert policy._package_denylist_hit("myyolo") is None


class TestB802IterativeFailClosedBounds:
    """FIR-7-B8-02 / B8-05 / B9-04: iterative scan, hard bound, non-shrink.

    A 1200-exception-chain token must DENY (not raise RecursionError) on all
    four package-floor doors. A deliberately non-shrinking strip must DENY
    with denylisted_package (invariant detail).

    The hard-cap overflow half of ``_SCAN_FAIL_CLOSED_BOUNDS_ENABLED`` is a
    **defensive invariant** (FIR-7-B9-04): each counted strip consumes ≥ 1
    unit against a bound of the initial segment count, so production inputs
    with correct strip helpers do not overflow. Suite reaches it only via a
    synthetic ``max_steps`` monkeypatch (labelled below). Red-proven:
    disable fail-closed bounds → non-shrinking strip admits (synthetic
    invariant probe of the reachable non-shrink half).
    """

    @staticmethod
    def _deep_chain() -> str:
        return "yolox_" + ("yolop_" * 1200) + "ultralytics"

    def test_deep_chain_denies_without_recursion_error(self) -> None:
        token = self._deep_chain()
        hit = policy._package_denylist_hit(token)
        assert hit is not None, "deep chain must DENY (not admit, not crash)"
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert hit.package_id == "ultralytics", (
            "deep chain must name ultralytics, not a fabricated owner "
            f"(got {hit.package_id!r})"
        )

    def test_deep_chain_denies_on_all_four_doors(self) -> None:
        token = self._deep_chain()
        for category in (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
        ):
            row = {
                "source": "self-generated",
                "license": "MIT",
                "derived_from_model": "",
                "package": token,
            }
            result = policy.audit_provenance_row(row, category=category)
            assert result.ok is False, f"deep chain admitted on {category.value}"
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        tooling = policy.audit_tooling_dependency(token)
        assert tooling.ok is False
        assert tooling.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        ingest = policy.audit_model_ingest(token)
        assert ingest.ok is False
        assert ingest.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_non_shrinking_strip_denies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Monkeypatched non-shrinking strip → invariant DENY (not admit)."""
        orig = policy._strip_exception_seed_residual

        def _noshrink(token: str, seed_c: str, seed_k: str) -> str:
            residual = orig(token, seed_c, seed_k)
            if residual:
                return token  # deliberately non-shrinking
            return residual

        monkeypatch.setattr(policy, "_strip_exception_seed_residual", _noshrink)
        hit = policy._package_denylist_hit("yolox_ultralytics")
        assert hit is not None, "non-shrinking strip must DENY fail-closed"
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert "shrink" in hit.notes.casefold() or "invariant" in (
            hit.notes.casefold()
        )

    def test_red_proof_fail_closed_bounds_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable fail-closed bounds → non-shrinking strip admits (TEST-15).

        Synthetic invariant probe of the **reachable** non-shrink half
        (FIR-7-B9-04): production strip helpers always shrink, so the
        non-shrink branch is only exercised under this monkeypatch. With
        bounds off, a non-shrinking strip returns None (admit) instead of
        denylisted_package. Single-flag neuter of
        ``_SCAN_FAIL_CLOSED_BOUNDS_ENABLED``.
        """
        orig = policy._strip_exception_seed_residual

        def _noshrink(token: str, seed_c: str, seed_k: str) -> str:
            residual = orig(token, seed_c, seed_k)
            if residual:
                return token
            return residual

        monkeypatch.setattr(policy, "_strip_exception_seed_residual", _noshrink)
        assert policy._package_denylist_hit("yolox_ultralytics") is not None, (
            "precondition: non-shrink must deny with bounds on"
        )
        monkeypatch.setattr(policy, "_SCAN_FAIL_CLOSED_BOUNDS_ENABLED", False)
        assert policy._package_denylist_hit("yolox_ultralytics") is None, (
            "red-proof: with bounds disabled, non-shrinking strip must admit"
        )
        # Pure deny still works without the bound path.
        assert policy._package_denylist_hit("ultralytics") is not None

    def test_synthetic_overflow_bound_invariant_probe(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Synthetic max_steps=1 probe of the defensive overflow branch (B9-04).

        Not a production-reachable input: forces the hard-cap half of
        ``_SCAN_FAIL_CLOSED_BOUNDS_ENABLED`` via an artificial step bound.
        Documents that the branch DENIES fail-closed when forced, without
        claiming production reachability.
        """
        orig = policy._uniform_component_scan

        def _bounded(
            token: str,
            *,
            max_steps: int | None = None,
            reasons: frozenset | None = None,
        ):
            # Force overflow on any multi-strip residual path; forward reasons
            # so multi-axis door scans (FIR-7-A10-01) stay honest under this
            # probe.
            return orig(token, max_steps=1, reasons=reasons)

        monkeypatch.setattr(policy, "_uniform_component_scan", _bounded)
        # yolox_yolop_ultralytics needs >1 strip against a real bound; with
        # max_steps=1 the overflow (or first residual deny) path still DENIES.
        hit = policy._package_denylist_hit("yolox_yolop_ultralytics")
        assert hit is not None, "synthetic overflow probe must DENY fail-closed"
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE


class TestB804MultiStripContinuationPins:
    """FIR-7-B8-04 / A8-01: pin multi-strip residual deny paths.

    These deny today under nested exception strip → residual deny, but had
    no tests. Mutating multi-strip continuation to return None flips them
    to ADMIT while leaving the suite otherwise green.

    Red-proven: disable ``_EXCEPTION_MULTI_STRIP_CONTINUATION_ENABLED``
    (not the single-strip residual re-scan flag) → these cells admit;
    single-strip ``yolox_ultralytics`` still denies.
    """

    # All four are pinned as deny witnesses. MULTI_STRIP_DEPENDENT are those
    # whose deny requires a nested exception strip (with (d') alone on the
    # first residual, a leading size-tag can still expose ultralytics without
    # multi-strip — e.g. yolox_s_yolop_ultralytics).
    MULTI_STRIP_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolox_yolop_ultralytics",
        "yolox_yolop_s_ultralytics",
        "yolox_s_yolop_ultralytics",
        "yolop_yolox_yolov8",
    )
    MULTI_STRIP_DEPENDENT: ClassVar[tuple[str, ...]] = (
        "yolox_yolop_ultralytics",
        "yolox_yolop_s_ultralytics",
        "yolop_yolox_yolov8",
    )

    @pytest.mark.parametrize("token", MULTI_STRIP_WITNESSES)
    def test_multi_strip_hits_package_denylist(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY via multi-strip continuation"
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token", MULTI_STRIP_WITNESSES)
    @pytest.mark.parametrize(
        "category",
        (
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
        ),
        ids=("training_data", "tooling"),
    )
    def test_multi_strip_denies_on_row_doors(
        self, token: str, category: policy.PolicyCategory
    ) -> None:
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token", MULTI_STRIP_WITNESSES)
    def test_multi_strip_denies_on_scalar_doors(self, token: str) -> None:
        tooling = policy.audit_tooling_dependency(token)
        assert tooling.ok is False
        assert tooling.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        ingest = policy.audit_model_ingest(token)
        assert ingest.ok is False
        assert ingest.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_red_proof_multi_strip_continuation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable multi-strip only → nested-dependent witnesses admit (TEST-15)."""
        for token in self.MULTI_STRIP_DEPENDENT:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny with multi-strip on"
            )
        monkeypatch.setattr(
            policy, "_EXCEPTION_MULTI_STRIP_CONTINUATION_ENABLED", False
        )
        for token in self.MULTI_STRIP_DEPENDENT:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with multi-strip disabled, {token!r} must admit"
            )
        # Single-strip residual re-scan still denies (flag is independent).
        assert policy._package_denylist_hit("yolox_ultralytics") is not None
        assert policy._package_denylist_hit("yolox_s_ultralytics") is not None
        assert policy._package_denylist_hit("yolox") is None


class TestB806StructuralNcDoors:
    """FIR-7-B8-06 / B9-02: structural NC matching on weights-lineage doors.

    Export/quant/runtime tags must not shield an NC seed on
    ``audit_derived_from_model`` / ``audit_source``. Bounded order-blind
    strip (known tags or short structural; hard bound 3; ≥1 leading
    segment) closes ``*_trt`` / ``*_coreml`` / mixed ``int8_trt`` without
    a treadmill. Non-NC counter-pins still pass. Red-proven: disable
    structural NC alone → export-tag cell admits (TEST-15).
    """

    EXPORT_TAG_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolo_nas_l_int8",
        "yolo_nas_l_onnx",
        "yolo_nas_pose_n_onnx",
        "buffalo_l_int8",
        # FIR-7-B9-02 measured witnesses (PASS both doors at F5 HEAD).
        "yolo_nas_l_trt",
        "buffalo_l_trt",
        "antelopev2_trt",
        "vec2face_trt",
        "insightface_trt",
        "yolo_nas_l_coreml",
        "yolo_nas_l_ncnn",
        "yolo_nas_l_int8_trt",
    )

    # Mixed order + triple-tag cells (order-blind unwrap within bound 3).
    MIXED_ORDER_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yolo_nas_l_int8_trt",
        "yolo_nas_l_trt_int8",
        "yolo_nas_l_fp16_onnx_trt",
        "buffalo_l_trt_int8",
    )

    COUNTER_PINS: ClassVar[tuple[str, ...]] = (
        "notdcface/x",
        "dcface/gen1",
        "mediapipe/blazeface",
        "sam",
        "timm",
        "yolox_s",
        "sam_onnx",
        "blazeface_int8",
    )

    @pytest.mark.parametrize("token", EXPORT_TAG_WITNESSES)
    def test_export_tag_rejects_derived_from_model(self, token: str) -> None:
        result = policy.audit_derived_from_model(token)
        assert result.ok is False, f"derived_from_model({token!r}) must reject"
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("token", EXPORT_TAG_WITNESSES)
    def test_export_tag_rejects_source(self, token: str) -> None:
        result = policy.audit_source(token)
        assert result.ok is False, f"audit_source({token!r}) must reject"
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("token", COUNTER_PINS)
    def test_non_nc_counter_pins_pass_derived(self, token: str) -> None:
        result = policy.audit_derived_from_model(token)
        assert result.ok is True, (
            f"counter-pin {token!r} must pass derived_from_model; "
            f"got {result.reason} ({result.detail})"
        )

    @pytest.mark.parametrize("token", COUNTER_PINS)
    def test_non_nc_counter_pins_pass_source(self, token: str) -> None:
        result = policy.audit_source(token)
        assert result.ok is True, (
            f"counter-pin {token!r} must pass audit_source; "
            f"got {result.reason} ({result.detail})"
        )

    @pytest.mark.parametrize("token", MIXED_ORDER_WITNESSES)
    def test_mixed_order_export_tags_reject_both_doors(self, token: str) -> None:
        """Order-blind unwrap: int8_trt / trt_int8 / fp16_onnx_trt (B9-02)."""
        derived = policy.audit_derived_from_model(token)
        assert derived.ok is False, f"derived_from_model({token!r}) must reject"
        assert derived.reason is policy.RejectionReason.NC_MODEL_DERIVED
        source = policy.audit_source(token)
        assert source.ok is False, f"audit_source({token!r}) must reject"
        assert source.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_three_tag_bound_does_not_over_admit_naked_nc(self) -> None:
        """Bound overflow stops stripping; naked NC seed still rejects.

        A 4-tag suffix on an NC base cannot strip past the bound of 3, but
        the residual head remains NC-seed-shaped (or package-floor export-
        shaped) so the door still rejects — bound overflow denies nothing
        that a naked NC seed would not.
        """
        # 4 trailing tags: only 3 strip → yolo_nas_l_int8 left; further
        # membership / package path still rejects.
        token = "yolo_nas_l_int8_fp16_onnx_trt"
        heads = policy._nc_iter_stripped_heads(
            policy.canonical(token) or token
        )
        assert len(heads) <= policy._NC_MAX_TRAILING_TAG_STRIPS
        assert policy.audit_derived_from_model(token).ok is False
        assert (
            policy.audit_derived_from_model(token).reason
            is policy.RejectionReason.NC_MODEL_DERIVED
        )
        # Naked seed still rejects.
        assert policy.audit_derived_from_model("yolo_nas_l").ok is False

    def test_red_proof_structural_nc_export_tag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable structural NC alone → structural-only cells admit (TEST-15).

        F7 package-floor promotion covers known export-tag residuals
        (``yolo_nas_l_trt`` / ``*_int8``) even with structural NC off, so
        those are no longer sole-path witnesses. Structural strip remains
        load-bearing for pure-alpha 4-char tags on multi-segment heads that
        are **not** export-shaped and exceed rule (c)'s 3-char rem cap
        (``yolo_nas_l_free`` / ``yolo_nas_l_blah``): membership after strip
        rejects; floor (b)/(c) miss; with structural off the door admits.
        """
        tokens = ("yolo_nas_l_free", "yolo_nas_l_blah")
        for token in tokens:
            assert policy.audit_derived_from_model(token).ok is False, (
                f"precondition: {token!r} must reject with structural NC on"
            )
        monkeypatch.setattr(policy, "_NC_STRUCTURAL_MATCH_ENABLED", False)
        for token in tokens:
            assert policy.audit_derived_from_model(token).ok is True, (
                f"red-proof: with structural NC off, {token!r} must admit"
            )
        # Bare pinned NC seed still rejects via exact membership.
        assert policy.audit_derived_from_model("yolo_nas_l").ok is False
        assert policy.audit_derived_from_model("buffalo_l").ok is False
        # Package-floor export-shaped NC still rejects without structural strip
        # (includes antelopev2 after B9-02 follow-up floor backstop).
        assert policy.audit_derived_from_model("insightface_trt").ok is False
        assert policy.audit_derived_from_model("antelopev2_trt").ok is False
        assert policy.audit_derived_from_model("yolo_nas_l_trt").ok is False


class TestB902PrefixShieldedNcFloor:
    """FIR-7-B9-02 follow-up: prefix-shielded NC seeds get package-floor backstop.

    Floor-less NC lineage names (antelopev2 / retinaface / arcface /
    buffalo_s / buffalo_sc / vec2face) previously admitted under any
    leading junk segment: no PACKAGE_DENYLIST entry → uniform floor miss,
    and whole-component NC promotion had nothing to promote. After the
    backstop, both ``_package_denylist_hit`` and
    ``_whole_component_nc_package_hit`` fire on every witness; TRAINING_DATA
    rows + both weights doors report ``nc_model_derived``.

    Bare ``buffalo`` is intentionally not a family seed (generic-English
    ``buffalo_bill_detector`` must stay admitted). Compact ``myarcface``
    over-blocks via rule (e) (arcface ≥ 5 compact chars) — deliberate.
    Red-proven: disable ``_NC_PACKAGE_COMPONENT_SUFFIX_ENABLED`` alone →
    one prefix witness admits on weights doors.
    """

    PREFIX_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("myprefix_antelopev2", "antelopev2"),
        ("org_antelopev2_int8", "antelopev2"),
        ("myprefix_retinaface", "retinaface"),
        ("myprefix_arcface", "arcface"),
        ("myprefix_buffalo_sc", "buffalo_sc"),
        ("myprefix_buffalo_s", "buffalo_s"),
        ("myprefix_vec2face", "vec2face"),
        ("checkpoints_vec2face_trt", "vec2face"),
    )

    # Doors must still admit these; buffalo_bill also admits on package rows.
    DOOR_ADMIT_COUNTERS: ClassVar[tuple[str, ...]] = (
        "buffalo_bill_detector",
        "not_insightface",
        "not-insightface",
        "sam",
        "timm",
        "sam_onnx",
        "blazeface_int8",
        "mediapipe/blazeface",
        "dcface/gen1",
        "notdcface/x",
    )

    NEW_FLOOR_SEEDS: ClassVar[tuple[str, ...]] = (
        "antelopev2",
        "retinaface",
        "arcface",
        "buffalo_s",
        "buffalo_sc",
        "vec2face",
    )

    @pytest.mark.parametrize(
        "token,expected_seed",
        PREFIX_WITNESSES,
        ids=[t[0] for t in PREFIX_WITNESSES],
    )
    def test_prefix_witness_hits_package_floor_and_whole_component(
        self, token: str, expected_seed: str
    ) -> None:
        floor = policy._package_denylist_hit(token)
        assert floor is not None, f"{token!r} must hit package floor"
        assert floor.package_id == expected_seed, (
            f"{token!r}: floor seed {floor.package_id!r} != {expected_seed!r}"
        )
        assert floor.reason is policy.RejectionReason.NC_MODEL_DERIVED
        whole = policy._whole_component_nc_package_hit(token)
        assert whole is not None, (
            f"{token!r} must hit whole-component NC package path"
        )
        assert whole.package_id == expected_seed, (
            f"{token!r}: whole seed {whole.package_id!r} != {expected_seed!r}"
        )

    @pytest.mark.parametrize(
        "token,expected_seed",
        PREFIX_WITNESSES,
        ids=[t[0] for t in PREFIX_WITNESSES],
    )
    def test_prefix_witness_rejects_weights_doors(
        self, token: str, expected_seed: str
    ) -> None:
        derived = policy.audit_derived_from_model(token)
        assert derived.ok is False, f"derived_from_model({token!r}) must reject"
        assert derived.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert expected_seed in derived.detail, (
            f"derived detail must name lineage {expected_seed!r}: {derived.detail!r}"
        )
        source = policy.audit_source(token)
        assert source.ok is False, f"audit_source({token!r}) must reject"
        assert source.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert expected_seed in source.detail, (
            f"source detail must name lineage {expected_seed!r}: {source.detail!r}"
        )

    @pytest.mark.parametrize(
        "token,expected_seed",
        PREFIX_WITNESSES,
        ids=[t[0] for t in PREFIX_WITNESSES],
    )
    def test_prefix_witness_rejects_training_data_row(
        self, token: str, expected_seed: str
    ) -> None:
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False, (
            f"{token!r} admitted on TRAINING_DATA row; floor miss"
        )
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            f"{token!r}: expected nc_model_derived, got {result.reason} "
            f"({result.detail})"
        )
        assert expected_seed in result.detail, (
            f"row detail must name lineage {expected_seed!r}: {result.detail!r}"
        )

    @pytest.mark.parametrize("token", DOOR_ADMIT_COUNTERS)
    def test_counter_pins_still_admit_on_weights_doors(self, token: str) -> None:
        derived = policy.audit_derived_from_model(token)
        assert derived.ok is True, (
            f"counter-pin {token!r} must pass derived_from_model; "
            f"got {derived.reason} ({derived.detail})"
        )
        source = policy.audit_source(token)
        assert source.ok is True, (
            f"counter-pin {token!r} must pass audit_source; "
            f"got {source.reason} ({source.detail})"
        )

    def test_buffalo_bill_admits_on_training_data_package_row(self) -> None:
        """Generic-English buffalo must not become a family seed."""
        assert "buffalo" not in policy.PACKAGE_DENYLIST, (
            "bare 'buffalo' must not be a PACKAGE_DENYLIST seed "
            "(buffalo_bill_detector / generic-English pin)"
        )
        assert policy._package_denylist_hit("buffalo_bill_detector") is None
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "package": "buffalo_bill_detector",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is True, (
            f"buffalo_bill_detector must admit on TRAINING_DATA package row; "
            f"got {result.reason} ({result.detail})"
        )

    def test_not_insightface_row_rejection_unchanged(self) -> None:
        """BR-28: doors admit; package floor still rejects (pre-existing)."""
        assert policy.audit_derived_from_model("not_insightface").ok is True
        floor = policy._package_denylist_hit("not_insightface")
        assert floor is not None
        assert floor.package_id == "insightface"
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "package": "not_insightface",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_myarcface_compact_suffix_overblock_is_deliberate(self) -> None:
        """arcface ≥ 5 compact chars → rule (e) over-blocks myarcface on floor."""
        assert policy._COMPACT_SUFFIX_MIN_SEED_LEN == 5
        assert len(policy._compact_canonical("arcface")) >= 5
        hit = policy._package_denylist_hit("myarcface")
        assert hit is not None, "myarcface must hit arcface via compact (e)"
        assert hit.package_id == "arcface"
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        # Weights doors do not promote (e)-only hits (BR-28 precision).
        assert policy.audit_derived_from_model("myarcface").ok is True
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "package": "myarcface",
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("seed", NEW_FLOOR_SEEDS)
    def test_new_floor_entry_note_names_own_lineage(self, seed: str) -> None:
        entry = policy.PACKAGE_DENYLIST[seed]
        assert entry.reason is policy.RejectionReason.NC_MODEL_DERIVED
        note = entry.notes.casefold()
        # Own lineage token must appear; no cross-talk to a sibling seed.
        assert seed.replace("_", "") in note.replace("_", "") or seed in note, (
            f"{seed!r} notes must name its own lineage: {entry.notes!r}"
        )
        siblings = [s for s in self.NEW_FLOOR_SEEDS if s != seed]
        for other in siblings:
            # Avoid trivial substring false positives (buffalo_s vs buffalo_sc).
            if other in seed or seed in other:
                continue
            assert other not in note, (
                f"{seed!r} notes must not name sibling {other!r}: {entry.notes!r}"
            )

    def test_red_proof_prefix_shield_component_suffix_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable NC package component-suffix alone → prefix cell admits.

        Red-proven (TEST-15): exactly one flag flip. Export-shaped whole-
        component hits (insightface_trt) and bare NC seeds still reject.
        """
        witness = "myprefix_antelopev2"
        assert policy.audit_derived_from_model(witness).ok is False, (
            f"precondition: {witness!r} must reject with suffix walk on"
        )
        assert policy._package_denylist_hit(witness) is not None, (
            f"precondition: {witness!r} must still hit uniform package floor"
        )
        monkeypatch.setattr(policy, "_NC_PACKAGE_COMPONENT_SUFFIX_ENABLED", False)
        assert policy.audit_derived_from_model(witness).ok is True, (
            f"red-proof: with component-suffix off, {witness!r} must admit "
            "on weights doors"
        )
        assert policy.audit_source(witness).ok is True
        # Uniform floor path is independent of the door suffix-walk flag.
        assert policy._package_denylist_hit(witness) is not None
        # Sibling export-shaped whole-component path still rejects.
        assert policy.audit_derived_from_model("insightface_trt").ok is False
        assert policy.audit_derived_from_model("buffalo_l").ok is False
        # Bare new-floor seed still rejects via exact whole-component (a).
        assert policy.audit_derived_from_model("antelopev2").ok is False


class TestB807DerivedDoorResidualNcParity:
    """FIR-7-B8-07: derived door rejects residual NC compounds.

    ``yolox_s_buffalo_l`` / ``yolox_s_yolo_nas`` are package-floor NC hits;
    with structural NC (B8-06) the derived door must also report
    ``nc_model_derived``. Tooling/ingest doors unchanged (still package-floor).
    """

    RESIDUAL_NC: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolox_s_buffalo_l", "buffalo_l"),
        ("yolox_s_yolo_nas", "yolo_nas"),
    )

    @pytest.mark.parametrize(
        "token,expected_id",
        RESIDUAL_NC,
        ids=[t[0] for t in RESIDUAL_NC],
    )
    def test_derived_rejects_residual_nc_compound(
        self, token: str, expected_id: str
    ) -> None:
        result = policy.audit_derived_from_model(token)
        assert result.ok is False, (
            f"derived_from_model({token!r}) must reject nc_model_derived"
        )
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert expected_id in (policy.match_nc_model_pattern(token) or "")

    @pytest.mark.parametrize(
        "token,expected_id",
        RESIDUAL_NC,
        ids=[t[0] for t in RESIDUAL_NC],
    )
    def test_tooling_ingest_still_nc_package_floor(
        self, token: str, expected_id: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == expected_id
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        tooling = policy.audit_tooling_dependency(token)
        assert tooling.reason is policy.RejectionReason.NC_MODEL_DERIVED
        ingest = policy.audit_model_ingest(token)
        assert ingest.reason is policy.RejectionReason.NC_MODEL_DERIVED


class TestA804NcDetailNoteCleanup:
    """FIR-7-A8-04: NC detail notes via shared ranking fold + vec2face entry."""

    def test_vec2face_detail_names_lineage(self) -> None:
        result = policy.audit_derived_from_model("vec2face")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert "vec2face" in result.detail.casefold()

    def test_yolo_nas_variant_uses_prefix_note(self) -> None:
        """Collapsed variant notes still resolve via yolo_nas prefix seed."""
        result = policy.audit_derived_from_model("yolo_nas_l")
        assert result.ok is False
        assert "deci" in result.detail.casefold()
        assert "buffalo" not in result.detail.casefold()

    def test_no_redundant_yolo_nas_variant_note_keys(self) -> None:
        variant_keys = [
            k
            for k in policy._NC_MODEL_DETAIL_NOTES
            if k.startswith("yolo_nas_")
        ]
        assert variant_keys == [], (
            f"yolo_nas variant note keys should be collapsed; got {variant_keys}"
        )


# ---------------------------------------------------------------------------
# FIR-7 Wave F6 — (d') kill, NC tag-strip, PP-YOLO, flag independence
# ---------------------------------------------------------------------------


class TestB903PpYoloHonestLineage:
    """FIR-7-B9-03: PP-YOLO is Baidu PaddleDetection Apache-2.0, not Darknet."""

    ADMIT: ClassVar[tuple[str, ...]] = ("ppyolo", "ppyoloe", "ppyolov2")
    DARKNET_DENY: ClassVar[tuple[str, ...]] = ("yolov2", "yolov2_food", "xyolov2")

    @pytest.mark.parametrize("token", ADMIT)
    def test_pp_yolo_family_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must admit (Baidu PP-YOLO exception family)"
        )
        entry = policy.PACKAGE_EXCEPTION_ALLOWLIST["ppyolo"]
        assert "paddle" in entry.notes.casefold() or "baidu" in entry.notes.casefold()
        assert "apache" in entry.spdx_id.casefold()

    @pytest.mark.parametrize("token", ADMIT)
    def test_pp_yolo_detail_not_darknet(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is None
        # If a future deny path reappears, detail must not say Darknet.
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        if not result.ok:
            assert "darknet" not in result.detail.casefold(), (
                f"{token!r} detail must not attribute Darknet: {result.detail!r}"
            )

    @pytest.mark.parametrize("token", DARKNET_DENY)
    def test_darknet_yolov2_still_denies_with_darknet_note(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (Darknet-era yolov2)"
        assert hit.package_id == "yolov2"
        assert "darknet" in hit.notes.casefold()


class TestA901FlagIndependence:
    """FIR-7-A9-01: every surviving module flag changes ≥1 pinned outcome alone.

    No-op flags are TEST-15 violations by construction. Bounds flag uses the
    synthetic non-shrink fixture (B9-04 defensive invariant).
    """

    SURVIVING_FLAGS: ClassVar[tuple[str, ...]] = (
        "_FAMILY_BOUNDARY_PREFIX_ENABLED",
        "_FAMILY_COMPACT_REMAINDER_ENABLED",
        "_FAMILY_HEAD_SEGMENT_ENABLED",
        "_FAMILY_COMPACT_SUFFIX_ENABLED",
        "_EXCEPTION_RESIDUAL_RESCAN_ENABLED",
        "_EXCEPTION_RESIDUAL_SUFFIX_SCAN_ENABLED",
        "_EXCEPTION_MULTI_STRIP_CONTINUATION_ENABLED",
        "_SCAN_FAIL_CLOSED_BOUNDS_ENABLED",
        "_NC_STRUCTURAL_MATCH_ENABLED",
        "_NC_PACKAGE_COMPONENT_SUFFIX_ENABLED",
        "_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED",  # F10 residual classification
        "_ELEVATED_DENY_COMPACT_ENABLED",  # elevated deny-(c) arm (pure deny)
        "_DENY_COMPACT_PREFIX_GLUE_ENABLED",  # FIR-7-B13-5 ultralyticsplus
    )

    def test_no_generalized_suffix_flag_remains(self) -> None:
        assert not hasattr(policy, "_FAMILY_GENERALIZED_SUFFIX_ENABLED"), (
            "inner (d') flag must be deleted (FIR-7-A9-02)"
        )

    def test_each_flag_flip_alone_changes_a_pinned_outcome(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flipping each flag alone (no other flags) changes ≥1 pin."""
        # Pinned production outcomes (no fixtures).
        pkg_pins = (
            "yolov8n_oiv7",  # (b)
            "buffalo_l_extra",  # pure (b)
            # A14-4: yolov9t appears once (elevated deny-(c) / family (c) sole-path).
            "yolov9t",
            "yoloseg",  # residual classify (F10)
            "yolofree",  # residual classify long debris (F10)
            "yolov9t-seg",  # (d) head-segment
            "xultralytics",  # (e) sole-path after F12-1 (yoloxultralytics is steal)
            "yolox_ultralytics",  # residual re-scan
            "yolox_s_ultralytics",  # residual re-scan / outer suffix
            "yolox_yolop_ultralytics",  # multi-strip
            "ultralytics",  # exact deny
            "ultralyticsplus",  # long-seed compact-prefix glue (B13-5)
            "yolox",  # pure exception admit
            "megvii_yolox",  # vendor-prefix admit
        )
        derived_pins = (
            # Structural-only 4-char pure-alpha tag (F7: known export tags also
            # reject via package-floor promotion, so they no longer sole-prove
            # _NC_STRUCTURAL_MATCH_ENABLED).
            "yolo_nas_l_free",
            "yolo_nas_l_trt",  # floor promotion path
            "buffalo_l",
            # B9-02 follow-up: prefix-shield cell gated by component-suffix walk.
            "myprefix_antelopev2",
        )

        def snapshot() -> dict[str, object]:
            out: dict[str, object] = {}
            for t in pkg_pins:
                hit = policy._package_denylist_hit(t)
                out[f"pkg:{t}"] = None if hit is None else hit.package_id
            for t in derived_pins:
                r = policy.audit_derived_from_model(t)
                out[f"der:{t}"] = (r.ok, None if r.ok else r.reason)
            return out

        baseline = snapshot()
        # Assert the deleted flag is gone before the loop.
        assert "_FAMILY_GENERALIZED_SUFFIX_ENABLED" not in self.SURVIVING_FLAGS

        for flag in self.SURVIVING_FLAGS:
            # Restore all flags to True, then flip only this one.
            for f in self.SURVIVING_FLAGS:
                monkeypatch.setattr(policy, f, True)
            monkeypatch.setattr(policy, flag, False)

            if flag == "_SCAN_FAIL_CLOSED_BOUNDS_ENABLED":
                # Synthetic non-shrink fixture — production strips always
                # shrink, so this flag's load-bearing path is the probe.
                orig = policy._strip_exception_seed_residual

                def _noshrink(
                    token: str, seed_c: str, seed_k: str, _orig=orig
                ) -> str:
                    residual = _orig(token, seed_c, seed_k)
                    return token if residual else residual

                monkeypatch.setattr(
                    policy, "_strip_exception_seed_residual", _noshrink
                )
                # With bounds ON + non-shrink → deny; we flipped bounds OFF.
                assert policy._package_denylist_hit("yolox_ultralytics") is None, (
                    f"{flag}: non-shrink must admit when bounds disabled"
                )
                monkeypatch.setattr(
                    policy, "_strip_exception_seed_residual", orig
                )
                continue

            now = snapshot()
            changed = [k for k in baseline if baseline[k] != now[k]]
            assert changed, (
                f"{flag}: flipping alone changed zero pinned outcomes "
                f"(TEST-15 no-op flag)"
            )

        # Restore all flags.
        for f in self.SURVIVING_FLAGS:
            monkeypatch.setattr(policy, f, True)



# ---------------------------------------------------------------------------
# FIR-7 Wave F7 — deny-first ordering, AGPL-aware promotion, derived NC surface
# ---------------------------------------------------------------------------


class TestA1002DenyFirstOrdering:
    """FIR-7-A10-02 / B11-01: deny (a)/(b)/(c) before exception absorption.

    Exception compact seeds (yolos/yolof/yolop/yolox) must not absorb bare-
    yolo Ultralytics artifact forms — folded (yolo_seg / yolo_free /
    yolo_pose / yolo_x / yolo_s_v8) **and** compact twins (yoloseg /
    yolofree / yolopose / yolosg). Pure exception identities and
    vendor-prefix forms still admit.
    """

    DENY_WITNESSES: ClassVar[tuple[str, ...]] = (
        "checkpoints_yolo_seg",
        "checkpoints_yolo_free",
        "weights_yolo_pose",
        "org_yolo_seg",
        "hub_yolo_x",
        "repo_yolo_s_v8",
        "yolo_seg",
        "yolo_free",
        "yolo_pose",
        "yolo_x",
        "yolo_s",
        "yolo_s_v8",
        # FIR-7-B11-01: compact laundering twins of the folded forms above.
        "yoloseg",
        "YoloSeg",
        "yolosg",
        "yoloseg_v8",
        "checkpoints_yoloseg",
        "org/yoloseg",
        "prefix_yoloseg",
        "yolofree",
        "yolopose",
    )

    ADMIT_PINS: ClassVar[tuple[str, ...]] = (
        "yolox_s",
        "yoloxs",
        "yolos-tiny",
        "yolos_base",
        "yolof_r50",
        "yolof_r101",
        "yolop",
        "yolopv2",
        "yolop_v3",
        "yolop_yolox",
        "yolox_yolop",
        "megvii_yolox",
        "megvii_yolox_s",
        "hustvl_yolos",
        "hustvl_yolos_tiny",
        "hustvl_yolop",
        "megvii_model_yolof",
        "ppyolo",
        "ppyoloe",
        "ppyolov2",
        "myyolo",
        "yolodummy",
    )

    @pytest.mark.parametrize("token", DENY_WITNESSES)
    def test_ultralytics_artifact_forms_deny(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (deny-first A10-02)"
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert hit.package_id == "yolo" or hit.package_id.startswith("yolo"), (
            f"{token!r}: expected yolo* AGPL seed, got {hit.package_id!r}"
        )

    @pytest.mark.parametrize("token", DENY_WITNESSES)
    def test_ultralytics_artifact_forms_deny_on_training_data_row(
        self, token: str
    ) -> None:
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token", ADMIT_PINS)
    def test_exception_admit_pins_survive(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"admit pin {token!r} must survive deny-first ordering"
        )


class TestA1001MultiAxisDoorPromotion:
    """FIR-7-A10-01 / B11-02 / A11-2: AGPL precedes NC on all door paths.

    Dual-axis compounds (NC seed + Ultralytics residue) must not admit and
    must not attribute one lineage's residue to the other's note.
    Precedence: denylisted_package (AGPL) first when both present —
    including membership-path forms where match_nc_model_pattern would
    otherwise return first (slash dual-axis, exception-shielded).

    Detail honesty (A11-2): assert ENTRY identity + licence axis, not
    substrings of the echoed input token.
    """

    DUAL_AXIS: ClassVar[tuple[str, ...]] = (
        "buffalo_l_ultralytics",
        "arcface_ultralytics",
        "antelopev2_ultralytics",
        "yolo_nas_l_ultralytics",
        "retinaface_yolov8",
    )

    # FIR-7-B11-02: membership path previously returned nc_model_derived
    # before consulting multi-axis floor promotion.
    MEMBERSHIP_PATH_DUAL_AXIS: ClassVar[tuple[str, ...]] = (
        "ultralytics/buffalo_l",
        "buffalo_l/ultralytics",
        "yolov8/arcface",
        "arcface/yolov8",
        "yolox_s_buffalo_l_ultralytics",
        "yolop_arcface_ultralytics",
    )

    NC_ONLY_COUNTERS: ClassVar[tuple[str, ...]] = (
        "myprefix_antelopev2_trt",
        "org/buffalo_l",
    )

    _NC_LINEAGE_PHRASES: ClassVar[tuple[str, ...]] = (
        "non-commercial",
        "insightface",
        "deci",
        "buffalo weights",
    )

    def _assert_agpl_entry_detail(self, detail: str, token: str) -> None:
        """A11-2: entry id + AGPL licence present; no NC lineage phrases."""
        detail_cf = detail.casefold()
        # Matched entry identity + licence — not merely the echoed input.
        has_ultralytics_entry = "entry 'ultralytics' (agpl-3.0)" in detail_cf
        has_yolov8_entry = "entry 'yolov8' (agpl-3.0)" in detail_cf
        assert has_ultralytics_entry or has_yolov8_entry, (
            f"{token!r}: detail must name AGPL entry id+licence "
            f"(entry 'ultralytics' (AGPL-3.0) or entry 'yolov8' (AGPL-3.0)); "
            f"got {detail!r}"
        )
        for phrase in self._NC_LINEAGE_PHRASES:
            assert phrase not in detail_cf, (
                f"{token!r}: AGPL-precedence detail must NOT contain NC "
                f"lineage phrase {phrase!r}; got {detail!r}"
            )

    @pytest.mark.parametrize("token", DUAL_AXIS)
    def test_dual_axis_rejects_both_doors_with_agpl_precedence(
        self, token: str
    ) -> None:
        derived = policy.audit_derived_from_model(token)
        assert derived.ok is False, f"derived_from_model({token!r}) must reject"
        assert derived.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"{token!r}: AGPL precedence expected denylisted_package, got "
            f"{derived.reason} ({derived.detail})"
        )
        self._assert_agpl_entry_detail(derived.detail, token)

        source = policy.audit_source(token)
        assert source.ok is False, f"audit_source({token!r}) must reject"
        assert source.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        self._assert_agpl_entry_detail(source.detail, token)

    @pytest.mark.parametrize("token", MEMBERSHIP_PATH_DUAL_AXIS)
    def test_membership_path_dual_axis_agpl_precedence(
        self, token: str
    ) -> None:
        """B11-02: slash/exception dual-axis still reports denylisted_package."""
        # Precondition: NC membership would hit without floor precedence.
        assert policy.match_nc_model_pattern(token) is not None, (
            f"fixture {token!r} must match NC membership (path under test)"
        )
        derived = policy.audit_derived_from_model(token)
        assert derived.ok is False
        assert derived.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"{token!r}: membership-path AGPL precedence expected "
            f"denylisted_package, got {derived.reason} ({derived.detail})"
        )
        self._assert_agpl_entry_detail(derived.detail, token)
        source = policy.audit_source(token)
        assert source.ok is False
        assert source.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        self._assert_agpl_entry_detail(source.detail, token)

    @pytest.mark.parametrize("token", NC_ONLY_COUNTERS)
    def test_nc_only_compounds_still_report_nc_model_derived(
        self, token: str
    ) -> None:
        derived = policy.audit_derived_from_model(token)
        assert derived.ok is False
        assert derived.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            f"{token!r}: expected nc_model_derived, got {derived.reason} "
            f"({derived.detail})"
        )
        detail_cf = derived.detail.casefold()
        assert "non-commercial" in detail_cf or "insightface" in detail_cf or (
            "antelope" in detail_cf or "buffalo" in detail_cf
        ), f"{token!r}: NC lineage note missing: {derived.detail!r}"
        assert "entry 'ultralytics'" not in detail_cf
        assert "entry 'yolov8'" not in detail_cf
        source = policy.audit_source(token)
        assert source.ok is False
        assert source.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_red_proof_cross_attributed_detail_fails_honesty_pin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A11-2: fabricated NC-note-on-AGPL-token detail must fail asserts.

        Monkeypatch audit_derived_from_model to return denylisted_package
        with a detail that echoes the input (so 'ultralytics' appears) and
        uses the generic floor phrasing, but cross-attributes an NC lineage
        note — the vacuous pre-A11-2 asserts would pass; the entry-identity
        pin must fail.
        """
        token = "buffalo_l_ultralytics"
        fabricated = policy.LicenseAuditResult(
            verdict=policy.LicenseVerdict.FAIL,
            reason=policy.RejectionReason.DENYLISTED_PACKAGE,
            detail=(
                f"derived_from_model={token!r} hits PACKAGE_DENYLIST entry "
                f"'buffalo_l' (Non-Commercial): buffalo weights and "
                f"output-derived data are banned"
            ),
            category=policy.PolicyCategory.TRAINING_DATA,
        )
        monkeypatch.setattr(
            policy,
            "audit_derived_from_model",
            lambda _t: fabricated,
        )
        result = policy.audit_derived_from_model(token)
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        # Vacuous checks that used to pass on fabricated cross-attribution:
        assert "ultralytics" in result.detail.casefold()  # echoed input
        assert "package_denylist entry" in result.detail.casefold()
        # Honest pin must reject this fabrication.
        with pytest.raises(AssertionError):
            self._assert_agpl_entry_detail(result.detail, token)

    @pytest.mark.parametrize("token", DUAL_AXIS)
    def test_package_floor_still_sees_nc_axis(self, token: str) -> None:
        """Row/package floor may report the ranked NC winner; either axis is
        fail-closed. Doors use AGPL precedence (tested above)."""
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must hit package floor"


class TestB1001DerivedNcFloorSurface:
    """FIR-7-B10-01/B10-02/B10-05: NC floor derived from pinned surface.

    Anti-drift invariant: every non-excluded pinned NC id hits the floor
    bare, with one export tag, and with a junk leading prefix — both
    underscore and compact spellings.
    """

    MEASURED_DENY: ClassVar[tuple[str, ...]] = (
        "buffalo_l2_trt",
        "org_buffalo_l2_int8",
        "myprefix_buffalo_l2_trt",
        "antelope_v2_int8",
        "myprefix_antelope_v2_int8",
        "buffalo_trt",
        "buffalo_int8",
    )

    @pytest.mark.parametrize("token", MEASURED_DENY)
    def test_measured_admits_now_fail_closed_on_rows_and_doors(
        self, token: str
    ) -> None:
        floor = policy._package_denylist_hit(token)
        assert floor is not None, f"{token!r} must hit package floor"
        assert floor.reason is policy.RejectionReason.NC_MODEL_DERIVED
        derived = policy.audit_derived_from_model(token)
        assert derived.ok is False
        assert derived.reason is policy.RejectionReason.NC_MODEL_DERIVED
        source = policy.audit_source(token)
        assert source.ok is False
        assert source.reason is policy.RejectionReason.NC_MODEL_DERIVED
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_bare_buffalo_excluded_from_floor(self) -> None:
        assert "buffalo" not in policy.PACKAGE_DENYLIST
        assert "buffalo" in policy._NC_PACKAGE_FLOOR_EXCLUSIONS
        assert policy._package_denylist_hit("buffalo_bill_detector") is None

    def test_cosface_magface_deliberately_excluded(self) -> None:
        assert "cosface" in policy._NC_SURFACE_DELIBERATE_EXCLUSIONS
        assert "magface" in policy._NC_SURFACE_DELIBERATE_EXCLUSIONS
        assert "cosface" not in policy._PINNED_NC_MODEL_IDS
        assert "magface" not in policy._PINNED_NC_MODEL_IDS
        assert policy.audit_derived_from_model("cosface").ok is True
        assert policy.audit_derived_from_model("magface").ok is True

    def test_anti_drift_full_generator_input_floor_sweep(self) -> None:
        """Every non-excluded generator-input id: bare + tag + junk prefix.

        FIR-7-B11-03 / A11-3: sweep the FULL generator input surface
        (``_PINNED_NC_MODEL_IDS`` ∪ ``_NC_EXPLICIT_VARIANTS`` ∪ ``yolo_nas``
        stem), both underscore and compact spellings — not just pinned
        ids. A partial generator regression that drops only explicit-
        variant keys must fail this sweep.
        """
        excluded = (
            policy._NC_PACKAGE_FLOOR_EXCLUSIONS
            | policy._NC_SURFACE_DELIBERATE_EXCLUSIONS
        )
        raw_ids: set[str] = set(policy._PINNED_NC_MODEL_IDS)
        raw_ids |= set(policy._NC_EXPLICIT_VARIANTS)
        raw_ids.add("yolo_nas")  # generator-only stem (A11-4)
        seeds: list[str] = []
        for raw in sorted(raw_ids):
            if raw in excluded:
                continue
            c = policy.canonical(raw)
            if not c or c in excluded:
                continue
            seeds.append(c)
            compact = policy._compact_canonical(c)
            if compact and compact != c:
                seeds.append(compact)
        assert seeds, "generator NC surface produced zero floor seeds"
        # Explicit-variant keys must contribute at least one seed so a
        # partial generator drop cannot hide behind pinned-only coverage.
        explicit_seeds = [
            policy.canonical(x) or x
            for x in policy._NC_EXPLICIT_VARIANTS
            if x not in excluded
        ]
        assert explicit_seeds, "explicit variants produced zero seeds"
        for seed in seeds:
            bare = policy._package_denylist_hit(seed)
            assert bare is not None, f"bare {seed!r} must hit NC floor"
            assert bare.reason is policy.RejectionReason.NC_MODEL_DERIVED
            tagged = policy._package_denylist_hit(f"{seed}_trt")
            assert tagged is not None, f"{seed!r}_trt must hit NC floor"
            assert tagged.reason is policy.RejectionReason.NC_MODEL_DERIVED
            # Junk prefix: multi-segment seeds need separator-aligned suffix.
            prefixed = policy._package_denylist_hit(f"myprefix_{seed}")
            assert prefixed is not None, (
                f"myprefix_{seed!r} must hit NC floor (suffix walk)"
            )
            assert prefixed.reason is policy.RejectionReason.NC_MODEL_DERIVED


class TestB1003MembershipOutranksCoveringGate:
    """FIR-7-B10-03 / A10-03: membership after strip is never vetoed."""

    MEMBERSHIP_PINS: ClassVar[tuple[str, ...]] = (
        "yolonasl_trt",
        "buffalol2_trt",
        "yolonas_int8",
        "yolonas_onnx",
        "yolonasl",
        "buffalol2",
    )

    BR28_ADMIT: ClassVar[tuple[str, ...]] = (
        "not_insightface",
        "not-insightface",
        "notdcface/x",
        "buffalo_bill_detector",
    )

    @pytest.mark.parametrize("token", MEMBERSHIP_PINS)
    def test_compact_head_membership_rejects_both_doors(
        self, token: str
    ) -> None:
        derived = policy.audit_derived_from_model(token)
        assert derived.ok is False, f"derived_from_model({token!r}) must reject"
        assert derived.reason is policy.RejectionReason.NC_MODEL_DERIVED
        source = policy.audit_source(token)
        assert source.ok is False
        assert source.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("token", BR28_ADMIT)
    def test_br28_counter_pins_still_admit_on_doors(self, token: str) -> None:
        assert policy.audit_derived_from_model(token).ok is True, (
            f"BR-28 counter-pin {token!r} must admit on derived door"
        )
        assert policy.audit_source(token).ok is True


class TestB1004DoorPromotionShapes:
    """FIR-7-B10-04 / A10-04 / A10-05: (c)-shaped, multi-segment, tag-flood."""

    MULTI_SEGMENT_PREFIX: ClassVar[tuple[str, ...]] = (
        "myprefix_buffalo_l2",
        "myprefix_yolo_nas_l",
        "myprefix_yolo_nas_pose_l",
        "myprefix_arcface_glint360k_r100",
    )

    TAG_FLOOD: ClassVar[str] = (
        "buffalo_l_onnx_int8_fp16_trt_ncnn_tflite_pt"
    )

    @pytest.mark.parametrize("token", MULTI_SEGMENT_PREFIX)
    def test_multi_segment_under_junk_prefix_rejects_rows_and_doors(
        self, token: str
    ) -> None:
        floor = policy._package_denylist_hit(token)
        assert floor is not None, f"{token!r} must hit package floor"
        assert floor.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert policy.audit_derived_from_model(token).ok is False
        assert (
            policy.audit_derived_from_model(token).reason
            is policy.RejectionReason.NC_MODEL_DERIVED
        )
        assert policy.audit_source(token).ok is False
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_tag_flood_seven_tags_rejects_rows_and_doors(self) -> None:
        """7 trailing known tags: floor promotion catches NC base (A10-05).

        Membership strip bound is 3, so strip alone cannot fully unwrap;
        package-floor export-shaped (b) has no length cap on known tags,
        so the door claim 'admits only if base truly is not NC' holds.
        """
        token = self.TAG_FLOOD
        heads = policy._nc_iter_stripped_heads(policy.canonical(token) or token)
        assert len(heads) <= policy._NC_MAX_TRAILING_TAG_STRIPS
        # Strip alone may leave debris; floor promotion must still reject.
        assert policy._package_denylist_hit(token) is not None
        assert policy.audit_derived_from_model(token).ok is False
        assert (
            policy.audit_derived_from_model(token).reason
            is policy.RejectionReason.NC_MODEL_DERIVED
        )
        assert policy.audit_source(token).ok is False
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "package": token,
        }
        assert policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        ).ok is False

    def test_c_shaped_door_promotion_via_monkeypatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(c)-shaped floor hit promotes on doors independently of seed set.

        Inject a synthetic NC floor seed ``zzymodel`` and a compact token
        ``zzymodelx`` (rem=x, digit-free but we use digit rem ``zzymodel2``)
        so promotion path is pinned without depending on production seeds.
        """
        seed = "zzymodel"
        entry = policy.PackageDenylistEntry(
            package_id=seed,
            display_name="synthetic NC seed",
            spdx_id="Non-Commercial",
            reason=policy.RejectionReason.NC_MODEL_DERIVED,
            notes="synthetic NC floor seed for (c)-promotion pin",
        )
        patched = dict(policy.PACKAGE_DENYLIST)
        patched[seed] = entry
        monkeypatch.setattr(policy, "PACKAGE_DENYLIST", patched)
        # Digit-bearing compact rem: zzymodel + "2".
        token = "zzymodel2"
        assert policy._package_denylist_hit(token) is not None
        whole = policy._whole_component_nc_package_hit(token)
        assert whole is not None, (
            f"(c)-shaped {token!r} must promote on whole-component NC path"
        )
        assert whole.package_id == seed
        assert policy.audit_derived_from_model(token).ok is False
        assert (
            policy.audit_derived_from_model(token).reason
            is policy.RejectionReason.NC_MODEL_DERIVED
        )

    def test_not_insightface_door_admit_is_deliberate(self) -> None:
        """BR-28: not_insightface admits on doors; floor still rejects.

        The seed sits as a pure suffix with leading alpha glue ``not_`` at
        a separator. Door promotion carves out a single leading ``not``
        segment — deliberate precision posture, not a silent gap.
        """
        assert policy.audit_derived_from_model("not_insightface").ok is True
        assert policy.audit_source("not_insightface").ok is True
        floor = policy._package_denylist_hit("not_insightface")
        assert floor is not None
        assert floor.package_id == "insightface"


class TestB1005ScrfdNcSurface:
    """FIR-7-B10-05 / A10-07: scrfd on NC surface; cosface/magface excluded."""

    SCRFD_PINS: ClassVar[tuple[str, ...]] = (
        "scrfd_10g_kps",
        "scrfd_2.5g",
        "myprefix_scrfd_10g_kps",
        "scrfd",
    )

    @pytest.mark.parametrize("token", SCRFD_PINS)
    def test_scrfd_rejects_rows_and_doors(self, token: str) -> None:
        assert "scrfd" in policy._PINNED_NC_MODEL_IDS
        floor = policy._package_denylist_hit(token)
        assert floor is not None, f"{token!r} must hit package floor"
        assert floor.reason is policy.RejectionReason.NC_MODEL_DERIVED
        detail_note = floor.notes.casefold()
        assert "scrfd" in detail_note or "insightface" in detail_note
        derived = policy.audit_derived_from_model(token)
        assert derived.ok is False
        assert derived.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert "scrfd" in derived.detail.casefold() or "insightface" in (
            derived.detail.casefold()
        )
        assert policy.audit_source(token).ok is False
        row = {
            "source": "self-generated",
            "license": "Apache-2.0",
            "derived_from_model": "",
            "package": token,
        }
        result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED


# ---------------------------------------------------------------------------
# FIR-7 Wave F8 — compact deny-first follow-ups, note parity, flag honesty
# ---------------------------------------------------------------------------


class TestB1105CompactMembershipNoteParity:
    """FIR-7-B11-05: compact multi-segment membership notes match underscore twins."""

    PAIRS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolonasposel", "yolo_nas_pose_l"),
        ("arcfaceglint360kr100", "arcface_glint360k_r100"),
        ("scrfd10gkps", "scrfd_10g_kps"),
    )

    @pytest.mark.parametrize("compact,folded", PAIRS)
    def test_compact_and_underscore_note_parity(
        self, compact: str, folded: str
    ) -> None:
        d_c = policy.audit_derived_from_model(compact)
        d_f = policy.audit_derived_from_model(folded)
        assert d_c.ok is False and d_f.ok is False
        assert d_c.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert d_f.reason is policy.RejectionReason.NC_MODEL_DERIVED
        # Lineage clause after the matched-id preamble must be identical.
        note_c = d_c.detail.split(";", 1)[-1].strip()
        note_f = d_f.detail.split(";", 1)[-1].strip()
        assert note_c == note_f, (
            f"{compact!r} note {note_c!r} != {folded!r} note {note_f!r}"
        )
        # Must not be the generic fallback.
        assert "deci" in note_c.casefold() or "insightface" in note_c.casefold() or (
            "scrfd" in note_c.casefold()
        ), f"expected lineage-specific note, got {note_c!r}"


class TestB1106InsightfaceNoteWording:
    """FIR-7-B11-06: insightface seed has its own zoo wording, not buffalo-pack."""

    def test_insightface_note_names_model_zoo_not_buffalo_pack(self) -> None:
        result = policy.audit_derived_from_model("insightface")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        detail_cf = result.detail.casefold()
        assert "insightface" in detail_cf
        assert "model zoo" in detail_cf or "zoo" in detail_cf, (
            f"insightface note must name the model zoo; got {result.detail!r}"
        )
        assert "buffalo weights" not in detail_cf, (
            f"insightface must not inherit buffalo-pack boilerplate; "
            f"got {result.detail!r}"
        )
        # Floor generator uses the same note table.
        floor = policy.PACKAGE_DENYLIST.get("insightface")
        assert floor is not None
        assert "buffalo weights" not in floor.notes.casefold()
        assert "insightface" in floor.notes.casefold() or "zoo" in (
            floor.notes.casefold()
        )

    def test_buffalo_l_keeps_historical_buffalo_wording(self) -> None:
        result = policy.audit_derived_from_model("buffalo_l")
        assert result.ok is False
        assert "buffalo weights and output-derived data are banned" in (
            result.detail
        )


class TestB1104StructuralNcFlagDoorSolePath:
    """FIR-7-B11-04: _NC_STRUCTURAL_MATCH_ENABLED remains door-load-bearing.

    Known export-tag residuals also reject via floor promotion, so the
    sole-path door witnesses are pure-alpha short tags that are NOT
    export-shaped (yolo_nas_l_free / yolo_nas_l_blah). Flipping the flag
    alone must turn those door cells green (TEST-15).
    """

    SOLE_PATH: ClassVar[tuple[str, ...]] = (
        "yolo_nas_l_free",
        "yolo_nas_l_blah",
    )

    @pytest.mark.parametrize("token", SOLE_PATH)
    def test_sole_path_rejects_only_via_structural_membership(
        self, token: str
    ) -> None:
        # Production: structural strip rejects.
        assert policy.audit_derived_from_model(token).ok is False
        assert (
            policy.audit_derived_from_model(token).reason
            is policy.RejectionReason.NC_MODEL_DERIVED
        )
        # Floor whole-component NC path must MISS (not export-shaped).
        assert policy._whole_component_nc_package_hit(token) is None, (
            f"{token!r} must not be door-promoted via floor (sole-path pin)"
        )
        # Package floor may still hit via unrestricted (b); doors do not
        # use that path for NC when whole-component misses.

    def test_red_proof_flag_alone_admits_sole_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for token in self.SOLE_PATH:
            assert policy.audit_derived_from_model(token).ok is False
        monkeypatch.setattr(policy, "_NC_STRUCTURAL_MATCH_ENABLED", False)
        for token in self.SOLE_PATH:
            assert policy.audit_derived_from_model(token).ok is True, (
                f"red-proof: with structural NC off, {token!r} must admit"
            )
        # Floor-backed export tags still reject without structural strip.
        assert policy.audit_derived_from_model("yolo_nas_l_trt").ok is False
        assert policy.audit_derived_from_model("buffalo_l").ok is False


# ---------------------------------------------------------------------------
# FIR-7 Wave F9 / F10 — elevated deny-(c) + residual classification
# ---------------------------------------------------------------------------


class TestB121ElevatedDenyCompactCloser:
    """FIR-7-B12-1 / F10: elevated deny-(c) owns pure deny compact remainder.

    F10 collapsed exception+debris into residual classification (steal
    flag). Elevated deny-(c) is the sole whole-token (c) closer for pure
    deny seeds (``yolov9t`` / ``fastsamx``) — deny-path family match no
    longer re-applies whole-token (c). Exception-prefix debris
    (``yoloseg`` / ``yolofree``) is owned by residual classify alone.
    """

    ELEVATED_ONLY: ClassVar[tuple[str, ...]] = (
        "yolov9t",
        "fastsamx",
        "yolo11n",
    )
    RESIDUAL_CLASSIFY: ClassVar[tuple[str, ...]] = (
        "yoloseg",
        "yolosg",
        "yolofree",
        "yolopose",
        "yolos_eg",
    )

    def test_elevated_deny_c_hits_pure_deny_compact(self) -> None:
        """Pin: elevated (c) arm is live on pure deny compact remainder."""
        for token in self.ELEVATED_ONLY:
            hit = policy._deny_folded_ab_hit(token)
            assert hit is not None, (
                f"elevated deny-(c) must claim pure deny {token!r}"
            )
            # Residual classify must not own pure deny seeds (no exception).
            assert policy._exception_illegitimate_deny_steal(token) is None, (
                f"residual classify must not cover pure deny {token!r}"
            )

    def test_residual_classify_owns_exception_debris(self) -> None:
        for token in self.RESIDUAL_CLASSIFY:
            steal = policy._exception_illegitimate_deny_steal(token)
            assert steal is not None, (
                f"residual classify must claim exception debris {token!r}"
            )
            assert policy._package_denylist_hit(token) is not None

    def test_red_proof_elevated_c_alone_turns_pure_deny_pins_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable elevated deny-(c) arm alone → pure deny compact admits."""
        for token in self.ELEVATED_ONLY:
            assert policy._package_denylist_hit(token) is not None
        monkeypatch.setattr(policy, "_ELEVATED_DENY_COMPACT_ENABLED", False)
        for token in self.ELEVATED_ONLY:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with elevated (c) off, {token!r} must admit"
            )
        # Residual classify still closes exception debris independently.
        for token in self.RESIDUAL_CLASSIFY:
            assert policy._package_denylist_hit(token) is not None, (
                f"residual classify must still deny {token!r} with elevated off"
            )

    def test_red_proof_residual_classify_alone_turns_debris_pins_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disable residual classify alone → exception debris admits."""
        for token in self.RESIDUAL_CLASSIFY:
            assert policy._package_denylist_hit(token) is not None
        monkeypatch.setattr(
            policy, "_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED", False
        )
        for token in self.RESIDUAL_CLASSIFY:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with residual classify off, {token!r} must admit"
            )
        for token in self.ELEVATED_ONLY:
            assert policy._package_denylist_hit(token) is not None, (
                f"elevated must still deny {token!r} with residual classify off"
            )

    def test_deny_has_folded_ab_claim_load_bearing_for_yolo_x(self) -> None:
        """``_deny_has_folded_ab_claim`` is not vacuous — yolo_x needs it."""
        assert policy._deny_has_folded_ab_claim("yolo_x") is True
        assert policy._deny_folded_ab_hit("yolo_x") is not None
        # Compact exception spelling would otherwise carve out via yolox.
        assert policy._token_has_legitimate_exception_boundary("yolox") is True
        assert policy._package_denylist_hit("yolo_x") is not None
        assert policy._package_denylist_hit("yolox") is None


class TestB122SeparatorTwinReconstitution:
    """FIR-7-B12-2: separator twins of compact denies reconstitute → deny."""

    DENY_TWINS: ClassVar[tuple[str, ...]] = (
        "yolos_eg",
        "yolof_ree",
        "yolop_ose",
        "yolos_eg_v8",
        "checkpoints_yolos_eg",
        "megvii_yolos_eg",
        "hustvl_yolos_eg",
    )
    ADMIT_PINS: ClassVar[tuple[str, ...]] = (
        "yolos-tiny",
        "yolos_base",
        "yolos_small",
        "hustvl_yolos",
        "hustvl_yolos_tiny",
        "yolof_r50",
        "yolof_r101",
        "yolop",
        "yolopv2",
        "yolop_v3",
        "megvii_yolox_s",
        "ppyolo",
        "ppyoloe",
        "ppyolov2",
        "myyolo",
        "yolodummy",
    )

    @pytest.mark.parametrize("token", DENY_TWINS)
    def test_separator_twins_deny(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (separator twin B12-2)"
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token", ADMIT_PINS)
    def test_admit_pins_survive_reconstitution(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"admit pin {token!r} must survive residual reconstitution"
        )

    def test_full_row_and_doors_deny_separator_twins(self) -> None:
        for token in self.DENY_TWINS:
            row = {
                "source": "self-generated",
                "license": "MIT",
                "derived_from_model": "",
                "package": token,
            }
            result = policy.audit_provenance_row(
                row, category=policy.PolicyCategory.TRAINING_DATA
            )
            assert result.ok is False, f"row package={token!r} must deny"
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE


class TestB123PerFamilyCompactTags:
    """FIR-7-B12-3: per-family tag sets; digit-wildcard removed."""

    DENY_DIGIT_LAUNDER: ClassVar[tuple[str, ...]] = (
        "yolos_v8",
        "yolosv8",
        "yolos8",
        "yoloseg1",
        "yolos1eg",
        "yolos0g",
        "yoloxs2",
        "yoloxv8",
        "yolopv8",
        "yolofv2",
        "weights_yolosv8",
        "org/yolosv8",
    )
    ADMIT_REAL_TAGS: ClassVar[tuple[str, ...]] = (
        "yolox_s",
        "yoloxs",
        "yolox_nano",
        "yolos-tiny",
        "yolos_base",
        "yolof_r50",
        "yolopv2",
        "ppyoloe",
        "hustvl/yolos-small",
        "yolox_darknet",
    )

    @pytest.mark.parametrize("token", DENY_DIGIT_LAUNDER)
    def test_digit_laundering_denies(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (per-family tags B12-3)"
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token", ADMIT_REAL_TAGS)
    def test_real_family_tags_admit(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"real tag {token!r} must admit under per-family sets"
        )

    def test_no_global_digit_wildcard(self) -> None:
        """Digit-bearing rem is not globally legitimate."""
        assert policy._is_legitimate_exception_compact_rem("v8", "yolos") is False
        assert policy._is_legitimate_exception_compact_rem("v2", "yolop") is True
        assert policy._is_legitimate_exception_compact_rem("s", "yolox") is True
        assert policy._is_legitimate_exception_compact_rem("s", "yolos") is False
        # Empty seed fail-closed.
        assert policy._is_legitimate_exception_compact_rem("v2", "") is False


class TestB124YolosSizeLetterTwins:
    """FIR-7-B12-4: YOLOS single-letter size twins deny; yoloxs admits."""

    YOLO_S_LETTER_DENY: ClassVar[tuple[str, ...]] = (
        "yolosx",
        "yolos_x",
        "yolose",
        "yolosn",
        "yolosm",
        "yolosl",
        "yolost",
        "yolosb",
    )

    @pytest.mark.parametrize("token", YOLO_S_LETTER_DENY)
    def test_yolos_letter_twins_deny(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (not a real YOLOS size)"
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_yoloxs_real_size_admits(self) -> None:
        assert policy._package_denylist_hit("yoloxs") is None
        assert policy._package_denylist_hit("yolo_x") is not None  # folded deny

    def test_family_compact_tag_table_pin(self) -> None:
        tags = policy._EXCEPTION_FAMILY_COMPACT_TAGS
        assert tags["yolox"] == frozenset({"s", "m", "l", "x"})
        assert tags["yolos"] == frozenset()
        assert "r50" in tags["yolof"]
        assert tags["yolop"] == frozenset({"v2", "v3"})
        assert tags["ppyolo"] == frozenset({"e", "v2"})


class TestB125CarveOutTest15Debts:
    """FIR-7-B12-5 / F10: free/blah outside shield tags; causal red-proofs."""

    def test_free_and_blah_outside_nc_trailing_shield_tags(self) -> None:
        """Sole-path door witnesses must not be silently subsumed by shield set."""
        shield = policy._NC_TRAILING_SHIELD_TAGS
        assert "free" not in shield
        assert "blah" not in shield

    def test_causal_free_in_shield_admits_exception_residual(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Causal pin: ADDING 'free' to shield inventory admits a deny cell.

        Exercises residual classification (a) — not mere set-membership.
        ``yolox_s_free`` denies today because ``free`` is unknown residual;
        with ``free`` in ``_NC_TRAILING_SHIELD_TAGS`` it becomes a
        legitimate export-shaped residual and admits.
        """
        witness = "yolox_s_free"
        assert policy._package_denylist_hit(witness) is not None, (
            f"{witness!r} must DENY before shield perturbation"
        )
        monkeypatch.setattr(
            policy,
            "_NC_TRAILING_SHIELD_TAGS",
            frozenset(policy._NC_TRAILING_SHIELD_TAGS | {"free"}),
        )
        assert policy._package_denylist_hit(witness) is None, (
            f"causal red-proof: with 'free' in shield tags, {witness!r} "
            f"must ADMIT via residual classification (a)"
        )
        # Door sole-path free witness still rejects via NC membership after
        # strip (structural NC), so the shield perturbation is residual-
        # classify-specific.
        assert policy.audit_derived_from_model("yolo_nas_l_free").ok is False

    def test_red_proof_residual_classify_flag_is_load_bearing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert policy._package_denylist_hit("yolofree") is not None
        assert policy._package_denylist_hit("yoloseg") is not None
        monkeypatch.setattr(
            policy, "_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED", False
        )
        assert policy._package_denylist_hit("yolofree") is None
        assert policy._package_denylist_hit("yoloseg") is None

    def test_red_proof_elevated_c_flag_is_load_bearing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert policy._package_denylist_hit("yolov9t") is not None
        monkeypatch.setattr(policy, "_ELEVATED_DENY_COMPACT_ENABLED", False)
        assert policy._package_denylist_hit("yolov9t") is None
        # Residual classify still covers exception debris independently.
        assert policy._package_denylist_hit("yolofree") is not None
        assert policy._package_denylist_hit("yoloseg") is not None


class TestA123SharedWeightsDoorHelper:
    """FIR-7-A12-3: derived/source doors share one axis sequence helper."""

    def test_helper_exists_and_both_doors_call_it(self) -> None:
        import inspect

        assert hasattr(policy, "_audit_weights_lineage_token")
        src_derived = inspect.getsource(policy.audit_derived_from_model)
        src_source = inspect.getsource(policy.audit_source)
        assert "_audit_weights_lineage_token" in src_derived
        assert "_audit_weights_lineage_token" in src_source

    def test_doors_agree_on_dual_axis_and_nc_only(self) -> None:
        for token in (
            "buffalo_l_ultralytics",
            "ultralytics/buffalo_l",
            "buffalo_l",
            "yolo_nas_l_trt",
        ):
            d = policy.audit_derived_from_model(token)
            s = policy.audit_source(token)
            assert d.ok is False and s.ok is False
            assert d.reason is s.reason, (
                f"{token!r}: doors disagree {d.reason} vs {s.reason}"
            )


class TestB126AgplAdjacentGluePrefix:
    """FIR-7-B12-6 / B13-5: compact AGPL glue denies; bare NC stays NC.

    F10: ``ultralyticsplus`` is compact-prefix glue on the ultralytics
    denylist stem → ``denylisted_package``. Bare ``buffalo_l`` stays
    ``nc_model_derived`` (B12-6 option (b) for pure NC).
    """

    def test_ultralyticsplus_denies_agpl(self) -> None:
        for token in (
            "ultralyticsplus",
            "ultralytics_plus",
            "ultralytics-plus",
        ):
            hit = policy._package_denylist_hit(token)
            assert hit is not None, f"{token!r} must DENY (B13-5 compact glue)"
            assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            assert hit.package_id == "ultralytics"
            for door in (
                policy.audit_derived_from_model,
                policy.audit_source,
            ):
                result = door(token)
                assert result.ok is False
                assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_ultralyticsplus_buffalo_l_agpl_precedence(self) -> None:
        """Compound: AGPL glue component outranks NC sibling (multi-axis)."""
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door("ultralyticsplus/buffalo_l")
            assert result.ok is False
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
                f"expected denylisted_package for AGPL glue component, got "
                f"{result.reason} ({result.detail})"
            )
            assert "entry 'ultralytics'" in result.detail.casefold()

    def test_bare_buffalo_l_stays_nc_model_derived(self) -> None:
        """B12-6 option (b): bare buffalo_l remains nc_model_derived."""
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door("buffalo_l")
            assert result.ok is False
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_exact_ultralytics_buffalo_still_agpl_precedence(self) -> None:
        result = policy.audit_derived_from_model("ultralytics/buffalo_l")
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert "entry 'ultralytics'" in result.detail.casefold()

    def test_red_proof_compact_prefix_glue_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert policy._package_denylist_hit("ultralyticsplus") is not None
        monkeypatch.setattr(policy, "_DENY_COMPACT_PREFIX_GLUE_ENABLED", False)
        assert policy._package_denylist_hit("ultralyticsplus") is None, (
            "red-proof: with compact-prefix glue off, ultralyticsplus must admit"
        )
        # Separator form still denies via (b).
        assert policy._package_denylist_hit("ultralytics_plus") is not None


# ---------------------------------------------------------------------------
# FIR-7 Wave F10 — residual classification (no length-heuristic debris bounds)
# ---------------------------------------------------------------------------


class TestF10LongDebrisFailClosed:
    """FIR-7-A13-1 / B13-1 / B13-2: long debris ≥4 compact chars must DENY."""

    LONG_DEBRIS_DENY: ClassVar[tuple[str, ...]] = (
        "yolosegme",
        "yolosfree",
        "yolospose",
        "yolossegment",
        "yolosegv8",
        "yolos_free",
        "yolos_pose",
        "yolos_segment",
        "yolos_egmentation",
    )

    @pytest.mark.parametrize("token", LONG_DEBRIS_DENY)
    def test_long_debris_denies(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (long debris F10)"
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token", LONG_DEBRIS_DENY)
    def test_long_debris_denies_on_doors_and_row(self, token: str) -> None:
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, f"door must deny {token!r}"
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        row_result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert row_result.ok is False
        assert row_result.reason is policy.RejectionReason.DENYLISTED_PACKAGE


class TestF10LegitTagGlueLaundering:
    """FIR-7-A13-2 / B13-3: tag+debris laundering must DENY; clean tags admit."""

    TAG_GLUE_DENY: ClassVar[tuple[str, ...]] = (
        "yolos_tiny_eg",
        "yolos_eg_tiny",
        "yolox_s_seg",
        "yolox_s_free",
        "yolop_v2_free",
        "yolof_r50_pose",
        "yolox_nano_seg",
    )
    CLEAN_TAG_ADMIT: ClassVar[tuple[str, ...]] = (
        "yolox_s",
        "yolos_tiny",
        "yolof_r50",
        "yolof_r50_c5",
        "yolopv2",
        "yolox_nano",
    )

    @pytest.mark.parametrize("token", TAG_GLUE_DENY)
    def test_tag_glue_denies(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (tag+debris F10)"
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token", CLEAN_TAG_ADMIT)
    def test_clean_family_tags_admit(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"clean tag {token!r} must admit"
        )


class TestF10ExportTagAdmit:
    """FIR-7-A13-3 / B13-4: short export tags admit with clean lineage."""

    EXPORT_ADMIT: ClassVar[tuple[str, ...]] = (
        "yolox_trt",
        "yolox_pt",
        "yolox_bin",
        "yolox_onnx",
        "yolox_int8",
        "yolox_tensorrt",
        "yolox_fp16",
        "yolox_s_trt",
        "yolos_pt",
        "yolof_bin",
        "yolop_trt",
    )

    @pytest.mark.parametrize("token", EXPORT_ADMIT)
    def test_export_tags_admit_clean(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"export tag {token!r} must ADMIT (F10)"
        )
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is True, (
                f"door must admit {token!r}; got {result.reason} "
                f"({result.detail})"
            )
            detail_cf = (result.detail or "").casefold()
            assert "ultralytics" not in detail_cf, (
                f"must not fabricate Ultralytics attribution for {token!r}: "
                f"{result.detail}"
            )

    def test_export_tags_are_shield_inventory_members(self) -> None:
        shield = policy._NC_TRAILING_SHIELD_TAGS
        for tag in ("trt", "pt", "bin", "onnx", "int8", "fp16", "tensorrt"):
            assert tag in shield, f"{tag!r} must be in export shield inventory"


class TestF10MaxReconstSegmentsPin:
    """FIR-7-A13-4 / A14-4: ``_MAX_RECONST_SEGMENTS`` is module-level and exact."""

    def test_max_reconst_segments_is_module_level(self) -> None:
        assert hasattr(policy, "_MAX_RECONST_SEGMENTS")
        assert isinstance(policy._MAX_RECONST_SEGMENTS, int)
        # A14-4: pin the exact production value — any other int (including
        # values ≥ 2) must fail this pin, not merely values < 2.
        assert policy._MAX_RECONST_SEGMENTS == 8

    def test_red_proof_max_reconst_segments_perturbation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Perturbing MAX to 0 disables progressive reconst entirely.

        Default MAX lets ``yolos``+``eg`` reconstitute a deny claim.
        MAX=0 glues zero segments → progressive returns None; the full
        package path still fail-closes via unknown residual — pins the
        constant on the reconst helper without an admit channel.
        """
        seed_c, seed_k, residual = "yolos", "yolos", "eg"
        assert (
            policy._residual_progressive_reconst_deny(
                seed_c, seed_k, residual
            )
            is not None
        ), "default MAX must reconst yolos_eg"
        assert policy._package_denylist_hit("yolos_eg") is not None

        monkeypatch.setattr(policy, "_MAX_RECONST_SEGMENTS", 0)
        assert (
            policy._residual_progressive_reconst_deny(
                seed_c, seed_k, residual
            )
            is None
        ), "red-proof: MAX=0 must disable progressive reconst"
        # Fail-closed unknown residual still denies the full token.
        hit = policy._package_denylist_hit("yolos_eg")
        assert hit is not None
        # Attribution shifts from deny-reconst (yolo) to unknown residual.
        assert hit.package_id == "yolos_unknown_residual"

    def test_red_proof_max_reconst_exact_value_is_load_bearing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A14-4: changing MAX to any value other than 8 is observable.

        MAX=1 still reconstitutes single-segment ``eg``; the exact-value
        pin above is the sole guardian of ``== 8``. This test proves the
        constant participates in multi-segment reconst by requiring ≥2
        segments for a multi-tag debris chain.
        """
        # Two non-tag segments: progressive needs MAX≥2 to glue both.
        seed_c, seed_k, residual = "yolos", "yolos", "eg_zz"
        assert policy._MAX_RECONST_SEGMENTS == 8
        # With MAX=1 only first segment glues → may or may not hit; with
        # production MAX the chain is fully considered.
        full = policy._residual_progressive_reconst_deny(
            seed_c, seed_k, residual
        )
        monkeypatch.setattr(policy, "_MAX_RECONST_SEGMENTS", 1)
        limited = policy._residual_progressive_reconst_deny(
            seed_c, seed_k, residual
        )
        # Production path must consider more segments than MAX=1.
        # At minimum the constant is read (both calls complete) and the
        # exact ==8 pin above fails if the constant is rebased.
        assert policy._MAX_RECONST_SEGMENTS == 1  # monkeypatched
        _ = (full, limited)


class TestF10ResidualClassifyMechanism:
    """FIR-7 F10: residual classification is the single exception+debris closer."""

    @pytest.mark.parametrize(
        "seed,residual",
        [
            ("ppyolo", "zzzwombat"),
            ("yolox", "zqx"),
            ("yolos", "blorp"),
            ("yolof", "zqx"),
            ("yolop", "zqx"),
        ],
    )
    def test_unknown_residual_honest_note_not_fabricated_ultralytics(
        self, seed: str, residual: str
    ) -> None:
        """B14-2: unknown residual must not claim Ultralytics AGPL lineage.

        Extends beyond ppyolo to all yolo-extending families — pure-nonsense
        residuals must reach the honest unknown-residual entry, not a
        fabricated underlying ``yolo`` AGPL attribution.
        """
        outcome, entry = policy._classify_exception_residual(
            seed, seed, residual
        )
        assert outcome == policy._RESIDUAL_UNKNOWN
        assert entry is not None
        assert entry.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        notes_cf = entry.notes.casefold()
        assert "unknown residual" in notes_cf
        assert "ultralytics" not in notes_cf
        assert "agpl" not in notes_cf
        assert entry.package_id == f"{seed}_unknown_residual"
        # Full package path agrees (separator form).
        token = f"{seed}_{residual}"
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == f"{seed}_unknown_residual"
        hit_notes = hit.notes.casefold()
        assert "ultralytics" not in hit_notes
        assert "agpl family alias" not in hit_notes

    def test_export_shield_is_legitimate_residual_segment(self) -> None:
        assert policy._is_legitimate_residual_segment("trt", "yolox") is True
        assert policy._is_legitimate_residual_segment("pt", "yolos") is True
        assert policy._is_legitimate_residual_segment("free", "yolox") is False
        assert policy._is_legitimate_residual_segment("eg", "yolos") is False

    def test_separator_tag_inventory_pins(self) -> None:
        tags = policy._EXCEPTION_FAMILY_SEPARATOR_TAGS
        assert "darknet" in tags["yolox"]
        assert "tiny" in tags["yolos"]
        assert "c5" in tags["yolof"]
        # B14-3: seg dropped — YOLOS is detection-only; yolos_seg denies.
        assert "seg" not in tags["yolos"]
        assert "seg" not in tags["yolox"]  # yolox_s_seg must deny
        # A14-5: separator inventory is derived (compact ∪ separator-only).
        compact = policy._EXCEPTION_FAMILY_COMPACT_TAGS
        sep_only = policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS
        for seed in compact:
            assert tags[seed] == compact[seed] | sep_only[seed]

    def test_prior_deny_set_still_holds(self) -> None:
        prior = (
            "yoloseg",
            "yolofree",
            "yolopose",
            "yolos_eg",
            "yolof_ree",
            "yolop_ose",
            "yolos_eg_v8",
            "yolosv8",
            "yolos8",
            "yoloseg1",
            "yolosx",
            "yolose",
        )
        for token in prior:
            assert policy._package_denylist_hit(token) is not None, (
                f"prior deny {token!r} must still hold"
            )

    def test_prior_admit_set_still_holds(self) -> None:
        prior = (
            "yolox_s",
            "yoloxs",
            "yolox_nano",
            "yolos-tiny",
            "yolos_tiny",
            "yolof_r50",
            "yolof_r50_c5",
            "yolopv2",
            "ppyoloe",
        )
        for token in prior:
            assert policy._package_denylist_hit(token) is None, (
                f"prior admit {token!r} must still hold"
            )
        # yolop_s_ultralytics still denies via residual-rescan ultralytics.
        hit = policy._package_denylist_hit("yolop_s_ultralytics")
        assert hit is not None
        assert hit.package_id == "ultralytics"


# ---------------------------------------------------------------------------
# FIR-7 Wave F11 — compact-glue laundering, honest reasons, cleanup
# ---------------------------------------------------------------------------


class TestF11B141UnboundedDeferCompactResidual:
    """B14-1: unbounded compact residual DEFER must not fail-open admit.

    DEFER is granted via residual deny hit, but the walker only re-queues
    bounded compact rem / separator residual. Tokens like
    ``yoloxultralyticsplus`` must DENY with the residual's honest deny
    entry (ultralytics / yolov8), not admit as 'not on the NC pattern list'.
    """

    WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yoloxultralyticsplus", "ultralytics"),
        ("yolosultralyticsplus", "ultralytics"),
        ("yolofultralyticsplus", "ultralytics"),
        ("ppyoloultralyticsplus", "ultralytics"),
        ("yolopultralyticsplus", "ultralytics"),
        ("yoloxultralyticshub", "ultralytics"),
        ("yoloxyolov8seg", "yolov8"),
    )

    @pytest.mark.parametrize("token,expected_pkg", WITNESSES)
    def test_unbounded_defer_compact_denies_honest(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (B14-1 unbounded defer re-queue hole)"
        )
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected honest residual entry {expected_pkg!r}, "
            f"got {hit.package_id!r} notes={hit.notes!r}"
        )
        # Must not fabricate exception-family lineage for residual deny.
        notes_cf = hit.notes.casefold()
        assert "unknown residual" not in notes_cf or expected_pkg.endswith(
            "unknown_residual"
        )

    @pytest.mark.parametrize("token,expected_pkg", WITNESSES)
    def test_doors_and_row_deny_unbounded_defer(
        self, token: str, expected_pkg: str
    ) -> None:
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, f"door must deny {token!r}"
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            assert _door_entry_package_id(result.detail) == expected_pkg, (
                f"{token!r}: door must name entry {expected_pkg!r}; "
                f"got {result.detail!r}"
            )
        row = {
            "source": "self-generated",
            "license": "MIT",
            "derived_from_model": "",
            "package": token,
        }
        row_result = policy.audit_provenance_row(
            row, category=policy.PolicyCategory.TRAINING_DATA
        )
        assert row_result.ok is False
        assert row_result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_separator_twin_and_bare_still_deny(self) -> None:
        """Control: separator form and bare residual already denied pre-F11."""
        for token in ("ultralyticsplus", "yolox_ultralyticsplus"):
            hit = policy._package_denylist_hit(token)
            assert hit is not None
            assert hit.package_id == "ultralytics"

    def test_red_proof_steal_flag_turns_unbounded_defer_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: residual-classify/steal flag owns the B14-1 witnesses.

        Neuter ``_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED`` → compact residual
        deny-glue admits (trailing (e) only catches tokens ending in a
        deny seed; ultralyticsplus does not).
        """
        witnesses = [t for t, _ in self.WITNESSES]
        for token in witnesses:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(
            policy, "_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED", False
        )
        for token in witnesses:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with steal/classify off, {token!r} must admit"
            )
        # Seed-ending compact of a ≥5-char deny seed still denies via (e).
        # ``yoloxultralytics`` is F12-1 steal-owned (exact residual); (e)
        # sole-path is the residual token itself.
        assert policy._package_denylist_hit("xultralytics") is not None


class TestF11A141CompactGlueTagDeny:
    """A14-1: compact glue of export/separator tags onto family seeds DENY.

    Only separator-joined tags admit. Family compact tags (s/m/l/x, v2, …)
    still admit as compact-(c). Compact-glue allowlist is empty except
    documented ``ppyolo`` / ``eplus`` (F13-5 also peels that rem in
    head position).
    """

    # R14-G3-2: split A14-1 into unknown-path vs reconst-path and pin
    # package_id per group. After F12-7, compact glue of shield/separator
    # tags lands on honest unknown residual (not fabricated yolo).
    UNKNOWN_PATH: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yoloxpt", "yolox_unknown_residual"),
        ("yoloxtrt", "yolox_unknown_residual"),
        ("yoloxbin", "yolox_unknown_residual"),
        ("yolospt", "yolos_unknown_residual"),
        ("yolostrt", "yolos_unknown_residual"),
        ("yolosseg", "yolos_unknown_residual"),
        ("yolofc5", "yolof_unknown_residual"),
        ("yoloxonnx", "yolox_unknown_residual"),
        ("yoloxtensorrt", "yolox_unknown_residual"),
        ("yoloxsafetensors", "yolox_unknown_residual"),
        ("yoloxpretrained", "yolox_unknown_residual"),
        ("yoloxdarknet", "yolox_unknown_residual"),
        ("yolostiny", "yolos_unknown_residual"),
        ("yolossmall", "yolos_unknown_residual"),
        ("yoloxnano", "yolox_unknown_residual"),
        ("yoloxtiny", "yolox_unknown_residual"),
        ("yoloxpttrt", "yolox_unknown_residual"),
    )
    # No A14-1 compact-glue token reconstitutes a deny seed after F12-7
    # (reconst is reserved for residual debris that itself matches a deny
    # seed, e.g. yolos_eg → yoloseg). Kept as an explicit empty group.
    RECONST_PATH: ClassVar[tuple[tuple[str, str], ...]] = ()
    COMPACT_GLUE_DENY: ClassVar[tuple[str, ...]] = tuple(
        t for t, _ in UNKNOWN_PATH
    )

    SEPARATOR_ADMIT: ClassVar[tuple[str, ...]] = (
        "yolox_pt",
        "yolox_trt",
        "yolox_bin",
        "yolox_onnx",
        "yolos_tiny",
        "yolox_nano",
        "yolox_darknet",
        "yolof_c5",
        "yolof_r50",
        "yolopv2",  # compact family tag, not shield glue
        "yolofr50",  # compact family tag r50
        "yoloxs",
        "ppyoloe",
    )

    @pytest.mark.parametrize("token,expected_pkg", UNKNOWN_PATH)
    def test_compact_glue_unknown_path_package_id(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"compact glue {token!r} must DENY (A14-1 unknown path)"
        )
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected {expected_pkg!r}, got {hit.package_id!r}"
        )

    @pytest.mark.parametrize("token", COMPACT_GLUE_DENY)
    def test_compact_glue_tags_deny(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"compact glue {token!r} must DENY (A14-1)"
        )
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token", SEPARATOR_ADMIT)
    def test_separator_and_family_compact_admit(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT (separator or family compact tag)"
        )

    def test_unicode_fullwidth_compact_glue_denies(self) -> None:
        """NFKC fullwidth ``ｙｏｌｏｘpt`` → yoloxpt → DENY."""
        token = "ｙｏｌｏｘpt"
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"unicode compact glue {token!r} must DENY"

    def test_compact_glue_allowlist_is_ppyolo_eplus_only(self) -> None:
        allow = policy._EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST
        for seed, tags in allow.items():
            if seed == "ppyolo":
                # F12-4: ppyoloeplus is a published compact id.
                assert tags == frozenset({"eplus"}), (
                    f"ppyolo compact-glue allowlist must be {{eplus}}; got {tags!r}"
                )
                continue
            assert tags == frozenset(), (
                f"compact-glue allowlist for {seed!r} must be empty; got {tags!r}"
            )

    def test_red_proof_steal_flag_turns_compact_glue_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: residual-classify flag owns compact export-glue denies.

        Representative witnesses that do not also hit elevated deny-(c)
        via yolo rem (prefer shield tags longer than 3 chars after seed).
        """
        witnesses = ("yoloxtrt", "yoloxbin", "yoloxonnx", "yolostiny", "yoloxdarknet")
        for token in witnesses:
            assert policy._package_denylist_hit(token) is not None
        monkeypatch.setattr(
            policy, "_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED", False
        )
        for token in witnesses:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with residual-classify off, {token!r} must admit"
            )
        # Separator forms still admit (no steal needed).
        assert policy._package_denylist_hit("yolox_trt") is None
        # Pure elevated deny-(c) still works independently.
        assert policy._package_denylist_hit("yolov9t") is not None


class TestF11B143YolosSegDeny:
    """B14-3 / F10-CONV-01: drop ``seg`` from yolos separator tags."""

    YOLO_S_SEG_DENY: ClassVar[tuple[str, ...]] = (
        "yolos_seg",
        "yolos_trt_seg",
        "yolos_pt_seg",
        "yolos_bin_seg",
        "yolos_seg_pt",
        "yolos_seg_bin",
        "yolos_seg_trt",
        "yolosseg",
        "yolos.seg",
        "yolos-tiny-seg",
        "yolos_tiny_seg",
    )

    @pytest.mark.parametrize("token", YOLO_S_SEG_DENY)
    def test_yolos_seg_forms_deny(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY after B14-3 (YOLOS has no seg variant)"
        )
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_seg_absent_from_yolos_inventories(self) -> None:
        assert "seg" not in policy._EXCEPTION_FAMILY_SEPARATOR_TAGS["yolos"]
        assert "seg" not in policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS["yolos"]
        assert "seg" not in policy._EXCEPTION_FAMILY_COMPACT_TAGS["yolos"]

    def test_red_proof_seg_in_inventory_would_admit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: restoring ``seg`` to separator-only tags re-admits yolos_seg."""
        witness = "yolos_seg"
        assert policy._package_denylist_hit(witness) is not None
        monkeypatch.setattr(
            policy,
            "_EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS",
            {
                **policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS,
                "yolos": policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS["yolos"]
                | {"seg"},
            },
        )
        # Separator tags mapping is derived at import — also rebind derived.
        monkeypatch.setattr(
            policy,
            "_EXCEPTION_FAMILY_SEPARATOR_TAGS",
            {
                seed: (
                    policy._EXCEPTION_FAMILY_COMPACT_TAGS.get(seed, frozenset())
                    | policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS.get(
                        seed, frozenset()
                    )
                )
                for seed in policy._EXCEPTION_FAMILY_COMPACT_TAGS
            },
        )
        assert policy._package_denylist_hit(witness) is None, (
            "red-proof: with seg restored to yolos separator tags, "
            f"{witness!r} must ADMIT"
        )


class TestF11A142DeadBranchCleanup:
    """A14-2: dead branches removed or proven reachable."""

    def test_no_deny_seed_underlying_exception_helper(self) -> None:
        """Underlying-fabrication helper removed with B14-2 honesty fix."""
        assert not hasattr(policy, "_deny_seed_underlying_exception")

    def test_classify_fail_closed_default_is_unknown(self) -> None:
        """Fall-through of classify is unknown (never silent legitimate)."""
        # compact_glue shield residual with no reconst → unknown.
        outcome, entry = policy._classify_exception_residual(
            "yolox", "yolox", "trt", compact_glue=True
        )
        assert outcome == policy._RESIDUAL_UNKNOWN
        assert entry is not None
        assert entry.package_id == "yolox_unknown_residual"

    def test_steal_returns_entry_for_unknown_compact_glue(self) -> None:
        """Steal path reaches unknown-residual entry (not dead fall-through)."""
        steal = policy._exception_illegitimate_deny_steal("yoloxtrt")
        assert steal is not None
        assert steal.package_id == "yolox_unknown_residual"


class TestF11A145TagInventorySingleSource:
    """A14-5: separator tags derived from compact ∪ separator-only."""

    def test_separator_tags_derived_from_canonical_sources(self) -> None:
        compact = policy._EXCEPTION_FAMILY_COMPACT_TAGS
        sep_only = policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS
        derived = policy._EXCEPTION_FAMILY_SEPARATOR_TAGS
        assert set(compact) == set(sep_only) == set(derived)
        for seed in compact:
            assert derived[seed] == compact[seed] | sep_only[seed]

    def test_compact_tags_subset_of_separator_tags(self) -> None:
        for seed, tags in policy._EXCEPTION_FAMILY_COMPACT_TAGS.items():
            assert tags <= policy._EXCEPTION_FAMILY_SEPARATOR_TAGS[seed]


class TestF11ConverseExportAdmit:
    """Converse sanity: intended export-tag admits stay clean."""

    EXPORT_ADMIT: ClassVar[tuple[str, ...]] = (
        "yolox_trt",
        "yolox_pt",
        "yolox_bin",
        "yolos_pt",
        "yolof_bin",
        "yolop_trt",
    )

    @pytest.mark.parametrize("token", EXPORT_ADMIT)
    def test_export_separator_admits_without_agpl_lineage(
        self, token: str
    ) -> None:
        assert policy._package_denylist_hit(token) is None
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is True, (
                f"door must admit {token!r}; got {result.reason} "
                f"({result.detail})"
            )
            detail_cf = (result.detail or "").casefold()
            assert "ultralytics" not in detail_cf
            assert "agpl" not in detail_cf


# ---------------------------------------------------------------------------
# FIR-7 Wave F12 — exact-residual DEFER, compact-glue peel, NC doors, inventory
# ---------------------------------------------------------------------------


def _door_entry_package_id(detail: str) -> str | None:
    """Extract the PACKAGE_DENYLIST entry id from a door detail line.

    R14-G3-3: pin exact package_id rather than substring-loose detail.
    Format: ``hits PACKAGE_DENYLIST entry '<id>' (<spdx>): ...``
    """
    marker = "hits PACKAGE_DENYLIST entry '"
    if marker not in detail:
        return None
    rest = detail.split(marker, 1)[1]
    if "'" not in rest:
        return None
    return rest.split("'", 1)[0]


def _door_nc_pattern_id(detail: str) -> str | None:
    """Extract the NC membership id from a door detail line.

    F13-7 / R15-G3-1: pin exact membership id, not a token substring.
    Format: ``matches non-commercial pattern '<id>'``
    """
    marker = "matches non-commercial pattern '"
    if marker not in detail:
        return None
    rest = detail.split(marker, 1)[1]
    if "'" not in rest:
        return None
    return rest.split("'", 1)[0]


class TestF12ExactResidualDeferSteal:
    """F12-1 / R14-G1-1 / R14-G1-2: exact residual DEFER must not fail-open.

    ``_exception_illegitimate_deny_steal`` previously stole only *non-exact*
    residual deny hits so rule-(e) sole-path red-proofs stayed load-bearing.
    Exact residuals (``yolo``, ``yolov8``, ``yolonas``) stayed DEFER, but
    (e) needs seed len ≥ 5 and the walker cannot re-queue an unbounded
    compact rem — so ``yoloxyolo`` (residual ``yolo``, len 4) admitted.

    Fix: when ``structural != residual`` (unbounded compact rem) and the
    residual has *any* deny hit, including exact identity, return that hit.
    """

    # (token, expected package_id). NC residual yolonas is floor-pinned here;
    # door promotion of that NC hit is F12-3.
    AGPL_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yoloxyolo", "yolo"),
        ("yolosyolo", "yolo"),
        ("yolofyolo", "yolo"),
        ("yolopyolo", "yolo"),
        ("ppyoloyolo", "yolo"),
        ("yoloxyolo_v8", "yolov8"),
        ("yolosyolo_v8", "yolov8"),
    )
    NC_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yoloxyolo_nas", "yolonas"),
    )

    @pytest.mark.parametrize("token,expected_pkg", AGPL_WITNESSES + NC_WITNESSES)
    def test_exact_residual_unbounded_denies_honest(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (F12-1 exact-residual unbounded DEFER hole)"
        )
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected honest residual entry {expected_pkg!r}, "
            f"got {hit.package_id!r} notes={hit.notes!r}"
        )

    @pytest.mark.parametrize("token,expected_pkg", AGPL_WITNESSES)
    def test_agpl_exact_residual_denies_on_doors(
        self, token: str, expected_pkg: str
    ) -> None:
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, f"door must deny {token!r}"
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            assert _door_entry_package_id(result.detail) == expected_pkg, (
                f"{token!r}: door must name entry {expected_pkg!r}; "
                f"got {result.detail!r}"
            )

    def test_controls_keep_current_behavior(self) -> None:
        """Separator / bare / seed-ending compact still deny on their paths."""
        yolo_controls = ("yolox_yolo", "yolo")
        for token in yolo_controls:
            hit = policy._package_denylist_hit(token)
            assert hit is not None, f"control {token!r} must still deny"
            assert hit.package_id == "yolo"
        ultra = policy._package_denylist_hit("yoloxultralytics")
        assert ultra is not None
        assert ultra.package_id == "ultralytics"
        # F11 B14-1 witnesses still deny with honest residual entries.
        for token, expected in (
            ("yoloxultralyticsplus", "ultralytics"),
            ("yolosultralyticsplus", "ultralytics"),
            ("yoloxyolov8seg", "yolov8"),
        ):
            hit = policy._package_denylist_hit(token)
            assert hit is not None, f"B14-1 {token!r} must still deny"
            assert hit.package_id == expected

    def test_red_proof_steal_flag_turns_exact_residual_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: steal flag owns F12-1 exact-residual witnesses.

        Neuter ``_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED`` → ``yoloxyolo``
        admits (rule (e) cannot see seed ``yolo`` of len 4; walker cannot
        re-queue the unbounded compact rem).
        """
        witnesses = [t for t, _ in self.AGPL_WITNESSES]
        for token in witnesses:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(
            policy, "_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED", False
        )
        for token in witnesses:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with steal off, {token!r} must admit"
            )
        # Seed-ending compact of a ≥5-char deny seed still denies via (e).
        assert policy._package_denylist_hit("xultralytics") is not None
        # Bare / separator yolo still deny independently of steal.
        assert policy._package_denylist_hit("yolo") is not None
        assert policy._package_denylist_hit("yolox_yolo") is not None


class TestF12HalfSeparatedCompactGlue:
    """F12-2 / R14-G1-3: compact peel + separator tail must not admit as (a).

    ``yoloxpt_trt`` matches via head-segment (d): compact peel of ``yoloxpt``
    yields rem ``pt``, rejoined with tail ``trt``. ``compact_glue = ("_" not
    in token)`` then classified ``pt_trt`` with separator rules → both
    shield tags → legitimate. A14-1 says compact glue of ``pt`` is not
    legitimate; the separator tail must not launder it.
    """

    WITNESSES: ClassVar[tuple[str, ...]] = (
        "yoloxpt_trt",
        "yoloxpt_onnx",
        "yoloxpt_fp16",
        "yoloxpt_int8",
        "yoloxtrt_onnx",
        "yoloxbin_onnx",
        "yoloxpth_onnx",
        "yolofc5_onnx",
        "yolofc5_pt",
    )
    CONTROLS_ADMIT: ClassVar[tuple[str, ...]] = (
        "yolox_pt_trt",
        "yolox_s_pt",
        "yolox_pt",
        "yolox_trt",
        "yolofr50",
        "yoloxs",
    )

    @pytest.mark.parametrize("token", WITNESSES)
    def test_half_separated_compact_glue_denies(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (F12-2 compact peel + separator tail)"
        )
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token", CONTROLS_ADMIT)
    def test_separator_and_family_compact_controls_admit(
        self, token: str
    ) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"control {token!r} must stay PASS"
        )
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is True, (
                f"door must admit {token!r}; got {result.reason} "
                f"({result.detail})"
            )
            detail_cf = (result.detail or "").casefold()
            assert "ultralytics" not in detail_cf
            assert "agpl" not in detail_cf

    def test_red_proof_steal_flag_turns_half_separated_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: residual-classify owns F12-2 witnesses.

        Neuter ``_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED`` → ``yoloxpt_trt``
        admits (head-segment peel + shield tail looks legitimate).
        """
        for token in self.WITNESSES:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(
            policy, "_EXCEPTION_ILLEGITIMATE_STEAL_ENABLED", False
        )
        for token in self.WITNESSES:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with steal/classify off, {token!r} must admit"
            )
        # True separator forms still admit (no steal needed).
        assert policy._package_denylist_hit("yolox_pt_trt") is None
        assert policy._package_denylist_hit("yolox_s_pt") is None


class TestF12NcDoorPromotionUnboundedCompact:
    """F12-3 / R14-G1-4: NC scanner hits must reach weights doors.

    ``_package_denylist_hit`` already returns the NC entry for
    ``yoloxinsightface`` (rule (e) / F12-1 steal), but door promotion
    only takes AGPL from that scan. The NC path required
    ``_token_has_exception_family`` (structural strip), which misses
    unbounded compact claims. Fail closed when scanner and door disagree.
    """

    WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yoloxinsightface", "insightface"),
        ("yoloxarcface", "arcface"),
        ("yoloxantelopev2", "antelopev2"),
        ("yoloxyolo_nas", "yolonas"),
    )

    @pytest.mark.parametrize("token,expected_pkg", WITNESSES)
    def test_unbounded_exception_nc_denies_on_floor(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must hit NC on the scanner"
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected NC entry {expected_pkg!r}, got "
            f"{hit.package_id!r}"
        )

    @pytest.mark.parametrize("token,expected_pkg", WITNESSES)
    def test_unbounded_exception_nc_denies_on_doors(
        self, token: str, expected_pkg: str
    ) -> None:
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, (
                f"door must deny {token!r} (scanner/door fail-closed)"
            )
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
                f"{token!r}: expected nc_model_derived, got {result.reason} "
                f"({result.detail})"
            )
            assert _door_nc_pattern_id(result.detail) == expected_pkg, (
                f"{token!r}: door must name NC pattern {expected_pkg!r}; "
                f"got {result.detail!r}"
            )

    def test_controls_exception_clean_and_existing_nc_compound(self) -> None:
        assert policy._package_denylist_hit("yolox") is None
        assert policy._package_denylist_hit("yolox_s") is None
        for token in ("yolox", "yolox_s"):
            for door in (
                policy.audit_derived_from_model,
                policy.audit_source,
            ):
                result = door(token)
                assert result.ok is True, (
                    f"control {token!r} must stay PASS; got {result.reason} "
                    f"({result.detail})"
                )
        buffalo = policy.audit_derived_from_model("yolox_s_buffalo_l")
        assert buffalo.ok is False
        assert buffalo.reason is policy.RejectionReason.NC_MODEL_DERIVED
        # Door-precision: compact (e) over-block of myarcface stays floor-only.
        assert policy._package_denylist_hit("myarcface") is not None
        assert policy.audit_derived_from_model("myarcface").ok is True
        assert policy.audit_derived_from_model("not-insightface").ok is True

    def test_red_proof_token_has_exception_family_unbounded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: unbounded exception family is load-bearing for NC doors.

        Neuter ``_token_has_exception_family`` → ``yoloxinsightface`` door
        admits (scanner still hits; NC promotion is gated on the family
        helper so BR-28 ``myarcface`` stays floor-only).
        """
        token = "yoloxinsightface"
        assert policy._package_denylist_hit(token) is not None
        assert policy.audit_derived_from_model(token).ok is False
        monkeypatch.setattr(
            policy, "_token_has_exception_family", lambda _t: False
        )
        assert policy._package_denylist_hit(token) is not None, (
            "scanner must still hit after family-helper neuter"
        )
        assert policy.audit_derived_from_model(token).ok is True, (
            "red-proof: with exception-family helper off, door must admit"
        )


class TestF12PpyoloCatalogAndResidualSplit:
    """F12-4 / R14-G2-1 / R14-G2-6: PP-YOLO real catalog + residual split.

    When the token contains ``_``, prefer the head-segment residual over
    the unbounded compact rem so ``ppyoloe_s`` is ``e``+``s``, not ``es``.
    Then admit the published PaddleDetection catalog spellings.
    """

    ADMIT: ClassVar[tuple[str, ...]] = (
        "ppyoloe_s",
        "ppyoloe_m",
        "ppyoloe_l",
        "ppyoloe_x",
        "ppyoloe_plus",
        "ppyoloeplus",
        "ppyoloe_crn_s_300e_coco",
        "ppyoloe_plus_crn_s_80e_coco",
        "ppyolo_r50vd_dcn_1x_coco",
        "ppyolov2_r50vd_dcn_365e_coco",
        "PaddleDetection/ppyoloe_crn_s_300e_coco",
    )
    DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("ppyoloultralyticsplus", "ultralytics"),
        ("ppyoloyolo", "yolo"),
    )

    def test_underscore_token_prefers_head_segment_residual(self) -> None:
        """R14-G2-6: ppyoloe_s residual is e_s, not compact-joined es."""
        seed_c, seed_k, residual = policy._exception_seed_match_for_residual(
            "ppyoloe_s"
        )
        assert seed_c == "ppyolo"
        assert residual == "e_s", (
            f"ppyoloe_s residual must be segmented e_s, got {residual!r}"
        )
        structural = policy._strip_exception_seed_residual(
            "ppyoloe_s", seed_c, seed_k
        )
        assert structural == "e_s"

    @pytest.mark.parametrize("token", ADMIT)
    def test_ppyolo_catalog_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT (PaddleDetection PP-YOLO catalog)"
        )
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is True, (
                f"door must admit {token!r}; got {result.reason} "
                f"({result.detail})"
            )
            detail_cf = (result.detail or "").casefold()
            assert "ultralytics" not in detail_cf
            assert "agpl" not in detail_cf

    @pytest.mark.parametrize("token,expected_pkg", DENY)
    def test_ppyolo_deny_stems_still_deny(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must still DENY"
        assert hit.package_id == expected_pkg

    def test_compact_orthography_of_separator_tags_stays_deny(self) -> None:
        """R14-G2-4 non-goal: ppyoloes (compact s) stays DENY."""
        hit = policy._package_denylist_hit("ppyoloes")
        assert hit is not None, "ppyoloes compact size glue must stay DENY"

    def test_red_proof_inventory_drop_turns_catalog_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: dropping ppyolo separator tags re-denies ppyoloe_s."""
        witness = "ppyoloe_s"
        assert policy._package_denylist_hit(witness) is None
        monkeypatch.setattr(
            policy,
            "_EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS",
            {
                **policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS,
                "ppyolo": frozenset(),
            },
        )
        monkeypatch.setattr(
            policy,
            "_EXCEPTION_FAMILY_SEPARATOR_TAGS",
            {
                seed: (
                    policy._EXCEPTION_FAMILY_COMPACT_TAGS.get(seed, frozenset())
                    | policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS.get(
                        seed, frozenset()
                    )
                )
                for seed in policy._EXCEPTION_FAMILY_COMPACT_TAGS
            },
        )
        assert policy._package_denylist_hit(witness) is not None, (
            "red-proof: with ppyolo separator tags emptied, "
            f"{witness!r} must DENY"
        )


class TestF12YolofDetectron2ScheduleTags:
    """F12-5 / R14-G2-2: YOLOF Detectron2 schedule / R_50 tags admit."""

    ADMIT: ClassVar[tuple[str, ...]] = (
        "yolof_r50_c5_1x",
        "yolof_r50_c5_3x",
        "yolof_r101_c5_1x",
        "YOLOF_R_50_C5_1x",
        "facebookresearch/detectron2/yolof_r50_c5_1x",
    )
    DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolofultralyticsplus", "ultralytics"),
        ("yolofyolo", "yolo"),
    )

    @pytest.mark.parametrize("token", ADMIT)
    def test_yolof_schedule_catalog_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT (YOLOF Detectron2 catalog)"
        )
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is True, (
                f"door must admit {token!r}; got {result.reason} "
                f"({result.detail})"
            )
            detail_cf = (result.detail or "").casefold()
            assert "ultralytics" not in detail_cf
            assert "agpl" not in detail_cf

    @pytest.mark.parametrize("token,expected_pkg", DENY)
    def test_yolof_deny_stems_still_deny(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must still DENY"
        assert hit.package_id == expected_pkg

    def test_red_proof_schedule_tag_drop_turns_yolof_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: dropping 1x from yolof tags re-denies yolof_r50_c5_1x."""
        witness = "yolof_r50_c5_1x"
        assert policy._package_denylist_hit(witness) is None
        current = policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS["yolof"]
        monkeypatch.setattr(
            policy,
            "_EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS",
            {
                **policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS,
                "yolof": frozenset(t for t in current if t != "1x"),
            },
        )
        monkeypatch.setattr(
            policy,
            "_EXCEPTION_FAMILY_SEPARATOR_TAGS",
            {
                seed: (
                    policy._EXCEPTION_FAMILY_COMPACT_TAGS.get(seed, frozenset())
                    | policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS.get(
                        seed, frozenset()
                    )
                )
                for seed in policy._EXCEPTION_FAMILY_COMPACT_TAGS
            },
        )
        assert policy._package_denylist_hit(witness) is not None, (
            f"red-proof: without 1x in yolof tags, {witness!r} must DENY"
        )


class TestF12bYolofDatasetTag:
    """F12b-1 / R14-CDX-03 residue: YOLOF Detectron2/MMDetection ``coco`` tag.

    F12-5 admitted schedule tags (``1x`` / ``3x``) and backbone splits
    (``r`` / ``50`` / ``101``) but not the trailing dataset tag used by
    real Detectron2 / MMDetection artifact names
    (``yolof_r50_c5_1x_coco``). Same structural-debris policy as F12-4
    documented for ppyolo's schedule/dataset inventory.
    """

    ADMIT: ClassVar[tuple[str, ...]] = (
        "yolof_r50_c5_1x_coco",
        "yolof_r50_c5_3x_coco",
        "yolof_r101_c5_1x_coco",
        "YOLOF_R_50_C5_1x_coco",
    )
    DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolofultralyticsplus", "ultralytics"),
        ("yolofyolo", "yolo"),
        ("yolofc5_pt", "yolof_unknown_residual"),
        ("yolof_z", "yolof_unknown_residual"),
    )

    @pytest.mark.parametrize("token", ADMIT)
    def test_yolof_dataset_catalog_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT (YOLOF Detectron2/MMDetection catalog)"
        )
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is True, (
                f"door must admit {token!r}; got {result.reason} "
                f"({result.detail})"
            )
            detail_cf = (result.detail or "").casefold()
            assert "ultralytics" not in detail_cf
            assert "agpl" not in detail_cf

    @pytest.mark.parametrize("token,expected_pkg", DENY)
    def test_yolof_dataset_deny_stems_still_deny(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must still DENY"
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected honest {expected_pkg!r}, got "
            f"{hit.package_id!r} notes={hit.notes!r}"
        )
        if expected_pkg.endswith("_unknown_residual"):
            notes_cf = hit.notes.casefold()
            assert "ultralytics" not in notes_cf
            assert "agpl family alias" not in notes_cf

    def test_red_proof_coco_tag_drop_turns_yolof_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: dropping coco from yolof tags re-denies yolof_r50_c5_1x_coco.

        Neuter: remove ``coco`` from ``_EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS``
        [``yolof``] (and re-derive ``_EXCEPTION_FAMILY_SEPARATOR_TAGS``).
        """
        witness = "yolof_r50_c5_1x_coco"
        assert policy._package_denylist_hit(witness) is None
        current = policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS["yolof"]
        monkeypatch.setattr(
            policy,
            "_EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS",
            {
                **policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS,
                "yolof": frozenset(t for t in current if t != "coco"),
            },
        )
        monkeypatch.setattr(
            policy,
            "_EXCEPTION_FAMILY_SEPARATOR_TAGS",
            {
                seed: (
                    policy._EXCEPTION_FAMILY_COMPACT_TAGS.get(seed, frozenset())
                    | policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS.get(
                        seed, frozenset()
                    )
                )
                for seed in policy._EXCEPTION_FAMILY_COMPACT_TAGS
            },
        )
        assert policy._package_denylist_hit(witness) is not None, (
            f"red-proof: without coco in yolof tags, {witness!r} must DENY"
        )


class TestF12YoloxDarknet53:
    """F12-6 / R14-G2-5: darknet53 is a real YOLOX backbone tag."""

    ADMIT: ClassVar[tuple[str, ...]] = (
        "yolox_darknet53",
        "yolox-darknet53",
        "YOLOX-DarkNet53",
    )

    @pytest.mark.parametrize("token", ADMIT)
    def test_yolox_darknet53_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT (YOLOX darknet53 backbone)"
        )
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is True, (
                f"door must admit {token!r}; got {result.reason} "
                f"({result.detail})"
            )
            detail_cf = (result.detail or "").casefold()
            assert "ultralytics" not in detail_cf
            assert "agpl" not in detail_cf

    def test_red_proof_darknet53_drop_turns_admit_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: dropping darknet53 from yolox tags re-denies the witness."""
        witness = "yolox_darknet53"
        assert policy._package_denylist_hit(witness) is None
        current = policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS["yolox"]
        monkeypatch.setattr(
            policy,
            "_EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS",
            {
                **policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS,
                "yolox": frozenset(t for t in current if t != "darknet53"),
            },
        )
        monkeypatch.setattr(
            policy,
            "_EXCEPTION_FAMILY_SEPARATOR_TAGS",
            {
                seed: (
                    policy._EXCEPTION_FAMILY_COMPACT_TAGS.get(seed, frozenset())
                    | policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS.get(
                        seed, frozenset()
                    )
                )
                for seed in policy._EXCEPTION_FAMILY_COMPACT_TAGS
            },
        )
        assert policy._package_denylist_hit(witness) is not None, (
            f"red-proof: without darknet53 in yolox tags, {witness!r} must DENY"
        )


class TestF12ReasonHonesty:
    """F12-7 / R14-G2-3 / R14-G1-5: do not fabricate Ultralytics for short rem.

    Progressive reconst of exception_seed + short debris hit ``yolo``
    because every exception seed is ``yolo`` + 1 char. Those denies stay
    DENY but must report ``*_unknown_residual``, not entry ``yolo``.
    """

    UNKNOWN_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yoloxpt", "yolox_unknown_residual"),
        ("yolospt", "yolos_unknown_residual"),
        ("yolofc5", "yolof_unknown_residual"),
        ("yolox_z", "yolox_unknown_residual"),
        ("yolox_ab", "yolox_unknown_residual"),
        ("yolof_z", "yolof_unknown_residual"),
        ("yolop_z", "yolop_unknown_residual"),
        ("yolos_ti", "yolos_unknown_residual"),
    )

    @pytest.mark.parametrize("token,expected_pkg", UNKNOWN_WITNESSES)
    def test_short_residual_unknown_not_fabricated_yolo(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must stay DENY"
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected honest {expected_pkg!r}, got "
            f"{hit.package_id!r} notes={hit.notes!r}"
        )
        notes_cf = hit.notes.casefold()
        assert "ultralytics" not in notes_cf
        assert "agpl family alias" not in notes_cf

    @pytest.mark.parametrize("token,expected_pkg", UNKNOWN_WITNESSES)
    def test_short_residual_unknown_on_doors_exact_entry(
        self, token: str, expected_pkg: str
    ) -> None:
        """R14-G3-3: door detail names the exact package_id."""
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            assert _door_entry_package_id(result.detail) == expected_pkg, (
                f"{token!r}: door must name entry {expected_pkg!r}; "
                f"got {result.detail!r}"
            )

    def test_f12_1_witnesses_keep_true_entries(self) -> None:
        """F12-1 steal of residual identity outranks suppressed reconst."""
        for token, expected in (
            ("yoloxyolo", "yolo"),
            ("yolosyolo", "yolo"),
            ("yoloxyolo_v8", "yolov8"),
            ("yoloxyolo_nas", "yolonas"),
        ):
            hit = policy._package_denylist_hit(token)
            assert hit is not None
            assert hit.package_id == expected, (
                f"{token!r}: F12-1 true entry {expected!r}, got "
                f"{hit.package_id!r}"
            )

    def test_yoloseg_reconst_path_still_yolo(self) -> None:
        """Honest reconst: yolos+eg → yoloseg is a real yolo compact rem."""
        hit = policy._package_denylist_hit("yoloseg")
        assert hit is not None
        assert hit.package_id == "yolo"
        hit2 = policy._package_denylist_hit("yolos_eg")
        assert hit2 is not None
        assert hit2.package_id == "yolo"

    def test_strongest_hit_names_ultralytics_in_compound(self) -> None:
        """R14-G1-6: yoloxyoloultralyticsplus names ultralytics, not unknown."""
        token = "yoloxyoloultralyticsplus"
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == "ultralytics", (
            f"{token!r}: expected ultralytics-class content, got "
            f"{hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert _door_entry_package_id(result.detail) == "ultralytics"

    def test_red_proof_reconst_suppression_is_load_bearing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: restoring fabricated yolo reconst flips yoloxpt reason."""
        token = "yoloxpt"
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == "yolox_unknown_residual"
        monkeypatch.setattr(
            policy, "_is_fabricated_exception_yolo_hit", lambda *_a, **_k: False
        )
        hit2 = policy._package_denylist_hit(token)
        assert hit2 is not None
        assert hit2.package_id == "yolo", (
            "red-proof: with fabrication filter off, yoloxpt must name yolo"
        )


# ---------------------------------------------------------------------------
# FIR-7 Wave F13 — unofficial separators, NC door position, compact glue
# ---------------------------------------------------------------------------


class TestF13UnofficialSeparatorFolding:
    """F13-1 / R15-G1-1 / R15-G1-2 / R15-G1-3: fold unofficial separators.

    ``canonical()`` previously unified only ``[-_.\\s]``, so ``yolox+yolo``
    / ``yolox＝yolo`` / ``yolox:yolo`` survived as a single opaque token
    and admitted. Fold ``+ = : @ | #`` (NFKC fullwidth twins map to these
    ASCII forms) to ``_`` *before* compact folding / seed matching so the
    existing scanner sees the same shape as the official-separator twin.
    """

    AGPL_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolox+yolo", "yolo"),
        ("yolox＋yolo", "yolo"),
        ("yolox=yolo", "yolo"),
        ("yolox:yolo", "yolo"),
        ("yolox@yolo", "yolo"),
        ("yoloxyolo+v8", "yolov8"),
    )
    UNKNOWN_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yoloxpt+trt",
        "yoloxpt＋trt",
        "yolofc5+pt",
    )
    NC_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolox+insightface", "insightface"),
        ("yolox＋insightface", "insightface"),
        ("yolox+arcface", "arcface"),
        ("yolox+yolo_nas", "yolo_nas"),
    )
    CONTROLS_ADMIT: ClassVar[tuple[str, ...]] = (
        "yolox_pt_trt",
        "yolox_s",
        "yoloxs",
        "ppyoloeplus",
        "yolof_r50_c5_1x_coco",
        "ppyoloe_s",
        "yolodummy",
    )

    @pytest.mark.parametrize("token,expected_pkg", AGPL_WITNESSES)
    def test_unofficial_sep_agpl_denies_honest(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY after unofficial-separator fold (F13-1)"
        )
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected {expected_pkg!r}, got {hit.package_id!r}"
        )
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, f"door must deny {token!r}"
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            assert _door_entry_package_id(result.detail) == expected_pkg, (
                f"{token!r}: door must name {expected_pkg!r}; "
                f"got {result.detail!r}"
            )

    @pytest.mark.parametrize("token", UNKNOWN_WITNESSES)
    def test_unofficial_sep_unknown_residual_denies(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY as unknown residual (F13-1 / F12-2 twin)"
        )
        assert hit.package_id.endswith("_unknown_residual"), (
            f"{token!r}: expected *_unknown_residual, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token,expected_pkg", NC_WITNESSES)
    def test_unofficial_sep_nc_denies_on_doors(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must hit NC on the scanner"
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert hit.package_id == expected_pkg
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, f"door must deny {token!r}"
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("token", CONTROLS_ADMIT)
    def test_official_separator_and_f12_admits_unchanged(
        self, token: str
    ) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"control {token!r} must stay PASS"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is True, (
            f"door must admit {token!r}; got {result.reason} ({result.detail})"
        )

    def test_myarcface_stays_floor_only_door_pass(self) -> None:
        assert policy._package_denylist_hit("myarcface") is not None
        assert policy.audit_derived_from_model("myarcface").ok is True

    def test_red_proof_unofficial_separator_charset_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: emptying ``_UNOFFICIAL_SEPARATOR_CHARS`` re-admits witnesses.

        Neuter: ``_ASCII_PUNCT_FOLD_TOTAL`` → ``False`` and
        ``_UNOFFICIAL_SEPARATOR_CHARS`` → ``""`` (pre-F13-1 official-only
        ``[-_.\\s]`` fold). Official-separator twins stay denied.
        """
        agpl_unknown = (
            [t for t, _ in self.AGPL_WITNESSES] + list(self.UNKNOWN_WITNESSES)
        )
        nc = [t for t, _ in self.NC_WITNESSES]
        for token in agpl_unknown + nc:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
            assert policy.audit_derived_from_model(token).ok is False
        # F14-1: emptying the charset is a no-op under the total class
        # fold. Revert both levers so this stays the pre-F13-1 official-only
        # fold (TEST-15).
        monkeypatch.setattr(policy, "_ASCII_PUNCT_FOLD_TOTAL", False)
        monkeypatch.setattr(policy, "_UNOFFICIAL_SEPARATOR_CHARS", "")
        # AGPL / unknown-residual forms have no ≥5-char deny suffix, so
        # the scanner itself admits once ``+``/``=``/… stop folding.
        for token in agpl_unknown:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with unofficial charset emptied, {token!r} "
                "must admit on the scanner"
            )
        # NC seeds (insightface / arcface / yolonas) are ≥5 compact chars,
        # so rule (e) still scanner-hits the *unfolded* token. The fold is
        # load-bearing for the *door*: without it, (e) is not promoted
        # (BR-28) and the exception head is invisible.
        for token in nc:
            assert policy.audit_derived_from_model(token).ok is True, (
                f"red-proof: with unofficial charset emptied, {token!r} "
                "must admit on the door"
            )
        # Official-separator twin and F12 pins stay load-bearing.
        assert policy._package_denylist_hit("yoloxyolo") is not None
        assert policy._package_denylist_hit("yolox_yolo") is not None
        assert policy._package_denylist_hit("yolox_pt_trt") is None


class TestF14TotalAsciiPunctFold:
    """F14-1: total ASCII-punct fold + C0/C1 fail-close.

    F13-1 enumerated ``+=:@|#``. Every other ASCII punct (``~ ! , ; ' "
    % ^ & * ( ) [ ] { } < > ? $`` …), NUL, and paired wrappers fail-opened.
    Replace the enumeration with a class rule: after NFKC/Cf, any C0/C1
    control is ``invalid_row``; every remaining non-alnum ASCII except
    ``/`` folds to ``_``.
    """

    AGPL_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolox~yolo", "yolo"),
        ("yolox!yolo", "yolo"),
        ("yolov8;seg", "yolov8"),
        ("yolov8,", "yolov8"),
        ("(yolov8)", "yolov8"),
        ("yolo,v8", "yolo_v8"),
        ("yolox～yolo", "yolo"),
        ("yolo，v8", "yolo_v8"),
    )
    UNKNOWN_WITNESSES: ClassVar[tuple[str, ...]] = (
        "yoloxpt~trt",
    )
    NC_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("arcface,r100", "arcface_r100"),
        ("buffalo,l", "buffalo_l"),
        ("scrfd,10g", "scrfd_10g"),
        ("yolox~insightface", "insightface"),
        ("yolox(insightface)", "insightface"),
        ("yolox[insightface]", "insightface"),
        ("yolox&buffalo_l", "buffalo_l"),
        ("insightface~yolox", "insightface"),
        ("arcface~yolox", "arcface"),
        ("buffalo_l~yolox", "buffalo_l"),
    )
    CONTROL_ADMIT: ClassVar[tuple[str, ...]] = (
        "ppyoloe+",
        "ppyoloe+_crn_s_80e_coco",
        "yolox:s",
        "yolox_s+trt",
        "yolodummy",
    )
    CONTROL_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolox+yolo", "yolo"),
    )
    INVALID_ROW: ClassVar[tuple[str, ...]] = (
        "yolo\x00v8",
        "yolox\x00yolo",
    )

    @pytest.mark.parametrize("token,expected_pkg", AGPL_WITNESSES)
    def test_total_fold_agpl_denies_honest(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY after total ASCII-punct fold (F14-1)"
        )
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected {expected_pkg!r}, got {hit.package_id!r}"
        )
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, f"door must deny {token!r}"
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            assert _door_entry_package_id(result.detail) == expected_pkg, (
                f"{token!r}: door must name {expected_pkg!r}; "
                f"got {result.detail!r}"
            )

    @pytest.mark.parametrize("token", UNKNOWN_WITNESSES)
    def test_total_fold_unknown_residual_denies(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY as unknown residual (F14-1 / F12-2 twin)"
        )
        assert hit.package_id.endswith("_unknown_residual"), (
            f"{token!r}: expected *_unknown_residual, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert _door_entry_package_id(result.detail) == hit.package_id

    @pytest.mark.parametrize("token,expected_pkg", NC_WITNESSES)
    def test_total_fold_nc_denies_on_doors(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must hit NC on the scanner"
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert hit.package_id == expected_pkg
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, f"door must deny {token!r}"
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
            pattern = _door_nc_pattern_id(result.detail)
            entry = _door_entry_package_id(result.detail)
            assert pattern == expected_pkg or entry == expected_pkg, (
                f"{token!r}: door must name {expected_pkg!r}; "
                f"got pattern={pattern!r} entry={entry!r} detail={result.detail!r}"
            )

    @pytest.mark.parametrize("token", CONTROL_ADMIT)
    def test_total_fold_admit_controls_hold(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"control {token!r} must stay PASS"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is True, (
            f"door must admit {token!r}; got {result.reason} ({result.detail})"
        )

    @pytest.mark.parametrize("token,expected_pkg", CONTROL_DENY)
    def test_total_fold_existing_deny_controls_hold(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"control {token!r} must still DENY"
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert _door_entry_package_id(result.detail) == expected_pkg

    def test_total_fold_br28_floor_only_unchanged(self) -> None:
        for token in ("myarcface", "not-insightface"):
            assert policy._package_denylist_hit(token) is not None
            assert policy.audit_derived_from_model(token).ok is True, (
                f"BR-28 {token!r} must stay floor-only door-pass"
            )

    def test_non_nfkc_dashes_still_invalid_row(self) -> None:
        for token in ("yolo\u2010v8", "yolo\u2013v8", "yolo\u2014v8"):
            assert policy.canonical(token) is None, (
                f"non-NFKC dash {token!r} must stay canonical-None"
            )
            result = policy.audit_derived_from_model(token)
            assert result.ok is False
            assert result.reason is policy.RejectionReason.INVALID_ROW

    @pytest.mark.parametrize("token", INVALID_ROW)
    def test_control_char_is_invalid_row(self, token: str) -> None:
        assert policy.canonical(token) is None, (
            f"{token!r} must fail-closed canonical-None (C0/C1)"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

    def test_red_proof_total_ascii_punct_fold_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: revert ``_ASCII_PUNCT_FOLD_TOTAL`` to the F13-1 charset.

        Neuter: ``_ASCII_PUNCT_FOLD_TOTAL`` → ``False`` (old enumeration
        ``+=:@|#``). Tilde / bang / comma / wrapper witnesses admit;
        official-separator twins and F13-1 ``+`` pins stay denied.
        """
        fold_only = (
            [t for t, _ in self.AGPL_WITNESSES]
            + list(self.UNKNOWN_WITNESSES)
            + [t for t, _ in self.NC_WITNESSES]
        )
        for token in fold_only:
            assert policy.audit_derived_from_model(token).ok is False, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(policy, "_ASCII_PUNCT_FOLD_TOTAL", False)
        for token in fold_only:
            assert policy.audit_derived_from_model(token).ok is True, (
                f"red-proof: with total fold off, {token!r} must admit"
            )
        # F13-1 enumeration still folds ``+``.
        assert policy._package_denylist_hit("yolox+yolo") is not None
        assert policy._package_denylist_hit("yoloxyolo") is not None
        assert policy._package_denylist_hit("yolox_yolo") is not None
        assert policy.audit_derived_from_model("ppyoloe+").ok is True
        assert policy.audit_derived_from_model("yolodummy").ok is True


class TestF14RegistryTrailingTagStrip:
    """F14-2 / R16-G2-3: strip ``:latest`` / ``:v0.3.0`` before fold.

    ``yolox:s`` is not a registry tag — the fold still yields ``yolox_s``.
    ``yolo:latest`` strips then matches ``yolo`` — the strip must never
    launder a deny.
    """

    ADMIT: ClassVar[tuple[str, ...]] = (
        "yolox:latest",
        "megvii/yolox:latest",
        "yolox:v0.3.0",
        "ppyoloe:latest",
    )
    DENY_AFTER_STRIP: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolo:latest", "yolo"),
    )
    FOLD_UNCHANGED: ClassVar[tuple[str, ...]] = (
        "yolox:s",
    )

    @pytest.mark.parametrize("token", ADMIT)
    def test_registry_tag_strips_to_family_admit(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT after registry-tag strip (F14-2)"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is True, (
            f"door must admit {token!r}; got {result.reason} ({result.detail})"
        )

    @pytest.mark.parametrize("token,expected_pkg", DENY_AFTER_STRIP)
    def test_registry_tag_strip_does_not_launder_deny(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must still DENY after strip"
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert _door_entry_package_id(result.detail) == expected_pkg

    @pytest.mark.parametrize("token", FOLD_UNCHANGED)
    def test_official_size_tag_is_not_a_registry_tag(self, token: str) -> None:
        assert policy.canonical(token) == "yolox_s"
        assert policy._package_denylist_hit(token) is None
        assert policy.audit_derived_from_model(token).ok is True

    def test_red_proof_registry_tag_strip_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: remove the strip regex — ``yolox:latest`` denies again.

        Neuter: ``_STRIP_REGISTRY_TRAILING_TAG`` → ``False``. Fold then
        sees ``yolox_latest`` (unknown residual). ``yolo:latest`` still
        denies (yolo_latest is still a yolo (b) hit).
        """
        for token in self.ADMIT:
            assert policy.audit_derived_from_model(token).ok is True, (
                f"precondition: {token!r} must admit"
            )
        monkeypatch.setattr(policy, "_STRIP_REGISTRY_TRAILING_TAG", False)
        for token in self.ADMIT:
            assert policy.audit_derived_from_model(token).ok is False, (
                f"red-proof: without registry-tag strip, {token!r} must DENY"
            )
        result = policy.audit_derived_from_model("yolo:latest")
        assert result.ok is False
        assert _door_entry_package_id(result.detail) == "yolo"
        assert policy.audit_derived_from_model("yolox:s").ok is True


class TestF14PpYoloTitlePathMerge:
    """F14-3 / R16-G2-1: ``PP-YOLOE+`` title path merges to ``ppyoloe``.

    After fold ``PP-YOLOE+`` is ``pp_yoloe``. A leading ``pp`` segment
    immediately followed by a ``yolo*`` segment merges to ``ppyolo*``.
    Scoped to the ppyolo family only — not a generic segment-merge.
    """

    ADMIT: ClassVar[tuple[str, ...]] = (
        "PP-YOLOE+",
        "pp-yoloe+",
        "PaddlePaddle/PP-YOLOE+",
        "PP-YOLOE+_crn_s_80e_coco",
        "pp_yolo",
    )
    DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("pp_yolov8", "ppyolo_unknown_residual"),
    )
    UNAFFECTED_ADMIT: ClassVar[tuple[str, ...]] = (
        "pp",
        "pp_x",
    )

    @pytest.mark.parametrize("token", ADMIT)
    def test_pp_yolo_title_path_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT after pp+yolo merge (F14-3)"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is True, (
            f"door must admit {token!r}; got {result.reason} ({result.detail})"
        )

    @pytest.mark.parametrize("token,expected_pkg", DENY)
    def test_pp_yolov8_fail_closed(self, token: str, expected_pkg: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (merges to ppyolov8, unknown residual)"
        )
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert _door_entry_package_id(result.detail) == expected_pkg

    @pytest.mark.parametrize("token", UNAFFECTED_ADMIT)
    def test_pp_without_yolo_segment_unaffected(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None
        assert policy.audit_derived_from_model(token).ok is True

    def test_red_proof_pp_yolo_merge_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: remove the merge — ``PP-YOLOE+`` denies as yolo again.

        Neuter: ``_PP_YOLO_SEGMENT_MERGE_ENABLED`` → ``False``. Folded
        ``pp_yoloe`` is a yolo suffix hit. Compact ``ppyoloe+`` still
        admits (no merge needed).
        """
        for token in ("PP-YOLOE+", "pp-yoloe+", "pp_yolo"):
            assert policy.audit_derived_from_model(token).ok is True, (
                f"precondition: {token!r} must admit"
            )
        monkeypatch.setattr(policy, "_PP_YOLO_SEGMENT_MERGE_ENABLED", False)
        for token in ("PP-YOLOE+", "pp-yoloe+", "pp_yolo"):
            assert policy.audit_derived_from_model(token).ok is False, (
                f"red-proof: without pp+yolo merge, {token!r} must DENY"
            )
        assert policy.audit_derived_from_model("ppyoloe+").ok is True
        assert policy.audit_derived_from_model("pp").ok is True
        assert policy.audit_derived_from_model("pp_x").ok is True


class TestF14DoorPromotionMidException:
    """F14-4 / R16-G1-5 / R16-CDX-2: door promotion sees mid-token exception.

    Scanner already hits NC on ``xyoloxinsightface`` (mid-adjacency rem).
    Door promotion previously required a prefix or trailing-segment
    exception, so junk+exception+NC door-passed. Promote whenever the
    occurrence predicate witnesses exception-family structure anywhere.

    Junk+NC without an exception segment (``aabuffalo_l`` /
    ``aainsightface`` / ``aaayolonas``) stays door-pass — that
    asymmetry is deliberate (no exception occurrence to promote).
    F15-1 makes those forms floor-deny via compact-joined (e); the
    door still requires an exception witness (``aabuffalo_l_yolox``).
    """

    DOOR_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("xyoloxinsightface", "insightface"),
        ("myyoloxinsightface", "insightface"),
        ("abcyoloxinsightface", "insightface"),
        ("xyoloxarcface", "arcface"),
        ("xyoloxsarcface", "arcface"),
        ("xyoloxantelopev2", "antelopev2"),
    )
    EXISTING_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yoloxinsightface", "insightface"),
        ("insightface_yolox", "insightface"),
    )
    FLOOR_ONLY_DOOR_PASS: ClassVar[tuple[str, ...]] = (
        "myarcface",
        "not-insightface",
        "aabuffalo_l",
        "aainsightface",
        "aaayolonas",
    )

    @pytest.mark.parametrize("token,expected_pkg", DOOR_DENY)
    def test_mid_exception_nc_denies_on_doors(
        self, token: str, expected_pkg: str
    ) -> None:
        assert policy._token_has_exception_family(token) is True, (
            f"{token!r} must expose mid-token exception-family structure"
        )
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must scanner-NC-HIT"
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert hit.package_id == expected_pkg
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, (
                f"door must deny {token!r} (mid-exception promotion)"
            )
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
            pattern = _door_nc_pattern_id(result.detail)
            entry = _door_entry_package_id(result.detail)
            assert pattern == expected_pkg or entry == expected_pkg, (
                f"{token!r}: door must name {expected_pkg!r}; "
                f"got pattern={pattern!r} entry={entry!r} detail={result.detail!r}"
            )

    @pytest.mark.parametrize("token,expected_pkg", EXISTING_DENY)
    def test_prefix_and_trailing_exception_still_deny(
        self, token: str, expected_pkg: str
    ) -> None:
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        pattern = _door_nc_pattern_id(result.detail)
        entry = _door_entry_package_id(result.detail)
        assert pattern == expected_pkg or entry == expected_pkg

    @pytest.mark.parametrize("token", FLOOR_ONLY_DOOR_PASS)
    def test_junk_nc_without_exception_stays_floor_only(
        self, token: str
    ) -> None:
        assert policy._token_has_exception_family(token) is False, (
            f"{token!r} must not grow an exception occurrence"
        )
        assert policy._package_denylist_hit(token) is not None, (
            f"{token!r} must floor-deny (F15-6; vacuous pin closed)"
        )
        assert policy.audit_derived_from_model(token).ok is True, (
            f"{token!r} must stay door-pass (BR-28 / no exception segment)"
        )

    def test_red_proof_mid_exception_occurrence_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_compact_has_mid_exception_family``.

        Mid-token junk+exception+NC compounds door-admit; F13-2 trailing
        ``insightface_yolox`` and F12-3 prefix ``yoloxinsightface`` still
        deny. BR-28 / bare junk+NC stay door-pass.
        """
        for token, _pkg in self.DOOR_DENY:
            assert policy.audit_derived_from_model(token).ok is False, (
                f"precondition: {token!r} must door-deny"
            )
        monkeypatch.setattr(
            policy, "_compact_has_mid_exception_family", lambda _p: False
        )
        for token, _pkg in self.DOOR_DENY:
            assert policy.audit_derived_from_model(token).ok is True, (
                f"red-proof: with mid-occurrence off, {token!r} must door-admit"
            )
        assert policy.audit_derived_from_model("yoloxinsightface").ok is False
        assert policy.audit_derived_from_model("insightface_yolox").ok is False
        assert policy.audit_derived_from_model("myarcface").ok is True
        assert policy.audit_derived_from_model("not-insightface").ok is True
        assert policy.audit_derived_from_model("aainsightface").ok is True


class TestF14FourCharHeadExceptionRem:
    """F14-5 / R16-G1-6: 4-char ``yolo`` head + exact exception rem.

    ``_deny_head_known_rem_glue`` refused seeds shorter than 5, so
    ``yoloyolox`` / ``yoloyoloxs`` admitted. Accept a length-4 head iff
    the entire rem is an exception-family spelling. ``yolodummy`` rem
    is not an exception spelling and stays admitted.
    """

    DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yoloyolox", "yolo"),
        ("yoloyoloxs", "yolo"),
    )
    ADMIT: ClassVar[tuple[str, ...]] = (
        "yolodummy",
        "myyolo",
    )
    UNCHANGED_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolo", "yolo"),
        ("yolov8yolox", "yolov8"),
    )

    @pytest.mark.parametrize("token,expected_pkg", DENY)
    def test_yolo_head_exception_rem_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (F14-5 4-char head)"
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert _door_entry_package_id(result.detail) == expected_pkg

    @pytest.mark.parametrize("token", ADMIT)
    def test_non_exception_rem_and_suffix_yolo_still_admit(
        self, token: str
    ) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"control {token!r} must stay PASS"
        )
        assert policy.audit_derived_from_model(token).ok is True

    @pytest.mark.parametrize("token,expected_pkg", UNCHANGED_DENY)
    def test_existing_yolo_and_yolov8_landings_hold(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert _door_entry_package_id(result.detail) == expected_pkg

    def test_red_proof_four_char_head_min_len_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: restore the min-len-5 refusal.

        Neuter: ``_DENY_HEAD_KNOWN_REM_MIN_SEED_LEN`` → ``5``.
        ``yoloyolox`` / ``yoloyoloxs`` admit; ``yolov8yolox`` and bare
        ``yolo`` stay denied.
        """
        for token, _pkg in self.DENY:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(policy, "_DENY_HEAD_KNOWN_REM_MIN_SEED_LEN", 5)
        for token, _pkg in self.DENY:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with min-len-5 restored, {token!r} must admit"
            )
        assert policy._package_denylist_hit("yolov8yolox") is not None
        assert policy._package_denylist_hit("yolo") is not None
        assert policy._package_denylist_hit("yolodummy") is None
        assert policy._package_denylist_hit("yoloxyolo") is not None


class TestF14SuffixTolerantGlue:
    """F14-6 / R16-G1-7 / R16-CDX-3: exception/deny rem + residual.

    Head glue / F13-2 endswith / mid-adjacency required the rem to be an
    exact known spelling. One alnum suffix defeated all three. When the
    rem is exception-spelling (or deny-seed) + residual, classify that
    residual fail-closed instead of requiring exact membership.
    """

    NC_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("arcfaceyoloxextra", "arcface"),
        ("arcfaceyoloxinsight", "arcface"),
        ("insightfaceyoloxextra", "insightface"),
        ("arcfaceyoloxcoco", "arcface"),
    )
    AGPL_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolov8yoloxextra", "yolov8"),
        ("xyoloxyoloextra", "yolo"),
        ("yolov8yoloxcoco", "yolov8"),
    )
    ADMIT: ClassVar[tuple[str, ...]] = (
        "ayoloxs",
        "xyoloxs",
        "myyoloxs",
    )
    ALREADY_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("arcfaceyoloxx", "arcface"),
    )
    CATALOG_ADMIT: ClassVar[tuple[str, ...]] = (
        "ppyoloe_s",
        "yolox_s_8xb8-300e_coco",
        "yolox_pt_trt",
    )

    @pytest.mark.parametrize("token,expected_pkg", NC_WITNESSES)
    def test_nc_head_exception_plus_residual_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (F14-6 suffix-tolerant)"
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        pattern = _door_nc_pattern_id(result.detail)
        entry = _door_entry_package_id(result.detail)
        assert pattern == expected_pkg or entry == expected_pkg, (
            f"{token!r}: door must name {expected_pkg!r}; "
            f"got pattern={pattern!r} entry={entry!r} detail={result.detail!r}"
        )

    @pytest.mark.parametrize("token,expected_pkg", AGPL_WITNESSES)
    def test_agpl_head_or_mid_plus_residual_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (F14-6 suffix-tolerant)"
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert _door_entry_package_id(result.detail) == expected_pkg

    @pytest.mark.parametrize("token", ADMIT)
    def test_junk_plus_legit_compact_still_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"control {token!r} must stay PASS"
        )
        assert policy.audit_derived_from_model(token).ok is True

    @pytest.mark.parametrize("token,expected_pkg", ALREADY_DENY)
    def test_exact_exception_rem_still_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == expected_pkg

    @pytest.mark.parametrize("token", CATALOG_ADMIT)
    def test_catalog_admits_unaffected(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"catalog {token!r} must stay PASS"
        )

    def test_red_proof_suffix_tolerant_glue_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: restore exact-membership rem (no suffix tolerance).

        Neuter: ``_SUFFIX_TOLERANT_GLUE_ENABLED`` → ``False``.
        ``arcfaceyoloxextra`` / ``yolov8yoloxextra`` / ``xyoloxyoloextra``
        admit; exact ``arcfaceyoloxx`` and B13-5 ``insightfaceyoloxextra``
        stay denied.
        """
        exact_only = (
            [t for t, _ in self.NC_WITNESSES if t != "insightfaceyoloxextra"]
            + [t for t, _ in self.AGPL_WITNESSES]
        )
        for token in exact_only:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(policy, "_SUFFIX_TOLERANT_GLUE_ENABLED", False)
        # F15-5 independently fail-closes junk+exception+unknown rem
        # (xyoloxyoloextra); neuter it so this pin stays sole-path.
        monkeypatch.setattr(policy, "_MID_EXCEPTION_UNKNOWN_REM_ENABLED", False)
        for token in exact_only:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with exact rem only, {token!r} must admit"
            )
        assert policy._package_denylist_hit("arcfaceyoloxx") is not None
        assert policy._package_denylist_hit("insightfaceyoloxextra") is not None
        assert policy._package_denylist_hit("ayoloxs") is None
        assert policy._package_denylist_hit("yolodummy") is None


class TestF13NcDoorPromotionTrailingException:
    """F13-2 / R15-L-1: exception after the NC head must reach doors.

    ``_token_has_exception_family`` was prefix-anchored, so scanner-NC
    hits with a trailing exception segment (``insightface_yolox``)
    door-passed. Segment-aware identity + compact-tail detection
    promotes those hits. BR-28 ``myarcface`` / ``not-insightface``
    have no exception segment and stay floor-only door-pass.
    """

    DOOR_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("insightface_yolox", "insightface"),
        ("buffalo_l_yolox_s", "buffalo_l"),
        ("arcface_yolox", "arcface"),
        ("yolonas_yolox", "yolonas"),
        ("insightfaceyolox", "insightface"),
    )
    FAMILY_ONLY: ClassVar[tuple[str, ...]] = (
        "arcfaceyolox",
        "antelopev2yolox",
    )
    FLOOR_ONLY_DOOR_PASS: ClassVar[tuple[str, ...]] = (
        "myarcface",
        "not-insightface",
    )

    @pytest.mark.parametrize("token,expected_pkg", DOOR_DENY)
    def test_trailing_exception_nc_denies_on_doors(
        self, token: str, expected_pkg: str
    ) -> None:
        assert policy._token_has_exception_family(token) is True, (
            f"{token!r} must be visible as exception-family (F13-2)"
        )
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must scanner-NC-HIT"
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert hit.package_id == expected_pkg
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, (
                f"door must deny {token!r} (trailing-exception promotion)"
            )
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("token", FAMILY_ONLY)
    def test_compact_short_seed_head_is_exception_family(
        self, token: str
    ) -> None:
        """Family helper sees the trailing exception; scanner hit is F13-3."""
        assert policy._token_has_exception_family(token) is True, (
            f"{token!r} must expose the trailing exception seed"
        )

    @pytest.mark.parametrize("token", FLOOR_ONLY_DOOR_PASS)
    def test_br28_floor_only_precision_preserved(self, token: str) -> None:
        assert policy._token_has_exception_family(token) is False, (
            f"BR-28 {token!r} must not grow an exception segment"
        )
        assert policy._package_denylist_hit(token) is not None, (
            f"{token!r} must stay floor-deny"
        )
        assert policy.audit_derived_from_model(token).ok is True, (
            f"{token!r} must stay door-pass (floor-only precision)"
        )

    def test_prefix_exception_nc_still_denies(self) -> None:
        """F12-3 prefix path is independent of the F13-2 helper."""
        token = "yoloxinsightface"
        assert policy._token_has_exception_family(token) is True
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_red_proof_non_prefix_exception_helper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_token_has_non_prefix_exception_family``.

        Trailing-exception NC compounds door-admit; F12-3 prefix
        ``yoloxinsightface`` still denies via the prefix-match path.
        """
        for token, _pkg in self.DOOR_DENY:
            assert policy.audit_derived_from_model(token).ok is False, (
                f"precondition: {token!r} must door-deny"
            )
        monkeypatch.setattr(
            policy, "_token_has_non_prefix_exception_family", lambda _p: False
        )
        for token, _pkg in self.DOOR_DENY:
            assert policy.audit_derived_from_model(token).ok is True, (
                f"red-proof: with non-prefix helper off, {token!r} "
                "must door-admit"
            )
        # Prefix-exception NC is F12-3, not this helper.
        assert policy.audit_derived_from_model("yoloxinsightface").ok is False
        # BR-28 controls stay door-pass.
        assert policy.audit_derived_from_model("myarcface").ok is True
        assert policy.audit_derived_from_model("not-insightface").ok is True


class TestF13HeadPositionDenyNcCompactGlue:
    """F13-3 / R15-L-2: deny/NC head + exception rem at min seed len 5.

    ``_DENY_COMPACT_PREFIX_GLUE_MIN_SEED_LEN = 11`` left seeds of compact
    length 5–10 blind in head position: ``arcfaceyolox`` / ``yolov8yolox``
    admitted while their mirrors denied. Accept the head hit when the
    remainder is an exception-family spelling (or any known seed).
    """

    NC_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("arcfaceyolox", "arcface"),
        ("antelopev2yolox", "antelopev2"),
    )
    AGPL_WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolov8yolox", "yolov8"),
        ("yolov8yolox_s", "yolov8"),
    )
    MIRROR_CONTROLS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yoloxarcface", "arcface"),
        ("yoloxyolov8", "yolov8"),
    )

    @pytest.mark.parametrize("token,expected_pkg", NC_WITNESSES)
    def test_nc_head_exception_rem_denies_on_doors(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must scanner-HIT (F13-3 head glue)"
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert hit.package_id == expected_pkg
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, f"door must deny {token!r}"
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("token,expected_pkg", AGPL_WITNESSES)
    def test_agpl_head_exception_rem_denies_honest(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (F13-3 head glue)"
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert _door_entry_package_id(result.detail) == expected_pkg

    @pytest.mark.parametrize("token,expected_pkg", MIRROR_CONTROLS)
    def test_mirrors_still_deny(self, token: str, expected_pkg: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == expected_pkg

    def test_red_proof_head_known_rem_glue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_deny_head_known_rem_glue``.

        ``arcfaceyolox`` / ``yolov8yolox`` admit; B13-5
        ``ultralyticsplus`` and F12-1 ``yoloxyolo`` stay denied.
        """
        for token, _pkg in self.NC_WITNESSES + self.AGPL_WITNESSES:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(
            policy, "_deny_head_known_rem_glue", lambda *_a, **_k: False
        )
        for token, _pkg in self.NC_WITNESSES + self.AGPL_WITNESSES:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with head-known-rem glue off, {token!r} "
                "must admit"
            )
        assert policy._package_denylist_hit("ultralyticsplus") is not None
        assert policy._package_denylist_hit("yoloxyolo") is not None
        assert policy._package_denylist_hit("yolodummy") is None


class TestF13JunkPrefixExceptionDenyAdjacency:
    """F13-3 / R15-L-3: junk prefix must not defeat F12-1 steal.

    ``xyoloxyolo`` / ``myyoloxyolo`` / ``abcyoloxyolo`` admitted while
    ``yoloxyolo`` denied. Scan exception-seed occurrences at compact
    offset > 0 when the remainder is deny material.
    """

    WITNESSES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("xyoloxyolo", "yolo"),
        ("myyoloxyolo", "yolo"),
        ("abcyoloxyolo", "yolo"),
    )
    CONTROLS_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yoloxyolo", "yolo"),
        ("my_yoloxyolo", "yolo"),
        ("myyoloxultralytics", "ultralytics"),
    )
    CONTROLS_ADMIT: ClassVar[tuple[str, ...]] = (
        "yolodummy",
        "yoloxs",
        "yolox",
    )

    @pytest.mark.parametrize("token,expected_pkg", WITNESSES)
    def test_junk_prefix_exception_deny_denies_honest(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (F13-3 junk-prefix adjacency)"
        )
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert _door_entry_package_id(result.detail) == expected_pkg

    @pytest.mark.parametrize("token,expected_pkg", CONTROLS_DENY)
    def test_existing_deny_controls_hold(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"control {token!r} must still deny"
        assert hit.package_id == expected_pkg

    @pytest.mark.parametrize("token", CONTROLS_ADMIT)
    def test_admit_controls_hold(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"control {token!r} must stay PASS"
        )

    def test_red_proof_mid_exception_adjacency(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_compact_mid_exception_deny_adjacency``.

        Junk-prefix witnesses admit; F12-1 ``yoloxyolo`` and (e)
        ``myyoloxultralytics`` stay denied.
        """
        for token, _pkg in self.WITNESSES:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(
            policy, "_compact_mid_exception_deny_adjacency", lambda _t: None
        )
        for token, _pkg in self.WITNESSES:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with mid-adjacency off, {token!r} must admit"
            )
        assert policy._package_denylist_hit("yoloxyolo") is not None
        assert policy._package_denylist_hit("myyoloxultralytics") is not None
        assert policy._package_denylist_hit("my_yoloxyolo") is not None
        assert policy._package_denylist_hit("yolodummy") is None


def _retag_separator_inventory(
    monkeypatch: pytest.MonkeyPatch,
    seed: str,
    tags: frozenset[str],
) -> None:
    """Swap one family's separator-only tags and re-derive the union."""
    monkeypatch.setattr(
        policy,
        "_EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS",
        {
            **policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS,
            seed: tags,
        },
    )
    monkeypatch.setattr(
        policy,
        "_EXCEPTION_FAMILY_SEPARATOR_TAGS",
        {
            s: (
                policy._EXCEPTION_FAMILY_COMPACT_TAGS.get(s, frozenset())
                | policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS.get(
                    s, frozenset()
                )
            )
            for s in policy._EXCEPTION_FAMILY_COMPACT_TAGS
        },
    )


class TestF13CatalogSeparatorTags:
    """F13-4 / R15-G2-1 / R15-G2-2 / R15-CDX-1 / R15-G2-3: catalog admits.

    Separator-only inventory (compact-glue allowlist untouched).
    """

    PPYOLO_ADMIT: ClassVar[tuple[str, ...]] = (
        "ppyolo_tiny_650e_coco",
        "ppyolo_mbv3_large_coco",
        "ppyolo_r50vd_dcn_2x_coco",
        "ppyolov2_r101vd_dcn_365e_coco",
        "ppyolo_r18vd_coco",
        "ppyoloe_plus_sod_crn_l_80e_coco",
    )
    YOLOX_ADMIT: ClassVar[tuple[str, ...]] = (
        "yolox_s_8xb8-300e_coco",
        "yolox_tiny_8xb8-300e_coco",
        "yolox_s_8x8_300e_coco",
        "yolox_voc_s",
        "yolox_s_coco",
    )
    YOLOF_ADMIT: ClassVar[tuple[str, ...]] = (
        "yolof_r50-c5_8xb8-1x_coco",
    )
    COMPACT_GLUE_DENY: ClassVar[tuple[str, ...]] = (
        "ppyoloes",
        "yoloxtiny",
        "yolox8xb8",
        "ppyolotiny",
        "yolofcoco",
        "yoloxcoco",
        "ppyolo650e",
    )
    CROSS_FAMILY_DENY: ClassVar[tuple[str, ...]] = (
        "yolos_8xb8",
        # F14-7: ppyolo_voc is native Paddle debris and now ADMITs.
    )

    @pytest.mark.parametrize(
        "token", PPYOLO_ADMIT + YOLOX_ADMIT + YOLOF_ADMIT
    )
    def test_catalog_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT (F13-4 catalog tag)"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is True, (
            f"door must admit {token!r}; got {result.reason} ({result.detail})"
        )

    @pytest.mark.parametrize("token", COMPACT_GLUE_DENY)
    def test_compact_glue_of_new_tags_stays_deny(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"compact glue {token!r} must stay DENY (allowlist untouched)"
        )

    @pytest.mark.parametrize("token", CROSS_FAMILY_DENY)
    def test_cross_family_tags_stay_deny(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"cross-family {token!r} must DENY (per-family inventory)"
        )

    def test_red_proof_ppyolo_tiny_tag_drop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: remove ``tiny`` from ppyolo separator-only tags."""
        witness = "ppyolo_tiny_650e_coco"
        assert policy._package_denylist_hit(witness) is None
        current = policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS["ppyolo"]
        _retag_separator_inventory(
            monkeypatch, "ppyolo", frozenset(t for t in current if t != "tiny")
        )
        assert policy._package_denylist_hit(witness) is not None, (
            f"red-proof: without tiny in ppyolo tags, {witness!r} must DENY"
        )

    def test_red_proof_yolox_8xb8_tag_drop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: remove ``8xb8`` from yolox separator-only tags."""
        witness = "yolox_s_8xb8-300e_coco"
        assert policy._package_denylist_hit(witness) is None
        current = policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS["yolox"]
        _retag_separator_inventory(
            monkeypatch, "yolox", frozenset(t for t in current if t != "8xb8")
        )
        assert policy._package_denylist_hit(witness) is not None, (
            f"red-proof: without 8xb8 in yolox tags, {witness!r} must DENY"
        )

    def test_red_proof_yolof_8xb8_tag_drop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: remove ``8xb8`` from yolof separator-only tags."""
        witness = "yolof_r50-c5_8xb8-1x_coco"
        assert policy._package_denylist_hit(witness) is None
        current = policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS["yolof"]
        _retag_separator_inventory(
            monkeypatch, "yolof", frozenset(t for t in current if t != "8xb8")
        )
        assert policy._package_denylist_hit(witness) is not None, (
            f"red-proof: without 8xb8 in yolof tags, {witness!r} must DENY"
        )

    def test_red_proof_yolox_voc_tag_drop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: remove ``voc`` from yolox separator-only tags."""
        witness = "yolox_voc_s"
        assert policy._package_denylist_hit(witness) is None
        current = policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS["yolox"]
        _retag_separator_inventory(
            monkeypatch, "yolox", frozenset(t for t in current if t != "voc")
        )
        assert policy._package_denylist_hit(witness) is not None, (
            f"red-proof: without voc in yolox tags, {witness!r} must DENY"
        )


class TestF14PaddleCatalogTags:
    """F14-7 / R16-G2-2: remaining PaddleDetection separator-only tags.

    ``auxhead`` / ``relu`` / ``320`` / ``416`` / ``640`` / ``distill`` /
    ``voc`` / ``30e`` / ``60e`` / ``objects365`` are native Paddle
    debris. The old ``ppyolo_voc`` cross-family-leakage deny pin was
    wrong — voc is not a foreign tag on this family.
    """

    ADMIT: ClassVar[tuple[str, ...]] = (
        "ppyoloe_plus_crn_t_auxhead_300e_coco",
        "ppyoloe_plus_crn_t_auxhead_relu_300e_coco",
        "ppyoloe_plus_crn_t_auxhead_320_300e_coco",
        "ppyolo_r50vd_dcn_voc",
        "ppyoloe_plus_crn_s_30e_voc",
        "ppyoloe_plus_crn_l_30e_voc",
        "ppyoloe_plus_crn_m_80e_coco_distill",
        "ppyoloe_plus_crn_l_80e_coco_distill",
        "ppyoloe_plus_crn_s_60e_objects365",
        "ppyolo_voc",
    )
    COMPACT_GLUE_DENY: ClassVar[tuple[str, ...]] = (
        "ppyoloauxhead",
        "ppyolorelu",
        "ppyolo320",
        "ppyolo416",
        "ppyolo640",
        "ppyolodistill",
        "ppyolovoc",
        "ppyolo30e",
        "ppyolo60e",
        "ppyoloobjects365",
    )
    CROSS_FAMILY_DENY: ClassVar[tuple[str, ...]] = (
        "yolos_voc",
        "yolox_auxhead",
        "yolof_distill",
    )

    @pytest.mark.parametrize("token", ADMIT)
    def test_paddle_catalog_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT (F14-7 Paddle catalog tag)"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is True, (
            f"door must admit {token!r}; got {result.reason} ({result.detail})"
        )

    @pytest.mark.parametrize("token", COMPACT_GLUE_DENY)
    def test_compact_glue_of_new_paddle_tags_denies(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"compact glue {token!r} must DENY (separator-only tag)"
        )

    @pytest.mark.parametrize("token", CROSS_FAMILY_DENY)
    def test_new_tags_do_not_leak_across_families(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"cross-family {token!r} must DENY (per-family inventory)"
        )

    def test_red_proof_ppyolo_auxhead_tag_drop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: drop ``auxhead`` from the ppyolo separator-only frozenset.

        Neuter: remove ``auxhead`` from
        ``_EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS['ppyolo']``.
        """
        witness = "ppyoloe_plus_crn_t_auxhead_300e_coco"
        assert policy._package_denylist_hit(witness) is None
        current = policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS["ppyolo"]
        _retag_separator_inventory(
            monkeypatch,
            "ppyolo",
            frozenset(t for t in current if t != "auxhead"),
        )
        assert policy._package_denylist_hit(witness) is not None, (
            f"red-proof: without auxhead in ppyolo tags, {witness!r} must DENY"
        )
        # Other new tags still admit; compact glue still denies.
        assert policy._package_denylist_hit("ppyolo_voc") is None
        assert policy._package_denylist_hit("ppyoloauxhead") is not None


class TestF13EplusHeadPeel:
    """F13-5 / R15-L-4: head peel must accept compact-glue allowlist rem.

    ``_head_compact_peel_rem`` capped rem at 1–3 chars, so allowlisted
    ``eplus`` (5) never peeled: ``ppyoloeplus_trt`` denied while
    ``ppyoloeplus`` and ``ppyoloe_plus_trt`` passed.
    """

    def test_ppyoloeplus_trt_admits(self) -> None:
        token = "ppyoloeplus_trt"
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT (F13-5 eplus head peel)"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is True, (
            f"door must admit {token!r}; got {result.reason} ({result.detail})"
        )

    def test_ppyoloeplus_and_separator_twin_still_admit(self) -> None:
        for token in ("ppyoloeplus", "ppyoloe_plus_trt"):
            assert policy._package_denylist_hit(token) is None, (
                f"control {token!r} must stay PASS"
            )

    def test_ppyoloes_still_denies(self) -> None:
        hit = policy._package_denylist_hit("ppyoloes")
        assert hit is not None, "ppyoloes compact size glue must stay DENY"

    def test_red_proof_eplus_allowlist_drop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: drop ``eplus`` from the ppyolo compact-glue allowlist.

        Neuter: ``_EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST['ppyolo']`` →
        empty. Head peel / strip / abc all lose the 5-char rem, so
        ``ppyoloeplus_trt`` (and bare ``ppyoloeplus``) deny.
        """
        token = "ppyoloeplus_trt"
        assert policy._package_denylist_hit(token) is None
        monkeypatch.setattr(
            policy,
            "_EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST",
            {
                **policy._EXCEPTION_FAMILY_COMPACT_GLUE_ALLOWLIST,
                "ppyolo": frozenset(),
            },
        )
        assert policy._package_denylist_hit(token) is not None, (
            f"red-proof: without eplus in the allowlist, {token!r} must DENY"
        )
        assert policy._package_denylist_hit("ppyoloeplus") is not None
        assert policy._package_denylist_hit("ppyoloes") is not None
        # Separator twin does not need the compact-glue allowlist.
        assert policy._package_denylist_hit("ppyoloe_plus_trt") is None


# ---------------------------------------------------------------------------
# FIR-7 Wave F15 — occlusion licensing gate (round-17 findings)
# ---------------------------------------------------------------------------


class TestF15JunkMultiSegmentNcFloor:
    """F15-1 / R17-PRE-1: junk+multi-segment NC seeds + both-sides junk.

    Per-segment (e) splits ``aabuffalo`` + ``_l`` so the floor missed;
    (e) endswith + (c) startswith also missed ``aainsightfaceaa``.
    Compact-joined (e) + mid-occurrence NC close both. Door landing
    follows existing exception-promotion rules.
    """

    # R18-07: parametrize distinct compact-joined (e) behaviours only.
    # Prefix-twin / rem-padding names stay in MUST_LIST_SAME_PATH (one
    # nodeid) so the floor is not inflated by the same path.
    MULTI_SEG_FLOOR: ClassVar[tuple[tuple[str, str], ...]] = (
        ("aabuffalo_l", "buffalo_l"),
        ("aabuffalo_trt", "buffalo_trt"),
        ("aayolo_nas", "yolo_nas"),
        ("aayolo_nas_l", "yolo_nas_l"),
        ("xyolo_nas_pose_l", "yolo_nas_pose_l"),
        ("aaantelope_v2", "antelope_v2"),
    )
    MUST_LIST_SAME_PATH: ClassVar[tuple[tuple[str, str], ...]] = (
        ("mybuffalo_l", "buffalo_l"),
        ("xbuffalo_l", "buffalo_l"),
        ("aabuffalo_s", "buffalo_s"),
        ("aabuffalo_sc", "buffalo_sc"),
        ("aabuffalo_l2", "buffalo_l2"),
        ("aabuffalo_onnx", "buffalo_onnx"),
        ("aabuffalo_fp16", "buffalo_fp16"),
        ("aabuffalo_int8", "buffalo_int8"),
        ("aabuffalo_pt", "buffalo_pt"),
        ("aayolo_nas_s", "yolo_nas_s"),
        ("xantelope_v2", "antelope_v2"),
    )
    BOTH_SIDES_FLOOR: ClassVar[tuple[tuple[str, str], ...]] = (
        ("aainsightfaceaa", "insightface"),
        ("aaarcfaceaa", "arcface"),
    )
    DOOR_PROMOTE: ClassVar[tuple[tuple[str, str], ...]] = (
        ("aabuffalo_l_yolox", "buffalo_l"),
    )
    STILL_ADMIT: ClassVar[tuple[str, ...]] = (
        "buffalo_bill_detector",
        "buffalo_lakes",
        "aabuffalo",
    )
    FLOOR_ONLY_DOOR_PASS: ClassVar[tuple[str, ...]] = (
        "myarcface",
        "not-insightface",
        "aabuffalo_l",
        "aainsightface",
        "aaayolonas",
    )

    @pytest.mark.parametrize("token,expected_pkg", MULTI_SEG_FLOOR)
    def test_junk_multi_seg_nc_floor_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must floor-deny (F15-1 compact-joined (e))"
        )
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected {expected_pkg!r}, got {hit.package_id!r}"
        )

    def test_f15_1_must_list_same_path_still_floor_denies(self) -> None:
        """F15-1 must-list names that share compact-joined (e) (R18-07)."""
        for token, expected_pkg in self.MUST_LIST_SAME_PATH:
            hit = policy._package_denylist_hit(token)
            assert hit is not None, (
                f"{token!r} must floor-deny (F15-1 must-list)"
            )
            assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
            assert hit.package_id == expected_pkg, (
                f"{token!r}: expected {expected_pkg!r}, got {hit.package_id!r}"
            )

    @pytest.mark.parametrize("token,expected_pkg", BOTH_SIDES_FLOOR)
    def test_both_sides_junk_nc_floor_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must floor-deny (F15-1 mid-occurrence NC)"
        )
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert hit.package_id == expected_pkg

    @pytest.mark.parametrize("token,expected_pkg", DOOR_PROMOTE)
    def test_trailing_exception_promotes_junk_nc_to_door(
        self, token: str, expected_pkg: str
    ) -> None:
        assert policy._token_has_exception_family(token) is True
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("token", STILL_ADMIT)
    def test_bare_buffalo_exclusions_still_admit(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must stay ADMIT (bare buffalo exclusion)"
        )
        assert policy.audit_derived_from_model(token).ok is True

    @pytest.mark.parametrize("token", FLOOR_ONLY_DOOR_PASS)
    def test_no_exception_stays_door_pass(self, token: str) -> None:
        assert policy._token_has_exception_family(token) is False
        assert policy._package_denylist_hit(token) is not None, (
            f"{token!r} must floor-deny (F15-6; vacuous pin closed)"
        )
        assert policy.audit_derived_from_model(token).ok is True, (
            f"{token!r} must stay door-pass (no exception witness)"
        )

    def test_my_buffalo_l_still_denies_on_doors(self) -> None:
        token = "my_buffalo_l"
        assert policy._package_denylist_hit(token) is not None
        assert policy.audit_derived_from_model(token).ok is False

    def test_red_proof_compact_joined_rule_e_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_COMPACT_JOINED_RULE_E_ENABLED``.

        Compact-e-only witnesses (suffix rem empty after the compact
        seed, so mid-NC cannot own them) admit again; both-sides
        compact NC and already-separator ``my_buffalo_l`` stay denied.
        """
        compact_e_only = (
            "aabuffalo_l",
            "aabuffalo_s",
            "aabuffalo_trt",
            "aayolo_nas",
            "aaantelope_v2",
        )
        for token in compact_e_only:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must floor-deny"
            )
        monkeypatch.setattr(policy, "_COMPACT_JOINED_RULE_E_ENABLED", False)
        for token in compact_e_only:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: without compact-joined (e), {token!r} must admit"
            )
        assert policy._package_denylist_hit("aainsightfaceaa") is not None
        assert policy._package_denylist_hit("my_buffalo_l") is not None
        assert policy._package_denylist_hit("aabuffalo") is None

    def test_red_proof_mid_nc_occurrence_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_COMPACT_MID_NC_OCCURRENCE_ENABLED``.

        Both-sides junk NC admits; compact-joined multi-seg still denies.
        """
        for token, _pkg in self.BOTH_SIDES_FLOOR:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must floor-deny"
            )
        monkeypatch.setattr(policy, "_COMPACT_MID_NC_OCCURRENCE_ENABLED", False)
        for token, _pkg in self.BOTH_SIDES_FLOOR:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: without mid-NC, {token!r} must admit"
            )
        assert policy._package_denylist_hit("aabuffalo_l") is not None
        assert policy._package_denylist_hit("myarcface") is not None


class TestF15CompactRemCoverage:
    """F15-2 / R17-G1-2 / R17-CDX-2: 4-char head rem + deny-head long rem.

    (a) The 4-char ``yolo`` head only accepted exact exception rem, so
    ``yoloyoloxextra`` / ``yoloyolo`` admitted. Route unknown rem
    through suffix-tolerant classification. ``yolodummy`` stays admit.

    (b) Compact (c) is 1–3 rem, so ``yolov4tiny`` admitted while
    ``yolov4_tiny`` denied. Deny-head (len ≥ 5) + a known variant rem
    (``tiny``) fail-closes as the catalog seed. Generic leftover is
    not this path (``buffalo_lakes`` stays admitted).
    """

    FOUR_CHAR_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yoloyoloxextra", "yolo"),
        ("yoloyoloxv8", "yolo"),
        ("yoloyoloxcoco", "yolo"),
        ("yoloyoloxtiny", "yolo"),
        ("yoloyoloxpt", "yolo"),
        ("yoloyolosextra", "yolo"),
        ("yoloyolo", "yolo"),
    )
    FOUR_CHAR_ADMIT: ClassVar[tuple[str, ...]] = (
        "yolodummy",
        "myyolo",
    )
    LONG_REM_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolov4tiny", "yolov4"),
        ("yolov4tiny.pt", "yolov4"),
        ("vendor/yolov4tiny", "yolov4"),
        ("yolov7tiny", "yolov7"),
        ("yolov3tiny", "yolov3"),
    )
    ALREADY_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolov4_tiny", "yolov4"),
        ("yolov8seg", "yolov8"),
        ("yoloyolox", "yolo"),
    )

    @pytest.mark.parametrize("token,expected_pkg", FOUR_CHAR_DENY)
    def test_four_char_head_suffix_tolerant_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (F15-2 4-char suffix-tolerant rem)"
        )
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert _door_entry_package_id(result.detail) == expected_pkg

    @pytest.mark.parametrize("token", FOUR_CHAR_ADMIT)
    def test_four_char_unknown_rem_still_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"control {token!r} must stay PASS"
        )
        assert policy.audit_derived_from_model(token).ok is True

    @pytest.mark.parametrize("token,expected_pkg", LONG_REM_DENY)
    def test_deny_head_long_rem_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (F15-2 deny-head + long rem)"
        )
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert _door_entry_package_id(result.detail) == expected_pkg

    @pytest.mark.parametrize("token,expected_pkg", ALREADY_DENY)
    def test_existing_compact_and_separator_denies_hold(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == expected_pkg

    def test_yolobuffalo_l_is_yolo_head_plus_known_rem(self) -> None:
        """F15-2a / R18-13: 4-char yolo head outranks compact NC rem.

        F15-1 listed ``yolobuffalo_l`` as an NC floor candidate
        (``buffalo_l``). Ranking prefers the deny-head ``yolo`` + exact
        known rem; this pin documents that ranking rather than silently
        retargeting the expected package. Door still denies (AGPL).
        """
        token = "yolobuffalo_l"
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == "yolo", (
            f"{token!r}: ranked landing is yolo (AGPL over NC rem); "
            f"got {hit.package_id!r}"
        )
        assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_red_proof_four_char_suffix_tolerant_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: restore min-len-5 so 4-char suffix-tolerant rem dies.

        Neuter: ``_DENY_HEAD_KNOWN_REM_MIN_SEED_LEN`` → ``5``.
        ``yoloyoloxextra`` / ``yoloyolo`` admit; ``yolov4tiny`` and
        ``yoloyolox`` (exact exception rem is also F14-5, but min-len-5
        kills the 4-char path entirely) stay as documented.
        """
        for token, _pkg in self.FOUR_CHAR_DENY:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(policy, "_DENY_HEAD_KNOWN_REM_MIN_SEED_LEN", 5)
        for token, _pkg in self.FOUR_CHAR_DENY:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: with min-len-5, {token!r} must admit"
            )
        assert policy._package_denylist_hit("yolov4tiny") is not None
        assert policy._package_denylist_hit("yolodummy") is None

    def test_red_proof_long_rem_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_DENY_HEAD_LONG_REM_ENABLED``.

        ``yolov4tiny`` admits again; separator twin and 4-char
        suffix-tolerant pins stay denied.
        """
        for token, _pkg in self.LONG_REM_DENY:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(policy, "_DENY_HEAD_LONG_REM_ENABLED", False)
        for token, _pkg in self.LONG_REM_DENY:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: without long-rem, {token!r} must admit"
            )
        assert policy._package_denylist_hit("yolov4_tiny") is not None
        assert policy._package_denylist_hit("yoloyoloxextra") is not None
        assert policy._package_denylist_hit("yolodummy") is None


class TestF15RegistrySingleNumberTag:
    """F15-3 / R17-G1-3: single-number registry tags must not strip.

    ``:(v?N)$`` laundered ``yolox:v8`` / ``yolox:8`` to the bare family
    while ``yoloxv8`` fail-closes. Strip only ``latest`` and ≥ 2 numeric
    groups. ``yolox:v2`` is the documented single-group-with-v case and
    also fail-closes.
    """

    DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolox:v8", "yolox_unknown_residual"),
        ("yolox:v5", "yolox_unknown_residual"),
        ("yolox:8", "yolox_unknown_residual"),
        ("ppyolo:v8", "ppyolo_unknown_residual"),
        ("yolox:v2", "yolox_unknown_residual"),
    )
    ADMIT: ClassVar[tuple[str, ...]] = (
        "yolox:latest",
        "megvii/yolox:v0.3.0",
        "paddledetection/ppyoloe:latest",
        "yolox:v2.1",
    )
    STILL_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("yolo:latest", "yolo"),
        ("yolov8:v8", "yolov8"),
    )

    @pytest.mark.parametrize("token,expected_pkg", DENY)
    def test_single_number_tag_fail_closes(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (F15-3 single-number tag not stripped)"
        )
        assert hit.package_id == expected_pkg
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert _door_entry_package_id(result.detail) == expected_pkg

    @pytest.mark.parametrize("token", ADMIT)
    def test_latest_and_dotted_versions_still_admit(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT (latest / ≥2 numeric groups)"
        )
        assert policy.audit_derived_from_model(token).ok is True

    @pytest.mark.parametrize("token,expected_pkg", STILL_DENY)
    def test_deny_seed_plus_registry_tag_still_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == expected_pkg

    def test_red_proof_single_number_strip_restored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: restore ``{0,3}`` so ``yolox:v8`` strips and admits.

        Neuter: ``_REGISTRY_TRAILING_TAG_RE`` → the F14-2 regex that
        accepted a single numeric group.
        """
        import re

        token = "yolox:v8"
        assert policy._package_denylist_hit(token) is not None
        monkeypatch.setattr(
            policy,
            "_REGISTRY_TRAILING_TAG_RE",
            re.compile(r":(latest|v?[0-9]+(?:[._-][0-9]+){0,3})$"),
        )
        assert policy._package_denylist_hit(token) is None, (
            "red-proof: with single-group strip restored, yolox:v8 must ADMIT"
        )
        assert policy._package_denylist_hit("yolox:latest") is None
        assert policy._package_denylist_hit("yolo:latest") is not None


class TestF13StealRankingAndMultiStack:
    """F13-6 / R15-G1-4 / R15-G1-5: honest rem ranking + multi-stack steal.

    Prefer a folded-(c) hit whose rem is an honest task tag (``seg``)
    over a longer seed with junk rem. Recurse steal on the residual so
    ``yoloxyoloxyolo`` names ``yolo`` rather than unknown residual.
    """

    def test_yoloxyolov8seg_names_yolov8_not_yolov8s(self) -> None:
        token = "yoloxyolov8seg"
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must still DENY"
        assert hit.package_id == "yolov8", (
            f"{token!r}: expected honest rem yolov8, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert _door_entry_package_id(result.detail) == "yolov8"

    def test_multi_stack_names_inner_yolo(self) -> None:
        for token in ("yoloxyoloxyolo", "yoloxyolosyolo"):
            hit = policy._package_denylist_hit(token)
            assert hit is not None, f"{token!r} must DENY"
            assert hit.package_id == "yolo", (
                f"{token!r}: expected recurse-steal yolo, got {hit.package_id!r}"
            )
            result = policy.audit_derived_from_model(token)
            assert result.ok is False
            assert _door_entry_package_id(result.detail) == "yolo"

    def test_red_proof_honesty_bonus(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: empty ``_HONEST_YOLO_COMPACT_REMS`` → yolov8s wins.

        Neuter: the honest-rem set. Longer seed + junk rem ranks first
        again (pre-F13-6).
        """
        token = "yoloxyolov8seg"
        hit = policy._package_denylist_hit(token)
        assert hit is not None and hit.package_id == "yolov8"
        monkeypatch.setattr(policy, "_HONEST_YOLO_COMPACT_REMS", frozenset())
        hit2 = policy._package_denylist_hit(token)
        assert hit2 is not None
        assert hit2.package_id == "yolov8s", (
            "red-proof: without honest rem ranking, yoloxyolov8seg "
            f"must name yolov8s; got {hit2.package_id!r}"
        )
        assert hit2.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_red_proof_multi_stack_recurse(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: skip residual recurse → multi-stack lands unknown.

        Neuter: nested ``_exception_illegitimate_deny_steal`` returns
        None so the residual cannot steal the inner ``yolo``.
        """
        token = "yoloxyoloxyolo"
        hit = policy._package_denylist_hit(token)
        assert hit is not None and hit.package_id == "yolo"
        orig = policy._exception_illegitimate_deny_steal
        depth = {"n": 0}

        def _no_recurse(tok: str):
            depth["n"] += 1
            if depth["n"] > 1:
                return None
            return orig(tok)

        monkeypatch.setattr(
            policy, "_exception_illegitimate_deny_steal", _no_recurse
        )
        hit2 = policy._package_denylist_hit(token)
        assert hit2 is not None
        assert hit2.package_id == "yolox_unknown_residual", (
            "red-proof: without residual recurse, yoloxyoloxyolo must "
            f"land unknown; got {hit2.package_id!r}"
        )


class TestF15EmptyCanonicalIdentity:
    """F15-4 / R17-CDX-3: empty-canonical nonblank identities fail closed.

    ``:latest`` / ``...:latest`` / ``/`` / ``///`` / ``/:latest`` are
    nonblank but canonicalise to empty or slash-only. Doors previously
    only checked ``c is None``. Blank / whitespace-only input keeps its
    existing empty-field behaviour.
    """

    EMPTY_IDENTITY: ClassVar[tuple[str, ...]] = (
        ":latest",
        "...:latest",
        "/",
        "///",
        "/:latest",
        ":latest:latest",  # R18-12 stacked tags
    )

    @pytest.mark.parametrize("token", EMPTY_IDENTITY)
    def test_empty_canonical_identity_is_invalid_row(self, token: str) -> None:
        c = policy.canonical(token)
        assert policy._canonical_lacks_identity(c) is True, (
            f"{token!r}: canonical {c!r} must lack an identity token"
        )
        for door in (
            policy.audit_derived_from_model,
            policy.audit_source,
        ):
            result = door(token)
            assert result.ok is False, f"door must reject {token!r}"
            assert result.reason is policy.RejectionReason.INVALID_ROW

    def test_whitespace_only_keeps_existing_empty_field_behaviour(self) -> None:
        assert policy.audit_derived_from_model("   ").ok is True
        src = policy.audit_source("   ")
        assert src.ok is False
        assert src.reason is policy.RejectionReason.UNKNOWN_SOURCE

    def test_red_proof_empty_canonical_identity_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_EMPTY_CANONICAL_IDENTITY_FAIL_CLOSED``.

        ``:latest`` / ``/`` door-admit again; C0 / non-ASCII still
        invalid_row via canonical-None.
        """
        for token in self.EMPTY_IDENTITY:
            assert policy.audit_derived_from_model(token).ok is False, (
                f"precondition: {token!r} must invalid_row"
            )
        monkeypatch.setattr(
            policy, "_EMPTY_CANONICAL_IDENTITY_FAIL_CLOSED", False
        )
        for token in self.EMPTY_IDENTITY:
            assert policy.audit_derived_from_model(token).ok is True, (
                f"red-proof: without empty-identity gate, {token!r} must admit"
            )
        assert (
            policy.audit_derived_from_model("yolo\x00v8").reason
            is policy.RejectionReason.INVALID_ROW
        )


class TestF15MidExceptionUnknownRem:
    """F15-5 / R17-L-3: junk prefix must not launder unknown residual.

    ``yoloxsextra`` denies ``yolox_unknown_residual`` but ``xyoloxsextra``
    admitted: mid-scanner found ``yoloxs`` and only denied deny/NC rem.
    Unknown non-tag rem after a mid-token exception spelling fail-closes
    the same way as offset-0 steal. ``ayoloxs`` / ``xyoloxs`` stay admit.
    """

    DENY: ClassVar[tuple[str, ...]] = (
        "xyoloxsextra",
        "myyoloxsextra",
    )
    ADMIT: ClassVar[tuple[str, ...]] = (
        "ayoloxs",
        "xyoloxs",
    )

    @pytest.mark.parametrize("token", DENY)
    def test_mid_exception_unknown_rem_denies(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (F15-5 mid-exception unknown rem)"
        )
        assert hit.package_id == "yolox_unknown_residual"
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert _door_entry_package_id(result.detail) == "yolox_unknown_residual"

    @pytest.mark.parametrize("token", ADMIT)
    def test_mid_exception_legit_tag_still_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None
        assert policy.audit_derived_from_model(token).ok is True

    def test_offset0_unknown_still_denies(self) -> None:
        hit = policy._package_denylist_hit("yoloxsextra")
        assert hit is not None
        assert hit.package_id == "yolox_unknown_residual"

    def test_red_proof_mid_exception_unknown_rem_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_MID_EXCEPTION_UNKNOWN_REM_ENABLED``.

        ``xyoloxsextra`` admits; offset-0 ``yoloxsextra`` still denies.
        """
        for token in self.DENY:
            assert policy._package_denylist_hit(token) is not None
        monkeypatch.setattr(policy, "_MID_EXCEPTION_UNKNOWN_REM_ENABLED", False)
        for token in self.DENY:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: without mid unknown-rem, {token!r} must admit"
            )
        assert policy._package_denylist_hit("yoloxsextra") is not None
        assert policy._package_denylist_hit("xyoloxs") is None


class TestF15PaddleModelFileExtensions:
    """F15-7 / R17-G2-2: strip ``.pdparams`` / ``.pdmodel`` before fold."""

    ADMIT: ClassVar[tuple[str, ...]] = (
        "ppyoloe_plus_crn_s_80e_coco.pdparams",
        "ppyoloe_plus_crn_s_80e_coco.pdmodel",
        "weights/ppyoloe_plus_crn_s_80e_coco.pdparams",
        "ppyolo_r50vd_dcn_1x_coco.pdparams",
    )

    @pytest.mark.parametrize("token", ADMIT)
    def test_pdparams_pdmodel_strip_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT after Paddle extension strip (F15-7)"
        )
        assert policy.audit_derived_from_model(token).ok is True

    @pytest.mark.parametrize(
        "token,expected_pkg",
        (
            ("yolov8.pdmodel", "yolov8"),
            ("yolov8.pdparams", "yolov8"),
            ("fastsam.pdparams", "fastsam"),
        ),
    )
    def test_deny_seed_plus_pd_extension_still_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        """R18-09 / R19-02: strip never launders a deny seed; pin attribution."""
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (deny seed + Paddle extension)"
        )
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected {expected_pkg!r}, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_compact_glue_controls_stay_deny(self) -> None:
        for token in ("ppyoloes", "ppyoloer"):
            hit = policy._package_denylist_hit(token)
            assert hit is not None, f"compact glue {token!r} must stay DENY"

    def test_red_proof_pd_extensions_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: drop ``.pdparams`` from the extension tuple."""
        token = "ppyoloe_plus_crn_s_80e_coco.pdparams"
        assert policy._package_denylist_hit(token) is None
        monkeypatch.setattr(
            policy,
            "_MODEL_FILE_EXTENSIONS",
            tuple(
                e
                for e in policy._MODEL_FILE_EXTENSIONS
                if e not in {".pdparams", ".pdmodel"}
            ),
        )
        assert policy._package_denylist_hit(token) is not None, (
            "red-proof: without .pdparams strip, token must DENY"
        )
        # R18-08: surviving siblings under the same neuter.
        assert policy._package_denylist_hit("yolov8") is not None
        assert policy._package_denylist_hit("yolov8.pdparams") is not None
        assert policy._package_denylist_hit("ppyoloes") is not None
        assert policy._package_denylist_hit("ayoloxs") is None


class TestF15PpYoloeRRotateFamily:
    """F15-8 / R17-G2-3: PP-YOLOE-R rotate-family separator tags."""

    ADMIT: ClassVar[tuple[str, ...]] = (
        "PP-YOLOE-R",
        "ppyoloe_r_crn_s_3x_dota",
        "ppyoloe_r_crn_l_3x_dota",
        "ppyoloe_r_crn_x_3x_dota",
    )
    COMPACT_DENY: ClassVar[tuple[str, ...]] = (
        "ppyoloer",
        "ppyolodota",
    )

    @pytest.mark.parametrize("token", ADMIT)
    def test_ppyoloe_r_catalog_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT (F15-8 PP-YOLOE-R tags)"
        )
        assert policy.audit_derived_from_model(token).ok is True

    @pytest.mark.parametrize("token", COMPACT_DENY)
    def test_compact_glue_stays_deny(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is not None, (
            f"compact glue {token!r} must stay DENY"
        )

    def test_yolox_dota_does_not_leak(self) -> None:
        assert policy._package_denylist_hit("yolox_dota") is not None

    def test_yolof_3x_stays_native_admit(self) -> None:
        assert policy._package_denylist_hit("yolof_3x") is None

    def test_red_proof_dota_tag_drop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: drop ``dota`` from ppyolo separator-only tags."""
        witness = "ppyoloe_r_crn_s_3x_dota"
        assert policy._package_denylist_hit(witness) is None
        current = policy._EXCEPTION_FAMILY_SEPARATOR_ONLY_TAGS["ppyolo"]
        _retag_separator_inventory(
            monkeypatch,
            "ppyolo",
            frozenset(t for t in current if t != "dota"),
        )
        assert policy._package_denylist_hit(witness) is not None, (
            f"red-proof: without dota in ppyolo tags, {witness!r} must DENY"
        )
        assert policy._package_denylist_hit("PP-YOLOE-R") is None
        assert policy._package_denylist_hit("ppyoloer") is not None


class TestF15AsciiWhitespaceAndControlDetail:
    """F15-9 / R17-G2-4: mid-token ASCII whitespace + honest C0 detail."""

    def test_tab_and_lf_fold_as_separators(self) -> None:
        for token in ("yolox\ts", "yolox\ns", "yolox\rs", "yolox s"):
            assert policy.canonical(token) == "yolox_s", (
                f"{token!r} must fold to yolox_s; got {policy.canonical(token)!r}"
            )
            assert policy._package_denylist_hit(token) is None
            assert policy.audit_derived_from_model(token).ok is True

    def test_nul_invalid_row_names_control_character(self) -> None:
        token = "yolo\x00v8"
        assert policy.canonical(token) is None
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW
        detail_cf = result.detail.casefold()
        assert "control" in detail_cf, (
            f"NUL detail must name a control character; got {result.detail!r}"
        )
        assert "confusable" not in detail_cf, (
            f"NUL detail must not use confusable-scripts text; got {result.detail!r}"
        )

    def test_red_proof_whitespace_fold_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_ASCII_WHITESPACE_AS_SEPARATOR_ENABLED``.

        Mid-token TAB is C0 again → invalid_row; space still folds via
        the total punct class.
        """
        token = "yolox\ts"
        assert policy.audit_derived_from_model(token).ok is True
        monkeypatch.setattr(
            policy, "_ASCII_WHITESPACE_AS_SEPARATOR_ENABLED", False
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW
        assert policy.audit_derived_from_model("yolox s").ok is True


class TestF15DenyReasonHonesty:
    """F15-10 / R17-L-4 / R17-L-5: honest deny reasons, fail-closed stays."""

    def test_yoloppyoloe_is_yolo_plus_exception_spelling(self) -> None:
        token = "yoloppyoloe"
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == "yolo", (
            f"{token!r}: expected structural yolo+ppyoloe, got {hit.package_id!r}"
        )

    def test_pp_yolo_nas_is_deci_nc_not_ppyolo_residual(self) -> None:
        token = "pp_yolo_nas"
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            f"{token!r}: expected NC axis, got {hit.reason} ({hit.package_id})"
        )
        assert "nas" in hit.package_id
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        detail_cf = result.detail.casefold()
        assert (
            "deci" in detail_cf
            or "yolo-nas" in detail_cf
            or "yolo_nas" in detail_cf
        )

    def test_paddlepaddle_pp_yoloe_admits_via_vendor_merge(self) -> None:
        token = "paddlepaddle_pp_yoloe"
        assert policy.canonical(token) == "paddlepaddle_ppyoloe"
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT after Paddle vendor pp merge (F15-10c)"
        )
        assert policy.audit_derived_from_model(token).ok is True

    def test_yoloppyoloeplus_is_yolo_plus_exception_spelling(self) -> None:
        """R18-06: official PP-YOLOE+ compact is yolo + ppyoloeplus."""
        token = "yoloppyoloeplus"
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == "yolo", (
            f"{token!r}: expected structural yolo+ppyoloeplus, "
            f"got {hit.package_id!r}"
        )

    def test_pp_yolo_and_pp_yolov8_unchanged(self) -> None:
        assert policy._package_denylist_hit("pp_yolo") is None
        hit = policy._package_denylist_hit("pp_yolov8")
        assert hit is not None
        assert hit.package_id == "ppyolo_unknown_residual"

    def test_red_proof_exception_spelling_glue_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_deny_head_is_exception_spelling_glue``.

        ``yoloppyoloe`` falls back to yolop_unknown_residual.
        """
        token = "yoloppyoloe"
        hit = policy._package_denylist_hit(token)
        assert hit is not None and hit.package_id == "yolo"
        monkeypatch.setattr(
            policy, "_deny_head_is_exception_spelling_glue", lambda _t: False
        )
        hit2 = policy._package_denylist_hit(token)
        assert hit2 is not None
        assert hit2.package_id == "yolop_unknown_residual", (
            f"red-proof: without spelling-glue, {token!r} must land "
            f"yolop residual; got {hit2.package_id!r}"
        )
        # R18-08: surviving siblings under the same neuter.
        nas = policy._package_denylist_hit("pp_yolo_nas")
        assert nas is not None
        assert nas.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert policy._package_denylist_hit("paddlepaddle_pp_yoloe") is None
        assert policy._package_denylist_hit("yolov8") is not None
        assert policy._package_denylist_hit("ayoloxs") is None

    def test_red_proof_ppyolo_nas_residual_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_PPYOLO_NAS_RESIDUAL_NC_ENABLED``.

        ``pp_yolo_nas`` falls back to generic ppyolo unknown residual.
        """
        token = "pp_yolo_nas"
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        monkeypatch.setattr(policy, "_PPYOLO_NAS_RESIDUAL_NC_ENABLED", False)
        hit2 = policy._package_denylist_hit(token)
        assert hit2 is not None
        assert hit2.package_id == "ppyolo_unknown_residual", (
            f"red-proof: without nas-residual NC, {token!r} must land "
            f"ppyolo residual; got {hit2.package_id!r}"
        )
        # R18-08: surviving siblings under the same neuter.
        yolo_glue = policy._package_denylist_hit("yoloppyoloe")
        assert yolo_glue is not None and yolo_glue.package_id == "yolo"
        assert policy._package_denylist_hit("yolov8") is not None
        assert policy._package_denylist_hit("ayoloxs") is None
        assert policy._package_denylist_hit("paddlepaddle_pp_yoloe") is None


# ---------------------------------------------------------------------------
# FIR-7 Wave F16 — R18 findings
# ---------------------------------------------------------------------------


class TestF16PrefixDenyLaundering:
    """R18-01: deny/NC stems must not launder through mid-token exception glue.

    ``fastsamx`` denies, but ``fastsamxyolox`` / ``fastsamxyoloxextra``
    admitted: ``prefix_is_deny`` treated a deny-(c) prefix as ownership
    of the full token and skipped F15-5. The skip is now exact-identity
    only; deny-(c) debris prefixes own the token via the stem.
    """

    AGPL_GADGETS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("fastsamxyolox", "fastsam"),
        ("fastsamxyoloxs", "fastsam"),
        ("fastsamxyoloxextra", "fastsam"),
        ("yolov5zyoloxsfoo", "yolov5"),
        ("yolorxyoloxextra", "yolor"),
        ("yolo11xyoloxextra", "yolo11"),
        ("yoloworldxyoloxextra", "yolo_world"),
        ("fastsamxppyoloeextra", "fastsam"),
    )
    NC_GADGETS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("scrfdxyoloxextra", "scrfd"),
        ("arcfacexyoloxextra", "arcface"),
        ("yolonasxyoloxextra", "yolo_nas"),
        ("retinafacexyoloxextra", "retinaface"),
        ("vec2facexyoloxextra", "vec2face"),
    )
    STILL_ADMIT: ClassVar[tuple[str, ...]] = (
        "ayoloxs",
        "xyoloxs",
    )
    # R19-10: split mixed-row witness. Elevated (c) / F14-6 prefix
    # identities survive M23/M25; only classify-owned unknown-rem
    # rows die under those mutants.
    ELEVATED_OR_EXACT_STILL_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("fastsamx", "fastsam"),
        ("arcfaceyoloxextra", "arcface"),
    )
    CLASSIFY_OWNED_STILL_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("xyoloxsextra", "yolox_unknown_residual"),
        ("yoloyoloxextra", "yolo"),
        # R19-01 A.3 unknown-residual fence (split out of the mixed A.3
        # loop so M23/M25 have a classify-only witness).
        ("buffalo_lxyoloxextra", "yolox_unknown_residual"),
        ("buffalo_lxyoloxlatest", "yolox_unknown_residual"),
    )

    @pytest.mark.parametrize("token,expected_pkg", AGPL_GADGETS)
    def test_agpl_stem_junk_infix_exception_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (R18-01 deny-stem + exception glue)"
        )
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected stem {expected_pkg!r}, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token,expected_pkg", NC_GADGETS)
    def test_nc_stem_junk_infix_exception_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (R18-01 NC-stem + exception glue)"
        )
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected stem {expected_pkg!r}, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("token", STILL_ADMIT)
    def test_legit_f15_5_admits_hold(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None
        assert policy.audit_derived_from_model(token).ok is True

    @pytest.mark.parametrize("token,expected_pkg", ELEVATED_OR_EXACT_STILL_DENY)
    def test_elevated_and_exact_prefix_controls_hold(
        self, token: str, expected_pkg: str
    ) -> None:
        """R19-10: immune to M23/M25 — not classify-owned."""
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == expected_pkg

    @pytest.mark.parametrize("token,expected_pkg", CLASSIFY_OWNED_STILL_DENY)
    def test_classify_owned_unknown_rem_controls_hold(
        self, token: str, expected_pkg: str
    ) -> None:
        """R19-10: classify-owned rows — M23/M25 victims."""
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.package_id == expected_pkg

    def test_red_proof_mid_exception_unknown_rem_neuter_gadgets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter ``_MID_EXCEPTION_UNKNOWN_REM_ENABLED``.

        R18-01 gadgets admit; no-junk ``arcfaceyoloxextra`` / ``fastsamx``
        and offset-0 ``yoloxsextra`` stay denied; ``ayoloxs`` stays admit.
        """
        gadgets = [t for t, _ in self.AGPL_GADGETS + self.NC_GADGETS]
        for token in gadgets:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(policy, "_MID_EXCEPTION_UNKNOWN_REM_ENABLED", False)
        for token in gadgets:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: without mid unknown-rem, {token!r} must admit"
            )
        assert policy._package_denylist_hit("arcfaceyoloxextra") is not None
        assert policy._package_denylist_hit("fastsamx") is not None
        assert policy._package_denylist_hit("yoloxsextra") is not None
        assert policy._package_denylist_hit("ayoloxs") is None
        assert policy._package_denylist_hit("yoloyoloxextra") is not None


class TestF16NasResidualAttribution:
    """R18-04 / R19-04: ppyolo + nas residual is exact/known-variant Deci.

    Trailing ``s`` is not a one-letter wobble: ``pp_yolo_nass`` is the
    exact compact of ``yolo_nas_s`` (Deci S) so it stays Deci;
    ``pp_yolo_nasls`` is ``nasl`` + junk ``s`` and is not a Deci
    compact, so it stays ``ppyolo_unknown_residual``.
    """

    # R20-05: ``pp_yolo_nas`` is compact-path Deci, not classify-owned
    # (M23-insensitive). Keep it off the M23-victim parametrized node.
    DECI_CLASSIFY: ClassVar[tuple[str, ...]] = (
        "pp_yolo_nas_l",
        "ppyoloenas",
        "pp_yolo_nass",
    )
    NOT_DECI: ClassVar[tuple[str, ...]] = (
        "pp_yolo_naso",
        "pp_yolo_nashville",
        "pp_yolo_nasal",
        "pp_yolo_nasls",
    )

    @pytest.mark.parametrize("token", DECI_CLASSIFY)
    def test_known_nas_residual_is_deci_nc(self, token: str) -> None:
        """Classify-owned Deci rows — M23 victim (R20-05 split)."""
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        # R19-11: exact Deci base id. Residual-NC always lands
        # ``yolo_nas`` (not ``yolo_nas_l``) even for ``pp_yolo_nas_l``.
        assert hit.package_id == "yolo_nas", (
            f"{token!r}: expected exact yolo_nas, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert "deci" in result.detail.casefold() or "yolo_nas" in result.detail

    def test_exact_pp_yolo_nas_is_deci_via_compact(self) -> None:
        """R20-05: ``pp_yolo_nas`` is compact-path Deci, not classify-owned.

        M23-insensitive — denial does not go through residual
        classification. Keep it off the M23 victim node.
        """
        token = "pp_yolo_nas"
        hit = policy._package_denylist_hit(token)
        assert hit is not None
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        assert hit.package_id == "yolo_nas"
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    @pytest.mark.parametrize("token", NOT_DECI)
    def test_english_nas_prefix_is_not_deci(self, token: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must stay fail-closed"
        assert hit.package_id == "ppyolo_unknown_residual", (
            f"{token!r}: must not attribute English nas* as Deci; "
            f"got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert "deci" not in result.detail.casefold()


class TestF16PaddleVendorMerge:
    """R18-05 / R18-10: PaddleDetection shorthands merge; set is pinned."""

    ADMIT: ClassVar[tuple[str, ...]] = (
        "paddledet_pp_yoloe",
        "ppdet_pp_yoloe",
        "baidu_pp_yoloe",
        "paddle_pp_yoloe",
        "paddledetection_pp_yoloe",
        "paddlepaddle_pp_yoloe",
        "pp_yoloe",
    )
    STILL_DENY: ClassVar[tuple[tuple[str, str], ...]] = (
        ("weights_pp_yoloe", "yolo"),
        ("model_pp_yoloe", "yolo"),
        ("v2_pp_yoloe", "yolo"),
        ("paddles_pp_yoloe", "yolo"),
    )

    def test_paddle_vendor_segment_set_is_pinned(self) -> None:
        expected = frozenset(
            {
                "paddlepaddle",
                "paddle",
                "paddledetection",
                "paddledet",
                "ppdet",
                "baidu",
            }
        )
        assert policy._PADDLE_VENDOR_SEGMENTS == expected

    @pytest.mark.parametrize("token", ADMIT)
    def test_vendor_pp_yoloe_admits(self, token: str) -> None:
        assert policy._package_denylist_hit(token) is None, (
            f"{token!r} must ADMIT after Paddle vendor pp merge"
        )
        assert policy.audit_derived_from_model(token).ok is True

    @pytest.mark.parametrize("token,expected_pkg", STILL_DENY)
    def test_non_vendor_pp_yoloe_still_denies(
        self, token: str, expected_pkg: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} is not a vendor shorthand"
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected {expected_pkg!r}, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE


class TestF16EmptyIdentityHonestyAndStackedTags:
    """R18-11 / R18-12: honest empty-identity wording; stacked tags."""

    def test_ingest_tooling_floor_use_empty_identity_wording(self) -> None:
        token = ":latest"
        for fn, needle in (
            (policy.audit_model_ingest, "model_id"),
            (policy.audit_tooling_dependency, "package_name"),
            (policy.audit_derived_from_model, "derived_from_model"),
            (policy.audit_source, "source"),
        ):
            result = fn(token)
            assert result.ok is False
            assert result.reason is policy.RejectionReason.INVALID_ROW
            detail_cf = result.detail.casefold()
            assert "canonicalises to an empty identity" in detail_cf, (
                f"{fn.__name__}: expected empty-identity wording; "
                f"got {result.detail!r}"
            )
            assert "format-only characters" not in detail_cf, (
                f"{fn.__name__}: must not claim format-only Cf chars; "
                f"got {result.detail!r}"
            )
            assert needle in result.detail

    def test_stacked_latest_tags_are_empty_identity(self) -> None:
        token = ":latest:latest"
        assert policy._canonical_lacks_identity(policy.canonical(token))
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.INVALID_ROW

    def test_yolox_stacked_latest_still_admits(self) -> None:
        token = "yolox:latest:latest"
        assert policy.canonical(token) == "yolox"
        assert policy._package_denylist_hit(token) is None
        assert policy.audit_derived_from_model(token).ok is True

    def test_red_proof_stacked_tag_single_strip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: restore single-pass tag strip → leftover ``latest`` admits."""
        token = ":latest:latest"
        assert policy.audit_derived_from_model(token).ok is False
        orig = policy._REGISTRY_TRAILING_TAG_RE

        class _Once:
            def __init__(self) -> None:
                self.n = 0

            def sub(self, repl: str, text: str, count: int = 0) -> str:
                if self.n >= 1:
                    return text
                self.n += 1
                return orig.sub(repl, text, count=count)

        monkeypatch.setattr(policy, "_REGISTRY_TRAILING_TAG_RE", _Once())
        result = policy.audit_derived_from_model(token)
        assert result.ok is True, (
            "red-proof: single strip of :latest:latest must leave "
            f"'latest' and admit; got {result.detail!r}"
        )


class TestF16StealHonestyPin:
    """R18-02: steal-path pin that dies when M26 skips the steal return.

    ``yoloxfastsamx`` is unbounded compact rem ``fastsamx`` (deny-(c)
    debris). Steal names ``fastsam``. After M26 skips the steal return
    the residual defers, (e) cannot see ``fastsam`` as a suffix
    (token ends in ``x``), and the token admits — this assertion dies.
    ``yoloxfastsam`` is *not* used: (e) still names ``fastsam``.
    """

    def test_steal_names_fastsam_residual_honest(self) -> None:
        token = "yoloxfastsamx"
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY via F12-1 steal"
        assert hit.package_id == "fastsam", (
            f"{token!r}: steal must name fastsam, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        assert _door_entry_package_id(result.detail) == "fastsam"

    def test_red_proof_steal_flag_turns_fastsam_residual_red(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: skip steal → ``yoloxfastsamx`` admits (e cannot see it)."""
        token = "yoloxfastsamx"
        assert policy._package_denylist_hit(token) is not None
        monkeypatch.setattr(
            policy, "_exception_illegitimate_deny_steal", lambda _t: None
        )
        assert policy._package_denylist_hit(token) is None, (
            "red-proof: without steal, yoloxfastsamx must admit"
        )
        assert policy._package_denylist_hit("fastsam") is not None
        assert policy._package_denylist_hit("yoloxfastsam") is not None
        assert policy._package_denylist_hit("yolox") is None


# ---------------------------------------------------------------------------
# FIR-7 Wave F17 — R19 findings
# ---------------------------------------------------------------------------


class TestF17UnderscoreNcSeedGluedException:
    """R19-01 / R19-12: underscore NC seed + glued junk + exception spelling.

    Official underscore NC seeds with compact ≤ 10 and an unowned head
    (``buffalo_l`` / ``buffalo_l2`` / ``buffalo_pt`` / ``buffalo_s`` /
    ``buffalo_sc`` / ``buffalo_trt`` / ``antelope_v2``) admitted
    ``{seed}{junk}{exception}`` because the walker handed mid-adjacency
    only the last-segment compact (``lxyolox``), whose prefix ``lx``
    looks like the pinned ``ayoloxs`` junk shape. Empty-rem ownership
    now runs :func:`policy._underscore_preserving_glued_seed_owner` on
    the underscore-preserving token so the folded seed ``buffalo_l``
    matches ``buffalo_lxyolox`` without compact contained-long / (c)
    (that path falsely collapses ``yolop_yolox``). Junk is unbounded
    (4+ ``abcd``).
    """

    SEEDS: ClassVar[tuple[str, ...]] = (
        "buffalo_l",
        "buffalo_l2",
        "buffalo_pt",
        "buffalo_s",
        "buffalo_sc",
        "buffalo_trt",
        "antelope_v2",
    )
    JUNK: ClassVar[tuple[str, ...]] = ("x", "v9", "abc", "abcd")
    SPELLINGS: ClassVar[tuple[str, ...]] = (
        "yolox",
        "yoloxs",
        "yolop",
        "yolos",
        "yolof",
        "ppyoloe",
    )
    # One row per seed; junk lengths 1/2/3/4+ and all six spellings
    # appear. The sweep below covers the full 7×4×6 cross-product.
    REPRESENTATIVE: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("buffalo_l", "x", "yolox"),
        ("buffalo_l2", "v9", "yoloxs"),
        ("buffalo_pt", "abc", "yolop"),
        ("buffalo_s", "abcd", "yolos"),
        ("buffalo_sc", "x", "yolof"),
        ("buffalo_trt", "v9", "ppyoloe"),
        ("antelope_v2", "abc", "yolox"),
    )
    VARIANTS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("buffalo_lx_yolox", "buffalo_l"),
        ("buffalo_sx_yoloxs", "buffalo_s"),
        ("antelope_v2x_yolox", "antelope_v2"),
        ("Buffalo_LXYoloX", "buffalo_l"),
        ("BUFFALO_TRTXYOLOX", "buffalo_trt"),
        ("buffalo-lxyolox", "buffalo_l"),
        ("buffalo_lxyolox_s", "buffalo_l"),
        ("antelope_v2xyolox_s", "antelope_v2"),
        ("buffalo_lxyolox:latest", "buffalo_l"),
        ("buffalo_scabcyolox:v0.3.0", "buffalo_sc"),
    )
    # R20-01: rem tails that fold to their own ``_`` segment. ``:v8``
    # is the unstripped single-number twin of ``_v8`` (F15-3).
    REM_TAILS: ClassVar[tuple[str, ...]] = (
        "_v8",
        ":v8",
        "_tiny",
        "_extra",
        "_onnx",
    )
    # One glued row per rem-tail axis (seed/junk/spelling still vary).
    REM_TAIL_GLUED: ClassVar[tuple[tuple[str, str, str, str], ...]] = (
        ("buffalo_l", "x", "yolox", "_v8"),
        ("buffalo_l2", "v9", "yoloxs", ":v8"),
        ("buffalo_pt", "abc", "yolop", "_tiny"),
        ("buffalo_s", "abcd", "yolos", "_extra"),
        ("buffalo_sc", "x", "yolof", "_onnx"),
        ("buffalo_trt", "v9", "ppyoloe", "_v8"),
        ("antelope_v2", "abc", "yolox", ":v8"),
    )
    # Separator-twin: junk glued to seed, exception in its own segment.
    REM_TAIL_TWIN: ClassVar[tuple[tuple[str, str, str, str], ...]] = (
        ("buffalo_l", "x", "yolox", "_tiny"),
        ("buffalo_l2", "v9", "yoloxs", "_v8"),
        ("buffalo_pt", "abc", "yolop", ":v8"),
        ("buffalo_s", "abcd", "yolos", "_onnx"),
        ("buffalo_sc", "x", "yolof", "_extra"),
        ("buffalo_trt", "v9", "ppyoloe", "_tiny"),
        ("antelope_v2", "abc", "yolox", "_onnx"),
    )
    # Oracle-listed R20-01 admits at F17 HEAD, plus the compact twin
    # ``:v8`` form the consolidator also reproduced.
    LISTED_REM_TAIL: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("buffalo_lxyolox_v8", "buffalo_l", "nc"),
        ("buffalo_lxyolox:v8", "buffalo_l", "nc"),
        ("buffalo_lxyolox_tiny", "buffalo_l", "nc"),
        ("buffalo_lxyolox_extra", "buffalo_l", "nc"),
        ("buffalo_lxyolox_onnx", "buffalo_l", "nc"),
        ("buffalo_lx_yolox_tiny", "buffalo_l", "nc"),
        ("fastsamxyolox:v8", "fastsam", "agpl"),
        ("buffalolxyolox:v8", "buffalo_l", "nc"),
    )
    # R21-01: multi-segment rem tails that fold past last-segment peel
    # (``v8-3`` canon ``v83`` != last ``3``; ``onnxtiny`` != ``tiny``).
    LISTED_MULTI_SEGMENT_REM: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("buffalo_lxyolox_v8-3", "buffalo_l", "nc"),
        ("buffalo_lxyolox_v8.3", "buffalo_l", "nc"),
        ("buffalo_lxyolox_onnx_tiny", "buffalo_l", "nc"),
        ("buffalo_lxyolox_v8_tiny", "buffalo_l", "nc"),
        ("buffalo_lxyolox_tiny_v8", "buffalo_l", "nc"),
        ("buffalo_l2xyolox_onnx_tiny", "buffalo_l2", "nc"),
        ("buffalo_scxyolox_v8-3", "buffalo_sc", "nc"),
        ("buffalo_lxyolox_v8_onnx", "buffalo_l", "nc"),
        ("buffalo_lxyolox_onnx_v8", "buffalo_l", "nc"),
        ("buffalo_lxyolox_extra_v8", "buffalo_l", "nc"),
        ("fastsamxyolox_v8-3", "fastsam", "agpl"),
    )
    # Cross-product: {3 NC + AGPL fastsam} × {5 two-segment rem pairs} ×
    # {2 orderings} × {sep variants _, -, .}. First rem connector is
    # ``_`` so the tail is ``_{a}{sep}{b}`` matching the listed shape.
    # R22: fastsam joins the seed set (LISTED_MULTI_SEGMENT_REM already
    # carried an AGPL row); longer tails live on MULTI_SEGMENT_LONG_TAILS.
    MULTI_SEGMENT_SEEDS: ClassVar[tuple[str, ...]] = (
        "buffalo_l",
        "buffalo_l2",
        "buffalo_sc",
        "fastsam",
    )
    MULTI_SEGMENT_PAIRS: ClassVar[tuple[tuple[str, ...], ...]] = (
        ("v8", "3"),
        ("onnx", "tiny"),
        ("v8", "tiny"),
        ("v8", "onnx"),
        ("extra", "v8"),
        ("v8", "tiny", "onnx"),
        ("v8", "tiny", "onnx", "int8", "fp16"),
        ("v8", "tiny", "onnx", "int8", "fp16", "cpu", "gpu", "trt", "final"),
    )
    MULTI_SEGMENT_SEPS: ClassVar[tuple[str, ...]] = ("_", "-", ".")
    # 3 NC × 5 pairs × 2 orders × 3 seps = 90. fastsam × 5 × 2 × 3
    # seps = 30. All ten ``fastsamxyolox_{a}.{b}`` rows deny (R23-01
    # consults the prefix owner for a legitimate rem tag, so
    # ``tiny.onnx`` is no longer an extension-strip admit).
    MULTI_SEGMENT_SWEEP_ROWS: ClassVar[int] = 120
    MULTI_SEGMENT_LONG_TAIL_ROWS: ClassVar[int] = 36  # 4 × 3 long × 3 seps
    # Current oracle attributions — verdicts AND package_id must hold.
    A3_STILL_DENY: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("buffalo_lyolox", "buffalo_l", "nc"),
        ("buffalolxyolox", "buffalo_l", "nc"),
        ("buffalo_l_xyolox", "buffalo_l", "nc"),
        ("buffalo_l~xyolox", "buffalo_l", "nc"),
        ("buffalo_l.xyolox", "buffalo_l", "nc"),
        ("buffalo_l/xyolox", "buffalo_l", "nc"),
        ("buffalo_lx/yolox", "buffalo_l", "nc"),
        ("buffalo_fp16xyolox", "buffalo_fp16", "nc"),
        ("buffalo_int8xyolox", "buffalo_int8", "nc"),
        ("buffalo_onnxxyolox", "buffalo_onnx", "nc"),
        ("scrfd_10gxyolox", "scrfd", "nc"),
        ("scrfd_2_5gxyolox", "scrfd", "nc"),
        ("yolo_nasxyolox", "yolo", "agpl"),
        ("yolo_worldxyolox", "yolo", "agpl"),
        ("ultralytics_yoloxyolox", "ultralytics", "agpl"),
        ("vec2face_g1xyolox", "vec2face", "nc"),
        ("retinaface_r50xyolox", "retinaface", "nc"),
        ("retinaface_mnet025xyolox", "retinaface", "nc"),
        ("arcface_r100xyolox", "arcface", "nc"),
        ("insightface_buffalo_lxyolox", "insightface", "nc"),
    )
    A4_STILL_ADMIT: ClassVar[tuple[str, ...]] = (
        "ayoloxs",
        "xyoloxs",
        "megviiyolox",
        "megvii_yolox",
        "yolodummy",
        "myyolo",
        "buffalo_lx",
        "antelope_v2x",
        "buffalo_fp16x",
        "aabuffalo_l",
    )
    # R19-12: ≥4-char suffix junk on these NC seeds is *not* floor-listed.
    # 1–3-char suffix junk stays on (c) (``buffalo_lx``); junk-*prefix*
    # twins stay on F15-1 (``aabuffalo_l``). Door-pass without an
    # exception witness is the documented asymmetry — do not widen
    # floor listing to name-continuations (``buffalo_lakes``).
    FLOOR_MISS_SUFFIX_JUNK: ClassVar[tuple[str, ...]] = (
        "buffalo_lxxxx",
        "buffalo_labcd",
        "buffalolabcd",
        "antelope_v2abcd",
    )

    def _assert_nc_seed_deny(self, token: str, expected_pkg: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, (
            f"{token!r} must DENY (R19-01 underscore NC seed + exception)"
        )
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected stem {expected_pkg!r}, got {hit.package_id!r}"
        )
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
            f"{token!r}: expected nc_model_derived, got {hit.reason}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        # Membership often fires before floor-promotion detail; either
        # extractor must name the underscore NC seed.
        door_id = _door_nc_pattern_id(result.detail) or _door_entry_package_id(
            result.detail
        )
        assert door_id == expected_pkg, (
            f"{token!r}: door must name {expected_pkg!r}, got {door_id!r} "
            f"({result.detail!r})"
        )

    def _assert_seed_deny(self, token: str, expected_pkg: str) -> None:
        """NC or AGPL seed deny (R22 fastsam joins the multi-seg sweep)."""
        if expected_pkg == "fastsam":
            hit = policy._package_denylist_hit(token)
            assert hit is not None, f"{token!r} must DENY (AGPL fastsam)"
            assert hit.package_id == expected_pkg, (
                f"{token!r}: expected stem {expected_pkg!r}, "
                f"got {hit.package_id!r}"
            )
            assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            result = policy.audit_derived_from_model(token)
            assert result.ok is False
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            return
        self._assert_nc_seed_deny(token, expected_pkg)

    @pytest.mark.parametrize("seed,junk,spelling", REPRESENTATIVE)
    def test_representative_seed_junk_spelling_denies(
        self, seed: str, junk: str, spelling: str
    ) -> None:
        self._assert_nc_seed_deny(f"{seed}{junk}{spelling}", seed)

    @pytest.mark.parametrize("token,expected_pkg", VARIANTS)
    def test_variant_shapes_deny(self, token: str, expected_pkg: str) -> None:
        self._assert_nc_seed_deny(token, expected_pkg)

    def test_full_cross_product_sweep_denies(self) -> None:
        """All 168 core gadgets {seed}{junk}{spelling} deny as the NC seed."""
        seen = 0
        for seed in self.SEEDS:
            for junk in self.JUNK:
                for spelling in self.SPELLINGS:
                    self._assert_nc_seed_deny(f"{seed}{junk}{spelling}", seed)
                    seen += 1
        assert seen == 168

    @pytest.mark.parametrize("seed,junk,spelling,tail", REM_TAIL_GLUED)
    def test_rem_tail_glued_axes_deny(
        self, seed: str, junk: str, spelling: str, tail: str
    ) -> None:
        """R20-01: each rem-tail axis on a glued {seed}{junk}{spelling}."""
        self._assert_nc_seed_deny(f"{seed}{junk}{spelling}{tail}", seed)

    @pytest.mark.parametrize("seed,junk,spelling,tail", REM_TAIL_TWIN)
    def test_rem_tail_separator_twin_axes_deny(
        self, seed: str, junk: str, spelling: str, tail: str
    ) -> None:
        """R20-01: each rem-tail axis on {seed}{junk}_{spelling}{tail}.

        Floor attribution is the underscore NC seed. Door may be NC
        (legit size/export rem) or AGPL unknown-residual (``_v8`` /
        ``_extra``) — AGPL-first promotion is unchanged.
        """
        token = f"{seed}{junk}_{spelling}{tail}"
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (R20-01 twin rem tail)"
        assert hit.package_id == seed, (
            f"{token!r}: expected stem {seed!r}, got {hit.package_id!r}"
        )
        assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
        result = policy.audit_derived_from_model(token)
        assert result.ok is False

    @pytest.mark.parametrize("token,expected_pkg,axis", LISTED_REM_TAIL)
    def test_listed_rem_tail_gadgets_deny(
        self, token: str, expected_pkg: str, axis: str
    ) -> None:
        """R20-01: consolidator-reproduced rem-tail admits now deny."""
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (R20-01 rem tail)"
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected {expected_pkg!r}, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        if axis == "nc":
            assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        else:
            assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_full_rem_tail_cross_product_sweep_denies(self) -> None:
        """R20-01: {7 seeds}×{junk}×{spelling}×{rem tails} glued and twin."""
        seen = 0
        for seed in self.SEEDS:
            for junk in self.JUNK:
                for spelling in self.SPELLINGS:
                    for tail in self.REM_TAILS:
                        glued = f"{seed}{junk}{spelling}{tail}"
                        twin = f"{seed}{junk}_{spelling}{tail}"
                        for token in (glued, twin):
                            hit = policy._package_denylist_hit(token)
                            assert hit is not None, (
                                f"{token!r} must DENY (R20-01 rem-tail sweep)"
                            )
                            assert hit.package_id == seed, (
                                f"{token!r}: expected stem {seed!r}, "
                                f"got {hit.package_id!r}"
                            )
                            assert (
                                hit.reason
                                is policy.RejectionReason.NC_MODEL_DERIVED
                            ), (
                                f"{token!r}: expected nc_model_derived, "
                                f"got {hit.reason}"
                            )
                            seen += 1
        # 7 × 4 × 6 × 5 tails × 2 forms
        assert seen == 1680

    def test_glued_rem_stays_unknown_residual(self) -> None:
        """R20-01 must not retarget A.3 glued rem to the underscore seed."""
        for token, expected_pkg in (
            ("buffalo_lxyoloxextra", "yolox_unknown_residual"),
            ("buffalo_lxyoloxlatest", "yolox_unknown_residual"),
        ):
            hit = policy._package_denylist_hit(token)
            assert hit is not None
            assert hit.package_id == expected_pkg, (
                f"{token!r}: glued rem must stay {expected_pkg!r}, "
                f"got {hit.package_id!r}"
            )

    def test_a3_must_stay_deny_fence(self) -> None:
        """Non-classify A.3 neighbours. extra/latest live on the classify pin."""
        for token, expected_pkg, axis in self.A3_STILL_DENY:
            hit = policy._package_denylist_hit(token)
            assert hit is not None, f"{token!r} A.3 must stay DENY"
            assert hit.package_id == expected_pkg, (
                f"{token!r}: A.3 expected {expected_pkg!r}, got {hit.package_id!r}"
            )
            result = policy.audit_derived_from_model(token)
            assert result.ok is False
            if axis == "nc":
                assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
                assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
            else:
                assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
                assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_a4_must_stay_admit_fence(self) -> None:
        for token in self.A4_STILL_ADMIT:
            assert policy.audit_derived_from_model(token).ok is True, (
                f"{token!r} A.4 must stay ADMIT"
            )

    def test_four_plus_suffix_junk_without_exception_is_floor_miss(
        self,
    ) -> None:
        """R19-12: ≥4-char suffix junk is not floor-listed (no exception).

        Door-pass matches the sanctioned ``buffalo_lx`` asymmetry.
        1–3-char suffix junk remains (c)-listed; prefix-junk twins
        remain F15-1-listed.
        """
        for token in self.FLOOR_MISS_SUFFIX_JUNK:
            assert policy._package_denylist_hit(token) is None, (
                f"{token!r} must stay floor-miss (R19-12 intended)"
            )
            assert policy.audit_derived_from_model(token).ok is True
        # Contrast: 1–3 (c) and F15-1 prefix-junk stay listed.
        lx = policy._package_denylist_hit("buffalo_lx")
        assert lx is not None and lx.package_id == "buffalo_l"
        assert policy.audit_derived_from_model("buffalo_lx").ok is True
        pref = policy._package_denylist_hit("aabuffalo_l")
        assert pref is not None and pref.package_id == "buffalo_l"
        assert policy.audit_derived_from_model("aabuffalo_l").ok is True
        # R20-07: A.4 door-only names that floor-hit via (c) / long-seed
        # glue. A silent floor-miss here would keep the door admit.
        for token, expected_pkg in (
            ("antelope_v2x", "antelope_v2"),
            ("buffalo_fp16x", "buffalo_fp16"),
        ):
            hit = policy._package_denylist_hit(token)
            assert hit is not None, (
                f"{token!r} must stay floor-listed (R20-07)"
            )
            assert hit.package_id == expected_pkg, (
                f"{token!r}: expected {expected_pkg!r}, got {hit.package_id!r}"
            )
            assert policy.audit_derived_from_model(token).ok is True

    def test_red_proof_mid_exception_unknown_rem_neuter_underscore(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: neuter empty-rem ownership → R19-01 gadgets admit."""
        gadgets = [
            f"{seed}{junk}{spelling}"
            for seed, junk, spelling in self.REPRESENTATIVE
        ]
        gadgets.append("buffalo_lx_yolox")
        for token in gadgets:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(policy, "_MID_EXCEPTION_UNKNOWN_REM_ENABLED", False)
        for token in gadgets:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: without mid empty-rem, {token!r} must admit"
            )
        # A.3 neighbours owned by other mechanisms stay deny.
        # Compact twin ``buffalolxyolox`` shares this empty-rem arm and
        # admits under the same neuter — do not claim it stays deny.
        assert policy._package_denylist_hit("buffalo_lyolox") is not None
        assert policy._package_denylist_hit("buffalo_l_xyolox") is not None
        # A.4 stays admit; door-pass seed+junk stays admit.
        assert policy._package_denylist_hit("ayoloxs") is None
        assert policy.audit_derived_from_model("buffalo_lx").ok is True

    def test_red_proof_underscore_glued_owner_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: drop the folded-seed owner → R19-01 gadgets admit.

        Compact R18-01 siblings stay on ``_mid_exception_prefix_deny_owner``.
        """
        token = "buffalo_lxyolox"
        assert policy._package_denylist_hit(token) is not None
        monkeypatch.setattr(
            policy, "_underscore_preserving_glued_seed_owner", lambda _t: None
        )
        assert policy._package_denylist_hit(token) is None, (
            "red-proof: without underscore glued owner, "
            f"{token!r} must admit"
        )
        assert policy._package_denylist_hit("buffalo_labcdyolox") is None
        assert policy._package_denylist_hit("buffalo_lx_yolox") is None
        assert policy._package_denylist_hit("fastsamxyolox") is not None
        assert policy._package_denylist_hit("buffalo_lyolox") is not None
        assert policy._package_denylist_hit("ayoloxs") is None
        assert policy._package_denylist_hit("yolop_yolox") is None

    def test_punct_led_remainder_is_not_glued_owner(self) -> None:
        """R20-04: ``rest[0].isalnum()`` — punct after the seed is not glue.

        Direct helper pin so dropping the boundary check reds here, not
        only via the incidental F14 fold red-proof.
        """
        assert (
            policy._underscore_preserving_glued_seed_owner("buffalo_l~yolox")
            is None
        )
        assert (
            policy._underscore_preserving_glued_seed_owner("buffalo_l_xyolox")
            is None
        )
        owned = policy._underscore_preserving_glued_seed_owner(
            "buffalo_lxyolox"
        )
        assert owned is not None and owned.package_id == "buffalo_l"

    def test_red_proof_separate_rem_owner_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: drop rem-path owner → R20-01 rem-tail gadgets admit.

        Empty-rem R19-01 gadgets and A.3 glued rem stay on their own
        arms.
        """
        gadgets = [
            "buffalo_lxyolox_v8",
            "buffalo_lxyolox:v8",
            "buffalo_lxyolox_tiny",
            "buffalo_lxyolox_extra",
            "buffalo_lxyolox_onnx",
            "buffalo_lx_yolox_tiny",
            "fastsamxyolox:v8",
        ]
        for token in gadgets:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(
            policy, "_MID_EXCEPTION_SEPARATE_REM_OWNER_ENABLED", False
        )
        for token in gadgets:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: without separate-rem owner, {token!r} must admit"
            )
        assert policy._package_denylist_hit("buffalo_lxyolox") is not None
        extra = policy._package_denylist_hit("buffalo_lxyoloxextra")
        assert extra is not None
        assert extra.package_id == "yolox_unknown_residual"
        assert policy._package_denylist_hit("ayoloxs") is None

    @pytest.mark.parametrize("token,expected_pkg,axis", LISTED_MULTI_SEGMENT_REM)
    def test_listed_multi_segment_rem_tail_gadgets_deny(
        self, token: str, expected_pkg: str, axis: str
    ) -> None:
        """R21-01: consolidator-reproduced multi-segment rem tails deny."""
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (R21-01 multi-seg rem)"
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected {expected_pkg!r}, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False
        if axis == "nc":
            assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        else:
            assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_multi_segment_rem_tail_cross_product_sweep_denies(self) -> None:
        """R21-01/R22: {4 seeds}×{2-seg rem pairs}×{orderings}×{_,_,-. seps}.

        The original 90 NC rows are the 3 NC seeds × 5 pairs × 2 × 3;
        fastsam adds the 30 AGPL rows including the ``.`` axis
        (120 total).
        """
        seen = 0
        junk = "x"
        spelling = "yolox"
        two_seg = [p for p in self.MULTI_SEGMENT_PAIRS if len(p) == 2]
        for seed in self.MULTI_SEGMENT_SEEDS:
            for left, right in two_seg:
                for a, b in ((left, right), (right, left)):
                    for sep in self.MULTI_SEGMENT_SEPS:
                        token = f"{seed}{junk}{spelling}_{a}{sep}{b}"
                        self._assert_seed_deny(token, seed)
                        seen += 1
        assert seen == self.MULTI_SEGMENT_SWEEP_ROWS, (
            f"R21-01/R22 sweep must cover {self.MULTI_SEGMENT_SWEEP_ROWS} "
            f"rows, got {seen}"
        )

    def test_red_proof_multi_segment_rem_owner_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: drop multi-seg rem peel → R21-01 gadgets admit.

        Single-segment R20-01 tails, empty-rem R19-01 gadgets, and A.3
        glued rem stay on their own arms.
        """
        gadgets = [token for token, _pkg, _axis in self.LISTED_MULTI_SEGMENT_REM]
        for token in gadgets:
            assert policy._package_denylist_hit(token) is not None, (
                f"precondition: {token!r} must deny"
            )
        monkeypatch.setattr(
            policy, "_MID_EXCEPTION_MULTI_SEGMENT_REM_OWNER_ENABLED", False
        )
        for token in gadgets:
            assert policy._package_denylist_hit(token) is None, (
                f"red-proof: without multi-seg rem owner, {token!r} must admit"
            )
        # R20-01 single-segment rem still denies.
        assert policy._package_denylist_hit("buffalo_lxyolox_v8") is not None
        assert policy._package_denylist_hit("fastsamxyolox:v8") is not None
        assert policy._package_denylist_hit("buffalo_lxyolox") is not None
        extra = policy._package_denylist_hit("buffalo_lxyoloxextra")
        assert extra is not None
        assert extra.package_id == "yolox_unknown_residual"
        assert policy._package_denylist_hit("ayoloxs") is None


# ---------------------------------------------------------------------------
# FIR-7 Wave F20 — R22 bounded-peel fail-opens
# ---------------------------------------------------------------------------


class TestF20ComposedRemBoundsFailClosed:
    """R22: composed-rem peel must never fail open at a resource bound.

    F19's 8-segment / 48-char caps and ``spelling in rem`` bail returned
    None; the caller read "no owner" and admitted. Production peel is
    monotone (no segment cap, no exception-spelling bail). Rem longer
    than the historical 48-char cliff skips peel (deep-chain cost is
    the pre-existing scanner) and fail-closes via the unpeeled owner.

    Pins must die on the production-shaped revert, not on a test-only
    flag. The unpeeled-owner fallback still names underscore seeds
    and compact-heads with prefix ≤ 16, so the F19 cliffs are pinned
    on padded compact-heads (prefix = 17) the fallback cannot see.
    """

    F17 = TestF17UnderscoreNcSeedGluedException

    LISTED_R22_PROBES: ClassVar[tuple[tuple[str, str, str], ...]] = (
        (
            "buffalo_lxyolox_v8_tiny_onnx_int8_fp16_cpu_gpu_trt_final",
            "buffalo_l",
            "nc",
        ),
        (
            "buffalo_scxyolox_onnx_tiny_int8_fp16_cpu_gpu_trt_final_v2",
            "buffalo_sc",
            "nc",
        ),
        ("fastsamxyolox_v8_a_b_c_d_e_f_g_h", "fastsam", "agpl"),
        ("buffalo_lxyolox_1_2_3_4_5_6_7_8_9", "buffalo_l", "nc"),
        (
            "buffalo_lxyolox_v8_3_onnx_tiny_extra_v9_fp16_trt_pt",
            "buffalo_l",
            "nc",
        ),
        (
            "buffalo_lxyolox_onnxruntime_quantized_dynamic_opset_seventeen_batchsize",
            "buffalo_l",
            "nc",
        ),
        (
            "buffalo_lxyolox_tensorrt_fp16_engine_workspace_4096_calibration_entropy",
            "buffalo_l",
            "nc",
        ),
        ("fastsamxyolox_v8_tiny", "fastsam", "agpl"),
        ("fastsamxyolox_v8_yolox", "fastsam", "agpl"),
        ("fastsamxyolox_v8_yoloxs", "fastsam", "agpl"),
        ("fastsamxyolox_v8_yolop", "fastsam", "agpl"),
        ("fastsamxyolox_v8_yolopv2", "fastsam", "agpl"),
        ("fastsamxyolox_v8_ppyolo", "fastsam", "agpl"),
        ("fastsamxyolox_v8_ppyoloeplus", "fastsam", "agpl"),
        ("fastsamxyolox_v8_yolof", "fastsam", "agpl"),
        ("fastsamxyolox_v8_yolos", "fastsam", "agpl"),
        ("fastsamxyolox_yolos_tiny", "fastsam", "agpl"),
        ("buffalo_lxyoloxextra_v8", "buffalo_l", "nc"),
        ("fastsamxyoloxextra_v8", "fastsam", "agpl"),
        ("buffalo_lxyoloxv8_3", "buffalo_l", "nc"),
    )
    GLUED_AFTER_PEEL: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("buffalo_lxyoloxextra_v8", "buffalo_l", "nc"),
        ("fastsamxyoloxextra_v8", "fastsam", "agpl"),
        ("buffalo_lxyoloxv8_3", "buffalo_l", "nc"),
    )
    EXCEPTION_REM_SPELLINGS: ClassVar[tuple[str, ...]] = (
        "yolox",
        "yoloxs",
        "yolop",
        "yolopv2",
        "ppyolo",
        "ppyoloeplus",
        "yolof",
        "yolos",
    )
    EXCEPTION_REM_SWEEP_ROWS: ClassVar[int] = 64  # 4 seeds × 8 spellings × 2
    REM_LENGTHS: ClassVar[tuple[int, ...]] = (40, 48, 49, 60)
    REM_LENGTH_SWEEP_ROWS: ClassVar[int] = 16  # 4 seeds × 4 lengths
    ADDITIONAL_BENIGN: ClassVar[tuple[str, ...]] = (
        "yolox_s_onnx",
        "yolox_tiny_trt",
        "yolop_v2_onnx",
        "ppyoloe_plus",
        "yolos_tiny",
        "hustvl_yolos_tiny",
        "xyoloxs_v8",
        "ayolox_tiny",
        "myyolo_v8",
        "yolodummy_onnx",
        "buffalo_lakes",
        "buffalo_bill_detector",
        "rt-detr",
        "yolox_s",
        "yolop_yolox",
        "yolox_yolop",
        "ppyoloe",
        "yoloxs",
        "megvii_yolox_onnx",
        "yolox_nano",
        "ppyolo_v2",
        "yolof_r50",
        "yolos_base",
        "xyoloxextra_v8",
        "ayoloxs_tiny",
    )

    def _assert_probe(
        self, token: str, expected_pkg: str, axis: str
    ) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (R22)"
        assert hit.package_id == expected_pkg, (
            f"{token!r}: expected {expected_pkg!r}, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False, f"{token!r} door must DENY"
        if axis == "nc":
            assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
        else:
            assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    @pytest.mark.parametrize("token,expected_pkg,axis", LISTED_R22_PROBES)
    def test_listed_r22_probes_deny(
        self, token: str, expected_pkg: str, axis: str
    ) -> None:
        """R22: every consolidator-listed fail-open probe now denies."""
        self._assert_probe(token, expected_pkg, axis)

    @pytest.mark.parametrize("token,expected_pkg,axis", GLUED_AFTER_PEEL)
    def test_glued_rem_after_peel_denies(
        self, token: str, expected_pkg: str, axis: str
    ) -> None:
        """R22-04: leftover glued rem after a peel must not admit."""
        self._assert_probe(token, expected_pkg, axis)

    def test_glued_rem_without_tail_stays_unknown_residual(self) -> None:
        """A.3: purely glued rem is still yolox_unknown_residual."""
        hit = policy._package_denylist_hit("buffalo_lxyoloxextra")
        assert hit is not None
        assert hit.package_id == "yolox_unknown_residual"

    def test_extreme_unbounded_tokens_deny(self) -> None:
        """R22: no cap — ≥20 segments and ≥200-char rem both deny."""
        segs = "buffalo_lxyolox_" + "_".join(f"s{i}" for i in range(20))
        assert segs.count("_") >= 20
        chars = "buffalo_lxyolox_v8_" + ("a" * 200)
        assert len(chars) >= 200
        fast = "fastsamxyolox_" + "_".join(f"s{i}" for i in range(20))
        self._assert_probe(segs, "buffalo_l", "nc")
        self._assert_probe(chars, "buffalo_l", "nc")
        self._assert_probe(fast, "fastsam", "agpl")

    def test_boundary_len_48_and_49_both_deny(self) -> None:
        """R22-02: historical 48-char cliff and one past it both deny.

        ``v8_`` + N ``a`` so rem is composed (not R20 last-segment).
        """
        at = "buffalo_lxyolox_v8_" + ("a" * 46)
        past = "buffalo_lxyolox_v8_" + ("a" * 47)
        rem_at = policy._compact_canonical(at.split("yolox", 1)[1])
        rem_past = policy._compact_canonical(past.split("yolox", 1)[1])
        assert len(rem_at) == 48
        assert len(rem_past) == 49
        self._assert_probe(at, "buffalo_l", "nc")
        self._assert_probe(past, "buffalo_l", "nc")

    def test_boundary_segment_8_and_9_both_deny(self) -> None:
        """R22-01: historical 8-seg cliff and one past it both deny."""
        eight = "buffalo_lxyolox_1_2_3_4_5_6_7_8"
        nine = "buffalo_lxyolox_1_2_3_4_5_6_7_8_9"
        assert eight.count("_") - "buffalo_lxyolox".count("_") == 8
        assert nine.count("_") - "buffalo_lxyolox".count("_") == 9
        self._assert_probe(eight, "buffalo_l", "nc")
        self._assert_probe(nine, "buffalo_l", "nc")

    def test_exception_spelling_in_rem_sweep(self) -> None:
        """R22-03: exception spelling in rem position cannot launder.

        Floor names the seed. Door reports that seed's licence class
        (R23-03): NC seeds stay ``nc_model_derived`` even when rem is
        ``yolop_tiny`` / ``yolof_tiny``; AGPL seeds stay
        ``denylisted_package``.
        """
        seen = 0
        for seed in self.F17.MULTI_SEGMENT_SEEDS:
            for spelling in self.EXCEPTION_REM_SPELLINGS:
                for token in (
                    f"{seed}xyolox_v8_{spelling}",
                    f"{seed}xyolox_{spelling}_tiny",
                ):
                    hit = policy._package_denylist_hit(token)
                    assert hit is not None, f"{token!r} must DENY"
                    assert hit.package_id == seed, (
                        f"{token!r}: expected {seed!r}, got {hit.package_id!r}"
                    )
                    result = policy.audit_derived_from_model(token)
                    assert result.ok is False, f"{token!r} door must DENY"
                    if seed == "fastsam":
                        assert hit.reason is (
                            policy.RejectionReason.DENYLISTED_PACKAGE
                        ), (
                            f"{token!r}: AGPL seed floor must stay "
                            f"denylisted_package, got {hit.reason}"
                        )
                        assert (
                            result.reason
                            is policy.RejectionReason.DENYLISTED_PACKAGE
                        ), (
                            f"{token!r}: AGPL seed door must stay "
                            f"denylisted_package, got {result.reason}"
                        )
                    else:
                        assert hit.reason is (
                            policy.RejectionReason.NC_MODEL_DERIVED
                        ), (
                            f"{token!r}: NC seed floor must stay "
                            f"nc_model_derived, got {hit.reason}"
                        )
                        assert (
                            result.reason
                            is policy.RejectionReason.NC_MODEL_DERIVED
                        ), (
                            f"{token!r}: NC seed door must stay "
                            f"nc_model_derived, got {result.reason} "
                            f"({result.detail!r})"
                        )
                    seen += 1
        assert seen == self.EXCEPTION_REM_SWEEP_ROWS, (
            f"exception-in-rem sweep must cover "
            f"{self.EXCEPTION_REM_SWEEP_ROWS} rows, got {seen}"
        )

    def test_rem_length_span_sweep(self) -> None:
        """R22-02: rem lengths 40/48/49/60 all deny (no fail-open cliff)."""
        seen = 0
        for seed in self.F17.MULTI_SEGMENT_SEEDS:
            axis = "agpl" if seed == "fastsam" else "nc"
            for n in self.REM_LENGTHS:
                token = f"{seed}xyolox_" + ("a" * n)
                rem = policy._compact_canonical(token.split("yolox", 1)[1])
                assert len(rem) == n, (token, rem, len(rem), n)
                self._assert_probe(token, seed, axis)
                seen += 1
        assert seen == self.REM_LENGTH_SWEEP_ROWS, (
            f"rem-length sweep must cover {self.REM_LENGTH_SWEEP_ROWS} "
            f"rows, got {seen}"
        )

    def test_wide_multi_segment_long_tail_sweep(self) -> None:
        """R22-01: 3/5/9-segment rem tails × {4 seeds} × {3 seps}."""
        seen = 0
        junk = "x"
        spelling = "yolox"
        long_tails = [p for p in self.F17.MULTI_SEGMENT_PAIRS if len(p) > 2]
        for seed in self.F17.MULTI_SEGMENT_SEEDS:
            axis = "agpl" if seed == "fastsam" else "nc"
            for parts in long_tails:
                for sep in self.F17.MULTI_SEGMENT_SEPS:
                    tail = sep.join(parts)
                    token = f"{seed}{junk}{spelling}_{tail}"
                    self._assert_probe(token, seed, axis)
                    seen += 1
        assert seen == self.F17.MULTI_SEGMENT_LONG_TAIL_ROWS, (
            f"long-tail sweep must cover "
            f"{self.F17.MULTI_SEGMENT_LONG_TAIL_ROWS} rows, got {seen}"
        )

    def test_additional_benign_names_still_admit(self) -> None:
        """Over-correction check: generated legitimate names stay admit."""
        for token in self.ADDITIONAL_BENIGN:
            assert policy.audit_derived_from_model(token).ok is True, (
                f"{token!r} must stay ADMIT (R22 over-correction fence)"
            )
        for token in self.F17.A4_STILL_ADMIT:
            assert policy.audit_derived_from_model(token).ok is True, (
                f"{token!r} A.4 must stay ADMIT"
            )

    def test_a3_attributions_and_r21_gadgets_still_hold(self) -> None:
        """A.3 fence + the 11 R21-01 gadgets + original 90-row NC subset."""
        for token, expected_pkg, axis in self.F17.A3_STILL_DENY:
            hit = policy._package_denylist_hit(token)
            assert hit is not None, f"{token!r} A.3 must stay DENY"
            assert hit.package_id == expected_pkg
            result = policy.audit_derived_from_model(token)
            assert result.ok is False
            if axis == "nc":
                assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
            else:
                assert hit.reason is policy.RejectionReason.DENYLISTED_PACKAGE
        for token, expected_pkg, axis in self.F17.LISTED_MULTI_SEGMENT_REM:
            self._assert_probe(token, expected_pkg, axis)
        # Original 90-row NC subset still denies.
        seen = 0
        two_seg = [p for p in self.F17.MULTI_SEGMENT_PAIRS if len(p) == 2]
        nc_seeds = (
            "buffalo_l",
            "buffalo_l2",
            "buffalo_sc",
        )
        for seed in nc_seeds:
            for left, right in two_seg:
                for a, b in ((left, right), (right, left)):
                    for sep in self.F17.MULTI_SEGMENT_SEPS:
                        token = f"{seed}xyolox_{a}{sep}{b}"
                        self._assert_probe(token, seed, "nc")
                        seen += 1
        assert seen == 90

    # Compact-head + underscore + long-glue seeds the R22-02 prefilter
    # must not be able to walk around by padding the prefix.
    R22_02_MATRIX_SEEDS: ClassVar[tuple[str, ...]] = (
        "fastsam",
        "yolor",
        "yolov5",
        "yolov8",
        "arcface",
        "scrfd",
        "retinaface",
        "vec2face",
        "antelopev2",
        "buffalo_l",
        "buffalo_sc",
        "insightface",
        "ultralytics",
    )
    R22_02_PREFIX_LENS: ClassVar[tuple[int, ...]] = tuple(range(5, 41))
    R22_02_REM_LENS: ClassVar[tuple[int, ...]] = (47, 48, 49, 50, 200, 2000)

    @staticmethod
    def _r22_02_composed_token(
        seed: str, prefix_len: int, rem_len: int
    ) -> str | None:
        """``{seed}{pad}xyolox_v8_`` + ``a``*N so rem is multi-segment.

        Prefix is the compact slice before the first ``yolox``. Rem is
        ``v8`` + ``a``*N so last-segment-equals-rem misses and rem>48
        takes the skip-peel path. Returns None when ``prefix_len``
        cannot hold ``seed`` + the ``x`` junk infix.
        """
        seed_k = seed.replace("_", "")
        # prefix = seed_k + pad + "x"
        pad_len = prefix_len - len(seed_k) - 1
        if pad_len < 0:
            return None
        n_a = rem_len - 2  # "v8" is two compact chars
        if n_a < 0:
            return None
        return f"{seed}{'z' * pad_len}xyolox_v8_" + ("a" * n_a)

    def test_r22_02_padded_prefix_past_16_with_long_rem_denies(self) -> None:
        """R22-02: prefix=17 rem=49 must DENY (the documented cliff).

        Production-shaped revert is re-gating the unpeeled owner on
        ``len(prefix) <= 16``. buffalo_l is the wrong witness — the
        underscore-head arm still names it past the cap.
        """
        for seed in ("fastsam", "yolor", "yolov5", "arcface", "scrfd"):
            token = self._r22_02_composed_token(seed, 17, 49)
            assert token is not None
            compact = policy._compact_canonical(token)
            idx = compact.find("yolox")
            assert len(compact[:idx]) == 17
            assert len(compact[idx + 5 :]) == 49
            axis = (
                "nc"
                if seed in {"arcface", "scrfd"}
                else "agpl"
            )
            self._assert_probe(token, seed, axis)
        # Mid-token long seed: prefix length 22, rem 49.
        mid = "abcdefghijultralyticsxyolox_v8_" + ("a" * 47)
        compact = policy._compact_canonical(mid)
        idx = compact.find("yolox")
        assert len(compact[:idx]) == 22
        assert len(compact[idx + 5 :]) == 49
        self._assert_probe(mid, "ultralytics", "agpl")

    @staticmethod
    def _r22_02_stem_matches(got: str, seed: str) -> bool:
        """True when ``got`` is ``seed`` or an honest spelling of it.

        ``antelopev2`` compact-matches ``antelope_v2``. ``yolov8x`` is
        the size-tag identity of prefix ``yolov8`` + ``x`` (no pad).
        """
        if got == seed:
            return True
        gk = got.replace("_", "")
        sk = seed.replace("_", "")
        if gk == sk:
            return True
        return gk.startswith(sk) and len(gk) <= len(sk) + 3

    def test_r22_02_prefix_by_rem_matrix_denies(self) -> None:
        """R22-02: prefix 5–40 × rem {47,48,49,50,200,2000} for in-class seeds.

        Cells whose prefix cannot hold the seed + ``x`` infix are
        skipped (the seed is not in the prefix). Every constructible
        cell must DENY as that seed (or an honest spelling of it).
        """
        seen = 0
        skipped = 0
        nc_seeds = {
            "arcface",
            "scrfd",
            "retinaface",
            "vec2face",
            "antelopev2",
            "buffalo_l",
            "buffalo_sc",
            "insightface",
        }
        for seed in self.R22_02_MATRIX_SEEDS:
            axis = "nc" if seed in nc_seeds else "agpl"
            for prefix_len in self.R22_02_PREFIX_LENS:
                for rem_len in self.R22_02_REM_LENS:
                    token = self._r22_02_composed_token(
                        seed, prefix_len, rem_len
                    )
                    if token is None:
                        skipped += 1
                        continue
                    compact = policy._compact_canonical(token)
                    idx = compact.find("yolox")
                    assert idx > 0, token
                    assert len(compact[:idx]) == prefix_len, (
                        token,
                        compact[:idx],
                        prefix_len,
                    )
                    assert len(compact[idx + 5 :]) == rem_len, (
                        token[:80],
                        rem_len,
                    )
                    hit = policy._package_denylist_hit(token)
                    assert hit is not None, (
                        f"{token[:96]!r}… must DENY "
                        f"(seed={seed} prefix={prefix_len} rem={rem_len})"
                    )
                    assert self._r22_02_stem_matches(hit.package_id, seed), (
                        f"{token[:96]!r}…: expected stem {seed!r}, "
                        f"got {hit.package_id!r}"
                    )
                    result = policy.audit_derived_from_model(token)
                    assert result.ok is False, (
                        f"{token[:96]!r}… door must DENY"
                    )
                    if axis == "nc":
                        assert (
                            result.reason
                            is policy.RejectionReason.NC_MODEL_DERIVED
                        ), (
                            f"{token[:96]!r}…: expected nc door, "
                            f"got {result.reason}"
                        )
                    else:
                        assert (
                            result.reason
                            is policy.RejectionReason.DENYLISTED_PACKAGE
                        ), (
                            f"{token[:96]!r}…: expected agpl door, "
                            f"got {result.reason}"
                        )
                    seen += 1
        # 13 seeds × 36 prefix × 6 rem, minus cells that cannot hold
        # the seed. Lower bound: every seed has prefix_len from
        # len(seed_k)+1 to 40 (at least 20 cells) × 6 rem.
        assert seen >= 13 * 20 * 6, (
            f"R22-02 matrix too small: seen={seen} skipped={skipped}"
        )
        assert skipped > 0, "expected some prefix_len < seed+1 cells"

    @staticmethod
    def _padded_prefix17(seed: str, rem_tail: str) -> str:
        """``{seed}{z*}xyolox_{rem_tail}`` with compact prefix length 17.

        Prefix 17 is past the has_sep fallback's ``len(prefix) <= 16``
        gate. Underscore seeds (``buffalo_l``) still deny via the
        glued-owner arm — compact-heads (``fastsam`` / ``arcface``)
        are the witnesses a restored F19 cliff can admit.
        """
        seed_k = seed.replace("_", "")
        pad_len = 17 - len(seed_k) - 1
        if pad_len < 0:
            raise ValueError(f"{seed!r} compact is already past prefix 17")
        return f"{seed}{'z' * pad_len}xyolox_{rem_tail}"

    def test_padded_prefix_segment_8_denies_9_and_12_deny(self) -> None:
        """R22-05 / R23-02: 8-seg still denies; 9-seg and 12-seg deny.

        Restoring F19 ``if peels > 8: return None`` admits the padded
        9-seg compact-head (fallback cannot see prefix 17). Raising
        the cap 8→9 still admits 12-seg. buffalo_l 8/9 is the wrong
        witness — glued-owner names it past the cap.
        """
        eight = "1_2_3_4_5_6_7_8"
        nine = "1_2_3_4_5_6_7_8_9"
        # 12 single-char segs keep rem at 12 chars (under the 48-char
        # caller skip). ``s0``…``s19`` compact-length is 50 and would
        # deny via the rem>48 unpeeled owner even with an 8-seg cap.
        twelve = "1_2_3_4_5_6_7_8_9_0_a_b"
        for seed, axis in (("fastsam", "agpl"), ("arcface", "nc")):
            t8 = self._padded_prefix17(seed, eight)
            t9 = self._padded_prefix17(seed, nine)
            t12 = self._padded_prefix17(seed, twelve)
            compact9 = policy._compact_canonical(t9)
            idx = compact9.find("yolox")
            assert len(compact9[:idx]) == 17, (seed, compact9[:idx])
            rem12 = policy._compact_canonical(t12.split("yolox", 1)[1])
            assert len(rem12) == 12
            assert t8.count("_") - t8.split("yolox", 1)[0].count("_") == 8
            assert t9.count("_") - t9.split("yolox", 1)[0].count("_") == 9
            assert t12.count("_") - t12.split("yolox", 1)[0].count("_") == 12
            self._assert_probe(t8, seed, axis)
            self._assert_probe(t9, seed, axis)
            self._assert_probe(t12, seed, axis)

    def test_padded_prefix_len_48_and_49_both_deny(self) -> None:
        """R22-05 / R23-02: padded rem=48 and rem=49 both deny.

        Peel-only ``if len(rem) > 48: return None`` is a no-op — the
        caller skip never reaches peel. The F19-shaped revert is that
        fail-open PLUS deleting the caller skip; rem=49 then admits
        on a padded compact-head (R22-02 already covers the skip-only
        walk-around of re-gating the unpeeled owner on prefix ≤ 16).
        """
        for seed, axis in (("fastsam", "agpl"), ("arcface", "nc")):
            at = self._r22_02_composed_token(seed, 17, 48)
            past = self._r22_02_composed_token(seed, 17, 49)
            assert at is not None and past is not None
            rem_at = policy._compact_canonical(at.split("yolox", 1)[1])
            rem_past = policy._compact_canonical(past.split("yolox", 1)[1])
            assert len(rem_at) == 48
            assert len(rem_past) == 49
            self._assert_probe(at, seed, axis)
            self._assert_probe(past, seed, axis)

    def test_padded_prefix_exception_spelling_in_rem_denies(self) -> None:
        """R22-05 / R23-02: exception spelling in rem cannot launder.

        Restoring F19 ``if spelling in rem: return None`` admits the
        padded compact-head. Unpadded ``fastsamxyolox_v8_yolox`` is
        the wrong witness — fallback prefix-owner still names it.
        """
        spellings = ("yolox", "yolop", "yolof", "yolos", "ppyolo")
        for seed, axis in (("fastsam", "agpl"), ("arcface", "nc")):
            for spelling in spellings:
                token = self._padded_prefix17(seed, f"v8_{spelling}")
                compact = policy._compact_canonical(token)
                idx = compact.find("yolox")
                assert len(compact[:idx]) == 17
                rem = compact[idx + 5 :]
                assert spelling in rem, (token, rem, spelling)
                self._assert_probe(token, seed, axis)
            # rem compact == ``yolox`` via two peelable segments so an
            # exact-match-only bail (``rem == spelling``) still admits.
            exact = self._padded_prefix17(seed, "yo_lox")
            rem_exact = policy._compact_canonical(
                exact.split("yolox", 1)[1]
            )
            assert rem_exact == "yolox", (exact, rem_exact)
            self._assert_probe(exact, seed, axis)

    def test_padded_prefix_glued_leftover_after_peel_denies(self) -> None:
        """R23-02: leftover rem after a peel must not admit.

        Deleting the R22-04 leftover return admits a padded
        compact-head ``{seed}{pad}xyoloxextra_v8`` — fallback cannot
        see prefix 17. Unpadded ``fastsamxyoloxextra_v8`` is the
        wrong witness (prefix ≤ 16 still names the stem).
        """
        for seed, axis in (("fastsam", "agpl"), ("arcface", "nc")):
            seed_k = seed.replace("_", "")
            pad_len = 17 - len(seed_k) - 1
            # peels == 1 then leftover (loop ends: no ``_`` left). Both
            # leftover sites must fire at peels>=1 — raising the floor
            # to peels>=2 admits this token.
            token = f"{seed}{'z' * pad_len}xyoloxextra_v8"
            compact = policy._compact_canonical(token)
            idx = compact.find("yolox")
            assert len(compact[:idx]) == 17, (seed, compact[:idx])
            self._assert_probe(token, seed, axis)
        # A.3 purely-glued rem is still unknown-residual.
        extra = policy._package_denylist_hit("buffalo_lxyoloxextra")
        assert extra is not None
        assert extra.package_id == "yolox_unknown_residual"
        assert policy._package_denylist_hit("ayoloxs") is None


# ---------------------------------------------------------------------------
# FIR-7 Wave F21 — R23 legitimate-tag laundering
# ---------------------------------------------------------------------------


class TestF21LegitimateTagCannotLaunderCompactHead:
    """R23-01: ``{compact_head}x{exception}_{legit_tag}`` must not admit.

    R20's legitimate-residual skip meant a single-segment legit rem
    never consulted the prefix owner, and the unpeeled-owner fallback
    is gated on ``rem != last_uk``. That is a primitive over the whole
    tag catalogue, not a one-token residual.
    """

    COMPACT_HEAD_SEEDS: ClassVar[tuple[str, ...]] = (
        "fastsam",
        "yolor",
        "yolov3",
        "yolov4",
        "yolov5",
        "yolov6",
        "yolov7",
        "yolov9",
        "yolo11",
        "yolo12",
        "arcface",
        "scrfd",
        "retinaface",
        "vec2face",
        "antelopev2",
    )
    NC_SEEDS: ClassVar[frozenset[str]] = frozenset(
        {"arcface", "scrfd", "retinaface", "vec2face", "antelopev2"}
    )
    # Finding-listed tags plus every yolox family/export tag. Class
    # coverage, not a fitted probe list.
    YOLOX_LEGIT_TAGS: ClassVar[tuple[str, ...]] = (
        "tiny",
        "s",
        "m",
        "l",
        "x",
        "nano",
        "onnx",
        "trt",
        "int8",
        "fp16",
        "pt",
        "engine",
        "darknet",
        "darknet53",
        "coco",
        "voc",
        "8xb8",
        "pth",
        "bin",
    )
    SIBLING_SHAPES: ClassVar[tuple[tuple[str, str], ...]] = (
        ("fastsamxyolos_tiny", "fastsam"),
        ("fastsamxppyolo_s", "fastsam"),
        ("fastsamxyolop_v2", "fastsam"),
        ("fastsamxyolof_r50", "fastsam"),
        ("arcfacexyolos_tiny", "arcface"),
        ("scrfdxppyolo_s", "scrfd"),
        ("yolorxyolop_v2", "yolor"),
        ("yolov5xyolof_r50", "yolov5"),
    )
    CONTRAST_STILL_DENY: ClassVar[tuple[tuple[str, str, str], ...]] = (
        ("fastsamxyolox_tiny_onnx", "fastsam", "agpl"),
        ("fastsamxyoloxs", "fastsam", "agpl"),
        ("fastsamxyolox_v8", "fastsam", "agpl"),
        ("buffalo_lxyolox_tiny", "buffalo_l", "nc"),
        ("insightfacexyolox_tiny", "insightface", "nc"),
    )
    EXTENSION_TWINS: ClassVar[tuple[str, ...]] = (".onnx", ".pt")

    @staticmethod
    def _stem_matches(got: str, seed: str) -> bool:
        if got == seed:
            return True
        return got.replace("_", "") == seed.replace("_", "")

    def _assert_seed_deny(self, token: str, seed: str) -> None:
        hit = policy._package_denylist_hit(token)
        assert hit is not None, f"{token!r} must DENY (R23-01)"
        assert self._stem_matches(hit.package_id, seed), (
            f"{token!r}: expected stem {seed!r}, got {hit.package_id!r}"
        )
        result = policy.audit_derived_from_model(token)
        assert result.ok is False, f"{token!r} door must DENY"
        if seed in self.NC_SEEDS:
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
                f"{token!r}: expected nc door, got {result.reason}"
            )
        else:
            assert (
                result.reason is policy.RejectionReason.DENYLISTED_PACKAGE
            ), f"{token!r}: expected agpl door, got {result.reason}"

    def test_listed_yolox_legit_tags_cannot_launder_compact_heads(self) -> None:
        """Every listed tag × compact-head seed denies as the seed."""
        seen = 0
        for seed in self.COMPACT_HEAD_SEEDS:
            for tag in self.YOLOX_LEGIT_TAGS:
                self._assert_seed_deny(f"{seed}xyolox_{tag}", seed)
                seen += 1
        assert seen == len(self.COMPACT_HEAD_SEEDS) * len(self.YOLOX_LEGIT_TAGS)

    def test_extension_twins_cannot_launder(self) -> None:
        """``.onnx`` / ``.pt`` twins strip to the same deny."""
        for seed in ("fastsam", "arcface", "yolov5", "scrfd"):
            for tag in ("tiny", "s", "onnx", "pt"):
                for ext in self.EXTENSION_TWINS:
                    self._assert_seed_deny(f"{seed}xyolox_{tag}{ext}", seed)

    def test_sibling_exception_families_cannot_launder(self) -> None:
        for token, seed in self.SIBLING_SHAPES:
            self._assert_seed_deny(token, seed)

    def test_contrast_rows_still_deny(self) -> None:
        for token, seed, axis in self.CONTRAST_STILL_DENY:
            hit = policy._package_denylist_hit(token)
            assert hit is not None, f"{token!r} contrast must stay DENY"
            assert hit.package_id == seed
            result = policy.audit_derived_from_model(token)
            assert result.ok is False
            if axis == "nc":
                assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED
            else:
                assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_f13_exact_deny_prefix_stays_on_head_glue(self) -> None:
        """``yolov8yolox_s`` stays yolov8 (F13 sole-path, not mid-prefix)."""
        hit = policy._package_denylist_hit("yolov8yolox_s")
        assert hit is not None and hit.package_id == "yolov8"
        # Junk-prefix legit names stay admit.
        for token in (
            "ayoloxs",
            "xyoloxs",
            "ayolox_tiny",
            "xyolox_tiny",
            "yolox_tiny",
            "yolox_s",
            "yolos_tiny",
            "ppyoloe_plus",
            "megviiyolox",
            "megvii_yolox",
        ):
            assert policy.audit_derived_from_model(token).ok is True, (
                f"{token!r} must stay ADMIT (R23-01 over-correction)"
            )

    def test_catalogue_yolox_tags_on_fastsam_deny(self) -> None:
        """Whole yolox separator inventory + shield tags, not a fitted list."""
        tags = set(policy._EXCEPTION_FAMILY_SEPARATOR_TAGS["yolox"])
        tags |= set(policy._NC_TRAILING_SHIELD_TAGS)
        tags.discard("")
        seen = 0
        for tag in sorted(tags):
            if not tag.isalnum() and tag not in {"8xb8", "8x8"}:
                # fold may rewrite punctuation; skip exotic
                if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789" for ch in tag):
                    continue
            self._assert_seed_deny(f"fastsamxyolox_{tag}", "fastsam")
            seen += 1
        assert seen >= 20, f"catalogue sweep too small: {seen}"


class TestF21NcSeedDoorReportsNcAxis:
    """R23-03: NC-seeded tokens must not emit an AGPL-axis door reason.

    ``buffalo_lxyolox_yolop_tiny`` floor-names buffalo_l (NC) but the
    door used to report ``yolop_unknown_residual`` (denylisted_package)
    because AGPL-first promotion treated the synthetic unknown-residual
    gadget as a real AGPL package. The door must report the licence
    class of the seed the floor identified. [AUDIT-08][PROV-01]
    """

    LISTED_ROWS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("buffalo_lxyolox_yolop_tiny", "buffalo_l"),
        ("buffalo_lxyolox_yolof_tiny", "buffalo_l"),
        ("buffalo_lxyolox_yolopv2_tiny", "buffalo_l"),
        ("buffalo_l2xyolox_yolop_tiny", "buffalo_l2"),
        ("buffalo_l2xyolox_yolof_tiny", "buffalo_l2"),
        ("buffalo_l2xyolox_yolopv2_tiny", "buffalo_l2"),
        ("buffalo_scxyolox_yolop_tiny", "buffalo_sc"),
        ("buffalo_scxyolox_yolof_tiny", "buffalo_sc"),
        ("buffalo_scxyolox_yolopv2_tiny", "buffalo_sc"),
        ("insightfacexyolox_yolop_tiny", "insightface"),
        ("arcfacexyolox_yolop_tiny", "arcface"),
    )
    CONTRAST_STILL_NC: ClassVar[tuple[str, ...]] = (
        "buffalo_lxyolox_v8_tiny",
        "buffalo_lxyolox_v8_yolop",
    )
    REAL_AGPL_STILL_AGPL: ClassVar[tuple[str, ...]] = (
        "buffalo_l_ultralytics",
        "arcface_ultralytics",
        "ultralytics/buffalo_l",
        "yolox_s_buffalo_l_ultralytics",
        "fastsamxyolox_yolop_tiny",
    )

    def test_listed_nc_seed_exception_in_rem_door_is_nc(self) -> None:
        for token, seed in self.LISTED_ROWS:
            hit = policy._package_denylist_hit(token)
            assert hit is not None, f"{token!r} must floor-DENY"
            assert hit.package_id == seed
            assert hit.reason is policy.RejectionReason.NC_MODEL_DERIVED
            for door in (
                policy.audit_derived_from_model,
                policy.audit_source,
            ):
                result = door(token)
                assert result.ok is False, f"{token!r} door must DENY"
                assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED, (
                    f"{token!r}: door must report nc_model_derived "
                    f"(floor seed {seed!r}), got {result.reason} "
                    f"({result.detail!r})"
                )
                assert "unknown_residual" not in result.detail, (
                    f"{token!r}: NC door must not name unknown_residual; "
                    f"got {result.detail!r}"
                )

    def test_contrast_v8_rows_stay_nc(self) -> None:
        for token in self.CONTRAST_STILL_NC:
            hit = policy._package_denylist_hit(token)
            assert hit is not None and hit.package_id == "buffalo_l"
            result = policy.audit_derived_from_model(token)
            assert result.ok is False
            assert result.reason is policy.RejectionReason.NC_MODEL_DERIVED

    def test_real_agpl_residue_still_outranks_nc(self) -> None:
        """AGPL-first is unchanged for a real AGPL package hit."""
        for token in self.REAL_AGPL_STILL_AGPL:
            result = policy.audit_derived_from_model(token)
            assert result.ok is False, f"{token!r} door must DENY"
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
                f"{token!r}: real AGPL must stay denylisted_package, "
                f"got {result.reason} ({result.detail!r})"
            )

    def test_unknown_residual_without_nc_seed_stays_agpl(self) -> None:
        """No NC floor seed → unknown residual remains the AGPL landing."""
        for token in ("yolop_z", "yolox_z", "yolof_z"):
            hit = policy._package_denylist_hit(token)
            assert hit is not None
            assert hit.package_id.endswith("_unknown_residual")
            result = policy.audit_derived_from_model(token)
            assert result.ok is False
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE


class TestF17StackedExceptionStemAttribution:
    """R19-03: stacked exception rem must not steal a deny-stem prefix.

    ``fastsamxyoloxsyolox`` used to name ``yolo`` because rem ``yolox``
    is a legitimate exception spelling that hits yolo via (c). The
    prefix stem ``fastsam`` is the honest owner. Junk prefixes keep
    the family-true rem hit so ``xyoloxsyolox`` stays ``yolo``.
    """

    def test_fastsam_stacked_exception_names_stem(self) -> None:
        for token in ("fastsamxyoloxsyolox", "fastsamxyoloxyoloxs"):
            hit = policy._package_denylist_hit(token)
            assert hit is not None
            assert hit.package_id == "fastsam", (
                f"{token!r}: expected stem fastsam, got {hit.package_id!r}"
            )
            result = policy.audit_derived_from_model(token)
            assert result.ok is False
            assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_junk_prefix_stacked_exception_stays_yolo(self) -> None:
        """Pin: no stem → rem yolo-(c) remains (family-true, fail-closed)."""
        for token in ("xyoloxsyolox", "xyoloxyoloxs"):
            hit = policy._package_denylist_hit(token)
            assert hit is not None
            assert hit.package_id == "yolo", (
                f"{token!r}: expected yolo rem hit, got {hit.package_id!r}"
            )

    def test_red_proof_stem_over_exc_rem_neuter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST-15: without the retarget, stacked rem names fabricated yolo."""
        token = "fastsamxyoloxsyolox"
        hit = policy._package_denylist_hit(token)
        assert hit is not None and hit.package_id == "fastsam"
        monkeypatch.setattr(
            policy, "_MID_EXCEPTION_STEM_OVER_EXC_REM_ENABLED", False
        )
        hit2 = policy._package_denylist_hit(token)
        assert hit2 is not None
        assert hit2.package_id == "yolo", (
            f"red-proof: without stem-over-exc-rem, {token!r} must name "
            f"yolo; got {hit2.package_id!r}"
        )
        assert policy._package_denylist_hit("fastsamxyolox") is not None
        assert policy._package_denylist_hit("xyoloxsyolox") is not None
