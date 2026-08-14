"""ORCH-LAUNCH-01 RC-05 / #473: weight-exclusion policy across two writers.

`.dockerignore` and `scripts/deploy/recognition-service.sh` rsync `--exclude=`
share one policy (artifact classes) but use **inverted** glob-depth semantics:

- **Docker**: `*.bin` is root-anchored; depth-recursive form is `**/*.bin`.
- **rsync**: a pattern with no `/` (except optional trailing `/`) matches the
  basename at every depth. `models--*/` is recursive; `**/models--*/` is NOT
  the portable "widen" form and must not appear in the rsync list.

A test that demands identical spellings across both tools can only go green by
getting one side wrong (the regression that put `**/models--*/` in rsync). This
module compares **artifact class sets**, each side spelled in its own syntax.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

# recognition/tests/deploy/<this> → parents[3] = service root;
# parents[5] = monorepo root.
SERVICE_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(__file__).resolve().parents[5]
DOCKERIGNORE = SERVICE_ROOT / ".dockerignore"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"

# Protected weight artifact classes (single source for class identity).
# Path-anchored ONNX is a required class but is not depth-recursive on either side
# (LICENSE/README under that dir must remain transferrable).
WEIGHT_EXTENSION_CLASSES: frozenset[str] = frozenset(
    ("safetensors", "bin", "pt", "pth", "gguf", "msgpack")
)
HF_SNAPSHOT_CLASS = "models--"
ONNX_CLASS = "onnx"
ONNX_PATTERN = "recognition/infrastructure/face_pipeline/models/*.onnx"

# Dead cache-dir patterns that must stay gone (ORCH-LAUNCH-01-S1-RA-09 / RB-06).
_DEAD_CACHE_PATTERNS = (
    "**/huggingface_cache/",
    "**/.cache/huggingface/",
)

_EXCLUDE_RE = re.compile(r"""--exclude=(?:'([^']+)'|"([^"]+)"|(\S+))""")
_INCLUDE_RE = re.compile(r"""--include=(?:'([^']+)'|"([^"]+)"|(\S+))""")
# rsync --filter='+ *.bin' / '--filter=- *.bin' (first token after = is rule).
_FILTER_RE = re.compile(
    r"""--filter=(?:'([^']+)'|"([^"]+)"|(\S+))"""
)
_FILES_FROM_RE = re.compile(r"""--files-from=(?:'([^']+)'|"([^"]+)"|(\S+))""")

# Docker depth-recursive weight patterns: **/ + class shape.
_DOCKER_EXT_RE = re.compile(
    r"^\*\*/\*\.(?P<ext>safetensors|bin|pt|pth|gguf|msgpack)$"
)
_DOCKER_HF_RE = re.compile(r"^\*\*/models--\*/$")

# rsync depth-recursive weight patterns: no non-trailing slash (basename-any-depth).
_RSYNC_EXT_RE = re.compile(
    r"^\*\.(?P<ext>safetensors|bin|pt|pth|gguf|msgpack)$"
)
_RSYNC_HF_RE = re.compile(r"^models--\*/$")

# Context-shipping rsync: SERVICE_DIR → REMOTE_BUILD_DIR (the real build-context
# transfer). Other inert rsync calls must not satisfy the weight-exclude gate (RC6).
_CONTEXT_RSYNC_DEST_RE = re.compile(
    r"""["']?\$\{?SSH_TARGET\}?:\$\{?REMOTE_BUILD_DIR\}?/?["']?"""
)
_CONTEXT_RSYNC_SRC_RE = re.compile(
    r"""["']?\$\{?SERVICE_DIR\}?/?["']?"""
)


def _iter_rsync_commands(text: str) -> list[str]:
    """Split deploy-script text into logical rsync command strings (\\-joined)."""
    commands: list[str] = []
    buf = ""
    in_rsync = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not in_rsync:
            if re.search(r"(?:^|&&|;|\|)\s*rsync\b", stripped) or stripped.startswith(
                "rsync "
            ) or stripped == "rsync":
                in_rsync = True
                buf = stripped
                if stripped.endswith("\\"):
                    buf = stripped[:-1] + " "
                    continue
                commands.append(buf)
                buf = ""
                in_rsync = False
            continue
        # Continuation of an rsync command.
        if stripped.endswith("\\"):
            buf += stripped[:-1] + " "
            continue
        buf += stripped
        commands.append(buf)
        buf = ""
        in_rsync = False
    if buf:
        commands.append(buf)
    return commands


def context_shipping_rsync_commands(text: str) -> list[str]:
    """Rsync invocations that ship SERVICE_DIR → REMOTE_BUILD_DIR (build context)."""
    hits: list[str] = []
    for cmd in _iter_rsync_commands(text):
        if _CONTEXT_RSYNC_SRC_RE.search(cmd) and _CONTEXT_RSYNC_DEST_RE.search(cmd):
            hits.append(cmd)
    return hits


def rsync_excludes_from_command(command: str) -> set[str]:
    """Parse --exclude= values from a single rsync command string."""
    patterns: set[str] = set()
    for match in _EXCLUDE_RE.finditer(command):
        value = match.group(1) or match.group(2) or match.group(3)
        if value:
            patterns.add(value)
    return patterns


def rsync_excludes_from_script(text: str) -> set[str]:
    """Parse --exclude= values from the context-shipping rsync only (RC6).

    Falls back to every rsync only when no context-shipping invocation is found
    (synthetic unit fixtures that omit SERVICE_DIR/REMOTE_BUILD_DIR markers).
    """
    context_cmds = context_shipping_rsync_commands(text)
    if context_cmds:
        patterns: set[str] = set()
        for cmd in context_cmds:
            patterns |= rsync_excludes_from_command(cmd)
        return patterns
    # Synthetic fixtures / unit tests without the real dest markers.
    patterns = set()
    for cmd in _iter_rsync_commands(text):
        patterns |= rsync_excludes_from_command(cmd)
    # Last resort: whole-text scan for fixtures that are a single bare command line.
    if not patterns:
        for match in _EXCLUDE_RE.finditer(text):
            value = match.group(1) or match.group(2) or match.group(3)
            if value:
                patterns.add(value)
    return patterns


def _active_dockerignore_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _docker_line_to_class(pattern: str) -> str | None:
    """Map a non-negated .dockerignore pattern to a weight class id, or None."""
    if pattern == ONNX_PATTERN:
        return ONNX_CLASS
    m = _DOCKER_EXT_RE.match(pattern)
    if m:
        return m.group("ext")
    if _DOCKER_HF_RE.match(pattern):
        return HF_SNAPSHOT_CLASS
    return None


def docker_weight_classes(text: str) -> set[str]:
    """Map .dockerignore → protected class ids with last-match-wins (RC5).

    Docker evaluates .dockerignore top-to-bottom; a later ``!**/*.bin``
    re-includes bin weights and removes the class from the excluded set.
    """
    # disposition[class] = True when currently excluded, False when re-included.
    disposition: dict[str, bool] = {}
    for line in _active_dockerignore_lines(text):
        negated = line.startswith("!")
        pattern = line[1:].lstrip() if negated else line
        class_id = _docker_line_to_class(pattern)
        if class_id is None:
            continue
        disposition[class_id] = not negated
    return {cid for cid, excluded in disposition.items() if excluded}


def _rsync_pattern_to_class(pattern: str) -> str | None:
    """Map an rsync include/exclude pattern to a weight class id, or None."""
    if pattern == ONNX_PATTERN:
        return ONNX_CLASS
    m = _RSYNC_EXT_RE.match(pattern)
    if m:
        return m.group("ext")
    if _RSYNC_HF_RE.match(pattern):
        return HF_SNAPSHOT_CLASS
    return None


def _rsync_filter_rule(raw: str) -> tuple[str, str] | None:
    """Parse ``+ pattern`` / ``- pattern`` filter rules → (disposition, pattern)."""
    text = raw.strip()
    if not text:
        return None
    # Leading merge-file tokens: + / - / P / S … we only care about +/- class patterns.
    if text[0] in {"+", "-"}:
        disp = "include" if text[0] == "+" else "exclude"
        pattern = text[1:].lstrip()
        if pattern:
            return disp, pattern
    return None


def rsync_weight_classes(text: str) -> set[str]:
    """Map context-shipping rsync rules → excluded class ids (first-match-wins).

    rsync evaluates ``--include`` / ``--exclude`` / ``--filter`` left-to-right;
    the first matching rule wins. A leading ``--include=*.bin`` before the
    weight excludes re-ships every ``.bin`` while a pure-exclude scan would
    still report full class coverage (G-06). ``--files-from`` is treated as
    failing closed for the whole class set (explicit file list bypasses
    exclude globs).
    """
    context_cmds = context_shipping_rsync_commands(text)
    commands = context_cmds if context_cmds else _iter_rsync_commands(text)
    if not commands:
        # Synthetic single-line fixtures without a full rsync invocation.
        disposition: dict[str, bool] = {}
        for match in _EXCLUDE_RE.finditer(text):
            value = match.group(1) or match.group(2) or match.group(3)
            if not value:
                continue
            class_id = _rsync_pattern_to_class(value)
            if class_id is not None and class_id not in disposition:
                disposition[class_id] = True  # excluded
        for match in _INCLUDE_RE.finditer(text):
            value = match.group(1) or match.group(2) or match.group(3)
            if not value:
                continue
            class_id = _rsync_pattern_to_class(value)
            if class_id is not None and class_id not in disposition:
                disposition[class_id] = False  # included (not excluded)
        return {cid for cid, excluded in disposition.items() if excluded}

    disposition: dict[str, bool] = {}
    for cmd in commands:
        if _FILES_FROM_RE.search(cmd):
            # Explicit file list: weight globs no longer protect the transfer.
            return set()
        # Walk flags left-to-right; first disposition per class wins.
        tokens: list[tuple[str, str]] = []
        for match in re.finditer(
            r"""--(?:exclude|include|filter)=(?:'([^']+)'|"([^"]+)"|(\S+))""",
            cmd,
        ):
            full = match.group(0)
            value = match.group(1) or match.group(2) or match.group(3) or ""
            if full.startswith("--exclude="):
                tokens.append(("exclude", value))
            elif full.startswith("--include="):
                tokens.append(("include", value))
            else:
                rule = _rsync_filter_rule(value)
                if rule is not None:
                    tokens.append(rule)
        for disp, pattern in tokens:
            class_id = _rsync_pattern_to_class(pattern)
            if class_id is None or class_id in disposition:
                continue
            disposition[class_id] = disp == "exclude"
    return {cid for cid, excluded in disposition.items() if excluded}


def expected_weight_classes() -> set[str]:
    return set(WEIGHT_EXTENSION_CLASSES) | {HF_SNAPSHOT_CLASS, ONNX_CLASS}


def _is_rsync_depth_recursive_pattern(pattern: str) -> bool:
    """True when pattern matches basename-at-any-depth under rsync rules.

    rsync: no non-trailing `/` means basename match at every depth.
    A leading `**/` injects a slash and is the wrong-tool spelling for rsync.
    """
    if pattern.startswith("**/"):
        return False
    # Allow a single trailing slash for directory-only excludes.
    body = pattern[:-1] if pattern.endswith("/") else pattern
    return "/" not in body


# ---- positive: real tree -------------------------------------------------


def test_dockerignore_weight_classes_are_docker_depth_recursive() -> None:
    """Each protected class has a Docker-recursive pattern (begins **/ for globs).

    Uses last-match-wins class disposition (RC5): a later ``!**/*.<ext>``
    re-inclusion must remove the class even when the exclude line still exists.
    """
    text = DOCKERIGNORE.read_text()
    classes = docker_weight_classes(text)
    missing = expected_weight_classes() - classes
    assert not missing, (
        f".dockerignore missing Docker-recursive coverage for classes: {sorted(missing)}. "
        f"Extensions must be **/*.<ext>; HF snapshots must be **/models--*/. "
        f"A later ! negation re-including a weight pattern also fails this gate (RC5)."
    )
    # Explicit shape: final disposition must exclude each class (not mere line presence).
    for ext in WEIGHT_EXTENSION_CLASSES:
        assert ext in classes, (
            f".dockerignore final disposition must exclude **/*.{ext} "
            f"(last-match-wins; a trailing !**/*.{ext} re-includes weights)"
        )
    assert HF_SNAPSHOT_CLASS in classes
    assert ONNX_CLASS in classes


def test_rsync_weight_classes_are_rsync_depth_recursive() -> None:
    """Each protected class has an rsync-recursive pattern on the context-shipping rsync.

    RC6: excludes on an inert second rsync must not satisfy this gate.
    """
    text = DEPLOY_SCRIPT.read_text()
    context_cmds = context_shipping_rsync_commands(text)
    assert context_cmds, (
        "deploy script must contain a context-shipping rsync "
        "(SERVICE_DIR → SSH_TARGET:REMOTE_BUILD_DIR)"
    )
    classes = rsync_weight_classes(text)
    missing = expected_weight_classes() - classes
    assert not missing, (
        f"context-shipping rsync excludes missing rsync-recursive coverage for "
        f"classes: {sorted(missing)}. "
        f"Extensions must be *.<ext>; HF snapshots must be models--*/ (no **/)."
    )
    excludes = rsync_excludes_from_script(text)
    for ext in WEIGHT_EXTENSION_CLASSES:
        assert f"*.{ext}" in excludes, (
            f"context-shipping rsync must --exclude='*.{ext}'"
        )
    assert "models--*/" in excludes
    assert ONNX_PATTERN in excludes


def test_weight_class_sets_match_across_writers() -> None:
    """Class sets must be equal so adding a weight type to one side only goes red."""
    di = docker_weight_classes(DOCKERIGNORE.read_text())
    rs = rsync_weight_classes(DEPLOY_SCRIPT.read_text())
    assert di, "dockerignore weight class set empty"
    assert rs, "rsync weight class set empty"
    assert di == rs == expected_weight_classes(), (
        f"class set mismatch: dockerignore={sorted(di)} rsync={sorted(rs)} "
        f"expected={sorted(expected_weight_classes())}"
    )


def test_no_rsync_exclude_begins_with_double_star_slash() -> None:
    """Regression guard: rsync must not use Docker-style **/ prefixes.

    A prior pass rewrote --exclude='models--*/' to --exclude='**/models--*/'
    believing it widened the guard. Under rsync rules that form is the wrong-tool
    spelling; basename-at-any-depth requires no non-trailing slash.
    """
    bad = sorted(
        p for p in rsync_excludes_from_script(DEPLOY_SCRIPT.read_text()) if p.startswith("**/")
    )
    assert not bad, (
        f"rsync --exclude patterns must not begin with '**/' (wrong-tool Docker spelling): {bad}"
    )


def test_dead_cache_dir_patterns_are_absent() -> None:
    """Dead cache-dir patterns must not re-enter as active exclude rules."""
    di_active = set(_active_dockerignore_lines(DOCKERIGNORE.read_text()))
    script_excludes = rsync_excludes_from_script(DEPLOY_SCRIPT.read_text())
    for dead in _DEAD_CACHE_PATTERNS:
        assert dead not in di_active, f"dead pattern {dead!r} reappeared in .dockerignore"
        assert dead not in script_excludes, f"dead pattern {dead!r} reappeared as rsync --exclude="


def _probe_repo_name(target: str, script: Path = DEPLOY_SCRIPT) -> subprocess.CompletedProcess[str]:
    """Call the real resolve_image_repo_name.

    The deploy script guards its dispatcher with BASH_SOURCE, so sourcing it
    defines the helpers without running a command. Probing behaviour keeps this
    gate alive across equivalent refactors of the case arms (TEST-06) — the
    earlier source-regex form went red when `runtime-vlm)` widened to
    `runtime-vlm|builder-vlm)` even though the mapping was unchanged.
    """
    return subprocess.run(
        ["bash", "-c", f'source "{script}"; resolve_image_repo_name'],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "ACX_BUILD_TARGET": target},
        timeout=15,
    )


def test_image_repo_name_derived_from_build_target() -> None:
    """RA-07: ACX_BUILD_TARGET selects a distinct repository so variants never collide."""
    script = DEPLOY_SCRIPT.read_text()
    assert "resolve_image_repo_name()" in script, "expected resolve_image_repo_name helper"
    for target in ("runtime-vlm", "builder-vlm"):
        proc = _probe_repo_name(target)
        assert proc.returncode == 0, f"{target}: {proc.stderr}"
        assert proc.stdout.strip().endswith("-vlm"), (
            f"{target} must map to IMAGE_NAME-vlm (got {proc.stdout.strip()!r})"
        )
    for target in ("", "runtime"):
        proc = _probe_repo_name(target)
        assert proc.returncode == 0, f"{target!r}: {proc.stderr}"
        assert not proc.stdout.strip().endswith("-vlm"), (
            f"{target!r} must keep the default IMAGE_NAME (got {proc.stdout.strip()!r})"
        )
    # Unmapped targets fail closed rather than inventing a repo suffix.
    assert _probe_repo_name("bogus").returncode != 0, "unknown ACX_BUILD_TARGET must fail closed"
    assert re.search(
        r'IMAGE_BASE="\$\{OCIR_REGISTRY\}/\$\{OCIR_NAMESPACE\}/\$\(resolve_image_repo_name\)"',
        script,
    ), "IMAGE_BASE must be derived from resolve_image_repo_name"
    # Rollback story documented for operators.
    assert "ACX_IMAGE_VARIANT" in script
    assert "acx-backend-vlm" in script


# ---- parsers / TEST-15 mutations ----------------------------------------


def test_parser_docker_classes_from_synthetic() -> None:
    body = (
        "# comment\n"
        "tests/\n"
        f"{ONNX_PATTERN}\n"
        "**/*.safetensors\n"
        "**/*.bin\n"
        "**/models--*/\n"
        # Wrong-tool / root-only forms must NOT count as depth-recursive classes.
        "*.pt\n"
        "README.md\n"
    )
    assert docker_weight_classes(body) == {
        ONNX_CLASS,
        "safetensors",
        "bin",
        HF_SNAPSHOT_CLASS,
    }


def test_parser_rsync_classes_from_synthetic() -> None:
    script = (
        "rsync -az --delete \\\n"
        "  --exclude='.git/' \\\n"
        "  --exclude='*.safetensors' \\\n"
        f"  --exclude='{ONNX_PATTERN}' \\\n"
        "  --exclude='models--*/' \\\n"
        "  --exclude='**/models--*/' \\\n"  # wrong-tool; must not count
        "  src/ dst/\n"
    )
    assert rsync_weight_classes(script) == {
        "safetensors",
        ONNX_CLASS,
        HF_SNAPSHOT_CLASS,
    }


def test_parity_bites_when_rsync_drops_a_class() -> None:
    """TEST-15: drop one rsync weight class → class sets diverge."""
    di_text = "**/*.safetensors\n**/*.bin\n**/*.pt\n**/models--*/\n" + ONNX_PATTERN + "\n"
    # rsync missing bin
    script_text = (
        "rsync -az \\\n"
        "  --exclude='*.safetensors' \\\n"
        "  --exclude='*.pt' \\\n"
        "  --exclude='models--*/' \\\n"
        f"  --exclude='{ONNX_PATTERN}' \\\n"
        "  src/ dst/\n"
    )
    di = docker_weight_classes(di_text)
    rs = rsync_weight_classes(script_text)
    assert "bin" in (di - rs)
    assert di != rs


def test_parity_bites_when_dockerignore_gains_unshared_class() -> None:
    """TEST-15: add a weight class only on the Docker side → sets diverge."""
    di_text = "**/*.safetensors\n**/*.gguf\n"
    script_text = "rsync -az --exclude='*.safetensors' src/ dst/\n"
    di = docker_weight_classes(di_text)
    rs = rsync_weight_classes(script_text)
    assert "gguf" in (di - rs)
    assert di != rs


def test_parity_bites_when_rsync_has_orphan_class() -> None:
    """TEST-15: weight class only on rsync side also fails set equality."""
    di_text = "**/*.safetensors\n"
    script_text = (
        "rsync -az --exclude='*.safetensors' --exclude='*.pth' src/ dst/\n"
    )
    di = docker_weight_classes(di_text)
    rs = rsync_weight_classes(script_text)
    assert rs - di == {"pth"}
    assert di != rs


def test_wrong_tool_spelling_does_not_satisfy_docker_class() -> None:
    """TEST-15: root-only *.ext (rsync spelling) must NOT count as Docker-recursive."""
    body = "*.safetensors\n*.bin\nmodels--*/\n"
    assert docker_weight_classes(body) == set()


def test_wrong_tool_spelling_does_not_satisfy_rsync_class() -> None:
    """TEST-15: Docker **/ form must NOT count as rsync-recursive for HF snapshots."""
    script = "rsync -az --exclude='**/models--*/' --exclude='**/*.safetensors' src/ dst/\n"
    # **/*.safetensors contains non-trailing slashes → not rsync depth-recursive class.
    # **/models--*/ starts with **/ → rejected by HF rsync regex.
    assert rsync_weight_classes(script) == set()
    bad = [p for p in rsync_excludes_from_script(script) if p.startswith("**/")]
    assert bad == ["**/models--*/", "**/*.safetensors"] or set(bad) == {
        "**/models--*/",
        "**/*.safetensors",
    }


def test_rsync_depth_recursive_helper_rejects_double_star() -> None:
    """TEST-15: helper itself goes red on **/ and green on basename forms."""
    assert _is_rsync_depth_recursive_pattern("*.bin")
    assert _is_rsync_depth_recursive_pattern("models--*/")
    assert _is_rsync_depth_recursive_pattern("__pycache__/")
    assert not _is_rsync_depth_recursive_pattern("**/models--*/")
    assert not _is_rsync_depth_recursive_pattern("**/*.bin")
    assert not _is_rsync_depth_recursive_pattern("recognition/infrastructure/face_pipeline/models/*.onnx")


def test_image_tag_derivation_mutation_would_collide(tmp_path: Path) -> None:
    """TEST-15: if resolve_image_repo_name dropped the vlm arm, variants would collide.

    Mutates a *copy of the real script* rather than a synthetic Python mirror —
    a mirror asserts on its own reimplementation and stays green no matter what
    the shell does.
    """
    assert _probe_repo_name("") .stdout.strip() != _probe_repo_name("runtime-vlm").stdout.strip(), (
        "empty and runtime-vlm targets must not share a repository (RA-07)"
    )

    original = DEPLOY_SCRIPT.read_text()
    mutant_text, subs = re.subn(
        r"^\s*runtime-vlm\|builder-vlm\)\s*printf.*$",
        "    runtime-vlm|builder-vlm) printf '%s\\\\n' \"${IMAGE_NAME}\" ;;",
        original,
        count=1,
        flags=re.MULTILINE,
    )
    assert subs == 1, "could not locate the vlm case arm to mutate (arm renamed?)"
    mutant = tmp_path / "recognition-service.sh"
    mutant.write_text(mutant_text)

    collided = _probe_repo_name("runtime-vlm", script=mutant).stdout.strip()
    baseline = _probe_repo_name("", script=mutant).stdout.strip()
    assert collided == baseline, (
        "mutation harness is inert: dropping the -vlm suffix did not cause a collision"
    )


def test_dockerignore_negation_reincludes_weight_class() -> None:
    """Wave-3 M5/RC5: later !**/*.bin re-includes bin weights (last-match-wins)."""
    body = (
        "**/*.safetensors\n"
        "**/*.bin\n"
        "**/*.pt\n"
        "**/models--*/\n"
        f"{ONNX_PATTERN}\n"
        # Hostile re-inclusion after the excludes (M5).
        "!**/*.bin\n"
        "!**/*.safetensors\n"
    )
    classes = docker_weight_classes(body)
    assert "bin" not in classes, "later !**/*.bin must drop bin from excluded set"
    assert "safetensors" not in classes, (
        "later !**/*.safetensors must drop safetensors from excluded set"
    )
    assert "pt" in classes
    # Control: mere line presence of **/*.bin would stay green under the old gate.
    lines = set(_active_dockerignore_lines(body))
    assert "**/*.bin" in lines and "!**/*.bin" in lines


def test_rsync_include_before_exclude_drops_class() -> None:
    """G-06 / first-match-wins: --include=*.bin ahead of --exclude=*.bin re-ships bins."""
    script = (
        "rsync -az --delete \\\n"
        "  --include='*.bin' \\\n"
        "  --exclude='*.safetensors' \\\n"
        "  --exclude='*.bin' \\\n"
        "  --exclude='*.pt' \\\n"
        "  --exclude='models--*/' \\\n"
        f"  --exclude='{ONNX_PATTERN}' \\\n"
        '  "${SERVICE_DIR}/" "${SSH_TARGET}:${REMOTE_BUILD_DIR}/"\n'
    )
    classes = rsync_weight_classes(script)
    assert "bin" not in classes, (
        "leading --include='*.bin' must drop bin from the excluded set (rsync first-match)"
    )
    assert "safetensors" in classes
    # filter=+ form is the same disposition.
    filtered = (
        "rsync -az \\\n"
        "  --filter='+ *.bin' \\\n"
        "  --exclude='*.bin' \\\n"
        "  --exclude='*.safetensors' \\\n"
        '  "${SERVICE_DIR}/" "${SSH_TARGET}:${REMOTE_BUILD_DIR}/"\n'
    )
    assert "bin" not in rsync_weight_classes(filtered)
    assert "safetensors" in rsync_weight_classes(filtered)


def test_rsync_excludes_bound_to_context_shipping_invocation() -> None:
    """Wave-3 M6/RC6: weight excludes on an inert rsync must not satisfy the gate."""
    # Real-shaped context rsync without weight excludes…
    context = (
        "rsync -az --delete \\\n"
        "  --exclude='.git/' \\\n"
        "  --exclude='__pycache__/' \\\n"
        '  "${SERVICE_DIR}/" "${SSH_TARGET}:${REMOTE_BUILD_DIR}/"\n'
    )
    # …plus an inert second rsync that holds the weight list (M6).
    inert = (
        "rsync -az \\\n"
        "  --exclude='*.safetensors' \\\n"
        "  --exclude='*.bin' \\\n"
        "  --exclude='*.pt' \\\n"
        "  --exclude='*.pth' \\\n"
        "  --exclude='*.gguf' \\\n"
        "  --exclude='*.msgpack' \\\n"
        "  --exclude='models--*/' \\\n"
        f"  --exclude='{ONNX_PATTERN}' \\\n"
        "  /tmp/empty/ /tmp/other/\n"
    )
    script = context + "\n" + inert
    # File-global grep would still find the excludes; context binding must not.
    file_global = {
        (m.group(1) or m.group(2) or m.group(3))
        for m in _EXCLUDE_RE.finditer(script)
    }
    assert "*.bin" in file_global, "control: whole-file grep would stay green"
    context_excludes = set()
    for cmd in context_shipping_rsync_commands(script):
        context_excludes |= rsync_excludes_from_command(cmd)
    assert "*.bin" not in context_excludes
    assert rsync_weight_classes(script) == set()
    # Positive control: excludes on the context-shipping command do count.
    fixed = (
        "rsync -az --delete \\\n"
        "  --exclude='*.safetensors' \\\n"
        "  --exclude='*.bin' \\\n"
        "  --exclude='models--*/' \\\n"
        f"  --exclude='{ONNX_PATTERN}' \\\n"
        '  "${SERVICE_DIR}/" "${SSH_TARGET}:${REMOTE_BUILD_DIR}/"\n'
    )
    assert rsync_weight_classes(fixed) == {
        "safetensors",
        "bin",
        HF_SNAPSHOT_CLASS,
        ONNX_CLASS,
    }
