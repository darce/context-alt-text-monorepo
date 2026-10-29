#!/usr/bin/env python3
"""Check dispatch rules for active lanes in orchestration manifests."""

import argparse
import json
from pathlib import Path
import re


TERMINAL_STATUSES = {"merged", "closed", "closed_stale", "retired"}
DESCRIPTION_SERVICE = "apps/prototype-description-service/"
DESCRIPTION_COMMAND = "uv run --directory apps/prototype-description-service"
FORBIDS_COMMIT = re.compile(r"do not commit|don't commit|no commits", re.I)


def _lane_findings(lane):
    """Yield (level, rule, message) findings for one active lane."""
    if isinstance(lane.get("terminal"), dict) or lane.get("status") in TERMINAL_STATUSES:
        return

    commands = lane.get("test_commands")
    if "test_commands" not in lane or commands == []:
        yield "ERROR", "test-commands-empty", "test_commands is missing or empty"
    command_entries = commands if isinstance(commands, list) else []
    paths = lane.get("owned_paths", [])
    path_entries = paths if isinstance(paths, list) else []
    if any(isinstance(path, str) and path.startswith(DESCRIPTION_SERVICE) for path in path_entries):
        if not any(isinstance(command, str) and DESCRIPTION_COMMAND in command for command in command_entries):
            yield "ERROR", "description-service-env", "description service tests must use its uv environment"

    missing_pins = []
    if lane.get("preferred_backend") == "codex-remote":
        for key in ("preferred_model", "preferred_reasoning_effort"):
            value = lane.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing_pins.append(key)
    if "preferred_speed" in lane and lane["preferred_speed"] is None:
        missing_pins.append("preferred_speed")
    if missing_pins:
        yield "ERROR", "route-pin-null", "missing, null or blank route pin(s): " + ", ".join(missing_pins)

    objective = lane.get("objective", "")
    if isinstance(objective, str) and FORBIDS_COMMIT.search(objective):
        yield "ERROR", "brief-forbids-commit", "objective forbids committing the lane result"
    if len(path_entries) > 3:
        yield "WARNING", "owned-paths-wide", f"lane owns {len(path_entries)} paths (more than 3)"


def _manifest_findings(path):
    """Yield findings with lane ids, including malformed input diagnostics."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        yield "ERROR", "-", "manifest-malformed", str(exc)
        return
    if not isinstance(manifest, dict) or not isinstance(manifest.get("lanes"), dict):
        yield "ERROR", "-", "manifest-malformed", "manifest must be an object with a lanes object"
        return
    if any(not isinstance(lane, dict) for lane in manifest["lanes"].values()):
        yield "ERROR", "-", "manifest-malformed", "lanes must map lane ids to objects"
        return
    for lane_id, lane in manifest["lanes"].items():
        for level, rule, message in _lane_findings(lane):
            yield level, lane_id, rule, message


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", type=Path, default=Path("config/lane-orchestration"))
    parser.add_argument("--task-ref", action="append", default=[])
    args = parser.parse_args(argv)
    if not args.manifest_dir.is_dir():
        parser.error(f"manifest directory does not exist: {args.manifest_dir}")
    if args.task_ref:
        manifests = [args.manifest_dir / f"{ref}.json" for ref in args.task_ref]
        for path in manifests:
            if not path.is_file():
                parser.error(f"manifest file does not exist: {path}")
    else:
        manifests = sorted(
            (path for path in args.manifest_dir.glob("*.json")
             if path.is_file() and not path.name.endswith(".golden.json")),
            key=lambda path: path.name,
        )

    errors = warnings = 0
    for path in manifests:
        for level, lane_id, rule, message in _manifest_findings(path):
            print(f"{level} {path.name} {lane_id}: {rule}: {message}")
            errors += level == "ERROR"
            warnings += level == "WARNING"
    print(f"lane manifest rules: {errors} error(s), {warnings} warning(s) in {len(manifests)} manifest(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
