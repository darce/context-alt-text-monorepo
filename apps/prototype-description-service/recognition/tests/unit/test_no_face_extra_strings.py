"""FIR-4 S5: no leftover ``[face]`` / ``[local]`` install-extra strings.

Scans live service + runbook surfaces for deprecated optional-dependency
markers. Planning history and archives are allowlisted (do not rewrite history).

Heuristics: [SERVE-03][RLSE-08]
"""

from __future__ import annotations

import re
from pathlib import Path

# Install-extra forms only — not bare Python list literals like ``[face]`` vars.
# Covers: '[face]' / ".[face]" / pkg[face] / extra == "face" / --extra face / face = [
# Package-extra arm avoids Python subscripts used as assignment targets (``x[local] =``).
_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "[face]",
        re.compile(
            r"""(?:["']\[face\]["']|\.\[face\]|(?<![A-Za-z0-9_.-])[\w.-]+\[face\](?!\s*=)|extra\s*==\s*["']face["']|--extra\s+face\b)"""
        ),
    ),
    (
        "[local]",
        re.compile(
            r"""(?:["']\[local\]["']|\.\[local\]|(?<![A-Za-z0-9_.-])[\w.-]+\[local\](?!\s*=)|extra\s*==\s*["']local["']|--extra\s+local\b)"""
        ),
    ),
    ("face extra table", re.compile(r"""(?m)^face\s*=\s*\[""")),
)

# Relative to monorepo root. Guard tests document the forbidden strings; plan/
# assessment/history trees are outside _SCAN_ROOTS so no allowlist needed there.
_ALLOWLIST_PREFIXES: tuple[str, ...] = (
    "apps/prototype-description-service/recognition/tests/unit/test_no_face_extra_strings.py",
    "apps/prototype-description-service/recognition/tests/unit/test_bench_extra_isolation.py",
)

_SCAN_ROOTS: tuple[str, ...] = (
    "apps/prototype-description-service",
    "docs/runbooks",
    "infra",
    ".github",
    "scripts",
)

_TEXT_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".toml",
        ".md",
        ".sh",
        ".yml",
        ".yaml",
        ".txt",
        ".json",
        ".Dockerfile",
        "",  # Dockerfile (no suffix)
    }
)

_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "models",  # ONNX / binary-ish dirs
    }
)


def _repo_root() -> Path:
    # recognition/tests/unit/this_file.py → parents[5] = monorepo root
    return Path(__file__).resolve().parents[5]


def _service_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _is_allowlisted(rel_posix: str) -> bool:
    return any(rel_posix == p or rel_posix.startswith(p) for p in _ALLOWLIST_PREFIXES)


def _iter_scan_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for root_name in _SCAN_ROOTS:
        base = repo_root / root_name
        if not base.exists():
            continue
        if base.is_file():
            files.append(base)
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.name == "uv.lock":
                continue
            if path.suffix.lower() not in _TEXT_SUFFIXES and path.name not in {
                "Dockerfile",
                "Makefile",
            }:
                continue
            files.append(path)
    return files


def test_no_deprecated_face_or_local_extra_strings() -> None:
    """Live surfaces must not advertise ``[face]`` / ``[local]`` install extras."""
    repo = _repo_root()
    # Sanity: monorepo layout (service root is under apps/...)
    assert (_service_root() / "pyproject.toml").is_file()

    violations: list[str] = []
    for path in _iter_scan_files(repo):
        rel = path.relative_to(repo).as_posix()
        if _is_allowlisted(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in _FORBIDDEN_PATTERNS:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                snippet = match.group(0).replace("\n", "\\n")
                violations.append(f"{rel}:{line_no}: {label} → {snippet!r}")

    assert not violations, (
        "Deprecated install-extra strings remain outside allowlisted plan/history docs. "
        "Rename to [bench] / remove [local], or extend the allowlist with rationale:\n  - " + "\n  - ".join(violations)
    )


def test_pyproject_defines_bench_not_face() -> None:
    """Contract matrix: optional-deps table is bench, not face."""
    pyproject = (_service_root() / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^bench\s*=\s*\[", pyproject)
    assert not re.search(r"(?m)^face\s*=\s*\[", pyproject)
    assert "insightface" in pyproject
    # gpu must not re-introduce insightface
    gpu_block = re.search(r"(?ms)^gpu\s*=\s*\[(.*?)\]", pyproject)
    assert gpu_block is not None
    assert "insightface" not in gpu_block.group(1)


def test_dockerfile_pip_installs_bench_extra() -> None:
    """S5CR-01: recognition Dockerfile must install the ``.[bench]`` extra."""
    dockerfile = (_service_root() / "Dockerfile").read_text(encoding="utf-8")
    pip_lines = [ln for ln in dockerfile.splitlines() if "pip install" in ln]
    assert any(".[bench]" in ln for ln in pip_lines), (
        "Dockerfile pip install line must contain '.[bench]' (incumbent dark extra)"
    )
