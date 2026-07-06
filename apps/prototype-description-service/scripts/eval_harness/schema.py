"""Shared eval-artifact schema identifiers — single source of truth (sr-007).

One ``schema`` id (``acx-eval/v1``) tags both eval documents; the ``kind``
discriminator distinguishes a raw fetch **run record** from a scored **report**
so a consumer — and the score phase — can tell them apart instead of guessing
from which keys happen to be present (HARM-06).
"""

from __future__ import annotations

from enum import StrEnum

SCHEMA = "acx-eval/v1"


class DocKind(StrEnum):
    """Document-kind discriminator carried alongside ``schema``."""

    RUN_RECORD = "run_record"
    REPORT = "report"
