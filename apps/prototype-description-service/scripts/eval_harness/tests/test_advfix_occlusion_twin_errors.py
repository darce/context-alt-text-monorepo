"""Regression coverage for malformed occlusion twin-pass error attestations."""

from __future__ import annotations

import pytest

from scripts.eval_harness.report import score_face_run_record


def _face_run_record(*, attestation: dict | None = None, include_attestation: bool = True) -> dict:
    provenance = {"manifest_sha256": "m" * 64, "head_sha": "0" * 40, "leg": "candidate"}
    if include_attestation:
        provenance["occlusion_twin_pass"] = attestation if attestation is not None else {}
    return {
        "schema": "acx-eval/v1",
        "kind": "face_run_record",
        "provenance": provenance,
        "items": [
            {
                "media_id": 1,
                "path": "x.jpg",
                "model_id": "m",
                "embedding_dim": 4,
                "image_size": [10, 10],
                "faces": [],
            }
        ],
    }


def _zero_box_manifest() -> dict:
    return {
        "annotation_mode": "exhaustive",
        "roster": [],
        "roster_cohorts": {},
        "entries": [
            {
                "path": "x.jpg",
                "media_id": 1,
                "face_count": 0,
                "present_identities": [],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [],
                "annotation_mode": "exhaustive",
            }
        ],
    }


@pytest.mark.parametrize(
    "errors",
    [
        pytest.param(None, id="none"),
        pytest.param(False, id="false"),
        pytest.param(0, id="zero"),
        pytest.param("", id="empty-string"),
        pytest.param({}, id="empty-dict"),
        pytest.param((), id="tuple"),
        pytest.param("decoder failed", id="non-empty-string"),
        pytest.param(3, id="number"),
    ],
)
def test_malformed_twin_errors_are_incomplete_and_block_admission(errors: object) -> None:
    face_run = _face_run_record(attestation={"errors": errors})

    scored = score_face_run_record(face_run, _zero_box_manifest())

    assert scored["provenance"]["occlusion_twin_pass_status"] == "incomplete"
    assert scored["gate_proposal"]["evidence_admission"]["occlusion_twin_pass"] == {
        "status": "incomplete",
        "n_errors": 1,
        "admission": "blocked",
    }
    for occlusion in scored["slices"]["occlusion"].values():
        assert occlusion["synthetic"]["directional"] is True
        assert "occlusion_twin_pass_status=incomplete" in occlusion["synthetic"]["reasons"]


def test_empty_twin_errors_list_still_certifies_complete_pass() -> None:
    scored = score_face_run_record(
        _face_run_record(attestation={"errors": []}),
        _zero_box_manifest(),
    )

    assert scored["provenance"]["occlusion_twin_pass_status"] == "complete"
    assert scored["gate_proposal"]["evidence_admission"]["occlusion_twin_pass"] == {
        "status": "complete",
        "n_errors": 0,
        "admission": "eligible",
    }


def test_missing_twin_errors_key_stays_incomplete() -> None:
    scored = score_face_run_record(
        _face_run_record(attestation={"n_pairs": 0}),
        _zero_box_manifest(),
    )

    assert scored["provenance"]["occlusion_twin_pass_status"] == "incomplete"
    assert scored["gate_proposal"]["evidence_admission"]["occlusion_twin_pass"]["admission"] == "blocked"


def test_missing_twin_attestation_stays_unattested() -> None:
    scored = score_face_run_record(
        _face_run_record(include_attestation=False),
        _zero_box_manifest(),
    )

    assert scored["provenance"]["occlusion_twin_pass_status"] == "unattested"
    assert scored["gate_proposal"]["evidence_admission"]["occlusion_twin_pass"]["admission"] == "blocked"
