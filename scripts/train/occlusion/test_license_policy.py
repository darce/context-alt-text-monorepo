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
        # path is the synthetic door's pending default.
        row = {
            "source": "vec2face-successor",
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
        assert via_row.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE
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
            "vec2face-successor",
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

    Floor order (see ``_common_provenance_checks`` docstring):
      derived taint → source taint → clearance_decision → registration → licence
    TOOLING additionally places the package denylist before licence (GATE-05).
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
    """GATE-20: pin each adjacent pair in the documented floor order.

    Documented order (``_common_provenance_checks`` / BR-72):
      derived taint → source taint → clearance_decision → registration → licence

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

    def test_clearance_outranks_registration(self) -> None:
        # Pair 3: uncleared synthetic source + unregistered derived → clearance
        # wins (clearance runs before registration on the floor).
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
        # Pair 4: unregistered derived + denylisted licence → registration wins.
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
    """

    # Measured escape witnesses (must FAIL).
    W1_TOOLING_SHADOW: ClassVar[dict[str, str]] = {
        "package": "numba",
        "package_name": "ultralytics",
        "license": "BSD-2-Clause",
        "derived_from_model": "",
    }
    W2_MODEL_ID_WINS: ClassVar[dict[str, str]] = {
        "model_id": "yunet",
        "package": "ultralytics",
        "license": "MIT",
        "derived_from_model": "",
    }
    W3_TRAINING_PACKAGE: ClassVar[dict[str, str]] = {
        "source": "self-generated",
        "package": "ultralytics",
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
                "package",
                "ultralytics",
            ),
            (
                W3_TRAINING_PACKAGE,
                policy.PolicyCategory.TRAINING_DATA,
                "package",
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
    """FIR-7-RV-11: non-registry synthetic sources keep specific taint reasons."""

    @pytest.mark.parametrize(
        ("source", "expected_reason"),
        [
            ("ffhq", policy.RejectionReason.RESEARCH_ONLY_SOURCE),
            ("buffalo_l", policy.RejectionReason.NC_MODEL_DERIVED),
        ],
    )
    def test_synthetic_door_reports_source_axis_taint(
        self, source: str, expected_reason: policy.RejectionReason
    ) -> None:
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


