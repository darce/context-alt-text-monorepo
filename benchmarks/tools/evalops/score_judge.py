"""Score EVALOPS review findings against explicit blinded human labels (stdlib).

API: score(findings, predictions=None, qc=None, *, protocol=None) -> dict.
No input is modified. ValueError means invalid schema. No quality threshold is
invented: quality_acceptance is always not_evaluated. Rollback is git revert;
operator labels and QC events must be retained.

CLI: --findings FILE [--predictions FILE] [--qc FILE] [--output FILE]
Findings are JSONL objects in the findings-v0 schema. Required fields: id,
finding_db_id, finding_id, task_ref, severity, review_mode, stratum,
stratum_population, stratum_sample, weight, human_label, human_note. Original
seed descriptive fields may remain; prelabels and extra fields are rejected.
Labels are defect (actionable), not_defect (negative), unclear, or null (missing).
Unclear/null humans never become negatives. Resolution status is never truth.

Predictions file is a JSON object:
  {"predictions": [{"id": "fnd-1", "label": "defect"}], "protocol":
   {"model": "version", "prompt": "digest/version", "rubric": "digest/version",
    "decoding": {"temperature": 0}, "seed": 7, "order_handling": "shuffled:7"}}
protocol is optional. Missing/null protocol fields are reported as unknown.
Explicit predictions may be incomplete, but estimates are withheld until every
finding has a definitive prediction. Without predictions, the estimand is the
precision of all raised review findings, treated as positive assertions; this
is disclosed and is not an invented LLM prediction or human answer.

QC file is a JSON object {"decisions": [event, ...]}. Each event requires
decision_id, item_id, annotator, field, label (a non-null categorical label).
Optional gold_label is an independently known answer; optional repeat_of names
an earlier original event for the SAME item/annotator/field. A repeated event
cannot also count as gold. Preserve pre-adjudication labels here. Independent
gold provenance is supplied by the operator, never inferred from predictions.
QC is evaluated per annotator/field: >=10% gold, >=10% repeats, gold accuracy
>=.90, repeat agreement >=.90; >=20 gold decisions per annotator and >=20
repeats per annotator/field. Small batches export as insufficient_support.
QC covers only supplied identities/fields and does not certify finding labels.

All supplied strata are critical and reported individually [EVAL-04]. Precision
is true positives / predicted positives. Any unresolved human in a stratum
withholds its rate/CI, including unresolved predicted negatives. Within-stratum
Wilson 95% intervals use integer counts and the binomial approximation (no
finite-population correction; not simultaneous confidence bounds). The overall
estimate is an explicit stratified ratio sum((N_h/n_h)*TP_h) /
sum((N_h/n_h)*P_h). Exact design weights are reconstructed after validating the
seed's rounded weight; no Wilson interval is applied to weighted counts.
Sampling-design assumptions (random within stratum, full supplied frame) are
not independently verified. Partial labels/predictions withhold the aggregate.

Cohen kappa is shared for judge/human and QC pairs: categorical, unweighted,
DIAGNOSTIC ONLY [HITL-04/05]. Null pairs are excluded with counts; unclear is a
category for agreement, not a negative for precision. Constant identical labels
have undefined kappa, even at perfect observed agreement. Kappa ~.80 is neither
an acceptance gate nor equivalent to alpha guidance (FIRBENCH decision16734).

Canon v0.26.2: [EVAL-04] Slice-based gate (Designing Machine Learning Systems);
[EVAL-12] Validate the judge against humans and [EVAL-13] Pin the judging
protocol (AI Engineering); [HITL-03] Gold-embedded annotator QC, [HITL-04]
Chance-adjusted annotator score, [HITL-05] Agreement is a diagnostic, not the
truth (Human-in-the-Loop ML). [AGT-10] Degrade loudly (The Art of UNIX
Programming, ch. 1): CLI I/O/schema errors emit structured stderr and exit 2.
Successful exports exit 0, including needs_labels; this is not quality approval.
No external services, optional imports, or model calls are used.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path


LABELS = {"defect", "not_defect", "unclear"}
DEFINITIVE = {"defect", "not_defect"}
PROTOCOL_FIELDS = ("model", "prompt", "rubric", "decoding", "seed", "order_handling")
REQUIRED_FINDING = set("""
id finding_db_id finding_id task_ref severity review_mode stratum
stratum_population stratum_sample weight human_label human_note
""".split())
OPTIONAL_FINDING = set("""
lane_id file_path line_start line_end description failure_scenario fix impact created_at
""".split())


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _label(value, *, missing=True):
    return (missing and value is None) or (isinstance(value, str) and value in LABELS)


def _object(value, required, allowed, context):
    _require(isinstance(value, dict), f"{context}: expected object")
    _require(required <= value.keys(), f"{context}: missing fields {sorted(required - value.keys())}")
    _require(value.keys() <= allowed, f"{context}: unexpected fields {sorted(value.keys() - allowed)}")


def wilson_interval(numerator, denominator):
    """Two-sided 95% Wilson score interval for integer binomial counts, or None."""
    _require(type(numerator) is int and type(denominator) is int, "Wilson counts must be integers")
    _require(0 <= numerator <= denominator, "Wilson requires 0 <= numerator <= denominator")
    if denominator == 0:
        return None
    z = 1.959963984540054
    n, p = denominator, numerator / denominator
    scale = 1 + z * z / n
    center = (p + z * z / (2 * n)) / scale
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / scale
    return [max(0.0, center - half), min(1.0, center + half)]


def cohen_kappa(left, right):
    """Paired categorical agreement diagnostic; nulls excluded, unclear retained."""
    left, right = list(left), list(right)
    _require(len(left) == len(right), "agreement pairs must have equal lengths")
    _require(all(_label(x) for x in left + right), "invalid agreement label")
    pairs = [(a, b) for a, b in zip(left, right) if a is not None and b is not None]
    n = len(pairs)
    result = {
        "diagnostic_only": True,
        "paired_count": n,
        "missing_pairs": len(left) - n,
        "observed_agreement": None,
        "chance_agreement": None,
        "kappa": None,
        "status": "missing",
        "negative_kappa": False,
        "reference_only": "~0.80 is diagnostic, not an acceptance floor or alpha equivalence",
    }
    if not n:
        return result
    a, b = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    observed = sum(x == y for x, y in pairs) / n
    chance_count = sum(a[c] * b[c] for c in LABELS)
    chance = chance_count / (n * n)
    kappa = None if chance_count == n * n else (observed - chance) / (1 - chance)
    result.update(
        observed_agreement=observed,
        chance_agreement=chance,
        kappa=kappa,
        status="degenerate" if kappa is None else "ok",
        negative_kappa=kappa is not None and kappa < 0,
    )
    return result


def _findings(rows):
    rows = list(rows)
    _require(bool(rows), "findings must not be empty")
    seen, strata = set(), defaultdict(list)
    for row in rows:
        _object(row, REQUIRED_FINDING, REQUIRED_FINDING | OPTIONAL_FINDING, "finding")
        _require(_text(row["id"]) and row["id"] not in seen, "finding id must be unique nonempty text")
        seen.add(row["id"])
        _require(
            type(row["finding_db_id"]) is int and row["id"] == f"fnd-{row['finding_db_id']}",
            "id must match finding_db_id",
        )
        _require(_text(row["finding_id"]) and _text(row["task_ref"]), "finding_id/task_ref must be text")
        _require(row["severity"] in ("high", "medium", "low"), "invalid severity")
        _require(row["review_mode"] is None or _text(row["review_mode"]), "invalid review_mode")
        _require(
            row["stratum"] == f"{row['severity']}|{row['review_mode'] or 'none'}",
            "stratum must match severity/review_mode",
        )
        population, sample = row["stratum_population"], row["stratum_sample"]
        _require(
            type(population) is int and type(sample) is int and population >= sample >= 1,
            "invalid stratum population/sample",
        )
        weight = row["weight"]
        _require(
            type(weight) in (int, float) and math.isfinite(weight) and weight == round(population / sample, 4),
            "weight must equal rounded population/sample",
        )
        _require(_label(row["human_label"]), "invalid human_label")
        _require(row["human_note"] is None or isinstance(row["human_note"], str), "invalid human_note")
        strata[row["stratum"]].append(row)
    for name, group in strata.items():
        first = group[0]
        _require(len(group) == first["stratum_sample"], f"{name}: count must equal stratum_sample")
        _require(
            all(
                (r["stratum_sample"], r["stratum_population"])
                == (first["stratum_sample"], first["stratum_population"])
                for r in group
            ),
            f"{name}: inconsistent design",
        )
    return rows, strata


def _protocol(protocol):
    protocol = {} if protocol is None else protocol
    _object(protocol, set(), set(PROTOCOL_FIELDS), "protocol")
    for key, value in protocol.items():
        if value is None:
            continue
        if key == "seed":
            _require(type(value) is int, "protocol seed must be integer or null")
        elif key == "decoding":
            _require(isinstance(value, dict), "protocol decoding must be object or null")
            try:
                json.dumps(value, allow_nan=False)
            except (ValueError, TypeError) as exc:
                raise ValueError("protocol decoding must be finite JSON") from exc
        else:
            _require(_text(value), f"protocol {key} must be nonempty text or null")
    values = {key: copy.deepcopy(protocol.get(key)) for key in PROTOCOL_FIELDS}
    return {"values": values, "unknown_fields": [k for k, v in values.items() if v is None or v == {}]}


def _qc(qc):
    if qc is None:
        return {"status": "not_provided", "groups": [], "decisions": []}
    _object(qc, {"decisions"}, {"decisions"}, "qc")
    _require(isinstance(qc["decisions"], list), "qc decisions must be array")
    events, identities, groups, known_answers = {}, set(), defaultdict(list), {}
    required = {"decision_id", "item_id", "annotator", "field", "label"}
    for row in qc["decisions"]:
        _object(row, required, required | {"gold_label", "repeat_of"}, "qc decision")
        _require(
            all(_text(row[k]) for k in ("decision_id", "item_id", "annotator", "field")),
            "QC identities must be nonempty text",
        )
        _require(row["decision_id"] not in events, "duplicate QC decision_id")
        _require(_label(row["label"], missing=False), "QC label must be categorical, not missing")
        _require(_label(row.get("gold_label")), "invalid known-answer gold_label")
        if row.get("gold_label") is not None:
            gold_key = (row["item_id"], row["field"])
            _require(
                gold_key not in known_answers or known_answers[gold_key] == row["gold_label"],
                "conflicting gold answers for the same item/field",
            )
            known_answers[gold_key] = row["gold_label"]
        key = (row["item_id"], row["annotator"], row["field"])
        repeat = row.get("repeat_of")
        if repeat is not None:
            _require(_text(repeat) and repeat in events, "repeat_of must identify an earlier original decision")
            original = events[repeat]
            _require(not original.get("repeat_of"), "repeat_of must reference original, not another repeat")
            _require(
                key == (original["item_id"], original["annotator"], original["field"]),
                "repeat identity/annotator/field mismatch",
            )
            _require(row.get("gold_label") is None, "repeat decision cannot also supply gold support")
        else:
            _require(key not in identities, "duplicate item identity requires explicit repeat_of")
        identities.add(key)
        events[row["decision_id"]] = row
        groups[(row["annotator"], row["field"])].append(row)
    gold_by_annotator = Counter(row["annotator"] for row in events.values() if row.get("gold_label") is not None)
    summaries = []
    for (annotator, field), rows in sorted(groups.items()):
        gold = [r for r in rows if r.get("gold_label") is not None]
        repeats = [r for r in rows if r.get("repeat_of") is not None]
        gold_correct = sum(r["label"] == r["gold_label"] for r in gold)
        repeat_correct = sum(r["label"] == events[r["repeat_of"]]["label"] for r in repeats)
        support = gold_by_annotator[annotator] >= 20 and len(repeats) >= 20
        floors = (
            len(gold) * 10 >= len(rows)
            and len(repeats) * 10 >= len(rows)
            and bool(gold)
            and gold_correct * 10 >= len(gold) * 9
            and bool(repeats)
            and repeat_correct * 10 >= len(repeats) * 9
        )
        summaries.append({
            "annotator": annotator,
            "field": field,
            "decisions": len(rows),
            "gold_count": len(gold),
            "annotator_gold_count": gold_by_annotator[annotator],
            "repeat_count": len(repeats),
            "gold_fraction": len(gold) / len(rows),
            "repeat_fraction": len(repeats) / len(rows),
            "gold_accuracy": gold_correct / len(gold) if gold else None,
            "repeat_agreement": repeat_correct / len(repeats) if repeats else None,
            "gold_diagnostic": cohen_kappa([r["label"] for r in gold], [r["gold_label"] for r in gold]),
            "repeat_diagnostic": cohen_kappa(
                [r["label"] for r in repeats], [events[r["repeat_of"]]["label"] for r in repeats]
            ),
            "support_met": support,
            "floors_met": bool(floors),
            "status": "insufficient_support" if not support else "passed" if floors else "failed",
        })
    statuses = {r["status"] for r in summaries}
    if "failed" in statuses:
        status = "failed"
    elif not summaries or "insufficient_support" in statuses:
        status = "insufficient_support"
    else:
        status = "passed"
    return {
        "status": status,
        "scope": "only supplied annotator/field identities; not finding-label certification",
        "floors": {
            "gold_fraction": 0.1,
            "repeat_fraction": 0.1,
            "gold_accuracy": 0.9,
            "repeat_agreement": 0.9,
            "gold_per_annotator": 20,
            "repeats_per_annotator_field": 20,
        },
        "groups": summaries,
        "decisions": copy.deepcopy(qc["decisions"]),
    }


def score(findings, predictions=None, qc=None, *, protocol=None):
    """Return JSON-compatible measurements; raise ValueError for invalid inputs."""
    rows, strata = _findings(findings)
    protocol_report = _protocol(protocol)
    if predictions is None:
        predicted = {r["id"]: "defect" for r in rows}
    else:
        predicted = {}
        ids = {r["id"] for r in rows}
        for row in predictions:
            _object(row, {"id", "label"}, {"id", "label"}, "prediction")
            _require(_text(row["id"]) and row["id"] in ids, "unknown prediction id")
            _require(row["id"] not in predicted, "duplicate prediction id")
            _require(_label(row["label"]), "invalid prediction label")
            predicted[row["id"]] = row["label"]
    missing_human = sum(r["human_label"] not in DEFINITIVE for r in rows)
    missing_prediction = sum(predicted.get(r["id"]) not in DEFINITIVE for r in rows)
    summaries = {}
    weighted_tp, weighted_positive = 0.0, 0.0
    for name, group in sorted(strata.items()):
        positives = [r for r in group if predicted.get(r["id"]) == "defect"]
        labeled_positives = [r for r in positives if r["human_label"] in DEFINITIVE]
        tp = sum(r["human_label"] == "defect" for r in labeled_positives)
        unresolved = sum(r["human_label"] not in DEFINITIVE for r in group)
        unknown = sum(predicted.get(r["id"]) not in DEFINITIVE for r in group)
        if unresolved:
            status = "needs_labels"
        elif unknown:
            status = "needs_predictions"
        else:
            status = "scored" if positives else "no_positives"
        ready = status == "scored"
        weight = group[0]["stratum_population"] / len(group)
        weighted_tp += weight * tp
        weighted_positive += weight * len(positives)
        summaries[name] = {
            "status": status,
            "sample": len(group),
            "population": group[0]["stratum_population"],
            "design_weight": weight,
            "recorded_weight": group[0]["weight"],
            "numerator": tp,
            "denominator": len(labeled_positives),
            "predicted_positive_count": len(positives),
            "unresolved_human": unresolved,
            "unresolved_prediction": unknown,
            "rate": tp / len(positives) if ready else None,
            "wilson_95": wilson_interval(tp, len(positives)) if ready else None,
        }
    complete = not missing_human and not missing_prediction
    if missing_human:
        status = "needs_labels"
    elif missing_prediction:
        status = "needs_predictions"
    else:
        status = "scored" if weighted_positive else "no_positives"
    return {
        "schema_version": "evalops-score-judge/v1",
        "status": status,
        "quality_acceptance": "not_evaluated",
        "prediction_source": "raised_findings_assumed_positive" if predictions is None else "explicit",
        "protocol": protocol_report,
        "coverage": {
            "findings": len(rows),
            "unresolved_human": missing_human,
            "unresolved_prediction": missing_prediction,
        },
        "strata": summaries,
        "interval_scope": (
            "within-stratum binomial approximation; no FPC, no simultaneous coverage; "
            "random-within-stratum design unverified"
        ),
        "aggregate": {
            "method": (
                "stratified ratio: sum((N_h/n_h)*TP_h) / sum((N_h/n_h)*P_h); "
                "exact design weights, not rounded seed weights; supplied strata only"
            ),
            "weighted_numerator": weighted_tp if complete else None,
            "weighted_denominator": weighted_positive if complete else None,
            "rate": weighted_tp / weighted_positive if complete and weighted_positive else None,
            "interval_95": None,
            "interval_reason": "No design-based interval implemented; Wilson on weighted counts is invalid",
        },
        "agreement": cohen_kappa([predicted.get(r["id"]) for r in rows], [r["human_label"] for r in rows]),
        "qc": _qc(qc),
    }


def _load_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def main(argv=None):
    """CLI entry point; export status is separate from measurement/QC status."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--qc", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.findings.open(encoding="utf-8") as stream:
            rows = []
            for number, line in enumerate(stream, 1):
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except ValueError as exc:
                        raise ValueError(f"{args.findings}:{number}: {exc}") from exc
        predictions, protocol = None, None
        if args.predictions is not None:
            payload = _load_json(args.predictions)
            _object(payload, {"predictions"}, {"predictions", "protocol"}, "predictions file")
            _require(isinstance(payload["predictions"], list), "predictions must be array")
            predictions, protocol = payload["predictions"], payload.get("protocol")
        report = score(rows, predictions, _load_json(args.qc) if args.qc is not None else None, protocol=protocol)
        serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output is None:
            sys.stdout.write(serialized)
        else:
            inputs = (args.findings, args.predictions, args.qc)
            _require(
                args.output.resolve() not in {p.resolve() for p in inputs if p is not None},
                "output must not overwrite input labels/predictions/QC",
            )
            args.output.write_text(serialized, encoding="utf-8")
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        sys.stderr.write(json.dumps({"status": "error", "error": str(exc)}) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
