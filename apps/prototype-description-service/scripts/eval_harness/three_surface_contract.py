"""Strict three-surface writer output boundary (opt-in; legacy parsing is unchanged).

``three_surfaces.schema.json`` is the shared writer contract: exactly ``title``,
``alt`` and ``caption``, each a string of length >= 1, nothing else. This module
validates raw writer text against it and serializes a validated value. It never
repairs, completes or re-asks: a missing surface stays a rejection.

Error codes keep three failure classes apart: JSON the strict parser rejects
(including duplicate members and non-finite numbers), schema violations, and
schema-valid content that is whitespace-only or not encodable as UTF-8.
Transport completion (HTTP status, finish reason, truncation) must be checked
before this boundary, and passing it says nothing about factual correctness.

Canonical text is the standard ``json`` encoder's output with keys in
``THREE_SURFACE_KEYS`` order, separators ``(",", ":")``, ``ensure_ascii=False``
and ``allow_nan=False``. Newline policy: one line with no trailing newline; CR
and LF inside values appear only as the JSON escapes ``\\r`` and ``\\n``. Other
characters, including U+0085, U+2028 and U+2029, are emitted unescaped, so
encode canonical text as UTF-8 and do not split it with ``str.splitlines``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn

THREE_SURFACE_SCHEMA_ID = "urn:altcontext:schema:three-surfaces:v2"
THREE_SURFACE_KEYS = ("title", "alt", "caption")
_SCHEMA_PATH = Path(__file__).resolve().parent / "three_surfaces.schema.json"


class ThreeSurfaceErrorCode(StrEnum):
    JSON_SYNTAX_FAILED = "json_syntax_failed"
    SCHEMA_FAILED = "schema_failed"
    CONTENT_SHAPE_FAILED = "content_shape_failed"


class ThreeSurfaceValidationError(ValueError):
    """Writer output violates the contract. ``code`` is stable; ``fields`` names the offending keys."""

    def __init__(self, code: ThreeSurfaceErrorCode, message: str, fields: tuple[str, ...] = ()) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.fields = fields


def load_three_surface_schema() -> dict[str, Any]:
    """Return a fresh parse of the shared schema; mutating it cannot affect later calls."""
    schema: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ThreeSurfaceValidationError(ThreeSurfaceErrorCode.JSON_SYNTAX_FAILED, f"duplicate member {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> NoReturn:
    raise ThreeSurfaceValidationError(ThreeSurfaceErrorCode.JSON_SYNTAX_FAILED, f"non-finite number {name}")


def _finite_float(literal: str) -> float:
    # Overflowing literals such as 1e999 become inf without reaching parse_constant.
    value = float(literal)
    if not math.isfinite(value):
        _reject_constant(literal)
    return value


def _utf8_encodable(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:  # lone surrogate, e.g. from a "\ud800" escape
        return False
    return True


def _checked_surfaces(document: object) -> dict[str, str]:
    if not isinstance(document, Mapping):
        raise ThreeSurfaceValidationError(
            ThreeSurfaceErrorCode.SCHEMA_FAILED, f"expected an object, got {type(document).__name__}"
        )
    missing = tuple(key for key in THREE_SURFACE_KEYS if key not in document)
    extra = tuple(str(key) for key in document if key not in THREE_SURFACE_KEYS)
    if missing or extra:
        raise ThreeSurfaceValidationError(
            ThreeSurfaceErrorCode.SCHEMA_FAILED, f"missing {list(missing)}, unexpected {list(extra)}", missing + extra
        )
    not_text = tuple(key for key in THREE_SURFACE_KEYS if not isinstance(document[key], str) or not document[key])
    if not_text:
        raise ThreeSurfaceValidationError(
            ThreeSurfaceErrorCode.SCHEMA_FAILED, f"{list(not_text)} must be non-empty strings", not_text
        )
    unusable = tuple(key for key in THREE_SURFACE_KEYS if document[key].isspace() or not _utf8_encodable(document[key]))
    if unusable:
        raise ThreeSurfaceValidationError(
            ThreeSurfaceErrorCode.CONTENT_SHAPE_FAILED,
            f"{list(unusable)} must contain non-whitespace text encodable as UTF-8",
            unusable,
        )
    return {key: document[key] for key in THREE_SURFACE_KEYS}


def validate_three_surface_text(raw: str) -> dict[str, str]:
    """Strictly parse raw writer text into its surfaces, in ``THREE_SURFACE_KEYS`` order.

    The whole text must be one JSON object; only JSON whitespace may surround it,
    so markdown fences, prose and trailing data are syntax failures. Values are
    returned exactly as decoded, without stripping or Unicode normalization.
    """
    if not isinstance(raw, str):
        raise TypeError(f"raw writer output must be str, not {type(raw).__name__}")
    try:
        document = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except ThreeSurfaceValidationError:
        raise
    except json.JSONDecodeError as exc:
        raise ThreeSurfaceValidationError(
            ThreeSurfaceErrorCode.JSON_SYNTAX_FAILED, f"{exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc
    except ValueError as exc:  # e.g. an integer literal past the interpreter's digit limit
        raise ThreeSurfaceValidationError(ThreeSurfaceErrorCode.JSON_SYNTAX_FAILED, str(exc)) from exc
    except RecursionError as exc:
        raise ThreeSurfaceValidationError(ThreeSurfaceErrorCode.JSON_SYNTAX_FAILED, "nesting too deep") from exc
    return _checked_surfaces(document)


def serialize_three_surfaces(value: Mapping[str, str]) -> str:
    """Validate ``value`` and return its canonical JSON text (see the module docstring)."""
    surfaces = _checked_surfaces(value)
    text = json.dumps(surfaces, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if validate_three_surface_text(text) != surfaces:
        raise RuntimeError("canonical three-surface text did not round-trip")
    return text
