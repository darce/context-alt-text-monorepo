#!/usr/bin/env python3
"""Check live lane manifests for overlapping owned paths.

Lane manifests are intentionally kept out of git because they describe the
currently running orchestration.  This checker therefore treats a missing or
empty manifest directory as a successful no-op, while making overlap failures
explicit for both humans and automation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_DIR = REPO_ROOT / "config" / "lane-orchestration"
TERMINAL_STATUSES = frozenset({"closed", "merged"})


@dataclass(frozen=True)
class Lane:
    """The overlap-relevant portion of one lane manifest entry."""

    task_ref: str
    lane_id: str
    owned_paths: tuple[str, ...]
    status: str | None
    manifest_path: Path

    @property
    def key(self) -> str:
        return f"{self.task_ref}/{self.lane_id}"


class ManifestError(ValueError):
    """Raised when a lane manifest cannot be interpreted."""


def _normalise_slashes(value: str) -> str:
    """Return a repository-relative, slash-separated path spelling."""

    value = value.strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    while "//" in value:
        value = value.replace("//", "/")
    return value


def normalize_owned_path(path: str) -> str:
    """Normalise one owned path for prefix comparison.

    A trailing slash and a terminal ``*``/``**`` glob both mean "the
    directory below this point".  Removing those suffixes makes directory
    prefix comparison component-aware instead of relying on unsafe raw string
    prefixes (for example, ``src/a.py`` does not overlap ``src/ab.py``).
    """

    if not isinstance(path, str):
        raise TypeError("owned paths must be strings")

    value = _normalise_slashes(path)
    while value.endswith("/"):
        value = value[:-1]

    # Repeated suffixes occur in patterns such as ``src/**/*``.  They all
    # denote a directory prefix for this checker.
    while value.endswith("/**") or value.endswith("/*"):
        value = value[:-3]
        while value.endswith("/"):
            value = value[:-1]

    # A root glob (or an explicit current-directory path) owns the whole
    # repository.  The empty spelling is convenient for prefix checks.
    if value in {"", ".", "*", "**"}:
        return ""
    return value.strip("/")


# British spelling is used in a few existing orchestration documents; retain
# a public alias while keeping the American spelling conventional in Python.
normalise_owned_path = normalize_owned_path


def paths_overlap(path_a: str, path_b: str) -> bool:
    """Return whether two owned paths are equal or directory-prefix related."""

    left = normalize_owned_path(path_a)
    right = normalize_owned_path(path_b)
    if left == right:
        return True
    if not left or not right:
        return True
    return left.startswith(right + "/") or right.startswith(left + "/")


def _path_pair(path_a: str, path_b: str) -> dict[str, str]:
    """Return a stable JSON representation of one matching path pair."""

    # Preserve lane-pair orientation: ``left`` belongs to the first lane in
    # the ``lanes`` field and ``right`` belongs to the second.
    return {
        "left": normalize_owned_path(path_a),
        "right": normalize_owned_path(path_b),
    }


def _status(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _task_ref(document: dict[str, Any], manifest_path: Path) -> str:
    for key in ("task_ref", "task", "task_id", "ref"):
        value = document.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return manifest_path.stem


def _lane_entries(document: dict[str, Any], manifest_path: Path) -> Iterable[dict[str, Any]]:
    raw_lanes = document.get("lanes", [])
    if isinstance(raw_lanes, dict):
        entries: list[dict[str, Any]] = []
        for lane_id, config in raw_lanes.items():
            if not isinstance(config, dict):
                raise ManifestError(
                    f"{manifest_path}: lane {lane_id!r} must be an object"
                )
            entry = dict(config)
            entry.setdefault("lane_id", lane_id)
            entries.append(entry)
        return entries
    if not isinstance(raw_lanes, list):
        raise ManifestError(f"{manifest_path}: lanes must be a list or object")
    entries = []
    for index, entry in enumerate(raw_lanes):
        if not isinstance(entry, dict):
            raise ManifestError(
                f"{manifest_path}: lanes[{index}] must be an object"
            )
        entries.append(entry)
    return entries


def _owned_paths(entry: dict[str, Any], manifest_path: Path) -> tuple[str, ...]:
    raw_paths = entry.get("owned_paths", [])
    if raw_paths is None:
        return ()
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    if not isinstance(raw_paths, list):
        raise ManifestError(f"{manifest_path}: owned_paths must be a list")

    paths: list[str] = []
    for index, path in enumerate(raw_paths):
        if not isinstance(path, str):
            raise ManifestError(
                f"{manifest_path}: owned_paths[{index}] must be a string"
            )
        normalized = normalize_owned_path(path)
        if normalized not in paths:
            paths.append(normalized)
    return tuple(paths)


def load_lanes(manifest_dir: Path) -> tuple[list[Path], list[Lane]]:
    """Load all JSON lane manifests and return their paths and lane rows."""

    manifest_paths = sorted(
        path for path in manifest_dir.glob("*.json") if path.is_file()
    ) if manifest_dir.is_dir() else []
    lanes: list[Lane] = []
    for manifest_path in manifest_paths:
        try:
            document = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"{manifest_path}: cannot read JSON ({exc})") from exc
        if not isinstance(document, dict):
            raise ManifestError(f"{manifest_path}: top-level JSON value must be an object")

        task_ref = _task_ref(document, manifest_path)
        for index, entry in enumerate(_lane_entries(document, manifest_path)):
            lane_id_value = entry.get("lane_id", entry.get("id", entry.get("name")))
            if lane_id_value is None or not str(lane_id_value).strip():
                lane_id = str(index)
            else:
                lane_id = str(lane_id_value).strip()
            lanes.append(
                Lane(
                    task_ref=str(entry.get("task_ref", task_ref)).strip(),
                    lane_id=lane_id,
                    owned_paths=_owned_paths(entry, manifest_path),
                    status=_status(entry["status"]) if "status" in entry else None,
                    manifest_path=manifest_path,
                )
            )
    return manifest_paths, lanes


def _add_status(
    statuses: dict[str, str], key: object, value: object, *, task_ref: str | None = None
) -> None:
    if not isinstance(value, str):
        return
    key_text = str(key).strip()
    if "/" not in key_text and task_ref:
        key_text = f"{task_ref}/{key_text}"
    if key_text and "/" in key_text:
        statuses[key_text] = value.strip().lower()


def _collect_statuses(
    value: object, statuses: dict[str, str], *, task_ref: str | None = None
) -> None:
    """Accept flat maps, nested task/lane maps, and exported lane rows."""

    if isinstance(value, list):
        for row in value:
            _collect_statuses(row, statuses, task_ref=task_ref)
        return
    if not isinstance(value, dict):
        return

    row_task = value.get("task_ref")
    row_lane = value.get("lane_id")
    row_status = value.get("status")
    if row_task is not None and row_lane is not None:
        _add_status(
            statuses,
            f"{row_task}/{row_lane}",
            row_status,
        )

    # Orchestrator exports commonly wrap rows under `lanes`; recursively
    # handling this also tolerates a top-level `rows`/`data` wrapper.
    for container_key in ("lanes", "rows", "data", "statuses"):
        if container_key in value:
            _collect_statuses(value[container_key], statuses, task_ref=task_ref)

    for key, child in value.items():
        if key in {"lanes", "rows", "data", "statuses", "task_ref", "lane_id", "status"}:
            continue
        if isinstance(child, str):
            _add_status(statuses, key, child, task_ref=task_ref)
        elif isinstance(child, (dict, list)):
            child_task = task_ref
            if "/" not in str(key):
                child_task = str(key)
            _collect_statuses(child, statuses, task_ref=child_task)


def load_lane_statuses(status_path: Path | None) -> dict[str, str]:
    """Load an optional task/lane -> status export."""

    if status_path is None:
        return {}
    try:
        document = json.loads(status_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"{status_path}: cannot read JSON ({exc})") from exc
    statuses: dict[str, str] = {}
    _collect_statuses(document, statuses)
    return statuses


def _parse_status_filters(values: Iterable[str]) -> set[str]:
    statuses: set[str] = set()
    for value in values:
        statuses.update(
            part.strip().lower()
            for part in value.split(",")
            if part.strip()
        )
    return statuses


def _lane_is_included(
    lane: Lane, status_override: dict[str, str], include_statuses: set[str]
) -> bool:
    effective_status = status_override.get(lane.key, lane.status)
    if include_statuses:
        return "all" in include_statuses or "*" in include_statuses or (
            effective_status is not None and effective_status in include_statuses
        )
    return effective_status not in TERMINAL_STATUSES


def _parse_allow_specs(values: Iterable[str]) -> dict[frozenset[str], str]:
    allowlist: dict[frozenset[str], str] = {}
    for raw_value in values:
        raw = raw_value.strip()
        reason = "allowlisted via --allow"
        if "=" in raw:
            pair_text, reason_text = raw.split("=", 1)
            if reason_text.strip():
                reason = reason_text.strip()
        elif "|" in raw:
            pair_text, reason_text = raw.split("|", 1)
            if reason_text.strip():
                reason = reason_text.strip()
        else:
            pieces = raw.split(":", 2)
            if len(pieces) == 3 and "/" in pieces[0] and "/" in pieces[1]:
                pair_text = f"{pieces[0]}:{pieces[1]}"
                if pieces[2].strip():
                    reason = pieces[2].strip()
            else:
                pair_text = raw

        endpoints = pair_text.split(":")
        if len(endpoints) != 2 or not all(endpoint.strip() for endpoint in endpoints):
            raise ManifestError(
                "--allow must be TASK/LANE:TASK/LANE, optionally followed by "
                "=REASON"
            )
        left, right = (endpoint.strip() for endpoint in endpoints)
        if "/" not in left or "/" not in right:
            raise ManifestError("--allow endpoints must be TASK/LANE identifiers")
        allowlist[frozenset((left, right))] = reason
    return allowlist


def find_overlaps(
    lanes: Iterable[Lane], allowlist: dict[frozenset[str], str] | None = None
) -> list[dict[str, Any]]:
    """Return one record for every pair of lanes with one or more matches."""

    ordered_lanes = sorted(lanes, key=lambda lane: (lane.key, str(lane.manifest_path)))
    allowlist = allowlist or {}
    overlaps: list[dict[str, Any]] = []
    for index, left_lane in enumerate(ordered_lanes):
        if not left_lane.owned_paths:
            continue
        for right_lane in ordered_lanes[index + 1 :]:
            if not right_lane.owned_paths:
                continue
            path_pairs: list[dict[str, str]] = []
            for left_path in left_lane.owned_paths:
                for right_path in right_lane.owned_paths:
                    if paths_overlap(left_path, right_path):
                        pair = _path_pair(left_path, right_path)
                        if pair not in path_pairs:
                            path_pairs.append(pair)
            if not path_pairs:
                continue
            path_pairs.sort(key=lambda pair: (pair["left"], pair["right"]))
            lane_pair = frozenset((left_lane.key, right_lane.key))
            overlaps.append(
                {
                    "lanes": [left_lane.key, right_lane.key],
                    "paths": path_pairs,
                    "allowed": lane_pair in allowlist,
                    "allow_reason": allowlist.get(lane_pair),
                }
            )
    return overlaps


def _result_payload(
    manifest_dir: Path, manifest_paths: list[Path], lanes: list[Lane], overlaps: list[dict[str, Any]]
) -> dict[str, Any]:
    unallowed_count = sum(1 for overlap in overlaps if not overlap["allowed"])
    return {
        "manifest_dir": str(manifest_dir),
        "manifest_count": len(manifest_paths),
        "lane_count": len(lanes),
        "overlap_count": len(overlaps),
        "unallowed_overlap_count": unallowed_count,
        "overlaps": overlaps,
    }


def _print_human(
    manifest_dir: Path,
    manifest_paths: list[Path],
    lanes: list[Lane],
    overlaps: list[dict[str, Any]],
) -> None:
    print(
        f"Lane manifest overlap check: {len(lanes)} live lanes "
        f"from {len(manifest_paths)} manifest(s)"
    )
    if not overlaps:
        print("No owned-path overlaps.")
        return
    print("Status | Lane pair | Overlapping paths | Reason")
    for overlap in overlaps:
        marker = "ALLOW" if overlap["allowed"] else "OVERLAP"
        lane_text = " <-> ".join(overlap["lanes"])
        paths_text = ", ".join(
            f"{pair['left']} <-> {pair['right']}" for pair in overlap["paths"]
        )
        reason = overlap.get("allow_reason")
        reason_text = f" ({reason})" if reason else ""
        print(f"{marker}: {lane_text} | {paths_text}{reason_text}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check live lane manifests for overlapping owned paths."
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=DEFAULT_MANIFEST_DIR,
        help="directory containing lane manifest JSON files (default: config/lane-orchestration)",
    )
    parser.add_argument(
        "--lane-status-json",
        type=Path,
        help="optional task/lane status export used to filter live lanes",
    )
    parser.add_argument(
        "--include-status",
        action="append",
        default=[],
        metavar="STATUS",
        help="only inspect lanes with this status (repeat or use comma-separated values; all includes every status)",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="TASK/LANE:TASK/LANE[=REASON]",
        help="allow an overlap pair and record an optional reason",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit machine-readable JSON instead of a human table",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_dir = args.manifest_dir
    try:
        manifest_paths, all_lanes = load_lanes(manifest_dir)
    except (ManifestError, OSError, TypeError, ValueError) as exc:
        print(f"check_lane_manifest_overlaps: {exc}", file=sys.stderr)
        return 2

    if not manifest_paths:
        if args.as_json:
            print(
                json.dumps(
                    _result_payload(manifest_dir, [], [], []),
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(f"No lane manifests found in {manifest_dir}.")
        return 0

    try:
        status_override = load_lane_statuses(args.lane_status_json)
        include_statuses = _parse_status_filters(args.include_status)
        allowlist = _parse_allow_specs(args.allow)
    except (ManifestError, OSError, TypeError, ValueError) as exc:
        print(f"check_lane_manifest_overlaps: {exc}", file=sys.stderr)
        return 2

    lanes = [
        lane
        for lane in all_lanes
        if _lane_is_included(lane, status_override, include_statuses)
    ]
    overlaps = find_overlaps(lanes, allowlist)
    payload = _result_payload(manifest_dir, manifest_paths, lanes, overlaps)
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human(manifest_dir, manifest_paths, lanes, overlaps)
    return 1 if payload["unallowed_overlap_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
