"""Recover the corpus downscale recipe from the manifest (CORPUS-1).

The v3 manifest records, for all 646 entries, the digest (``sha256``, downscaled
space), the pixel dimensions and the byte length of a downscaled mirror whose
producer was never committed. The mirror itself is gone. This module treats the
manifest as a **fixed oracle** and sweeps a declared grid of candidate recipes,
so "which recipe built it" is a decidable experiment rather than an argument.

Three oracles, increasing strictness and decreasing environment-independence:

``dims``
    Pure arithmetic on (source_w, source_h). No decode, no encode. Settles
    geometry and rounding mode. Always available: the manifest carries
    ``width``/``height``.
``pixels``
    Decode both sides and compare, within a stated per-channel tolerance.
    Catches the resample filter. Tolerance is not a fudge factor: the mirror is
    JPEG, so ``decode(reference)`` can never equal ``render(source)`` exactly,
    and a tier demanding bit equality against a lossy container would report
    every candidate — including the true one — as a mismatch. ``tolerance=0``
    is available and correct for a lossless mirror. **Requires a reference
    mirror**, which is exactly what was lost, so it reports ``UNAVAILABLE``
    until one exists and never silently degrades to a skip.
``bytes``
    sha256 of the re-encoded file against ``entry["sha256"]``. Available now,
    but binds the result to one libjpeg build, so a miss here is weak evidence
    against a recipe that already passed ``dims``.

The intended reproducibility contract for the rebuilt mirror is ``pixels``, not
``bytes``: the detector never sees the JPEG container, and a byte gate that
fires on an encoder upgrade with every pixel unchanged is a false alarm that
teaches operators to override it.

Heuristics: PROV-01 (preprocessing is part of the evidence chain — a recovered
recipe is only useful if it is recorded with its library version), TEST-08
(determinism: sorted iteration, no sampling, no randomness), rg-007 (per-item
isolation: one unreadable source must not end the sweep), rg-008 (an absent
oracle is an explicit UNAVAILABLE, never an empty default that reads as a pass).
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

# Rounding is the whole ballgame: the observed mirror floors the minor axis
# where Pillow, ImageMagick and WordPress all round up. Name every mode
# explicitly so a sweep result points at one of them instead of "some rounding".
_HALF = Fraction(1, 2)

# Every mode accepts a Fraction or a float. Fraction inputs keep the arithmetic
# exact, which matters: five corpus entries land a hair under an integer under
# IEEE-754 multiplication and a hair over it under exact rationals, and the two
# disagree on the floor.
ROUND_MODES: dict[str, Callable[[Any], int]] = {
    "floor": math.floor,
    "ceil": math.ceil,
    "half_up": lambda x: math.floor(x + _HALF),
    "half_down": lambda x: math.ceil(x - _HALF),
    "half_even": round,  # Python's built-in; banker's rounding
}

RESAMPLE_FILTERS: dict[str, int] = {
    "lanczos": Image.LANCZOS,
    "bicubic": Image.BICUBIC,
    "bilinear": Image.BILINEAR,
    "box": Image.BOX,
    "hamming": Image.HAMMING,
    "nearest": Image.NEAREST,
}


class Tier(StrEnum):
    """Oracle strictness. Ordered weakest to strongest."""

    DIMS = "dims"
    PIXELS = "pixels"
    BYTES = "bytes"


class Verdict(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


class RecipeError(RuntimeError):
    """A recipe is malformed, or a sweep was asked for an impossible tier."""


@dataclass(frozen=True)
class Recipe:
    """One candidate downscale, fully declared.

    Every field that can change output bytes is named here, because a recovered
    recipe that omits one is not reproducible (PROV-01). ``shrink_only`` is not
    a tuning knob: upscaling interpolates pixels that carry no information, and
    for face recognition it inflates the crop past a detector's minimum-size
    gate, manufacturing a detection at a resolution that never existed. A
    recipe with ``shrink_only=False`` is retained only so the sweep can *test*
    whether the historical mirror upscaled; it is never a rebuild candidate.
    """

    name: str
    cap: int
    rounding: str
    shrink_only: bool = True
    resample: str = "lanczos"
    quality: int = 85
    subsampling: int = -1  # -1 = keep encoder default
    progressive: bool = False
    exact_ratio: bool = True  # exact rationals, not IEEE-754 float scaling

    def __post_init__(self) -> None:
        if self.rounding not in ROUND_MODES:
            raise RecipeError(f"unknown rounding {self.rounding!r}; known: {sorted(ROUND_MODES)}")
        if self.resample not in RESAMPLE_FILTERS:
            raise RecipeError(f"unknown resample {self.resample!r}; known: {sorted(RESAMPLE_FILTERS)}")
        if self.cap < 1:
            raise RecipeError(f"cap must be >= 1, got {self.cap}")

    def geometry(self, source_w: int, source_h: int) -> tuple[int, int]:
        """Output dimensions, without touching pixels."""
        longest = max(source_w, source_h)
        if longest <= self.cap and self.shrink_only:
            return source_w, source_h
        roundf = ROUND_MODES[self.rounding]
        if self.exact_ratio:
            ratio = Fraction(self.cap, longest)
            return max(1, roundf(source_w * ratio)), max(1, roundf(source_h * ratio))
        scale = self.cap / longest
        return max(1, roundf(source_w * scale)), max(1, roundf(source_h * scale))

    def upscales(self, source_w: int, source_h: int) -> bool:
        out_w, out_h = self.geometry(source_w, source_h)
        return max(out_w, out_h) > max(source_w, source_h)

    def render(self, source: Path) -> Image.Image:
        with Image.open(source) as im:
            im.load()
            target = self.geometry(*im.size)
            if target == im.size:
                return im.convert("RGB")
            return im.convert("RGB").resize(target, RESAMPLE_FILTERS[self.resample])

    def encode(self, source: Path) -> bytes:
        buf = BytesIO()
        self.render(source).save(
            buf,
            format="JPEG",
            quality=self.quality,
            subsampling=self.subsampling,
            progressive=self.progressive,
        )
        return buf.getvalue()

    def provenance(self) -> dict[str, Any]:
        """The lineage a rebuilt mirror must carry (PROV-01)."""
        import PIL

        return {
            "recipe": self.name,
            "cap": self.cap,
            "rounding": self.rounding,
            "shrink_only": self.shrink_only,
            "resample": self.resample,
            "quality": self.quality,
            "subsampling": self.subsampling,
            "progressive": self.progressive,
            "exact_ratio": self.exact_ratio,
            "pillow_version": PIL.__version__,
        }


@dataclass
class TierResult:
    tier: Tier
    matched: int = 0
    mismatched: int = 0
    errored: int = 0
    unavailable: int = 0
    residual: list[dict[str, Any]] = field(default_factory=list)

    @property
    def considered(self) -> int:
        return self.matched + self.mismatched + self.errored + self.unavailable

    @property
    def rate(self) -> float | None:
        """Match rate over *decidable* items only.

        Errored and unavailable items are excluded from the denominator rather
        than counted as failures: a recipe is not wrong because a source file
        was unreadable. They stay visible in their own counters so the caller
        can never mistake a thin denominator for a strong result.
        """
        decidable = self.matched + self.mismatched
        return self.matched / decidable if decidable else None


def build_source_index(roots: Iterable[Path], digests: set[str]) -> dict[str, Path]:
    """Content-address the source tree: ``sha256_source`` -> path.

    Keyed on content, never on filename or directory layout, so a source tree
    that has been reorganised, renamed or partially re-downloaded still
    resolves. First path wins for duplicate content, in sorted order, so the
    index is deterministic across runs (TEST-08).
    """
    index: dict[str, Path] = {}
    for root in roots:
        for path in sorted(Path(root).rglob("*")):
            if not path.is_file():
                continue
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue  # rg-007: one unreadable file must not end the walk
            if digest in digests and digest not in index:
                index[digest] = path
    return index


def evaluate(
    recipe: Recipe,
    entries: Sequence[dict[str, Any]],
    sources: dict[str, Path],
    tier: Tier,
    mirror_root: Path | None = None,
    residual_cap: int = 40,
    pixel_tolerance: int = 0,
) -> TierResult:
    """Score one recipe against the manifest at one oracle tier.

    ``pixel_tolerance`` is the maximum per-channel absolute difference the
    ``pixels`` tier will accept. Use 0 against a lossless mirror; against the
    JPEG mirror this corpus used, a small non-zero value is required or the
    true recipe fails alongside every false one.
    """
    if tier is Tier.PIXELS and mirror_root is None:
        # rg-008: the honest answer to "no reference mirror" is UNAVAILABLE,
        # not a zero-denominator pass.
        return TierResult(tier=tier, unavailable=len(entries))

    result = TierResult(tier=tier)
    for entry in entries:
        source = sources.get(entry.get("sha256_source", ""))
        if source is None:
            result.unavailable += 1
            continue
        try:
            verdict, got, want = _judge(recipe, entry, source, tier, mirror_root, pixel_tolerance)
        except (OSError, ValueError) as exc:  # rg-007
            result.errored += 1
            if len(result.residual) < residual_cap:
                result.residual.append({"media_id": entry.get("media_id"), "error": str(exc)[:120]})
            continue
        if verdict is Verdict.MATCH:
            result.matched += 1
        else:
            result.mismatched += 1
            if len(result.residual) < residual_cap:
                result.residual.append(
                    {
                        "media_id": entry.get("media_id"),
                        "path": entry.get("path"),
                        "bucket": entry.get("bucket"),
                        "got": got,
                        "want": want,
                    }
                )
    return result


def _judge(
    recipe: Recipe,
    entry: dict[str, Any],
    source: Path,
    tier: Tier,
    mirror_root: Path | None,
    pixel_tolerance: int = 0,
) -> tuple[Verdict, Any, Any]:
    if tier is Tier.DIMS:
        with Image.open(source) as im:
            got = recipe.geometry(*im.size)
        want = (entry["width"], entry["height"])
        return (Verdict.MATCH if got == want else Verdict.MISMATCH), got, want
    if tier is Tier.BYTES:
        got = hashlib.sha256(recipe.encode(source)).hexdigest()
        want = entry["sha256"]
        return (Verdict.MATCH if got == want else Verdict.MISMATCH), got[:12], str(want)[:12]
    assert mirror_root is not None  # narrowed by evaluate()
    reference = mirror_root / str(entry["path"])
    with Image.open(reference) as ref:
        want_im = ref.convert("RGB")
        want_im.load()
    got_im = recipe.render(source)
    if got_im.size != want_im.size:
        # Report the geometry miss rather than a meaningless channel delta.
        return Verdict.MISMATCH, got_im.size, want_im.size
    bands = ImageChops.difference(got_im, want_im).getextrema()
    worst = max(hi for _lo, hi in bands)
    return (
        Verdict.MATCH if worst <= pixel_tolerance else Verdict.MISMATCH,
        f"max_channel_delta={worst}",
        f"tolerance={pixel_tolerance}",
    )


def upscale_violations(recipe: Recipe, entries: Sequence[dict[str, Any]], sources: dict[str, Path]) -> list[int]:
    """media_ids this recipe would upscale. A rebuild candidate must return []."""
    out: list[int] = []
    for entry in entries:
        source = sources.get(entry.get("sha256_source", ""))
        if source is None:
            continue
        try:
            with Image.open(source) as im:
                if recipe.upscales(*im.size):
                    out.append(int(entry["media_id"]))
        except (OSError, ValueError):
            continue  # rg-007
    return out


def default_grid() -> list[Recipe]:
    """The candidate grid for tier 1. Geometry only — filter and quality do not
    move dimensions, so sweeping them here would multiply cost for no signal."""
    return [
        Recipe(
            name=f"cap{cap}_{'shrink' if shrink else 'force'}_{mode}_{'exact' if exact else 'float'}",
            cap=cap,
            rounding=mode,
            shrink_only=shrink,
            exact_ratio=exact,
        )
        for cap in (1280, 2560, 1024)
        for shrink in (True, False)
        for mode in sorted(ROUND_MODES)
        for exact in (True, False)
    ]


def sweep(
    entries: Sequence[dict[str, Any]],
    sources: dict[str, Path],
    recipes: Sequence[Recipe],
    tier: Tier = Tier.DIMS,
    mirror_root: Path | None = None,
    pixel_tolerance: int = 0,
) -> list[tuple[Recipe, TierResult]]:
    """Score every recipe, best first. Ties break on name for determinism."""
    scored = [
        (r, evaluate(r, entries, sources, tier, mirror_root, pixel_tolerance=pixel_tolerance))
        for r in recipes
    ]
    scored.sort(key=lambda pair: (-pair[1].matched, pair[0].name))
    return scored


def load_entries(manifest_path: Path) -> list[dict[str, Any]]:
    raw = json.loads(Path(manifest_path).read_text())
    entries = raw.get("entries", raw.get("items", []))
    if not entries:
        raise RecipeError(f"{manifest_path} carries no entries")
    return list(entries)


def characterize_residual(residual: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Summarise *how* a recipe misses, not just how often.

    A recipe that is off by one on the minor axis for 3% of a corpus is a
    rounding question; one that misses by 40% is a different rule. Collapsing
    both to a match count hides the distinction that decides the next move.
    """
    deltas: Counter[str] = Counter()
    buckets: Counter[str] = Counter()
    for item in residual:
        buckets[str(item.get("bucket"))] += 1
        got, want = item.get("got"), item.get("want")
        if isinstance(got, tuple) and isinstance(want, tuple) and len(got) == len(want) == 2:
            deltas[f"{got[0] - want[0]:+d},{got[1] - want[1]:+d}"] += 1
    return {
        "n": len(residual),
        "dim_deltas": dict(deltas.most_common()),
        "buckets": dict(buckets.most_common()),
        "off_by_one_only": bool(deltas) and all(
            max(abs(int(p)) for p in key.split(",")) == 1 for key in deltas
        ),
    }

def main(argv: Sequence[str] | None = None) -> int:
    """Sweep the candidate grid and print the ranking plus the residual.

    Exits non-zero when the best candidate would upscale anything, because a
    recipe that can upscale is disqualified as a rebuild candidate regardless
    of how well it fits the historical mirror.
    """
    import argparse

    ap = argparse.ArgumentParser(description="Recover the corpus downscale recipe.")
    ap.add_argument("--manifest", required=True, help="v3 corpus manifest (the oracle)")
    ap.add_argument("--source-root", action="append", required=True, dest="source_roots",
                    help="directory of original images; repeatable")
    ap.add_argument("--tier", choices=[t.value for t in Tier], default=Tier.DIMS.value)
    ap.add_argument("--mirror-root", help="reference downscaled tree; required for --tier pixels")
    ap.add_argument("--pixel-tolerance", type=int, default=0)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args(list(argv) if argv is not None else None)

    entries = load_entries(Path(args.manifest))
    wanted = {e["sha256_source"] for e in entries if e.get("sha256_source")}
    sources = build_source_index([Path(r) for r in args.source_roots], wanted)
    print(f"entries={len(entries)}  sources_resolved={len(sources)}/{len(wanted)}")

    tier = Tier(args.tier)
    mirror = Path(args.mirror_root) if args.mirror_root else None
    if tier is Tier.PIXELS and mirror is None:
        print("error: --tier pixels needs --mirror-root; the oracle is the mirror", file=sys.stderr)
        return 2

    ranked = sweep(entries, sources, default_grid(), tier, mirror, args.pixel_tolerance)
    print(f"\n{'recipe':<40}{'match':>7}{'miss':>7}{'err':>6}{'unavail':>9}{'rate':>8}")
    for recipe, r in ranked[: args.top]:
        rate = f"{r.rate:.3f}" if r.rate is not None else "n/a"
        print(f"{recipe.name:<40}{r.matched:>7}{r.mismatched:>7}{r.errored:>6}{r.unavailable:>9}{rate:>8}")

    best, _ = ranked[0]
    full = evaluate(best, entries, sources, tier, mirror, residual_cap=len(entries),
                    pixel_tolerance=args.pixel_tolerance)
    print(f"\nbest: {best.name}")
    print(f"provenance: {json.dumps(best.provenance(), sort_keys=True)}")
    print(f"residual: {json.dumps(characterize_residual(full.residual), sort_keys=True)}")

    violations = upscale_violations(best, entries, sources)
    if violations:
        print(f"\nREFUSED: {best.name} would upscale {len(violations)} entries: {violations[:20]}",
              file=sys.stderr)
        return 1
    print("\nupscale check: clean")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
