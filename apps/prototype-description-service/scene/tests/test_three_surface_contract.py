"""Strict three-surface writer output boundary (FORMAT-CONTRACT-R1).

Fixture provenance (saved data, copied verbatim; no live model call):
- validation-fixtures.json sha256 1b1ea38bfc68492b6d9c5039d9a13e6d9790577e06bf037e5d40ac6de06ec59d
- three-surfaces.schema.json (frozen design) sha256
  601fd9f8d0f7dd2d3c6aed0bb8c2b7a7a28c60f730ce3fa32d12804112393cc0
- qwen-errors-and-latency.json (real BF16 writer outputs, original-001/002) sha256
  f7f89bb61cfb3340e192f70d680f130a687c4a64757f398b6f725737328e0a4c

Format validity is a syntax/schema property only; it says nothing about whether a
description is factually correct. Transport completion (finish reason, truncation)
belongs to a separate helper and is not decided here.
"""

from __future__ import annotations

import json
from types import MappingProxyType

import pytest

from scripts.eval_harness.three_surface_contract import (
    THREE_SURFACE_KEYS,
    THREE_SURFACE_SCHEMA_ID,
    ThreeSurfaceErrorCode,
    ThreeSurfaceValidationError,
    load_three_surface_schema,
    serialize_three_surfaces,
    validate_three_surface_text,
)

SYNTAX = ThreeSurfaceErrorCode.JSON_SYNTAX_FAILED
SCHEMA = ThreeSurfaceErrorCode.SCHEMA_FAILED
CONTENT = ThreeSurfaceErrorCode.CONTENT_SHAPE_FAILED

FROZEN_DESIGN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:altcontext:schema:three-surfaces:v2-design",
    "title": "Three description surfaces",
    "type": "object",
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "alt": {"type": "string", "minLength": 1},
        "caption": {"type": "string", "minLength": 1},
    },
    "required": ["title", "alt", "caption"],
    "additionalProperties": False,
}

# Verbatim raw_writer strings from the completed BF16 pilot cells.
REAL_MISSING_COMMA_RAW = (
    "```json\n{\n"
    '  "title": "Climber crouching in ice cave"\n'
    '  "alt": "Climber crouches on wet rocks in a dark ice cave, wearing a white helmet, '
    'fur-lined jacket, and crampons while holding a camera.",\n'
    '  "caption": "A climber crouches on wet, dark rocks before a towering blue-green ice wall. '
    "She wears a white helmet with a headlamp, a dark winter jacket with a fur-lined hood, and "
    "boots fitted with orange crampons. A camera hangs at her side as she looks toward the viewer "
    'in the dim, cold light."\n'
    "}\n```"
)
REAL_TITLE_ONLY_RAW = '```json\n{\n  "title": "Woman taking a playful mirror selfie"\n}\n```'


def _unfence(raw: str) -> str:
    """Test-only: the body between the fences, to show the next failure the fence hid."""
    return raw.removeprefix("```json\n").removesuffix("\n```")


def _reject(raw: str) -> ThreeSurfaceValidationError:
    with pytest.raises(ThreeSurfaceValidationError) as info:
        validate_three_surface_text(raw)
    return info.value


# --- shared schema ----------------------------------------------------------------


def test_schema_keeps_frozen_design_semantics_with_explicit_v2_id() -> None:
    schema = load_three_surface_schema()

    assert FROZEN_DESIGN_SCHEMA["$id"] == "urn:altcontext:schema:three-surfaces:v2-design"
    assert schema["$id"] == THREE_SURFACE_SCHEMA_ID == "urn:altcontext:schema:three-surfaces:v2"
    assert {**schema, "$id": FROZEN_DESIGN_SCHEMA["$id"]} == FROZEN_DESIGN_SCHEMA
    assert tuple(schema["required"]) == tuple(schema["properties"]) == THREE_SURFACE_KEYS == ("title", "alt", "caption")


def test_schema_loader_mutation_does_not_contaminate_later_calls() -> None:
    first = load_three_surface_schema()
    first["$id"] = "tampered"
    first["required"].append("identity")
    first["properties"]["title"]["minLength"] = 0
    first["properties"]["identity"] = {"type": "string"}
    first["additionalProperties"] = True

    second = load_three_surface_schema()

    assert second == {**FROZEN_DESIGN_SCHEMA, "$id": THREE_SURFACE_SCHEMA_ID}
    assert second["required"] is not first["required"]
    assert second["properties"]["title"] is not first["properties"]["title"]
    assert _reject('{"title":"A","alt":"B","caption":"C","identity":"guessed"}').code is SCHEMA


def test_error_codes_are_stable_strings() -> None:
    assert {code.value for code in ThreeSurfaceErrorCode} == {
        "json_syntax_failed",
        "schema_failed",
        "content_shape_failed",
    }
    error = _reject('{"title":"A","alt":"B"}')
    assert isinstance(error.code, ThreeSurfaceErrorCode)
    assert error.code == "schema_failed"


# --- real BF16 writer failures ----------------------------------------------------


def test_real_missing_comma_output_rejects_as_syntax() -> None:
    assert _reject(REAL_MISSING_COMMA_RAW).code is SYNTAX
    # Without the fence, the missing comma after "title" is still a syntax failure.
    assert _reject(_unfence(REAL_MISSING_COMMA_RAW)).code is SYNTAX


def test_real_title_only_output_rejects_and_is_not_completed() -> None:
    assert _reject(REAL_TITLE_ONLY_RAW).code is SYNTAX
    # Without the fence it is well-formed JSON that omits grounded content: a schema
    # failure naming the missing surfaces, never a filled-in object.
    error = _reject(_unfence(REAL_TITLE_ONLY_RAW))
    assert error.code is SCHEMA
    assert error.fields == ("alt", "caption")


# --- negative fixtures ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "code", "fields"),
    [
        # validation-fixtures.json, verbatim
        pytest.param(
            '{"title":"Climber" "alt":"A person on rocks.","caption":"A person crouches on rocks."}',
            SYNTAX,
            (),
            id="fixture-missing_comma",
        ),
        pytest.param('{"title":"A mirror selfie"}', SCHEMA, ("alt", "caption"), id="fixture-title_only"),
        pytest.param(
            '{"title":"Title","alt":"   ","caption":"Visible scene."}', CONTENT, ("alt",), id="fixture-blank_alt"
        ),
        pytest.param(
            '{"title":"Title","alt":"Visible scene.","caption":null}', SCHEMA, ("caption",), id="fixture-null_caption"
        ),
        pytest.param(
            '{"title":"Title","alt":"Scene.","caption":"Scene.","identity":"guessed"}',
            SCHEMA,
            ("identity",),
            id="fixture-extra_key",
        ),
        pytest.param(
            '{"title":"A","title":"B","alt":"Scene.","caption":"Scene."}', SYNTAX, (), id="fixture-duplicate_key"
        ),
        pytest.param('["Title","Alt","Caption"]', SCHEMA, (), id="fixture-non_object"),
        pytest.param('{"title":"A","alt":"B","caption":NaN}', SYNTAX, (), id="fixture-non_finite_number"),
        # duplicates and non-finite values anywhere in the document
        pytest.param('{"title":"A","alt":"B","caption":"C","x":{"k":1,"k":2}}', SYNTAX, (), id="nested-duplicate"),
        pytest.param('{"title":"A","alt":"B","caption":Infinity}', SYNTAX, (), id="infinity"),
        pytest.param('{"title":"A","alt":"B","caption":-Infinity}', SYNTAX, (), id="negative-infinity"),
        pytest.param('{"title":"A","alt":"B","caption":"C","x":1e999}', SYNTAX, (), id="overflow-to-infinity"),
        # Past the interpreter's int-digit limit, which json reports as a bare ValueError.
        pytest.param(
            '{"title":"A","alt":"B","caption":"C","x":' + "1" * 5_000 + "}", SYNTAX, (), id="oversized-integer"
        ),
        # wrappers, trailing text and non-JSON
        pytest.param('```json\n{"title":"A","alt":"B","caption":"C"}\n```', SYNTAX, (), id="markdown-fence"),
        pytest.param('```\n{"title":"A","alt":"B","caption":"C"}\n```', SYNTAX, (), id="bare-fence"),
        pytest.param('{"title":"A","alt":"B","caption":"C"}\nDone.', SYNTAX, (), id="trailing-text"),
        pytest.param('{"title":"A","alt":"B","caption":"C"}{}', SYNTAX, (), id="trailing-object"),
        pytest.param('Here it is: {"title":"A","alt":"B","caption":"C"}', SYNTAX, (), id="leading-prose"),
        pytest.param('\ufeff{"title":"A","alt":"B","caption":"C"}', SYNTAX, (), id="byte-order-mark"),
        pytest.param('{"title":"A","alt":"B","caption":"C",}', SYNTAX, (), id="trailing-comma"),
        pytest.param("{'title':'A','alt':'B','caption':'C'}", SYNTAX, (), id="single-quotes"),
        pytest.param('{"title":"A\nB","alt":"B","caption":"C"}', SYNTAX, (), id="raw-control-char"),
        pytest.param("", SYNTAX, (), id="empty-text"),
        pytest.param(" \n", SYNTAX, (), id="whitespace-text"),
        pytest.param("[" * 100_000 + "]" * 100_000, SYNTAX, (), id="deep-nesting"),
        # root must be an object
        pytest.param('"Title"', SCHEMA, (), id="root-string"),
        pytest.param("1", SCHEMA, (), id="root-number"),
        pytest.param("null", SCHEMA, (), id="root-null"),
        pytest.param("true", SCHEMA, (), id="root-bool"),
        # exactly title/alt/caption, each a string of length >= 1
        pytest.param("{}", SCHEMA, ("title", "alt", "caption"), id="empty-object"),
        pytest.param('{"title":"A","caption":"C"}', SCHEMA, ("alt",), id="missing-alt"),
        pytest.param('{"title":"A","alt":"B","caption":"C","Title":"D"}', SCHEMA, ("Title",), id="extra-case-variant"),
        pytest.param('{"title":1,"alt":"B","caption":"C"}', SCHEMA, ("title",), id="number-value"),
        pytest.param('{"title":"A","alt":true,"caption":"C"}', SCHEMA, ("alt",), id="bool-value"),
        pytest.param('{"title":"A","alt":"B","caption":["C"]}', SCHEMA, ("caption",), id="array-value"),
        pytest.param('{"title":{"text":"A"},"alt":"B","caption":"C"}', SCHEMA, ("title",), id="object-value"),
        pytest.param('{"title":"","alt":"B","caption":"C"}', SCHEMA, ("title",), id="empty-string"),
        pytest.param('{"title":null,"alt":null,"caption":"C"}', SCHEMA, ("title", "alt"), id="two-nulls"),
        # schema-valid but blank or not encodable as UTF-8
        pytest.param('{"title":"A","alt":"B","caption":"\\n\\t "}', CONTENT, ("caption",), id="escaped-whitespace"),
        pytest.param('{"title":"\\u00a0","alt":"B","caption":"C"}', CONTENT, ("title",), id="nbsp-only"),
        pytest.param('{"title":"A","alt":"\\u3000","caption":"C"}', CONTENT, ("alt",), id="ideographic-space-only"),
        pytest.param(
            '{"title":"A","alt":"B","caption":"bad \\ud800 half"}', CONTENT, ("caption",), id="lone-surrogate"
        ),
    ],
)
def test_strict_validation_rejects_with_typed_code(
    raw: str, code: ThreeSurfaceErrorCode, fields: tuple[str, ...]
) -> None:
    error = _reject(raw)
    assert error.code is code
    assert error.fields == fields


def test_validation_requires_text_not_bytes() -> None:
    with pytest.raises(TypeError):
        validate_three_surface_text(b'{"title":"A","alt":"B","caption":"C"}')  # type: ignore[arg-type]


# --- valid content is preserved exactly -------------------------------------------


def test_valid_text_is_returned_in_canonical_order_without_stripping_or_normalizing() -> None:
    raw = (
        '\n  {\n    "caption": "First line.\\nSecond line.\\r\\n",\n'
        '    "alt": "A sign reads \\"Caf\\u00e9\\" \\\\ back\\tslash",\n'
        '    "title": "  cafe\\u0301 \\u2014 padded  "\n  }\n'
    )

    surfaces = validate_three_surface_text(raw)

    assert list(surfaces) == ["title", "alt", "caption"]
    assert surfaces == {
        "title": "  cafe\u0301 \u2014 padded  ",
        "alt": 'A sign reads "Caf\u00e9" \\ back\tslash',
        "caption": "First line.\nSecond line.\r\n",
    }


def test_factual_claims_pass_format_but_are_not_reviewed() -> None:
    # validation-fixtures.json factual_claim_not_a_schema_error: format may pass;
    # profession, intent, events and truth still require content review.
    claim = {
        "title": "A scientist",
        "alt": "A scientist invents a new engine.",
        "caption": "A scientist completes a groundbreaking invention.",
    }
    assert validate_three_surface_text(serialize_three_surfaces(claim)) == claim


def test_text_validation_does_not_decide_transport_truncation() -> None:
    # validation-fixtures.json truncated_even_if_parseable: finish_reason="length" must
    # be rejected by the transport-completion helper before this text is validated.
    assert validate_three_surface_text('{"title":"A","alt":"B","caption":"C"}') == {
        "title": "A",
        "alt": "B",
        "caption": "C",
    }


# --- canonical serialization ------------------------------------------------------


def test_serializer_emits_exact_canonical_text_for_unicode_quotes_newlines_fixture() -> None:
    surfaces = {
        "title": "A sign \u2014 caf\u00e9",
        "alt": 'A sign reads "Caf\u00e9".',
        "caption": "First line.\nSecond line.",
    }

    canonical = serialize_three_surfaces(surfaces)

    assert canonical == (
        '{"title":"A sign \u2014 caf\u00e9","alt":"A sign reads \\"Caf\u00e9\\".","caption":"First line.\\nSecond line."}'
    )
    assert "caf\u00e9".encode() in canonical.encode("utf-8")
    assert "\\u00e9" not in canonical
    assert validate_three_surface_text(canonical) == surfaces


def test_serializer_fixes_key_order_and_newline_policy() -> None:
    surfaces = MappingProxyType(
        {
            "caption": "Line one.\r\nLine two.\n",
            "alt": "Tab\there, U+2028\u2028and NEL\x85kept.",
            "title": "  Leading and trailing  ",
        }
    )

    canonical = serialize_three_surfaces(surfaces)

    assert list(json.loads(canonical)) == ["title", "alt", "caption"]
    # One line, no trailing newline: in-value CR/LF use the JSON escapes \r and \n.
    assert "\n" not in canonical
    assert "\r" not in canonical
    assert canonical.startswith('{"title":"  Leading and trailing  ",')
    assert canonical.endswith('"caption":"Line one.\\r\\nLine two.\\n"}')
    assert validate_three_surface_text(canonical) == dict(surfaces)


def test_raw_and_canonical_stay_distinct_and_serialization_is_a_fixpoint() -> None:
    raw = '{ "alt" : "B \\u00e9", "caption" : "C", "title" : "A" }\n'

    surfaces = validate_three_surface_text(raw)
    canonical = serialize_three_surfaces(surfaces)

    assert canonical == '{"title":"A","alt":"B \u00e9","caption":"C"}'
    assert canonical != raw
    assert raw == '{ "alt" : "B \\u00e9", "caption" : "C", "title" : "A" }\n'
    assert serialize_three_surfaces(validate_three_surface_text(canonical)) == canonical
    assert canonical.encode("utf-8").decode("utf-8") == canonical


def test_serializer_does_not_mutate_its_input() -> None:
    surfaces = {"caption": " C ", "alt": "B", "title": "A"}
    serialize_three_surfaces(surfaces)
    assert list(surfaces.items()) == [("caption", " C "), ("alt", "B"), ("title", "A")]


@pytest.mark.parametrize(
    ("value", "code", "fields"),
    [
        # A title-only result cannot be completed by the serializer.
        pytest.param({"title": "A mirror selfie"}, SCHEMA, ("alt", "caption"), id="title-only"),
        pytest.param(
            {"title": "A", "alt": "B", "caption": "C", "identity": "guessed"}, SCHEMA, ("identity",), id="extra"
        ),
        pytest.param({"title": "A", "alt": "B", "caption": None}, SCHEMA, ("caption",), id="none"),
        pytest.param({"title": "A", "alt": 2, "caption": "C"}, SCHEMA, ("alt",), id="int"),
        pytest.param({"title": "A", "alt": b"B", "caption": "C"}, SCHEMA, ("alt",), id="bytes"),
        pytest.param({"title": "", "alt": "B", "caption": "C"}, SCHEMA, ("title",), id="empty"),
        pytest.param({"title": "A", "alt": " \n", "caption": "C"}, CONTENT, ("alt",), id="whitespace"),
        pytest.param({"title": "A", "alt": "B", "caption": "\ud800"}, CONTENT, ("caption",), id="lone-surrogate"),
        pytest.param([("title", "A"), ("alt", "B"), ("caption", "C")], SCHEMA, (), id="pairs-not-mapping"),
        pytest.param('{"title":"A","alt":"B","caption":"C"}', SCHEMA, (), id="json-text-not-mapping"),
    ],
)
def test_serializer_rejects_invalid_typed_input(
    value: object, code: ThreeSurfaceErrorCode, fields: tuple[str, ...]
) -> None:
    with pytest.raises(ThreeSurfaceValidationError) as info:
        serialize_three_surfaces(value)  # type: ignore[arg-type]
    assert info.value.code is code
    assert info.value.fields == fields
