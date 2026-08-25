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

from recognition.tests.dockerfile_stages import (
    DockerfileParseError,
    copy_from_dep_stages,
    default_build_target,
    dockerfile_stages as _dockerfile_stages_shared,
    effective_stage_body,
    has_vlm_extra,
    join_continued_lines,
    parse_from_instruction,
    stage_resolves_vlm_extra,
    unlocked_project_extra_installs,
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
    path.parent.mkdir(parents=True, exist_ok=True)
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
    # Do not use list(stages)[-1]: named-only order is not BuildKit's default
    # when an anonymous final FROM exists (D5.1 / A-13).


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
    """Parsed COPY --from deps, not raw substring (A-11)."""
    stages = _dockerfile_stages()
    assert copy_from_dep_stages(stages[DEFAULT_STAGE]) == ["builder"]
    assert copy_from_dep_stages(stages[VLM_STAGE]) == ["builder-vlm"]


def test_runtime_stages_are_distinguishable_at_runtime() -> None:
    """RA-07: an operator must be able to tell which image is running."""
    stages = _dockerfile_stages()
    # ENV map lookup via active lines (not brittle substring adjacency).
    def _env_map(body: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for ln in body.splitlines():
            m = re.match(r"^\s*ENV\s+([A-Za-z_][\w]*)=(.+?)\s*$", ln)
            if m:
                out[m.group(1)] = m.group(2).strip().strip("'\"")
        return out

    assert _env_map(stages[DEFAULT_STAGE]).get("ACX_IMAGE_VARIANT") == "recognition"
    assert _env_map(stages[VLM_STAGE]).get("ACX_IMAGE_VARIANT") == "vlm"


def test_runtime_vlm_is_opt_in_offline_and_not_the_default_target() -> None:
    """PROV-01b: runtime-vlm carries torch extras but never becomes the bare build."""
    stages = _dockerfile_stages()
    vlm = stages[VLM_STAGE]

    def _env_map(body: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for ln in body.splitlines():
            m = re.match(r"^\s*ENV\s+([A-Za-z_][\w]*)=(.+?)\s*$", ln)
            if m:
                out[m.group(1)] = m.group(2).strip().strip("'\"")
        return out

    env = _env_map(vlm)
    assert default_build_target(DOCKERFILE) == DEFAULT_STAGE
    assert default_build_target(DOCKERFILE) != VLM_STAGE
    assert env.get("ACX_IMAGE_VARIANT") == "vlm"
    assert env.get("HF_HUB_OFFLINE") == "1"
    assert env.get("TRANSFORMERS_OFFLINE") == "1"
    assert stage_resolves_vlm_extra(DOCKERFILE, VLM_STAGE)
    assert not stage_resolves_vlm_extra(DOCKERFILE, DEFAULT_STAGE)


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
    """RC mutation (a): appending runtime-vlm last flips the default target.

    Routes through ``default_build_target`` (BuildKit last-stage rule), not
    ``list(named_stages)[-1]`` which ignores anonymous finals (A-13).
    """
    swapped = _SYNTHETIC.replace(
        "FROM python:3.12-slim AS runtime-vlm\nCOPY --from=builder-vlm /opt/venv /opt/venv\nENV ACX_IMAGE_VARIANT=vlm\n\n",
        "",
    ) + "\nFROM python:3.12-slim AS runtime-vlm\nCOPY --from=builder-vlm /opt/venv /opt/venv\nENV ACX_IMAGE_VARIANT=vlm\n"
    path = _write(tmp_path, swapped)
    assert default_build_target(path) == VLM_STAGE


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


# ---- D5: six parser bypasses (synthetic fixtures only; never live DOCKERFILE) -


def test_d5_anonymous_final_stage_is_buildkit_default(tmp_path: Path) -> None:
    """D5.1: anonymous final FROM is BuildKit's default; last *named* stage is not.

    Before: default_build_target returned list(named)[-1] == runtime while
    BuildKit would build the trailing anonymous FROM runtime-vlm.
    After: default_build_target returns None (anonymous last) so the gate fails.
    """
    path = _write(
        tmp_path,
        _SYNTHETIC + "\nFROM runtime-vlm\nENV LEAKED=1\n",
    )
    named = _dockerfile_stages(path)
    assert list(named)[-1] == DEFAULT_STAGE, "control: last named stage still runtime"
    assert default_build_target(path) is None, (
        "anonymous final stage must not report a named default target"
    )
    assert default_build_target(path) != DEFAULT_STAGE


def test_d5_comment_inside_line_continuation_keeps_copy_edge(tmp_path: Path) -> None:
    """D5.2: Docker drops # lines inside \\ continuations before join.

    Before: join split the COPY across the comment, so COPY --from deps vanished.
    After: the logical COPY remains one instruction and provenance sees the edge.
    """
    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS builder-vlm\n"
        "RUN uv sync --locked --extra vlm\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "COPY --from=builder-vlm \\\n"
        "  # comment inside continuation (Docker strips this before join)\n"
        "  /opt/venv /opt/venv\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
    )
    body = _dockerfile_stages(path)[DEFAULT_STAGE]
    joined = join_continued_lines(body)
    assert any("COPY --from=builder-vlm" in ln and "/opt/venv" in ln for ln in joined), (
        f"continuation+comment must yield one COPY logical line; got {joined!r}"
    )
    assert copy_from_dep_stages(body) == ["builder-vlm"]
    assert stage_resolves_vlm_extra(path, DEFAULT_STAGE)


def test_d5_quoted_extra_vlm_is_detected(tmp_path: Path) -> None:
    """D5.3: --extra \"vlm\" / --extra='vlm' must count as the vlm extra.

    Before: only bare --extra vlm / --extra=vlm matched; quotes evaded the gate.
    After: quoted forms are detected and stage_resolves_vlm_extra goes red.
    """
    for flag in ('--extra "vlm"', "--extra='vlm'", '--extra="vlm"'):
        path = _write(
            tmp_path,
            "FROM python:3.12-slim AS builder\n"
            f"RUN uv sync --locked {flag}\n"
            "\n"
            "FROM python:3.12-slim AS runtime\n"
            "COPY --from=builder /opt/venv /opt/venv\n",
        )
        assert has_vlm_extra(_dockerfile_stages(path)["builder"]), flag
        assert stage_resolves_vlm_extra(path, DEFAULT_STAGE), flag


def test_d5_numeric_copy_from_and_path_allowlist_and_cycle(tmp_path: Path) -> None:
    """D5.4: numeric --from, non-venv paths, and COPY cycles must not evade.

    Before:
      - COPY --from=0 resolved as stage name \"0\" (miss)
      - COPY --from=builder-vlm / / skipped by path allowlist
      - provenance cycles returned False silently
    After: numeric refs resolve, all COPY --from edges count, cycles raise.
    """
    # Numeric stage index 0 -> builder-vlm
    numeric = _write(
        tmp_path / "numeric",
        "FROM python:3.12-slim AS builder-vlm\n"
        "RUN uv sync --locked --extra vlm\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "COPY --from=0 /opt/venv /opt/venv\n",
    )
    assert stage_resolves_vlm_extra(numeric, DEFAULT_STAGE)

    # Path outside the old venv/site-packages allowlist
    root_copy = _write(
        tmp_path / "rootcopy",
        "FROM python:3.12-slim AS builder-vlm\n"
        "RUN uv sync --locked --extra vlm\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "COPY --from=builder-vlm / /\n",
    )
    assert copy_from_dep_stages(_dockerfile_stages(root_copy)[DEFAULT_STAGE]) == [
        "builder-vlm"
    ]
    assert stage_resolves_vlm_extra(root_copy, DEFAULT_STAGE)

    # COPY --from cycle must raise, not return False
    cyclic = _write(
        tmp_path / "cycle",
        "FROM python:3.12-slim AS a\n"
        "COPY --from=b /opt/venv /opt/venv\n"
        "\n"
        "FROM python:3.12-slim AS b\n"
        "COPY --from=a /opt/venv /opt/venv\n",
    )
    with pytest.raises(ValueError, match="cycle"):
        stage_resolves_vlm_extra(cyclic, "a")


def test_d5_pip_install_env_and_shell_wrappers(tmp_path: Path) -> None:
    """D5.5: env FOO=1 pip install and sh -c \"pip install\" must trip the gate.

    Before: _PIP_INSTALL_RE required the install at fragment start, so wrappers
    returned []. After: both forms appear in unlocked_project_extra_installs.
    """
    env_wrapped = 'RUN env FOO=1 pip install ".[bench]"'
    assert unlocked_project_extra_installs(env_wrapped), env_wrapped

    shell_wrapped = 'RUN sh -c "pip install .[bench]"'
    assert unlocked_project_extra_installs(shell_wrapped), shell_wrapped

    bash_wrapped = "RUN bash -c 'pip install .[dev]'"
    assert unlocked_project_extra_installs(bash_wrapped), bash_wrapped

    # Control: --no-deps still exempts.
    assert not unlocked_project_extra_installs(
        'RUN env FOO=1 pip install --no-deps ".[bench]"'
    )


def test_d5_heredoc_run_body_is_modelled(tmp_path: Path) -> None:
    """D5.6: RUN <<EOF bodies must be one logical command for install scanning.

    Before: heredoc lines were separate; a wrapped install inside could hide.
    After: join_continued_lines folds the body and unlocked installs fire.
    """
    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS builder\n"
        "RUN <<EOF\n"
        'env FOO=1 pip install ".[bench]"\n'
        "EOF\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "RUN true\n",
    )
    body = _dockerfile_stages(path)["builder"]
    joined = join_continued_lines(body)
    assert len(joined) == 1, f"heredoc must fold to one logical RUN; got {joined!r}"
    assert "pip install" in joined[0]
    offenders = unlocked_project_extra_installs(body)
    assert offenders, f"heredoc pip install must be detected; joined={joined!r}"


def test_d5_heredoc_false_positives_do_not_blind_copy_from(tmp_path: Path) -> None:
    """W5C: ``<<`` in comments / shift ops must not swallow the rest of the stage.

    Before: _HEREDOC_OPEN_RE fired on any ``<<``, so a comment like
    ``# prefer RUN <<EOF`` or ``RUN python -c 'print(1<<3)'`` consumed every
    subsequent line as a heredoc body — ``copy_from_dep_stages`` returned [],
    ``stage_resolves_vlm_extra`` stayed False, and gates reported clean.
    """
    # Comment mentioning heredoc must leave the following COPY visible.
    comment_poison = _write(
        tmp_path / "comment",
        "FROM python:3.12-slim AS builder-vlm\n"
        "RUN uv sync --locked --extra vlm\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "# prefer RUN <<EOF for multi-line installs\n"
        "COPY --from=builder-vlm /opt/venv /opt/venv\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
    )
    body = _dockerfile_stages(comment_poison)[DEFAULT_STAGE]
    assert copy_from_dep_stages(body) == ["builder-vlm"], (
        f"comment << must not blind COPY --from; joined={join_continued_lines(body)!r}"
    )
    assert stage_resolves_vlm_extra(comment_poison, DEFAULT_STAGE)

    # Shift operator must not open a heredoc.
    shift = _write(
        tmp_path / "shift",
        "FROM python:3.12-slim AS builder-vlm\n"
        "RUN uv sync --locked --extra vlm\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "RUN python -c 'print(1<<3)'\n"
        "COPY --from=builder-vlm /opt/venv /opt/venv\n",
    )
    body = _dockerfile_stages(shift)[DEFAULT_STAGE]
    assert copy_from_dep_stages(body) == ["builder-vlm"], (
        f"shift << must not blind COPY --from; joined={join_continued_lines(body)!r}"
    )
    assert stage_resolves_vlm_extra(shift, DEFAULT_STAGE)


def test_d5_heredoc_indented_terminator_closes(tmp_path: Path) -> None:
    """W5C: ``RUN <<-EOF`` must close on a tab/space-indented terminator."""
    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS builder\n"
        "RUN <<-EOF\n"
        'env FOO=1 pip install ".[bench]"\n'
        "\tEOF\n"
        "RUN true\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "RUN true\n",
    )
    body = _dockerfile_stages(path)["builder"]
    joined = join_continued_lines(body)
    assert any("pip install" in ln for ln in joined), joined
    # Second RUN must remain a separate logical line (terminator closed).
    assert any(ln.strip() == "RUN true" or ln.strip().endswith("RUN true") for ln in joined) or any(
        "RUN true" in ln and "pip install" not in ln for ln in joined
    ), f"indented terminator must close heredoc; got {joined!r}"
    assert unlocked_project_extra_installs(body)


def test_d5_has_vlm_extra_joins_continuations_and_ignores_comments(tmp_path: Path) -> None:
    """W5C: has_vlm_extra must use join_continued_lines (live Dockerfile form).

    ``--extra \\`` / next-line ``vlm`` is how builder-vlm invokes uv sync.
    Comment prose mentioning the extra must not trip the gate.
    """
    continued = (
        "RUN uv sync --locked --no-dev --extra \\\n"
        "    vlm --no-install-project\n"
    )
    assert has_vlm_extra(continued), "continued --extra vlm must resolve"

    prose = (
        "FROM python:3.12-slim AS builder\n"
        "# do not use --extra vlm here; torch is builder-vlm only\n"
        "RUN uv sync --locked --no-dev --extra bench\n"
    )
    assert not has_vlm_extra(prose), "comment mentioning --extra vlm must not trip"

    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS builder\n"
        "RUN uv sync --locked --extra \\\n"
        "    vlm\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "COPY --from=builder /opt/venv /opt/venv\n",
    )
    assert has_vlm_extra(_dockerfile_stages(path)["builder"])
    assert stage_resolves_vlm_extra(path, DEFAULT_STAGE)


def test_d5_comment_line_ending_backslash_does_not_absorb_copy(tmp_path: Path) -> None:
    """W5C: a ``# … \\`` line must not continue into the next COPY --from."""
    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS builder-vlm\n"
        "RUN uv sync --locked --extra vlm\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "# note about multi-line installs \\\n"
        "COPY --from=builder-vlm /opt/venv /opt/venv\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
    )
    body = _dockerfile_stages(path)[DEFAULT_STAGE]
    assert copy_from_dep_stages(body) == ["builder-vlm"], (
        f"comment-ending-\\\\ must not absorb COPY; joined={join_continued_lines(body)!r}"
    )
    assert stage_resolves_vlm_extra(path, DEFAULT_STAGE)


def test_d5_from_arg_expansion_walks_provenance(tmp_path: Path) -> None:
    """W5C: ARG BASE=builder-vlm + FROM ${BASE} AS runtime must see vlm provenance."""
    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS builder-vlm\n"
        "RUN uv sync --locked --extra vlm\n"
        "\n"
        "ARG BASE=builder-vlm\n"
        "FROM ${BASE} AS runtime\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
    )
    from recognition.tests.dockerfile_stages import dockerfile_stage_bases

    bases = dockerfile_stage_bases(path)
    assert bases["runtime"] == "builder-vlm", bases
    assert stage_resolves_vlm_extra(path, DEFAULT_STAGE)


def test_d5_empty_dockerfile_raises_not_none(tmp_path: Path) -> None:
    """W5C: no stages raises; anonymous last returns None — disambiguated.

    Callers that only assert ``is not None`` would stay green on an empty
    file if both cases returned None.
    """
    empty = _write(tmp_path / "empty", "# no from lines\n")
    with pytest.raises(DockerfileParseError, match="no FROM stages"):
        default_build_target(empty)

    anon = _write(tmp_path / "anon", "FROM python:3.12-slim\nRUN true\n")
    assert default_build_target(anon) is None


def test_d5_from_as_case_and_quoted_hash_strip() -> None:
    """A-08: Docker accepts as/As/AS; quote-aware # strip must keep quoted hashes."""
    for spelling in ("as", "As", "AS"):
        ref, name = parse_from_instruction(
            f"FROM python:3.12-slim {spelling} builder"
        )
        assert (ref, name) == ("python:3.12-slim", "builder"), spelling

    # Quoted '#' in the image ref must survive; trailing unquoted comment must not.
    # Naive line.split("#") would truncate the ref before AS and raise.
    ref, name = parse_from_instruction('FROM "registry.example/app#canary" AS runtime')
    assert name == "runtime"
    assert "app#canary" in ref
    ref, name = parse_from_instruction(
        "FROM python:3.12-slim AS builder # ship torch-free"
    )
    assert (ref, name) == ("python:3.12-slim", "builder")


def test_d5_heredoc_instruction_restriction_ignores_env_label(tmp_path: Path) -> None:
    """W8-VER-02: ENV/LABEL/ARG lines with << must not open a heredoc.

    Use ``ENV MSG=<<EOF`` (non-word char before ``<<``) so the lookbehind half
    of ``_HEREDOC_OPEN_RE`` still matches — only the instruction-prefix half
    rejects the line. Widening ``(?:RUN|COPY|ADD)`` to ``.*?`` then swallows
    the following COPY --from (wave-8 compound-gate rule).
    """
    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS builder-vlm\n"
        "RUN uv sync --locked --extra vlm\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "ENV MSG=<<EOF\n"
        "LABEL note=<<EOF\n"
        "ARG FLAG=<<EOF\n"
        "COPY --from=builder-vlm /opt/venv /opt/venv\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
    )
    body = _dockerfile_stages(path)[DEFAULT_STAGE]
    joined = join_continued_lines(body)
    assert copy_from_dep_stages(body) == ["builder-vlm"], (
        f"ENV/LABEL/ARG << must not open heredoc; joined={joined!r}"
    )
    # ENV line must remain its own logical instruction (not a heredoc opener).
    assert any(ln.strip().startswith("ENV MSG=") for ln in joined), joined
    assert stage_resolves_vlm_extra(path, DEFAULT_STAGE)


def test_d5_heredoc_from_line_is_not_stage_boundary(tmp_path: Path) -> None:
    """G-10: FROM inside RUN <<EOF must not truncate the stage or raise."""
    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS runtime\n"
        "RUN <<EOF\n"
        "echo FROM nowhere\n"
        "FROM nowhere\n"
        "EOF\n"
        "USER root\n",
    )
    stages = _dockerfile_stages(path)
    body = stages[DEFAULT_STAGE]
    assert "USER root" in body, f"trailing USER vanished from stage: {body!r}"
    assert "FROM nowhere" in body
    assert list(stages) == [DEFAULT_STAGE]


def test_d5_duplicate_stage_name_raises(tmp_path: Path) -> None:
    """A-09: BuildKit rejects duplicate stage names; parser must too."""
    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS runtime\n"
        "ENV A=1\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "ENV B=1\n",
    )
    with pytest.raises(DockerfileParseError, match="duplicate stage name"):
        _dockerfile_stages(path)


def test_d5_pip_var_assign_and_sh_lc_wrappers() -> None:
    """G-08: bare VAR=VALUE and sh -lc wrappers must trip unlocked installs."""
    var_wrapped = 'RUN PIP_NO_INPUT=1 pip install ".[bench]"'
    assert unlocked_project_extra_installs(var_wrapped), var_wrapped

    sh_lc = "RUN sh -lc 'pip install \".[bench]\"'"
    assert unlocked_project_extra_installs(sh_lc), sh_lc

    chained = 'RUN cd /app && FOO=1 pip install ".[bench]"'
    assert unlocked_project_extra_installs(chained), chained

    # Control: --no-deps still exempts.
    assert not unlocked_project_extra_installs(
        'RUN PIP_NO_INPUT=1 pip install --no-deps ".[bench]"'
    )


_TORCH_CONTAMINANT_RE = re.compile(
    r"(?:^|&&|;|\|)\s*(?:RUN\s+)?"
    r"(?:(?:env(?:\s+[A-Za-z_][\w]*=\S+)+\s+)|(?:[A-Za-z_][\w]*=\S+\s+)*)?"
    r"(?:"
    r"(?:(?:/[\w./-]+/)?(?:python3?|[\w.-]*python3?)\s+-m\s+)?"
    r"(?:uv\s+pip\s+install|pip(?:3)?\s+install|uv\s+add)"
    r"|"
    r"(?:/[\w./-]+/)?pip(?:3)?\s+install"  # /opt/venv/bin/pip install …
    r")\b"
    r"[^\n]*\b(?:torch|transformers|nvidia-[\w-]+|triton)\b",
    re.IGNORECASE,
)


def _stage_installs_torch_stack(stage_text: str) -> list[str]:
    """Install fragments that name torch/transformers/nvidia-/triton (G-09)."""
    hits: list[str] = []
    for ln in join_continued_lines(stage_text):
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        active = re.sub(r"\s+#.*$", "", stripped)  # crude trailing comment drop
        if _TORCH_CONTAMINANT_RE.search(active):
            hits.append(stripped)
    return hits


def test_default_image_path_does_not_install_torch_stack() -> None:
    """G-09: torch-free default path — not only 'no vlm extra' spelling."""
    stages = _dockerfile_stages()
    for name in ("builder", "runtime-base", DEFAULT_STAGE):
        if name not in stages:
            continue
        body = effective_stage_body(DOCKERFILE, name) if name != "builder" else stages[name]
        hits = _stage_installs_torch_stack(body)
        assert not hits, (
            f"{name} must not pip/uv-install torch/transformers/nvidia-/triton; got {hits}"
        )


def test_guard_bites_when_runtime_pip_installs_torch(tmp_path: Path) -> None:
    """TEST-15: direct torch install on default path is detectable (G-09)."""
    path = _write(
        tmp_path,
        "FROM python:3.12-slim AS builder\n"
        "RUN uv sync --locked --no-dev --extra bench --no-install-project\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "RUN /opt/venv/bin/pip install --no-cache-dir torch\n",
    )
    body = effective_stage_body(path, DEFAULT_STAGE)
    assert _stage_installs_torch_stack(body), "torch pip install must be detected"
    # Control: torch-free path stays clean.
    clean = _write(
        tmp_path / "clean",
        "FROM python:3.12-slim AS runtime\n"
        "RUN /opt/venv/bin/pip install --no-cache-dir pillow\n",
    )
    assert not _stage_installs_torch_stack(effective_stage_body(clean, DEFAULT_STAGE))
