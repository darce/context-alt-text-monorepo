"""Private static FIRBENCH-1 report (S5, screens S1-S8).

One self-contained ``index.html`` per run, plus ``report.json`` and per-table CSV.
The report reads run files only. It never imports S3 or S4 code and never
recomputes a score, threshold, cluster cut or interval: it displays what the
validated ``scores-v1``, ``clusters-v1``, ``frame-v1`` and ``face-search-record-v1``
records say, with the JSON path each number came from.

Canon v0.26.2: VIZ-41 (the selection pool comes first), VIZ-23 and INT-22 (a state
is shown with its reason), VIZ-32 (tables for exact lookup), VIZ-40 (direct labels),
WRIT-81 (decision-changing limits stay in the prose), MEAS-29 (no observation is
invented; tier-(a) labels stay out of analysis without a recorded reference),
EVAL-19 (detector-only rows never dilute the pool). Delegated defaults (MCP 16732-16736)
are displayed as declared project policy, never as ratification.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import io
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.eval_harness.firbench_glossary import render_glossary, term_link
from scripts.eval_harness.firbench_contract import (
    FaceOutcome,
    FrameContractError,
    NonPrivateOutputError,
    SearchStage,
    VerdictState,
    require_private_output_path,
    validate_interchange,
)

_SECTIONS: tuple[tuple[str, str], ...] = (
    ("curves", "Curves"),
    ("pair-cells", "Pair cells"),
    ("stages", "Stages"),
    ("failures", "Failures"),
    ("clusters", "Clusters"),
    ("compare", "Compare"),
    ("frames-power", "Frames and power"),
)
_GLYPHS: dict[str, str] = {
    VerdictState.superior: "✓",
    VerdictState.non_inferior: "✓",
    VerdictState.inconclusive: "○",
    VerdictState.guardrail_vetoed: "✗",
    VerdictState.unratified: "○",
    "pass": "✓",
    "fail": "✗",
    "veto": "✗",
    "unscored": "○",
    "not_evaluated": "○",
    "collect": "○",
    "not_scored": "○",
}
_STAGE_ORDER: tuple[str, ...] = (
    SearchStage.missed,
    SearchStage.detected,
    SearchStage.unaligned,
    SearchStage.embedded,
    SearchStage.unavailable,
    FaceOutcome.wrong_identity,
    FaceOutcome.rejected,
    FaceOutcome.correct,
)
_FAILURE_STAGES = frozenset({SearchStage.missed, SearchStage.detected, SearchStage.unaligned})
_FUSED_PREFIX = "insightface__"
_ALLOWED_DATE_SOURCES = frozenset({"seal.sealed_at", "ratification.ratified_at", "explicit"})
_NOT_EVALUATED_NO_EVIDENCE = "not evaluated: chaining evidence unavailable"
_NOT_EVALUATED_NO_PAIRS = "not evaluated: no eligible held-out different-identity pairs"
_TAU_LABEL = "acceptance τ (not a cluster cut)"
_PROJECTION_CAPTION = "diagnostic projection · distances not meaningful"
_NO_CUT = "no production cut recorded"
_TIER_A_UNRECORDED = "tier-(a): observation not recorded"
_FLOOR_NOTE = "Floors do not establish power, MDE adequacy, FPIR resolvability or exhaustive GT."
_UNRATIFIED = "unratified: no verdict"


# --- small formatting helpers ------------------------------------------------------


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _f(value: object, places: int = 3) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{places}f}"


def _jp(file: str, *parts: object) -> str:
    return file + "#/" + "/".join(str(p) for p in parts)


def _code(path: str) -> str:
    return (
        f'<button type="button" class="source" data-source="{_e(path)}" '
        f'aria-label="Inspect source {_e(path)}" title="{_e(path)}">↗ Source</button>'
    )


def _st(state: str, label: str | None = None) -> str:
    glyph = _GLYPHS.get(str(state), "○")
    return f'<span class="st st-{_e(state)}">{glyph} {_e(label if label is not None else state)}</span>'


def _interval_text(interval: Mapping[str, Any] | None) -> str:
    if not isinstance(interval, Mapping):
        return "not evaluated: no interval recorded"
    return f"[{_f(interval['lower'])}, {_f(interval['upper'])}] {float(interval['level']) * 100:.0f}%"


def _evidence_text(node: Mapping[str, Any]) -> str:
    """Return ``status`` text for an evidence wrapper; never a silent zero."""
    if node.get("status") != "available":
        return f"not evaluated: {node.get('reason') or node.get('status')}"
    return ""


def _table(caption: str, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f'<th scope="col">{_e(h)}</th>' for h in headers)
    body = "\n".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><caption>{_e(caption)}</caption>\n<thead><tr>{head}</tr></thead>\n<tbody>\n{body}\n</tbody></table>"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrameContractError(f"{path.name} is not valid JSON: {exc}") from exc


# --- run loading -------------------------------------------------------------------


def _repo_root_for(run_dir: Path) -> Path:
    """Return the repository whose ``benchmarks/private`` contains ``run_dir``."""
    parts = run_dir.parts
    for index in range(len(parts) - 1, 0, -1):
        if parts[index : index + 2] == ("benchmarks", "private"):
            candidate = Path(*parts[:index])
            try:
                require_private_output_path(run_dir, repo_root=candidate)
            except NonPrivateOutputError:
                continue
            return candidate
    raise NonPrivateOutputError(f"run {run_dir} is not under a repository benchmarks/private/ directory")


def _load_searches(run: Path, legs: Sequence[str]) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    rows: list[dict[str, Any]] = []
    sources: dict[str, bytes] = {}
    directory = _binding_file(run, "legs")
    if directory.is_dir():
        for child in directory.iterdir():
            if child.name not in legs and (child / "searches.jsonl").exists():
                raise FrameContractError("search artifact outside declared leg scope")
    for leg in legs:
        path = _binding_file(run, f"legs/{leg}/searches.jsonl")
        if not path.is_file():
            continue
        raw = path.read_bytes()
        sources[f"legs/{leg}/searches.jsonl"] = raw
        index = 0
        for line in raw.splitlines():
            if not line.strip():
                continue
            row = _binding_json(line, f"legs/{leg}/searches.jsonl row {index}")
            validate_interchange("face-search-record-v1", row)
            if row["leg_key"] != leg:
                raise FrameContractError("search leg contradicts containing leg artifact")
            row["_ref"] = _jp(f"legs/{leg}/searches.jsonl", index)
            rows.append(row)
            index += 1
    return rows, sources


def _semantic_created_at(manifest: Mapping[str, Any] | None) -> tuple[str, str | None]:
    """Display the recorded run timestamp; never fill one from the clock."""
    if manifest is None or not isinstance(manifest.get("firbench"), Mapping):
        return "date not recorded", None
    block = manifest["firbench"]
    source = block.get("created_at_source")
    if source not in _ALLOWED_DATE_SOURCES:
        raise FrameContractError(f"manifest created_at_source {source!r} is not a semantic date source")
    raw = block.get("created_at")
    if not isinstance(raw, str):
        raise FrameContractError("manifest firbench.created_at is missing")
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise FrameContractError(f"manifest firbench.created_at is not ISO8601: {exc}") from exc
    if parsed.tzinfo is None:
        raise FrameContractError("manifest firbench.created_at must carry a timezone")
    return parsed.isoformat(), str(source)


# --- S1 verdict ---------------------------------------------------------------------


def _floor_ok(scores: Mapping[str, Any]) -> bool:
    return int(scores["n_psu"]) >= int(scores["min_n_independent"])


def _fpir_interval_text(scores: Mapping[str, Any], leg: Mapping[str, Any]) -> str:
    if not _floor_ok(scores):
        raw = (
            f"FPIR interval not shown: global floor {scores['n_psu']} < {scores['min_n_independent']} "
            "independent PSUs (checked before any FPIR interval)"
        )
        return _e(raw)
    fpir = leg["operating_point"]["fpir"]
    if fpir.get("status") != "available":
        return _e(f"not evaluated: {fpir.get('reason')}")
    data = fpir["data"]
    iid = data["iid_ucl"]
    clustered = data["clustered_ucl"]
    iid_text = (
        f"iid UCL {_f(iid['data']['upper'])}"
        if iid.get("status") == "available"
        else _e(f"iid UCL not evaluated: {iid.get('reason')}")
    )
    if clustered.get("status") == "available":
        method = clustered["data"]["method"]
        cl_text = f"clustered UCL {_f(clustered['data']['upper'])} ({_e(method)})"
    else:
        cl_text = _e(f"clustered UCL not evaluated: {clustered.get('reason')}")
    return f"{iid_text}; {cl_text}"


def _verdict_html(scores: Mapping[str, Any]) -> str:
    verdict = scores["verdict"]
    state = verdict["state"]
    reason = verdict["reason"]
    if state == VerdictState.unratified:
        line = _st(state, _UNRATIFIED)
    elif state == VerdictState.inconclusive:
        line = _st(state, "INCONCLUSIVE") + ": " + (_e(reason) if reason else "no reason recorded")
    elif state == VerdictState.guardrail_vetoed:
        line = _st(state, "GUARDRAIL VETOED") + (": " + _e(reason) if reason else "")
    else:
        line = _st(state, str(state).replace("_", " ")) + " · recorded by S3 · ratification and seal are shown in S8"
    primary = scores["primary"]
    primary_text = (
        f"primary FPIR target {_f(primary['fpir_target'], 3)}: "
        f"{'resolvable' if primary['resolvable'] else 'not resolvable'}; "
        f"required n_nonmated_eff {_f(primary['required_n_nonmated_eff'], 1)}"
    )
    head = (
        f'<p class="verdict-line">{line}</p>\n'
        f"<p>Question: whether the model change is real at the primary point (FNIR at FPIR "
        f"{_f(primary['fpir_target'], 2)}, end to end). Frame admissibility "
        f"<strong>{_e(scores['admissibility'])}</strong>; frame n_eff {_f(scores['n_eff'])} "
        f"(whole GT inventory); n_psu {scores['n_psu']}; decision "
        f"{_code(_jp('scores.json', 'decision_sha256'))}.</p>\n"
        f"<p>{_e(primary_text)} {_code(_jp('scores.json', 'primary'))}</p>\n"
    )
    if not _floor_ok(scores):
        head += (
            f"<p>{_st('not_evaluated', 'global floor not met')}: n_psu {scores['n_psu']} &lt; "
            f"min_n_independent {scores['min_n_independent']}; FPIR intervals are withheld.</p>\n"
        )
    return head


def _leg_table(scores: Mapping[str, Any]) -> str:
    rows = []
    for index, leg in enumerate(scores["legs"]):
        op = leg["operating_point"]
        fnir = op["fnir"]
        fnir_data = fnir.get("data") if fnir.get("status") == "available" else None
        tau = leg["tau"]
        tau_text = (
            _f(tau["data"]["value"]) if tau.get("status") == "available" else _e(f"not evaluated: {tau.get('reason')}")
        )
        if fnir_data is not None:
            n_eff = _f(fnir_data["n_eff"])
            fnir_text = f"{fnir_data['misses']}/{fnir_data['n_mated']} = {_f(fnir_data['rate'])}"
            fnir_interval = (
                _interval_text(fnir_data["interval"]["data"])
                if fnir_data["interval"]["status"] == "available"
                else _e(f"not evaluated: {fnir_data['interval']['reason']}")
            )
        else:
            n_eff = "not evaluated"
            fnir_text = _e(f"not evaluated: {fnir.get('reason')}")
            fnir_interval = "not evaluated"
        rows.append(
            [
                _ui_leg_label(leg["leg_key"]).replace(
                    '<strong>sface</strong>', '<strong>SFace</strong>'
                ).replace('<strong>auraface</strong>', '<strong>AuraFace</strong>'
                ).replace('<strong>insightface</strong>', '<strong>InsightFace</strong>'),
                _e(scores["admissibility"]),
                f"{n_eff} {_code(_jp('scores.json', 'legs', index, 'operating_point', 'fnir', 'data', 'n_eff'))}",
                f"{fnir_text} {_code(_jp('scores.json', 'legs', index, 'operating_point', 'fnir'))}",
                _e(fnir_interval),
                f"{_fpir_text(leg)} {_code(_jp('scores.json', 'legs', index, 'operating_point', 'fpir'))}",
                _fpir_interval_text(scores, leg),
                f"{tau_text} {_code(_jp('scores.json', 'legs', index, 'tau'))}",
            ]
        )
    return (
        '<p>' + term_link('fnir', 'Missed enrolled-person searches (FNIR)') + '; '
        + term_link('fpir', 'False identifications among nonmated sources (FPIR)') + '; '
        + term_link('neff', 'Effective sample size (n_eff)') + '; '
        + term_link('threshold', 'Acceptance threshold τ') + '.</p>'
    ) + _table(
        "Per-model operating point at the frozen acceptance threshold (each model's own space)",
        [
            "Model / implementation identifier",
            "Permitted frame use",
            "Effective sample size (n_eff)",
            "Miss rate (FNIR: misses/mated searches)",
            "Miss-rate interval (FNIR)",
            "False-identification rate (FPIR: false identifications/source units)",
            "False-identification interval (FPIR)",
            "Acceptance threshold τ",
        ],
        rows,
    )


def _fpir_text(leg: Mapping[str, Any]) -> str:
    fpir = leg["operating_point"]["fpir"]
    if fpir.get("status") != "available":
        return _e(f"not evaluated: {fpir.get('reason')}")
    data = fpir["data"]
    return f"{data['fpi']}/{data['n_units']} = {_f(data['rate'])}"


def _hypotheses_html(scores: Mapping[str, Any]) -> str:
    hypotheses = list(scores["hypotheses"])
    first_state = hypotheses[0]["state"] if hypotheses else None
    rows = []
    for index, hyp in enumerate(hypotheses):
        path = _jp("scores.json", "hypotheses", index)
        if index > 0 and first_state == VerdictState.inconclusive:
            state_html = _st("not_evaluated", "not evaluated")
            reason = "H1 inconclusive; later steps are not run"
        elif hyp["state"] is None:
            state_html = _st("not_evaluated", "not evaluated")
            reason = "not reached"
        else:
            state_html = _st(hyp["state"], str(hyp["state"]).replace("_", " "))
            reason = hyp["reason"] or ""
        rows.append(
            [
                ("Is the recorded model change better?" if hyp["kind"] == "superiority"
                 else "Is the recorded model change within the allowed loss?" if hyp["kind"] == "non_inferiority"
                 else "Comparison question unavailable")
                + f'<br><small>Protocol identifier: {_e(hyp["id"])}</small>',
                _e(hyp["kind"]) + '<br><small>Comparison question unavailable in full: '
                'comparison legs unavailable; direction unavailable; margin unavailable '
                'in this score record.</small>',
                _f(hyp["step_index"], 0),
                _f(hyp["one_sided_alpha"], 3),
                _f(hyp["mde"]) if hyp["mde"] is not None else "null",
                _f(hyp["n_eff"]),
                _e(_interval_text(hyp["interval"])),
                state_html,
                _e(reason) if reason else "",
                _code(path),
            ]
        )
    if len(hypotheses) < 2 and (first_state == VerdictState.inconclusive or not hypotheses):
        rows.append(
            [
                "Comparison question unavailable (H2)",
                "Policy details unavailable: no H2 record",
                "2",
                "",
                "",
                "",
                "not evaluated",
                _st("not_evaluated", "not evaluated"),
                "H1 inconclusive; no H2 record" if first_state == VerdictState.inconclusive else "no H2 record",
                "",
            ]
        )
    return ('<p>' + term_link('hypothesis', 'Comparison questions and pass rules')
            + ': H2 is reached only after H1 passes. '
            + term_link('mde', 'Minimum detectable effect (MDE)') + '.</p>') + _table(
        "Hypotheses (each state is shown with its reason)",
        ["Hypothesis", "Rule / recorded policy availability", "Step", "One-sided error rate α", "MDE", "Effective sample size (n_eff)", "Interval", "State", "Reason", "Source"],
        rows,
    )


def _guardrails_html(scores: Mapping[str, Any]) -> str:
    rows = []
    for index, g in enumerate(scores["guardrails"]):
        state = g["state"]
        glyph_state = {"pass": "pass", "fail": "fail"}.get(state, "unscored")
        label = state
        if g["metric"] == "p95_ms_per_face":
            value = "semantic null; numeric ms only in timings.json"
        else:
            value = _f(g["value"]) if g["value"] is not None else "null"
        evidence = g.get("evidence") or {}
        reason = evidence.get("reason") if isinstance(evidence, Mapping) else None
        rows.append(
            [
                term_link('guardrail', {
                    'per_cohort_fpir': 'False-match rate by demographic group',
                    'p95_ms_per_face': '95th-percentile time per face',
                }.get(g['metric'], 'Recorded guardrail'))
                + f'<br><small>Protocol identifier: {_e(g["id"])}</small>',
                (term_link('kind-per-cohort-fpir', 'Demographic subgroup FPIR')
                 if g['metric'] == 'per_cohort_fpir' else
                 term_link('kind-p95', 'Amortized native processing cost')
                 if g['metric'] == 'p95_ms_per_face' else 'Definition unavailable')
                + f'<br><small>Technical key: {_e(g["metric"])}</small>',
                _e(g["role"]),
                _st(glyph_state, label),
                _e(value),
                _e(g["timings_sha256"] or "none"),
                _e(reason or "") + '<br><small>Active limit and comparison policy: '
                'inspect recorded evidence; unavailable details are not inferred.</small>',
                _code(_jp("scores.json", "guardrails", index)),
            ]
        )
    return _table(
        "Guardrails (veto or report-only; unscored is not a pass)",
        ["Guardrail / protocol identifier", "Metric / technical key", "Role", "State", "Value", "Timing artifact fingerprint (SHA-256)", "Reason / policy availability", "Source"],
        rows,
    )


def _decision_path_html(scores: Mapping[str, Any]) -> str:
    items = "".join(f"<li>{_e(step)}</li>" for step in scores["decision_path"])
    return (f"<details><summary>Recorded decision path ({len(scores['decision_path'])} steps)</summary>"
            + '<p>' + term_link('hypothesis', 'Hypothesis rules') + '; '
            + term_link('guardrail', 'Guardrail roles and unavailable states') + '.</p>'
            + f"<ol>{items}</ol></details>")


# --- S2 curves ----------------------------------------------------------------------

_LOG_LO = -4.0
_LOG_HI = 0.0


def _curves_svg(scores: Mapping[str, Any]) -> str:
    # Separate panels make tied/zero endpoints and arm scope readable without
    # displacing measurements. Geometry is shared across panels for comparison.
    curves = scores["curves"]
    positive = [p["fpir"] for c in curves for p in c["points"] if p["fpir"] > 0]
    log_lo = min(-4, math.floor(math.log10(min(positive)))) if positive else -4
    width, height = 760, 270
    left, end, top, base, zero_x = 130, 724, 24, 212, 68

    def x_of(fpir: float) -> float:
        return zero_x if fpir == 0 else left + (math.log10(fpir) - log_lo) / -log_lo * (end - left)

    def y_of(fnir: float) -> float:
        return base - fnir * (base - top)

    out = []
    for challenge in (False, True):
        selected = [(i, c) for i, c in enumerate(curves) if _figure_curve_scope(c["leg_key"])[1] == challenge]
        if not selected:
            continue
        scope = "Challenge arm · descriptive only" if challenge else "Probability arm · native curves"
        out.append(f"<h3>{scope}</h3>")
        if challenge:
            out.append(
                "<p>Challenge nonmated effective count: unknown (not recorded). "
                "FPIR resolvability unknown; no probability-arm count is borrowed.</p>"
            )
        for index, curve in selected:
            key, _ = _figure_curve_scope(curve["leg_key"])
            leg = next((leg for leg in scores["legs"] if leg["leg_key"] == key), None)
            pts = curve["points"]
            out.append(f"<p><strong>{_e(curve['leg_key'])}</strong> {_code(_jp('scores.json', 'curves', index))}</p>")
            parts = [
                f'<svg viewBox="0 0 {width} {height}" role="img" '
                f'aria-label="{_e(curve["leg_key"])}: FNIR against FPIR; {scope}">'
            ]
            if not challenge:
                neff, source = _figure_nonmated_count(scores, leg)
                if neff is None:
                    status = "Native nonmated effective count unknown; FPIR resolvability unknown."
                else:
                    limit = 3 / neff if neff > 0 else math.inf
                    status = (
                        f"Native nonmated n_eff = {neff}; unresolvable: FPIR below "
                        f"3/n_nonmated_eff = {limit:.6g}. No FNIR inference in this region."
                    )
                    x_limit = end if limit >= 1 else max(left, x_of(limit))
                    parts.append(
                        f'<rect class="unresolvable" x="{left}" y="{top}" '
                        f'width="{x_limit - left:.2f}" height="{base - top}"/>'
                    )
                out.append(f'<p class="note">{_e(status)} {_code(source) if source else ""}</p>')
            parts.append(f'<line class="axis" x1="{left}" x2="{end}" y1="{base}" y2="{base}"/>')
            parts.append(f'<line class="axis" x1="{left}" x2="{left}" y1="{top}" y2="{base}"/>')
            # Zero has its own gutter: never a positive 1e-4 observation, and no
            # invented line segment spans the discontinuity into log space.
            parts.append(f'<text class="lbl" x="{zero_x}" y="{base + 18}" text-anchor="middle">0 (separate)</text>')
            for tick in (0.0, 0.5, 1.0):
                parts.append(
                    f'<text class="lbl" x="{left - 7}" y="{y_of(tick) + 4}" text-anchor="end">{tick:.1f}</text>'
                )
            for ref in (0.001, 0.01, 0.05):
                x = x_of(ref)
                parts.append(f'<line class="ref" data-fpir="{ref}" x1="{x:.2f}" x2="{x:.2f}" y1="{top}" y2="{base}"/>')
                parts.append(f'<text class="lbl" x="{x:.2f}" y="{top - 8}" text-anchor="middle">FPIR {ref}</text>')
            for exp in sorted({log_lo, -3, -2, -1, 0}):
                parts.append(
                    f'<text class="lbl" x="{x_of(10.0**exp):.2f}" y="{base + 18}" text-anchor="middle">1e{exp}</text>'
                )
            parts.append(
                f'<text class="lbl" x="{(left + end) / 2}" y="{height - 6}" '
                'text-anchor="middle">FPIR (positive values: log scale)</text>'
            )
            parts.append('<text class="lbl" x="12" y="124" transform="rotate(-90 12 124)">FNIR</text>')
            segment = []
            for point_index, p in enumerate(pts):
                if p["fnir"] is None or p["fpir"] == 0:
                    if segment:
                        parts.append(
                            f'<polyline class="series s{index % 4}" style="fill:none" points="{" ".join(segment)}"/>'
                        )
                    segment = []
                if p["fnir"] is None:
                    continue
                x, y = x_of(p["fpir"]), y_of(p["fnir"])
                if p["fpir"] > 0:
                    segment.append(f"{x:.2f},{y:.2f}")
                parts.append(
                    f'<circle class="s{index % 4}" fill="currentColor" r="2.5" '
                    f'data-point="{point_index}" data-fpir="{p["fpir"]}" '
                    f'cx="{x:.2f}" cy="{y:.2f}"><title>'
                    f"{_e(curve['leg_key'])}: threshold {_e(p['threshold'])}, "
                    f"FPIR {p['fpir']}, FNIR {p['fnir']}</title></circle>"
                )
            if segment:
                parts.append(f'<polyline class="series s{index % 4}" style="fill:none" points="{" ".join(segment)}"/>')
            matches = _figure_tau_points(curve, leg)
            for point_index, p in matches:
                if p["fnir"] is None:
                    continue
                x, y = x_of(p["fpir"]), y_of(p["fnir"])
                parts.append(
                    f'<polygon class="tau" style="fill:var(--bg);stroke-dasharray:none" stroke="currentColor" stroke-width="2" '
                    f'data-threshold="{p["threshold"]}" data-point="{point_index}" '
                    f'points="{x:.2f},{y - 6:.2f} {x + 6:.2f},{y:.2f} '
                    f'{x:.2f},{y + 6:.2f} {x - 6:.2f},{y:.2f}">'
                    f"<title>Frozen τ = {_e(p['threshold'])}</title></polygon>"
                )
            tau = leg.get("tau", {}) if leg else {}
            if matches and any(p["fnir"] is not None for _, p in matches):
                marker_status = f"◇ frozen τ = {tau['data']['value']} (exact recorded point)"
            elif tau.get("status") != "available":
                marker_status = f"τ unavailable: {tau.get('reason') or 'native calibration not recorded'}"
            elif matches:
                marker_status = "τ point recorded; FNIR unavailable, marker cannot be positioned."
            else:
                marker_status = "τ marker unavailable: no exact recorded curve point at frozen τ."
            parts.append("</svg>")
            out.extend(parts)
            out.append(
                f'<p class="note">{_e(marker_status)} Observed points are descriptive; '
                "zero FPIR is separate from the positive log axis.</p>"
            )
    return "\n".join(out)


def _figure_curve_scope(key: str) -> tuple[str, bool]:
    """Use the actual S3 descriptive-key wire, never infer scope from counts."""
    suffix = "::sampling=challenge"
    return (key[: -len(suffix)], True) if key.endswith(suffix) else (key, False)


def _figure_nonmated_count(scores: Mapping[str, Any], leg: Mapping[str, Any] | None) -> tuple[float | None, str | None]:
    if leg is not None:
        wrapper = leg["operating_point"]["fpir"]
        if wrapper.get("status") == "available" and isinstance(wrapper.get("data"), Mapping):
            value = wrapper["data"].get("n_nonmated_eff")
            if value is not None:
                index = next(i for i, item in enumerate(scores["legs"]) if item["leg_key"] == leg["leg_key"])
                return value, _jp("scores.json", "legs", index, "operating_point", "fpir", "data", "n_nonmated_eff")
    return scores.get("n_nonmated_eff"), _jp("scores.json", "n_nonmated_eff") if "n_nonmated_eff" in scores else None


def _figure_tau_points(curve: Mapping[str, Any], leg: Mapping[str, Any] | None) -> list[tuple[int, Mapping[str, Any]]]:
    tau = leg.get("tau", {}) if leg else {}
    if tau.get("status") != "available":
        return []
    # JSON preserves these numeric values: exact equality, no gate epsilon and
    # no nearest-point interpolation. Keep all recorded ties, without refitting.
    return [(i, p) for i, p in enumerate(curve["points"]) if p["threshold"] == tau["data"]["value"]]


def _tau_markers(scores: Mapping[str, Any]) -> str:
    rows = []
    seen = set()
    for index, curve in enumerate(scores["curves"]):
        key, challenge = _figure_curve_scope(curve["leg_key"])
        seen.add(key)
        leg = next((leg for leg in scores["legs"] if leg["leg_key"] == key), None)
        tau = leg.get("tau", {}) if leg else {}
        scope = "challenge · descriptive only; effective count unknown" if challenge else "probability · native"
        matches = _figure_tau_points(curve, leg)
        if not matches:
            status = (
                f"τ unavailable: {tau.get('reason') or 'not recorded'}"
                if tau.get("status") != "available"
                else f"τ = {tau['data']['value']}; no exact recorded curve point"
            )
            rows.append(
                [
                    _e(curve["leg_key"]),
                    _e(scope),
                    _e(status),
                    "unknown",
                    "unknown",
                    _code(_jp("scores.json", "curves", index)),
                ]
            )
        for point_index, match in matches:
            rows.append(
                [
                    _e(curve["leg_key"]),
                    _e(scope),
                    _e(f"τ = {tau['data']['value']} (frozen on calibration folds)"),
                    _e(match["fpir"]),
                    _e(match["fnir"]) if match["fnir"] is not None else "unavailable",
                    _code(_jp("scores.json", "curves", index, "points", point_index)),
                ]
            )
    for index, leg in enumerate(scores["legs"]):
        if leg["leg_key"] not in seen:
            rows.append(
                [
                    _e(leg["leg_key"]),
                    "probability · native",
                    "curve unavailable",
                    "unknown",
                    "unknown",
                    _code(_jp("scores.json", "legs", index, "tau")),
                ]
            )
    return _table(
        "At-τ readout (existing curve points; descriptive, not refit)",
        ["Leg", "Scope", "τ", "FPIR", "FNIR", "JSON path"],
        rows,
    )


def _curves_html(scores: Mapping[str, Any], *, unratified: bool) -> str:
    note = f"<p>{_st('unratified', _UNRATIFIED)}: numbers only, no winner.</p>" if unratified else ""
    return (
        f'{note}<div class="chart">{_curves_svg(scores)}</div>\n'
        '<p class="note">FPIR reference lines at 0.001, 0.01 and 0.05; '
        'the τ marker is the frozen threshold.</p>\n'
        + _tau_markers(scores)
        + '<button type="button" id="explore-tau" disabled>↗ Explore τ</button>'
        '<p id="explore-status" class="note">○ Exploration unavailable: requires a development '
        'frame explicitly unsealed in the inline source.</p>'
        '<div id="tau-explorer" hidden><p class="mode-banner" role="status">'
        '○ Exploring recorded descriptive points. Nothing is saved. Frozen values remain above.</p>'
        '<label>Leg <select id="explore-leg"></select></label> '
        '<label>Recorded point <select id="explore-point"></select></label>'
        '<p id="explore-readout" aria-live="polite"></p>'
        '<button type="button" id="exit-explore">↩ Exit exploration (Esc)</button></div>'
    )


# --- S3 pair cells -------------------------------------------------------------------


def _cells_html(
    scores: Mapping[str, Any],
    *,
    withheld_reason: str | None = None,
    withheld_cells: Mapping[int, str] | None = None,
) -> str:
    floor = int(scores["cell_floor_n_independent"])
    rows = []
    for index, cell in enumerate(scores["cells"]):
        reason = withheld_reason or (withheld_cells or {}).get(index)
        path = _code(_jp("scores.json", "cells", index))
        show = not reason and cell["scored"] and int(cell["n_psu"]) >= floor
        if reason:
            status = _st("not_scored", f"not scored: {reason}")
        elif int(cell["n_units"]) == 0:
            status = _st("collect", "no data → collect")
        elif not cell["scored"] or int(cell["n_psu"]) < floor:
            status = _st("not_scored", cell.get("reason") or f"not scored (n_psu {cell['n_psu']}; floor {floor})")
        else:
            status = f"FNIR {_f(cell['fnir'])}"
        interval = _interval_text(cell["interval"]) if show and cell.get("interval") else "null"
        rows.append(
            [
                _e(cell["leg_key"]),
                _e(f"{cell['query_occluder']} / {cell['enrolled_occluder']}"),
                _e(cell["data_origin"]),
                _f(cell["n_units"], 0),
                _f(cell["n_identities"], 0),
                _f(cell["n_psu"], 0),
                _f(cell["n_eff"]),
                status,
                _e(interval),
                path,
            ]
        )
    return ('<p>' + term_link('occlusion-cell', 'Occlusion cells and cell origin')
            + ': synthetic cell origin describes generated cell data; it does not establish '
            'that the whole run is a software fixture. '
            + term_link('psu', 'Independent sampling units (PSUs)') + '; '
            + term_link('neff', 'Effective sample size (n_eff)') + '.</p>') + _table(
        f"Query by enrolled occlusion subgroup (below {floor} independent sampling units: not scored)",
        [
            "Leg",
            "query / enrolled",
            "origin",
            "units",
            "identities",
            "PSUs",
            "n_eff",
            "FNIR at τ",
            "interval",
            "JSON path",
        ],
        rows,
    )


# --- S4 stages ------------------------------------------------------------------------


def _stages_html(scores: Mapping[str, Any]) -> str:
    stage_rank = {str(s): i for i, s in enumerate(_STAGE_ORDER)}
    reported = scores.get("waterfall") or []
    for index, row in enumerate(reported):
        if row["leg_key"].startswith(_FUSED_PREFIX) and row["stage"] == SearchStage.unaligned:
            raise FrameContractError(f"waterfall[{index}]: the fused leg {row['leg_key']} writes no unaligned stage")
    # INT-22 / VIZ-23: interpret only the reported S3 ledger, with its exact pool
    # and evidence path. S3 emits sparse counts for available mated native test
    # searches; challenge counts have their own sampling-qualified leg label.
    scopes = {(leg["leg_key"], "native") for leg in scores.get("legs", [])}
    scopes.update((row["leg_key"], row["arm"]) for row in reported)
    summary_rows = []
    for leg, arm in sorted(scopes):
        rows = [(index, row) for index, row in enumerate(reported)
                if (row["leg_key"], row["arm"]) == (leg, arm)]
        counts = {}
        for _, row in rows:
            counts[row["stage"]] = counts.get(row["stage"], 0) + row["count"]
        total = sum(counts.values())
        failures = {stage: count for stage, count in counts.items()
                    if stage in _FAILURE_STAGES and count > 0}
        if failures:
            peak = max(failures.values())
            dominant = sorted((stage for stage, count in failures.items() if count == peak),
                              key=lambda stage: stage_rank[stage])
            failure_total = sum(failures.values())
            if len(dominant) == 1:
                state = (f"Dominant reported upstream stage: {dominant[0]} "
                         f"({peak} of {failure_total} reported upstream failures)")
            else:
                state = (f"Tied dominant reported upstream stages: {', '.join(dominant)} "
                         f"({peak} each of {failure_total} reported upstream failures)")
        elif total > 0 and counts.get(SearchStage.embedded, 0) == total:
            state = ("No reported upstream failure among these reported rows; "
                     f"all {total} records reached embedded")
        elif total == 0:
            state = "Unavailable: no positive-count reported waterfall evidence"
        else:
            state = "Unavailable: reported waterfall does not establish an upstream-failure summary"
        pool = f"{total} reported waterfall records" if total > 0 else "unavailable"
        sources = " ".join(_code(_jp("scores.json", "waterfall", index)) for index, _ in rows)
        if not sources:
            sources = _code(_jp("scores.json", "waterfall"))
        summary_rows.append(
            f"<p><strong>{_e(leg)} · {_e(arm)}</strong><br>"
            f"<strong>{_e(state)}</strong><br>Count pool: {_e(pool)}. {sources}</p>"
        )
    summary = (
        "<h3>Reported upstream stages</h3>"
        "<p>Scope: reported waterfall records for each leg and arm below. The S3 producer counts "
        "available, mated native test-fold searches; probability and explicitly labeled challenge "
        "scopes stay separate. Counts sum only those records, not the full GT inventory. "
        "Missing or empty evidence is unavailable. Embedded means the embedding stage was reached; "
        "it does not establish accepted or correct identity. "
        "Unavailable arm counts remain separate in joint gaps.</p>"
        + "\n".join(summary_rows)
    )
    if not summary_rows:
        summary += ("<p><strong>Unavailable: no positive-count reported waterfall evidence</strong> "
                    + _code(_jp("scores.json", "waterfall")) + "</p>")
    unavailable = {(g["leg_key"], g["arm"]): g["unavailable_counts"] for g in scores["joint_gaps"]}
    wrows = []
    for index, row in sorted(
        enumerate(reported),
        key=lambda item: (item[1]["leg_key"], item[1]["arm"], stage_rank.get(item[1]["stage"], 99), item[0]),
    ):
        wrows.append(
            [
                _e(row["leg_key"]),
                _e(row["arm"]),
                _e(row["stage"]),
                _f(row["count"], 0),
                _code(_jp("scores.json", "waterfall", index)),
            ]
        )
    waterfall = _table(
        "Stage waterfall (SearchStage rows; the fused leg has no unaligned row)",
        ["Leg", "Arm", "Stage", "Count", "JSON path"],
        wrows,
    )
    grows = []
    for index, gap in enumerate(scores["joint_gaps"]):
        leg = gap["leg_key"]
        availability = unavailable.get((leg, gap["arm"]), {"native": 0, "attribution": 0})
        arm_col = (
            f"attribution unavailable: {availability['attribution']}; native unavailable: {availability['native']}"
        )
        if gap["scored"]:
            delta = _f(gap["delta"])
            interval = _interval_text(gap["interval"])
        elif leg.startswith(_FUSED_PREFIX):
            delta = "no arm deltas (judge leg)"
            interval = "null"
        else:
            delta = _st("not_evaluated", f"not evaluated: {gap['reason']}")
            interval = "null"
        grows.append(
            [
                _e(leg),
                _e(gap["arm"]),
                _f(gap["n_pairs"], 0),
                delta,
                _e(interval),
                _e(arm_col),
                _code(_jp("scores.json", "joint_gaps", index)),
            ]
        )
    gaps = _table(
        "Joint gaps against native; unavailable arm counts are a column, never a stage",
        ["Leg", "Arm", "pairs", "Δ vs native", "interval", "arm_availability", "JSON path"],
        grows,
    )
    return summary + "\n" + waterfall + "\n" + gaps


# --- S5 failures and pool ----------------------------------------------------------


def _pool(frame: Mapping[str, Any] | None, rows: Sequence[Mapping[str, Any]], *, include_crops: bool) -> dict[str, Any]:
    faces = list(frame["faces"]) if frame is not None else []
    images = list(frame["images"]) if frame is not None else []
    exhaustive = frame is not None and frame.get("exhaustive") is True
    eligible = [r for r in rows if r["default_visible"]]
    eligible_faces = {r["face_id"] for r in eligible}
    eligible_images = {r["image_id"] for r in eligible}
    native = [
        r for r in rows if r["arm"] == "native" and r["fold_role"] == "test" and r["sampling_arm"] == "probability"
    ]
    legacy = any(r["outcome_reason"] == "legacy_face_outcomes_unavailable" for r in rows)
    # Rows carry the result of the run-local S7 join. Rechecking a bare annotation
    # here would discard that context, including when the UI asks for a subpool.
    by_face = {r["face_id"]: r for r in rows}
    reasons = sorted({
        reason
        for face in faces
        for qualified, reason in [
            (by_face[face["face_id"]]["qualified"], by_face[face["face_id"]]["qualification_reason"])
            if face["face_id"] in by_face else _binding_qualification(face, frame)
        ]
        if not qualified
    })
    psus = {r["image_id"]: r["psu_id"] for r in frame["psu_map"]} if frame else {}
    folds = {r["psu_id"]: r["fold"] for r in frame["folds"]} if frame else {}
    roles = {r["fold"]: r["role"] for r in frame["fold_roles"]} if frame else {}
    primary_images = {
        i["image_id"]
        for i in images
        if i["sampling_arm"] == "probability" and roles[folds[psus[i["image_id"]]]] == "test"
    }
    scored_native = [r for r in native if r["outcome_available"]]
    classification = (
        "unavailable"
        if legacy or not scored_native
        else ("partial" if len(scored_native) < len(native) else "available")
    )
    return {
        # Exhaustive FRAME inventory establishes the image/GT selection pool.
        # Identity and annotation restrictions govern row eligibility separately;
        # disclosure of either inventory or selection does not establish lack of bias.
        "status": "established" if exhaustive else "not established",
        "reason": "; ".join(reasons) if reasons else (None if exhaustive else "exhaustive GT unestablished"),
        "eligibility_restrictions": reasons,
        "overall_images": len(images) if frame is not None else None,
        "overall_gt_faces": len(faces) if frame is not None else None,
        "named_faces": sum(f["identity_status"] == "named" for f in faces),
        "unknown_faces": sum(f["identity_status"] == "unknown" for f in faces),
        "unresolved_identity_faces": sum(f["identity_status"] == "unresolved" for f in faces),
        "inventory_rows": len(rows),
        "inventory_faces": len({r["face_id"] for r in rows}),
        "inventory_images": len({r["image_id"] for r in rows}),
        "eligible_rows": len(eligible),
        "eligible_faces": len(eligible_faces),
        "eligible_images": len(eligible_images),
        "selected_faces": len(eligible_faces),
        "selected_images": len(eligible_images),
        "selected_rows": len(eligible),
        "shown_rows": len(eligible),
        "omitted_rows": 0,
        "outside_default_scope_rows": len(rows) - len(eligible),
        "scope_counts": {
            name: len(
                {
                    r["face_id"]
                    for r in native
                    if (r["identity_status"] == "unresolved" if name == "unresolved" else r["mated"] is value)
                }
            )
            for name, value in (("mated", True), ("nonmated", False), ("unresolved", None))
        },
        "membership_unavailable_faces": len(
            {r["face_id"] for r in native if r["mated"] is None and r["identity_status"] != "unresolved"}
        ),
        "fixed_background_source_units": len(images) if exhaustive else None,
        "primary_background_source_units": len(primary_images) if exhaustive else None,
        "scope_counts_by_leg": {
            leg: {
                name: len(
                    {
                        r["face_id"]
                        for r in native
                        if r["leg_key"] == leg
                        and (r["identity_status"] == "unresolved" if name == "unresolved" else r["mated"] is value)
                    }
                )
                for name, value in (("mated", True), ("nonmated", False), ("unresolved", None))
            }
            for leg in sorted({r["leg_key"] for r in native})
        },
        "nonmated_gt_source_units_by_leg": {
            leg: len({r["face_id"] for r in native if r["leg_key"] == leg and r["mated"] is False and r["qualified"]})
            for leg in sorted({r["leg_key"] for r in native})
        },
        "classification_status": classification,
        "classification_reason": "legacy_face_outcomes_unavailable"
        if legacy
        else (
            "no_primary_test_outcomes_available"
            if not scored_native
            else ("some_primary_test_outcomes_unavailable" if classification == "partial" else None)
        ),
        "unclassified_rows": sum(not r["outcome_available"] and r["fold_role"] == "test" for r in rows),
        "fit_metadata_rows": sum(r["fold_role"] == "fit" for r in rows),
        "crop_images_shown": len({r["crop_ref"] for r in eligible if r.get("crop_data_uri")}) if include_crops else 0,
        "filters": {
            "sampling_arm": "probability",
            "fold_role": "test",
            "arm": "native",
            "qualified": True,
            "is_failure": True,
        },
        "sort": "image_id, face_id, leg_key, arm, fold",
        "limit": None,
        "offset": 0,
    }


def _binding_index(rows: Sequence[Mapping[str, Any]], key: str, label: str) -> dict[Any, Mapping[str, Any]]:
    result = {r[key]: r for r in rows}
    if len(result) != len(rows):
        raise FrameContractError(f"duplicate {label} {key}")
    return result


def _binding_frame(frame: Mapping[str, Any] | None) -> tuple[dict, dict, dict, dict, dict]:
    if frame is None:
        return {}, {}, {}, {}, {}
    faces = _binding_index(frame["faces"], "face_id", "frame")
    images = _binding_index(frame["images"], "image_id", "frame")
    psus = {k: r["psu_id"] for k, r in _binding_index(frame["psu_map"], "image_id", "PSU").items()}
    folds = {k: r["fold"] for k, r in _binding_index(frame["folds"], "psu_id", "fold").items()}
    roles = {k: r["role"] for k, r in _binding_index(frame["fold_roles"], "fold", "role").items()}
    if set(psus) != set(images) or set(folds) != set(psus.values()):
        raise FrameContractError("frame image/PSU/fold coverage mismatch")
    for face in faces.values():
        image = face["image_id"]
        if image not in images or folds[psus[image]] not in roles:
            raise FrameContractError("frame GT image/fold foreign key mismatch")
        if (face["identity_status"] == "named") != (face["identity_id"] is not None):
            raise FrameContractError("frame GT identity/status mismatch")
    identities = {
        k: r["fold"] for k, r in _binding_index(frame["identity_folds"], "identity_id", "identity fold").items()
    }
    named = {face["identity_id"] for face in faces.values() if face["identity_status"] == "named"}
    if set(identities) != named or any(
        identities[face["identity_id"]] != folds[psus[face["image_id"]]]
        for face in faces.values()
        if face["identity_status"] == "named"
    ):
        raise FrameContractError("frame named identity fold coverage mismatch")
    if frame["sampling_arm_counts"] != {
        arm: sum(i["sampling_arm"] == arm for i in images.values()) for arm in ("probability", "challenge")
    }:
        raise FrameContractError("frame sampling arm counts mismatch")
    return faces, images, psus, folds, roles


def _binding_qualification(
    face: Mapping[str, Any],
    frame: Mapping[str, Any],
    *,
    qualification: Mapping[str, tuple[bool, str | None]] | None = None,
) -> tuple[bool, str | None]:
    if frame.get("exhaustive") is not True:
        return False, "exhaustive GT unestablished; analytics withheld"
    if face["identity_status"] == "unresolved":
        return False, "unresolved_identity; analytics withheld"
    if face["annotation"]["annotation_tier"] == "a":
        return (qualification or {}).get(
            face["face_id"],
            (False, "S7 QC/observation applicability unavailable in run-local artifacts; analytics withheld"),
        )
    return True, None


def _binding_label_evidence(
    run: Path,
    frame: Mapping[str, Any] | None,
    descriptor: Any,
    *,
    frame_sha256: str | None,
    files: dict[str, Any],
    inputs: dict[str, str],
) -> dict[str, tuple[bool, str | None]]:
    """Requalify frozen S7 bytes, then join actual rows to canonical FRAME units.

    This consumer never upgrades cached booleans or an observation reference to
    evidence. S7 owns the proof closure and the production qualification gates.
    """
    if descriptor is None:
        return {}
    if (
        frame is None
        or not isinstance(descriptor, Mapping)
        or set(descriptor) != {"schema", "frame_sha256", "export_path", "queue_path", "gold_path", "files"}
        or descriptor.get("schema") != "firbench-label-evidence/v1"
        or descriptor.get("frame_sha256") != frame_sha256
        or not isinstance(descriptor.get("files"), list)
        or not descriptor["files"]
    ):
        raise FrameContractError("S7 label evidence descriptor/frame SHA invalid")
    snapshots = {}
    for item in descriptor["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise FrameContractError("S7 label evidence file declaration invalid")
        name = item["path"]
        if (
            not isinstance(name, str)
            or not name.startswith("label-evidence/")
            or Path(name).as_posix() != name
            or name in snapshots
        ):
            raise FrameContractError("S7 label evidence file path invalid/ambiguous")
        try:
            raw = _binding_file(run, name).read_bytes()
        except OSError as exc:
            raise FrameContractError(f"S7 label evidence unavailable: {name}") from exc
        if _sha256_bytes(raw) != item["sha256"]:
            raise FrameContractError(f"S7 label evidence SHA mismatch: {name}")
        snapshots[name] = raw
    if list(snapshots) != sorted(snapshots) or any(
        descriptor.get(key) not in snapshots for key in ("export_path", "queue_path", "gold_path")
    ):
        raise FrameContractError("S7 label evidence roots/order invalid")

    from scripts.eval_harness import fir_occ_labels as s7

    requalify = getattr(s7, "requalify_label_evidence", None)
    if requalify is None:
        # The source snapshot can precede the concurrent S7 committed overlay.
        # No local substitute can confer eligibility in that state.
        rows = ()
        unavailable = "S7 frozen requalify_label_evidence unavailable; actual join pending; analytics withheld"
    else:
        rows = requalify(run, descriptor, frame_sha256=frame_sha256)
        s7.require_real_analysis_rows(rows)
        unavailable = "S7 qualified row/FRAME one-to-one annotation join unavailable; analytics withheld"
    for name, raw in snapshots.items():
        try:
            unchanged = _binding_file(run, name).read_bytes() == raw
        except OSError as exc:
            raise FrameContractError(f"S7 label evidence changed/unavailable: {name}") from exc
        if not unchanged:
            raise FrameContractError(f"S7 label evidence changed during qualification: {name}")
        files[name] = _binding_json(raw, name)
        inputs[name] = _sha256_bytes(raw)

    from scripts.eval_harness import firbench_frames as frames

    def annotation_key(annotation: Mapping[str, Any]) -> str:
        normalized = frames._optional_annotation(annotation, "S7/FRAME annotation").to_json()
        return json.dumps(normalized, sort_keys=True)

    def key(image_id: str, sha: str, row: Mapping[str, Any]) -> tuple:
        return image_id, sha, tuple(row["box"]), row["identity_status"], annotation_key(row["annotation"])

    candidates: dict[tuple, int] = {}
    for row in rows:
        if row.get("response") == "answered" and row.get("box") is not None:
            match = key(row["image_id"], row["image_sha256"], row)
            candidates[match] = candidates.get(match, 0) + 1
    images = {image["image_id"]: image for image in frame["images"]}
    matches = {}
    for face in frame["faces"]:
        if face["annotation"]["annotation_tier"] == "a":
            match = key(face["image_id"], images[face["image_id"]]["sha256"], face)
            matches.setdefault(match, []).append(face["face_id"])
    return {
        face_id: (True, None)
        if candidates.get(match) == 1
        and len(face_ids) == 1
        and images[match[0]].get("synthetic_parent_id") is None
        else (False, unavailable)
        for match, face_ids in matches.items()
        for face_id in face_ids
    }


def _binding_analytic_withholding(
    frame: Mapping[str, Any] | None,
    rows: Sequence[Mapping[str, Any]],
    scores: Mapping[str, Any],
    *,
    qualification: Mapping[str, tuple[bool, str | None]],
) -> tuple[str | None, dict[int, str]]:
    """Scope missing-label display gates without changing any producer metric."""
    if frame is None:
        return None, {}
    faces, images, psus, folds, roles = _binding_frame(frame)
    reasons = {}
    for face_id, face in faces.items():
        # Unresolved identities belong to inventory, never identity estimands.
        if (
            face["identity_status"] == "unresolved"
            or images[face["image_id"]]["sampling_arm"] != "probability"
            or roles[folds[psus[face["image_id"]]]] != "test"
        ):
            continue
        qualified, reason = _binding_qualification(face, frame, qualification=qualification)
        if not qualified:
            reasons[face_id] = reason
    if frame.get("exhaustive") is not True:
        reason = "exhaustive GT unestablished; analytics withheld"
        return reason, dict.fromkeys(range(len(scores["cells"])), reason)
    cells = {}
    for index, cell in enumerate(scores["cells"]):
        affected = {
            reasons[row["face_id"]]
            for row in rows
            if row["face_id"] in reasons
            and row["arm"] == "native"
            and row["mated"] is not False
            and row["leg_key"] == cell["leg_key"]
            and row["cell"] == f"{cell['query_occluder']} / {cell['enrolled_occluder']}"
        }
        if affected:
            cells[index] = "; ".join(sorted(affected))
    return "; ".join(sorted(set(reasons.values()))) or None, cells


def _binding_leg_scope(key: str) -> tuple[str, str, str, str, str]:
    """Decode only the frozen LegId wire; a key names exactly one arm/space."""
    from scripts.eval_harness.firbench_contract import Arm, LegId, LegKind

    if not isinstance(key, str) or Path(key).name != key or key in {".", ".."}:
        raise FrameContractError("unsafe declared leg_key")
    parts = key.split("__")
    if len(parts) != 5 or not parts[3].startswith("cv") or not parts[4].startswith("ort"):
        raise FrameContractError("malformed declared leg_key")
    kind, arm, space, cv, ort = parts
    try:
        decoded = LegId(LegKind(kind), Arm(arm), space, cv[2:], ort[3:])
    except ValueError as exc:
        raise FrameContractError("malformed declared leg_key") from exc
    if decoded.key() != key:
        raise FrameContractError("declared leg_key context mismatch")
    return kind, arm, space, cv, ort


def _binding_scopes(
    scores: Mapping[str, Any], manifest: Mapping[str, Any] | None
) -> dict[str, tuple[str | None, ...]]:
    """Keep native scored summaries separate from the complete arm inventory.

    Pre-outcome files could declare multiple arms inside native-key artifacts.
    Retain that historical metadata wire only when outcomes are absent; modern
    producers declare the complete typed kind/arm registry before searching.
    """
    from scripts.eval_harness.firbench_contract import Arm, LegKind

    block = (manifest or {}).get("firbench", {})
    scored = [row["leg_key"] for row in scores.get("legs", [])]
    declared = block.get("leg_keys", scored)
    if (
        not isinstance(declared, list) or not declared
        or any(not isinstance(key, str) for key in declared)
        or len(set(declared)) != len(declared) or len(set(scored)) != len(scored)
    ):
        raise FrameContractError("duplicate or missing declared/scores leg scope")
    typed = {key: _binding_leg_scope(key) for key in declared}
    native = {key for key, parts in typed.items() if parts[1] == "native"}
    if set(scored) != native:
        raise FrameContractError("manifest/scores declared native leg scope mismatch")
    arms = block.get("arms")
    modern = "face_outcomes" in scores
    if modern and "leg_keys" not in block:
        raise FrameContractError("face_outcomes requires actual declared leg scope")
    if arms is None and not modern:
        return {key: (parts[1],) for key, parts in typed.items()}
    if (
        not isinstance(arms, list) or not arms
        or any(arm not in {a.value for a in Arm} for arm in arms)
        or len(set(arms)) != len(arms) or "native" not in arms
    ):
        raise FrameContractError("inventory requires actual declared arm scope")
    pairs = [(parts[0], parts[1]) for parts in typed.values()]
    if len(set(pairs)) != len(pairs):
        raise FrameContractError("duplicate declared leg kind/arm context")
    kinds = {parts[0] for parts in typed.values()}
    if "legs" in block and (
        not isinstance(block["legs"], list)
        or any(kind not in {k.value for k in LegKind} for kind in block["legs"])
        or len(set(block["legs"])) != len(block["legs"])
        or set(block["legs"]) != kinds
    ):
        raise FrameContractError("declared leg kind scope mismatch")
    if set(pairs) != {(kind, arm) for kind in kinds for arm in arms}:
        if not modern and set(declared) == native and "legs" not in block:
            return {key: tuple(arms) for key in declared}
        raise FrameContractError("declared leg/arm inventory scope mismatch")
    for parts in typed.values():
        matching_native = "__".join((parts[0], "native", *parts[2:]))
        if matching_native not in native:
            raise FrameContractError("attribution/native leg space or runtime context mismatch")
    return {key: (parts[1],) for key, parts in typed.items()}


def _binding_registry(
    manifest: Mapping[str, Any] | None, frame: Mapping[str, Any] | None, legs: set[str], *, required: bool
) -> dict[tuple[str, int], Mapping[str, Any]]:
    rows = (manifest or {}).get("firbench", {}).get("gallery_membership")
    if rows is None and not required:
        return {}
    if not isinstance(rows, list) or frame is None:
        raise FrameContractError("declared gallery membership unavailable for outcome provenance")
    roles = {r["fold"] for r in frame["fold_roles"]}
    query_folds = {r["identity_id"]: r["fold"] for r in frame["identity_folds"]}
    registry, shared = {}, {}
    full_folds = None
    for row in rows:
        if (
            not isinstance(row, dict)
            or not {"leg_key", "fold", "gallery_sha256", "enrolled_identity_ids", "identity_folds"} <= row.keys()
        ):
            raise FrameContractError("gallery membership required fields unavailable")
        key, fold = row["leg_key"], row["fold"]
        if key not in legs or type(fold) is not int or fold not in roles or (key, fold) in registry:
            raise FrameContractError("gallery membership duplicate/foreign leg/fold")
        ids, provenance, sha = row["enrolled_identity_ids"], row["identity_folds"], row["gallery_sha256"]
        if (
            not isinstance(ids, list)
            or any(not isinstance(i, str) or not i for i in ids)
            or len(set(ids)) != len(ids)
            or not isinstance(provenance, dict)
            or any(not isinstance(i, str) or type(f) is not int or f not in roles for i, f in provenance.items())
            or not set(ids) <= provenance.keys()
            or any(provenance.get(i) != f for i, f in query_folds.items())
        ):
            raise FrameContractError("gallery identity/fold provenance contradicts FRAME")
        if full_folds is not None and provenance != full_folds:
            raise FrameContractError("gallery identity fold provenance differs across declarations")
        full_folds = provenance
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise FrameContractError("gallery SHA required")
        if fold in shared and set(ids) != shared[fold]:
            raise FrameContractError("native legs must share gallery membership")
        shared[fold] = set(ids)
        registry[key, fold] = row
    if set(registry) != {(leg, fold) for leg in legs for fold in roles}:
        raise FrameContractError("gallery membership must cover every declared leg/fold")
    return registry


def _binding_membership(
    manifest: Mapping[str, Any] | None, leg: str, fold: int, face: Mapping[str, Any]
) -> bool | None:
    if face["identity_status"] == "unresolved":
        return None
    if face["identity_status"] == "unknown":
        return False
    registry = (manifest or {}).get("firbench", {}).get("gallery_membership", [])
    matches = [r for r in registry if r["leg_key"] == leg and r["fold"] == fold]
    if len(matches) != 1:
        return None
    return face["identity_id"] in matches[0]["enrolled_identity_ids"]


def _failures_rows(
    searches: Sequence[Mapping[str, Any]],
    frame: Mapping[str, Any] | None,
    *,
    scores: Mapping[str, Any] | None = None,
    manifest: Mapping[str, Any] | None = None,
    qualification: Mapping[str, tuple[bool, str | None]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    faces, images, psus, folds, roles = _binding_frame(frame)
    scopes = _binding_scopes(scores or {}, manifest)
    legs = set(scopes)
    block = (manifest or {}).get("firbench", {})
    registry = _binding_registry(manifest, frame, legs, required="face_outcomes" in (scores or {}))
    search_map = {}
    seen = set()
    background = 0
    for row in searches:
        leg = row["leg_key"]
        if legs and leg not in legs:
            raise FrameContractError("search leg outside declared inventory scope")
        if row["arm"] not in scopes[leg]:
            raise FrameContractError("search arm outside declared scope")
        key = (leg, row["arm"], row["fold"], row["face_id"])
        if key in seen:
            raise FrameContractError("duplicate GT search key or detector search key")
        seen.add(key)
        if len(scopes[leg]) == 1:
            fused = _binding_leg_scope(leg)[0] == "insightface"
            fused_arm = fused and row["arm"] != "native"
            if fused_arm != (row["arm_availability"] == "unavailable_fused") or (
                fused_arm and (row["stage_reached"] is not None or row["top_k"])
            ):
                raise FrameContractError("search unavailable fused arm status contradicts declared leg")
            if row["arm_availability"] == "available" and row["stage_reached"] in (None, "unavailable"):
                raise FrameContractError("available search requires actual stage")
            if row["arm_availability"] == "unavailable" and (
                row["stage_reached"] != "unavailable" or row["top_k"]
            ):
                raise FrameContractError("unavailable search status contradicts stage/results")
        image = row["image_id"]
        if frame is None:
            raise FrameContractError("search provenance requires frame.json")
        if image not in images or row["psu_id"] != psus[image] or row["fold"] != folds[psus[image]]:
            raise FrameContractError("search image/PSU/fold contradicts FRAME")
        if row["fold_role"] != roles[row["fold"]] or row["sampling_arm"] != images[image]["sampling_arm"]:
            raise FrameContractError("search fold role/sampling arm contradicts FRAME")
        declaration = registry.get((leg, row["fold"]))
        if declaration is not None:
            if row["gallery_sha256"] != declaration["gallery_sha256"]:
                raise FrameContractError("search gallery SHA contradicts declaration")
            if any(identity not in declaration["enrolled_identity_ids"] for identity, _score in row["top_k"]):
                raise FrameContractError("search top-k identity outside declared gallery")
        face = faces.get(row["face_id"])
        if face is None:
            if (
                row["unit_id"] not in (None, "background:" + image)
                or row["identity_id"] is not None
                or row["identity_status"] != "unknown"
            ):
                raise FrameContractError("detector-only row cannot mint a GT source unit")
            background += 1
            continue
        if row["unit_id"] is not None and str(row["unit_id"]).startswith("background:"):
            raise FrameContractError("GT face cannot be a detector-only background row")
        if any(row[key] != face[key] for key in ("image_id", "identity_status")):
            raise FrameContractError("search GT image/identity_status contradicts FRAME")
        if declaration is not None:

            def occluder(value: Any) -> str:
                return "unknown" if value is None else ("+".join(sorted(set(value))) if value else "clear")

            expected_cell = [
                occluder(face["annotation"]["occluders"]),
                occluder(declaration.get("enrolled_occluders", {}).get(face["identity_id"])),
            ]
            if row["cell"] != expected_cell:
                raise FrameContractError("search cell contradicts GT query/enrolled annotations")
        membership = _binding_membership(manifest, leg, row["fold"], face)
        if membership is None:
            if row["identity_id"] not in (None, face["identity_id"]) or row["unit_id"] not in (None, face["face_id"]):
                raise FrameContractError("legacy GT identity/unit contradicts FRAME")
        elif row["identity_id"] != (face["identity_id"] if membership else None) or row["unit_id"] != (
            None if membership else face["face_id"]
        ):
            raise FrameContractError("GT identity/unit contradicts declared gallery membership")
        key = (leg, row["arm"], row["fold"], row["face_id"])
        if key in search_map:
            raise FrameContractError("duplicate GT search key")
        search_map[key] = row

    outcomes = (scores or {}).get("face_outcomes")
    if outcomes is not None:
        if frame is None:
            raise FrameContractError("face_outcomes requires FRAME provenance")
        expected = {
            (leg, arm, folds[psus[f["image_id"]]], f["face_id"])
            for leg, arms in scopes.items() for arm in arms for f in faces.values()
        }
        outcome_map = {}
        outcome_indices = {}
        for index, row in enumerate(outcomes):
            key = (row["leg_key"], row["arm"], row["fold"], row["face_id"])
            if key in outcome_map or key not in expected:
                raise FrameContractError("face_outcomes duplicate/foreign declared GT key")
            outcome_map[key] = row
            outcome_indices[key] = index
        if set(outcome_map) != expected or set(search_map) != expected:
            raise FrameContractError("face_outcomes/search GT inventory does not cover declared scope")
    else:
        outcome_map = {}
        # Legacy searches need not cover all GT. Preserve missing faces as
        # metadata with explicit null stages/outcomes, never detector outcomes.
        declared_arms = block.get("arms")
        if declared_arms is not None and (
            not isinstance(declared_arms, list)
            or not declared_arms
            or any(not isinstance(arm, str) or not arm for arm in declared_arms)
            or len(set(declared_arms)) != len(declared_arms)
        ):
            raise FrameContractError("legacy inventory declared arm scope invalid")
        legacy_scopes = {(leg, arm) for leg, arms in scopes.items() for arm in arms}
        if declared_arms is None:
            legacy_scopes = {(row["leg_key"], row["arm"]) for row in search_map.values()}
            for leg in legs:
                if not any(key == leg for key, _arm in legacy_scopes):
                    legacy_scopes.add((leg, None))

        def label(value: Any) -> str:
            return "unknown" if value is None else ("+".join(sorted(set(value))) if value else "clear")

        for index, face in enumerate(faces.values()):
            image_id = face["image_id"]
            fold = folds[psus[image_id]]
            for leg, arm in legacy_scopes:
                key = (leg, arm, fold, face["face_id"])
                if key in search_map:
                    continue
                declaration = registry.get((leg, fold), {})
                search_map[key] = {
                    "face_id": face["face_id"], "image_id": image_id, "psu_id": psus[image_id],
                    "leg_key": leg, "arm": arm, "fold": fold, "fold_role": roles[fold],
                    "sampling_arm": images[image_id]["sampling_arm"], "identity_status": face["identity_status"],
                    "stage_reached": None, "arm_availability": None, "top_k": [],
                    "cell": [label(face["annotation"]["occluders"]),
                             label(declaration.get("enrolled_occluders", {}).get(face["identity_id"]))],
                    "_ref": _jp("frame.json", "faces", index),
                }

    rows = []
    for key, source in search_map.items():
        face = faces[source["face_id"]]
        result = outcome_map.get(key)
        mated = _binding_membership(manifest, source["leg_key"], source["fold"], face)
        if result is not None:
            for field in (
                "image_id",
                "psu_id",
                "fold_role",
                "sampling_arm",
                "arm_availability",
                "stage_reached",
                "identity_status",
                "cell",
            ):
                if result[field] != source[field]:
                    raise FrameContractError(f"face_outcomes {field} contradicts validated search/FRAME")
            if result["mated"] is not mated:
                raise FrameContractError("face_outcomes mated contradicts declared gallery membership")
            if result["fold_role"] == "fit" and (
                result["outcome"] is not None
                or result["outcome_available"]
                or result["outcome_reason"] != "fit_fold_not_scored"
            ):
                raise FrameContractError("fit fold must remain metadata only")
            available = result["outcome_available"]
            if available and (
                result["outcome"] is None
                or result["outcome_reason"] is not None
                or result["arm_availability"] != "available"
                or mated is None
            ):
                raise FrameContractError("face_outcomes unavailable evidence cannot carry an outcome")
            if not available and (result["outcome"] is not None or not result["outcome_reason"]):
                raise FrameContractError("face_outcomes missing outcome requires a named null")
        qualified, reason = _binding_qualification(face, frame, qualification=qualification)
        outcome = result["outcome"] if result and qualified else None
        available = result["outcome_available"] if result and qualified else False
        failure = (
            outcome in {"missed", "unaligned", "wrong_identity", "rejected", "false_accept"} if available else None
        )
        top = source["top_k"][0] if source["top_k"] else None
        rows.append(
            {
                "image_id": source["image_id"],
                "face_id": source["face_id"],
                "psu_id": source["psu_id"],
                "leg_key": source["leg_key"],
                "arm": source["arm"],
                "stage": source["stage_reached"],
                "arm_availability": source["arm_availability"],
                "fold": source["fold"],
                "fold_role": source["fold_role"],
                "sampling_arm": source["sampling_arm"],
                "identity_status": source["identity_status"],
                "mated": mated,
                "cell": f"{source['cell'][0]} / {source['cell'][1]}",
                "annotation_tier": face["annotation"]["annotation_tier"],
                "qualified": qualified,
                "qualification_reason": reason,
                "outcome": outcome,
                "outcome_available": available,
                "outcome_reason": (result["outcome_reason"] if qualified else reason)
                if result
                else "legacy_face_outcomes_unavailable",
                "is_failure": failure,
                "default_visible": bool(
                    qualified
                    and failure
                    and source["sampling_arm"] == "probability"
                    and source["fold_role"] == "test"
                    and source["arm"] == "native"
                ),
                "top1_identity": top[0] if top else None,
                "top1_score": top[1] if top else None,
                "ref": source.get("_ref", "searches.jsonl"),
                "outcome_ref": _jp("scores.json", "face_outcomes", outcome_indices[key]) if result else None,
            }
        )
    rows.sort(key=lambda r: (r["image_id"], r["face_id"], r["leg_key"], r["arm"] or "", r["fold"]))
    return rows, background


def _failures_html(
    frame: Mapping[str, Any] | None, rows: list[dict[str, Any]], background: int, *, include_crops: bool
) -> str:
    pool = _pool(frame, rows, include_crops=include_crops)
    selected = [r for r in rows if r.get("default_visible") is True]
    lines = []
    if pool["status"] == "established":
        lines.append(
            f"<p>Selection pool (VIZ-41): overall {pool['overall_images']} images and "
            f"{pool['overall_gt_faces']} GT faces; named {pool['named_faces']}, unknown "
            f"{pool['unknown_faces']}, <strong>unresolved {pool['unresolved_identity_faces']}</strong>. "
            "Unresolved identities never enter a non-mated pool. "
            + _code(_jp("frame.json", "faces")) + "</p>"
        )
    else:
        lines.append(f"<p>{_st('not_evaluated', 'pool not established')}: {_e(pool['reason'])}. "
                     "No admissible non-mated N is implied.</p>")
    lines.append('<p>Default selection: binding-qualified primary test probability native failures. '
                 'Classification is supplied by the producer; upstream unavailable cases stay unclassified.</p>')
    if not rows or any("default_visible" not in r for r in rows):
        lines.append('<p class="note">○ Outcome classification unavailable for legacy inventory; '
                     'an empty selection does not establish absence of failures.</p>')
    lines.append(_ui_failure_controls(rows))
    lines.append(f'<p id="failure-counts" aria-live="polite">{_e(_ui_selection_counts(rows, selected))}</p>')
    lines.append(f'<p>Images shown as crops: 0 ({"crops off" if not include_crops else "no crop artifacts in this build"}). '
                 f'Detector-only rows: {background}, separate from fixed background source units. '
                 'Background source units: see bound pool accounting; unknown if absent.</p>')
    faces = list(frame["faces"]) if frame is not None else []
    tier_a = [f for f in faces if f["annotation"]["annotation_tier"] == "a"]
    if not tier_a:
        lines.append("<p>tier-(a) labels: none in this frame.</p>")
    elif any(f["annotation"]["observation_ref"] is None for f in tier_a):
        lines.append(f"<p>{_st('not_evaluated', _TIER_A_UNRECORDED)}: tier-(a) faces are "
                     "nonexhaustive and do not feed analysis or the pool.</p>")
    lines.append('<button type="button" id="back-to-origin" hidden>↩ Back to origin</button>')
    lines.append('<div id="failure-table">' + _ui_failure_table(selected) + '</div>')
    lines.append('<details><summary>Bound pool accounting</summary><pre id="failure-pool"></pre></details>')
    lines.append('<script type="application/json" id="failure-view-data">'
                 + _ui_json({"rows": rows, "pool": pool, "background": background}) + '</script>')
    return "\n".join(lines)


# --- S7 clusters ---------------------------------------------------------------------


def _chaining_html(leg_index: int, leg: Mapping[str, Any]) -> str:
    chaining = leg["chaining"]
    if chaining.get("status") != "available":
        return f"<p>{_st('not_evaluated', _NOT_EVALUATED_NO_EVIDENCE)} ({_e(chaining.get('reason'))})</p>"
    data = chaining["data"]
    eligible = data["eligible_pairs"]
    path_linked = data["path_linked_pairs"]
    third = data["third_identity_linked_pairs"]
    if not (0 <= third <= path_linked <= eligible):
        raise FrameContractError(
            f"chaining counts are malformed: third {third}, path {path_linked}, eligible {eligible}"
        )
    if eligible == 0:
        return f"<p>{_st('not_evaluated', _NOT_EVALUATED_NO_PAIRS)}</p>"
    d_rate = path_linked / eligible
    c_rate = third / eligible
    scope = data["scope"]
    exclusions = ", ".join(f"{_e(x['reason'])} ×{x['count']}" for x in data["exclusions"]) or "none"
    pairs = data["pairs"]
    details = []
    for pair_index, pair in enumerate(pairs):
        details.append(
            f'<button type="button" data-inspect-pair="{leg_index}:{pair_index}" '
            f'aria-haspopup="dialog">↗ Inspect chaining pair {_e(pair["pair_id"])} '
            f'(path_linked {_e(pair["path_linked"])}, third identity '
            f'{_e(pair["third_identity_id"] or "none")})</button>'
        )
    details.append(
        f'<script type="application/json" data-chaining-leg="{leg_index}">'
        + _ui_json({"chaining": leg["chaining"], "config": leg["config"],
                    "neighbours": leg.get("neighbours")}) + '</script>'
    )
    return (
        f"<p>Known-different path links D/N: {path_linked}/{eligible} = {_f(d_rate)} "
        f"{_code(_jp('clusters.json', 'legs', leg_index, 'chaining', 'data', 'path_linked_pairs'))}; "
        f"chaining_check C/N: {third}/{eligible} = {_f(c_rate)} "
        f"{_code(_jp('clusters.json', 'legs', leg_index, 'chaining', 'data', 'third_identity_linked_pairs'))}.</p>"
        f"<p>Held-out scope: frame {_e(scope['frame_id'])}, fold {scope['fold']} ({_e(scope['fold_role'])}); "
        f"rule: {_e(scope['pair_selection_rule'])}. Input pairs {data['input_pairs']}; "
        f"exclusions: {exclusions}. Identity is never inferred from co-assignment.</p>" + "\n".join(details)
    )


def _dendrogram_svg(leg: Mapping[str, Any]) -> str:
    dend = leg["dendrogram"]
    cut = leg["dendrogram_cut"]["distance"]
    caption = _NO_CUT if cut is None else f"production cut recorded at d = {cut}"
    if dend.get("status") != "available":
        return (
            f"<p>{_e(caption)}</p><p>{_st('not_evaluated', 'dendrogram not evaluated: ' + str(dend.get('reason')))}</p>"
        )
    leaves = dend["data"]["leaf_face_ids"]
    linkage = dend["data"]["linkage"]
    n = len(leaves)
    if not n:
        return f"<p>{_e(caption)}; dendrogram unavailable: no leaves recorded.</p>"
    tau_ref = leg["acceptance_tau_reference"]
    distances = [m[2] for m in linkage] + [0.0]
    if cut is not None:
        distances.append(cut)
    if tau_ref.get("status") == "available":
        distances.append(tau_ref["data"]["distance"])
    lo, hi = min(distances), max(distances)
    span = hi - lo or 1.0
    lo, hi = lo - span * 0.05, hi + span * 0.05
    # Horizontal layout reserves a row for every face. Traverse the actual
    # linkage to order leaves; numeric leaf-index order can create false crossings.
    order = []
    pending = [n + len(linkage) - 1] if linkage else list(reversed(range(n)))
    while pending:
        node = pending.pop()
        if node < n:
            order.append(node)
        else:
            a, b = linkage[node - n][:2]
            pending.extend((int(b), int(a)))
    left = max(110, max(len(str(face)) for face in leaves) * 7 + 24)
    width, height = max(760, left + 480), max(160, 64 + 26 * n)
    top, base = 18, height - 44

    def x_of(d: float) -> float:
        return left + (d - lo) / (hi - lo) * (width - left - 24)

    pos = {node: (x_of(0), top + (i + 0.5) * (base - top) / n) for i, node in enumerate(order)}
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Recorded linkage hierarchy in original-space cosine distance">'
    ]
    for k, (a, b, d, _count) in enumerate(linkage):
        xa, ya = pos[int(a)]
        xb, yb = pos[int(b)]
        xd, y = x_of(d), (ya + yb) / 2
        pos[n + k] = (xd, y)
        parts.append(
            f'<polyline class="tree" data-node="{n + k}" data-distance="{d}" '
            f'points="{xa:.2f},{ya:.2f} {xd:.2f},{ya:.2f} {xd:.2f},{yb:.2f} {xb:.2f},{yb:.2f}"/>'
        )
    for i, face_id in enumerate(leaves):
        _, y = pos[i]
        parts.append(f'<text class="lbl" x="{left - 8}" y="{y + 4:.2f}" text-anchor="end">{_e(face_id)}</text>')
    parts.append(f'<line class="axis" x1="{left}" x2="{width - 24}" y1="{base + 6}" y2="{base + 6}"/>')
    ticks = sorted({min(distances), max(distances)})
    # A reject-all τ can be one ULP above 1: its negative reference and zero
    # then have indistinguishable pixels. Preserve the exact reference caption
    # without printing overlapping tick labels at effectively the same place.
    if all(abs(x_of(0.0) - x_of(tick)) > 72 for tick in ticks):
        ticks.append(0.0)
    for distance in sorted(ticks):
        parts.append(
            f'<text class="lbl" x="{x_of(distance):.2f}" y="{base + 21}" text-anchor="middle">{distance:.6g}</text>'
        )
    parts.append(
        f'<text class="lbl" x="{(left + width - 24) / 2}" y="{height - 3}" '
        'text-anchor="middle">d = 1 − cosine similarity (original space)</text>'
    )
    if cut is not None:
        xc = x_of(cut)
        parts.append(
            f'<line class="cut" data-d="{cut:.6g}" x1="{xc:.2f}" x2="{xc:.2f}" y1="{top}" y2="{base}">'
            f"<title>Production cut d = 1 − s = {cut}</title></line>"
        )
    reference_caption = f"Acceptance τ reference unavailable: {tau_ref.get('reason') or 'not recorded'}"
    if tau_ref.get("status") == "available":
        distance = tau_ref["data"]["distance"]
        xt = x_of(distance)
        parts.append(
            f'<line class="tau" data-d="{distance:.6g}" x1="{xt:.2f}" x2="{xt:.2f}" y1="{top}" y2="{base}">'
            f"<title>{_TAU_LABEL} at d = 1 − τ = {distance}</title></line>"
        )
        reference_caption = f"Dashed line: {_TAU_LABEL}; τ = {tau_ref['data']['tau']}, d = 1 − τ = {distance}"
    parts.append("</svg>")
    return (
        f"<p>{_st('not_evaluated', caption) if cut is None else _e('Solid line: ' + caption)}</p>"
        f"<p>{_e(reference_caption)}. This is a separate acceptance reference, not hierarchy evidence.</p>\n"
        + "\n".join(parts)
    )


def _projection_html(leg_index: int, leg: Mapping[str, Any]) -> str:
    out = []
    for projection_index, proj in enumerate(leg["projections"]):
        params = ", ".join(f"{k} {v}" for k, v in sorted(proj["parameters"].items()))
        versions = ", ".join(f"{v['package']} {v['version']}" for v in proj["versions"]) or "versions not recorded"
        caption = (
            f'<p class="proj"><strong>{_e(_PROJECTION_CAPTION)}</strong> · {_e(proj["name"])} · '
            f"{_e(proj['method'])} · {_e(params)} · seed {proj['seed']} · {_e(versions)} "
            f"{_code(_jp('clusters.json', 'legs', leg_index, 'projections', projection_index))}</p>"
        )
        out.append(caption)
        result = proj["result"]
        if result.get("status") != "available":
            out.append(f"<p>{_st('not_evaluated', 'projection_unavailable')}: {_e(result.get('reason'))}</p>")
            continue
        pts = result["data"]
        if not pts:
            out.append("<p>Projection unavailable: no coordinates recorded.</p>")
            continue
        coords = [p["coordinates"] for p in pts]
        xs = [c[0] for c in coords] or [0.0]
        ys = [c[1] for c in coords] or [0.0]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        # One scale per projection preserves its supplied geometry. Degenerate
        # axes are centered; projections from separate legs are never aligned.
        scale = min(560 / (x1 - x0) if x1 > x0 else math.inf, 280 / (y1 - y0) if y1 > y0 else math.inf)
        if not math.isfinite(scale):
            scale = 1.0
        dots = "".join(
            f'<circle class="dot" cx="{320 + (c[0] - (x0 + x1) / 2) * scale:.2f}" '
            f'cy="{170 - (c[1] - (y0 + y1) / 2) * scale:.2f}" r="3">'
            f"<title>{_e(p['face_id'])}: {_e(c)}</title></circle>"
            for p, c in zip(pts, coords, strict=True)
        )
        out.append(
            "<p>Independent diagnostic coordinates for this leg only; axes have no original-space units. "
            "Metrics and neighbour similarities use the original embedding space only.</p>"
            f'<svg viewBox="0 0 640 340" role="img" aria-label="{_e(_PROJECTION_CAPTION)}">{dots}</svg>'
        )
    return "\n".join(out)


def _clusters_html(clusters: Mapping[str, Any] | None) -> str:
    if clusters is None:
        return f"<p>{_st('not_evaluated', 'not evaluated: clusters.json not written')}</p>"
    blocks = []
    for index, leg in enumerate(clusters["legs"]):
        cut = leg["dendrogram_cut"]
        pm = leg["partition_metrics"]
        if pm.get("status") == "available":
            d = pm["data"]
            rows = [
                ["named faces", _f(d["named_faces"], 0)],
                ["unknown / unresolved (excluded)", f"{d['unknown_faces']} / {d['unresolved_faces']}"],
                ["merges", _f(d["merges"], 0)],
                ["fragmentation", _f(d["fragmentation"], 0)],
                ["unknown absorbed", _f(d["unknown_absorbed"], 0)],
                ["noise faces (−1, unpaired)", _f(d["noise_faces"], 0)],
            ]
            pm_html = _table(
                "Partition metrics in original space (conditional on available GT vectors)", ["metric", "value"], rows
            )
        else:
            pm_html = f"<p>{_st('not_evaluated', 'partition metrics not evaluated: ' + _e(pm.get('reason')))}</p>"
        neighbours = leg["neighbours"]
        if neighbours.get("status") == "available":
            nrows = [
                [_e(e["source_face_id"]), _e(e["target_face_id"]), _f(e["cosine_similarity"])]
                for e in neighbours["data"]["edges"]
            ]
            n_html = _table("Nearest neighbours in the original leg space", ["source", "target", "cosine"], nrows)
        else:
            n_html = f"<p>{_st('not_evaluated', 'neighbours not evaluated: ' + _e(neighbours.get('reason')))}</p>"
        pca = leg["pca_spectrum"]
        pca_html = (
            f"<p>PCA variance-only spectrum: {', '.join(_f(v) for v in pca['data']['explained_variance_ratio'])} "
            f"(retained {pca['data']['retained_components']}; no loadings).</p>"
            if pca.get("status") == "available"
            else f"<p>{_st('not_evaluated', 'PCA spectrum not evaluated')}</p>"
        )
        cut_label = (
            _st("not_evaluated", _NO_CUT) if cut["distance"] is None else f"production cut d = {_f(cut['distance'])}"
        )
        if cut["labels"] is not None and cut["distance"] is not None:
            count: dict[int, int] = {}
            for item in cut["labels"]:
                count[item["label"]] = count.get(item["label"], 0) + 1
            cut_rows = [[_f(k, 0), _f(v, 0)] for k, v in sorted(count.items())]
            cut_html = _table("Recorded hierarchy cut labels (not recomputed)", ["label", "faces"], cut_rows)
        else:
            cut_html = f"<p>{_st('not_evaluated', _NO_CUT)}</p>" if cut["distance"] is None else ""
        chain = _chaining_html(index, leg)
        reference = leg["acceptance_tau_reference"]
        reference_text = (
            _TAU_LABEL
            if reference.get("status") == "available"
            else f"acceptance τ reference unavailable: {reference.get('reason') or 'not recorded'}"
        )
        blocks.append(
            f"<h3>Leg {_e(leg['leg_key'])} {_code(_jp('clusters.json', 'legs', index))}</h3>\n"
            f"{_figure_vector_coverage(index, leg)}\n"
            f"<p>Cut: {cut_label} · {_e(cut['caption'])} · {_e(reference_text)}.</p>\n"
            f"{pm_html}\n{cut_html}\n<h4>Held-out chaining (GRPH-18)</h4>\n{chain}\n"
            f"<h4>Dendrogram</h4><p>Recorded {_e(leg['config']['linkage'])} linkage in cosine distance; "
            f"production {_e(leg['config']['production_algorithm'])} configuration is separate metadata.</p>\n"
            f"{_dendrogram_svg(leg)}\n"
            f"<h4>Projection</h4>\n{_projection_html(index, leg)}\n"
            f"<h4>Neighbours</h4>\n{n_html}\n{pca_html}"
        )
    return "\n".join(blocks)


def _figure_vector_coverage(leg_index: int, leg: Mapping[str, Any]) -> str:
    """Display the optional frozen coverage wire, never infer it from plot rows."""
    coverage = leg.get("vector_coverage")
    if coverage is None:
        return (
            "<p>Vector coverage unknown: not recorded. Diagnostics are conditional on available GT vectors; "
            "full-cohort coverage is not established.</p>"
        )
    fields = (
        ("n_gt_faces", "GT faces (FRAME total)"),
        ("n_named_gt_faces", "Named GT faces (FRAME total)"),
        ("n_embedded_gt_faces", "Available embedded GT faces"),
        ("n_missing_gt_faces", "Missing GT vectors"),
        ("n_embedded_named_faces", "Available embedded named GT faces"),
        ("n_detector_only_rows", "Detector-only rows (excluded from GT)"),
    )
    rows = [
        [
            _e(label),
            "unknown (null)" if coverage[key] is None else _e(coverage[key]),
            _code(_jp("clusters.json", "legs", leg_index, "vector_coverage", key)),
        ]
        for key, label in fields
    ]
    return (
        f"<p>{_e(coverage['label'])}; conditional: {_f(coverage['conditional'])}. "
        "Missing vectors remain outside these diagnostics; full GT/outcome denominators are unchanged.</p>"
        + _table("Recorded vector coverage", ["Source unit", "Count", "JSON path"], rows)
    )


# --- S8 frames and power ------------------------------------------------------------


def _frames_html(scores: Mapping[str, Any], frame: Mapping[str, Any] | None, created: str, *, unratified: bool) -> str:
    if frame is None:
        frame_row = [
            _e(scores["frame_id"]),
            _st("not_evaluated", "not acquired"),
            "",
            "",
            "",
            "",
            "",
            _code("frame.json"),
        ]
    else:
        frame_row = [
            _e(frame["frame_id"]),
            _e(frame["admissibility"]),
            "exhaustive: "
            + (
                "true"
                if frame["exhaustive"] is True
                else ("false" if frame["exhaustive"] is False else "unestablished")
            ),
            _f(scores["n_psu"], 0),
            _f(scores["n_eff"]),
            _f(scores["design_effect"]),
            _f(scores["planning_icc"]),
            _code(_jp("scores.json", "n_eff")),
        ]
    frame_table = _table(
        "Frame (one row per frame)",
        ["Frame identifier", "Permitted use", "Exhaustive ground truth", "Independent sampling units (n_psu)", "Effective sample size (n_eff)", "Design effect (deff)", "Planning within-unit correlation (ICC)", "Source"],
        [frame_row],
    )
    sens_rows = []
    for index, s in enumerate(scores["icc_sensitivity"]):
        for h in s["hypotheses"]:
            sens_rows.append(
                [
                    _f(s["planning_icc"]),
                    _f(s["design_effect"]),
                    _f(s["n_eff"]),
                    _e(h["id"]),
                    _f(h["mde"]) if h["mde"] is not None else _st("not_evaluated", "not scored"),
                    _code(_jp("scores.json", "icc_sensitivity", index, "hypotheses")),
                ]
            )
    sens = _table(
        "Sensitivity to recorded planning within-unit correlation (report-only; assumptions, not observed correlations)",
        ["Planning correlation (ICC)", "Design effect (deff)", "Effective sample size (n_eff)", "Hypothesis identifier", "Minimum detectable effect (MDE)", "Source"],
        sens_rows,
    )
    floors = _table(
        "Floors and design assumptions (declared, not evidence of power)",
        ["quantity", "value", "JSON path"],
        [
            [
                "min_n_independent (global floor, checked before FPIR intervals)",
                _f(scores["min_n_independent"], 0),
                _code(_jp("scores.json", "min_n_independent")),
            ],
            [
                "cell_floor_n_independent (pair cells)",
                _f(scores["cell_floor_n_independent"], 0),
                _code(_jp("scores.json", "cell_floor_n_independent")),
            ],
            [
                "global floor status",
                "met" if _floor_ok(scores) else _st("not_evaluated", "not met"),
                _code(_jp("scores.json", "n_psu")),
            ],
            ["p_d (discordance design assumption)", _f(scores["p_d"]), _code(_jp("scores.json", "p_d"))],
            ["power (design assumption)", _f(scores["power"]), _code(_jp("scores.json", "power"))],
        ],
    )
    seal_line = (
        f"<p>{_st('unratified', 'unratified: no seal shown')}</p>"
        if unratified
        else f"<p>Recorded run date: {_e(created)}.</p>"
    )
    return ('<p>' + term_link('admissibility', 'Permitted frame use') + '; '
            + term_link('psu', 'Independent sampling units (n_psu)') + '; '
            + term_link('neff', 'Effective sample size (n_eff)') + '; '
            + term_link('mde', 'Minimum detectable effect (MDE)') + '; '
            + term_link('ratified', 'Policy approval (ratification)') + '; '
            + term_link('sealed', 'Run seal') + '.</p>'
            + f"{frame_table}\n{sens}\n{floors}\n<p>{_e(_FLOOR_NOTE)}</p>\n{seal_line}")


# --- page assembly -------------------------------------------------------------------

_CSS = """
:root { color-scheme: light dark; --fg:#1b1b1b; --bg:#fbfbf8; --mut:#5a5a5a; --line:#c9c9c2; --accent:#1f5f8b; --warn:#8a3b12; }
@media (prefers-color-scheme: dark) { :root { --fg:#e8e8e2; --bg:#16171a; --mut:#a4a4a0; --line:#3d3f44; --accent:#8fc3e6; --warn:#f0b38a; } }
body { font: 15px/1.45 system-ui, sans-serif; color: var(--fg); background: var(--bg); margin: 0; padding: 0 1rem 3rem; }
.skip { position: absolute; left: -999px; } .skip:focus { left: 1rem; top: 0.5rem; background: var(--bg); padding: 0.25rem; }
nav.tabs a { margin-right: 1rem; color: var(--accent); }
section { border-top: 1px solid var(--line); padding-top: 0.75rem; margin-top: 1rem; }
table { border-collapse: collapse; margin: 0.5rem 0 1rem; font-size: 13px; width: 100%; table-layout: fixed; }
th, td { overflow-wrap: anywhere; height: auto; }
tr { height: auto; }
button, select { font: inherit; color: var(--fg); background: var(--bg); border: 1px solid var(--mut); border-radius: 3px; padding: .3rem .45rem; max-width: 100%; }
button { cursor: pointer; } button:disabled { cursor: default; opacity: .7; }
a, summary { color: var(--accent); } summary { cursor: pointer; }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
section:focus { outline: 2px solid var(--accent); outline-offset: 3px; }
[hidden] { display: none !important; }
fieldset { border: 1px solid var(--line); display: flex; flex-wrap: wrap; align-items: end; gap: .65rem; }
label { display: inline-flex; flex-direction: column; gap: .2rem; max-width: 20rem; }
.provenance, .source { font-size: 12px; } .source { padding: .1rem .25rem; }
.provenance code { display: block; overflow-wrap: anywhere; }
.chart { max-width: 760px; }
.mode-banner { border-left: 4px solid var(--warn); padding: .5rem; color: var(--warn); }
dialog { color: var(--fg); background: var(--bg); border: 1px solid var(--mut); width: min(70rem, 90vw); max-height: 85vh; overflow: auto; }
dialog::backdrop { background: #0008; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 13px; }
@media (max-width: 760px) { table { table-layout: auto; } th, td { padding: .2rem; } section { overflow-x: auto; } }
th, td { border-bottom: 1px solid var(--line); padding: 0.2rem 0.5rem; text-align: left; vertical-align: top; }
caption { text-align: left; color: var(--mut); padding-bottom: 0.25rem; }
.verdict-line { font-size: 1.15rem; font-weight: 600; }
.st { font-weight: 600; } .st-inconclusive, .st-not_evaluated, .st-unratified, .st-not_scored, .st-collect, .st-unscored { color: var(--warn); }
code.jp { color: var(--mut); font-size: 12px; } .note { color: var(--mut); }
svg { display: block; width: min(100%, 760px); height: auto; } svg text.lbl { fill: var(--fg); font-size: 11px; }
svg .series { fill: none; stroke: var(--accent); stroke-width: 2; } svg .s1 { stroke: var(--warn); fill: var(--warn); }
svg .ref { stroke: var(--line); stroke-dasharray: 4 3; } svg .axis { stroke: var(--mut); }
svg .unresolvable { fill: var(--line); opacity: 0.5; } svg .tree { fill: none; stroke: var(--mut); }
svg .cut { stroke: var(--accent); stroke-width: 1.5; } svg .tau { stroke: var(--warn); stroke-dasharray: 5 3; }
svg .dot { fill: var(--accent); } svg text.s1 { stroke: none; fill: var(--warn); }
"""


def _strict_json(value: object, *, where: str, **options: Any) -> str:
    """JSON text with no non-finite token; refuses instead of emitting ``NaN``/``Infinity``."""
    _assert_finite_tree(value, where)
    return json.dumps(value, allow_nan=False, sort_keys=True, **options)


def _ui_json(value: object) -> str:
    """Inert JSON for HTML raw-text elements, including hostile pseudonymous IDs."""
    return (_strict_json(value, where="inline report JSON", ensure_ascii=True)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def _ui_leg_label(key: str) -> str:
    parts = key.split("__")
    return (f'<strong>{_e(parts[0])}</strong> <span class="note">{_e(" · ".join(parts[1:3]))}</span>'
            f'<details><summary>Leg contract</summary>{_e(key)}</details>')


def _ui_selection_counts(rows: Sequence[Mapping[str, Any]], selected: Sequence[Mapping[str, Any]]) -> str:
    return (
        f"Inventory: {len(rows)} rows. Eligible after filters: {len(selected)} rows, "
        f"{len({r['face_id'] for r in selected})} faces, {len({r['image_id'] for r in selected})} images. "
        f"Selected: {len(selected)} rows, {len({r['face_id'] for r in selected})} faces, "
        f"{len({r['image_id'] for r in selected})} images; shown {len(selected)}; "
        f"omitted: {len(rows) - len(selected)} inventory rows; eligible omitted 0. "
        "Offset 0; no limit. Sort: image_id, face_id, leg_key."
    )


def _ui_failure_controls(rows: Sequence[Mapping[str, Any]]) -> str:
    fields = [("sampling_arm", "Sampling arm"), ("fold_role", "Fold role"), ("arm", "Arm"),
              ("leg_key", "Model / implementation identifier"), ("cell", "Query / enrolled occlusion subgroup"), ("stage", "Search stage"),
              ("outcome", "Outcome"), ("identity_status", "Identity status"), ("qualified", "Qualified")]
    controls = [
        '<fieldset id="failure-filters"><legend>Filter GT inventory</legend>'
        '<label>Scope <select id="failure-scope"><option value="default">Primary test probability native failures</option>'
        '<option value="all">All GT inventory (including unclassified)</option></select></label>'
    ]
    for field, label in fields:
        values = sorted({str(r.get(field)) if r.get(field) is not None else "unknown" for r in rows})
        options = ''.join(f'<option value="{_e(v)}">{_e(v)}</option>' for v in values)
        controls.append(f'<label>{_e(label)} <select data-filter="{field}" id="filter-{field}">'
                        f'<option value="*">All</option>{options}</select></label>')
    controls.append('<label>Sort <select id="failure-sort"><option value="image">image_id, face_id, leg_key</option>'
                    '<option value="face">face_id, image_id, leg_key</option></select></label>'
                    '<button type="button" id="reset-filters">↩ Reset filters</button></fieldset>')
    return '\n'.join(controls)


def _ui_failure_sources(r: Mapping[str, Any]) -> str:
    """Outcome source is the producer classification record; Search source is the search record."""
    sources = (
        ("outcome_ref", "Outcome source", "Classification evidence unavailable: no outcome record supplied"),
        ("ref", "Search source", "Search evidence unavailable: no search record supplied"),
    )
    return " ".join(
        f'<button type="button" class="source" data-source="{_e(r[key])}" '
        f'aria-label="Inspect {label} {_e(r[key])}" title="{_e(r[key])}">↗ {label}</button>'
        if r.get(key) else f'<span class="note">○ {missing}</span>'
        for key, label, missing in sources
    )


def _ui_failure_table(rows: Sequence[Mapping[str, Any]]) -> str:
    cells = []
    for r in rows:
        outcome = r.get("outcome") if r.get("outcome_available") is True else (
            "○ unclassified: " + str(r.get("outcome_reason") or "classification unavailable"))
        cells.append([
            _e(r["image_id"]), _e(r["face_id"]), _ui_leg_label(r["leg_key"]),
            _e(r.get("stage") or "unknown"), _e(outcome), _e(r.get("top1_identity") or "none"),
            _f(r.get("top1_score")), _e(r.get("fold")), _e(r.get("fold_role") or "unknown"),
            _e(r.get("cell")), _e(r.get("annotation_tier") or "unknown"), _ui_failure_sources(r),
        ])
    return _table("Ground-truth (GT) inventory selection (outcomes supplied by producer)",
                  ["Image identifier (image_id)", "Face identifier (face_id)", "Model", "Search stage", "Outcome / reason", "Top-ranked identity",
                   "top-1 score", "Fold", "Fold role", "Cell", "Label tier", "Source"], cells)


def _ui_script() -> str:
    """View operations only: select supplied rows/points and inspect inline evidence."""
    return r"""
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const parse = el => el ? JSON.parse(el.textContent) : {};
  const view = parse($('report-view-data'));
  const files = view.files || {};
  const own = (obj, key) => obj != null && Object.hasOwn(obj, key);
  const text = value => value == null ? 'unknown' : String(value);
  const node = (tag, value, parent) => {
    const el = document.createElement(tag);
    if (value != null) el.textContent = text(value);
    if (parent) parent.append(el);
    return el;
  };
  const focus = el => { if (el) el.focus({preventScroll: true}); };
  const snapshot = () => ({active: document.activeElement, x: scrollX, y: scrollY,
    selection: window.getSelection()?.rangeCount ? window.getSelection().getRangeAt(0).cloneRange() : null});
  const restore = saved => {
    if (!saved) return;
    focus(saved.active);
    if (saved.selection && saved.selection.startContainer.isConnected) {
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(saved.selection);
    }
    window.scrollTo(saved.x, saved.y);
  };
  let modalContext = null;
  const inspections = [];
  const dialog = $('source-inspector');
  const closeDialog = () => {
    if (inspections.length) {
      const previous = inspections.pop();
      $('inspector-title').textContent = previous.title;
      $('close-inspector').textContent = previous.title.startsWith('Chaining pair ') ? '↩ Close pair inspection (Esc)' : '↩ Close source inspection (Esc)';
      $('inspector-body').replaceChildren(...previous.nodes);
      restore(previous.context);
    } else { dialog.close(); restore(modalContext); modalContext = null; }
  };
  $('close-inspector').addEventListener('click', closeDialog);
  dialog.addEventListener('cancel', event => { event.preventDefault(); closeDialog(); });
  const inspect = (heading, build) => {
    if (dialog.open) inspections.push({title: $('inspector-title').textContent,
      nodes: [...$('inspector-body').childNodes], context: snapshot()});
    else modalContext = snapshot();
    $('close-inspector').textContent = heading.startsWith('Chaining pair ') ? '↩ Close pair inspection (Esc)' : '↩ Close source inspection (Esc)';
    $('inspector-title').textContent = heading;
    $('inspector-body').replaceChildren();
    build($('inspector-body'));
    if (!dialog.open) dialog.showModal();
    focus($('close-inspector'));
  };
  const resolve = path => {
    const split = path.indexOf('#');
    if (split < 0) throw new Error('JSONPointer fragment missing');
    const filename = path.slice(0, split);
    if (!own(files, filename)) throw new Error('source file not supplied in inline files map');
    let value = files[filename];
    const pointer = decodeURIComponent(path.slice(split + 1));
    if (pointer !== '' && !pointer.startsWith('/')) throw new Error('invalid JSONPointer');
    if (pointer) for (const raw of pointer.slice(1).split('/')) {
      if (/~(?:[^01]|$)/.test(raw)) throw new Error('invalid JSONPointer escape');
      const key = raw.replace(/~1/g, '/').replace(/~0/g, '~');
      if (!own(value, key)) throw new Error('JSONPointer value unavailable');
      value = value[key];
    }
    return value;
  };
  const sourceButton = (parent, path) => {
    const button = node('button', '↗ Inspect source', parent);
    button.type = 'button'; button.dataset.source = path;
    button.setAttribute('aria-label', 'Inspect source ' + path);
  };
  // Outcome source is the producer classification record; Search source is the search record.
  const failureSources = (parent, row) => {
    for (const [key, label, missing] of [
      ['outcome_ref', 'Outcome source', 'Classification evidence unavailable: no outcome record supplied'],
      ['ref', 'Search source', 'Search evidence unavailable: no search record supplied']]) {
      if (parent.childNodes.length) parent.append(' ');
      if (!row[key]) { node('span', '○ ' + missing, parent).className = 'note'; continue; }
      const button = node('button', '↗ ' + label, parent);
      button.type = 'button'; button.className = 'source'; button.dataset.source = row[key]; button.title = row[key];
      button.setAttribute('aria-label', 'Inspect ' + label + ' ' + row[key]);
    }
  };
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-source]');
    if (!button) return;
    inspect('Source: ' + button.dataset.source, body => {
      try { node('pre', JSON.stringify(resolve(button.dataset.source), null, 2), body); }
      catch (error) { node('p', '○ Source unavailable: ' + error.message, body); }
    });
  });
  for (const anchor of document.querySelectorAll('.skip, nav.tabs a')) {
    anchor.addEventListener('click', () => {
      const target = $(anchor.hash.slice(1));
      if (target) { focus(target); target.scrollIntoView({block: 'start'}); }
    });
  }

  // Supplied binding flags determine default selection. No outcome classification here.
  const fallback = parse($('failure-view-data'));
  const rows = view.failure_rows || fallback.rows || [];
  const filters = [...document.querySelectorAll('[data-filter]')];
  const scope = $('failure-scope');
  const sort = $('failure-sort');
  const valueOf = (row, key) => text(row[key]);
  const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const cellOf = row => Array.isArray(row.cell) ? row.cell.join(' / ') : text(row.cell);
  const fieldOf = (row, key) => key === 'cell' ? cellOf(row) : valueOf(row, key);
  const setOptions = (select, values) => {
    select.replaceChildren();
    for (const [value, label] of values) { const opt = node('option', label, select); opt.value = value; }
  };
  if (scope) {
    for (const select of filters) setOptions(select, [['*', 'All'], ...[...new Set(
      rows.map(row => fieldOf(row, select.dataset.filter)))].sort(compare).map(v => [v, v])]);
  }
  const table = (body, caption, headers, records) => {
    const t = node('table', null, body); node('caption', caption, t);
    const head = node('tr', null, node('thead', null, t));
    for (const h of headers) node('th', h, head).scope = 'col';
    const tb = node('tbody', null, t);
    for (const values of records) {
      const tr = node('tr', null, tb);
      for (const value of values) node('td', value, tr);
    }
    return t;
  };
  // Empty-selection recovery offers only actions that can select supplied inventory rows.
  const scopeLabel = value => scope.querySelector(`option[value="${value}"]`).textContent;
  const changedFilters = () => filters.filter(f => f.value !== '*').map(f =>
    `${f.closest('label')?.firstChild?.textContent.trim() || f.dataset.filter} = ${f.value}`);
  const recoveryButton = (id, label) => {
    if (!scope || !rows.length) return null;
    const button = document.createElement('button');
    button.type = 'button'; button.id = id; button.textContent = label;
    return button;
  };
  const inspectInventory = recoveryButton('inspect-available-inventory', 'Inspect available inventory');
  const clearChanged = recoveryButton('clear-changed-filters', 'Clear changed filters');
  const explainEmpty = body => {
    if (!rows.length) {
      node('p', '○ No GT inventory rows were supplied' + (own(files, 'frame.json') ? '' :
        ' (frame.json, which lists GT faces, is not among the inline source files)') +
        ', so there is nothing to select or filter; this does not establish absence of failures. ' +
        'Inspect the supplied source evidence with the ↗ Source buttons in ' +
        (document.querySelector('#verdict [data-source]') ? 'Verdict.' : 'Inline source files.'), body);
      return;
    }
    const inScope = rows.filter(row => scope.value === 'all' || row.default_visible === true).length;
    const unknown = rows.filter(row => row.outcome_available !== true).length;
    node('p', (inScope
      ? `○ Empty selection: none of the ${inScope} rows in scope ${scope.selectedOptions[0].textContent} matches the changed filters (${changedFilters().join('; ')})`
      : `○ Empty selection in primary scope (${scopeLabel('default')}): 0 of ${rows.length} GT inventory rows are in it, and ${unknown} of ${rows.length} are unclassified (outcome unknown)`) +
      `; this does not establish absence of failures. Inspect available inventory selects ${scopeLabel('all')} and clears changed filters; sort is kept.`, body);
    body.append(inspectInventory);
  };
  const announce = note => $('failure-counts').prepend(note + ' ');
  const legLabel = (parent, key) => {
    const parts = text(key).split('__');
    const names = new Map([['sface', 'SFace'], ['auraface', 'AuraFace'], ['insightface', 'InsightFace']]);
    parent.replaceChildren();
    node('strong', names.get(parts[0]) || parts[0], parent); parent.append(' ');
    node('span', parts.slice(1, 3).join(' · '), parent).className = 'note';
    const details = node('details', null, parent);
    node('summary', 'Leg contract', details); details.append(document.createTextNode(text(key)));
  };
  const drawFailures = () => {
    if (!scope) return;
    const selected = rows.filter(row => (scope.value === 'all' || row.default_visible === true) &&
      filters.every(f => f.value === '*' || fieldOf(row, f.dataset.filter) === f.value));
    const keys = sort.value === 'face' ? ['face_id', 'image_id', 'leg_key', 'arm', 'fold'] :
      ['image_id', 'face_id', 'leg_key', 'arm', 'fold'];
    selected.sort((a, b) => { for (const key of keys) { const n = compare(text(a[key]), text(b[key])); if (n) return n; } return 0; });
    const faces = new Set(selected.map(r => r.face_id)).size;
    const images = new Set(selected.map(r => r.image_id)).size;
    const unknown = selected.filter(r => r.outcome_available !== true).length;
    $('failure-counts').textContent = `Inventory: ${rows.length} rows. Eligible after filters: ${selected.length} rows, ${faces} faces, ${images} images. Selected: ${selected.length} rows, ${faces} faces, ${images} images. Shown ${selected.length}; omitted ${rows.length - selected.length} inventory rows; eligible omitted 0; offset 0; no limit. Scope: ${scope.selectedOptions[0].textContent}. Sort: ${sort.selectedOptions[0].textContent}.` +
      (unknown ? ` Outcome unknown (unclassified): ${unknown} of ${selected.length} selected rows.` : '') +
      (selected.length ? '' : ' Empty selection; this does not establish absence of failures.');
    const body = $('failure-table'); body.replaceChildren();
    if (!selected.length) explainEmpty(body);
    const t = table(body, 'GT inventory selection (outcomes supplied by producer)',
      ['Image identifier (image_id)', 'Face identifier (face_id)', 'Model', 'Search stage', 'Outcome / reason', 'Top-ranked identity', 'top-1 score', 'Fold', 'Fold role', 'Cell', 'Label tier', 'Source'],
      selected.map(r => [r.image_id, r.face_id, r.leg_key, r.stage ?? 'unknown',
        r.outcome_available === true ? r.outcome : '○ unclassified: ' + (r.outcome_reason || 'classification unavailable'),
        r.top1_identity, r.top1_score, r.fold, r.fold_role, cellOf(r), r.annotation_tier, '']));
    [...t.tBodies[0].rows].forEach((tr, i) => legLabel(tr.cells[2], selected[i].leg_key));
    [...t.tBodies[0].rows].forEach((tr, i) => failureSources(tr.lastElementChild, selected[i]));
  };
  if (scope) {
    for (const el of [scope, sort, ...filters]) el.addEventListener('change', drawFailures);
    $('reset-filters').textContent = '↩ Reset to primary scope';
    $('reset-filters').addEventListener('click', () => {
      scope.value = 'default'; sort.value = 'image'; filters.forEach(f => { f.value = '*'; }); drawFailures();
      announce('Reset to primary scope, all filters and default sort.');
    });
    if (clearChanged) {
      $('reset-filters').after(clearChanged);
      clearChanged.addEventListener('click', () => {
        const cleared = changedFilters();
        filters.forEach(f => { f.value = '*'; }); drawFailures();
        announce(cleared.length ? `Cleared changed filters (${cleared.join('; ')}); scope and sort kept.` :
          'No changed filters to clear; scope and sort kept.');
      });
      inspectInventory.addEventListener('click', () => {
        const cleared = changedFilters();
        scope.value = 'all'; filters.forEach(f => { f.value = '*'; }); drawFailures();
        announce(`Inspecting available inventory${cleared.length ? '; cleared ' + cleared.join('; ') : ''}; sort kept.`);
        const result = $('failure-table').querySelector('table');
        result.tabIndex = -1; focus(result);
      });
    }
    $('failure-pool').textContent = JSON.stringify(view.failure_pool || fallback.pool || {}, null, 2);
    drawFailures();
  } else if (Array.isArray(view.failure_rows) && !rows.length && $('failures')) {
    // The producer renders no filter view for zero inventory; state that result and an evidence path that works.
    const status = node('p', 'Inventory: 0 rows. Selected: 0 rows, 0 faces, 0 images. ' +
      'Empty selection; this does not establish absence of failures.');
    status.id = 'failure-counts'; status.setAttribute('aria-live', 'polite');
    const body = node('div'); body.id = 'failure-table'; explainEmpty(body);
    const fallbackTable = $('failures').querySelector(':scope > table');
    if (fallbackTable) fallbackTable.before(status, body); else $('failures').append(status, body);
  }
  // Existing mapped cell/stage -> failures -> back handoffs; preserve the prior filter state.
  let origin = null;
  const handoff = (button, criteria) => {
    origin = {context: snapshot(), values: [scope, sort, ...filters].map(el => el.value)};
    scope.value = 'default'; filters.forEach(el => { el.value = '*'; });
    for (const [key, value] of Object.entries(criteria)) {
      const select = filters.find(el => el.dataset.filter === key);
      if (select && ![...select.options].some(opt => opt.value === value)) {
        const opt = node('option', value, select); opt.value = value;
      }
      if (select) select.value = value;
    }
    drawFailures();
    $('back-to-origin').hidden = false;
    $('back-to-origin').textContent = '↩ Back to ' + (button.dataset.origin === 'stages' ? 'stage ledger' : 'pair cells');
    focus($('failures')); $('failures').scrollIntoView();
  };
  if (scope) {
    $('back-to-origin').addEventListener('click', () => {
      if (!origin) return;
      [scope, sort, ...filters].forEach((el, i) => { el.value = origin.values[i]; });
      drawFailures(); $('back-to-origin').hidden = true;
      restore(origin.context); origin = null;
    });
    const scores = files['scores.json'];
    if (scores) {
      const cellRows = document.querySelectorAll('#pair-cells tbody tr');
      (scores.cells || []).forEach((cell, i) => {
        if (!cellRows[i]) return;
        const button = node('button', '↗ Open failures for this cell and leg', cellRows[i].lastElementChild);
        button.type = 'button'; button.dataset.origin = 'pair-cells';
        button.addEventListener('click', () => handoff(button, {leg_key: cell.leg_key, cell: cell.query_occluder + ' / ' + cell.enrolled_occluder}));
      });
      const stageTable = document.querySelector('#stages table');
      for (const tr of stageTable?.tBodies[0]?.rows || []) {
        const [leg, arm, stage] = [...tr.cells].map(c => c.textContent);
        const button = node('button', '↗ Open failures for this stage', tr.lastElementChild);
        button.type = 'button'; button.dataset.origin = 'stages';
        button.addEventListener('click', () => handoff(button, {leg_key: leg, arm, stage}));
      }
    }
  }

  // Exploration selects existing descriptive points only; the frozen readout is never edited.
  const frame = files['frame.json'];
  const scores = files['scores.json'];
  const curves = (scores?.curves || []).filter(c => c.points?.length);
  const explore = $('explore-tau');
  let exploration = null;
  const legSelect = $('explore-leg'), pointSelect = $('explore-point');
  const drawPoint = () => {
    const curve = curves[Number(legSelect.value)];
    const point = curve?.points[Number(pointSelect.value)];
    if (!point) return;
    $('explore-readout').textContent = `Recorded descriptive point · ${curve.leg_key} · τ ${text(point.threshold)} · FNIR ${text(point.fnir)} · FPIR ${text(point.fpir)}. Support and intervals: frozen evidence above; no new inference.`;
  };
  const chooseLeg = () => {
    const curve = curves[Number(legSelect.value)];
    setOptions(pointSelect, curve.points.map((p, i) => [String(i), 'τ ' + text(p.threshold)]));
    const tau = scores.legs.find(l => l.leg_key === curve.leg_key)?.tau;
    const frozenIndex = tau?.status === 'available' ? curve.points.findIndex(p => p.threshold === tau.data.value) : -1;
    pointSelect.value = String(frozenIndex >= 0 ? frozenIndex : 0); drawPoint();
  };
  const exitExplore = () => {
    if (!exploration) return;
    $('tau-explorer').hidden = true; explore.setAttribute('aria-expanded', 'false');
    legSelect.value = exploration.leg; chooseLeg(); pointSelect.value = exploration.point;
    $('explore-readout').textContent = exploration.readout;
    restore(exploration.context); exploration = null;
  };
  if (explore) {
    explore.setAttribute('aria-controls', 'tau-explorer'); explore.setAttribute('aria-expanded', 'false');
    if (scores?.admissibility === 'development' && frame?.admissibility === 'development' && frame.sealed === false && curves.length) {
      explore.disabled = false;
      $('explore-status').textContent = '○ Development, unsealed: inspect recorded points; nothing is saved.';
      setOptions(legSelect, curves.map((c, i) => [String(i), c.leg_key])); chooseLeg();
    }
    explore.addEventListener('click', () => {
      if (exploration) { focus(pointSelect); return; }
      exploration = {context: snapshot(), leg: legSelect.value, point: pointSelect.value, readout: $('explore-readout').textContent};
      $('tau-explorer').hidden = false; explore.setAttribute('aria-expanded', 'true'); focus(legSelect);
    });
    legSelect.addEventListener('change', chooseLeg); pointSelect.addEventListener('change', drawPoint);
    $('exit-explore').addEventListener('click', exitExplore);
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && event.target.closest('dialog') == null && !dialog.open && exploration && !event.defaultPrevented) { event.preventDefault(); exitExplore(); }
    });
  }

  // Pair inspection stays available without a projection; aliases are joined to actual FRAME GT.
  const gtFaces = new Map((frame?.faces || []).map(face => [face.face_id, face]));
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-inspect-pair]');
    if (!button) return;
    const [legIndex, pairIndex] = button.dataset.inspectPair.split(':').map(Number);
    const embedded = document.querySelector(`script[data-chaining-leg="${legIndex}"]`);
    const leg = files['clusters.json']?.legs[legIndex] || parse(embedded);
    const pair = leg.chaining?.data?.pairs[pairIndex];
    if (!pair) return;
    inspect('Chaining pair ' + pair.pair_id, body => {
      const scope = leg.chaining.data.scope;
      node('p', `Held-out frame ${scope.frame_id}, fold ${scope.fold} (${scope.fold_role}). Independently verified different endpoints; identity is never inferred from co-assignment.`, body);
      const alias = endpoint => {
        const gt = gtFaces.get(endpoint.face_id);
        return `${endpoint.face_id} · image ${text(gt?.image_id)} · identity ${text(endpoint.identity_id)} · verification ${text(endpoint.verification_ref)}`;
      };
      node('p', 'Left: ' + alias(pair.left) + '; right: ' + alias(pair.right), body);
      node('p', `Path linked: ${pair.path_linked}; third identity: ${text(pair.third_identity_id)}; through third identity: ${pair.through_third_identity}`, body);
      node('p', 'Production threshold and link rule (as recorded): ' + JSON.stringify(leg.config), body);
      if (!pair.path?.length) node('p', '○ No recorded linking path.', body);
      const pathTable = table(body, 'Ordered path in original leg space',
        ['Order', 'face_id', 'image_id', 'identity_id', 'Identity status', 'Third identity', 'Verification'],
        (pair.path || []).map((p, i) => [i + 1, p.face_id, gtFaces.get(p.face_id)?.image_id,
          p.identity_id, p.identity_status, pair.through_third_identity === true && pair.third_identity_id != null && p.identity_id === pair.third_identity_id ? '✓ third identity' : '', p.verification_ref]));
      pathTable.dataset.zone = 'neighbour-table';
      table(body, 'Recorded path edges (original leg space)', ['Order', 'Source', 'Target', 'Cosine'],
        pair.edges.map((e, i) => [i + 1, e.source_face_id, e.target_face_id, e.cosine_similarity]));
      if (leg.neighbours?.status === 'available') {
        table(body, 'Recorded nearest neighbours in original leg space (source order)',
          ['Source face', 'Source image', 'Target face', 'Target image', 'Cosine'],
          leg.neighbours.data.edges.map(e => [e.source_face_id, gtFaces.get(e.source_face_id)?.image_id,
            e.target_face_id, gtFaces.get(e.target_face_id)?.image_id, e.cosine_similarity]));
      } else node('p', '○ Neighbour evidence unavailable.', body);
      sourceButton(body, `clusters.json#/legs/${legIndex}/chaining/data/pairs/${pairIndex}`);
    });
  });
})();
"""


def _page(
    title: str, body_sections: Sequence[tuple[str, str]], verdict_html: str, *,
    view_data: Mapping[str, Any] | None = None,
) -> str:
    nav = " ".join(f'<a href="#{sid}">{_e(label)}</a>' for sid, label in _SECTIONS)
    sections = "\n".join(
        f'<section id="{sid}" tabindex="-1" aria-label="{_e(label)}"><h2>{_e(label)}</h2>\n{content}\n</section>'
        for (sid, label), (_, content) in zip(_SECTIONS, body_sections, strict=True)
    )
    source_files = (view_data or {}).get("files", {})
    provenance = (
        '<details class="provenance"><summary>Inline source files</summary><ul>'
        + ''.join(f'<li>{_e(name)} {_code(name + "#")}</li>' for name in sorted(source_files))
        + '</ul></details>'
    ) if source_files else '<p class="note">○ Inline source files unavailable.</p>'
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; '
        'script-src &#39;unsafe-inline&#39;; style-src &#39;unsafe-inline&#39;; '
        'img-src data:; connect-src &#39;none&#39;; base-uri &#39;none&#39;; form-action &#39;none&#39;">\n'
        f"<title>{_e(title)}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n"
        '<a class="skip" href="#verdict">Skip to verdict</a>\n'
        f'<header><h1>FIRBENCH-1 report</h1></header>\n<nav class="tabs" aria-label="Report sections">{nav}</nav>\n'
        '<p><a href="#glossary">Report glossary</a></p>\n'
        f'{provenance}<main>\n<section id="verdict" tabindex="-1" aria-label="Verdict"><h2>Verdict</h2>\n'
        '<p>Compare recorded model outcomes under the recorded decision policy. '
        + term_link('fnir', 'Missed enrolled-person searches (FNIR)') + '; '
        + term_link('fpir', 'False identifications (FPIR)') + '; '
        + term_link('admissibility', 'Permitted frame use') + '; '
        + term_link('native', 'Native processing') + '; '
        + term_link('gt-crop-redetect', 'GT-crop redetect') + '; '
        + term_link('cached-landmark-replay', 'Cached landmark replay') + '.</p>\n'
        + f'{verdict_html}\n</section>\n{sections}\n{render_glossary()}\n</main>\n'
        '<dialog id="source-inspector" aria-labelledby="inspector-title">'
        '<h2 id="inspector-title">Inspection</h2>'
        '<button type="button" id="close-inspector">↩ Close inspection (Esc)</button>'
        '<div id="inspector-body"></div></dialog>\n'
        '<script type="application/json" id="report-view-data">'
        + _ui_json(view_data or {}) + '</script>\n<script>' + _ui_script() + '</script>\n</body>\n</html>\n'
    )


def _csv_text(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()


def _legs_csv(scores: Mapping[str, Any]) -> str:
    rows = []
    for leg in scores["legs"]:
        op = leg["operating_point"]
        fnir = op["fnir"].get("data") or {}
        fpir = op["fpir"].get("data") or {}
        rows.append(
            [
                leg["leg_key"],
                scores["admissibility"],
                fnir.get("n_eff"),
                fnir.get("misses"),
                fnir.get("n_mated"),
                fpir.get("fpi"),
                fpir.get("n_units"),
            ]
        )
    return _csv_text(["leg_key", "admissibility", "n_eff", "misses", "n_mated", "fpi", "n_units"], rows)


def _assert_finite_tree(value: object, where: str) -> None:
    """Refuse any non-finite number in a parsed or emitted value; iterative, so depth cannot escape."""
    stack: list[object] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, float):
            if not math.isfinite(item):
                raise FrameContractError(f"{where}: non-finite JSON number refused")
        elif isinstance(item, Mapping):
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)


def _binding_json(raw: bytes, where: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise FrameContractError(f"{where}: duplicate JSON key {key}")
            result[key] = value
        return result

    def constant(value: str) -> Any:
        raise FrameContractError(f"{where}: non-finite JSON constant {value}")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError) as exc:
        raise FrameContractError(f"{where}: malformed JSON: {exc}") from exc
    _assert_finite_tree(value, where)
    return value


def _binding_file(run: Path, name: str) -> Path:
    path = run / name
    if Path(name).is_absolute() or ".." in Path(name).parts:
        raise FrameContractError("run artifact must be run-local")
    current = run
    for part in Path(name).parts:
        current /= part
        if current.is_symlink():
            raise FrameContractError(f"run artifact symlink refused: {name}")
    if not path.resolve().is_relative_to(run):
        raise FrameContractError(f"run artifact escapes run: {name}")
    return path


def _comparison_html(comparison: Mapping[str, Any] | None) -> str:
    if comparison is None:
        return "<p>comparison.json unavailable: no run-local comparison supplied.</p>"
    rows = []
    for index, row in enumerate(comparison["paired_deltas"]):
        rows.append(
            [
                _e(row[k])
                for k in (
                    "leg_kind",
                    "leg_key_a",
                    "leg_key_b",
                    "status",
                    "reason",
                    "n_searches",
                    "n_psu",
                    "n_eff",
                    "point",
                    "lower",
                    "upper",
                )
            ]
            + [_code(_jp("comparison.json", "paired_deltas", index))]
        )
    # Canon v0.26.2 INT-22 / VIZ-23: expose the recorded result and its evidence,
    # independently of per-leg scoring status or the original run verdicts.
    state = comparison["comparison_state"]
    glyph = {"comparable": "↔", "exploratory": "△"}[state]
    treatment = comparison["treatment"]
    summary = (
        f'<p><strong>Input comparability:</strong> <span class="st">{glyph} {_e(state)}</span> '
        f"{_code(_jp('comparison.json', 'comparison_state'))}</p>"
        f"<p>Declared treatment name: {_e(treatment['name']) if treatment['name'] is not None else 'none'} "
        f"{_code(_jp('comparison.json', 'treatment', 'name'))}; "
        f"Declared treatment fields: {_e(', '.join(treatment['fields']) or 'none')} "
        f"{_code(_jp('comparison.json', 'treatment', 'fields'))}.</p>"
        f"<p>{_e(comparison['label'])}. Descriptive contrasts only; no posthoc winner.</p>"
        f"<p>Runs {_e(comparison['run_a']['run_id'])} / {_e(comparison['run_b']['run_id'])}; "
        f"differences: {_e(', '.join(comparison['differences']) or 'none')} "
        f"{_code(_jp('comparison.json', 'differences'))}. "
        f"Original run states: {_e(json.dumps(comparison['verdicts'], sort_keys=True))}.</p>"
        "<p>Input compatibility does not establish inferential scoring eligibility; "
        "the recorded per-leg status and reason below apply.</p>"
    )
    deltas = _table(
        "Recorded per-leg contrasts",
        [
            "kind",
            "leg A",
            "leg B",
            "status",
            "reason",
            "searches",
            "PSUs",
            "n_eff",
            "point",
            "lower",
            "upper",
            "JSON path",
        ],
        rows,
    )
    history = []
    for index, row in enumerate(comparison["history"]):
        for j, point in enumerate(row["points"]):
            history.append(
                [_e(row["leg_kind"]), _e(row["leg_key"])]
                + [_e(point[k]) if point[k] is not None else "null" for k in ("run_id", "fnir", "tau", "reason")]
                + [_code(_jp("comparison.json", "history", index, "points", j))]
            )
    spread = []
    for index, row in enumerate(comparison["tau_spread"]):
        spread.append(
            [_e(row[k]) if row[k] is not None else "null" for k in ("leg_kind", "run_id", "status", "reason")]
            + [
                _e(json.dumps(row["values"], sort_keys=True)),
                _e(row["minimum"]) if row["minimum"] is not None else "null",
                _e(row["maximum"]) if row["maximum"] is not None else "null",
                _code(_jp("comparison.json", "tau_spread", index)),
            ]
        )
    changes = [
        [_e(row[k]) for k in ("leg_kind", "leg_key_a", "leg_key_b", "label")]
        + [_code(_jp("comparison.json", "leg_changes", i))]
        for i, row in enumerate(comparison["leg_changes"])
    ]
    return (
        summary
        + deltas
        + _table(
            "Supplied history (no interpolation)", ["kind", "leg", "run", "FNIR", "tau", "reason", "JSON path"], history
        )
        + _table(
            "Recorded tau spread (absence stays unavailable)",
            ["kind", "run", "status", "reason", "values", "minimum", "maximum", "JSON path"],
            spread,
        )
        + _table("Leg contract changes", ["kind", "leg A", "leg B", "label", "JSON path"], changes)
    )


def _binding_comparison(comparison: Mapping[str, Any]) -> None:
    validate_interchange("comparison-v1", comparison)
    for row in comparison["paired_deltas"]:
        if row["status"] == "scored" and not row["lower"] <= row["point"] <= row["upper"]:
            raise FrameContractError("comparison-v1 interval ordering mismatch")
    if len(set(comparison["differences"])) != len(comparison["differences"]):
        raise FrameContractError("comparison-v1 duplicate differences")
    for row in comparison["tau_spread"]:
        values = [r["tau"] for r in row["values"]]
        if values and (min(values) != row["minimum"] or max(values) != row["maximum"]):
            raise FrameContractError("comparison-v1 tau spread bounds mismatch")


def _binding_crops(
    run: Path,
    frame: Mapping[str, Any] | None,
    rows: list[dict[str, Any]],
    files: dict[str, Any],
    inputs: dict[str, str],
    *,
    enabled: bool,
) -> str | None:
    """Optional crop-artifacts/v1 manifest: exact keys, run-local PNG/JPEG, at most 256 KiB each.

    {schema, frame_sha256, artifacts:[{face_id,image_id,source_sha256,path,sha256,mime}]}
    No acquisition or source-image reopening. Crops off returns before any artifact IO.
    """
    from typing import Literal, TypedDict

    class CropArtifact(TypedDict):
        face_id: str
        image_id: str
        source_sha256: str
        path: str
        sha256: str
        mime: Literal["image/png", "image/jpeg"]

    class CropManifest(TypedDict):
        schema: Literal["firbench-crop-artifacts/v1"]
        frame_sha256: str
        artifacts: list[CropArtifact]

    if not enabled:
        return "crops_disabled"
    path = _binding_file(run, "crop-artifacts.json")
    if not path.is_file():
        return "crop_artifacts_absent"
    if path.stat().st_size > 1024 * 1024:
        raise FrameContractError("crop manifest exceeds 1 MiB")
    raw = path.read_bytes()
    if len(raw) > 1024 * 1024:
        raise FrameContractError("crop manifest exceeds 1 MiB")
    manifest: CropManifest = _binding_json(raw, path.name)
    if not isinstance(manifest, dict) or set(manifest) != {"schema", "frame_sha256", "artifacts"}:
        raise FrameContractError("crop manifest exact fields required")
    if manifest["schema"] != "firbench-crop-artifacts/v1" or manifest["frame_sha256"] != inputs.get("frame.json"):
        raise FrameContractError("crop manifest FRAME binding mismatch")
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) > 10000:
        raise FrameContractError("crop artifact inventory must be bounded at 10000 records")
    faces, images, *_ = _binding_frame(frame)
    seen = set()
    total = 0
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {
            "face_id",
            "image_id",
            "source_sha256",
            "path",
            "sha256",
            "mime",
        }:
            raise FrameContractError("crop artifact exact fields required")
        if any(not isinstance(v, str) or not v for v in item.values()):
            raise FrameContractError("crop artifact fields must be nonempty strings")
        face = faces.get(item["face_id"])
        if face is None or face["image_id"] != item["image_id"] or item["face_id"] in seen:
            raise FrameContractError("crop artifact GT/image binding mismatch or duplicate")
        seen.add(item["face_id"])
        if item["source_sha256"] != images[item["image_id"]]["sha256"]:
            raise FrameContractError("crop artifact source SHA mismatch")
        relative = Path(item["path"])
        if len(relative.parts) < 2 or relative.parts[0] != "crops" or item["mime"] not in {"image/png", "image/jpeg"}:
            raise FrameContractError("crop artifact must be an explicit crops/ PNG or JPEG")
        crop = _binding_file(run, item["path"])
        size = crop.stat().st_size
        total += size
        if size > 256 * 1024 or total > 16 * 1024 * 1024:
            raise FrameContractError("crop artifact bytes exceed bounded manifest budget")
        data = crop.read_bytes()
        valid_magic = (
            data.startswith(b"\x89PNG\r\n\x1a\n") if item["mime"] == "image/png" else data.startswith(b"\xff\xd8\xff")
        )
        if not valid_magic or _sha256_bytes(data) != item["sha256"]:
            raise FrameContractError("crop artifact MIME/SHA mismatch")
        # Validate only the bounded in-memory crop; never open a source/query image.
        import base64

        from PIL import Image

        try:
            with Image.open(io.BytesIO(data)) as decoded:
                expected_format = "PNG" if item["mime"] == "image/png" else "JPEG"
                if (
                    decoded.format != expected_format
                    or not 0 < decoded.width <= 1024
                    or not 0 < decoded.height <= 1024
                    or getattr(decoded, "n_frames", 1) != 1
                ):
                    raise FrameContractError("crop artifact format/dimensions exceed bounded still-crop contract")
                decoded.verify()
        except (OSError, SyntaxError, ValueError) as exc:
            raise FrameContractError(f"crop artifact invalid image: {exc}") from exc
        inputs[item["path"]] = _sha256_bytes(data)
        uri = "data:" + item["mime"] + ";base64," + base64.b64encode(data).decode("ascii")
        for row in rows:
            if row["face_id"] == item["face_id"]:
                row["crop_data_uri"] = uri
                row["crop_ref"] = item["path"]
    files[path.name] = manifest
    inputs[path.name] = _sha256_bytes(raw)
    for row in rows:
        if "crop_data_uri" not in row:
            row["crop_reason"] = "crop_artifact_absent_for_GT_face"
    return None


def _binding_table_exports(sections: Sequence[tuple[str, str]]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    # Export the actual rendered evidence tables, including withheld values/reasons.
    from html.parser import HTMLParser

    class Tables(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.tables: list[tuple[str, list[list[str]]]] = []
            self.rows: list[list[str]] | None = None
            self.row: list[str] | None = None
            self.cell: list[str] | None = None
            self.caption: list[str] | None = None
            self.name = ""

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "table":
                self.rows = []
                self.name = ""
            elif tag == "caption" and self.rows is not None:
                self.caption = []
            elif tag == "tr" and self.rows is not None:
                self.row = []
            elif tag in {"td", "th"} and self.row is not None:
                self.cell = []

        def handle_data(self, data: str) -> None:
            if self.cell is not None:
                self.cell.append(data)
            if self.caption is not None:
                self.caption.append(data)

        def handle_endtag(self, tag: str) -> None:
            if tag in {"td", "th"} and self.cell is not None:
                self.row.append("".join(self.cell).strip())
                self.cell = None
            elif tag == "caption" and self.caption is not None:
                self.name = "".join(self.caption).strip()
                self.caption = None
            elif tag == "tr" and self.row is not None:
                self.rows.append(self.row)
                self.row = None
            elif tag == "table" and self.rows is not None:
                self.tables.append((self.name, self.rows))
                self.rows = None

    exports, inventory = {}, []
    for section, content in sections:
        parser = Tables()
        parser.feed(content)
        for index, (caption, rows) in enumerate(parser.tables):
            filename = f"table-{section}-{index + 1:02d}.csv"
            exports[filename] = _csv_text(rows[0] if rows else [], rows[1:])
            inventory.append(
                {"filename": filename, "section": section, "caption": caption, "n_rows": max(0, len(rows) - 1)}
            )
    return exports, inventory


def render_report(run_dir: Path | str, *, out_dir: Path | str, include_crops: bool = False) -> Path:
    """Render validated frozen files. Crops off performs no crop manifest or pixel reads."""
    lexical_run = Path(run_dir).absolute()
    repo = _repo_root_for(lexical_run)
    run = require_private_output_path(lexical_run, repo_root=repo)
    target = require_private_output_path(out_dir, repo_root=repo)
    if lexical_run.is_symlink():
        raise FrameContractError("run directory symlink refused")
    files: dict[str, Any] = {}
    inputs: dict[str, str] = {}

    def load(name: str, schema: str | None = None, *, required: bool = False) -> Any:
        path = _binding_file(run, name)
        if not path.is_file():
            if required:
                raise FrameContractError(f"required run artifact unavailable: {name}")
            return None
        raw = path.read_bytes()
        value = _binding_json(raw, name)
        if not isinstance(value, dict):
            raise FrameContractError(f"{name}: JSON object required")
        if schema:
            validate_interchange(schema, value)
        files[name] = value
        inputs[name] = _sha256_bytes(raw)
        return value

    scores = load("scores.json", "scores-v1", required=True)
    frame = load("frame.json", "frame-v1")
    clusters = load("clusters.json", "clusters-v1")
    manifest = load("manifest.json")
    comparison = load("comparison.json", "comparison-v1")
    if comparison is not None:
        _binding_comparison(comparison)
    created, _source = _semantic_created_at(manifest)
    if frame is not None and (
        frame["frame_id"] != scores["frame_id"] or frame["admissibility"] != scores["admissibility"]
    ):
        raise FrameContractError("scores/FRAME identity or admissibility mismatch")
    block = (manifest or {}).get("firbench", {})
    if "decision_sha256" in block and block["decision_sha256"] != scores["decision_sha256"]:
        raise FrameContractError("scores/manifest decision SHA mismatch")
    if frame is not None and "frame" in block:
        for key in ("frame_id", "admissibility", "exhaustive", "sealed", "source_sha256"):
            if block["frame"].get(key) != frame[key]:
                raise FrameContractError(f"manifest/FRAME {key} mismatch")
    scopes = _binding_scopes(scores, manifest)
    searches, search_sources = _load_searches(run, list(scopes))
    for leg in scopes:
        name = f"legs/{leg}/searches.jsonl"
        if name not in search_sources:
            if "face_outcomes" in scores:
                raise FrameContractError(f"required declared leg searches unavailable: {name}")
            continue
        raw = search_sources[name]
        inputs[name] = _sha256_bytes(raw)
        files[name] = [{key: value for key, value in row.items() if key != "_ref"}
                       for row in searches if row["leg_key"] == leg]
    _binding_frame(frame)
    qualification = _binding_label_evidence(
        run,
        frame,
        block.get("label_evidence"),
        frame_sha256=inputs.get("frame.json"),
        files=files,
        inputs=inputs,
    )
    failure_rows, background = _failures_rows(
        searches, frame, scores=scores, manifest=manifest, qualification=qualification
    )
    crop_reason = _binding_crops(run, frame, failure_rows, files, inputs, enabled=include_crops)
    pool = _pool(frame, failure_rows, include_crops=include_crops)
    pool["crop_reason"] = crop_reason
    pool["background_detector_rows"] = background
    if "face_outcomes" in scores:
        for leg, counts in pool["scope_counts_by_leg"].items():
            if counts["unresolved"]:
                continue
            fixed = pool["primary_background_source_units"]
            if fixed is not None and fixed + counts["nonmated"] != scores["n_units"]:
                raise FrameContractError(f"{leg}: fixed source units do not reconcile with scores n_units")
    if "face_outcomes" not in scores:
        pool["classification_status"] = "unavailable"
        pool["classification_reason"] = "legacy_face_outcomes_unavailable"

    # A receipt is immutable assessment input; never recompute a p95 or rewrite it.
    receipt_refs = {g["timings_sha256"] for g in scores["guardrails"] if g.get("timings_sha256")}
    if receipt_refs:
        timings = load("timings.json", required=True)
        if receipt_refs != {inputs["timings.json"]}:
            raise FrameContractError("timings.json does not match pinned scores timing receipt SHA")
        values = timings.get("timing_receipt_ms")
        if not isinstance(values, dict) or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
            for v in values.values()
        ):
            raise FrameContractError("timings.json requires finite nonnegative receipt milliseconds")

    withheld_reason, withheld_cells = _binding_analytic_withholding(
        frame, failure_rows, scores, qualification=qualification
    )
    unratified = scores["verdict"]["state"] == VerdictState.unratified
    verdict_html = (
        _verdict_html(scores)
        + _leg_table(scores)
        + _hypotheses_html(scores)
        + _guardrails_html(scores)
        + _decision_path_html(scores)
    )
    if withheld_reason:
        verdict_html = (
            f"<p>Analytic display withheld: {_e(withheld_reason)}. "
            "Original producer states remain available in scores.json.</p>"
        )
    default_rows = [r for r in failure_rows if r["default_visible"]]
    failure_note = (
        f"<p>GT inventory: {pool['inventory_rows']} rows, {pool['inventory_faces']} distinct faces, "
        f"{pool['inventory_images']} distinct images. Overall FRAME: {_e(pool['overall_gt_faces'])} GT faces, "
        f"{_e(pool['overall_images'])} images; unresolved {pool['unresolved_identity_faces']}. "
        f"Default: qualified probability/test/native failures; eligible {pool['eligible_rows']} rows, "
        f"selected {pool['shown_rows']}, omitted {pool['omitted_rows']}; no cap. "
        f"Fixed background source units: {_e(pool['fixed_background_source_units'])}; "
        f"detector-only rows: {background} (never GT). "
        f"Classification {_e(pool['classification_status'])}: {_e(pool['classification_reason'])}. "
        f"Unclassified rows: {pool['unclassified_rows']}; crops: {_e(crop_reason)}.</p>"
    )
    if withheld_reason:
        failure_note += f"<p>Analytic selection withheld: {_e(withheld_reason)}.</p>"
    if pool["reason"]:
        failure_note += f"<p>Inventory qualification limits: {_e(pool['reason'])}.</p>"
    if pool["classification_status"] == "unavailable":
        failure_note += "<p>classification unavailable: no all-clear claim can be made from this run.</p>"
    # Full GT inventory is retained for UI filters, separately from the default selection.
    inventory_columns = [
        "image_id",
        "face_id",
        "leg_key",
        "arm",
        "fold",
        "fold_role",
        "sampling_arm",
        "identity_status",
        "mated",
        "stage",
        "outcome",
        "outcome_reason",
        "qualified",
        "qualification_reason",
        "default_visible",
    ]
    scope_keys = ("fold_role", "sampling_arm", "arm", "leg_key")
    scopes = sorted(
        {tuple(r[k] for k in scope_keys) for r in failure_rows},
        key=lambda scope: tuple(value or "" for value in scope),
    )
    failure_html = failure_note
    failure_html += _table(
        "Default qualified probability/test/native failures",
        [*inventory_columns, "JSON path"],
        [
            [_e(r.get(key)) if r.get(key) is not None else "null" for key in inventory_columns]
            + [_code(r["outcome_ref"] or r["ref"])]
            for r in default_rows
        ],
    )
    failure_html += "<details><summary>Full GT inventory by declared scope (metadata and diagnostics)</summary>"
    for scope in scopes:
        scoped_rows = [r for r in failure_rows if tuple(r[k] for k in scope_keys) == scope]
        failure_html += _table(
            " / ".join(value if value is not None else "unknown" for value in scope),
            [*inventory_columns, "JSON path"],
            [
                [_e(r.get(key)) if r.get(key) is not None else "null" for key in inventory_columns]
                + [_code(r["outcome_ref"] or r["ref"])]
                for r in scoped_rows
            ],
        )
    failure_html += "</details>"
    displayed_crops = {r["face_id"]: r for r in default_rows if r.get("crop_data_uri")}
    for face_id, row in sorted(displayed_crops.items()):
        failure_html += (
            f"<p>{_e(face_id)} {_code(row['crop_ref'])}</p>"
            f'<img src="{_e(row["crop_data_uri"])}" alt="Validated run-local crop {_e(face_id)}">'
        )
    ui_ready = (
        "view_data" in _page.__code__.co_varnames[: _page.__code__.co_argcount + _page.__code__.co_kwonlyargcount]
    )
    if failure_rows and ui_ready:
        failure_html += _failures_html(frame, failure_rows, background, include_crops=include_crops)
    coverage = ""
    if clusters is not None:
        for index, leg in enumerate(clusters["legs"]):
            value = leg.get("vector_coverage")
            coverage += (
                f"<p>{_e(leg['leg_key'])}: "
                + (
                    _e(json.dumps(value, sort_keys=True))
                    if value is not None
                    else "vector coverage unknown (not recorded)"
                )
                + f" {_code(_jp('clusters.json', 'legs', index, 'vector_coverage'))}</p>"
            )
    sections = [
        (
            "curves",
            f"<p>Analytic curves withheld: {_e(withheld_reason)}</p>"
            if withheld_reason
            else _curves_html(scores, unratified=unratified),
        ),
        ("pair-cells", _cells_html(scores, withheld_cells=withheld_cells)),
        ("stages", _stages_html(scores)),
        ("failures", failure_html),
        (
            "clusters",
            coverage
            + (
                f"<p>Analytic diagnostics withheld: {_e(withheld_reason)}</p>"
                if withheld_reason
                else _clusters_html(clusters)
            ),
        ),
        (
            "compare",
            f"<p>Analytic comparison withheld: {_e(withheld_reason)}</p>"
            if withheld_reason
            else _comparison_html(comparison),
        ),
        ("frames-power", _frames_html(scores, frame, created, unratified=unratified)),
    ]
    view_data = {
        "files": files,
        "failure_rows": failure_rows,
        "failure_pool": pool,
        "background": background,
        "inputs": dict(sorted(inputs.items())),
    }
    dependencies = []
    if "face_outcomes" not in scores:
        dependencies.append("scores face_outcomes producer/schema unavailable or legacy run")
    if withheld_reason:
        dependencies.append(withheld_reason)
    if frame is not None:
        dependencies.extend(sorted({
            reason
            for face in frame["faces"]
            if face["annotation"]["annotation_tier"] == "a"
            for qualified, reason in [_binding_qualification(face, frame, qualification=qualification)]
            if not qualified and reason not in dependencies
        }))
    title = f"FIRBENCH-1 report · {scores['frame_id']}"
    if ui_ready:
        page = _page(title, sections, verdict_html, view_data=view_data)
    else:
        dependencies.append("UI _page view_data seam unavailable; source inspector and filters pending")
        page = _page(title, sections, verdict_html)
    tables, exports = _binding_table_exports([("verdict", verdict_html), *sections])
    # Keep existing machine-readable filenames; rendered tables have their own exact exports.
    tables.update(
        {
            "legs.csv": _legs_csv(scores)
            if not withheld_reason
            else _csv_text(["status", "reason"], [["withheld", withheld_reason]]),
            "curves.csv": _csv_text(
                ["leg_key", "threshold", "fpir", "fnir"],
                [[c["leg_key"], p["threshold"], p["fpir"], p["fnir"]] for c in scores["curves"] for p in c["points"]]
                if not withheld_reason
                else [],
            ),
            "failures.csv": _csv_text(
                inventory_columns, [[r.get(key) for key in inventory_columns] for r in failure_rows]
            ),
        }
    )
    tables["cells.csv"] = tables["table-pair-cells-01.csv"]
    tables["waterfall.csv"] = tables["table-stages-01.csv"]
    tables["icc_sensitivity.csv"] = tables["table-frames-power-02.csv"]
    report = {
        "schema_version": 1,
        "frame_id": scores["frame_id"],
        "admissibility": scores["admissibility"],
        "decision_sha256": scores["decision_sha256"],
        "verdict": scores["verdict"],
        "inputs": dict(sorted(inputs.items())),
        "label_evidence": block.get("label_evidence"),
        "comparison": comparison,
        "failures": {"pool": pool, "rows": failure_rows, "background_units_detector_only": background},
        "frames": {"created_at": created, "global_floor_met": _floor_ok(scores)},
        "table_exports": exports,
        "dependencies_pending": dependencies,
    }
    report_text = _strict_json(report, where="report.json", indent=2, ensure_ascii=False) + "\n"
    # Complete validation precedes every write; refuse redirected existing artifacts.
    for name in ("index.html", "report.json", *tables):
        destination = target / name
        require_private_output_path(destination, repo_root=repo)
        if destination.is_symlink():
            raise FrameContractError(f"report artifact symlink refused: {name}")
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.html").write_text(page, encoding="utf-8")
    (target / "report.json").write_text(report_text, encoding="utf-8")
    for name, text in sorted(tables.items()):
        (target / name).write_text(text, encoding="utf-8")
    return target / "index.html"
