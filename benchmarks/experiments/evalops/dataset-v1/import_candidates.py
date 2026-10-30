"""Project pinned operational records into quarantined references, never gold/splits.

Reads only the specified error snapshot, frozen metadata and named repository
contracts. Does not open answer files, real journals, databases or network APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

BASE = Path(__file__).resolve().parent
REPO = BASE.parents[3]
REASONS = [
    "replay_input_and_source_context_unavailable",
    "task_root_cause_repeat_linkage_unsubstantiated",
    "exposure_attestation_unknown",
    "independent_expected_behavior_and_labels_unavailable",
    "track_intent_difficulty_segment_criticality_unassigned",
    "prompt_model_config_environment_pins_unavailable",
    "sampling_probability_and_population_weights_unknown",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def reject_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def load(data):
    def reject_constant(_):
        raise ValueError("nonfinite JSON constant")

    return json.loads(data, object_pairs_hook=reject_pairs, parse_constant=reject_constant)


def json_file(path):
    return load(path.read_bytes())


def content_hash(record):
    return sha(canonical({k: v for k, v in record.items() if k != "content_sha256"}))


def candidate(original, coded, mapping, protocol_hash, lock_hash, snapshot_hash):
    source_id = original["id"]
    record = {
        "schema_version": "evalops.real-case-candidate.v1",
        "dataset_version": "1.0.0",
        "candidate_id": f"agent_errors:{source_id}",
        "protocol_sha256": protocol_hash,
        "input_lock_sha256": lock_hash,
        "status": "quarantine",
        "sealed_split": None,
        "quarantine_reasons": REASONS.copy(),
        "source": {
            "system": "handoff.db",
            "table": "agent_errors",
            "snapshot": "agent-errors.json",
            "source_id": source_id,
            "snapshot_sha256": snapshot_hash,
            "row_sha256": coded["source_row_sha256"],
            "summary_ref": coded["original_summary_ref"],
            "summary_sha256": coded["original_summary_sha256"],
            "task_ref": original["task_ref"],
            "created_at": original["created_at"],
            "last_seen_at": original["last_seen_at"],
            "timezone": None,
            "occurrence_count": original["occurrence_count"],
            "analysis_ref": (f"benchmarks/experiments/evalops/analysis-v1/open-coded.jsonl#source_id={source_id}"),
            "analysis_record_sha256": sha(canonical(coded)),
            "analysis_record_group_id": coded["record_group_id"],
            "incident_link_status": "unknown",
        },
        "input": None,
        "expected_output_or_rubric": None,
        "intent": None,
        "difficulty": None,
        "segment": None,
        "track": "unknown",
        "source_context": None,
        "criticality": "unknown",
        "stratum": "unknown",
        "sampling": {
            "frame": "bounded_latest_operational_error_records",
            "inclusion_probability": None,
            "population_weight": None,
            "independent_episode": "unknown",
        },
        "grouping": {
            "canonical_task_id": None,
            "root_cause_id": None,
            "repeat_id": None,
            "group_id": None,
            "linkage_status": "unknown",
            "evidence": [],
        },
        "exposure": {"system_under_test": "unknown", "attestation": None},
        "annotation": {
            "label": None,
            "disposition": "unknown",
            "affected_action": None,
            "blocking_reason": None,
            "provenance": {
                "kind": "unknown",
                "exposure": "unknown",
                "attestation_ref": None,
                "original_ref": None,
                "protocol_version": None,
            },
            "annotation_schema": None,
            "original_event_id": None,
            "supersedes": None,
            "event_ref": None,
        },
        "independent_label": None,
        "independent_gold_status": "needs_labels",
        "coding": {
            "original_open_codes": coded["open_codes"],
            "axial_codes": [mapping[code] for code in coded["open_codes"]],
            "certainty": coded["coding_certainty"],
            "method": "rule_assisted_not_gold",
        },
        "execution_pins": {
            "prompt": None,
            "model": None,
            "config": None,
            "decoding": None,
            "seed": None,
            "order_handling": None,
            "environment": None,
            "task_version": None,
        },
    }
    record["content_sha256"] = content_hash(record)
    return record


def coverage(records, desired):
    count = len(records)
    known_tasks = Counter(r["source"]["task_ref"] for r in records if r["source"]["task_ref"] is not None)
    # Paths describe precisely what was missing in these references, not an
    # assertion about what evidence may exist outside the bounded snapshot.
    missing_paths = [
        ("input",),
        ("expected_output_or_rubric",),
        ("source_context",),
        ("intent",),
        ("difficulty",),
        ("segment",),
        ("grouping", "canonical_task_id"),
        ("grouping", "root_cause_id"),
        ("grouping", "repeat_id"),
        ("grouping", "group_id"),
        ("exposure", "attestation"),
        ("independent_label",),
        ("annotation", "label"),
        ("annotation", "event_ref"),
        ("annotation", "provenance", "attestation_ref"),
        ("annotation", "provenance", "original_ref"),
        ("annotation", "provenance", "protocol_version"),
        ("sampling", "inclusion_probability"),
        ("sampling", "population_weight"),
        *[("execution_pins", key) for key in records[0]["execution_pins"]],
    ]
    missing = {}
    for path in missing_paths:
        values = []
        for record in records:
            value = record
            for key in path:
                value = value[key]
            values.append(value)
        missing[".".join(path)] = {"null_records": sum(v is None for v in values), "denominator_records": count}
    return {
        "schema": "evalops.dataset-coverage.v1",
        "desired": desired,
        "actual": {
            "candidate_records": count,
            "stored_occurrences": sum(r["source"]["occurrence_count"] for r in records),
            "independent_episodes": None,
            "substantiated_groups": 0,
            "quarantined_records": count,
            "admitted_cases": 0,
            "independent_gold_cases": 0,
            "independent_gold_status": "needs_labels",
            "independent_healthy_controls": 0,
            "candidate_strata": dict(sorted(Counter(r["stratum"] for r in records).items())),
            "admitted_strata": dict.fromkeys(desired["strata"], 0),
            "stratum_acquisition_deficits": desired["strata"],
            "candidate_tracks": dict(sorted(Counter(r["track"] for r in records).items())),
            "admitted_tracks": dict.fromkeys(("review-policy", "retrieval", "description-generation"), 0),
            "sealed_split_assignments": {"train": 0, "dev": 0, "test": 0},
            "split_assignment_status": "withheld",
            "known_task_ref_records": sum(known_tasks.values()),
            "distinct_observed_task_refs": len(known_tasks),
            "task_ref_warning": "observed task_ref is not canonical task/root/repeat closure or an independent episode count",
            "unknown_task_ref_records": count - sum(known_tasks.values()),
            "rule_assisted_coding_certainty": dict(sorted(Counter(r["coding"]["certainty"] for r in records).items())),
        },
        "missingness": missing,
        "unknown_enum_records": {
            key: sum(r[key] == "unknown" for r in records) for key in ("track", "criticality", "stratum")
        },
        "quarantine_reason_counts": dict(
            sorted(Counter(reason for r in records for reason in r["quarantine_reasons"]).items())
        ),
        "sampling_weights": {"status": "unknown", "population_weighted_metrics": None},
        "acceptance": {
            "quality": "not_evaluated",
            "calibration": "unavailable",
            "runtime": "unavailable",
            "leakage_guarantee": None,
        },
    }


def build(input_dir, base=BASE, repo=REPO):
    lock = json_file(base / "input-lock.json")
    protocol = json_file(base / "protocol.json")
    require(lock["schema"] == "evalops.dataset-input-lock.v1", "unsupported input lock")
    require(
        protocol["schema"] == "evalops.grouped-real-case-protocol.v1" and protocol["version"] == "1.0.0",
        "unsupported protocol",
    )
    for path, digest in lock["repository_inputs"].items():
        source_path = repo / path
        require(source_path.resolve().is_relative_to(repo.resolve()), "foreign input path")
        # Repository paths are committed contract names, not restricted content.
        require(sha(source_path.read_bytes()) == digest, f"repository input hash mismatch: {path}")
    for item in (lock["frozen_manifest"], lock["snapshot"], lock["status_notes"]):
        require(Path(item["file"]).name == item["file"], "foreign snapshot path")
        require(sha((input_dir / item["file"]).read_bytes()) == item["sha256"], "frozen input hash mismatch")
    manifest = json_file(input_dir / lock["frozen_manifest"]["file"])
    require(manifest["schema"] == "acx-evalops-input-snapshot/1", "unsupported source manifest")
    require(
        manifest["files"]["agent-errors.json"]["sha256"] == lock["snapshot"]["sha256"]
        and manifest["files"]["agent-errors.json"]["rows"] == lock["snapshot"]["rows"]
        and manifest["files"]["agent-errors.json"]["query"] == lock["snapshot"]["query"],
        "snapshot metadata mismatch",
    )
    analysis = repo / "benchmarks/experiments/evalops/analysis-v1"
    coded = [load(line) for line in (analysis / "open-coded.jsonl").read_bytes().splitlines()]
    original = json_file(input_dir / "agent-errors.json")
    analysis_manifest = json_file(analysis / "manifest.json")
    mapping = json_file(analysis / "axial-mapping.json")["mapping"]
    require(isinstance(original, list) and original, "nonempty source array required")
    by_id = {r["id"]: r for r in original}
    coded_by_id = {r["source_id"]: r for r in coded}
    require(
        len(by_id)
        == len(original)
        == len(coded_by_id)
        == len(coded)
        == lock["snapshot"]["rows"]
        == analysis_manifest["record_count"],
        "duplicate IDs or record count mismatch",
    )
    require(set(by_id) == set(coded_by_id), "analysis/source membership mismatch")
    require(analysis_manifest["input_sha256"] == lock["snapshot"]["sha256"], "analysis snapshot mismatch")
    records = []
    protocol_hash = sha((base / "protocol.json").read_bytes())
    lock_hash = sha((base / "input-lock.json").read_bytes())
    schema = json_file(base / "schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for source_id in sorted(by_id):
        row, code = by_id[source_id], coded_by_id[source_id]
        require(code["source_row_sha256"] == sha(canonical(row)), "source row hash mismatch")
        require(code["original_summary_sha256"] == sha((row["summary"] or "").encode()), "summary hash mismatch")
        require(
            code["original_summary_ref"]
            == {"snapshot": "agent-errors.json", "source_id": source_id, "field": "summary"},
            "summary reference mismatch",
        )
        require(
            all(code[key] == row[key] for key in ("created_at", "last_seen_at", "occurrence_count")),
            "source projection mismatch",
        )
        require(
            code["incident_group_id"] is None and code["incident_link_status"] == "unknown",
            "new linkage requires a new manually admitted dataset release",
        )
        require(all(open_code in mapping for open_code in code["open_codes"]), "unmapped original code")
        record = candidate(row, code, mapping, protocol_hash, lock_hash, lock["snapshot"]["sha256"])
        # Keep validator failures free of restricted source content.
        require(validator.is_valid(record), "candidate schema violation")
        records.append(record)
    require(
        sum(r["source"]["occurrence_count"] for r in records) == analysis_manifest["occurrence_count"],
        "occurrence conservation mismatch",
    )
    report = coverage(records, protocol["desired"])
    outputs = {
        "candidates.jsonl": b"".join(canonical(record) + b"\n" for record in records),
        "coverage.json": encoded(report),
    }
    outputs["manifest.json"] = encoded(
        {
            "schema": "evalops.dataset-artifacts.v1",
            "version": "1.0.0",
            "files": {name: {"sha256": sha(data), "bytes": len(data)} for name, data in outputs.items()},
            "contract_files": {
                name: sha((base / name).read_bytes())
                for name in (
                    "schema.json",
                    "protocol.json",
                    "input-lock.json",
                    "import_candidates.py",
                    "test_candidates.py",
                    "README.md",
                )
            },
            "record_count": len(records),
            "occurrence_count": report["actual"]["stored_occurrences"],
            "independent_gold": "needs_labels",
            "sealed_splits": "withheld",
            "validation_scope": "deterministic source custody, schema and missingness; no native runtime or quality acceptance",
        }
    )
    return outputs


def verify_outputs(outputs, artifact_dir):
    require(artifact_dir.is_dir(), "candidate artifacts missing")
    require({p.name for p in artifact_dir.iterdir()} == set(outputs), "unexpected or missing candidate artifacts")
    for name, data in outputs.items():
        require((artifact_dir / name).read_bytes() == data, f"candidate artifact differs: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir", type=Path, required=True, help="retained frozen manifest/status/error-snapshot directory"
    )
    parser.add_argument("--check", action="store_true", help="validate without writing")
    args = parser.parse_args()
    try:
        outputs = build(args.input_dir)
        destination = BASE / "artifacts"
        if args.check:
            verify_outputs(outputs, destination)
        else:
            destination.mkdir(exist_ok=True)
            require(
                not any(p.name not in outputs for p in destination.iterdir()),
                "unexpected candidate artifacts; refusing overwrite",
            )
            for name, data in outputs.items():
                (destination / name).write_bytes(data)
    except (ValueError, KeyError, TypeError, OSError):
        # Deliberately omit parser/source values from console output.
        parser.exit(1, "Candidate validation failed; inspect pinned custody/contract inputs privately.\n")
    result = load(outputs["manifest.json"])
    print(
        f"Verified {result['record_count']} quarantined record references / "
        f"{result['occurrence_count']} stored occurrences; "
        "independent gold needs_labels; sealed assignments withheld."
    )


if __name__ == "__main__":
    main()
