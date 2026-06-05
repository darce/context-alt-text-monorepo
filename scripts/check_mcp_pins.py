#!/usr/bin/env python3
"""Consumer-side MCP package pin-parity guard.

Single source of truth for the workstate MCP runtime pins is the root
``Makefile`` (``MCP_HANDOFF_PACKAGE`` / ``MCP_ORCHESTRATOR_PACKAGE``). Every
other *current-pin* reference in this repo (harness configs, CI, operational
docs, doc-tests) must agree with it. This catches the manual fan-out drift that
left ``.github/copilot-instructions.md`` two minor versions stale.

Ownership note (coordinated with E17-15 / ADR-010): the live harness configs
(``.mcp.json`` / ``.vscode/mcp.json`` / ``.codex/config.toml``) are the pin
source of truth; emitted plugin manifests *preserve* these pins, and the plugin
generator + ``config/agent-workflows/mcp_servers.yaml`` manifest live in
``agentic-protocol-monorepo`` (out of bounds here). This guard is the consumer
"manifest check" that E17-15's verification calls for. The overlay
``mcp_servers.yaml`` is reported as an ADVISORY (not a hard failure) when it
drifts, because the bump belongs upstream.

Classification:
  - ERROR    : a strict pin (``pkg@X.Y.Z`` / ``pkg==X.Y.Z``) in an editable,
               non-frozen file disagrees with the Makefile canonical.
  - ADVISORY : drift in an overlay symlink (e.g. mcp_servers.yaml), a range
               form (``>=a,<b``), or a git+ssh tag scheme (different from PyPI).
  - OK       : matches canonical, or lives in a frozen as-of record.

Exit code 0 = no errors; 1 = at least one ERROR; 2 = guard misconfiguration.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PACKAGES = ("mcp-workstate-handoff", "mcp-workstate-orchestrator")

# Frozen as-of records: ADRs, specs, and task plans legitimately pin the pin
# value that was current when they were written. Never fail on these.
FROZEN_PREFIXES = ("docs/adrs/", "docs/specs/", "docs/tasks/")

# Generated / vendored / overlay clone roots: not scanned at all.
SKIP_PREFIXES = (
    ".workstate/remote/",
    "node_modules/",
    "dist/",
    ".task-state/",
)
SKIP_EXACT = {"DASHBOARD.txt", "CURRENT_TASK.json", "scripts/check_mcp_pins.py"}

STRICT_RE = re.compile(r"\b(mcp-workstate-(?:handoff|orchestrator))(?:@|==)(\d+\.\d+\.\d+)\b")
RANGE_RE = re.compile(r"\b(mcp-workstate-(?:handoff|orchestrator))\s*(>=|<=|~=|>|<)")
GITSSH_RE = re.compile(r"git\+ssh\S*?(mcp-workstate-(?:handoff|orchestrator))\.git@(v?\S+?)[\"'\s\\]")


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(out)


def parse_canonical(makefile: Path) -> dict[str, str]:
    """Extract canonical pins from Makefile MCP_*_PACKAGE assignments."""
    text = makefile.read_text(encoding="utf-8")
    pins: dict[str, str] = {}
    for m in re.finditer(r"MCP_\w+_PACKAGE\s*\??=\s*(mcp-workstate-(?:handoff|orchestrator))==(\d+\.\d+\.\d+)", text):
        pins[m.group(1)] = m.group(2)
    return pins


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    return [p for p in out if p]


def is_overlay_symlink(root: Path, rel: str) -> bool:
    p = root / rel
    return p.is_symlink() and "workstate/remote" in os.readlink(p)


def main() -> int:
    root = repo_root()
    canonical = parse_canonical(root / "Makefile")
    if set(canonical) != set(PACKAGES):
        print(f"check-mcp-pins: could not parse canonical pins from Makefile (got {canonical})", file=sys.stderr)
        return 2

    print("check-mcp-pins: canonical (Makefile) =", ", ".join(f"{k}=={v}" for k, v in sorted(canonical.items())))

    errors: list[str] = []
    advisories: list[str] = []

    for rel in tracked_files(root):
        if rel in SKIP_EXACT or any(rel.startswith(p) for p in SKIP_PREFIXES):
            continue
        path = root / rel
        try:
            if path.is_dir():
                continue
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue

        frozen = any(rel.startswith(p) for p in FROZEN_PREFIXES)
        overlay = is_overlay_symlink(root, rel)

        for lineno, line in enumerate(text.splitlines(), 1):
            for pkg, ver in STRICT_RE.findall(line):
                if ver == canonical[pkg]:
                    continue
                loc = f"{rel}:{lineno}"
                if overlay:
                    advisories.append(f"  [overlay] {loc}: {pkg}=={ver} (canonical {canonical[pkg]}) — bump upstream in workstate-system / agentic-protocol-monorepo")
                elif frozen:
                    pass  # as-of record, allowed
                else:
                    errors.append(f"  {loc}: {pkg}=={ver} != canonical {canonical[pkg]}")
            for pkg, op in RANGE_RE.findall(line):
                if not frozen:
                    advisories.append(f"  [range] {rel}:{lineno}: {pkg}{op}... — prefer exact canonical pin {canonical[pkg]}")
            for pkg, tag in GITSSH_RE.findall(line):
                advisories.append(f"  [git+ssh] {rel}:{lineno}: {pkg}.git@{tag} — private-repo tag scheme, distinct from PyPI {canonical[pkg]}; unverifiable from this checkout")

    if advisories:
        print("\ncheck-mcp-pins: ADVISORIES (not failures — upstream/out-of-bounds or non-pin forms):")
        for a in sorted(set(advisories)):
            print(a)

    if errors:
        print("\ncheck-mcp-pins: ERROR — pins disagree with Makefile canonical:", file=sys.stderr)
        for e in sorted(set(errors)):
            print(e, file=sys.stderr)
        print("\nFix: align the offending pin(s) with the Makefile MCP_*_PACKAGE values,", file=sys.stderr)
        print("or move the reference into a frozen record (docs/adrs|specs|tasks/).", file=sys.stderr)
        return 1

    print("\ncheck-mcp-pins: OK — all editable current-pin references match canonical.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
