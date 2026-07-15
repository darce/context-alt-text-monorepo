"""Corpus inventory + cheap stratification features for Golden-100 (VLM-6 S1).

Walks an image directory and, per original (WP `-WxH` thumbnails skipped),
computes deterministic, no-ML, no-network features that pre-bucket candidates for
operator review:

- ``sha256`` (dedup + manifest key), ``width``/``height``, aspect ratio.
- ``mean_saturation`` (HSV S-channel mean, 0..1) — near-zero flags the
  black-and-white stratum; a pixel statistic, not a model.
- ``celeb_name`` from the filename (public-figure identity label).
- ``xmp_names`` + ``xmp_face_count`` from embedded IPTC/MWG face regions.

Face-count-by-model strata (people/crowds) come from a later pass against the
remote recognition service; this module is the offline, local-only first pass.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from scripts.eval_harness.identity_sources import (
    celeb_identity_from_filename,
    extract_face_regions,
    named_identities,
)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
# WordPress generates resized copies named `<stem>-<W>x<H>.<ext>`; skip them so
# the inventory holds originals only.
_THUMBNAIL_SUFFIX = re.compile(r"-\d+x\d+\.[a-zA-Z]+$")


@dataclass(frozen=True)
class ImageRecord:
    path: str  # relative to the walked root
    sha256: str
    width: int | None
    height: int | None
    mean_saturation: float | None  # 0..1; None if unreadable as an image
    aspect_ratio: float | None
    celeb_name: str | None
    xmp_names: list[str]
    xmp_face_count: int
    bw_candidate: bool  # mean_saturation below the grayscale threshold


# Empirically separates B&W/monochrome scans from muted-but-colored photos.
BW_SATURATION_THRESHOLD = 0.06


def _mean_saturation(image: Image.Image) -> float:
    """HSV S-channel mean normalized to 0..1 (0 = pure grayscale)."""
    saturation = image.convert("RGB").convert("HSV").getchannel("S")
    # Image.getextrema/histogram avoids pulling every pixel into Python.
    histogram = saturation.histogram()
    total = sum(histogram)
    if total == 0:
        return 0.0
    weighted = sum(value * count for value, count in enumerate(histogram))
    return (weighted / total) / 255.0


def inventory_image(path: Path, root: Path) -> ImageRecord:
    """Inventory a single image. Image decode failures degrade to metadata-only."""
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    width = height = None
    mean_sat = aspect = None
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.width, image.height
            mean_sat = _mean_saturation(image)
        aspect = round(width / height, 4) if width and height else None
    except (OSError, ValueError, Image.DecompressionBombError):
        pass  # degrade-path: keep sha256 + XMP; image features stay None
    regions = extract_face_regions(data)
    names = named_identities(regions)
    return ImageRecord(
        path=str(path.relative_to(root)),
        sha256=sha,
        width=width,
        height=height,
        mean_saturation=None if mean_sat is None else round(mean_sat, 4),
        aspect_ratio=aspect,
        celeb_name=celeb_identity_from_filename(path.name),
        xmp_names=names,
        xmp_face_count=len(regions),
        bw_candidate=mean_sat is not None and mean_sat < BW_SATURATION_THRESHOLD,
    )


def iter_original_images(root: Path) -> Iterable[Path]:
    """Yield original image paths under ``root`` (WP `-WxH` thumbnails excluded)."""
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _IMAGE_EXTS:
            continue
        if _THUMBNAIL_SUFFIX.search(path.name):
            continue
        yield path


def inventory_dir(root: Path, *, limit: int | None = None) -> list[ImageRecord]:
    records: list[ImageRecord] = []
    for path in iter_original_images(root):
        records.append(inventory_image(path, root))
        if limit is not None and len(records) >= limit:
            break
    return records


def dedupe_by_sha256(records: Sequence[ImageRecord]) -> list[ImageRecord]:
    """Keep the first record per content hash (stable order)."""
    seen: set[str] = set()
    out: list[ImageRecord] = []
    for record in records:
        if record.sha256 in seen:
            continue
        seen.add(record.sha256)
        out.append(record)
    return out


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory an image directory for Golden-100 selection.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dedupe", action="store_true", help="drop content-duplicate images")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        parser.error(f"root is not a directory: {args.root}")
    records = inventory_dir(args.root, limit=args.limit)
    if args.dedupe:
        records = dedupe_by_sha256(records)
    args.out.write_text(json.dumps([asdict(r) for r in records], indent=2))
    bw = sum(1 for r in records if r.bw_candidate)
    named = sum(1 for r in records if r.xmp_names)
    celebs = sum(1 for r in records if r.celeb_name)
    print(f"{len(records)} images -> {args.out}  (bw~{bw}, xmp-named={named}, celeb-labeled={celebs})")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
