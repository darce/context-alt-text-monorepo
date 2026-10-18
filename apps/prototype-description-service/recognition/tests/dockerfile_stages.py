"""Shared multi-stage Dockerfile parser for deploy / FIR release gates.

Copied from recognition/tests/deploy/test_dockerfile_stage_topology.py so
``tests/unit`` and ``tests/deploy`` can both stage-scope Dockerfile claims
without depending on pytest conftest discovery across directories
(ORCH-LAUNCH-01-S1-RC-02). Do not reintroduce a second parser.

Stage inheritance (ORCH-LAUNCH-01 wave-2): ``dockerfile_stages`` returns each
stage's OWN body (file-order insertion preserved for named stages). BuildKit's
default target when ``--target`` is omitted is the **last stage in the file**,
named or anonymous — use ``default_build_target``, not ``list(stages)[-1]``.
Claims about what a *built image* contains must use ``effective_stage_body``,
which follows ``FROM <named-stage>`` transitively with cycle detection.

COPY --from provenance (ORCH-LAUNCH-01 wave-3 / RC3): dependency-set claims
(vlm extras / torch contamination) walk every ``COPY --from=<stage>`` edge
(including numeric stage indices) — the default runtime receives its venv
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

# pip/uv install anywhere in a shell fragment (D5.5 / G-08). Leading
# ``env VAR=…`` wrappers, bare ``VAR=VALUE`` assignments, absolute interpreters,
# and ``python -m`` prefixes are stripped by ``_strip_leading_wrappers`` so a
# start-anchored match cannot be defeated by inert tokens.
_PIP_INSTALL_RE = re.compile(
    r"(?:uv\s+pip\s+install|pip(?:3)?\s+install)\b",
    re.IGNORECASE,
)

# Leading env assignment tokens (``FOO=1`` / ``env FOO=1 BAR=2``).
_ENV_ASSIGN_RE = re.compile(r"^(?:env\s+)?(?:[A-Za-z_][\w]*=\S+\s+)+")

# sh -c / bash -c / sh -lc / bash -lc quoted payloads.
_SHELL_C_RE = re.compile(
    r"""(?:ba)?sh\s+-[a-zA-Z]*c[a-zA-Z]*\s+(?P<q>['"])(?P<body>.*?)(?P=q)""",
    re.IGNORECASE | re.DOTALL,
)

# COPY --from=<stage> … (flags may precede or follow --from=)
_COPY_FROM_RE = re.compile(
    r"^\s*COPY\s+(?:--[\w-]+(?:=[^\s]+)?\s+)*--from=([^\s]+)",
    re.IGNORECASE,
)

# Shell fragment separators for RUN chains (RC4).
_FRAGMENT_SPLIT_RE = re.compile(r"&&|;|\|")

# Heredoc openers only in genuine redirect position on RUN/COPY/ADD.
# Requires << or <<- not immediately after a word char (rejects 1<<3 / x<<y),
# and only on Dockerfile instruction lines (rejects comments / prose).
# Group "dash" is "-" for <<- (indented terminator) else "".
_HEREDOC_OPEN_RE = re.compile(
    r"^(?P<prefix>(?:RUN|COPY|ADD)\b(?:(?!<<).)*?)"
    r"(?<![\w])<<(?P<dash>-?)"
    r"(?P<q>['\"]?)(?P<delim>\w+)(?P=q)(?P<suffix>.*)$",
    re.IGNORECASE,
)

# Global ARG default: ARG NAME=value / ARG NAME (before or between FROMs).
_ARG_DEFAULT_RE = re.compile(
    r"^\s*ARG\s+([A-Za-z_][\w]*)(?:=(.*))?\s*$",
    re.IGNORECASE,
)

# ${VAR} or $VAR in a FROM ref (simple, unbraced single identifier).
_FROM_VAR_RE = re.compile(r"\$\{([A-Za-z_][\w]*)\}|\$([A-Za-z_][\w]*)")

# --extra vlm / --extra=vlm / --extra "vlm" / --extra='vlm'
# Quoted forms must not require a word-boundary after the closing quote
# (\" is non-word, so \\b after \"vlm\" never fires).
_EXTRA_VLM_RE = re.compile(
    r"""--extra(?:=|\s+)(?:"vlm"|'vlm'|vlm\b)"""
)


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


def _expand_from_ref(ref: str, arg_defaults: dict[str, str]) -> str:
    """Expand simple ``$VAR`` / ``${VAR}`` in a FROM ref via known ARG defaults.

    Only substitutes identifiers present in ``arg_defaults``. Unresolved vars
    are left intact so external image refs keep working. Stage-scoped ARGs
    declared *after* a FROM do not affect that FROM (BuildKit global-ARG rule
    for the image ref): callers pass only args seen before the current FROM.
    """

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        return arg_defaults.get(name, match.group(0))

    return _FROM_VAR_RE.sub(_sub, ref)


def _parse_arg_default(line: str) -> tuple[str, str] | None:
    """Return ``(name, default)`` for a global/stage ``ARG`` line, else None.

    ``ARG NAME`` (no default) is recorded as empty string so a later
    ``FROM $NAME`` does not invent a value. Trailing comments are stripped.
    """
    body = _strip_trailing_comment(line.strip())
    if not body:
        return None
    match = _ARG_DEFAULT_RE.match(body)
    if not match:
        return None
    name = match.group(1)
    raw = match.group(2)
    if raw is None:
        return name, ""
    # Strip optional surrounding quotes on the default value.
    default = raw.strip()
    if len(default) >= 2 and default[0] == default[-1] and default[0] in {"'", '"'}:
        default = default[1:-1]
    return name, default


def _parse_dockerfile(
    dockerfile: Path,
) -> tuple[dict[str, str], dict[str, str], list[str | None]]:
    """Return ``(own_bodies, bases, stage_order)`` for every ``FROM``.

    ``own_bodies`` / ``bases`` cover **named** stages only (insertion-ordered).
    ``stage_order`` lists every stage in file order; anonymous stages appear as
    ``None`` so ``default_build_target`` can match BuildKit (last stage wins,
    named or not).

    Global ``ARG NAME=value`` lines seen before a FROM expand ``$NAME`` /
    ``${NAME}`` in that FROM ref so provenance walks
    ``ARG BASE=builder-vlm`` / ``FROM ${BASE} AS runtime`` correctly.
    """
    stages: dict[str, list[str]] = {}
    bases: dict[str, str] = {}
    order: list[str | None] = []
    arg_defaults: dict[str, str] = {}
    current: list[str] | None = None
    heredoc_delim: str | None = None
    heredoc_indented = False
    for line in Path(dockerfile).read_text(encoding="utf-8").splitlines():
        # Heredoc bodies are opaque: a line beginning with FROM must not open a
        # new stage (G-10). Track openers only on RUN/COPY/ADD via the shared
        # heredoc regex used by join_continued_lines.
        if heredoc_delim is not None:
            if current is not None:
                current.append(line)
            if _is_heredoc_terminator(line, heredoc_delim, indented=heredoc_indented):
                heredoc_delim = None
                heredoc_indented = False
            continue

        if not line.lstrip().startswith("#"):
            scan = _strip_trailing_comment(line)
            heredoc = _HEREDOC_OPEN_RE.match(scan)
            if heredoc:
                if current is not None:
                    current.append(line)
                heredoc_delim = heredoc.group("delim")
                heredoc_indented = heredoc.group("dash") == "-"
                continue

        parsed = parse_from_instruction(line)
        if parsed is not None:
            ref, name = parsed
            ref = _expand_from_ref(ref, arg_defaults)
            order.append(name)
            if name is None:
                # Anonymous stage: BuildKit still builds it when last, but we
                # have no stable name to attach body claims to. Terminate the
                # previous stage so bodies do not bleed across the FROM.
                current = None
                continue
            if name in stages:
                raise DockerfileParseError(
                    f"duplicate stage name {name!r} (BuildKit rejects redefinition)"
                )
            current = []
            stages[name] = current
            bases[name] = ref
            continue
        # ARG defaults apply to subsequent FROM refs (global + re-declared).
        arg = _parse_arg_default(line)
        if arg is not None:
            arg_defaults[arg[0]] = arg[1]
            # Still keep ARG lines in the stage body when inside a stage so
            # own-body scans remain complete.
            if current is not None:
                current.append(line)
            continue
        if current is not None:
            current.append(line)
    return {name: "\n".join(body) for name, body in stages.items()}, bases, order


def dockerfile_stages(dockerfile: Path) -> dict[str, str]:
    """Ordered ``{stage_name: own_stage_body}`` for every named ``FROM ... AS``.

    Named-stage insertion order is file order among *named* stages only.
    BuildKit's default target when ``--target`` is omitted is the last stage in
    the file — including an anonymous final ``FROM`` — so do **not** treat
    ``list(stages)[-1]`` as the build default; use ``default_build_target``.

    Unnamed ``FROM`` lines still terminate the previous stage (bodies do not
    bleed) but are omitted from this map.

    Returns OWN bodies only — does not follow ``FROM <named-stage>``. Use
    ``effective_stage_body`` for built-image claims (COPY/CMD/ENV/USER/…).
    """
    bodies, _, _ = _parse_dockerfile(dockerfile)
    return bodies


def dockerfile_stage_bases(dockerfile: Path) -> dict[str, str]:
    """Map ``{stage_name: FROM_ref}`` for every named stage."""
    _, bases, _ = _parse_dockerfile(dockerfile)
    return bases


# Alias matching the topology helper name so call sites stay consistent.
_dockerfile_stages = dockerfile_stages


def default_build_target(dockerfile: Path) -> str | None:
    """Stage name BuildKit builds when ``--target`` is omitted.

    Returns the last stage's name in file order when that stage is named.

    Disambiguates the two failure modes that previously both returned
    ``None`` (a gate that cannot fail when callers only assert
    ``is not None`` against empty files):

    * **No stages** — raises ``DockerfileParseError`` so the empty-file case
      cannot be confused with a successful anonymous build.
    * **Anonymous last stage** — returns ``None`` (BuildKit still builds it,
      but there is no name). Callers that require a named production target
      must treat ``None`` as failure.
    """
    _, _, order = _parse_dockerfile(dockerfile)
    if not order:
        raise DockerfileParseError(
            "Dockerfile has no FROM stages; cannot determine default build target"
        )
    return order[-1]


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
    own, bases, _ = _parse_dockerfile(dockerfile)
    assert stage in own, (
        f"Dockerfile missing stage {stage!r}; have {list(own)}"
    )
    return _resolve_effective(own, bases, stage)


def effective_stage_bodies(dockerfile: Path) -> dict[str, str]:
    """Effective bodies for every named stage, in file insertion order."""
    own, bases, _ = _parse_dockerfile(dockerfile)
    return {name: _resolve_effective(own, bases, name) for name in own}


def _stage_index_map(order: list[str | None]) -> dict[str, str]:
    """Map BuildKit numeric stage indices to named stage names.

    Anonymous stages occupy an index but have no name; numeric refs that land
    on them are left unresolved (cannot attach named-stage claims).
    """
    mapping: dict[str, str] = {}
    for i, name in enumerate(order):
        if name is not None:
            mapping[str(i)] = name
    return mapping


def _is_heredoc_terminator(line: str, delim: str, *, indented: bool) -> bool:
    """True when ``line`` closes a heredoc opened with ``delim``.

    ``<<-`` allows the terminator to be indented with leading tabs (and, for
    Dockerfile practicality, leading spaces). Plain ``<<`` requires an exact
    match after trailing-whitespace strip only.
    """
    candidate = line.rstrip("\r\n").rstrip()
    if indented:
        return candidate.lstrip(" \t") == delim
    return candidate == delim


def join_continued_lines(text: str) -> list[str]:
    """Join Dockerfile physical lines into logical instructions.

    Models BuildKit/Docker preprocessing that the gates care about:

    1. Backslash continuations — Docker removes **comment-only** lines inside a
       ``\\`` continuation *before* joining, so a mid-continuation ``#`` line
       must not split one logical instruction into two. A comment-only line
       that *ends* in ``\\`` must **not** start a continuation (otherwise the
       next ``COPY --from`` is absorbed into a ``#…`` logical line and vanishes).
    2. Heredocs — ``RUN <<EOF`` / ``RUN <<-EOF`` / ``COPY <<…`` only when
       ``<<`` is a genuine redirect on a RUN/COPY/ADD instruction (not in a
       comment, not a shift operator). ``<<-`` closes on an indented terminator.
       Body folds into one logical command so pip/uv/COPY edges stay visible.
    """
    physical = text.splitlines()
    logical: list[str] = []
    buf = ""
    continuing = False
    i = 0
    while i < len(physical):
        raw = physical[i]
        line = raw.rstrip()

        # Heredoc only starts a new instruction when not mid-continuation.
        if not continuing:
            # Full-line comments never open heredocs or backslash continuations.
            # Strip a trailing inline comment only for heredoc detection so
            # ``RUN <<EOF  # note`` still opens, while ``# prefer RUN <<EOF``
            # does not.
            if line.lstrip().startswith("#"):
                logical.append(line)
                i += 1
                continue

            scan = _strip_trailing_comment(line)
            heredoc = _HEREDOC_OPEN_RE.match(scan)
            if heredoc:
                delim = heredoc.group("delim")
                indented = heredoc.group("dash") == "-"
                prefix = heredoc.group("prefix")
                suffix = heredoc.group("suffix").strip()
                body_parts: list[str] = []
                i += 1
                while i < len(physical):
                    if _is_heredoc_terminator(physical[i], delim, indented=indented):
                        break
                    body_parts.append(physical[i].rstrip())
                    i += 1
                # Skip the closing delimiter when present.
                if i < len(physical) and _is_heredoc_terminator(
                    physical[i], delim, indented=indented
                ):
                    i += 1
                body = " ; ".join(
                    part.strip()
                    for part in body_parts
                    if part.strip() and not part.strip().startswith("#")
                )
                pieces = [prefix.rstrip(), body, suffix]
                logical.append(" ".join(p for p in pieces if p))
                continue

        # Inside a backslash continuation, Docker drops comment-only lines.
        if continuing:
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped == "":
                i += 1
                continue

        if line.endswith("\\"):
            buf += line[:-1] + " "
            continuing = True
            i += 1
            continue

        buf += line
        logical.append(buf)
        buf = ""
        continuing = False
        i += 1

    if buf:
        logical.append(buf)
    return logical


def copy_from_dep_stages(
    stage_text: str,
    *,
    stage_index: dict[str, str] | None = None,
) -> list[str]:
    """Stage names referenced by ``COPY --from=`` in ``stage_text``.

    Every ``COPY --from`` edge is a dependency-set provenance edge (D5.4): a
    path allowlist previously let ``COPY --from=builder-vlm / /`` (or any path
    outside venv/site-packages) ship torch while the gate stayed green.
    Numeric refs (``COPY --from=0``) resolve via ``stage_index`` when provided.
    """
    deps: list[str] = []
    for line in join_continued_lines(stage_text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _COPY_FROM_RE.match(stripped)
        if not match:
            continue
        ref = match.group(1)
        # Strip quotes if present: --from="builder"
        if len(ref) >= 2 and ref[0] == ref[-1] and ref[0] in {"'", '"'}:
            ref = ref[1:-1]
        if stage_index is not None and ref.isdigit() and ref in stage_index:
            ref = stage_index[ref]
        deps.append(ref)
    return deps


def has_vlm_extra(stage_text: str) -> bool:
    """True when the stage text resolves the project ``vlm`` extra.

    Scans **logical** instructions (backslash continuations joined, comments
    skipped) so a live Dockerfile form such as::

        RUN uv sync --extra \\
            vlm

    is detected, and prose/comments mentioning ``--extra vlm`` are not.

    Recognises (RC2 / D5.3):
    - ``--extra vlm`` / ``--extra=vlm`` / ``--extra "vlm"`` / ``--extra='vlm'``
    - ``--all-extras`` (implies vlm when the project declares it)
    - project-extras forms ``.[vlm]`` / ``".[bench,vlm]"`` / ``'.[vlm]'``
    """
    for line in join_continued_lines(stage_text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        active = _strip_trailing_comment(stripped)
        if not active:
            continue
        if re.search(r"--all-extras\b", active):
            return True
        if _EXTRA_VLM_RE.search(active):
            return True
        for match in _PROJECT_EXTRAS_RE.finditer(active):
            if re.search(r"\bvlm\b", match.group(0)):
                return True
    return False



def stage_resolves_vlm_extra(
    dockerfile: Path,
    stage: str,
    *,
    _stack: frozenset[str] | None = None,
    _own: dict[str, str] | None = None,
    _bases: dict[str, str] | None = None,
    _index: dict[str, str] | None = None,
) -> bool:
    """True if ``stage``'s built image would contain the vlm extra.

    Checks the effective body (FROM inheritance) and walks ``COPY --from``
    edges as dependency-set provenance (RC3 / D5.4). A default ``runtime`` that
    copies a venv from a builder which synced ``--extra=vlm`` / ``--all-extras``
    is a failure even though the runtime stage's own body never mentions vlm.

    Raises ``ValueError`` on a ``COPY --from`` / FROM provenance cycle instead
    of returning False (silent cycle was a gate bypass).
    """
    stack = _stack or frozenset()
    if stage in stack:
        cycle = " -> ".join([*stack, stage])
        raise ValueError(f"Dockerfile stage dependency cycle: {cycle}")
    if _own is None or _bases is None or _index is None:
        own, bases, order = _parse_dockerfile(dockerfile)
        index = _stage_index_map(order)
    else:
        own, bases, index = _own, _bases, _index
    if stage not in own:
        raise AssertionError(
            f"Dockerfile missing stage {stage!r}; have {list(own)}"
        )
    eff = _resolve_effective(own, bases, stage)
    if has_vlm_extra(eff):
        return True
    next_stack = stack | {stage}
    for dep in copy_from_dep_stages(eff, stage_index=index):
        if dep in own and stage_resolves_vlm_extra(
            dockerfile,
            dep,
            _stack=next_stack,
            _own=own,
            _bases=bases,
            _index=index,
        ):
            return True
    return False


def _strip_leading_wrappers(fragment: str) -> str:
    """Drop RUN / env wrappers / VAR=VALUE / python -m prefixes before pip.

    Keeps the install match behavioural rather than start-anchored so
    ``PIP_NO_INPUT=1 pip install ".[bench]"`` and ``env FOO=1 …`` cannot evade.
    """
    text = fragment.strip()
    if text.upper().startswith("RUN"):
        rest = text[3:]
        if not rest or rest[0].isspace():
            text = rest.lstrip()
    # Repeat: env FOO=1 BAR=2 and bare FOO=1 prefixes may stack.
    while True:
        match = _ENV_ASSIGN_RE.match(text)
        if not match:
            break
        text = text[match.end() :]
    # Absolute or bare python -m pip …
    text = re.sub(
        r"^(?:/[\w./-]+/)?(?:python3?|[\w.-]*python3?)\s+-m\s+",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _fragments_to_scan(part: str) -> list[str]:
    """Expand shell wrappers so ``sh -c`` / ``sh -lc`` payloads are visible (D5.5)."""
    out = [part]
    for match in _SHELL_C_RE.finditer(part):
        body = match.group("body")
        out.append(body)
        # Nested fragments inside the quoted body.
        for sub in _FRAGMENT_SPLIT_RE.split(body):
            sub = sub.strip()
            if sub:
                out.append(sub)
    return out


def unlocked_project_extra_installs(stage_text: str) -> list[str]:
    """Install fragments that resolve project extras outside the frozen lock.

    Catches ``pip install .[bench]``, ``python -m pip install ".[bench]"``,
    ``/opt/venv/bin/python -m pip install '.[dev]'``, ``uv pip install …``,
    ``env FOO=1 pip install …``, ``PIP_NO_INPUT=1 pip install …``,
    ``sh -c`` / ``sh -lc`` / ``bash -c`` wrappers, line continuations,
    heredoc bodies, and any extra name — whenever ``--no-deps`` is absent
    from the *same* shell fragment (ORCH-LAUNCH-01-S1-RC-03 / RC4 / FIR4-BR-01 / D5).

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
            for fragment in _fragments_to_scan(part):
                fragment = fragment.strip()
                if not fragment or fragment.startswith("#"):
                    continue
                probe = _strip_leading_wrappers(fragment)
                if not _PIP_INSTALL_RE.search(probe):
                    continue
                if "--no-deps" in fragment:
                    continue
                if _PROJECT_EXTRAS_RE.search(fragment):
                    offenders.append(fragment)
    return offenders
