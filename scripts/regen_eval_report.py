#!/usr/bin/env python3
"""Regenerate one published eval report via the offline score CLI.

Copies the run-record to a temp name whose stem matches the published report
stem (so the CLI writes ``<stem>-report.json`` / ``.md``), scores it against
the named manifest, and copies the outputs to the destination paths.

The score CLI's exit code is the publication contract (rg-015): this script
does not invent a reason. Exit 0 publishes a clean score. Exit 1 is a
partial corpus and is never published. Exit 3 is a refused metric: publish
only with ``--allow-refused`` (default off) and still exit 3. Any other
nonzero exit is unrecognized and is not swallowed.

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
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from eval_exit_contract import (  # noqa: E402
    EXIT_CLEAN as CLI_EXIT_CLEAN,
    EXIT_PARTIAL as CLI_EXIT_PARTIAL,
    EXIT_REFUSED as CLI_EXIT_REFUSED,
    EXIT_USAGE as CLI_EXIT_USAGE,
)


@dataclass(frozen=True)
class ScoreExitDecision:
    """Publication decision derived from the scorer's actual exit code."""

    publish: bool
    exit_code: int
    reason: str
    message: str


def classify_score_exit(returncode: int, *, allow_refused: bool) -> ScoreExitDecision:
    """Map a score-CLI exit code to publish/hold and this script's exit.

    The reason string is selected by the numeric code the CLI actually
    returned. Callers must not pass a guessed reason in.
    """
    if returncode == CLI_EXIT_CLEAN:
        return ScoreExitDecision(
            publish=True,
            exit_code=CLI_EXIT_CLEAN,
            reason="clean-score",
            message="CLI exited 0 (clean score); publishing the written report",
        )
    if returncode == CLI_EXIT_PARTIAL:
        return ScoreExitDecision(
            publish=False,
            exit_code=CLI_EXIT_PARTIAL,
            reason="partial-corpus",
            message=(
                "CLI exited 1 (partial-corpus score gate); "
                "not publishing the written report"
            ),
        )
    if returncode == CLI_EXIT_USAGE:
        return ScoreExitDecision(
            publish=False,
            exit_code=CLI_EXIT_USAGE,
            reason="cli-usage",
            message="CLI exited 2 (usage/argparse); not publishing the written report",
        )
    if returncode == CLI_EXIT_REFUSED:
        if allow_refused:
            return ScoreExitDecision(
                publish=True,
                exit_code=CLI_EXIT_REFUSED,
                reason="refused-metrics",
                message=(
                    "CLI exited 3 (refused metrics); --allow-refused set, "
                    "publishing the written report"
                ),
            )
        return ScoreExitDecision(
            publish=False,
            exit_code=CLI_EXIT_REFUSED,
            reason="refused-metrics",
            message=(
                "CLI exited 3 (refused metrics); not publishing the written "
                "report (pass --allow-refused to publish a refused report)"
            ),
        )
    return ScoreExitDecision(
        publish=False,
        exit_code=returncode,
        reason="unrecognized-cli-exit",
        message=(
            f"CLI exited {returncode} (unrecognized); "
            "not publishing the written report"
        ),
    )


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def _faces_block(payload: dict, name: str) -> dict:
    faces = payload.get("faces") or {}
    if not isinstance(faces, dict):
        return {}
    block = faces.get(name) or {}
    return block if isinstance(block, dict) else {}


def detection_summary(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {"exists": False}
    payload = json.loads(path.read_text())
    det = _faces_block(payload, "detection")
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


def identification_summary(path: Path | None) -> dict:
    """Mirror of detection_summary for faces.identification (S2R5-11).

    A scored→refused identification withdrawal leaves no trace in
    detection_summary. This is the publish audit for that transition.
    """
    if path is None or not path.is_file():
        return {"exists": False}
    payload = json.loads(path.read_text())
    ident = _faces_block(payload, "identification")
    per_identity = ident.get("per_identity")
    per_identity_rows = len(per_identity) if isinstance(per_identity, dict) else 0
    wrong_names = ident.get("wrong_names")
    if wrong_names is None:
        wrong_name_rows = None
    elif isinstance(wrong_names, list):
        wrong_name_rows = len(wrong_names)
    else:
        wrong_name_rows = None
    return {
        "exists": True,
        "refused": ident.get("refused"),
        "invariant": ident.get("invariant"),
        "precision": ident.get("precision"),
        "recall": ident.get("recall"),
        "macro_precision": ident.get("macro_precision"),
        "macro_recall": ident.get("macro_recall"),
        "per_identity_rows": per_identity_rows,
        "wrong_name_rows": wrong_name_rows,
        "score_manifest_sha256": (payload.get("provenance") or {}).get("score_manifest_sha256"),
        "manifest_matches_fetch": (payload.get("provenance") or {}).get("manifest_matches_fetch"),
    }


def attach_disclosure_notes(json_path: Path, md_path: Path, notes: list[str]) -> None:
    """Write disclosure notes without inventing metric values.

    JSON ``notes`` is a list of strings. Markdown twins get one
    ``- notes:`` line per entry, inserted after the images line.
    Existing ``- notes:`` lines are replaced so a re-run does not stack.
    """
    if not notes:
        return
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["notes"] = list(notes)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        line
        for line in md_path.read_text(encoding="utf-8").splitlines()
        if not line.startswith("- notes:")
    ]
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.startswith("- images:"):
            for note in notes:
                out.append(f"- notes: {note}")
            inserted = True
    if not inserted:
        out.extend(f"- notes: {note}" for note in notes)
    md_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _md_section_first_bullet(path: Path | None, heading: str) -> str | None:
    if path is None or not path.is_file():
        return None
    in_section = False
    for line in path.read_text().splitlines():
        if line.startswith(heading):
            in_section = True
            continue
        if in_section and line.startswith("- "):
            return line
        if in_section and line.startswith("## "):
            break
    return None


def md_detection_line(path: Path | None) -> str | None:
    return _md_section_first_bullet(path, "## Face detection")


def md_identification_line(path: Path | None) -> str | None:
    return _md_section_first_bullet(path, "## Face identification")


def score_interpreter(root: Path) -> Path:
    """Resolve the interpreter that runs the score CLI.

    The service-local ``.venv`` only exists in whichever checkout ran the
    install, so a linked worktree has none and hardcoding it turned every
    real-CLI gate in this script's test module into an exit-2 abort. Prefer an
    explicit operator pin, then that venv, then the interpreter already
    running us -- which, under the repo venv, can import the CLI just fine.
    """
    override = os.environ.get("ACX_EVAL_SCORE_PYTHON")
    if override:
        return Path(override)
    venv_python = root / "apps" / "prototype-description-service" / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return venv_python
    return Path(sys.executable)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-record", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument(
        "--allow-refused",
        action="store_true",
        default=False,
        help=(
            "publish a report the scorer refused (CLI exit 3). "
            "Default: hold the report and exit 3. Does not change the "
            "partial-corpus gate (CLI exit 1). The script still exits 3 "
            "so a refused publish is not a clean score."
        ),
    )
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help=(
            "disclosure note attached after a successful publish "
            "(repeatable). Does not change scorer numbers."
        ),
    )
    args = parser.parse_args(argv)

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
    before_ident_json = identification_summary(
        out_json if out_json.is_file() else None
    )
    before_md = md_detection_line(out_md if out_md.is_file() else None)
    before_ident_md = md_identification_line(out_md if out_md.is_file() else None)

    service = root / "apps" / "prototype-description-service"
    python = score_interpreter(root)
    if not python.is_file():
        print(f"missing score interpreter: {python}", file=sys.stderr)
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
        decision = classify_score_exit(
            proc.returncode, allow_refused=args.allow_refused
        )
        print(decision.message)
        if not decision.publish:
            return decision.exit_code
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_json, out_json)
        shutil.copy2(tmp_md, out_md)
        if args.note:
            attach_disclosure_notes(out_json, out_md, list(args.note))

    after_json = detection_summary(out_json)
    after_ident_json = identification_summary(out_json)
    after_md = md_detection_line(out_md)
    after_ident_md = md_identification_line(out_md)
    print("BEFORE_JSON", json.dumps(before_json, sort_keys=True))
    print("AFTER_JSON", json.dumps(after_json, sort_keys=True))
    print("BEFORE_IDENT_JSON", json.dumps(before_ident_json, sort_keys=True))
    print("AFTER_IDENT_JSON", json.dumps(after_ident_json, sort_keys=True))
    print("BEFORE_MD", before_md)
    print("AFTER_MD", after_md)
    print("BEFORE_IDENT_MD", before_ident_md)
    print("AFTER_IDENT_MD", after_ident_md)
    return decision.exit_code


if __name__ == "__main__":
    sys.exit(main())
