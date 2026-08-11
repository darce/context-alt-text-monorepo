"""Shared multi-stage Dockerfile parser for deploy / FIR release gates.

Copied from recognition/tests/deploy/test_dockerfile_stage_topology.py so
``tests/unit`` and ``tests/deploy`` can both stage-scope Dockerfile claims
without depending on pytest conftest discovery across directories
(ORCH-LAUNCH-01-S1-RC-02). Do not reintroduce a second parser.

Stage inheritance (ORCH-LAUNCH-01 wave-2): ``dockerfile_stages`` returns each
stage's OWN body (file-order insertion preserved so
``list(stages)[-1]`` stays the default BuildKit target). Claims about what a
*built image* contains must use ``effective_stage_body``, which follows
``FROM <named-stage>`` transitively with cycle detection.
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_BUILDER_STAGE = "builder"
DEFAULT_RUNTIME_STAGE = "runtime"
RUNTIME_BASE_STAGE = "runtime-base"
RUNTIME_VLM_STAGE = "runtime-vlm"

# Capture both the base ref and optional stage name. The ref is kept so
# effective-body resolution can follow ``FROM runtime-base AS runtime``.
_FROM_RE = re.compile(
    r"^\s*FROM\s+(?P<ref>\S+)(?:\s+AS\s+(?P<name>[\w.-]+))?\s*$",
    re.IGNORECASE,
)

# Project install with extras: .[bench], ".[bench,vlm]", '.[dev]', etc.
_PROJECT_EXTRAS_RE = re.compile(r"""(?:['"]\.\[[^\]]+\]['"]|\.\[[^\]]+\])""")

# Optional Dockerfile `RUN` prefix and absolute interpreter path before pip/uv.
_PIP_INSTALL_RE = re.compile(
    r"(?:^|&&|;|\|)\s*(?:RUN\s+)?(?:/[\w./-]+/)?(?:uv\s+pip\s+install|pip(?:3)?\s+install)\b",
    re.IGNORECASE,
)


def _parse_dockerfile(dockerfile: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(own_bodies, bases)`` for every named ``FROM ... AS <name>``.

    ``own_bodies`` is insertion-ordered by file order.
    ``bases`` maps stage name → the ``FROM`` ref (image or prior stage name).
    """
    stages: dict[str, list[str]] = {}
    bases: dict[str, str] = {}
    current: list[str] | None = None
    for line in Path(dockerfile).read_text(encoding="utf-8").splitlines():
        match = _FROM_RE.match(line)
        if match:
            name = match.group("name")
            ref = match.group("ref")
            if name is None:
                current = None
                continue
            current = stages.setdefault(name, [])
            bases[name] = ref
            continue
        if current is not None:
            current.append(line)
    return {name: "\n".join(body) for name, body in stages.items()}, bases


def dockerfile_stages(dockerfile: Path) -> dict[str, str]:
    """Ordered ``{stage_name: own_stage_body}`` for every named ``FROM ... AS``.

    Insertion order is the file order, so ``list(stages)[-1]`` is the stage
    BuildKit builds when ``--target`` is omitted. Unnamed ``FROM`` lines start an
    anonymous stage; its body is discarded but it still terminates the previous
    stage, which keeps the bodies from bleeding into each other.

    Returns OWN bodies only — does not follow ``FROM <named-stage>``. Use
    ``effective_stage_body`` for built-image claims (COPY/CMD/ENV/USER/…).
    """
    bodies, _ = _parse_dockerfile(dockerfile)
    return bodies


def dockerfile_stage_bases(dockerfile: Path) -> dict[str, str]:
    """Map ``{stage_name: FROM_ref}`` for every named stage."""
    _, bases = _parse_dockerfile(dockerfile)
    return bases


# Alias matching the topology helper name so call sites stay consistent.
_dockerfile_stages = dockerfile_stages


def default_build_target(dockerfile: Path) -> str | None:
    """Stage name BuildKit builds when ``--target`` is omitted, or None."""
    stages = dockerfile_stages(dockerfile)
    if not stages:
        return None
    return list(stages)[-1]


def stage_body(dockerfile: Path, stage: str) -> str:
    """Return the OWN body of a named stage; raise AssertionError if missing."""
    stages = dockerfile_stages(dockerfile)
    assert stage in stages, (
        f"Dockerfile missing stage {stage!r}; have {list(stages)}"
    )
    return stages[stage]


def _resolve_effective(
    own: dict[str, str],
    bases: dict[str, str],
    stage: str,
    stack: frozenset[str] = frozenset(),
) -> str:
    """Transitively join parent effective body + own body; cycle-safe."""
    if stage not in own:
        raise KeyError(stage)
    if stage in stack:
        cycle = " -> ".join([*stack, stage])
        raise ValueError(f"Dockerfile stage inheritance cycle: {cycle}")
    own_body = own[stage]
    base = bases.get(stage, "")
    # Only follow the base when it names another stage in this file.
    if base in own:
        parent = _resolve_effective(own, bases, base, stack | {stage})
        if parent and own_body:
            return f"{parent}\n{own_body}"
        return parent or own_body
    return own_body


def effective_stage_body(dockerfile: Path, stage: str) -> str:
    """Body a built image for ``stage`` effectively has (own + inherited parents).

    If ``FROM <ref> AS stage`` names another stage in the same file, the effective
    body is that parent's effective body followed by this stage's own body.
    External image refs (``python:3.12-slim``, ``ghcr.io/...``) stop the walk.
    Raises ``AssertionError`` when ``stage`` is missing; ``ValueError`` on cycles.
    """
    own, bases = _parse_dockerfile(dockerfile)
    assert stage in own, (
        f"Dockerfile missing stage {stage!r}; have {list(own)}"
    )
    return _resolve_effective(own, bases, stage)


def effective_stage_bodies(dockerfile: Path) -> dict[str, str]:
    """Effective bodies for every named stage, in file insertion order."""
    own, bases = _parse_dockerfile(dockerfile)
    return {name: _resolve_effective(own, bases, name) for name in own}


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


def has_vlm_extra(stage_text: str) -> bool:
    """True when the stage text resolves the project ``vlm`` extra."""
    if re.search(r"--extra\s+vlm\b", stage_text):
        return True
    for match in _PROJECT_EXTRAS_RE.finditer(stage_text):
        if re.search(r"\bvlm\b", match.group(0)):
            return True
    return False
