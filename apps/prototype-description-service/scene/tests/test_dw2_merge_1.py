import pytest

from scene.application.identity_merge.merge import NormalizedBox
from scene.application.visual_facts_service import _phrase_boxes_from_json


@pytest.mark.parametrize(
    "coordinates",
    [
        (float("nan"), 0.1, 0.2, 0.2),
        (0.1, float("inf"), 0.2, 0.2),
        (0.1, 0.1, 0.0, 0.2),
        (0.1, 0.1, 0.2, -0.2),
        (-0.1, 0.1, 0.2, 0.2),
        (0.1, 0.1, 0.2, 1.0),
    ],
)
def test_normalized_box_rejects_invalid_geometry(coordinates):
    with pytest.raises(ValueError):
        NormalizedBox(x=coordinates[0], y=coordinates[1], width=coordinates[2], height=coordinates[3])


def test_phrase_boxes_from_json_drops_invalid_boxes_and_reversed_spans():
    payload = [
        {"phrase": "valid", "span": [0, 5], "box": [0.1, 0.2, 0.3, 0.4]},
        {"phrase": "non-finite", "span": [6, 16], "box": [0.1, 0.2, float("nan"), 0.4]},
        {"phrase": "zero-size", "span": [17, 26], "box": [0.1, 0.2, 0.0, 0.4]},
        {"phrase": "outside", "span": [27, 34], "box": [0.8, 0.2, 0.3, 0.4]},
        {"phrase": "reversed", "span": [40, 35], "box": [0.1, 0.2, 0.3, 0.4]},
    ]

    boxes = _phrase_boxes_from_json(payload)

    assert [(box.phrase, box.span_start, box.span_end) for box in boxes] == [("valid", 0, 5)]
