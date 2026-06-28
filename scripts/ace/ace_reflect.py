"""ACE reflection helpers for instruction-file strategy bullet evolution.

Project-local module — not part of any MCP package. Extracted from
workbay-orchestrator-mcp to keep handoff-mcp and orchestrator-mcp independent
and reusable without project-specific documentation evolution logic.

Usage:
    python3 scripts/ace/ace_reflect.py --state-dir .task-state
    python3 scripts/ace/ace_reflect.py --curation-report-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Pattern for ACE strategy bullets:
# - [sr-001] helpful=2 harmful=0 :: rule text
# - [rg-013] helpful=1 harmful=0 :: rule text
BULLET_RE = re.compile(
    r"^\s*-\s+\[(?P<rule_id>(?:sr|rg)-\d{3})\]\s+"
    r"helpful=(?P<helpful>\d+)\s+"
    r"harmful=(?P<harmful>\d+)\s*::\s*(?P<text>.+)$"
)

# Pattern that identifies any ACE rule reference in free text
RULE_REF_RE = re.compile(r"\[(?:sr|rg)-\d{3}\]")

# Keywords that indicate a finding *contradicts* a rule
_CONTRADICTION_KEYWORDS = frozenset(
    [
        "violat",
        "missing",
        "contradict",
        "breaks",
        "broke",
        "fail",
        "ignored",
        "bypass",
        "incorrect",
    ]
)


def parse_strategy_bullets(filepath: Path) -> dict[str, dict]:
    """Parse ACE strategy bullets from an instruction file.

    Returns a dict keyed by rule_id:
        {
            "sr-001": {
                "helpful": 3,
                "harmful": 0,
                "text": "Do not relax compliance/lint scripts...",
                "line_number": 139,
            },
            ...
        }
    """
    results: dict[str, dict] = {}
    if not filepath.exists():
        return results
    for line_number, line in enumerate(filepath.read_text(encoding="utf-8").splitlines(), start=1):
        m = BULLET_RE.match(line)
        if m:
            results[m.group("rule_id")] = {
                "helpful": int(m.group("helpful")),
                "harmful": int(m.group("harmful")),
                "text": m.group("text").strip(),
                "line_number": line_number,
            }
    return results


def detect_rule_references(text: str) -> list[str]:
    """Return all unique ACE rule IDs ([sr-NNN] / [rg-NNN]) found in *text*."""
    found = RULE_REF_RE.findall(text)
    seen: dict[str, None] = {}
    for raw in found:
        key = raw[1:-1]  # remove '[' and ']'
        seen[key] = None
    return list(seen)


def classify_rule_reference(text: str, rule_id: str) -> bool:
    """Return True when *text* indicates that *rule_id* was *contradicted*."""
    pattern = re.compile(re.escape(f"[{rule_id}]"))
    text_lower = text.lower()
    for m in pattern.finditer(text_lower):
        start = max(0, m.start() - 80)
        end = min(len(text_lower), m.end() + 80)
        neighbourhood = text_lower[start:end]
        for kw in _CONTRADICTION_KEYWORDS:
            if kw in neighbourhood:
                return True
    return False


def increment_counter(
    rule_id: str,
    counter: str,
    filepath: Path,
    dedup_key: str,
) -> bool:
    """Increment *counter* for *rule_id* in *filepath* if *dedup_key* is new.

    Returns True when the counter was actually incremented.
    """
    if counter not in ("helpful", "harmful"):
        raise ValueError(f"counter must be 'helpful' or 'harmful', got {counter!r}")

    sidecar = filepath.with_suffix(filepath.suffix + ".ace_dedup.json")

    dedup_set: set[str] = set()
    if sidecar.exists():
        try:
            dedup_set = set(json.loads(sidecar.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            dedup_set = set()

    if dedup_key in dedup_set:
        return False

    text = filepath.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    modified = False
    for i, line in enumerate(lines):
        m = BULLET_RE.match(line)
        if m and m.group("rule_id") == rule_id:
            old_val = int(m.group(counter))
            new_val = old_val + 1
            lines[i] = line.replace(f"{counter}={old_val}", f"{counter}={new_val}", 1)
            modified = True
            break

    if not modified:
        return False

    filepath.write_text("".join(lines), encoding="utf-8")
    dedup_set.add(dedup_key)
    sidecar.write_text(json.dumps(sorted(dedup_set), indent=2), encoding="utf-8")
    return True


def identify_pruning_candidates(filepath: Path) -> list[dict]:
    """Return bullets where helpful==0 and harmful>=2 (pruning candidates)."""
    bullets = parse_strategy_bullets(filepath)
    return [{"rule_id": rid, **info} for rid, info in bullets.items() if info["helpful"] == 0 and info["harmful"] >= 2]


def ace_reflect_on_findings(
    findings: list[dict[str, Any]],
    instruction_files: list[Path],
    state_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Scan *findings* for ACE rule references and classify them.

    Returns a list of reflection records:
        [{"finding_id": ..., "rule_id": ..., "contradicts": bool}, ...]

    When *state_dir* is provided, appends records to ace_reflect_log.jsonl
    and applies counter updates immediately.
    """
    import datetime as _dt  # noqa: PLC0415

    records: list[dict[str, Any]] = []
    known_rules: set[str] = set()
    for fp in instruction_files:
        known_rules.update(parse_strategy_bullets(fp).keys())

    for finding in findings:
        finding_id = finding.get("id") or finding.get("finding_id", "unknown")
        description = finding.get("description") or finding.get("text") or ""
        refs = detect_rule_references(description)
        for rule_id in refs:
            if rule_id not in known_rules:
                continue
            contradicts = classify_rule_reference(description, rule_id)
            records.append(
                {
                    "finding_id": finding_id,
                    "rule_id": rule_id,
                    "contradicts": contradicts,
                }
            )

    if state_dir is not None and records:
        state_dir.mkdir(parents=True, exist_ok=True)
        reflect_log = state_dir / "ace_reflect_log.jsonl"
        ts = _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
        with reflect_log.open("a", encoding="utf-8") as fh:
            for rec in records:
                entry = dict(rec)
                entry["timestamp"] = ts
                fh.write(json.dumps(entry) + "\n")
        ace_apply_counters(reflect_log, instruction_files)

    return records


def ace_apply_counters(
    reflect_log: Path,
    instruction_files: list[Path],
) -> dict[str, int]:
    """Process entries in *reflect_log* and increment counters.

    Returns a summary: {total_processed, incremented, skipped}.
    """
    if not reflect_log.exists():
        return {"total_processed": 0, "incremented": 0, "skipped": 0}

    processed = 0
    incremented = 0
    skipped = 0

    lines = reflect_log.read_text(encoding="utf-8").splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue

        finding_id = record.get("finding_id", "unknown")
        rule_id = record.get("rule_id")
        contradicts = record.get("contradicts", False)

        if not rule_id:
            skipped += 1
            continue

        counter = "harmful" if contradicts else "helpful"
        dedup_key = f"{finding_id}:{rule_id}:{counter}"

        did_update = False
        for fp in instruction_files:
            if increment_counter(rule_id, counter, fp, dedup_key):
                did_update = True

        processed += 1
        if did_update:
            incremented += 1

    total_non_empty = sum(1 for line in lines if line.strip())
    offset_file = reflect_log.with_name(reflect_log.name + ".offset")
    try:
        offset_file.write_text(json.dumps({"processed_line_count": total_non_empty}), encoding="utf-8")
    except OSError:
        pass

    return {
        "total_processed": processed,
        "incremented": incremented,
        "skipped": skipped,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply pending ACE counter updates or print a curation report.",
    )
    parser.add_argument("--state-dir", default=".task-state")
    parser.add_argument(
        "--instruction-files",
        nargs="+",
        default=["docs/workbay/instructions.md"],
    )
    parser.add_argument("--curation-report-only", action="store_true")
    parser.add_argument("--model-curation-backend", default=None, help="Optional backend for model-backed ACE curation.")
    parser.add_argument("--model-curation-model", default=None, help="Optional model override for model-backed curation.")
    parser.add_argument("--model-curation-reasoning-effort", default=None)
    parser.add_argument("--model-curation-threshold", type=int, default=5)
    parser.add_argument("--model-curation-budget-tokens", type=int, default=20000)
    return parser.parse_args()


def _curation_report(instruction_files: list[Path]) -> None:
    for fp in instruction_files:
        if not fp.exists():
            print(f"  {fp}: not found")
            continue
        bullets = parse_strategy_bullets(fp)
        candidates = identify_pruning_candidates(fp)
        print(f"\n## {fp}")
        print(f"  Total bullets: {len(bullets)}")
        total_helpful = sum(v["helpful"] for v in bullets.values())
        total_harmful = sum(v["harmful"] for v in bullets.values())
        print(f"  helpful sum: {total_helpful}  harmful sum: {total_harmful}")
        if candidates:
            print(f"  Pruning candidates ({len(candidates)}):")
            for c in candidates:
                print(f"    [{c['rule_id']}] helpful={c['helpful']} harmful={c['harmful']} :: {c['text'][:80]}")
        else:
            print("  No pruning candidates.")


def _append_curation_log(state_dir: Path, entry: dict[str, Any]) -> None:
    log_path = state_dir / "ace_curation_log.jsonl"
    state_dir.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _curation_token_total(state_dir: Path) -> int:
    log_path = state_dir / "ace_curation_log.jsonl"
    if not log_path.exists():
        return 0
    total = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        total += int(row.get("token_usage", {}).get("total", {}).get("total_tokens") or 0)
    return total


def _run_model_curation(
    *,
    state_dir: Path,
    instruction_files: list[Path],
    reflect_log: Path,
    backend: str | None,
    model: str | None,
    reasoning_effort: str | None,
    threshold: int,
    budget_tokens: int,
) -> dict[str, Any]:
    import datetime as _dt  # noqa: PLC0415

    pending_entries = (
        sum(1 for line in reflect_log.read_text(encoding="utf-8").splitlines() if line.strip())
        if reflect_log.exists()
        else 0
    )
    pruning_candidates = sum(len(identify_pruning_candidates(fp)) for fp in instruction_files if fp.exists())
    trigger_size = max(pending_entries, pruning_candidates)
    spent_tokens = _curation_token_total(state_dir)

    if not backend:
        return {"status": "disabled", "pending_entries": pending_entries, "pruning_candidates": pruning_candidates}
    if trigger_size < threshold:
        result: dict[str, Any] = {
            "status": "below_threshold",
            "pending_entries": pending_entries,
            "pruning_candidates": pruning_candidates,
            "threshold": threshold,
            "budget_tokens": budget_tokens,
        }
        _append_curation_log(state_dir, result)
        return result
    if spent_tokens >= budget_tokens:
        result = {
            "status": "budget_exhausted",
            "pending_entries": pending_entries,
            "pruning_candidates": pruning_candidates,
            "threshold": threshold,
            "budget_tokens": budget_tokens,
            "spent_tokens": spent_tokens,
        }
        _append_curation_log(state_dir, result)
        return result

    # Late import: model-backed curation requires workbay-orchestrator-mcp
    try:
        from workbay_orchestrator_mcp.orchestration.backend_registry import get_adapter  # noqa: PLC0415
    except ImportError:
        result = {
            "status": "backend_unavailable",
            "error": "Model-backed curation requires workbay-orchestrator-mcp (backend_registry). Install it or omit --model-curation-backend.",
            "pending_entries": pending_entries,
            "pruning_candidates": pruning_candidates,
        }
        _append_curation_log(state_dir, result)
        return result

    bullet_summaries: list[str] = []
    for fp in instruction_files:
        for candidate in identify_pruning_candidates(fp):
            bullet_summaries.append(
                f"{candidate['rule_id']}: helpful={candidate['helpful']} harmful={candidate['harmful']} text={candidate['text']}"
            )
    prompt = (
        "Review ACE rule evidence and propose curation actions.\n"
        f"Pending reflect entries: {pending_entries}\n"
        f"Pruning candidates: {pruning_candidates}\n"
        "Pruning candidate summaries:\n"
        + ("\n".join(f"- {item}" for item in bullet_summaries) if bullet_summaries else "- none")
    )
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "recommendations"],
        "additionalProperties": False,
    }
    adapter = get_adapter(backend)
    adapter_result = adapter.execute(
        prompt=prompt,
        schema=schema,
        worktree_path=Path.cwd(),
        model=model,
        reasoning_effort=reasoning_effort,
    )
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
    entry = {
        "timestamp": ts,
        "status": "triggered",
        "backend": backend,
        "model": model or adapter_result.response_model,
        "reasoning_effort": reasoning_effort or adapter_result.reasoning_effort,
        "threshold": threshold,
        "budget_tokens": budget_tokens,
        "pending_entries": pending_entries,
        "pruning_candidates": pruning_candidates,
        "summary": adapter_result.summary,
        "token_usage": adapter_result.token_usage or {},
    }
    _append_curation_log(state_dir, entry)
    return entry


def main() -> int:
    args = _parse_args()
    state_dir = Path(args.state_dir)
    instruction_files = [Path(f) for f in args.instruction_files]

    if args.curation_report_only:
        print("# ACE Curation Report")
        _curation_report(instruction_files)
        return 0

    reflect_log = state_dir / "ace_reflect_log.jsonl"
    summary = ace_apply_counters(reflect_log, instruction_files)
    print(
        f"ace-reflect: processed={summary['total_processed']}  "
        f"incremented={summary['incremented']}  skipped={summary['skipped']}"
    )
    if summary["total_processed"] == 0:
        print("  No pending entries in", reflect_log)

    curation = _run_model_curation(
        state_dir=state_dir,
        instruction_files=instruction_files,
        reflect_log=reflect_log,
        backend=args.model_curation_backend,
        model=args.model_curation_model,
        reasoning_effort=args.model_curation_reasoning_effort,
        threshold=max(1, args.model_curation_threshold),
        budget_tokens=max(1, args.model_curation_budget_tokens),
    )
    if curation.get("status") == "triggered":
        print(f"  model-curation: backend={curation.get('backend')} model={curation.get('model') or 'default'}")
    elif curation.get("status") == "backend_unavailable":
        print(f"  model-curation: {curation['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
