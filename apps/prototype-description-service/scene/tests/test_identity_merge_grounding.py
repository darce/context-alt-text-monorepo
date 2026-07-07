"""Slice 4: Florence `<CAPTION_TO_PHRASE_GROUNDING>` — parse, normalize, expose.

No model load: `_parse_phrase_grounding` is pure, and the describe-path test
monkeypatches `ensure_loaded`/`_run_task` so torch/transformers never import.
"""

from scene.application.description_adapter import AdapterResult
from scene.application.identity_merge import (
    ConfirmedFace,
    NormalizedBox,
    merge_identities,
    normalize_bbox,
)
from scene.infrastructure.vlm.florence_local_adapter import (
    _CAPTION_TASK,
    _OD_TASK,
    _PHRASE_GROUNDING_TASK,
    LocalCpuDescriptionAdapter,
)


def test_adapter_result_phrase_boxes_default_empty():
    result = AdapterResult(
        caption="c",
        objects=(),
        ocr_text=None,
        alt_text_draft="c",
        context_sources=(),
        context_applied=False,
    )
    assert result.phrase_boxes == ()


def test_grounding_task_in_defaults_and_prompt_version():
    adapter = LocalCpuDescriptionAdapter()
    assert _PHRASE_GROUNDING_TASK in adapter._tasks
    assert "caption_to_phrase_grounding" in adapter.prompt_or_task_version


class TestParsePhraseGrounding:
    def test_normalizes_to_unit_frame_and_finds_spans(self):
        caption = "A man stands by a window."
        parsed = {"bboxes": [[10.0, 10.0, 60.0, 90.0]], "labels": ["A man"]}
        boxes = LocalCpuDescriptionAdapter._parse_phrase_grounding(
            parsed, caption=caption, image_width=100, image_height=100
        )
        assert len(boxes) == 1
        pb = boxes[0]
        assert pb.phrase == "A man"
        assert (pb.span_start, pb.span_end) == (0, 5)
        assert pb.box == NormalizedBox(x=0.1, y=0.1, width=0.5, height=0.8)

    def test_case_insensitive_span_match_keeps_caption_casing(self):
        caption = "A man stands by a window."
        parsed = {"bboxes": [[0.0, 0.0, 50.0, 50.0]], "labels": ["a man"]}
        boxes = LocalCpuDescriptionAdapter._parse_phrase_grounding(
            parsed, caption=caption, image_width=100, image_height=100
        )
        assert boxes[0].phrase == "A man"  # caption substring, so span replacement verifies

    def test_label_missing_from_caption_gets_empty_span(self):
        caption = "A man stands."
        parsed = {"bboxes": [[0.0, 0.0, 10.0, 10.0]], "labels": ["a hallucinated phrase"]}
        boxes = LocalCpuDescriptionAdapter._parse_phrase_grounding(
            parsed, caption=caption, image_width=100, image_height=100
        )
        assert (boxes[0].span_start, boxes[0].span_end) == (-1, -1)

    def test_repeated_label_advances_span_search(self):
        caption = "A man opens the door. A man waves."
        parsed = {
            "bboxes": [[0.0, 0.0, 10.0, 10.0], [20.0, 0.0, 30.0, 10.0]],
            "labels": ["A man", "A man"],
        }
        boxes = LocalCpuDescriptionAdapter._parse_phrase_grounding(
            parsed, caption=caption, image_width=100, image_height=100
        )
        assert (boxes[0].span_start, boxes[0].span_end) == (0, 5)
        assert (boxes[1].span_start, boxes[1].span_end) == (22, 27)


def test_describe_exposes_phrase_boxes_without_changing_caption_or_od(monkeypatch):
    adapter = LocalCpuDescriptionAdapter()
    monkeypatch.setattr(adapter, "ensure_loaded", lambda: None)

    def fake_run_task(image, task, *, text_input=None):
        if task == _CAPTION_TASK:
            return {task: "A man stands by a window."}
        if task == _OD_TASK:
            return {task: {"labels": ["person", "window"], "bboxes": []}}
        if task == _PHRASE_GROUNDING_TASK:
            assert text_input == "A man stands by a window."
            return {task: {"bboxes": [[10.0, 10.0, 60.0, 90.0]], "labels": ["A man"]}}
        raise AssertionError(f"unexpected task {task}")

    monkeypatch.setattr(adapter, "_run_task", fake_run_task)
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (100, 100)).save(buf, format="PNG")
    result = adapter.describe(image_bytes=buf.getvalue(), context=None)
    assert result.caption == "A man stands by a window."
    assert result.objects == ("person", "window")
    assert len(result.phrase_boxes) == 1
    assert result.phrase_boxes[0].phrase == "A man"
    assert result.phrase_boxes[0].box.x == 0.1


def test_coordinate_fidelity_full_res_face_matches_downsampled_phrase_box():
    # Recognition detects on the full-res image (4000x2000); grounding boxes
    # come from the downsampled frame (1000x500). Same normalized [0,1] frame →
    # containment must still hold end to end through merge_identities.
    face = ConfirmedFace(
        identity_id="i",
        cluster_id="c",
        roster_id="r",
        label="Daniel",
        detection_confidence=0.95,
        box=normalize_bbox(x=1600, y=400, width=200, height=320, image_width=4000, image_height=2000),
    )
    caption = "A man stands by a window."
    parsed = {"bboxes": [[350.0, 50.0, 550.0, 450.0]], "labels": ["A man"]}
    phrase_boxes = LocalCpuDescriptionAdapter._parse_phrase_grounding(
        parsed, caption=caption, image_width=1000, image_height=500
    )
    result = merge_identities(caption=caption, phrase_boxes=list(phrase_boxes), confirmed_faces=[face])
    assert result.named_draft == "Daniel stands by a window."
