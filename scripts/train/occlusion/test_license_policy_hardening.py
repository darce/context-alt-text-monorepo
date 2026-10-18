"""FIR-7 Lane I hardening tests (GATE-21 / GATE-22 / GATE-23).

Lives in a new file because Lane H owns ``test_license_policy.py`` concurrently.
Every assertion pins an exact ``RejectionReason`` (TEST-15).

GATE-15, the GATE-22 floor-step-4 pin, and the rv3-01/rv3-02 pins moved to
test_license_policy.py (FIR-7-PANEL7D-rv2-02) — that file is
mutation_guard.py's kill file; a pin that lives only here is exercised by
`make test-scripts` but invisible to the mutation guard.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_MODULE_PATH = Path(__file__).resolve().parent / "license_policy.py"
_SPEC = importlib.util.spec_from_file_location(
    "license_policy_hardening_subject",
    _MODULE_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
policy = importlib.util.module_from_spec(_SPEC)
sys.modules["license_policy_hardening_subject"] = policy  # required before exec for @dataclass
_SPEC.loader.exec_module(policy)
assert Path(policy.__file__).resolve() == _MODULE_PATH


# ---------------------------------------------------------------------------
# GATE-21 — registration exemption keys off lineage, not source namespace
# ---------------------------------------------------------------------------


class TestGate21OperatorOwnedLineageRegistry:
    """GATE-21: OPERATOR_OWNED_LINEAGE is door-independent; source is not."""

    def test_tooling_internal_lineage_clears_without_provenance_in_source(self) -> None:
        # Compliant tooling: allowlisted package + operator-owned lineage tag.
        # Must not require stuffing a provenance token into the package field.
        row = {
            "package": "umap-learn",
            "license": "BSD-3-Clause",
            "derived_from_model": "acx_internal_projector",
        }
        result = policy.audit_tooling_row(row)
        assert result.ok is True, (
            f"operator-owned lineage must clear registration without source "
            f"provenance token: {result.reason} {result.detail}"
        )

    def test_tooling_source_is_package_shape_also_clears(self) -> None:
        # source-is-the-package shape: one key cannot hold both package id and
        # provenance. Lineage registry is the only reachable remedy.
        row = {
            "source": "umap-learn",
            "license": "BSD-3-Clause",
            "derived_from_model": "acx_internal_projector",
        }
        result = policy.audit_tooling_row(row)
        assert result.ok is True, (
            f"source-is-package + operator lineage must pass: "
            f"{result.reason} {result.detail}"
        )

    def test_provenance_token_in_source_no_longer_required(self) -> None:
        # The old escape hatch (source=self-generated) is no longer the
        # mechanism — lineage registry is. A row that only has the lineage
        # tag still clears even with a non-provenance source value.
        row = {
            "package": "umap-learn",
            "license": "BSD-3-Clause",
            "source": "umap-learn",
            "derived_from_model": "acx_internal_projector",
        }
        result = policy.audit_tooling_row(row)
        assert result.ok is True, result.detail

    @pytest.mark.parametrize(
        "category",
        [
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
            policy.PolicyCategory.MODEL_INGEST,
            policy.PolicyCategory.OCCLUDER_ASSET,
            policy.PolicyCategory.SYNTHETIC_SOURCE,
        ],
    )
    def test_unregistered_lineage_fails_every_door(self, category: policy.PolicyCategory) -> None:
        row = {
            "model_id": "rt-detr",
            "package": "numba",
            "license": "Apache-2.0",
            "source": "self-generated",  # provenance token must NOT exempt
            "derived_from_model": "not_in_any_registry_xyz",
            "photo_clearance": "cleared",
        }
        result = policy.audit_provenance_row(dict(row), category=category)
        assert result.ok is False, (
            f"category={category.value} PASSed unregistered lineage via "
            f"source-namespace escape hatch"
        )
        assert result.reason is policy.RejectionReason.UNREGISTERED_DERIVED_MODEL, (
            f"category={category.value} reported {result.reason}, "
            "expected unregistered_derived_model"
        )


# ---------------------------------------------------------------------------
# GATE-22 — package denylist outranks registration on the tooling door
# ---------------------------------------------------------------------------


class TestGate22PackageDenylistOutranksRegistration:
    """GATE-22 / BR-24: row-author derived tag must not mask package reason."""

    def test_denylisted_package_plus_unregistered_lineage_reports_package(self) -> None:
        row = {
            "package": "ultralytics",
            "derived_from_model": "acx_internal_projector_NOT_REGISTERED_junk",
        }
        # Use a junk tag that is NOT in OPERATOR_OWNED_LINEAGE so registration
        # would also fire if ordered first — the package reason must win.
        result = policy.audit_tooling_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE, (
            f"expected denylisted_package, got {result.reason} ({result.detail}); "
            "registration must not mask the package reason (BR-24 / GATE-22)"
        )

    def test_denylisted_package_plus_any_junk_lineage_reports_package(self) -> None:
        # Mirrors the measured baseline: ultralytics + acx_internal_projector
        # previously reported unregistered_derived_model; package must win.
        # acx_internal_projector is operator-owned after GATE-21, so this row
        # would PASS registration — package denylist is the sole fail path.
        row = {
            "package": "ultralytics",
            "derived_from_model": "acx_internal_projector",
        }
        result = policy.audit_tooling_row(row)
        assert result.ok is False
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE

    def test_precedence_inverted_order_would_surface_registration(self) -> None:
        """Discrimination: if registration ran first, this junk-tag row fails
        with unregistered_derived_model. The production order must not.
        """
        row = {
            "package": "ultralytics",
            "derived_from_model": "totally_unregistered_junk_tag_xyz",
        }
        # Floor registration alone reports unregistered.
        unreg = policy._audit_derived_registration(
            source="",
            derived="totally_unregistered_junk_tag_xyz",
            category=policy.PolicyCategory.TOOLING,
        )
        assert unreg is not None
        assert unreg.reason is policy.RejectionReason.UNREGISTERED_DERIVED_MODEL

        # Full tooling door must still report the package reason.
        result = policy.audit_tooling_row(row)
        assert result.reason is policy.RejectionReason.DENYLISTED_PACKAGE



# ---------------------------------------------------------------------------
# GATE-23 — synthetic-head exemption must re-check commercial_use every door
# ---------------------------------------------------------------------------


class TestGate23SyntheticExemptionRechecksCommercialUse:
    """GATE-23: FORBIDDEN synthetic not in NC_MODEL_IDS must fail every door."""

    @pytest.fixture
    def forbidden_synthetic_not_in_nc(self, monkeypatch: pytest.MonkeyPatch):
        """Register a FORBIDDEN synthetic head that is absent from NC_MODEL_IDS.

        ``vec2face`` is FORBIDDEN but also NC-tainted — it cannot prove this
        hole. A fresh entry with empty clearance_decision is required.
        """
        entry = policy.SyntheticSourceEntry(
            source_id="synth_forbidden_only",
            verification=policy.VerificationMetadata(
                spdx_id="PENDING-LEGAL-CLEARANCE",
                commercial_use=policy.CommercialUse.FORBIDDEN,
                clearance_decision="",  # content-triggered clearance is a no-op
                notes="test-only FORBIDDEN synthetic not mirrored into NC_MODEL_IDS",
            ),
        )
        new_synth = dict(policy.SYNTHETIC_SOURCE_ENTRIES)
        new_synth["synth_forbidden_only"] = entry
        monkeypatch.setattr(policy, "SYNTHETIC_SOURCE_ENTRIES", new_synth)

        # Expand synthetic id set so _resolve_registry_head finds the head.
        new_expanded = policy._expand_ids(frozenset(new_synth.keys()))
        monkeypatch.setattr(policy, "SYNTHETIC_SOURCE_IDS_EXPANDED", new_expanded)
        mapping: dict[str, str] = {}
        for head in new_synth:
            hc = policy.canonical(head)
            if hc is None:
                continue
            for form in policy._expand_id_forms(hc, exact_only=False):
                mapping[form] = hc
                mapping[policy._compact_canonical(form)] = hc
        monkeypatch.setattr(policy, "_SYNTHETIC_EXPANDED_TO_HEAD", mapping)

        # Critical: leave NC_MODEL_IDS / expanded WITHOUT this head so the NC
        # taint axis cannot be the reason that catches the row.
        assert "synth_forbidden_only" not in policy.NC_MODEL_IDS
        assert policy.match_nc_model_pattern("synth_forbidden_only") is None

        return "synth_forbidden_only"

    @pytest.mark.parametrize(
        "category",
        [
            policy.PolicyCategory.TRAINING_DATA,
            policy.PolicyCategory.TOOLING,
            policy.PolicyCategory.MODEL_INGEST,
            policy.PolicyCategory.OCCLUDER_ASSET,
            policy.PolicyCategory.SYNTHETIC_SOURCE,
        ],
    )
    def test_forbidden_synthetic_derived_fails_every_door(
        self,
        category: policy.PolicyCategory,
        forbidden_synthetic_not_in_nc: str,
    ) -> None:
        head = forbidden_synthetic_not_in_nc
        row: dict[str, Any] = {
            "model_id": "rt-detr",
            "package": "numba",
            "license": "Apache-2.0",
            "source": "self-generated",
            "derived_from_model": head,
            "photo_clearance": "cleared",
        }
        result = policy.audit_provenance_row(dict(row), category=category)
        assert result.ok is False, (
            f"category={category.value} PASSed FORBIDDEN synthetic derived "
            f"{head!r}; commercial_use was not re-checked on the exemption path"
        )
        # Must not be NC (that would mean our fixture leaked into NC_MODEL_IDS).
        assert result.reason is not policy.RejectionReason.NC_MODEL_DERIVED, (
            "fixture contaminated: NC taint caught the row; GATE-23 is unproven"
        )
        # commercial_use re-check on the synthetic-head path (preferred fix).
        assert result.reason is policy.RejectionReason.PENDING_LEGAL_CLEARANCE, (
            f"category={category.value} reported {result.reason}; "
            "expected pending_legal_clearance from commercial_use re-check"
        )


# ---------------------------------------------------------------------------
# RV-14 — unreadable node-id baseline returns named harness error (not traceback)
# ---------------------------------------------------------------------------


def _load_mutation_guard_module():
    """Import mutation_guard by path (same pattern as license_policy subject)."""
    path = Path(__file__).resolve().parent / "mutation_guard.py"
    spec = importlib.util.spec_from_file_location(
        "mutation_guard_hardening_subject",
        path,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mutation_guard_hardening_subject"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestRv14UnreadableNodeidBaseline:
    """RV-14: PermissionError on fixture must be a named harness error, not bare OSError."""

    def test_unreadable_baseline_returns_harness_error(
        self, tmp_path: Path
    ) -> None:
        import os

        if os.geteuid() == 0:
            pytest.skip("chmod 000 does not restrict root; RV-14 untestable as root")

        fixture = tmp_path / "mutation_guard_nodeid_baseline.txt"
        fixture.write_text(
            "test_license_policy.py::TestApacheSelfGeneratedPasses::"
            "test_apache_self_generated_row_passes\n",
            encoding="utf-8",
        )
        fixture.chmod(0o000)
        try:
            guard = _load_mutation_guard_module()
            nodeids, err = guard._load_nodeid_baseline(fixture)
        finally:
            fixture.chmod(0o644)

        assert nodeids == frozenset()
        assert err is not None
        # Exact contract, not a substring soup: the loader must emit the named
        # harness message with the path and the concrete errno (13 = EACCES).
        assert err.startswith(
            f"node-id baseline fixture unreadable: {fixture} [errno 13]:"
        ), err

    def test_non_utf8_baseline_returns_harness_error(self, tmp_path: Path) -> None:
        """A readable but non-UTF-8 fixture must not escape as a bare traceback.

        UnicodeDecodeError subclasses ValueError, not OSError, so an OSError-only
        catch leaves this branch crashing while every sibling malformed-fixture
        branch reports HARNESS-ERROR. Goes red if the catch narrows back to OSError.
        """
        fixture = tmp_path / "mutation_guard_nodeid_baseline.txt"
        fixture.write_bytes(
            b"test_license_policy.py::TestApacheSelfGeneratedPasses::"
            b"test_apache_self_generated_row_passes\n\xff\xfe"
        )

        guard = _load_mutation_guard_module()
        nodeids, err = guard._load_nodeid_baseline(fixture)

        assert nodeids == frozenset()
        assert err is not None
        # No errno on UnicodeDecodeError, so the bracket segment must be absent.
        assert err.startswith(f"node-id baseline fixture unreadable: {fixture}: "), err
        assert "codec can't decode" in err, err


