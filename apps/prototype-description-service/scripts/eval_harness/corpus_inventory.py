"""Corpus inventory + cheap stratification features for Golden-100 (VLM-6 S1).

Walks an image directory and, per original (WP `-WxH` thumbnails skipped),
computes deterministic, no-ML, no-network features that pre-bucket candidates for
operator review:

- ``sha256`` (dedup + manifest key), ``width``/``height``, aspect ratio.
- ``mean_saturation`` (HSV S-channel mean, 0..1) — near-zero flags the
  black-and-white stratum; a pixel statistic, not a model.
- ``mean_value`` (HSV V-channel mean) — flags the low-light stratum.
- ``flat_color_coverage`` — pixel share held by the few most common quantized
  colors; high on charts/screenshots, low on photographs.
- ``edge_density`` — mean edge response; ranks dense/busy scenes.
- ``celeb_name`` from the filename (public-figure identity label).
- ``xmp_names`` + ``xmp_face_count`` from embedded IPTC/MWG face regions.

Every feature is a SHORTLISTING signal for operator review, never ground truth:
the thresholds below pre-bucket candidates, and a human confirms the stratum.
Face-count-by-model strata (people/crowds) come from a later pass against the
remote recognition service; this module is the offline, local-only first pass.

Scans are checkpointed: records stream to JSONL as they are computed, so a scan
killed under memory pressure resumes with ``--resume`` instead of restarting.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from PIL import Image, ImageFilter

from scripts.eval_harness._pathtext import _printable_message, _printable_path
from scripts.eval_harness.identity_sources import (
    celeb_identity_from_filename,
    extract_face_regions,
    named_identities,
)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
# WordPress generates resized copies named `<stem>-<W>x<H>.<ext>`; skip them so
# the inventory holds originals only.
_THUMBNAIL_SUFFIX = re.compile(r"-\d+x\d+\.[a-zA-Z]+$")
# Above `big_image_size_threshold` WordPress also serves a `<stem>-scaled.<ext>`
# re-encode beside the untouched original. It is the same photo at a different size,
# so its bytes differ and sha256 dedupe cannot catch it — 398 such pairs sit in the
# real uploads tree, and left in they double-count a stratum and burn review slots.
_SCALED_SUFFIX = re.compile(r"-scaled(\.[a-zA-Z]+)$")


@dataclass(frozen=True)
class ImageRecord:
    path: str  # relative to the walked root
    sha256: str
    width: int | None
    height: int | None
    mean_saturation: float | None  # 0..1; None if unreadable as an image
    mean_value: float | None  # HSV V mean, 0..1; None if unreadable
    aspect_ratio: float | None
    celeb_name: str | None
    xmp_names: list[str]
    xmp_face_count: int
    bw_candidate: bool  # mean_saturation below the grayscale threshold
    low_light_candidate: bool  # mean_value below the dark threshold
    flat_color_coverage: float | None  # pixel share held by the top quantized colors
    flat_color_candidate: bool  # chart/screenshot-like flat-color image
    edge_density: float | None  # mean edge response, 0..1; ranks busy scenes


# Empirically separates B&W/monochrome scans from muted-but-colored photos.
BW_SATURATION_THRESHOLD = 0.06
# HSV V mean below this reads as a night/underexposed frame rather than a dim one.
LOW_LIGHT_VALUE_THRESHOLD = 0.22
# Share of pixels held by FLAT_COLOR_TOP_N colors after 5-bit-per-channel
# quantization. Charts/screenshots concentrate; photographs spread out.
FLAT_COLOR_COVERAGE_THRESHOLD = 0.5
FLAT_COLOR_TOP_N = 8
# Features are computed on a copy bounded to this edge so a 9.6k-image scan stays
# cheap on a memory-pressured host; recorded width/height remain the originals.
FEATURE_EDGE_PX = 256


def _feature_image(image: Image.Image) -> Image.Image:
    """Downscale to a bounded copy for feature stats (a uniform, unbiased sample)."""
    copy = image.convert("RGB")
    copy.thumbnail((FEATURE_EDGE_PX, FEATURE_EDGE_PX), Image.BILINEAR)
    return copy


def _channel_mean(image: Image.Image, channel: str) -> float:
    """Mean of one HSV channel normalized to 0..1, via the histogram (not per-pixel)."""
    histogram = image.convert("HSV").getchannel(channel).histogram()
    total = sum(histogram)
    if total == 0:
        return 0.0
    weighted = sum(value * count for value, count in enumerate(histogram))
    return (weighted / total) / 255.0


def _flat_color_coverage(image: Image.Image) -> float:
    """Pixel share held by the top-N colors at 5-bit-per-channel quantization.

    Quantizing to a fixed grid (rather than an adaptive palette) keeps this
    deterministic: near-identical shades collapse together, so large flat regions
    of a chart or screenshot concentrate into a few bins while photographic
    gradients stay spread across many.
    """
    quantized = image.point(lambda v: v & 0b11111000)
    colors = quantized.getcolors(maxcolors=quantized.width * quantized.height)
    if not colors:
        return 0.0
    total = sum(count for count, _ in colors)
    if total == 0:
        return 0.0
    top = sorted((count for count, _ in colors), reverse=True)[:FLAT_COLOR_TOP_N]
    return sum(top) / total


def _edge_density(image: Image.Image) -> float:
    """Mean edge-filter response, 0..1. The 1px border is cropped: FIND_EDGES
    leaves a bright frame there that would otherwise scale with the image."""
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    if edges.width <= 2 or edges.height <= 2:
        return 0.0
    inner = edges.crop((1, 1, edges.width - 1, edges.height - 1))
    histogram = inner.histogram()
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
    mean_sat = mean_val = aspect = coverage = edges = None
    try:
        with Image.open(io.BytesIO(data)) as image:
            # Read the true dims before draft(): drafting mutates image.size to the
            # DCT-scaled decode size, which would otherwise be recorded as the original.
            width, height = image.width, image.height
            image.draft("RGB", (FEATURE_EDGE_PX, FEATURE_EDGE_PX))  # fast JPEG path; no-op otherwise
            features = _feature_image(image)
        mean_sat = _channel_mean(features, "S")
        mean_val = _channel_mean(features, "V")
        coverage = _flat_color_coverage(features)
        edges = _edge_density(features)
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
        mean_value=None if mean_val is None else round(mean_val, 4),
        aspect_ratio=aspect,
        celeb_name=celeb_identity_from_filename(path.name),
        xmp_names=names,
        xmp_face_count=len(regions),
        bw_candidate=mean_sat is not None and mean_sat < BW_SATURATION_THRESHOLD,
        low_light_candidate=mean_val is not None and mean_val < LOW_LIGHT_VALUE_THRESHOLD,
        flat_color_coverage=None if coverage is None else round(coverage, 4),
        flat_color_candidate=coverage is not None and coverage > FLAT_COLOR_COVERAGE_THRESHOLD,
        edge_density=None if edges is None else round(edges, 4),
    )


def _is_redundant_scaled_copy(path: Path) -> bool:
    """True for a WP `-scaled` re-encode whose untouched original sits beside it.

    Gated on the original actually existing: some uploads are `-scaled`-only, and
    dropping those unconditionally would lose the image rather than a duplicate.
    """
    match = _SCALED_SUFFIX.search(path.name)
    if not match:
        return False
    return path.with_name(_SCALED_SUFFIX.sub(r"\1", path.name)).exists()


def iter_original_images(root: Path) -> Iterable[Path]:
    """Yield original image paths under ``root``.

    Excludes WP `-WxH` thumbnails and redundant `-scaled` re-encodes.
    """
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _IMAGE_EXTS:
            continue
        if _THUMBNAIL_SUFFIX.search(path.name) or _is_redundant_scaled_copy(path):
            continue
        yield path


def iter_new_images(root: Path, *, done: set[str]) -> Iterator[Path]:
    """Yield original images under ``root`` whose relative path isn't in ``done``."""
    for path in iter_original_images(root):
        if str(path.relative_to(root)) not in done:
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


_FIELD_NAMES = {f.name for f in fields(ImageRecord)}


def load_records(path: Path) -> list[ImageRecord]:
    """Read a checkpoint JSONL back into records.

    A scan killed mid-write leaves a truncated final line; it is dropped so a
    resume re-inventories that one image instead of crashing. Rows missing fields
    (written by an older schema) are likewise dropped and recomputed.
    """
    if not path.exists():
        return []
    records: list[ImageRecord] = []
    schema_dropped = 0
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # truncated tail of an interrupted write
        if not isinstance(row, dict) or set(row) != _FIELD_NAMES:
            schema_dropped += 1
            continue
        records.append(ImageRecord(**row))
    if schema_dropped:
        # A schema change silently invalidates the checkpoint; make the re-scan visible
        # rather than letting --resume quietly redo work it looks like it already did (rg-008).
        print(
            f"WARNING: {_printable_path(path)}: dropped {schema_dropped} checkpoint row(s) whose fields do not "
            "match the current ImageRecord schema; those images will be re-inventoried",
            file=sys.stderr,
        )
    return records


def _append_record(handle, record: ImageRecord) -> None:
    handle.write(json.dumps(asdict(record)) + "\n")
    handle.flush()  # checkpoint: a kill must not lose completed work


def write_records(path: Path, records: Iterable[ImageRecord]) -> None:
    with path.open("w") as handle:
        for record in records:
            _append_record(handle, record)


def _scan(root: Path, out: Path, *, limit: int | None, resume: bool) -> tuple[int, int, int]:
    """Stream an inventory scan to ``out``, returning (new_count, resumed_count, skipped_count)."""
    existing = load_records(out) if resume else []
    done = {record.path for record in existing}
    # Rewrite the kept prefix first: truncates on a fresh scan, and on a resume drops
    # any truncated tail line so appends can't land behind corrupt bytes.
    write_records(out, existing)
    written = 0
    skipped = 0
    with out.open("a") as handle:
        for path in iter_new_images(root, done=done):
            if limit is not None and written >= limit:
                break
            try:
                record = inventory_image(path, root)
            except Exception as exc:  # noqa: BLE001 — one unreadable/vanished file must not halt the scan (rg-007)
                # Skip and continue rather than aborting: an unhandled raise here would
                # end the whole scan, and since the file is never checkpointed every
                # --resume would re-hit it and re-abort at the same spot (never completing).
                skipped += 1
                print(
                    f"WARNING: skipping {_printable_path(path)}: {type(exc).__name__}: "
                    f"{_printable_message(str(exc))}",
                    file=sys.stderr,
                )
                continue
            _append_record(handle, record)
            written += 1
    return written, len(existing), skipped


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory an image directory for Golden-100 selection.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="checkpoint JSONL (one record per line)")
    parser.add_argument("--limit", type=int, default=None, help="max NEW images to inventory this run")
    parser.add_argument("--resume", action="store_true", help="keep --out's records and scan only what's missing")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        parser.error(f"root is not a directory: {_printable_path(args.root)}")
    written, resumed, skipped = _scan(args.root, args.out, limit=args.limit, resume=args.resume)
    records = load_records(args.out)
    bw = sum(1 for r in records if r.bw_candidate)
    named = sum(1 for r in records if r.xmp_names)
    celebs = sum(1 for r in records if r.celeb_name)
    dupes = len(records) - len(dedupe_by_sha256(records))
    print(
        f"{len(records)} images -> {_printable_path(args.out)}  (+{written} new, resumed {resumed}, skipped {skipped}, "
        f"dupes={dupes}, bw~{bw}, xmp-named={named}, celeb-labeled={celebs})"
    )
    # Non-zero when a run inventoried nothing new yet hit unreadable files: a bounded
    # signal that the scan made no progress rather than silently "succeeding" (rg-007).
    return 1 if written == 0 and skipped > 0 else 0


if __name__ == "__main__":
    sys.exit(_main())
