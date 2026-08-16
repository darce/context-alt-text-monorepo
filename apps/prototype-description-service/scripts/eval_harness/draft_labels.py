"""Draft-label generator: filename heuristics -> draft golden manifest + review notes.

One-time Slice-1 tool. Derives the roster from ``mock_entities/entity-<name>*``
crops and guesses per-scene present identities from filename tokens. The output
is a DRAFT — every guess must pass an operator confirmation pass before the
manifest is committed as ground truth (filenames encode nicknames and initials
the heuristic cannot resolve; those land in the review notes instead).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from .manifest import ManifestError
from .naming import IMAGE_EXTS, display_name, entity_slug


def normalize_rel_path(rel_path: str) -> str:
    """NFC-normalize a relative path for stable string comparison (S7-03).

    Fixture filenames can flip NFC/NFD across rsync hosts; compare and key on
    a single normalization form so draft-vs-golden reconcile is host-stable.
    """
    return unicodedata.normalize("NFC", rel_path)


def generate_draft_manifest(fixtures_dir: str) -> tuple[dict, list[str]]:
    """Build a draft manifest dict (strict-schema compatible) + operator review notes.

    ``fixtures_dir`` must contain ``mock_entities/`` and ``mock_images/``.
    """
    root = Path(fixtures_dir)
    entities_dir = root / "mock_entities"
    images_dir = root / "mock_images"
    if not entities_dir.is_dir() or not images_dir.is_dir():
        raise ManifestError(
            f"fixture dirs not found under {root} (need mock_entities/ and mock_images/) — "
            "set GOLDEN_IMAGES_DIR to the rsync-bootstrapped copy (see scene/tests/seed/README.md)"
        )

    slugs = sorted({entity_slug(p.name) for p in entities_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS})
    roster = [display_name(s) for s in slugs]
    token_to_name: dict[str, str] = {}
    for slug, name in zip(slugs, roster, strict=True):
        for token in slug.split("-"):
            token_to_name.setdefault(token, name)

    notes: list[str] = []
    entries: list[dict] = []
    media_id = 0
    for image in sorted(images_dir.iterdir(), key=lambda p: p.name):
        if image.suffix.lower() not in IMAGE_EXTS:
            continue
        media_id += 1
        stem_tokens = re.split(r"[-_.\s]+", image.stem.lower())
        matched: list[str] = []
        unmatched: list[str] = []
        for token in stem_tokens:
            guess = token_to_name.get(token)
            if guess is not None:
                if guess not in matched:
                    matched.append(guess)
            else:
                unmatched.append(token)
        matched.sort()
        if not matched:
            notes.append(
                f"{image.name}: no roster match (tokens: {', '.join(unmatched)}) — confirm no known identities present"
            )
        elif unmatched:
            notes.append(
                f"{image.name}: matched {', '.join(matched)}; unresolved tokens: "
                f"{', '.join(unmatched)} — confirm labels"
            )
        entries.append(
            {
                "path": normalize_rel_path(f"mock_images/{image.name}"),
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "media_id": media_id,
                # Draft floor: at least the matched identities. The operator sets
                # the true total (including non-roster strangers) during review.
                "face_count": len(matched),
                "present_identities": matched,
                "context_pack": {},
                # v2 requires the key; operator fills a real caption during review (S6-01).
                "base_caption": "",
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "provenance": {
                    "source": "fixture",
                    "license": "fixture",
                    "note": "vendored eval-corpus fixture",
                },
            }
        )

    draft = {
        "manifest_version": 3,
        "annotation_mode": "roster_only",
        "roster": roster,
        "entries": entries,
    }
    return draft, notes
