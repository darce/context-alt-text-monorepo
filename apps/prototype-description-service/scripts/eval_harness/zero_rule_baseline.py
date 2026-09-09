"""EVAL-01 zero-rule bake-off arm: metadata-only captions, no VLM, no pixels.

Rule (stated so the baseline is inspectable): for each golden entry, emit
``alt_text_draft`` as the concatenation of non-empty ``context_pack`` fields
``title``, ``caption``, ``description`` in that order, joined by a single
space. An empty pack yields an empty caption. The arm asserts no identities
and no face_count. It consumes the L3 held-out ``held_out_golden.json`` as-is and
never re-runs ``assign_split``.

The run record uses the same ``acx-eval/v1`` / ``run_record`` shape as a
live bake-off fetch so ``score_run_record`` can score it unmodified.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.eval_harness._pathtext import _printable_path
from scripts.eval_harness.bakeoff import DEFAULT_PROMPT_VARIANT, _stamp_pipeline_provenance
from scripts.eval_harness.cli import _head_sha, _manifest_sha
from scripts.eval_harness.manifest import GoldenManifest, load_manifest
from scripts.eval_harness.report import build_reports
from scripts.eval_harness.schema import SCHEMA, DocKind

HERE = Path(__file__).resolve().parent
GOLDEN_MANIFEST_PATH = HERE.parents[1] / "scene" / "tests" / "seed" / "held_out_golden.json"
CONTEXT_FIELD_ORDER = ("title", "caption", "description")
BASELINE_ARM = "zero_rule_context_echo"
BASELINE_RULE = (
    "concatenates non-empty context_pack title, caption, description in that "
    "order; empty pack yields an empty caption; no pixels, no VLM, no identity claims"
)
_HASH_SKIP_REASON = "zero-rule baseline is metadata-only; image bytes are never opened"


def zero_rule_caption(context_pack: Mapping[str, Any] | None) -> str:
    """Context-echo caption. Field order is the rule; missing fields are skipped."""
    pack = context_pack or {}
    parts: list[str] = []
    for key in CONTEXT_FIELD_ORDER:
        value = pack.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts)


def load_held_out_manifest(path: Path | None = None) -> GoldenManifest:
    """Load the L3 held-out held_out_golden.json. Does not re-draw the split."""
    manifest_path = path if path is not None else GOLDEN_MANIFEST_PATH
    return load_manifest(
        str(manifest_path),
        skip_hash_verification=True,
        hash_skip_reason=_HASH_SKIP_REASON,
        metadata_only=True,
    )


def stamped_entries(manifest: GoldenManifest) -> list[dict[str, Any]]:
    """Parent annotation_mode stamped onto dumped entries (GoldenEntry forbids the field)."""
    entries: list[dict[str, Any]] = []
    for entry in manifest.entries:
        row = entry.model_dump()
        if row.get("annotation_mode") is None:
            row["annotation_mode"] = manifest.annotation_mode
        entries.append(row)
    return entries


def build_zero_rule_run_record(
    manifest: GoldenManifest,
    *,
    started_at: str,
    head_sha: str | None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for entry in manifest.entries:
        pack = entry.context_pack.model_dump(exclude_none=True)
        items.append(
            {
                "media_id": entry.media_id,
                "path": entry.path,
                "describe": {
                    "alt_text_draft": zero_rule_caption(pack),
                    "visual_facts": {"objects": []},
                    "adapter": "zero_rule",
                    "model_id": "zero-rule-context-echo",
                    "model_version": "1",
                    "cached": False,
                },
                "identities": [],
                "face_count": 0,
                "error": None,
                "latency_s": 0.0,
                "image_width": None,
                "image_height": None,
                "identity_ordering": None,
            }
        )
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": DocKind.RUN_RECORD.value,
        "provenance": {
            "manifest_sha256": _manifest_sha(manifest),
            "base_url": "zero-rule://context-echo",
            "head_sha": head_sha,
            "started_at": started_at,
            "eval_mode": "standard",
            "baseline_arm": BASELINE_ARM,
            "baseline_rule": BASELINE_RULE,
        },
        "items": items,
    }
    _stamp_pipeline_provenance(
        record["provenance"],
        prompt_variant=DEFAULT_PROMPT_VARIANT,
        two_pass=False,
        dual_length=False,
        face_gate=False,
        eval_mode="standard",
    )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(GOLDEN_MANIFEST_PATH))
    parser.add_argument("--out-record", default=str(HERE / "out" / "zero-rule-heldout-run.json"))
    parser.add_argument("--out-json", default=str(HERE / "out" / "zero-rule-heldout-report.json"))
    parser.add_argument("--out-md", default=str(HERE / "out" / "zero-rule-heldout-report.md"))
    parser.add_argument(
        "--candidate",
        default=None,
        help="optional candidate run-record path; Δ is scored against the zero-rule arm",
    )
    args = parser.parse_args(argv)
    manifest = load_held_out_manifest(Path(args.manifest))
    started_at = datetime.now(UTC).isoformat()
    baseline = build_zero_rule_run_record(manifest, started_at=started_at, head_sha=_head_sha())
    entries = stamped_entries(manifest)
    roster = list(manifest.roster)
    score_sha = baseline["provenance"]["manifest_sha256"]
    candidate_record = baseline
    baseline_for_delta = None
    if args.candidate:
        candidate_record = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
        baseline_for_delta = baseline
    json_doc, md = build_reports(
        candidate_record,
        entries,
        score_manifest_sha256=score_sha,
        manifest_roster=roster,
        baseline_run_record=baseline_for_delta,
    )
    for path, text in (
        (Path(args.out_record), json.dumps(baseline, indent=2, sort_keys=True) + "\n"),
        (Path(args.out_json), json_doc),
        (Path(args.out_md), md if md.endswith("\n") else md + "\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(_printable_path(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
