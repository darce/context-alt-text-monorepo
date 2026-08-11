"""Shared multi-stage Dockerfile parser for deploy / FIR release gates.

Copied from recognition/tests/deploy/test_dockerfile_stage_topology.py so
``tests/unit`` and ``tests/deploy`` can both stage-scope Dockerfile claims
without depending on pytest conftest discovery across directories
(ORCH-LAUNCH-01-S1-RC-02). Do not reintroduce a second parser.
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_BUILDER_STAGE = "builder"
DEFAULT_RUNTIME_STAGE = "runtime"

_FROM_RE = re.compile(r"^\s*FROM\s+\S+(?:\s+AS\s+(?P<name>[\w.-]+))?\s*$", re.IGNORECASE)

# Project install with extras: .[bench], ".[bench,vlm]", '.[dev]', etc.
_PROJECT_EXTRAS_RE = re.compile(r"""(?:['"]\.\[[^\]]+\]['"]|\.\[[^\]]+\])""")

# Optional Dockerfile `RUN` prefix and absolute interpreter path before pip/uv.
_PIP_INSTALL_RE = re.compile(
    r"(?:^|&&|;|\|)\s*(?:RUN\s+)?(?:/[\w./-]+/)?(?:uv\s+pip\s+install|pip(?:3)?\s+install)\b",
    re.IGNORECASE,
)


def dockerfile_stages(dockerfile: Path) -> dict[str, str]:
    """Ordered ``{stage_name: stage_body}`` for every named ``FROM ... AS <name>``.

    Insertion order is the file order, so ``list(stages)[-1]`` is the stage
    BuildKit builds when ``--target`` is omitted. Unnamed ``FROM`` lines start an
    anonymous stage; its body is discarded but it still terminates the previous
    stage, which keeps the bodies from bleeding into each other.
    """
    stages: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in Path(dockerfile).read_text(encoding="utf-8").splitlines():
        match = _FROM_RE.match(line)
        if match:
            name = match.group("name")
            if name is None:
                current = None
                continue
            current = stages.setdefault(name, [])
            continue
        if current is not None:
            current.append(line)
    return {name: "\n".join(body) for name, body in stages.items()}


# Alias matching the topology helper name so call sites stay consistent.
_dockerfile_stages = dockerfile_stages


def default_build_target(dockerfile: Path) -> str | None:
    """Stage name BuildKit builds when ``--target`` is omitted, or None."""
    stages = dockerfile_stages(dockerfile)
    if not stages:
        return None
    return list(stages)[-1]


def stage_body(dockerfile: Path, stage: str) -> str:
    """Return the body of a named stage; raise AssertionError if missing."""
    stages = dockerfile_stages(dockerfile)
    assert stage in stages, (
        f"Dockerfile missing stage {stage!r}; have {list(stages)}"
    )
    return stages[stage]


def join_continued_lines(text: str) -> list[str]:
    """Join backslash-continued Dockerfile lines into logical commands."""
    logical: list[str] = []
    buf = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        logical.append(buf)
        buf = ""
    if buf:
        logical.append(buf)
    return logical


def unlocked_project_extra_installs(stage_text: str) -> list[str]:
    """Install fragments that resolve project extras outside the frozen lock.

    Catches ``pip install .[bench]``, ``pip install ".[bench,vlm]"``,
    ``uv pip install '.[dev]'``, line continuations, and any extra name —
    regardless of quoting/spacing — whenever ``--no-deps`` is absent
    (ORCH-LAUNCH-01-S1-RC-03 / FIR4-BR-01 / FINALB-05).
    """
    offenders: list[str] = []
    for line in join_continued_lines(stage_text):
        for part in re.split(r"&&", line):
            part = part.strip()
            if not part or part.startswith("#"):
                continue
            # Anchor at fragment start so mid-line noise cannot hide an install.
            probe = part if _PIP_INSTALL_RE.match(part) else f"&& {part}"
            if not _PIP_INSTALL_RE.search(probe):
                continue
            if "--no-deps" in part:
                continue
            if _PROJECT_EXTRAS_RE.search(part):
                offenders.append(part)
    return offenders
