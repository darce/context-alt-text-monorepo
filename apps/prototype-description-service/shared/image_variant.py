"""Canonical Docker image variant identity (sr-007).

Lives under ``shared`` — a wheel-included package — because ``api.main`` imports
it. ``scripts`` is deliberately excluded from the hatch/setuptools wheel include,
so any constant ``api.main`` needs must not live there or the production image
fails at import. ``scripts.verify_vlm_cache`` re-exports these members for the
boot-time gate.
"""

from enum import StrEnum
from pathlib import Path


class ImageVariant(StrEnum):
    """Canonical Docker image variant labels (sr-007).

    Baked into each runtime stage as ``/app/.image-variant`` (and ENV mirror).
    Do not scatter the string literals elsewhere in Python — import these members.
    """

    RECOGNITION = "recognition"
    VLM = "vlm"


IMAGE_VARIANT_ENV = "ACX_IMAGE_VARIANT"
DEFAULT_IMAGE_VARIANT = ImageVariant.RECOGNITION
# Build-immutable identity artifact (Dockerfile writes this per runtime stage).
# Module-level so tests can monkeypatch; production path is fixed.
IMAGE_VARIANT_ARTIFACT = Path("/app/.image-variant")
