"""Offline cursor example using the byte-for-byte supplied pure projection."""

import argparse
import json
from pathlib import Path

from snapshot_source import check, project_authority


RESULT_LIMIT_BYTES = 60000


class ResultLimitExceeded(RuntimeError):
    pass


def encode(value):
    """Synthetic transport encoding; the live serializer was not supplied."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def transport(value):
    payload = encode(value)
    if len(payload) > RESULT_LIMIT_BYTES:
        raise ResultLimitExceeded(
            f"result is {len(payload)} bytes; limit is {RESULT_LIMIT_BYTES}"
        )
    return payload


class SnapshotTransaction:
    """One transaction: discover once, then reuse the observed numeric floor.

    An explicit predecessor retains the supplied inclusive sequence boundary.
    Failed validation/transport does not establish a new observation boundary.
    """

    def __init__(self, previous=None):
        self._floor = None if previous is None else previous["sequence"]
        if previous is not None:
            check(type(self._floor) is int and self._floor >= 0, "unknown authority floor")

    @property
    def floor(self):
        return self._floor

    def read(self, raw):
        value = project_authority(raw, self._floor)
        transport(value)
        if self._floor is None:
            self._floor = value["highest_sequence"]
        return value


def synthetic_history(count=258):
    """Deterministic synthetic history; no live records or measured sizes."""
    return encode({
        "highest_sequence": count,
        "rejected_sequences": [],
        "intents": {
            f"synthetic-{sequence:04d}": {
                "sequence": sequence,
                "metadata": "x" * 512,
            }
            for sequence in range(1, count + 1)
        },
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw = synthetic_history()
    all_history = project_authority(raw, 0)
    tx = SnapshotTransaction()
    latest = tx.read(raw)
    try:
        transport(all_history)
    except ResultLimitExceeded as error:
        old_failure = str(error)
    else:
        raise AssertionError("synthetic old case did not exceed the fixed limit")
    small = project_authority(synthetic_history(2), 0)
    transport(small)
    for name, payload in (
        ("synthetic-history.json", raw),
        ("synthetic-all-projection.json", encode(all_history)),
        ("synthetic-latest-projection.json", encode(latest)),
    ):
        (args.output / name).write_bytes(payload)
    report = {
        "data_kind": "synthetic; not the measured live byte sizes",
        "limit_bytes": RESULT_LIMIT_BYTES,
        "synthetic_records": all_history["intent_count"],
        "synthetic_raw_bytes": len(raw),
        "synthetic_all_projection_bytes": len(encode(all_history)),
        "synthetic_latest_projection_bytes": len(encode(latest)),
        "synthetic_small_projection_bytes": len(encode(small)),
        "old_failure": old_failure,
        "pinned_numeric_cursor": tx.floor,
        "full_raw_sha256": latest["sha256"],
    }
    (args.output / "example-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
