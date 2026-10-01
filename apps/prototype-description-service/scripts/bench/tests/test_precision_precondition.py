"""Precision precondition: bootstrap half-width, occasion rules, Holm."""

from __future__ import annotations

from scripts.bench.score_report import (
    BOOTSTRAP_RESAMPLES,
    CrossbenchTier,
    _primary_claim_type,
    assign_tier,
    bootstrap_paired_delta,
    holm_bonferroni,
)


def test_green_identical_legs_half_width_zero() -> None:
    a = [1.0] * 6
    b = [1.0] * 6
    interval = bootstrap_paired_delta(a, b, seed=20260729, metric="mean")
    assert interval.ci_half_width == 0.0
    assert interval.ci_lower == 0.0
    assert interval.ci_upper == 0.0


def test_red_discordant_half_width_above_floor() -> None:
    a = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
    b = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    interval = bootstrap_paired_delta(a, b, seed=20260729, metric="mean")
    assert interval.ci_half_width > 0.05
    ctx = {
        "named": True,
        "primary": False,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": interval.ci_half_width,
        "head_to_head_delta": 0.10,
        "holm_significant": True,
        "exhaustiveness_ok": True,
        "count_only": False,
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "ci_half_width_above_precision_floor"


def test_occasion_vs_media_resampling() -> None:
    # two occasions of three images: (+1,+1,+1) and (-1,-1,-1)
    a = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
    b = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    occasions = ["A", "A", "A", "B", "B", "B"]
    media = bootstrap_paired_delta(a, b, seed=1, metric="mean")
    occ = bootstrap_paired_delta(a, b, seed=1, metric="mean", occasion_ids=occasions)
    assert occ.resampling_unit == "occasion"
    assert occ.ci_half_width != media.ci_half_width
    assert media.resampling_unit in {"image", "media"}


def test_partial_occasion_splits() -> None:
    a = [1.0, 1.0, 1.0, 0.0]
    b = [0.0, 0.0, 0.0, 1.0]
    # occasion A fully accepted (3); occasion B only one accepted image
    occasions = ["A", "A", "A", "B"]
    accepted_mask = [True, True, True, True]
    # Mark occasion B as partial by declaring its full size is 3
    interval = bootstrap_paired_delta(
        a,
        b,
        seed=2,
        metric="mean",
        occasion_ids=occasions,
        occasion_full_size={"A": 3, "B": 3},
        accepted_mask=accepted_mask,
    )
    assert interval.partial_occasions >= 1
    assert interval.resampling_unit == "occasion+image"


def test_unknown_occasions_remain_image_resampling_units() -> None:
    interval = bootstrap_paired_delta(
        [1.0, 0.0],
        [0.0, 1.0],
        seed=3,
        metric="mean",
        occasion_ids=["image:1", "image:2"],
        occasion_full_size={"image:1": 1, "image:2": 1},
    )
    assert interval.resampling_unit == "image"


def test_holm_on_secondaries() -> None:
    # Three secondaries; first two tiny p, third large.
    result = holm_bonferroni(
        [("s1", 0.001), ("s2", 0.01), ("s3", 0.20)],
        alpha=0.05,
    )
    assert result["s1"]["holm_significant"] is True
    assert result["s3"]["holm_significant"] is False
    empty = holm_bonferroni([], alpha=0.05)
    assert empty == {}


def test_holm_family_size_does_not_shrink() -> None:
    # One computed p in a declared family of 3 must use threshold 0.05/3.
    result = holm_bonferroni([("s1", 0.04)], alpha=0.05, family_size=3)
    assert result["s1"]["holm_threshold"] == 0.05 / 3
    assert result["s1"]["holm_significant"] is False
    shrunk = holm_bonferroni([("s1", 0.04)], alpha=0.05)
    assert shrunk["s1"]["holm_threshold"] == 0.05
    assert shrunk["s1"]["holm_significant"] is True


def test_bootstrap_resamples_pinned() -> None:
    assert BOOTSTRAP_RESAMPLES == 2000


def test_unknown_metric_raises() -> None:
    from scripts.bench.stack_pair import BenchError

    try:
        bootstrap_paired_delta([1.0], [0.0], seed=1, metric="ratio")
    except BenchError as exc:
        assert exc.code == "config_invalid"
    else:
        raise AssertionError("unknown metric must fail closed")


def test_assign_tier_missing_half_width_is_fail_closed() -> None:
    ctx = {
        "named": True,
        "primary": True,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "ci_half_width_above_precision_floor"


def test_assign_tier_primary_emits_confirmatory() -> None:
    ctx = {
        "named": True,
        "primary": True,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "ok",
        "primary_claim_type": "equivalence",
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.CONFIRMATORY
    assert reason is None


def test_assign_tier_superiority_claim_emits_confirmatory() -> None:
    ctx = {
        "named": True,
        "primary": True,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.02,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "ok",
        "primary_claim_type": "superiority",
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.CONFIRMATORY
    assert reason is None


def test_primary_claim_classifies_superiority_equivalence_and_unsupported() -> None:
    assert _primary_claim_type(0.02, 0.07, 0.10) == "superiority"
    assert _primary_claim_type(-0.04, 0.03, 0.10) == "equivalence"
    assert _primary_claim_type(-0.12, 0.02, 0.10) is None


def test_primary_claim_is_required_for_confirmatory_tier() -> None:
    ctx = {
        "named": True,
        "primary": True,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "ok",
        "primary_claim_type": None,
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "primary_claim_unsupported"


def test_assign_tier_holm_secondary_emits_confirmatory() -> None:
    ctx = {
        "named": True,
        "primary": False,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": True,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "ok",
    }
    tier, reason = assign_tier("detection_precision@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.CONFIRMATORY
    assert reason is None


def test_assign_tier_primary_name_does_not_bypass_flag() -> None:
    ctx = {
        "named": True,
        "primary": False,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "holm"


def test_bootstrap_p_uses_B_not_n_used() -> None:
    """Replaces the R2-07 vacuous all-same-sign red-proof (FIR-8 R3-01).

    Mixed-sign defined deltas plus dropped draws. Exact p must fail under
    `/n_used` AND under numerators that ignore undefined-as-zero.
    """
    import random

    from scripts.bench.score_report import ImageCounts, _resample_delta

    # 2 +1 images, 1 -1 image, 4 zero-denom (undefined when exclusively picked).
    a = [
        ImageCounts(1, 0, 0),
        ImageCounts(1, 0, 0),
        ImageCounts(0, 0, 1),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
    ]
    b = [
        ImageCounts(0, 0, 1),
        ImageCounts(0, 0, 1),
        ImageCounts(1, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
    ]
    B = 80
    seed = 7
    interval = bootstrap_paired_delta(a, b, seed=seed, metric="micro_recall", B=B)

    rng = random.Random(seed)
    n = len(a)
    n_le = n_ge = n_undef = 0
    n_defined_neg = n_defined_pos = 0
    for _ in range(B):
        picks = [rng.randrange(n) for _ in range(n)]
        delta = _resample_delta(a, b, picks, "micro_recall")
        if delta is None:
            n_undef += 1
            n_le += 1
            n_ge += 1
        else:
            if delta <= 0.0:
                n_le += 1
            if delta >= 0.0:
                n_ge += 1
            if delta < 0.0:
                n_defined_neg += 1
            if delta > 0.0:
                n_defined_pos += 1
    n_used = B - n_undef
    assert n_used < B
    assert n_undef > 0
    assert n_defined_neg > 0 and n_defined_pos > 0
    assert interval.n_used == n_used
    assert interval.bootstrap_status == "partial"
    # Hand-fixed (seed=7, B=80): n_le=22, n_ge=69, n_undef=1.
    # 2 * min(22, 69) / 80 = 0.55. Do not replay the production aggregator.
    p_expected = 0.55
    assert n_le == 22 and n_ge == 69 and n_undef == 1
    assert interval.p_value == p_expected
    # Mutations that must not collide with p_expected:
    p_over_n_used = min(1.0, max(2.0 * min(n_le / n_used, n_ge / n_used), 1.0 / (B + 1)))
    p_unadjusted = min(
        1.0,
        max(2.0 * min((n_le - n_undef) / B, (n_ge - n_undef) / B), 1.0 / (B + 1)),
    )
    assert p_over_n_used != p_expected
    assert p_unadjusted != p_expected
    # Hand-computed oracle for a singleton resample of image 0 (FIR-8 R4-12).
    # a[0] recall = tp/(tp+fn) = 1/(1+0) = 1; b[0] = 0/(0+1) = 0; Δ = 1.
    # Production _resample_delta is the SUT, not the oracle.
    assert a[0].tp == 1 and a[0].fn == 0
    assert b[0].tp == 0 and b[0].fn == 1
    hand_delta = (1 / 1) - (0 / 1)
    assert hand_delta == 1.0
    assert _resample_delta(a, b, [0], "micro_recall") == hand_delta


def test_assign_tier_partial_bootstrap_demotes_primary() -> None:
    ctx = {
        "named": True,
        "primary": True,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "partial",
    }
    tier, reason = assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "bootstrap_status"


def test_assign_tier_partial_bootstrap_demotes_holm_secondary() -> None:
    ctx = {
        "named": True,
        "primary": False,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": True,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "bootstrap_series_mismatch",
    }
    tier, reason = assign_tier("detection_precision@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "bootstrap_status"


def test_empty_series_raises() -> None:
    from scripts.bench.stack_pair import BenchError

    try:
        bootstrap_paired_delta([], [], seed=1, metric="mean")
    except BenchError as exc:
        assert exc.code == "bootstrap_empty_series"
    else:
        raise AssertionError("empty series must fail closed")


def test_assign_tier_missing_bootstrap_status_is_fail_closed() -> None:
    from scripts.bench.stack_pair import BenchError

    ctx = {
        "named": True,
        "primary": True,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
    }
    try:
        assign_tier("detection_recall@frame_e2e/label_map_primary", ctx)
    except BenchError as exc:
        assert exc.code == "bootstrap_status_missing"
    else:
        raise AssertionError("missing bootstrap_status must not default to ok")


def test_assign_tier_partial_nonsignificant_secondary_reasons_status() -> None:
    ctx = {
        "named": True,
        "primary": False,
        "optimistic": False,
        "native_frame": False,
        "floor_ok": True,
        "ci_half_width": 0.0,
        "head_to_head_delta": 0.10,
        "holm_significant": False,
        "exhaustiveness_ok": True,
        "count_only": False,
        "bootstrap_status": "partial",
    }
    tier, reason = assign_tier("identification_recall@frame_e2e/label_map_primary", ctx)
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "bootstrap_status"


def test_padded_ci_uses_B_draw_space_not_survivors() -> None:
    """Exact ci_lower/ci_upper on mixed defined/undefined (FIR-8 R4-02)."""
    from scripts.bench.score_report import ImageCounts

    a = [
        ImageCounts(1, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
    ]
    b = [
        ImageCounts(0, 0, 1),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
        ImageCounts(0, 0, 0),
    ]
    B = 20
    seed = 7
    interval = bootstrap_paired_delta(a, b, seed=seed, metric="micro_recall", B=B)
    assert interval.bootstrap_status == "partial"
    # Padded B-draw space (seed=7, B=20): 17 defined Δ=1.0 + 3 zeros.
    # Linear 2.5th/97.5th of [0]*3 + [1]*17: lower=0.0, upper=1.0.
    # Survivor-only percentiles of [1]*17 would be 1.0/1.0.
    assert interval.n_used == 17
    assert interval.ci_lower == 0.0
    assert interval.ci_upper == 1.0
    assert (interval.ci_lower, interval.ci_upper) != (1.0, 1.0)


def test_score_uses_full_manifest_occasions_and_caps_golden150_tiers(
    tmp_path, monkeypatch
) -> None:
    import hashlib
    import json

    from scripts.bench import score_report
    from scripts.bench.driver import init_run_dir
    from scripts.bench.stack_pair import load_stack_pair
    from scripts.bench.tests.conftest import golden_entry, valid_pair_dict, write_pair
    from scripts.bench.tests.test_score_head_to_head import (
        A_STACK,
        B_STACK,
        NATIVE_ID,
        PRIMARY,
        _box,
        _pred,
        _write_leg,
        _write_manifest,
    )

    session_a = "occasion-a"
    session_b = "occasion-b"
    entries = []
    for media_id in range(1, 7):
        entry = golden_entry(
            media_id,
            face_count=2,
            present_identities=["Alice Q"],
            face_boxes=[
                _box(),
                {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0, "name": None, "source": "iptc"},
            ],
        )
        entry["face_boxes"][0]["lineage"]["capture_session_id"] = (
            session_a if media_id <= 3 else session_b
        )
        entry["face_boxes"][1]["lineage"]["capture_session_id"] = (
            session_a if media_id <= 3 else session_b
        )
        entries.append(entry)

    manifest_path = _write_manifest(
        tmp_path / "golden150-draft-20260723.json", entries
    )
    secondary_endpoints = [
        "detection_precision@frame_e2e/label_map_primary",
        "identification_recall@frame_e2e/label_map_primary",
        "identification_precision@frame_e2e/label_map_primary",
        "identification_recall@frame_e2e/label_map_optimistic",
        NATIVE_ID,
    ]
    pair = load_stack_pair(
        write_pair(
            tmp_path / "pair.yaml",
            valid_pair_dict(accepted_set_floor=0.5, secondary_endpoints=secondary_endpoints),
        )
    )
    run_dir = init_run_dir(tmp_path / "run", pair, manifest_path)
    media_ids = list(range(1, 7))
    predictions = [_pred(media_id) for media_id in media_ids]
    for stack_id in (A_STACK, B_STACK):
        _write_leg(run_dir, stack_id, predictions, media_ids)
        items_path = run_dir / "legs" / stack_id / "items.jsonl"
        retained = [
            line
            for line in items_path.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["manifest_media_id"] not in {5, 6}
        ]
        items_path.write_text("\n".join(retained) + "\n", encoding="utf-8")
        exports_path = run_dir / "legs" / stack_id / "exports"
        identities_path = exports_path / "media_identities.json"
        identities = json.loads(identities_path.read_text(encoding="utf-8"))
        identities = [row for row in identities if row["media_id"] not in {5, 6}]
        identities_path.write_text(json.dumps(identities), encoding="utf-8")
        identity_results = [
            {
                "media_id": media_id,
                "query_succeeded": True,
                "rows": [row for row in identities if row["media_id"] == media_id],
            }
            for media_id in range(1, 5)
        ]
        (exports_path / "media_identity_results.json").write_text(
            json.dumps(identity_results), encoding="utf-8"
        )
        members_path = exports_path / "cluster_members.json"
        members = json.loads(members_path.read_text(encoding="utf-8"))
        for cluster in members:
            cluster["members"] = [
                row for row in cluster["members"] if row["media_id"] not in {5, 6}
            ]
        members_path.write_text(json.dumps(members), encoding="utf-8")

    observed_calls: list[dict[str, object]] = []
    original_bootstrap = score_report.bootstrap_paired_delta

    def observe_bootstrap(*args, **kwargs):
        observed_calls.append(kwargs.copy())
        return original_bootstrap(*args, **kwargs)

    # Test an approved pinned manifest after its run metadata has disappeared.
    monkeypatch.setattr(
        score_report,
        "GOLDEN150_MANIFEST_SHA256",
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )
    run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    run_doc["manifest_path"] = "renamed-source.json"
    (run_dir / "run.json").write_text(json.dumps(run_doc), encoding="utf-8")
    assert score_report._is_golden150_corpus(run_dir) is True
    (run_dir / "run.json").unlink()

    # This regression exercises tier provenance, not the separately gated PROV-01 check.
    monkeypatch.setattr(score_report, "_require_prov01_preflights", lambda root, stacks: True)
    monkeypatch.setattr(score_report, "bootstrap_paired_delta", observe_bootstrap)
    score_report.score_head_to_head(run_dir)

    primary_call = next(call for call in observed_calls if call.get("cell") == PRIMARY)
    assert primary_call["occasion_ids"] == [
        f"occasion:{session_a}",
        f"occasion:{session_a}",
        f"occasion:{session_a}",
        f"occasion:{session_b}",
    ]
    assert primary_call["occasion_full_size"] == {
        f"occasion:{session_a}": 3,
        f"occasion:{session_b}": 3,
    }

    frames = json.loads((run_dir / "score" / "frames.json").read_text(encoding="utf-8"))
    assert frames["primary_claim"]["claim_type"] == "equivalence"
    assert frames["primary_claim"]["direction"] is None
    assert frames["degenerate_box_dropped"] == {A_STACK: 4, B_STACK: 4}
    expected_holm_family = [
        "detection_precision@frame_e2e/label_map_primary",
        "identification_recall@frame_e2e/label_map_primary",
        "identification_precision@frame_e2e/label_map_primary",
    ]
    assert frames["holm_family"] == expected_holm_family
    assert frames["holm_family_size"] == len(expected_holm_family)
    for endpoint in expected_holm_family:
        endpoint_cells = [cell for cell in frames["cells"] if cell.get("cell") == endpoint]
        assert len(endpoint_cells) == 2
        for cell in endpoint_cells:
            expected_threshold = 0.05 / (len(expected_holm_family) - cell["holm_rank"] + 1)
            assert cell["holm_threshold"] == expected_threshold
    directional_secondaries = [
        cell for cell in frames["cells"]
        if cell.get("cell") in {NATIVE_ID, "identification_recall@frame_e2e/label_map_optimistic"}
    ]
    assert len(directional_secondaries) == 4
    assert all("holm_rank" not in cell for cell in directional_secondaries)
    primary_cells = [cell for cell in frames["cells"] if cell.get("cell") == PRIMARY]
    assert len(primary_cells) == 2
    for cell in primary_cells:
        assert cell["primary_claim_type"] == "equivalence"
        assert cell["primary_claim_direction"] is None
        assert cell["resampling_unit"] == "occasion+image"
        assert cell["partial_occasions"] == 1
        assert cell["tier"] == CrossbenchTier.DIRECTIONAL.value
        assert cell["reason"] == "golden150_bias_bound_pending"

    native_identification = [
        cell for cell in frames["cells"] if cell.get("cell") == NATIVE_ID
    ]
    assert len(native_identification) == 2
    assert all(cell["tier"] == CrossbenchTier.DIRECTIONAL.value for cell in native_identification)
    assert all(cell["reason"] == "frame_fir5_native" for cell in native_identification)
