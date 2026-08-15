#!/usr/bin/env python3
"""Regenerate one published eval report via the offline score CLI.

Copies the run-record to a temp name whose stem matches the published report
stem (so the CLI writes ``<stem>-report.json`` / ``.md``), scores it against
the named manifest, and copies the outputs to the destination paths.

Usage (from repo root):

    python3 scripts/regen_eval_report.py \\
        --run-record docs/tasks/vlm/VLM-2C-seeded-stub-run-record-20260707.json \\
        --manifest apps/prototype-description-service/scene/tests/seed/golden.json \\
        --out-json docs/tasks/vlm/VLM-2C-seeded-stub-score-20260707-report.json \\
        --out-md docs/tasks/vlm/VLM-2C-seeded-stub-score-20260707-report.md
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def detection_summary(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {"exists": False}
    payload = json.loads(path.read_text())
    det = ((payload.get("faces") or {}).get("detection")) or {}
    return {
        "exists": True,
        "refused": det.get("refused"),
        "invariant": det.get("invariant"),
        "precision": det.get("precision"),
        "recall": det.get("recall"),
        "tp": det.get("tp"),
        "fp": det.get("fp"),
        "fn": det.get("fn"),
        "score_manifest_sha256": (payload.get("provenance") or {}).get("score_manifest_sha256"),
        "manifest_matches_fetch": (payload.get("provenance") or {}).get("manifest_matches_fetch"),
    }


def md_detection_line(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    in_section = False
    for line in path.read_text().splitlines():
        if line.startswith("## Face detection"):
            in_section = True
            continue
        if in_section and line.startswith("- "):
            return line
        if in_section and line.startswith("## "):
            break
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-record", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args()

    root = repo_root()
    run_record = (root / args.run_record).resolve()
    manifest = (root / args.manifest).resolve()
    out_json = (root / args.out_json).resolve()
    out_md = (root / args.out_md).resolve()
    if not run_record.is_file():
        print(f"missing run-record: {run_record}", file=sys.stderr)
        return 2
    if not manifest.is_file():
        print(f"missing manifest: {manifest}", file=sys.stderr)
        return 2

    before_json = detection_summary(out_json if out_json.is_file() else None)
    before_md = md_detection_line(out_md if out_md.is_file() else None)

    service = root / "apps" / "prototype-description-service"
    python = service / ".venv" / "bin" / "python"
    if not python.is_file():
        print(f"missing service venv python: {python}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="regen-eval-") as tmp:
        tmp_dir = Path(tmp)
        tmp_record = tmp_dir / "run.json"
        shutil.copy2(run_record, tmp_record)
        cmd = [
            str(python),
            "-m",
            "scripts.eval_harness.cli",
            "score",
            "--run-record",
            str(tmp_record),
            "--manifest",
            str(manifest),
        ]
        print("REGEN:", " ".join(cmd))
        proc = subprocess.run(cmd, cwd=service)
        tmp_json = tmp_dir / "run-report.json"
        tmp_md = tmp_dir / "run-report.md"
        if not tmp_json.is_file() or not tmp_md.is_file():
            print(
                f"CLI did not write expected reports in {tmp_dir} (exit {proc.returncode})",
                file=sys.stderr,
            )
            return proc.returncode or 2
        if proc.returncode != 0:
            print(
                f"CLI exited {proc.returncode} after writing reports "
                "(partial-corpus score gate); publishing the written report"
            )
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_json, out_json)
        shutil.copy2(tmp_md, out_md)

    after_json = detection_summary(out_json)
    after_md = md_detection_line(out_md)
    print("BEFORE_JSON", json.dumps(before_json, sort_keys=True))
    print("AFTER_JSON", json.dumps(after_json, sort_keys=True))
    print("BEFORE_MD", before_md)
    print("AFTER_MD", after_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
