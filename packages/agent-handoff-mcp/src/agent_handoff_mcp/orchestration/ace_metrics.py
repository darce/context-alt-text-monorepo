"""ACE observability metrics aggregation.

Reads JSONL worker/orchestrator logs, handoff.db, mcp-artifacts.db, and
instruction files to produce a metrics snapshot (JSON or markdown).

Usage:
    python -m agent_handoff_mcp.orchestration.ace_metrics \\
        --task-ref <task> \\
        --state-dir .task-state \\
        --logs-dir logs \\
        --output-format markdown

The snapshot is also appended (as JSON) to .task-state/metrics.jsonl.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# JSONL log parsing
# ---------------------------------------------------------------------------

def _iter_jsonl(path: Path):
    """Yield parsed JSON objects from a JSONL file; skip malformed lines."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _collect_worker_events(logs_dir: Path) -> list[dict]:
    events: list[dict] = []
    worker_dir = logs_dir / "worker-daemon"
    if worker_dir.exists():
        for f in sorted(worker_dir.glob("worker-*.jsonl")):
            events.extend(_iter_jsonl(f))
    return events


def _collect_orchestrator_events(logs_dir: Path) -> list[dict]:
    return list(_iter_jsonl(logs_dir / "daemon" / "orchestrator.jsonl"))


# ---------------------------------------------------------------------------
# Token burn aggregation
# ---------------------------------------------------------------------------

def _token_burn(worker_events: list[dict]) -> dict:
    total = 0
    by_lane: dict[str, int] = {}
    converged_cycles = 0
    total_review_cycles = 0

    for e in worker_events:
        event = e.get("event")
        if event == "subagent_turn_observed":
            tokens = (e.get("token_usage_totals") or {}).get("total_tokens") or 0
            lane = e.get("lane_id", "unknown")
            total += tokens
            by_lane[lane] = by_lane.get(lane, 0) + tokens
        elif event == "review_complete":
            total_review_cycles += 1
            if e.get("converged"):
                converged_cycles += 1

    tpc = (total // converged_cycles) if converged_cycles > 0 else None
    return {
        "data_available": total > 0,
        "total_tokens": total,
        "by_lane": by_lane,
        "converged_cycles": converged_cycles,
        "total_review_cycles": total_review_cycles,
        "tokens_per_converged_cycle": tpc,
    }


# ---------------------------------------------------------------------------
# Context pressure trending
# ---------------------------------------------------------------------------

def _context_pressure(worker_events: list[dict]) -> dict:
    counts: dict[str, int] = {"normal": 0, "elevated": 0, "high": 0}
    latest = "normal"
    for e in worker_events:
        if e.get("event") == "context_pressure":
            level = e.get("pressure_level", "normal")
            if level in counts:
                counts[level] += 1
                latest = level

    total = sum(counts.values())
    return {
        "data_available": total > 0,
        "latest_pressure": latest,
        "elevated_cycle_ratio": round(counts["elevated"] / total, 3) if total else 0.0,
        "high_cycle_ratio": round(counts["high"] / total, 3) if total else 0.0,
    }


# ---------------------------------------------------------------------------
# Lane health aggregation
# ---------------------------------------------------------------------------

def _lane_health(worker_events: list[dict]) -> dict:
    scope_violations = sum(1 for e in worker_events if e.get("event") == "scope_violation")
    max_streak = 0
    for e in worker_events:
        streak = (e.get("exhaustion_streak") or {}).get("count", 0)
        if streak > max_streak:
            max_streak = streak

    review_events = [e for e in worker_events if e.get("event") == "review_complete"]
    total_cycles = len(review_events)
    converged = sum(1 for e in review_events if e.get("converged"))
    convergence_rate = round(converged / total_cycles, 3) if total_cycles else 0.0

    return {
        "data_available": len(worker_events) > 0,
        "total_scope_violations": scope_violations,
        "max_exhaustion_streak": max_streak,
        "convergence_rate": convergence_rate,
    }


# ---------------------------------------------------------------------------
# Phase execution timing
# ---------------------------------------------------------------------------

def _phase_timing(worker_events: list[dict]) -> dict:
    exec_times: list[float] = []
    review_times: list[float] = []

    for e in worker_events:
        if e.get("event") == "exec_complete":
            t = e.get("exec_seconds")
            if t is not None:
                exec_times.append(float(t))
        elif e.get("event") == "review_complete":
            t = e.get("review_seconds")
            if t is not None:
                review_times.append(float(t))

    def _stats(values: list[float]) -> dict:
        if not values:
            return {"count": 0, "total": 0.0, "mean": 0.0, "max": 0.0}
        return {
            "count": len(values),
            "total": round(sum(values), 2),
            "mean": round(sum(values) / len(values), 2),
            "max": round(max(values), 2),
        }

    return {
        "data_available": len(exec_times) > 0 or len(review_times) > 0,
        "exec": _stats(exec_times),
        "review": _stats(review_times),
    }


# ---------------------------------------------------------------------------
# FTS5 retrieval stats (from SQLite databases)
# ---------------------------------------------------------------------------

def _fts5_retrieval(state_dir: Path) -> dict:
    result: dict = {
        "data_available": False,
        "artifact_sources_indexed": 0,
        "artifact_chunks_fts_count": 0,
        "handoff_record_counts": {
            "decisions": 0,
            "findings": 0,
            "blockers": 0,
            "actions": 0,
        },
    }

    handoff_db = state_dir / "handoff.db"
    if handoff_db.exists():
        try:
            with sqlite3.connect(str(handoff_db)) as conn:
                for table, key in [
                    ("decisions", "decisions"),
                    ("review_findings", "findings"),
                    ("blockers", "blockers"),
                    ("next_actions", "actions"),
                ]:
                    try:
                        (count,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                        result["handoff_record_counts"][key] = count
                        result["data_available"] = True
                    except sqlite3.OperationalError:
                        pass
        except sqlite3.Error:
            pass

    artifacts_db = state_dir / "mcp-artifacts.db"
    if artifacts_db.exists():
        try:
            with sqlite3.connect(str(artifacts_db)) as conn:
                try:
                    (count,) = conn.execute("SELECT COUNT(*) FROM artifact_sources").fetchone()
                    result["artifact_sources_indexed"] = count
                    result["data_available"] = True
                except sqlite3.OperationalError:
                    pass
                try:
                    (count,) = conn.execute("SELECT COUNT(*) FROM artifact_chunks_fts").fetchone()
                    result["artifact_chunks_fts_count"] = count
                    result["data_available"] = True
                except sqlite3.OperationalError:
                    pass
        except sqlite3.Error:
            pass

    return result


# ---------------------------------------------------------------------------
# ACE documentation health
# ---------------------------------------------------------------------------

def _ace_documentation(instruction_files: list[Path]) -> dict:
    # Import at call time (late binding) per rg-014
    from .ace_reflect import parse_strategy_bullets  # noqa: PLC0415

    total_helpful = 0
    total_harmful = 0
    all_bullets: dict[str, dict] = {}
    total_lines = 0

    for fp in instruction_files:
        if fp.exists():
            total_lines += len(fp.read_text(encoding="utf-8").splitlines())
            bullets = parse_strategy_bullets(fp)
            for rule_id, data in bullets.items():
                if rule_id not in all_bullets:
                    all_bullets[rule_id] = data
                    total_helpful += data["helpful"]
                    total_harmful += data["harmful"]

    pruning_candidates = [
        rule_id
        for rule_id, data in all_bullets.items()
        if data["helpful"] == 0 and data["harmful"] >= 2
    ]

    return {
        "data_available": len(all_bullets) > 0,
        "total_strategy_bullets": len(all_bullets),
        "pruning_candidates": len(pruning_candidates),
        "pruning_candidate_ids": pruning_candidates,
        "total_helpful": total_helpful,
        "total_harmful": total_harmful,
        "instruction_file_lines": total_lines,
    }


# ---------------------------------------------------------------------------
# Snapshot assembly and persistence
# ---------------------------------------------------------------------------

def build_snapshot(
    task_ref: str,
    state_dir: Path,
    logs_dir: Path,
    instruction_files: list[Path],
) -> dict:
    worker_events = _collect_worker_events(logs_dir)

    snapshot = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "task_ref": task_ref,
        "token_burn": _token_burn(worker_events),
        "context_pressure": _context_pressure(worker_events),
        "fts5_retrieval": _fts5_retrieval(state_dir),
        "lane_health": _lane_health(worker_events),
        "phase_timing": _phase_timing(worker_events),
        "ace_documentation": _ace_documentation(instruction_files),
    }
    return snapshot


def _append_snapshot(state_dir: Path, snapshot: dict) -> None:
    metrics_file = state_dir / "metrics.jsonl"
    state_dir.mkdir(parents=True, exist_ok=True)
    with metrics_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot) + "\n")


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def render_markdown(snapshot: dict) -> str:
    tb = snapshot["token_burn"]
    cp = snapshot["context_pressure"]
    fts = snapshot["fts5_retrieval"]
    lh = snapshot["lane_health"]
    ace = snapshot["ace_documentation"]

    lines = [
        f"# ACE Metrics Snapshot",
        f"",
        f"**Task**: `{snapshot['task_ref']}`  **Timestamp**: `{snapshot['timestamp']}`",
        f"",
        f"## Token Efficiency",
    ]
    if tb["data_available"]:
        lines += [
            f"- Total tokens: **{tb['total_tokens']:,}**",
            f"- Converged cycles: {tb['converged_cycles']} / {tb['total_review_cycles']}",
            f"- Tokens per converged cycle: "
            + (f"**{tb['tokens_per_converged_cycle']:,}**" if tb["tokens_per_converged_cycle"] else "n/a"),
        ]
        if tb["by_lane"]:
            lines.append("- By lane:")
            for lane, tokens in sorted(tb["by_lane"].items()):
                lines.append(f"  - `{lane}`: {tokens:,}")
    else:
        lines.append("_No worker turn events found. Data not available._")

    lines += [
        f"",
        f"## Context Pressure",
    ]
    if cp["data_available"]:
        lines += [
            f"- Latest pressure: **{cp['latest_pressure']}**",
            f"- Elevated cycle ratio: {cp['elevated_cycle_ratio']:.1%}",
            f"- High cycle ratio: {cp['high_cycle_ratio']:.1%}",
        ]
    else:
        lines.append("_No context pressure events recorded._")

    lines += [
        f"",
        f"## Retrieval Activity (FTS5)",
    ]
    if fts["data_available"]:
        hrc = fts["handoff_record_counts"]
        lines += [
            f"- Artifact sources indexed: {fts['artifact_sources_indexed']}",
            f"- Artifact chunks (FTS): {fts['artifact_chunks_fts_count']}",
            f"- Handoff records: decisions={hrc['decisions']}  "
            f"findings={hrc['findings']}  blockers={hrc['blockers']}  actions={hrc['actions']}",
        ]
    else:
        lines.append("_No database data available._")

    lines += [
        f"",
        f"## Lane Stability",
    ]
    if lh["data_available"]:
        lines += [
            f"- Scope violations: {lh['total_scope_violations']}",
            f"- Max exhaustion streak: {lh['max_exhaustion_streak']}",
            f"- Convergence rate: {lh['convergence_rate']:.1%}",
        ]
    else:
        lines.append("_No lane event data available._")

    pt = snapshot.get("phase_timing", {})
    lines += [
        f"",
        f"## Phase Timing",
    ]
    if pt.get("data_available"):
        exec_s = pt["exec"]
        rev_s = pt["review"]
        lines += [
            f"- Exec cycles: {exec_s['count']}  total={exec_s['total']}s  mean={exec_s['mean']}s  max={exec_s['max']}s",
            f"- Review cycles: {rev_s['count']}  total={rev_s['total']}s  mean={rev_s['mean']}s  max={rev_s['max']}s",
        ]
    else:
        lines.append("_No exec/review timing data recorded yet._")

    lines += [
        f"",
        f"## Documentation Fitness (ACE)",
    ]
    if ace["data_available"]:
        lines += [
            f"- Strategy bullets: {ace['total_strategy_bullets']}",
            f"- Total helpful: {ace['total_helpful']}  Total harmful: {ace['total_harmful']}",
            f"- Pruning candidates: {ace['pruning_candidates']}",
            f"- Instruction file lines: {ace['instruction_file_lines']}",
        ]
        if ace["pruning_candidate_ids"]:
            lines.append(f"- Candidate IDs: {', '.join(ace['pruning_candidate_ids'])}")
    else:
        lines.append("_No ACE strategy bullets found in instruction files._")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Sparkline visualization helpers
# ---------------------------------------------------------------------------

_SPARK_CHARS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"


def _sparkline(values: list[float]) -> str:
    """Convert a list of numeric values into a compact Unicode sparkline."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    spread = hi - lo or 1.0
    n = len(_SPARK_CHARS) - 1
    return "".join(_SPARK_CHARS[round((v - lo) / spread * n)] for v in values)


def render_sparklines(state_dir: Path, task_ref: str) -> str:
    """Read .task-state/metrics.jsonl and render time-series sparklines."""
    metrics_file = state_dir / "metrics.jsonl"
    if not metrics_file.exists():
        return f"No metrics history found at {metrics_file}\n"

    snapshots: list[dict] = []
    with metrics_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    s = json.loads(line)
                    if task_ref in ("", "unknown", s.get("task_ref", "")):
                        snapshots.append(s)
                except json.JSONDecodeError:
                    continue

    if not snapshots:
        return f"No snapshots found for task_ref={task_ref!r} in {metrics_file}\n"

    lines = [
        f"# ACE Metrics Trends",
        f"",
        f"**Task**: `{task_ref}`  **Snapshots**: {len(snapshots)}",
        f"",
    ]

    token_series = [s.get("token_burn", {}).get("total_tokens", 0) for s in snapshots]
    pressure_series = [
        1 if s.get("context_pressure", {}).get("latest_pressure") == "elevated" else
        2 if s.get("context_pressure", {}).get("latest_pressure") == "high" else 0
        for s in snapshots
    ]
    exec_mean_series = [s.get("phase_timing", {}).get("exec", {}).get("mean", 0.0) for s in snapshots]
    review_mean_series = [s.get("phase_timing", {}).get("review", {}).get("mean", 0.0) for s in snapshots]
    convergence_series = [s.get("lane_health", {}).get("convergence_rate", 0.0) for s in snapshots]

    lines += [
        "## Token Burn",
        f"  `{_sparkline(token_series)}`",
        f"  latest={token_series[-1]:,}" if token_series else "",
        "",
        "## Context Pressure Level (0=normal 1=elevated 2=high)",
        f"  `{_sparkline(pressure_series)}`",
        "",
        "## Exec Duration (mean seconds per cycle)",
        f"  `{_sparkline(exec_mean_series)}`",
        f"  latest={exec_mean_series[-1]:.1f}s" if exec_mean_series else "",
        "",
        "## Review Duration (mean seconds per cycle)",
        f"  `{_sparkline(review_mean_series)}`",
        f"  latest={review_mean_series[-1]:.1f}s" if review_mean_series else "",
        "",
        "## Lane Convergence Rate",
        f"  `{_sparkline(convergence_series)}`",
        f"  latest={convergence_series[-1]:.1%}" if convergence_series else "",
    ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ACE observability metrics aggregation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--task-ref", default="unknown", help="Task reference identifier")
    parser.add_argument("--state-dir", default=".task-state", help="Path to .task-state directory")
    parser.add_argument("--logs-dir", default="logs", help="Path to logs directory")
    parser.add_argument(
        "--output-format",
        choices=["json", "markdown"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--instruction-files",
        nargs="*",
        default=["docs/agentic/instructions.md"],
        help="Instruction files to scan for ACE strategy bullets.  CLAUDE.md and GEMINI.md are symlinks; do not list them separately.",
    )
    parser.add_argument(
        "--sparklines",
        action="store_true",
        help="Print time-series sparklines from accumulated metrics history and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    state_dir = Path(args.state_dir)
    logs_dir = Path(args.logs_dir)
    instruction_files = [Path(f) for f in args.instruction_files]

    if args.sparklines:
        print(render_sparklines(state_dir, args.task_ref))
        return

    snapshot = build_snapshot(
        task_ref=args.task_ref,
        state_dir=state_dir,
        logs_dir=logs_dir,
        instruction_files=instruction_files,
    )

    _append_snapshot(state_dir, snapshot)

    if args.output_format == "json":
        print(json.dumps(snapshot, indent=2))
    else:
        print(render_markdown(snapshot))


if __name__ == "__main__":
    main(sys.argv[1:])
