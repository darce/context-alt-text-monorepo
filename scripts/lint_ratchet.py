#!/usr/bin/env python3
"""Lint ratchet: turn eslint and ruff into merge gates that succeed on invocation.

Neither `npm run lint` nor `ruff check` passed on `main`, so neither could be
wired as a real gate (short-rule sr-002: a declared gate must succeed when
invoked). The fix is not to relax the rules (sr-001) but to freeze the known
debt in a checked-in baseline and fail on any movement away from it.

Design constraint, from the canon:

    OBS-11 (heuristics-canon-research/lexicons/engineering.md:481)
    "a standard that follows degraded recent performance creates a reinforcing
     decline; keep the bar absolute, externally owned, or upward-ratcheting
     from the best demonstrated result."

That rule is why `--check` fails on *improvement* as well as regression. A
baseline that silently re-derives itself from whatever the tree currently looks
like is exactly the "auto-baseline that follows the stock down" OBS-11 names.
Here the baseline is a checked-in artifact and `--accept` may only ever lower a
count, so the recorded bar is always the best demonstrated result.

Failure modes, all exit 1:

  REGRESSION  a (file, rule) count went up, or a new violating (file, rule)
              appeared. This is the merge gate.
  STALE       a count went down or vanished. The debt was paid; record it with
              `--accept` so the bar ratchets and can never slide back.
  SUPPRESSION a rule that the baseline recorded as enabled is now disabled, or
              an ignore list grew. Catches "silence the rule" edits (sr-001)
              even in files that carry no current violation.
  TAMPER      the baseline's stored total disagrees with the sum of its own
              entries, so a hand-edit changed a count without changing total.

`--accept` refuses to write any entry above its existing value and refuses to
write a weakened config guard, so it is safe to run: it can only tighten.
Renames need a hand-edit of the JSON, which is visible in review.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "apps" / "prototype-wp-alt-context"
BASELINE_DIR = REPO_ROOT / "config" / "lint-baseline"

# eslint resolves rules per file glob, so a single --print-config probe does not
# describe the whole config. These two files sit in different config buckets
# (typed app source vs. e2e specs); their union covers every rule the baseline
# can name.
ESLINT_PROBE_FILES = (
    "js/admin/api/settingsApi.ts",
    "playwright.config.ts",
)

BASELINE_VERSION = 1


class RatchetError(RuntimeError):
    """Raised when the ratchet cannot run at all (as opposed to finding drift)."""


# --------------------------------------------------------------------------
# Baseline model
# --------------------------------------------------------------------------


@dataclass
class Baseline:
    """A frozen inventory of known lint debt, keyed by file then rule id."""

    tool: str
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    config_guard: dict[str, object] = field(default_factory=dict)
    version: int = BASELINE_VERSION

    @property
    def total(self) -> int:
        return sum(sum(rules.values()) for rules in self.counts.values())

    def to_json(self) -> dict[str, object]:
        return {
            "tool": self.tool,
            "version": self.version,
            "total": self.total,
            "config_guard": self.config_guard,
            "counts": {
                path: dict(sorted(rules.items()))
                for path, rules in sorted(self.counts.items())
            },
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> Baseline:
        # rg-008: config consumed by multiple modules is validated at load time.
        for key in ("tool", "version", "total", "counts"):
            if key not in payload:
                raise RatchetError(f"baseline is missing required key {key!r}")
        counts_raw = payload["counts"]
        if not isinstance(counts_raw, dict):
            raise RatchetError("baseline 'counts' must be an object")
        counts: dict[str, dict[str, int]] = {}
        for path, rules in counts_raw.items():
            if not isinstance(rules, dict):
                raise RatchetError(f"baseline entry for {path!r} must be an object")
            for rule, n in rules.items():
                if not isinstance(n, int) or n < 1:
                    raise RatchetError(
                        f"baseline count for {path!r}/{rule!r} must be a positive int"
                    )
            counts[path] = dict(rules)
        guard = payload.get("config_guard") or {}
        if not isinstance(guard, dict):
            raise RatchetError("baseline 'config_guard' must be an object")
        obj = cls(
            tool=str(payload["tool"]),
            counts=counts,
            config_guard=dict(guard),
            version=int(payload["version"]),
        )
        stored_total = payload["total"]
        if not isinstance(stored_total, int) or stored_total != obj.total:
            raise RatchetError(
                f"TAMPER: baseline 'total' is {stored_total!r} but its entries sum "
                f"to {obj.total}. A count was edited without updating total."
            )
        return obj

    @classmethod
    def empty(cls, tool: str) -> Baseline:
        return cls(tool=tool)


def baseline_path(tool: str, baseline_dir: Path = BASELINE_DIR) -> Path:
    return baseline_dir / f"{tool}.json"


def load_baseline(tool: str, baseline_dir: Path = BASELINE_DIR) -> Baseline:
    path = baseline_path(tool, baseline_dir)
    if not path.exists():
        return Baseline.empty(tool)
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RatchetError(f"baseline {path} is not valid JSON: {exc}") from exc
    baseline = Baseline.from_json(payload)
    if baseline.tool != tool:
        raise RatchetError(f"baseline {path} declares tool {baseline.tool!r}, expected {tool!r}")
    return baseline


def write_baseline(baseline: Baseline, baseline_dir: Path = BASELINE_DIR) -> Path:
    path = baseline_path(baseline.tool, baseline_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline.to_json(), indent=2, sort_keys=False) + "\n")
    return path


# --------------------------------------------------------------------------
# Collectors
# --------------------------------------------------------------------------


def _relpath(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def _eslint_bin() -> Path:
    binary = FRONTEND_DIR / "node_modules" / ".bin" / "eslint"
    if not binary.exists():
        raise RatchetError(
            f"eslint not installed at {binary}. Run `npm ci` in {FRONTEND_DIR}, or in a "
            "linked worktree symlink node_modules from the primary checkout."
        )
    return binary


def collect_eslint() -> Baseline:
    binary = _eslint_bin()
    proc = _run([str(binary), ".", "-f", "json"], cwd=FRONTEND_DIR)
    if not proc.stdout.strip():
        raise RatchetError(f"eslint produced no JSON output.\n{proc.stderr}")
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RatchetError(f"eslint JSON output was unparseable: {exc}\n{proc.stderr}") from exc

    counts: dict[str, dict[str, int]] = {}
    for entry in report:
        rel = _relpath(entry["filePath"])
        for message in entry.get("messages", []):
            # A fatal parse error has no ruleId; it must still be gated, not dropped.
            rule = message.get("ruleId") or "__fatal__"
            counts.setdefault(rel, {})
            counts[rel][rule] = counts[rel].get(rule, 0) + 1
    return Baseline(tool="eslint", counts=counts, config_guard=eslint_config_guard(binary))


def eslint_config_guard(binary: Path | None = None) -> dict[str, object]:
    """Record which rule ids eslint currently has switched on.

    Count comparison alone cannot see a rule disabled in a file that happens to
    have no violations today, so the enabled-rule set is recorded separately.
    """
    binary = binary or _eslint_bin()
    enabled: set[str] = set()
    for probe in ESLINT_PROBE_FILES:
        if not (FRONTEND_DIR / probe).exists():
            raise RatchetError(
                f"eslint probe file {probe} is missing; update ESLINT_PROBE_FILES."
            )
        proc = _run([str(binary), "--print-config", probe], cwd=FRONTEND_DIR)
        if not proc.stdout.strip():
            raise RatchetError(f"eslint --print-config {probe} produced no output.\n{proc.stderr}")
        config = json.loads(proc.stdout)
        for rule, setting in (config.get("rules") or {}).items():
            severity = setting[0] if isinstance(setting, list) else setting
            if severity not in (0, "off"):
                enabled.add(rule)
    return {"enabled_rules": sorted(enabled)}


def _ruff_bin() -> str:
    """Resolve ruff to an explicit path, mirroring `_eslint_bin`.

    A bare `ruff` on PATH is not cwd-independent here: it lands on the pyenv
    shim, and pyenv's shell hook exports PYENV_DIR/PYENV_VERSION for whatever
    directory the caller was in. `make lint` from apps/prototype-description-service/
    therefore resolved the app's .python-version (3.12.7, no ruff installed)
    and the gate died with "ruff: command not found", while the byte-identical
    run from the repo root reported 408 and passed. A merge gate whose verdict
    depends on the invoking directory is not a gate. `subprocess(cwd=...)` does
    not fix this — PYENV_DIR/PYENV_VERSION are inherited and outrank cwd.
    """
    binary = REPO_ROOT / ".venv" / "bin" / "ruff"
    if binary.exists():
        return str(binary)
    # Fall back to PATH only when the repo venv is absent, and resolve it now so
    # a shim that cannot execute fails here with a name, not later as empty JSON.
    found = shutil.which("ruff")
    if found is None:
        raise RatchetError(
            f"ruff not found at {binary} and not on PATH. Run `uv sync` at the repo root."
        )
    return found


def collect_ruff() -> Baseline:
    proc = _run([_ruff_bin(), "check", "--output-format", "json", "."], cwd=REPO_ROOT)
    if not proc.stdout.strip():
        raise RatchetError(f"ruff produced no JSON output.\n{proc.stderr}")
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RatchetError(f"ruff JSON output was unparseable: {exc}\n{proc.stderr}") from exc

    counts: dict[str, dict[str, int]] = {}
    for item in report:
        rel = _relpath(item["filename"])
        rule = item.get("code") or "__syntax__"
        counts.setdefault(rel, {})
        counts[rel][rule] = counts[rel].get(rule, 0) + 1
    return Baseline(tool="ruff", counts=counts, config_guard=ruff_config_guard())


def ruff_config_guard(pyproject: Path | None = None) -> dict[str, object]:
    """Record ruff's select / ignore surface so widening it is detectable."""
    pyproject = pyproject or (REPO_ROOT / "pyproject.toml")
    data = tomllib.loads(pyproject.read_text())
    lint = data.get("tool", {}).get("ruff", {}).get("lint", {})
    per_file = lint.get("per-file-ignores", {}) or {}
    return {
        "select": sorted(lint.get("select", []) or []),
        "ignore": sorted(lint.get("ignore", []) or []),
        "per_file_ignores": {k: sorted(v) for k, v in sorted(per_file.items())},
    }


def ruff_format_config_guard(pyproject: Path | None = None) -> dict[str, object]:
    """Record `[tool.ruff.format]` so redefining "formatted" is detectable.

    Count comparison alone cannot see this: flipping `indent-style` to "tab"
    would make the 128 baselined files pass without a single one being fixed.
    """
    pyproject = pyproject or (REPO_ROOT / "pyproject.toml")
    data = tomllib.loads(pyproject.read_text())
    fmt = data.get("tool", {}).get("ruff", {}).get("format", {}) or {}
    return {"format_options": {k: fmt[k] for k in sorted(fmt)}}


def collect_ruff_format() -> Baseline:
    """Gate `ruff format --check` against a frozen set of unformatted files.

    `ruff format --check .` reports 128 files on this repo, so the raw command
    can never gate a merge (sr-002). Reformatting all 128 in the same slice as
    a gate change is the entanglement LINTGATE1-NEW-04 warns against. Freezing
    the known-unformatted set keeps every one of them visible and makes any
    NEW unformatted file a hard failure, while `--accept` can only shrink the
    set. Nothing is relaxed (sr-001): the debt is recorded, not suppressed.
    """
    # JSON, not the human renderer: ruff 0.16 replaced the stable
    # "Would reformat: <path>" lines with a rich diagnostic block, which would
    # have silently parsed as zero unformatted files — a gate that passes by
    # failing to understand its own tool. `--output-format json` is the same
    # machine interface `collect_ruff` relies on.
    proc = _run(
        [_ruff_bin(), "format", "--check", "--output-format", "json", "."],
        cwd=REPO_ROOT,
    )
    # 0 = all formatted, 1 = some would be reformatted; anything else is a real
    # failure (bad config, unparseable file) and must not be read as "clean".
    if proc.returncode not in (0, 1):
        raise RatchetError(
            f"ruff format --check failed with exit {proc.returncode}.\n{proc.stderr}"
        )
    if not proc.stdout.strip():
        raise RatchetError(f"ruff format --check produced no JSON output.\n{proc.stderr}")
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RatchetError(
            f"ruff format JSON output was unparseable: {exc}\n{proc.stderr}"
        ) from exc
    counts: dict[str, dict[str, int]] = {}
    for item in report:
        counts[_relpath(item["filename"])] = {"unformatted": 1}
    if proc.returncode == 1 and not counts:
        raise RatchetError(
            "ruff format --check signalled drift but named no files; "
            f"output format may have changed.\n{proc.stdout[:500]}\n{proc.stderr}"
        )
    return Baseline(tool="ruff-format", counts=counts, config_guard=ruff_format_config_guard())


COLLECTORS = {
    "eslint": collect_eslint,
    "ruff": collect_ruff,
    "ruff-format": collect_ruff_format,
}


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


@dataclass
class Drift:
    regressions: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    suppressions: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.regressions or self.stale or self.suppressions)


def compare_config_guard(baseline: dict[str, object], current: dict[str, object]) -> list[str]:
    """Report every way the current config is weaker than the baselined one."""
    problems: list[str] = []

    base_enabled = set(baseline.get("enabled_rules", []) or [])
    cur_enabled = set(current.get("enabled_rules", []) or [])
    for rule in sorted(base_enabled - cur_enabled):
        problems.append(f"rule {rule!r} was enabled in the baseline but is now off/absent")

    base_select = set(baseline.get("select", []) or [])
    cur_select = set(current.get("select", []) or [])
    for code in sorted(base_select - cur_select):
        problems.append(f"ruff select lost {code!r}")

    base_ignore = set(baseline.get("ignore", []) or [])
    cur_ignore = set(current.get("ignore", []) or [])
    for code in sorted(cur_ignore - base_ignore):
        problems.append(f"ruff ignore gained {code!r}")

    # Any change to what "formatted" means invalidates the frozen file set, so
    # surface it rather than silently re-interpreting the baseline.
    base_fmt = baseline.get("format_options", {}) or {}
    cur_fmt = current.get("format_options", {}) or {}
    if base_fmt != cur_fmt:
        for key in sorted(set(base_fmt) | set(cur_fmt)):
            if base_fmt.get(key) != cur_fmt.get(key):
                problems.append(
                    f"ruff format option {key!r} changed "
                    f"{base_fmt.get(key)!r} -> {cur_fmt.get(key)!r}"
                )

    base_pfi = baseline.get("per_file_ignores", {}) or {}
    cur_pfi = current.get("per_file_ignores", {}) or {}
    for pattern, codes in sorted(cur_pfi.items()):
        gained = set(codes) - set(base_pfi.get(pattern, []))
        for code in sorted(gained):
            problems.append(f"ruff per-file-ignores[{pattern!r}] gained {code!r}")
    return problems


def compare(baseline: Baseline, current: Baseline) -> Drift:
    drift = Drift()
    drift.suppressions = compare_config_guard(baseline.config_guard, current.config_guard)

    keys = {(p, r) for p, rules in baseline.counts.items() for r in rules}
    keys |= {(p, r) for p, rules in current.counts.items() for r in rules}

    for path, rule in sorted(keys):
        base_n = baseline.counts.get(path, {}).get(rule, 0)
        cur_n = current.counts.get(path, {}).get(rule, 0)
        if cur_n > base_n:
            label = "new violation" if base_n == 0 else f"{base_n} -> {cur_n}"
            drift.regressions.append(f"{path}: {rule} ({label})")
        elif cur_n < base_n:
            label = "fixed" if cur_n == 0 else f"{base_n} -> {cur_n}"
            drift.stale.append(f"{path}: {rule} ({label})")
    return drift


def tighten(baseline: Baseline, current: Baseline) -> tuple[Baseline, list[str]]:
    """Build the accepted baseline. Refuses anything that would loosen the bar.

    OBS-11: the recorded bar must ratchet from the best demonstrated result, so
    accept may lower a count or drop an entry, never raise or add one.
    """
    refusals: list[str] = []
    refusals.extend(compare_config_guard(baseline.config_guard, current.config_guard))

    counts: dict[str, dict[str, int]] = {}
    for path, rules in current.counts.items():
        for rule, cur_n in rules.items():
            base_n = baseline.counts.get(path, {}).get(rule, 0)
            if cur_n > base_n:
                label = "new entry" if base_n == 0 else f"{base_n} -> {cur_n}"
                refusals.append(f"{path}: {rule} ({label})")
                continue
            counts.setdefault(path, {})[rule] = cur_n

    accepted = Baseline(tool=current.tool, counts=counts, config_guard=current.config_guard)
    return accepted, refusals


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _report(tool: str, drift: Drift, baseline: Baseline, current: Baseline) -> None:
    def dump(title: str, items: list[str], hint: str) -> None:
        if not items:
            return
        print(f"\n  {title} ({len(items)}):", file=sys.stderr)
        for item in items[:40]:
            print(f"    - {item}", file=sys.stderr)
        if len(items) > 40:
            print(f"    ... and {len(items) - 40} more", file=sys.stderr)
        print(f"    => {hint}", file=sys.stderr)

    print(f"\n[{tool}] lint ratchet FAILED "
          f"(baseline {baseline.total}, current {current.total})", file=sys.stderr)
    dump(
        "SUPPRESSION",
        drift.suppressions,
        "sr-001: do not disable or ignore a rule to silence violations. Fix the code.",
    )
    dump(
        "REGRESSION",
        drift.regressions,
        "New lint debt. Fix it; the baseline only ever goes down.",
    )
    dump(
        "STALE",
        drift.stale,
        f"Debt was paid but not recorded. Run `make lint-ratchet-accept TOOL={tool}` "
        "and commit the baseline so the bar ratchets down permanently.",
    )


def run_tool(tool: str, accept: bool, baseline_dir: Path, init: bool = False) -> int:
    if init:
        path = baseline_path(tool, baseline_dir)
        if path.exists():
            raise RatchetError(
                f"{_relpath(path)} already exists. --init seeds the bar once, at adoption; "
                "after that the only sanctioned write is --accept, which can only tighten. "
                "Delete the file deliberately if you really mean to re-seed."
            )
        current = COLLECTORS[tool]()
        write_baseline(current, baseline_dir)
        print(f"[{tool}] seeded baseline with {current.total} violations; wrote {_relpath(path)}")
        return 0

    baseline = load_baseline(tool, baseline_dir)
    current = COLLECTORS[tool]()

    if accept:
        accepted, refusals = tighten(baseline, current)
        if refusals:
            print(
                f"\n[{tool}] REFUSING to accept: the baseline may only be tightened "
                f"(OBS-11). Fix these first:",
                file=sys.stderr,
            )
            for item in refusals[:40]:
                print(f"    - {item}", file=sys.stderr)
            if len(refusals) > 40:
                print(f"    ... and {len(refusals) - 40} more", file=sys.stderr)
            return 1
        path = write_baseline(accepted, baseline_dir)
        delta = baseline.total - accepted.total
        print(f"[{tool}] baseline tightened {baseline.total} -> {accepted.total} "
              f"(-{delta}); wrote {_relpath(path)}")
        return 0

    drift = compare(baseline, current)
    if drift.clean:
        print(f"[{tool}] lint ratchet OK: {current.total} known violations, no drift.")
        return 0
    _report(tool, drift, baseline, current)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--tool",
        choices=["eslint", "ruff", "ruff-format", "all"],
        default="all",
        help="Which linter to gate (default: all).",
    )
    parser.add_argument(
        "--accept",
        action="store_true",
        help="Record paid-down debt. Can only lower counts, never raise them.",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="One-time seed of a missing baseline at adoption time.",
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=BASELINE_DIR,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    tools = ["eslint", "ruff", "ruff-format"] if args.tool == "all" else [args.tool]
    exit_code = 0
    for tool in tools:
        try:
            exit_code |= run_tool(tool, args.accept, args.baseline_dir, args.init)
        except RatchetError as exc:
            print(f"[{tool}] lint ratchet ERROR: {exc}", file=sys.stderr)
            exit_code |= 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
