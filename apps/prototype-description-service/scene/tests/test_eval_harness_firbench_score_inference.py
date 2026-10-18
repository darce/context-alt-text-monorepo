"""S3 inference adjudication: synthetic cohorts and an independent PSU resampling oracle."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_score as fs


def _manifest(*, ratified: bool = True) -> fc.DecisionManifest:
    path = Path(__file__).resolve().parents[4] / "benchmarks/manifests/fir-bench-decision-v1.json"
    base = fc.load_decision_manifest(path)
    if not ratified:
        return base
    sha = "a" * 64
    base = dataclasses.replace(
        base,
        frames=tuple(dataclasses.replace(f, source_sha256=sha, exhaustive=True) for f in base.frames),
        gallery_lineage=dataclasses.replace(base.gallery_lineage, templates_sha256=sha),
        ratification=fc.Ratification(decision_ref="synthetic-only", ratified_at="2026-10-01T00:00:00Z"),
    )
    return fc.seal(base, sealed_at="2026-10-02T00:00:00Z")


def _arrays(leg: fc.LegKind = fc.LegKind.sface, **changes: object) -> fs.LegArrays:
    args = {
        "leg": leg,
        "face_ids": ("f0", "f1", "f2"),
        "outcomes": (fc.FaceOutcome.correct, fc.FaceOutcome.missed, fc.FaceOutcome.unaligned),
        "psu_ids": ("p0", "p1", "p1"),
        "weights": (1.0, 2.0, 3.0),
    }
    return fs.LegArrays(**(args | changes))


def _results(manifest: fc.DecisionManifest, **changes: object) -> fs.LegResults:
    args = {
        "frame": manifest.frame("confirm-v1" if manifest.seal else "fir-occ-v1-prob"),
        "legs": {leg: _arrays(leg) for leg in fc.LegKind},
        "unit_psu_ids": tuple(f"u{i}" for i in range(3000)),
        "h2_leg": fc.LegKind.auraface,
        "guardrails": {
            g.id: fs.GuardrailReading(fs.GuardrailState.pass_, 0.0)
            for g in manifest.guardrails
            if g.role is fc.GuardrailRole.veto
        },
    }
    return fs.LegResults(**(args | changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"face_ids": ("f0", "f1", "f1")},
        {"face_ids": ("f0", "", "f2")},
        {"face_ids": ("f0", None, "f2")},
        {"psu_ids": ("p0", "", "p1")},
        {"psu_ids": ("p0", None, "p1")},
        {"outcomes": (fc.FaceOutcome.correct,)},
        {"psu_ids": ("p0",)},
        {"weights": (1.0,)},
        *({"weights": (1.0, w, 3.0)} for w in [0.0, -1.0, np.inf, -np.inf, np.nan, None, True]),
        *({"outcomes": (fc.FaceOutcome.correct, o, fc.FaceOutcome.missed)}
          for o in [None, "correct", fc.FaceOutcome.correct_reject, fc.FaceOutcome.false_accept]),
    ],
)
def test_leg_arrays_reject_malformed_mated_inventory(changes: dict[str, object]) -> None:
    with pytest.raises(fc.FrameContractError):
        _arrays(**changes)


@pytest.mark.parametrize("mismatch", ["missing", "extra", "psu", "weight", "leg_key"])
def test_paired_cohorts_must_match_exactly(mismatch: str) -> None:
    results = _results(_manifest())
    right = results.legs[fc.LegKind.auraface]
    if mismatch in {"missing", "extra"}:
        right = dataclasses.replace(right, face_ids=("f0", "f1", "alien"))
        if mismatch == "missing":
            right = dataclasses.replace(
                right, face_ids=right.face_ids[:2], outcomes=right.outcomes[:2],
                psu_ids=right.psu_ids[:2], weights=right.weights[:2],
            )
    elif mismatch == "psu":
        right = dataclasses.replace(right, psu_ids=("different", "p1", "p1"))
    elif mismatch == "weight":
        right = dataclasses.replace(right, weights=(2.0, 2.0, 3.0))
    else:
        right = dataclasses.replace(right, leg=fc.LegKind.insightface)
    results = dataclasses.replace(results, legs=dict(results.legs) | {fc.LegKind.auraface: right})
    with pytest.raises(fc.FrameContractError):
        fs._paired(results, fc.LegKind.sface, fc.LegKind.auraface)


def test_reordered_cohort_keeps_explicit_misses_and_fixed_face_weights() -> None:
    results = _results(_manifest())
    right = _arrays(
        fc.LegKind.auraface, face_ids=("f2", "f0", "f1"),
        outcomes=(fc.FaceOutcome.correct, fc.FaceOutcome.missed, fc.FaceOutcome.correct),
        psu_ids=("p1", "p0", "p1"), weights=(3.0, 1.0, 2.0),
    )
    results = dataclasses.replace(results, legs=dict(results.legs) | {fc.LegKind.auraface: right})
    faces, a, b, psus, weights = fs._paired(results, fc.LegKind.sface, fc.LegKind.auraface)
    assert faces == ["f0", "f1", "f2"]
    assert a == [fc.FaceOutcome.correct, fc.FaceOutcome.missed, fc.FaceOutcome.unaligned]
    assert b == [fc.FaceOutcome.missed, fc.FaceOutcome.correct, fc.FaceOutcome.correct]
    interval = fs.paired_cluster_bootstrap(a, b, psus, weights=weights, n_boot=10000, seed=3, level=0.95)
    assert interval.delta == pytest.approx(4 / 6, abs=1e-12)


@pytest.mark.parametrize(
    "changes",
    [
        *({"n_boot": n} for n in [0, -1, 1.5, True, None]),
        *({"seed": s} for s in [-1, 1.5, True, None]),
        *({"level": level} for level in [0.0, 1.0, np.nan, np.inf, None, True]),
        *({"weights": (1.0, w)} for w in [0.0, -1.0, np.inf, np.nan, None, True]),
        {"weights": (1.0,)},
        {"psu_of": ("p0", None)},
        {"psu_of": ("p0", "")},
        {"outcomes_a": (fc.FaceOutcome.correct,)},
        {"outcomes_b": (fc.FaceOutcome.correct_reject, fc.FaceOutcome.correct)},
        {"outcomes_b": ("correct", fc.FaceOutcome.correct)},
    ],
)
def test_bootstrap_rejects_invalid_contract_inputs(changes: dict[str, object]) -> None:
    args = {
        "outcomes_a": (fc.FaceOutcome.correct, fc.FaceOutcome.missed),
        "outcomes_b": (fc.FaceOutcome.missed, fc.FaceOutcome.correct),
        "psu_of": ("p0", "p1"), "n_boot": 10000, "seed": 2429382368, "level": 0.95,
    }
    with pytest.raises(fc.FrameContractError):
        fs.paired_cluster_bootstrap(**(args | changes))


@pytest.mark.parametrize("value", [None, np.nan, np.inf, -np.inf])
def test_pass_without_finite_internal_measurement_is_unscored_veto(value: float | None) -> None:
    manifest = _manifest()
    results = _results(manifest)
    guardrail_id = next(iter(results.guardrails))
    readings = dict(results.guardrails) | {guardrail_id: fs.GuardrailReading(fs.GuardrailState.pass_, value)}
    verdict = fs.decide(manifest, dataclasses.replace(results, guardrails=readings))
    assert verdict.state is fc.VerdictState.inconclusive
    assert verdict.reason is fc.InconclusiveReason.required_guardrail_unscored
    assert all(h.interval is None for h in verdict.hypotheses)


def test_unratified_hypotheses_are_not_evaluated(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("unratified hypotheses must not read an interval")

    monkeypatch.setattr(fs, "paired_cluster_bootstrap", forbidden)
    manifest = _manifest(ratified=False)
    verdict = fs.decide(manifest, _results(manifest))
    assert verdict.state is fc.VerdictState.unratified
    assert all(h.state is None and h.interval is None and h.reason is None for h in verdict.hypotheses)
    for h in verdict.hypotheses:
        assert h.n_eff > 0
        assert h.mde == fs.minimum_detectable_effect(
            n_eff=h.n_eff, p_d=manifest.p_d, power=manifest.power, one_sided_alpha=h.one_sided_alpha,
        )


@pytest.mark.parametrize("state", [fs.GuardrailState.pass_, fs.GuardrailState.fail])
def test_p95_keeps_its_actual_internal_measurement_for_veto(state: fs.GuardrailState) -> None:
    manifest = _manifest()
    results = _results(manifest)
    gid = next(g.id for g in manifest.guardrails if g.metric == "p95_ms_per_face")
    reading = fs.GuardrailReading(state, 123.45)
    results = dataclasses.replace(results, guardrails=dict(results.guardrails) | {gid: reading})
    verdict = fs.decide(manifest, results)
    assert results.guardrails[gid].value == 123.45
    if state is fs.GuardrailState.pass_:
        assert verdict.hypotheses[0].interval is not None
    else:
        assert verdict.state is fc.VerdictState.guardrail_vetoed
        assert all(h.interval is None for h in verdict.hypotheses)


def test_extreme_finite_weights_do_not_overflow_the_estimand() -> None:
    result = fs.paired_cluster_bootstrap(
        (fc.FaceOutcome.missed, fc.FaceOutcome.correct),
        (fc.FaceOutcome.correct, fc.FaceOutcome.missed),
        ("p0", "p1"), weights=(1e308, 1e308), n_boot=10000, seed=0, level=0.95,
    )
    assert result.delta == 0.0
    assert (result.lower, result.upper) == (-1.0, 1.0)


@pytest.mark.parametrize("n_eff", [np.nan, np.inf, -np.inf])
def test_nonfinite_effective_size_cannot_produce_mde(n_eff: float) -> None:
    with pytest.raises(fc.FrameContractError):
        fs.minimum_detectable_effect(n_eff=n_eff, p_d=0.15, power=0.8, one_sided_alpha=0.025)


@pytest.mark.parametrize("n_psu", [17, 83])
@pytest.mark.parametrize("level", [0.90, 0.95])
def test_chunked_bootstrap_matches_literal_resampling_of_weighted_unequal_psus(
    n_psu: int, level: float, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Unequal sizes, nonuniform fractional weights and correlated paired errors; >1 chunk.
    codes = np.repeat(np.arange(n_psu), 1 + (np.arange(n_psu) * 7) % 11)
    n = len(codes)
    weights = 0.25 + (np.arange(n) * 13 % 19) / 7
    miss_a = (codes * 11 + np.arange(n)) % 17 < 7
    miss_b = (codes * 3 + np.arange(n)) % 13 < 4
    a = tuple(fc.FaceOutcome.missed if x else fc.FaceOutcome.correct for x in miss_a)
    b = tuple(fc.FaceOutcome.unaligned if x else fc.FaceOutcome.correct for x in miss_b)
    # Sorted PSU labels match the public deterministic ordering, independent of input order.
    psus = [f"p{code:04d}" for code in codes]
    seed, n_boot = 2429382368, 10000
    rng = np.random.default_rng(seed)
    expected = np.empty(n_boot)
    for i in range(n_boot):
        multiplicities = np.bincount(rng.integers(0, n_psu, size=n_psu), minlength=n_psu)[codes]
        boot_weights = multiplicities * weights
        expected[i] = np.sum(boot_weights * (miss_a.astype(float) - miss_b)) / boot_weights.sum()
    quantile = np.quantile

    def check_distribution(deltas: np.ndarray, q: object) -> np.ndarray:
        # Compare every replicate, in RNG order, including across chunk boundaries.
        np.testing.assert_allclose(deltas, expected, rtol=0, atol=1e-12)
        return quantile(deltas, q)

    with monkeypatch.context() as patch:
        patch.setattr(fs.np, "quantile", check_distribution)
        result = fs.paired_cluster_bootstrap(a, b, psus, weights=weights, n_boot=n_boot, seed=seed, level=level)
    tail = (1 - level) / 2
    assert (result.lower, result.upper) == pytest.approx(np.quantile(expected, [tail, 1 - tail]), abs=1e-12, rel=0)
    assert result.delta == pytest.approx(
        np.sum(weights * (miss_a.astype(float) - miss_b)) / weights.sum(), abs=1e-12, rel=0,
    )
    assert (result.n_psu, result.n_boot, result.seed, result.level) == (n_psu, n_boot, seed, level)
    assert result.icc is not None
    assert fs.paired_cluster_bootstrap(
        a, b, psus, weights=weights, n_boot=n_boot, seed=seed, level=level,
    ) == result
