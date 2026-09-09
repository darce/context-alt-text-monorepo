"""PA-01 harness acceptance gate: merge output scored by the eval harness.

Runs `merge_identities` over the VLM-2C-seeded fixtures (`golden.json` v2 +
`phrase_boxes.json` scenes) and asserts the three acceptance gates from the
task plan:

(a) expected-identities match — the named draft carries exactly the golden
    `present_identities`, and containment resolves exactly the fixture's
    `expected_containment` identities;
(b) insertion precision — `identification_pr.wrong_names == []` and
    `precision == 1.0` (or None with no positives), including an adversarial
    confirmed stranger whose face center lies in no phrase box;
(c) Must-Right / policy gate — `must_right_pass` True and `policy_violation`
    False on every scored entry; no `gated_score` zeroed by a merge-injected
    name.
"""

from pathlib import Path

import pytest

from scene.application.identity_merge import (
    ConfirmedFace,
    NamingPolicy,
    NormalizedBox,
    PhraseBox,
    merge_identities,
)
from scripts.eval_harness.caption_metrics import score_caption
from scripts.eval_harness.face_metrics import ImageIdentities, identification_pr
from scripts.eval_harness.manifest import load_manifest
from scripts.eval_harness.phrase_boxes import load_phrase_boxes

SEED_DIR = Path(__file__).parent / "seed"
FACE_W, FACE_H = 0.06, 0.08  # synthetic face-box extent around each authored center


def _load_scenes():
    # S7-02: same v2 pin + schema as the live harness (not raw json.loads).
    # Metadata-only: present_identities/must_right/easy_wrong/policy/path/face_count/
    # base_caption for merge scoring — faces are synthetic, never open image files.
    golden = load_manifest(str(SEED_DIR / "golden.json"), skip_hash_verification=True)
    boxes = load_phrase_boxes(SEED_DIR / "phrase_boxes.json")
    by_media = {e.media_id: e.model_dump() for e in golden.entries}
    return [(scene, by_media[scene["media_id"]]) for scene in boxes["scenes"].values()]


def _face(label: str, center, *, roster: str) -> ConfirmedFace:
    cx, cy = center
    return ConfirmedFace(
        identity_id=f"identity-{label}-{cx}",
        cluster_id=f"cluster-{label}",
        roster_id=roster,
        label=label,
        detection_confidence=0.97,
        box=NormalizedBox(x=cx - FACE_W / 2, y=cy - FACE_H / 2, width=FACE_W, height=FACE_H),
    )


def _phrase_boxes(scene, caption):
    phrase_boxes = []
    for pb in scene["phrase_boxes"]:
        start = caption.find(pb["phrase"])
        assert start != -1, f"phrase {pb['phrase']!r} not in base_caption for media {scene['media_id']}"
        x, y, w, h = pb["box"]
        phrase_boxes.append(
            PhraseBox(
                phrase=pb["phrase"],
                span_start=start,
                span_end=start + len(pb["phrase"]),
                box=NormalizedBox(x=x, y=y, width=w, height=h),
            )
        )
    return phrase_boxes


POLICY = NamingPolicy(agreement_enabled=True, suppressed_roster_ids=frozenset())


def _merge_scene(scene, entry, *, confirm_strangers=False):
    """Fixture-conform run: only resolved identities exist as confirmed faces
    (strangers have no DB identity). With ``confirm_strangers`` the stranger
    is adversarially confirmed under an Easy-Wrong name — whatever the
    geometry (no box, or shared box → ambiguity), that name must never land.
    """
    caption = entry["base_caption"]
    faces = []
    for idx, containment in enumerate(scene["expected_containment"]):
        identity = containment["resolved_identity"]
        if identity is not None:
            faces.append(_face(identity, containment["face_center"], roster=f"roster-{identity}"))
        elif confirm_strangers:
            wrong = (entry["easy_wrong"] or ["Wrong Person"])[0]
            faces.append(_face(wrong, containment["face_center"], roster=f"roster-stranger-{idx}"))
    return merge_identities(
        caption=caption,
        phrase_boxes=_phrase_boxes(scene, caption),
        confirmed_faces=faces,
        policy=POLICY,
    )


@pytest.fixture(scope="module")
def gate_results():
    results = []
    for scene, entry in _load_scenes():
        result = _merge_scene(scene, entry)
        resolved = {a.face.label for a in result.associations}
        expected = {c["resolved_identity"] for c in scene["expected_containment"] if c["resolved_identity"]}
        score = score_caption(
            result.named_draft,
            present_identities=entry["present_identities"],
            must_right=entry["must_right"],
            easy_wrong=entry["easy_wrong"],
            recognition_enabled=entry["policy"]["recognition_enabled"],
        )
        item = ImageIdentities(
            image=entry["path"],
            predicted=sorted(resolved),
            labeled=entry["present_identities"],
            recognition_enabled=entry["policy"]["recognition_enabled"],
            stranger_faces=entry["face_count"] - len(entry["present_identities"]),
        )
        results.append((scene, entry, result, resolved, expected, score, item))
    assert results, "no phrase-box scenes resolved against golden.json"
    return results


def test_gate_a_expected_identities_match(gate_results):
    for scene, entry, _result, resolved, expected, score, _ in gate_results:
        assert resolved == expected, f"media {scene['media_id']}: containment resolved {resolved} != {expected}"
        assert set(score.inserted_identities) == set(entry["present_identities"])
        assert score.missing_identities == []


def test_gate_b_insertion_precision_never_a_guessed_name(gate_results):
    for scene, entry, result, *_ in gate_results:
        names_in_draft = {n.name for n in (result.provenance.injected_names or ())}
        for wrong in entry["easy_wrong"]:
            assert wrong not in names_in_draft, f"media {scene['media_id']}: guessed name {wrong!r}"
            if wrong not in entry["base_caption"]:
                assert wrong not in result.named_draft
    pr = identification_pr([item for *_, item in gate_results])
    assert pr.wrong_names == []
    assert pr.precision in (None, 1.0)


def test_gate_b_adversarial_confirmed_stranger_never_named(gate_results):
    # Even when a stranger face is (wrongly) confirmed under an Easy-Wrong
    # roster name, the merge must not insert it: outside every box → no
    # association; sharing a box with the real person → 1:1 ambiguity →
    # nobody named. Either way the Easy-Wrong name never appears.
    for scene, entry, *_ in gate_results:
        if all(c["resolved_identity"] is not None for c in scene["expected_containment"]):
            continue  # no stranger in this scene
        result = _merge_scene(scene, entry, confirm_strangers=True)
        wrong = (entry["easy_wrong"] or ["Wrong Person"])[0]
        names = {n.name for n in (result.provenance.injected_names or ())}
        assert wrong not in names, f"media {scene['media_id']}: adversarial stranger named"
        assert {a.face.label for a in result.associations if a.face.label == wrong} == set()
        if wrong not in entry["base_caption"]:
            assert wrong not in result.named_draft


def test_gate_c_must_right_and_policy(gate_results):
    for scene, _entry, _result, _resolved, _expected, score, _ in gate_results:
        assert score.must_right_pass is True, f"media {scene['media_id']}: must-right failed"
        assert score.policy_violation is False
        assert score.gated_score > 0, f"media {scene['media_id']}: gated_score zeroed"
