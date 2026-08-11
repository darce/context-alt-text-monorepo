"""ORCH-LAUNCH-01 RC-05: weight-exclusion policy has one guard across two writers.

`.dockerignore` excludes model-weight artifacts from the Docker build context, but
`scripts/deploy/recognition-service.sh` rsyncs that same context to the build VM
with its own `--exclude=` list and does NOT read `.dockerignore`. Two files, one
policy: delete a pattern from either and you get a green suite plus a multi-GB
transfer or image with zero signal.

This guard derives both pattern sets by parsing the real files and compares them
as sets. It does not hardcode a duplicated literal list — the set comparison is
the whole point of the finding.

Dead patterns (must NOT reappear): `**/huggingface_cache/` and
`**/.cache/huggingface/` match nothing that can exist in the build context
(real caches live at $HOME/.cache/huggingface outside the context, and at the
in-container path HF_HOME=/data/cache/huggingface_cache). The policy excludes
artifact CLASSES instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# recognition/tests/deploy/<this> → parents[3] = service root;
# parents[5] = monorepo root.
SERVICE_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(__file__).resolve().parents[5]
DOCKERIGNORE = SERVICE_ROOT / ".dockerignore"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"

# Artifact-class shapes that constitute the weight-exclusion policy. Used only
# to *classify* lines as weight-related when parsing either file — not as the
# expected set (that set is derived from the files under test).
_WEIGHT_LINE_RE = re.compile(
    r"^(?:"
    r"\*\.(?:safetensors|bin|pt|pth|gguf|msgpack)"
    r"|(?:\*\*/)?models--\*/"
    r"|.+\.onnx"
    r")$"
)

_EXCLUDE_RE = re.compile(r"""--exclude=(?:'([^']+)'|"([^"]+)"|(\S+))""")

# Face-pipeline ONNX rule (pre-existing; always part of the policy).
ONNX_EXCLUDE = "recognition/infrastructure/face_pipeline/models/*.onnx"

# Dead cache-dir patterns that must stay gone (ORCH-LAUNCH-01-S1-RA-09 / RB-06).
_DEAD_CACHE_PATTERNS = (
    "**/huggingface_cache/",
    "**/.cache/huggingface/",
)


def _is_weight_pattern(pattern: str) -> bool:
    return bool(_WEIGHT_LINE_RE.match(pattern.strip()))


def weight_patterns_from_dockerignore(text: str) -> set[str]:
    """Parse weight-artifact exclude patterns from a .dockerignore body."""
    patterns: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if _is_weight_pattern(line):
            patterns.add(line)
    return patterns


def rsync_excludes_from_script(text: str) -> set[str]:
    """Parse every --exclude= value from rsync invocations in the deploy script."""
    patterns: set[str] = set()
    for match in _EXCLUDE_RE.finditer(text):
        value = match.group(1) or match.group(2) or match.group(3)
        if value:
            patterns.add(value)
    return patterns


def weight_excludes_from_script(text: str) -> set[str]:
    """Weight-artifact subset of the script's rsync --exclude= list."""
    return {p for p in rsync_excludes_from_script(text) if _is_weight_pattern(p)}


def _load_real() -> tuple[set[str], set[str]]:
    di = weight_patterns_from_dockerignore(DOCKERIGNORE.read_text())
    rs = weight_excludes_from_script(DEPLOY_SCRIPT.read_text())
    return di, rs


# ---- positive: the real tree is green -----------------------------------


def test_dockerignore_lists_weight_artifact_classes() -> None:
    """Each weight artifact class currently in .dockerignore is present, plus ONNX."""
    patterns = weight_patterns_from_dockerignore(DOCKERIGNORE.read_text())
    assert patterns, "expected weight-artifact patterns in .dockerignore"
    assert ONNX_EXCLUDE in patterns, f"missing pre-existing ONNX rule {ONNX_EXCLUDE!r}"
    # Artifact extension classes (policy surface, not a duplicated parity list).
    for ext in ("safetensors", "bin", "pt", "pth", "gguf", "msgpack"):
        assert f"*.{ext}" in patterns, f".dockerignore must exclude *.{ext}"
    assert any("models--" in p for p in patterns), "expected HF snapshot dir exclude (models--*)"


def _active_lines(text: str) -> set[str]:
    """Non-comment, non-empty lines (active exclude rules / script code)."""
    lines: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.add(line)
    return lines


def test_dead_cache_dir_patterns_are_absent() -> None:
    """Dead cache-dir patterns must not re-enter as active exclude rules.

    Mentions inside comments (documenting why they were removed) are fine;
    only non-comment lines count as policy.
    """
    di_active = _active_lines(DOCKERIGNORE.read_text())
    # Script: treat --exclude='pattern' values as the active exclude set.
    script_excludes = rsync_excludes_from_script(DEPLOY_SCRIPT.read_text())
    for dead in _DEAD_CACHE_PATTERNS:
        assert dead not in di_active, f"dead pattern {dead!r} reappeared as active .dockerignore rule"
        assert dead not in script_excludes, f"dead pattern {dead!r} reappeared as rsync --exclude="


def test_weight_exclude_parity_between_dockerignore_and_rsync() -> None:
    """Every weight pattern in .dockerignore appears as rsync --exclude= (set parity)."""
    di, rs = _load_real()
    assert di, "dockerignore weight set empty — parser or policy broken"
    assert rs, "rsync weight exclude set empty — parser or policy broken"
    missing_from_rsync = di - rs
    extra_in_rsync = rs - di
    assert not missing_from_rsync, (
        f"weight patterns in .dockerignore missing from preflight_rsync --exclude=: "
        f"{sorted(missing_from_rsync)}"
    )
    assert not extra_in_rsync, (
        f"weight --exclude= patterns in deploy script not in .dockerignore: "
        f"{sorted(extra_in_rsync)}"
    )
    assert di == rs


# ---- negative: prove each guard bites (TEST-15) --------------------------


def test_parser_reads_synthetic_dockerignore(tmp_path: Path) -> None:
    body = (
        "# comment\n"
        "tests/\n"
        f"{ONNX_EXCLUDE}\n"
        "*.safetensors\n"
        "*.bin\n"
        "**/models--*/\n"
        "README.md\n"
    )
    got = weight_patterns_from_dockerignore(body)
    assert got == {
        ONNX_EXCLUDE,
        "*.safetensors",
        "*.bin",
        "**/models--*/",
    }


def test_parser_reads_synthetic_rsync_excludes(tmp_path: Path) -> None:
    script = (
        "rsync -az --delete \\\n"
        "  --exclude='.git/' \\\n"
        "  --exclude='*.safetensors' \\\n"
        f"  --exclude='{ONNX_EXCLUDE}' \\\n"
        "  --exclude=\"**/models--*/\" \\\n"
        "  src/ dst/\n"
    )
    assert rsync_excludes_from_script(script) == {
        ".git/",
        "*.safetensors",
        ONNX_EXCLUDE,
        "**/models--*/",
    }
    assert weight_excludes_from_script(script) == {
        "*.safetensors",
        ONNX_EXCLUDE,
        "**/models--*/",
    }


def test_parity_bites_when_rsync_drops_a_weight_pattern() -> None:
    """TEST-15: drop one --exclude= and the set comparison goes red."""
    di_text = "*.safetensors\n*.bin\n*.pt\n"
    script_text = (
        "rsync -az \\\n"
        "  --exclude='*.safetensors' \\\n"
        "  --exclude='*.pt' \\\n"
        "  src/ dst/\n"
    )
    di = weight_patterns_from_dockerignore(di_text)
    rs = weight_excludes_from_script(script_text)
    assert di - rs == {"*.bin"}
    assert di != rs


def test_parity_bites_when_dockerignore_gains_an_unshared_pattern() -> None:
    """TEST-15: add a weight class only to .dockerignore → parity fails."""
    di_text = "*.safetensors\n*.gguf\n"
    script_text = "rsync -az --exclude='*.safetensors' src/ dst/\n"
    di = weight_patterns_from_dockerignore(di_text)
    rs = weight_excludes_from_script(script_text)
    assert "*.gguf" in (di - rs)
    assert di != rs


def test_parity_bites_when_rsync_has_orphan_weight_exclude() -> None:
    """TEST-15: weight exclude only on the rsync side also fails set equality."""
    di_text = "*.safetensors\n"
    script_text = (
        "rsync -az --exclude='*.safetensors' --exclude='*.pth' src/ dst/\n"
    )
    di = weight_patterns_from_dockerignore(di_text)
    rs = weight_excludes_from_script(script_text)
    assert rs - di == {"*.pth"}
    assert di != rs


def test_classifier_ignores_non_weight_excludes() -> None:
    """Non-weight rsync excludes (caches, venv) must not enter the weight set."""
    script_text = (
        "rsync -az --exclude='.git/' --exclude='.venv/' "
        "--exclude='*.safetensors' src/ dst/\n"
    )
    assert weight_excludes_from_script(script_text) == {"*.safetensors"}
