"""Shared <path-text> wire encoder for eval-harness stdout/stderr (VLM6-W17-L-01).

Leaf module: imports nothing from ``cli`` or ``manifest``. Both emission
sites re-export these names so existing
``from scripts.eval_harness.cli import _printable_path`` (and the
manifest equivalent) keep resolving.
"""

from __future__ import annotations

import os
from pathlib import Path

_UNDECODABLE_PATH_PREFIX = "undecodable:"


class EncodedText(str):
    """Already-encoded operator-facing text.

    Re-feeding to ``_printable_path`` or ``_printable_message`` is a no-op
    so the two encoders cannot compose into a third wire form (VLM6-W18-F1-01).
    """

    __slots__ = ()


class PathText(EncodedText):
    """Wire-form <path-text>. Produced by ``_printable_path``."""

    __slots__ = ()


class MessageText(EncodedText):
    """Wire-form operator message. Produced by ``_printable_message``."""

    __slots__ = ()


def _printable_message(message: str) -> EncodedText:
    """Make operator text printable without claiming it is a filename (API-11).

    Recovers PEP 383 surrogates the same way ``_printable_path`` recovers argv,
    but never applies the ``undecodable:`` path-slot marker and never prepends
    a backslash for an already-marked string. Idempotent: a second pass is a
    no-op (VLM6-RV16-L-02 / L-03). Already-encoded ``EncodedText`` is
    returned unchanged so this encoder cannot compose with ``_printable_path``
    (VLM6-W18-F1-01).
    """
    if isinstance(message, EncodedText):
        return message  # WHY: re-wrap drops PathText identity and allows later path re-escape
    try:
        message.encode("utf-8")
    except UnicodeEncodeError:
        raw = os.fsencode(message)
        try:
            return MessageText(raw.decode("utf-8"))
        except UnicodeDecodeError:
            doubled = raw.replace(b"\\", b"\\\\")
            return MessageText(doubled.decode("utf-8", errors="backslashreplace"))
    return MessageText(message)


def _escape_undecodable_marker(text: str) -> str:
    """Keep ``undecodable:`` out-of-band on decodable names (L-02).

    A real UTF-8 name that starts with the fallback prefix, or with one
    or more backslashes then that prefix, gets one extra leading
    backslash so two distinct filenames cannot share a wire form.
    """
    if text.lstrip("\\").startswith(_UNDECODABLE_PATH_PREFIX):
        return f"\\{text}"
    return text


def _printable_path(path: Path | str) -> EncodedText:
    """OBS-08: machine-consumable path text for stdout/stderr.

    Fast path: if the path text encodes as UTF-8, return it (no fsencode
    round-trip) except when it would collide with the fallback marker: a
    name that starts with ``undecodable:`` (or with backslashes then that
    marker) is emitted with one extra leading backslash. A name that
    literally contains the four characters ``\\xe9`` therefore prints as
    those four characters.

    Fallback: PEP 383 surrogates (C-locale argv) are recovered via
    ``os.fsencode``. Valid UTF-8 sequences become the real filename so a
    utf-8 stream emits the real path bytes (café, not ``\\udcc3\\udca9``)
    and then take the same marker-escape as the fast path. Remaining
    undecodable bytes use backslashreplace (``\\xHH``) after doubling any
    literal backslash so the escape is invertible, and are prefixed with
    ``undecodable:`` so a consumer can tell ``run-caf\\xe9-report.md``
    (literal) from ``undecodable:run-caf\\xe9-report.md`` (byte 0xe9).

    Round-trip:
    - If the text starts with ``undecodable:`` (no leading backslash),
      strip the prefix and decode C-style backslash escapes (``\\\\`` →
      one backslash, ``\\xHH`` → one byte, including ``\\b`` as
      backspace) to recover the original bytes.
    - If the text starts with one or more backslashes followed by
      ``undecodable:``, strip exactly one leading backslash; the rest is
      the UTF-8 filename.
    - Otherwise the text is the UTF-8 filename as-is.

    Already-encoded ``EncodedText`` is returned unchanged: applying this
    encoder twice, or applying it to ``_printable_message`` output, must
    not add another marker-escape (VLM6-W18-F1-01).
    """
    if isinstance(path, EncodedText):
        return path  # WHY: second pass prepends \\ onto undecodable: wire form
    text = os.fspath(path)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raw = os.fsencode(text)
        try:
            return PathText(_escape_undecodable_marker(raw.decode("utf-8")))
        except UnicodeDecodeError:
            doubled = raw.replace(b"\\", b"\\\\")
            escaped = doubled.decode("utf-8", errors="backslashreplace")
            return PathText(f"{_UNDECODABLE_PATH_PREFIX}{escaped}")
    return PathText(_escape_undecodable_marker(text))
