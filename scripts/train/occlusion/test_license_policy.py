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
            row["clearance"] = policy.DCFACE_CLEARANCE_DECISION
        elif clearance != "__omit__":
            row["clearance"] = clearance
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
        assert "clearance" not in row
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
        assert "clearance" not in row
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
            "clearance": clearance,
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
            "clearance": "uncleared",
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
            "clearance": "cleared",
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
            "clearance": "cleared",
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
        row = {
            "package_name": "ultralytics",
            "license": "Apache-2.0",
            "derived_from_model": "",
        }
        via_row = policy.audit_tooling_row(row)
        via_dep = policy.audit_tooling_dependency("ultralytics")
        assert via_row.reason is via_dep.reason
        assert via_row.reason is policy.RejectionReason.DENYLISTED_PACKAGE

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
        row = {
            "source": "synthface3",
            "license": "Apache-2.0",
            "derived_from_model": "synthface3/g1",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE


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
        row = {
            "source": "yunet",
            "license": "MIT",
            "derived_from_model": "acx/occluder-renderer-v1",
        }
        result = policy.audit_provenance_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.UNREGISTERED_DERIVED_MODEL

    def test_br33_nc_precedence_over_synthetic(self) -> None:
        # Dual violation: NC-derived + synthetic source key. NC wins.
        row = {
            "source": "dcface",
            "license": "Apache-2.0",
            "derived_from_model": "insightface/buffalo_l",
            "clearance": policy.DCFACE_CLEARANCE_DECISION,
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
               "derived_from_model": corpus, "clearance": "cleared"}
        result = policy.audit_provenance_row(row, category=policy.PolicyCategory.TRAINING_DATA)
        assert result.ok is False, f"self-generated + derived={corpus!r} must not pass"
        assert result.reason is policy.RejectionReason.RESEARCH_ONLY_SOURCE

    def test_clean_derived_still_passes(self) -> None:
        # Guards against a blanket-reject "fix".
        assert policy.audit_derived_from_model("rt-detr").ok is True


class TestBr53CategoryIndependentFloor:
    """BR-53: a caller must not escape the floor by picking a weaker category."""

    DENYLISTED_LICENSE_ROW = {"model_id": "yunet", "source": "insightface", "license": "AGPL-3.0"}
    CLEARED_SYNTHETIC_ROW = {"source": "dcface", "license": "AGPL-3.0", "derived_from_model": ""}

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_denylisted_license_rejected_by_every_door(self, category) -> None:
        result = policy.audit_provenance_row(dict(self.DENYLISTED_LICENSE_ROW), category=category)
        assert result.ok is False, (
            f"category={category.value} passed a row the other doors reject; "
            "a caller could pick this door to bypass the gate"
        )

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_clearance_does_not_waive_license_floor(self, category) -> None:
        row = dict(self.CLEARED_SYNTHETIC_ROW)
        row["clearance"] = policy.DCFACE_CLEARANCE_DECISION
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"category={category.value}: an operator clearance token must not "
            "waive the AGPL-3.0 denylist"
        )

    def test_license_floor_reason_is_exact(self) -> None:
        result = policy.audit_provenance_row(
            dict(self.DENYLISTED_LICENSE_ROW),
            category=policy.PolicyCategory.MODEL_INGEST,
        )
        assert result.reason is policy.RejectionReason.DENYLISTED_LICENSE

    @pytest.mark.parametrize("category", list(policy.PolicyCategory))
    def test_research_source_rejected_by_every_door(self, category) -> None:
        row = {"source": "ffhq", "license": "Apache-2.0", "derived_from_model": ""}
        result = policy.audit_provenance_row(row, category=category)
        assert result.ok is False, (
            f"category={category.value} accepted a research-only source"
        )

    def test_legitimate_model_ingest_still_passes(self) -> None:
        # Guards against a blanket-reject "fix" that would make the floor vacuous.
        row = {"model_id": "rt-detr", "license": "Apache-2.0", "derived_from_model": ""}
        result = policy.audit_provenance_row(row, category=policy.PolicyCategory.MODEL_INGEST)
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
        "clearance": "cleared",
    }
    RESEARCH_PLUS_DENYLISTED = {
        "source": "self-generated",
        "license": "AGPL-3.0",
        "derived_from_model": "ffhq",
        "clearance": "cleared",
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
    KEY_ABSENT_DENYLISTED_ROW = {
        "source": "self-generated",
        "license": "AGPL-3.0",
        "clearance": "cleared",
    }

    @pytest.mark.parametrize("category", FLOOR_REACHING_CATEGORIES)
    def test_floor_still_runs_when_derived_key_absent(self, category) -> None:
        # The taint block is guarded by `if "derived_from_model" in row`. Replace
        # that guard with an early `return None` and the floor is skipped for
        # key-absent rows -- asserting the exact reason is what catches it,
        # because other rules also produce ok=False here.
        row = dict(self.KEY_ABSENT_DENYLISTED_ROW)
        assert "derived_from_model" not in row
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
