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

from pathlib import Path

import pytest

from recognition.tests.dockerfile_stages import (
    DockerfileParseError,
    default_build_target,
    dockerfile_stages as _dockerfile_stages_shared,
    effective_stage_body,
    has_vlm_extra,
    parse_from_instruction,
    stage_resolves_vlm_extra,
)

# recognition/tests/deploy/<this> → parents[3] = the service root.
SERVICE_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = SERVICE_ROOT / "Dockerfile"

DEFAULT_STAGE = "runtime"
VLM_STAGE = "runtime-vlm"


def _dockerfile_stages(dockerfile: Path = DOCKERFILE) -> dict[str, str]:
    """Own-body stage map via the shared parser (file order preserved)."""
    return _dockerfile_stages_shared(dockerfile)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "Dockerfile"
    path.write_text(text)
    return path


# ---- positive: the real tree is green -----------------------------------


def test_default_build_target_is_the_torch_free_runtime() -> None:
    stages = _dockerfile_stages()
    assert stages, "expected named build stages in the Dockerfile"
    last = default_build_target(DOCKERFILE)
    assert last == DEFAULT_STAGE, (
        f"last stage is {last!r}, so a bare `docker build` would build it. "
        f"{DEFAULT_STAGE!r} must stay last or production ships the VLM image."
    )
    assert list(stages)[-1] == DEFAULT_STAGE


def test_default_builder_does_not_install_the_vlm_extra() -> None:
    """Default builder must not resolve vlm (space, equals, or --all-extras forms)."""
    builder = _dockerfile_stages()["builder"]
    assert not has_vlm_extra(builder), (
        "the default `builder` stage must not sync the vlm extra "
        "(--extra vlm / --extra=vlm / --all-extras / .[vlm]); torch belongs to builder-vlm only"
    )
    # COPY --from provenance: default runtime must not receive a vlm-contaminated venv.
    assert not stage_resolves_vlm_extra(DOCKERFILE, DEFAULT_STAGE), (
        "default runtime image must not resolve the vlm extra via own body, FROM parents, "
        "or COPY --from venv edges (RC3)"
    )


def test_vlm_stage_still_exists_and_is_reachable_by_target() -> None:
    stages = _dockerfile_stages()
    assert VLM_STAGE in stages, f"{VLM_STAGE!r} stage disappeared; `--target {VLM_STAGE}` would fail"
    assert has_vlm_extra(stages["builder-vlm"]), "builder-vlm must sync the vlm extra"
    assert stage_resolves_vlm_extra(DOCKERFILE, VLM_STAGE), (
        "runtime-vlm must resolve the vlm extra (via builder-vlm COPY --from)"
    )


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
    path = _write(tmp_path, leaked)
    assert has_vlm_extra(_dockerfile_stages(path)["builder"])
    assert stage_resolves_vlm_extra(path, DEFAULT_STAGE)


@pytest.mark.parametrize(
    "extra_flag",
    ["--extra=vlm", "--all-extras"],
    ids=["equals-form", "all-extras"],
)
def test_guard_bites_on_equals_and_all_extras_vlm_forms(
    tmp_path: Path, extra_flag: str
) -> None:
    """Wave-3 M2/M2b: --extra=vlm and --all-extras must be detected (RC2)."""
    leaked = _SYNTHETIC.replace(
        "RUN uv sync --frozen --no-dev --extra bench --no-install-project",
        f"RUN uv sync --frozen --no-dev --extra bench {extra_flag} --no-install-project",
        1,
    )
    path = _write(tmp_path, leaked)
    assert has_vlm_extra(_dockerfile_stages(path)["builder"]), extra_flag
    assert stage_resolves_vlm_extra(path, DEFAULT_STAGE), extra_flag


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


def test_effective_body_follows_named_stage_parent(tmp_path: Path) -> None:
    """Wave-2: effective body includes parent stage instructions."""
    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS runtime-base\n"
        "COPY scripts/ scripts/\n"
        'CMD ["/app/scripts/docker-entrypoint.sh"]\n'
        "\n"
        "FROM runtime-base AS runtime\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
    )
    own = _dockerfile_stages(path)[DEFAULT_STAGE]
    assert "COPY scripts/ scripts/" not in own
    assert "CMD" not in own
    eff = effective_stage_body(path, DEFAULT_STAGE)
    assert "COPY scripts/ scripts/" in eff
    assert 'CMD ["/app/scripts/docker-entrypoint.sh"]' in eff
    assert "ACX_IMAGE_VARIANT=recognition" in eff
    # Own-body order invariant for default target is unchanged.
    assert list(_dockerfile_stages(path))[-1] == DEFAULT_STAGE


def test_from_parser_tolerates_platform_flag_and_trailing_comment() -> None:
    """RC1: FROM --platform=… and trailing # comments must parse, not become body."""
    ref, name = parse_from_instruction(
        "FROM --platform=$TARGETPLATFORM runtime-vlm AS runtime-final"
    )
    assert (ref, name) == ("runtime-vlm", "runtime-final")
    ref, name = parse_from_instruction(
        "FROM runtime-vlm AS runtime-final # ship the vlm image by default"
    )
    assert (ref, name) == ("runtime-vlm", "runtime-final")
    ref, name = parse_from_instruction("FROM python:3.12-slim AS builder")
    assert (ref, name) == ("python:3.12-slim", "builder")


def test_from_parser_raises_on_unparseable_from_line() -> None:
    """RC1: unparseable FROM must RAISE, never silently reclassify as body."""
    with pytest.raises(DockerfileParseError):
        parse_from_instruction("FROM")
    with pytest.raises(DockerfileParseError):
        parse_from_instruction("FROM --platform=linux/arm64")
    with pytest.raises(DockerfileParseError):
        parse_from_instruction("FROM python:3.12-slim AS")


def test_guard_bites_when_platform_flagged_final_stage_appended(tmp_path: Path) -> None:
    """Wave-3 M1: FROM --platform=… AS runtime-final must flip default target."""
    text = _SYNTHETIC + (
        "\nFROM --platform=$TARGETPLATFORM runtime-vlm AS runtime-final\n"
    )
    path = _write(tmp_path, text)
    assert default_build_target(path) == "runtime-final"
    assert list(_dockerfile_stages(path))[-1] == "runtime-final"


def test_guard_bites_when_commented_final_stage_appended(tmp_path: Path) -> None:
    """Wave-3 M1b: trailing # comment on final FROM must not hide the stage."""
    text = _SYNTHETIC + (
        "\nFROM runtime-vlm AS runtime-final # ship the vlm image by default\n"
    )
    path = _write(tmp_path, text)
    assert default_build_target(path) == "runtime-final"


def test_guard_bites_when_copy_from_vlm_builder_contaminates_runtime(
    tmp_path: Path,
) -> None:
    """Wave-3 RC3/M8: COPY --from a stage that resolved vlm must fail the gate."""
    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS deps-base\n"
        "RUN uv sync --locked --extra vlm\n"
        "\n"
        "FROM deps-base AS builder\n"
        "RUN true\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "COPY --from=builder /opt/venv /opt/venv\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
    )
    # Own/effective runtime body never mentions vlm — provenance walk must.
    assert not has_vlm_extra(effective_stage_body(path, DEFAULT_STAGE))
    assert stage_resolves_vlm_extra(path, DEFAULT_STAGE)
    assert stage_resolves_vlm_extra(path, "builder")
