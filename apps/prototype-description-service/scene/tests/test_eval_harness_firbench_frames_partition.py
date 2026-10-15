"""Fake-only regressions for canonical PSU validation at the non-mated pool boundary."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from fractions import Fraction

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as ff


def _image(image_id: str, **metadata: str) -> ff.ImageUnit:
    return ff.ImageUnit(
        image_id=image_id,
        sha256=hashlib.sha256(image_id.encode()).hexdigest(),
        sampling_arm=fc.SamplingArm.challenge,
        inclusion_probability=None,
        **metadata,
    )


def _face(image_id: str, identity_id: str | None = None) -> ff.GtFace:
    return ff.GtFace(
        face_id=f"face:{image_id}",
        image_id=image_id,
        box=(0.0, 0.0, 10.0, 10.0),
        identity_status=fc.IdentityStatus.unknown if identity_id is None else fc.IdentityStatus.named,
        identity_id=identity_id,
    )


def _linked_pair(edge: str) -> tuple[list[ff.ImageUnit], list[ff.GtFace]]:
    images = [_image("image-a"), _image("image-b")]
    faces = [_face(image.image_id) for image in images]
    if edge == "duplicate":
        images = [replace(image, sha256=images[0].sha256, duplicate_group="duplicate-pair") for image in images]
    elif edge == "session":
        images = [replace(image, session_id="session-pair") for image in images]
    elif edge == "synthetic-parent":
        images[1] = replace(images[1], synthetic_parent_id="image-a")
    elif edge == "named-identity":
        faces = [_face(image.image_id, "identity-pair") for image in images]
    else:
        raise AssertionError(f"unexpected fixture edge {edge}")
    return images, faces


@pytest.mark.parametrize("edge", ["duplicate", "session", "synthetic-parent", "named-identity"])
@pytest.mark.parametrize("second_fold", [0, 1], ids=["inflated-effective-n", "cross-fold-leak"])
def test_pool_refuses_split_required_edge_with_exact_key_coverage(edge: str, second_fold: int) -> None:
    images, faces = _linked_pair(edge)
    # Both maps cover exactly the expected keys, but the partition breaks a required edge.
    with pytest.raises(fc.FrameContractError):
        ff.build_nonmated_pool(
            faces,
            images,
            {"image-a": 0, "image-b": second_fold},
            fold=0,
            component_map={"image-a": "image-a", "image-b": "image-b"},
            exhaustive=True,
            planning_icc=0.10,
        )


@pytest.mark.parametrize("psu_id", ["image-b", "arbitrary-psu"])
def test_pool_refuses_noncanonical_component_id(psu_id: str) -> None:
    images, faces = _linked_pair("duplicate")
    with pytest.raises(fc.FrameContractError):
        ff.build_nonmated_pool(
            faces,
            images,
            {psu_id: 0},
            fold=0,
            component_map={"image-a": psu_id, "image-b": psu_id},
            exhaustive=True,
            planning_icc=0.10,
        )


def test_pool_refuses_merging_independent_unknown_images() -> None:
    images = [_image("image-a"), _image("image-b")]
    faces = [_face(image.image_id) for image in images]
    with pytest.raises(fc.FrameContractError):
        ff.build_nonmated_pool(
            faces,
            images,
            {"image-a": 0},
            fold=0,
            component_map={"image-a": "image-a", "image-b": "image-a"},
            exhaustive=True,
            planning_icc=0.10,
        )


def test_pool_refuses_split_transitive_component_even_for_an_empty_requested_fold() -> None:
    images = [
        _image("image-a", duplicate_group="duplicate-pair"),
        _image("image-b", duplicate_group="duplicate-pair", session_id="session-pair"),
        _image("image-c", session_id="session-pair"),
        _image("image-d", synthetic_parent_id="image-c"),
        _image("image-e"),
    ]
    faces = [
        _face(image.image_id, "identity-pair" if image.image_id in {"image-d", "image-e"} else None) for image in images
    ]
    with pytest.raises(fc.FrameContractError):
        ff.build_nonmated_pool(
            faces,
            images,
            {"image-a": 0, "image-c": 1},
            fold=2,
            component_map={
                "image-a": "image-a",
                "image-b": "image-a",
                "image-c": "image-c",
                "image-d": "image-c",
                "image-e": "image-c",
            },
            exhaustive=True,
            planning_icc=0.10,
        )


@pytest.mark.parametrize("edge", ["duplicate", "session", "synthetic-parent", "named-identity"])
@pytest.mark.parametrize("reverse", [False, True], ids=["forward", "reversed"])
def test_valid_canonical_partition_preserves_units_counts_and_fold_assignments(edge: str, reverse: bool) -> None:
    images, faces = _linked_pair(edge)
    images.append(_image("image-c"))
    faces.append(_face("image-c"))
    if reverse:
        images.reverse()
        faces.reverse()
    components = ff.build_psu_components(images, faces)
    assert components == {"image-a": "image-a", "image-b": "image-a", "image-c": "image-c"}
    folds = {"image-a": 0, "image-c": 1}
    # Every source face and background appears once across the rotation; detectors supply no units.
    expected = {
        0: [
            ("background:image-a", "image-a"),
            ("background:image-b", "image-a"),
            ("face:image-a", "image-a"),
            ("face:image-b", "image-a"),
        ],
        1: [("background:image-c", "image-c"), ("face:image-c", "image-c")],
    }
    for fold, entries in expected.items():
        pool = ff.build_nonmated_pool(
            faces, images, folds, fold=fold, component_map=components, exhaustive=True, planning_icc=0.10
        )
        assert [(unit.unit_id, unit.psu_id) for unit in pool.units] == entries
        assert all(unit.fold == pool.fold == fold for unit in pool.units)
        n = len(entries)
        deff = 1 + Fraction(n - 1, 10)
        assert pool.n_units == n
        assert pool.design_effect == pytest.approx(float(deff), rel=0, abs=1e-12)
        assert pool.n_nonmated_eff == pytest.approx(float(n / deff), rel=0, abs=1e-12)


@pytest.mark.parametrize("exhaustive", [False, None])
def test_canonical_partition_still_requires_exhaustive_gt(exhaustive: bool | None) -> None:
    images, faces = _linked_pair("duplicate")
    with pytest.raises(fc.FrameContractError, match="exhaustive"):
        ff.build_nonmated_pool(
            faces,
            images,
            {"image-a": 0},
            fold=0,
            component_map={"image-a": "image-a", "image-b": "image-a"},
            exhaustive=exhaustive,
            planning_icc=0.10,
        )


def test_canonical_partition_still_refuses_unresolved_face_outside_requested_fold() -> None:
    images = [_image("image-a"), _image("image-b")]
    faces = [_face("image-a"), replace(_face("image-b"), identity_status=fc.IdentityStatus.unresolved)]
    with pytest.raises(fc.FrameContractError, match="unresolved"):
        ff.build_nonmated_pool(
            faces,
            images,
            {"image-a": 0, "image-b": 1},
            fold=0,
            component_map={"image-a": "image-a", "image-b": "image-b"},
            exhaustive=True,
            planning_icc=0.10,
        )
