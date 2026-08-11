"""ORCH-LAUNCH-01 C-02 / A-05: VLM image coordinates stay on a distinct repo.

RA-07 fixed the deploy script so ``ACX_BUILD_TARGET=runtime-vlm`` resolves to
``${IMAGE_NAME}-vlm`` (default ``acx-backend-vlm``), never a ``:vlm`` tag on
the recognition repository. Operator-facing docs (Dockerfile header + OCI
README) must instruct the same coordinates; otherwise an operator following
either doc pushes a torch-bearing image into the repo whose ``:dev`` /
``:staging`` / ``:latest`` tags the promote path walks (tag-clobber).

Behavioural authority is the real ``resolve_image_repo_name`` function from
``scripts/deploy/recognition-service.sh`` (sourced, not re-implemented).
Docs are checked for (1) presence of that resolved short name and
(2) absence of the forbidden same-repo tag form ``acx-backend:vlm``.

Self-contained: does not import ``recognition.tests.dockerfile_stages``
(owned by a sibling lane).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(__file__).resolve().parents[5]
DOCKERFILE = SERVICE_ROOT / "Dockerfile"
OCI_README = REPO_ROOT / "infra" / "oci" / "README.md"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"

# Same-repo tag form that clobbers env tags under promote (RA-07 hazard).
# Must not appear in operator recipes (Dockerfile header, OCI runbook).
_FORBIDDEN_SAME_REPO_VLM_TAG = re.compile(r"\bacx-backend:vlm\b")


def _resolve_image_repo_name(*, build_target: str, image_name: str = "acx-backend") -> str:
    """Call the real shell helper; never re-implement its case arm in Python."""
    script = f"""
set -euo pipefail
source "{DEPLOY_SCRIPT}"
IMAGE_NAME={image_name!r}
ACX_BUILD_TARGET={build_target!r}
ACX_IMAGE_VARIANT=
resolve_image_repo_name
"""
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"resolve_image_repo_name failed (target={build_target!r}): "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    # Script may emit log lines; take the last non-empty line as the name.
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"resolve_image_repo_name produced no stdout for {build_target!r}"
    return lines[-1]


def _operator_doc_surfaces() -> dict[str, str]:
    return {
        "Dockerfile": DOCKERFILE.read_text(encoding="utf-8"),
        "infra/oci/README.md": OCI_README.read_text(encoding="utf-8"),
    }


def surface_forbids_same_repo_vlm_tag(text: str) -> bool:
    """True when the forbidden ``acx-backend:vlm`` tag form is absent."""
    return _FORBIDDEN_SAME_REPO_VLM_TAG.search(text) is None


def surface_mentions_resolved_vlm_repo(text: str, vlm_repo: str) -> bool:
    """True when the operator surface names the resolved VLM repository."""
    if not vlm_repo or ":" in vlm_repo:
        return False
    # Require the short name as a path segment / tag prefix, not a prose typo.
    return re.search(rf"(?:/|\b){re.escape(vlm_repo)}(?::|\b)", text) is not None


# ---- live tree -----------------------------------------------------------


def test_resolve_image_repo_name_vlm_is_distinct_repository() -> None:
    """Behavioural: runtime-vlm maps to IMAGE_NAME-vlm, not a tag on IMAGE_NAME."""
    recognition = _resolve_image_repo_name(build_target="")
    vlm = _resolve_image_repo_name(build_target="runtime-vlm")
    assert recognition == "acx-backend"
    assert vlm == "acx-backend-vlm"
    assert vlm != recognition
    assert not vlm.startswith(recognition + ":")


def test_operator_docs_use_resolved_vlm_repository() -> None:
    """Dockerfile header + OCI README must advertise the repo resolve returns."""
    vlm_repo = _resolve_image_repo_name(build_target="runtime-vlm")
    for name, text in _operator_doc_surfaces().items():
        assert surface_mentions_resolved_vlm_repo(text, vlm_repo), (
            f"{name} must document the VLM image under repository {vlm_repo!r} "
            f"(resolve_image_repo_name for ACX_BUILD_TARGET=runtime-vlm); "
            f"found no such coordinate"
        )


def test_operator_docs_forbid_same_repo_vlm_tag() -> None:
    """No shipped operator surface may teach acx-backend:vlm (tag-clobber)."""
    for name, text in _operator_doc_surfaces().items():
        assert surface_forbids_same_repo_vlm_tag(text), (
            f"{name} contains forbidden same-repo VLM tag form 'acx-backend:vlm'; "
            f"use repository acx-backend-vlm:<env-tag> instead (RA-07 / C-02 / A-05)"
        )


# ---- discriminators / TEST-15 --------------------------------------------


def test_discriminator_forbidden_tag_form_detected() -> None:
    bad = "docker build -t iad.ocir.io/idu2kqqe2jxy/acx-backend:vlm ."
    good = "docker build -t iad.ocir.io/idu2kqqe2jxy/acx-backend-vlm:latest ."
    assert not surface_forbids_same_repo_vlm_tag(bad)
    assert surface_forbids_same_repo_vlm_tag(good)
    # Distinct-repo form must not false-positive the forbidden check.
    assert "acx-backend-vlm" in good
    assert _FORBIDDEN_SAME_REPO_VLM_TAG.search(good) is None


def test_discriminator_missing_resolved_repo_fails() -> None:
    vlm = "acx-backend-vlm"
    assert surface_mentions_resolved_vlm_repo(
        "push to iad.ocir.io/ns/acx-backend-vlm:latest\n", vlm
    )
    assert not surface_mentions_resolved_vlm_repo(
        "push to iad.ocir.io/ns/acx-backend:vlm\n", vlm
    )
    assert not surface_mentions_resolved_vlm_repo(
        "no image coordinates here\n", vlm
    )


def test_discriminator_live_docs_would_fail_if_reverted_to_tag_form(
    tmp_path: Path,
) -> None:
    """Synthetic mutation: rewriting the VLM recipe to :vlm fails the guards."""
    vlm_repo = _resolve_image_repo_name(build_target="runtime-vlm")
    mutated = (
        "# Build VLM\n"
        "docker build --target runtime-vlm "
        f"-t iad.ocir.io/idu2kqqe2jxy/acx-backend:vlm .\n"
    )
    assert not surface_forbids_same_repo_vlm_tag(mutated)
    assert not surface_mentions_resolved_vlm_repo(mutated, vlm_repo)
    # Control: corrected form passes both.
    fixed = mutated.replace("acx-backend:vlm", f"{vlm_repo}:latest")
    assert surface_forbids_same_repo_vlm_tag(fixed)
    assert surface_mentions_resolved_vlm_repo(fixed, vlm_repo)
    # Write path proves we are not asserting only against in-memory constants.
    sample = tmp_path / "recipe.txt"
    sample.write_text(mutated, encoding="utf-8")
    assert not surface_forbids_same_repo_vlm_tag(sample.read_text(encoding="utf-8"))
