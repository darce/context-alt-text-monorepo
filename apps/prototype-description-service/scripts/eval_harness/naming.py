"""Shared entity-name + image-extension helpers (roster consistency, HARM-05).

Roster names must stay byte-identical across three surfaces: the golden manifest
(`golden.json`), server-side cluster labels (seeding), and scoring. Deriving them
in one place — instead of slice-2 ``seed_roster`` reaching into slice-1
``draft_labels`` private helpers and each module keeping its own ``_IMAGE_EXTS``
copy — keeps a rename or extension-set edit from silently desynchronizing the
others.
"""

from __future__ import annotations

import re
from pathlib import Path

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png"})

_VARIANT_SUFFIX = re.compile(r"-\d+$")


def entity_slug(filename: str) -> str:
    """``entity-hollow-pennant-2.jpg`` -> ``hollow-pennant`` (strip prefix + variant suffix)."""
    stem = Path(filename).stem.removeprefix("entity-")
    return _VARIANT_SUFFIX.sub("", stem)


def display_name(slug: str) -> str:
    """``hollow-pennant`` -> ``Hollow Pennant`` (roster display form)."""
    return " ".join(part.capitalize() for part in slug.split("-"))
