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

COPY --from provenance (ORCH-LAUNCH-01 wave-3 / RC3): dependency-set claims
(vlm extras / torch contamination) must also walk ``COPY --from=<stage>`` edges
that ship a venv or site-packages tree — the default runtime receives its venv
via ``COPY --from=builder``, not via ``FROM``.
"""

from __future__ import annotations

import re
from pathlib import Path

DEFAULT_BUILDER_STAGE = "builder"
DEFAULT_RUNTIME_STAGE = "runtime"
RUNTIME_BASE_STAGE = "runtime-base"
RUNTIME_VLM_STAGE = "runtime-vlm"

# Project install with extras: .[bench], ".[bench,vlm]", '.[dev]', etc.
_PROJECT_EXTRAS_RE = re.compile(r"""(?:['"]\.\[[^\]]+\]['"]|\.\[[^\]]+\])""")

# Optional Dockerfile `RUN` prefix, absolute interpreter, and `python -m` before pip/uv.
# Anchored at fragment start (or after &&/;/|) so mid-line noise cannot hide an install.
_PIP_INSTALL_RE = re.compile(
    r"(?:^|&&|;|\|)\s*(?:RUN\s+)?"
    r"(?:(?:/[\w./-]+/)?(?:python3?|[\w.-]*python3?)\s+-m\s+)?"
    r"(?:uv\s+pip\s+install|pip(?:3)?\s+install)\b",
    re.IGNORECASE,
)

# COPY --from=<stage> … (flags may precede or follow --from=)
_COPY_FROM_RE = re.compile(
    r"^\s*COPY\s+(?:--[\w-]+(?:=[^\s]+)?\s+)*--from=([^\s]+)",
    re.IGNORECASE,
)

# Paths that constitute a dependency-set edge when copied across stages.
_DEP_COPY_PATH_RE = re.compile(
    r"(?:/opt/venv|/app/\.venv|(?:^|[\s=])\.venv\b|site-packages)",
    re.IGNORECASE,
)

# Shell fragment separators for RUN chains (RC4).
_FRAGMENT_SPLIT_RE = re.compile(r"&&|;|\|")


class DockerfileParseError(ValueError):
    """Raised when a FROM line cannot be understood (never silent reclassify)."""


def _strip_trailing_comment(line: str) -> str:
    """Strip a trailing ``#`` comment outside single/double quotes."""
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i].rstrip()
    return line.rstrip()


def parse_from_instruction(line: str) -> tuple[str, str | None] | None:
    """Tokenize a Dockerfile ``FROM`` instruction.

    Returns ``(ref, name)`` for a valid FROM line (``name`` is None when unnamed).
    Returns ``None`` when the line is not a FROM instruction at all.

    Tolerates ``--platform=…`` / any ``--flag[=value]`` between FROM and the ref,
    trailing ``#`` comments, and arbitrary internal whitespace. Any line that
    *starts* with FROM but cannot be understood raises ``DockerfileParseError``
    (RC1: never silently reclassify as body content).
    """
    stripped = line.strip()
    if not stripped:
        return None
    body = _strip_trailing_comment(stripped)
    if not body:
        return None
    tokens = body.split()
    if not tokens or tokens[0].upper() != "FROM":
        return None

    i = 1
    while i < len(tokens) and tokens[i].startswith("--"):
        i += 1
    if i >= len(tokens):
        raise DockerfileParseError(f"FROM line missing image ref: {line!r}")

    ref = tokens[i]
    i += 1
    name: str | None = None
    if i < len(tokens):
        if tokens[i].upper() != "AS":
            raise DockerfileParseError(
                f"unexpected tokens after FROM ref (expected AS <name>): {line!r}"
            )
        if i + 1 >= len(tokens):
            raise DockerfileParseError(f"FROM ... AS missing stage name: {line!r}")
        name = tokens[i + 1]
        i += 2
        if i < len(tokens):
            raise DockerfileParseError(
                f"unexpected tokens after FROM ... AS <name>: {line!r}"
            )
    return ref, name


def _parse_dockerfile(dockerfile: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(own_bodies, bases)`` for every named ``FROM ... AS <name>``.

    ``own_bodies`` is insertion-ordered by file order.
    ``bases`` maps stage name → the ``FROM`` ref (image or prior stage name).
    """
    stages: dict[str, list[str]] = {}
    bases: dict[str, str] = {}
    current: list[str] | None = None
    for line in Path(dockerfile).read_text(encoding="utf-8").splitlines():
        parsed = parse_from_instruction(line)
        if parsed is not None:
            ref, name = parsed
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


def copy_from_dep_stages(stage_text: str) -> list[str]:
    """Stage names whose venv/site-packages are ``COPY --from=``'d into this body.

    Only edges that ship a virtualenv or site-packages tree count as
    dependency-set provenance (RC3). Plain ``COPY --from=uv /uv …`` does not.
    """
    deps: list[str] = []
    for line in join_continued_lines(stage_text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _COPY_FROM_RE.match(stripped)
        if not match:
            continue
        if _DEP_COPY_PATH_RE.search(stripped):
            deps.append(match.group(1))
    return deps


def has_vlm_extra(stage_text: str) -> bool:
    """True when the stage text resolves the project ``vlm`` extra.

    Recognises (RC2):
    - ``--extra vlm`` / ``--extra=vlm``
    - ``--all-extras`` (implies vlm when the project declares it)
    - project-extras forms ``.[vlm]`` / ``".[bench,vlm]"`` / ``'.[vlm]'``
    """
    if re.search(r"--all-extras\b", stage_text):
        return True
    if re.search(r"--extra(?:=|\s+)vlm\b", stage_text):
        return True
    for match in _PROJECT_EXTRAS_RE.finditer(stage_text):
        if re.search(r"\bvlm\b", match.group(0)):
            return True
    return False


def stage_resolves_vlm_extra(
    dockerfile: Path,
    stage: str,
    *,
    _stack: frozenset[str] | None = None,
) -> bool:
    """True if ``stage``'s built image would contain the vlm extra.

    Checks the effective body (FROM inheritance) and walks ``COPY --from``
    venv/site-packages edges as dependency-set provenance (RC3). A default
    ``runtime`` that copies ``/opt/venv`` from a builder which synced
    ``--extra=vlm`` / ``--all-extras`` is a failure even though the runtime
    stage's own body never mentions vlm.
    """
    stack = _stack or frozenset()
    if stage in stack:
        return False
    own, bases = _parse_dockerfile(dockerfile)
    if stage not in own:
        raise AssertionError(
            f"Dockerfile missing stage {stage!r}; have {list(own)}"
        )
    eff = _resolve_effective(own, bases, stage)
    if has_vlm_extra(eff):
        return True
    next_stack = stack | {stage}
    for dep in copy_from_dep_stages(eff):
        if dep in own and stage_resolves_vlm_extra(
            dockerfile, dep, _stack=next_stack
        ):
            return True
    return False


def unlocked_project_extra_installs(stage_text: str) -> list[str]:
    """Install fragments that resolve project extras outside the frozen lock.

    Catches ``pip install .[bench]``, ``python -m pip install ".[bench]"``,
    ``/opt/venv/bin/python -m pip install '.[dev]'``, ``uv pip install …``,
    line continuations, and any extra name — whenever ``--no-deps`` is absent
    from the *same* shell fragment (ORCH-LAUNCH-01-S1-RC-03 / RC4 / FIR4-BR-01).

    Fragments are split on ``&&``, ``;``, and ``|`` so a harmless
    ``pip install --no-deps wheel`` cannot whitelist a sibling
    ``pip install ".[bench]"`` (M4).
    """
    offenders: list[str] = []
    for line in join_continued_lines(stage_text):
        for part in _FRAGMENT_SPLIT_RE.split(line):
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
