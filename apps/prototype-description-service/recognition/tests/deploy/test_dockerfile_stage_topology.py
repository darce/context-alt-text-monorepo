"""ORCH-LAUNCH-01 S1: the default `docker build` target must stay torch-free.

BuildKit builds the *last* stage when `--target` is omitted, and no build path
in this repo passes `--target` — `scripts/deploy/recognition-service.sh` (local
and remote), `.github/workflows/deploy-recognition.yml` (which auto-deploys dev
on every push to main touching this service), and `infra/oci/README.md` all
build bare. So appending the VLM stage after `runtime` silently makes torch the
production image (ORCH-LAUNCH-01-S1-BR-01/RA-01/RB-01/RC-01).

The pre-existing packaging guard could not see this: it unions `COPY` lines
across the whole file, so a second runtime stage with identical COPYs is
invisible to it. Deleting both new stages left its 37 tests byte-identically
green (RC mutation (d)) — green that carried no information about the change.
Per TEST-15 the mutations that fooled it are pinned here as permanent guards,
and each is proven to bite against a synthetic Dockerfile rather than merely
asserting the current tree is clean.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# recognition/tests/deploy/<this> → parents[3] = the service root.
SERVICE_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = SERVICE_ROOT / "Dockerfile"

DEFAULT_STAGE = "runtime"
VLM_STAGE = "runtime-vlm"

_FROM_RE = re.compile(r"^\s*FROM\s+\S+(?:\s+AS\s+(?P<name>[\w.-]+))?\s*$", re.IGNORECASE)


def _dockerfile_stages(dockerfile: Path = DOCKERFILE) -> dict[str, str]:
    """Ordered {stage_name: stage_body} for every named `FROM ... AS <name>`.

    Insertion order is the file order, so `list(stages)[-1]` is the stage
    BuildKit builds when `--target` is omitted. Unnamed `FROM` lines start an
    anonymous stage; its body is discarded but it still terminates the previous
    stage, which keeps the bodies from bleeding into each other.
    """
    stages: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in Path(dockerfile).read_text().splitlines():
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


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "Dockerfile"
    path.write_text(text)
    return path


# ---- positive: the real tree is green -----------------------------------


def test_default_build_target_is_the_torch_free_runtime() -> None:
    stages = _dockerfile_stages()
    assert stages, "expected named build stages in the Dockerfile"
    assert list(stages)[-1] == DEFAULT_STAGE, (
        f"last stage is {list(stages)[-1]!r}, so a bare `docker build` would build it. "
        f"{DEFAULT_STAGE!r} must stay last or production ships the VLM image."
    )


def test_default_builder_does_not_install_the_vlm_extra() -> None:
    assert "--extra vlm" not in _dockerfile_stages()["builder"], (
        "the default `builder` stage must not sync --extra vlm; torch belongs to builder-vlm only"
    )


def test_vlm_stage_still_exists_and_is_reachable_by_target() -> None:
    stages = _dockerfile_stages()
    assert VLM_STAGE in stages, f"{VLM_STAGE!r} stage disappeared; `--target {VLM_STAGE}` would fail"
    assert "--extra vlm" in stages["builder-vlm"], "builder-vlm must sync the vlm extra"


def test_each_runtime_stage_copies_its_matching_builder() -> None:
    stages = _dockerfile_stages()
    assert "COPY --from=builder /opt/venv" in stages[DEFAULT_STAGE]
    assert "COPY --from=builder-vlm /opt/venv" in stages[VLM_STAGE]


def test_runtime_stages_are_distinguishable_at_runtime() -> None:
    """RA-07: an operator must be able to tell which image is running."""
    stages = _dockerfile_stages()
    assert "ACX_IMAGE_VARIANT=recognition" in stages[DEFAULT_STAGE]
    assert "ACX_IMAGE_VARIANT=vlm" in stages[VLM_STAGE]


# ---- negative: prove each guard bites (TEST-15) --------------------------

_SYNTHETIC = """\
FROM python:3.12-slim AS builder
RUN uv sync --frozen --no-dev --extra bench --no-install-project

FROM python:3.12-slim AS builder-vlm
RUN uv sync --frozen --no-dev --extra bench --extra vlm --no-install-project

FROM python:3.12-slim AS runtime-vlm
COPY --from=builder-vlm /opt/venv /opt/venv
ENV ACX_IMAGE_VARIANT=vlm

FROM python:3.12-slim AS runtime
COPY --from=builder /opt/venv /opt/venv
ENV ACX_IMAGE_VARIANT=recognition
"""


def test_parser_reads_the_synthetic_control(tmp_path: Path) -> None:
    stages = _dockerfile_stages(_write(tmp_path, _SYNTHETIC))
    assert list(stages) == ["builder", "builder-vlm", "runtime-vlm", "runtime"]


def test_guard_bites_when_stage_order_is_swapped(tmp_path: Path) -> None:
    """RC mutation (a): appending runtime-vlm last flips the default target."""
    swapped = _SYNTHETIC.replace(
        "FROM python:3.12-slim AS runtime-vlm\nCOPY --from=builder-vlm /opt/venv /opt/venv\nENV ACX_IMAGE_VARIANT=vlm\n\n",
        "",
    ) + "\nFROM python:3.12-slim AS runtime-vlm\nCOPY --from=builder-vlm /opt/venv /opt/venv\nENV ACX_IMAGE_VARIANT=vlm\n"
    assert list(_dockerfile_stages(_write(tmp_path, swapped)))[-1] == VLM_STAGE


def test_guard_bites_when_default_builder_gains_the_vlm_extra(tmp_path: Path) -> None:
    """RC mutation (b): torch leaks into the default image via the builder."""
    leaked = _SYNTHETIC.replace(
        "RUN uv sync --frozen --no-dev --extra bench --no-install-project",
        "RUN uv sync --frozen --no-dev --extra bench --extra vlm --no-install-project",
        1,
    )
    assert "--extra vlm" in _dockerfile_stages(_write(tmp_path, leaked))["builder"]


def test_guard_bites_when_the_vlm_stages_are_deleted(tmp_path: Path) -> None:
    """RC mutation (d): the old suite stayed green with the whole change gone."""
    stages = _dockerfile_stages(
        _write(tmp_path, "FROM python:3.12-slim AS builder\nFROM python:3.12-slim AS runtime\n")
    )
    assert VLM_STAGE not in stages


@pytest.mark.parametrize("stage", [DEFAULT_STAGE, VLM_STAGE])
def test_guard_bites_when_a_variant_marker_is_missing(tmp_path: Path, stage: str) -> None:
    stripped = _SYNTHETIC.replace(
        f"ENV ACX_IMAGE_VARIANT={'recognition' if stage == DEFAULT_STAGE else 'vlm'}\n", "", 1
    )
    assert "ACX_IMAGE_VARIANT" not in _dockerfile_stages(_write(tmp_path, stripped))[stage]
