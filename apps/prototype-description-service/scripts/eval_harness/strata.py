"""Strata bucketing + operator shortlists for Golden-150 selection (VLM-6 S1).

Turns a raw ``corpus_inventory`` scan of ~9,600 images into per-stratum candidate
lists so the operator picks ~112 additions by reviewing tens of images per stratum
instead of thousands.

The strata split by what a pixel statistic can actually decide:

- **Offline strata** (``Confidence.OFFLINE``) — black-and-white, low-light, charts,
  dense-scene, faces/people/crowds. A feature decides membership, so each gets a
  RANKED shortlist, most-confident first.
- **Operator strata** (``Confidence.NEEDS_OPERATOR``) — mirrors, occlusion, art,
  abstract, animals, products, text-in-image. No offline signal exists for these:
  no pixel statistic sees a mirror. They share ONE deterministic diverse browse set
  rather than getting a fake per-stratum ranking. Dealing each of them a different
  slice would be worse than useless — if every mirror landed outside the mirror
  slice the operator would never see one.

Nothing here is ground truth: bucketing is a shortlisting aid and the operator
confirms every stratum. No ML, no network, fully deterministic.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from scripts.eval_harness.corpus_inventory import FEATURE_EDGE_PX, ImageRecord, dedupe_by_sha256, load_records
from scripts.eval_harness.manifest import Domain, GoldenEntry, SliceTag


class Source(StrEnum):
    """Which root an inventory was scanned from. Governs identity + publishability."""

    CELEBS01 = "celebs01"
    LOCALWP_UPLOADS = "localwp_uploads"


class Confidence(StrEnum):
    """Whether an offline feature can decide the stratum, or a human must look."""

    OFFLINE = "offline"
    NEEDS_OPERATOR = "needs_operator"


class FaceCountSource(StrEnum):
    """Which signal produced an image's face count. Neither is ground truth.

    Recorded per candidate because the two are not interchangeable: XMP is a
    human/Apple-Photos-authored face region, while MODEL is the recognition
    pipeline's embeddable-face count (a lower bound). An operator reviewing a
    ``crowds`` candidate needs to know which one put it there. NONE means nothing
    looked at this image — distinct from a model that looked and found zero.
    """

    XMP = "xmp"
    MODEL = "model"
    NONE = "none"


# An image whose short edge is under this is not Golden-150 material. The floor is
# corpus_inventory's own FEATURE_EDGE_PX: below it, an image is smaller than the
# window every stratification feature is computed in. It also lands in a real gap in
# the corpus — min-edge jumps from 88px (p2) to 387px (p3) — because everything under
# it is derived face crops rather than photographs.
MIN_CORPUS_EDGE_PX = FEATURE_EDGE_PX  # imported from corpus_inventory, not a drifting literal
# Three or more faces reads as a crowd rather than a group portrait.
CROWD_MIN_FACES = 3
# Dense-scene membership is relative: the busiest quartile of the actual pool.
DENSE_EDGE_QUANTILE = 0.75
# Plan requires >=5 images per stratum; thinner pools are surfaced, never silent.
MIN_STRATUM_POOL = 5

OFFLINE_DOMAINS: tuple[Domain, ...] = (
    Domain.PEOPLE,
    Domain.FACES,
    Domain.CROWDS,
    Domain.BLACK_AND_WHITE,
    Domain.LOW_LIGHT,
    Domain.CHARTS,
    Domain.DENSE_SCENE,
)
# Semantic strata: a mirror, a painting and an occluded face are invisible to every
# statistic this harness computes offline.
OPERATOR_DOMAINS: tuple[Domain, ...] = (
    Domain.OCCLUSION,
    Domain.MIRRORS,
    Domain.ANIMALS,
    Domain.ART,
    Domain.ABSTRACT,
    Domain.TEXT_IN_IMAGE,
    Domain.PRODUCTS,
)
# The hard/semantic strata are sourced from the uploads root by operator directive:
# celebs01 is the identification set, and a single-face publicity portrait is never
# a mirror, a product shot or an abstract. Drawing the browse set from every root
# let celebs' 111 identity groups outvote uploads' ~20 folders 196:4 — a browse set
# that was 98% portraits for strata that contain no portraits.
OPERATOR_SOURCES: tuple[Source, ...] = (Source.LOCALWP_UPLOADS,)


@dataclass(frozen=True)
class Candidate:
    path: str
    sha256: str
    source: Source
    strata: tuple[Domain, ...]
    confidence: Confidence
    # Curation HINT only (the scan root is the public-figure set); the authoritative
    # publishability gate is manifest.Provenance.is_publishable, not this flag (F-02).
    public_figure_root: bool
    celeb_name: str | None
    face_count: int
    face_count_source: FaceCountSource


@dataclass(frozen=True)
class Shortlist:
    domain: Domain
    confidence: Confidence
    pool_size: int  # every record matching the stratum, before truncation
    candidates: list[Candidate]

    @property
    def thin(self) -> bool:
        return self.pool_size < MIN_STRATUM_POOL


@dataclass(frozen=True)
class StrataReport:
    offline: dict[Domain, Shortlist]
    operator_review: Shortlist  # one shared browse set serving OPERATOR_DOMAINS
    operator_domains: tuple[Domain, ...]
    pool_size: int

    def thin_domains(self) -> list[Domain]:
        return [d for d, s in self.offline.items() if s.thin]


def load_inventory(path: Path, source: Source) -> list[tuple[ImageRecord, Source]]:
    """Read a checkpoint JSONL and tag every record with the root it came from."""
    return [(record, source) for record in load_records(path)]


def entries_with_slice_tag(entries: list[GoldenEntry], tag: SliceTag) -> list[GoldenEntry]:
    """Return GoldenEntry rows that carry ``tag`` in their FIR-5 slice tags.

    Slice rollups bind to ``SliceTag``, never ``Domain.OCCLUSION`` (FIR-5 contract).
    """
    return [entry for entry in entries if tag in entry.tags]


def is_eligible(record: ImageRecord) -> bool:
    """Whether an image can be Golden-150 material at all — before any stratum.

    Excludes unreadable files and anything under the resolution floor. This is not a
    stratum decision but an eligibility one, so it is applied to the pool rather than
    left to the operator: the uploads tree carries 217 ~80x112 face crops emitted by
    the plugin, which are derivatives of photos already in the corpus, are trivially
    "one face", and cannot be fairly described by any captioning model under test.

    Left in they were not merely inert. Round-robin gives a folder equal billing
    regardless of size, so a folder holding 3.5% of the pool took 25% of the
    operator's 200-image browse set, and would have taken a comparable slice of the
    face pass's bounded remote budget.
    """
    if record.width is None or record.height is None:
        return False
    return min(record.width, record.height) >= MIN_CORPUS_EDGE_PX


def celeb_label(record: ImageRecord, source: Source) -> str | None:
    """Identity label, or None. ONLY celebs01 filenames are identity labels.

    An uploads filename can parse as a plausible name while naming nobody (scraped
    social handles did exactly that), so the label is gated on the source root
    rather than on the parser's confidence.
    """
    return record.celeb_name if source is Source.CELEBS01 else None


def is_public_figure_root(record: ImageRecord, source: Source) -> bool:
    """Curation HINT: True iff the image was scanned from the public-figure root.

    This is a shortlist convenience flag, NOT the publishability authority — the
    authoritative gate is manifest.Provenance.is_publishable, which fails closed on
    private sources. Keeping the two separate (and this one named for what it is)
    prevents the drift where a shortlist "publishable:true" disagrees with the report
    gate. The private-personal signal is the UPLOADS root, not the presence of an XMP
    name: celebs01 embeds a (noisy, partial) name on 2320/2327 of its images — "Al"
    for al_pacino — so treating any XMP name as personal would mark 99.7% of the
    public-figure corpus non-public. Uploads are False regardless.
    """
    return source is Source.CELEBS01


def face_count_of(record: ImageRecord, face_counts: Mapping[str, int]) -> tuple[int, FaceCountSource]:
    """Effective face count + which signal decided it. XMP wins where it exists.

    An embedded face region was authored by a human (or Apple Photos) and beats a
    model's count, so ``face_pass`` only ever looks at images whose XMP count is
    zero and the two sources never disagree over one image.

    An image absent from ``face_counts`` scores 0/NONE — nothing looked at it. That
    is deliberately indistinguishable from "zero faces" for BUCKETING (both are
    excluded from people), but the source label keeps the distinction legible: a
    strata report where people is full of NONE is reporting an unrun pass, not an
    empty corpus.
    """
    if record.xmp_face_count > 0:
        return record.xmp_face_count, FaceCountSource.XMP
    model = face_counts.get(record.sha256)
    if model is None:
        return 0, FaceCountSource.NONE
    return model, FaceCountSource.MODEL


def _quantile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank quantile. No numpy; deterministic on ties."""
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(int(q * len(ordered)), len(ordered) - 1)
    return ordered[index]


def _domains_for(
    record: ImageRecord, source: Source, *, dense_edge_min: float | None, face_count: int
) -> tuple[Domain, ...]:
    domains: list[Domain] = []
    if face_count >= 1:
        domains.append(Domain.PEOPLE)
    # celebs01 is a public-figure portrait set by construction; uploads need a
    # detected/annotated face to prove a single face is present.
    if source is Source.CELEBS01 or face_count == 1:
        domains.append(Domain.FACES)
    if face_count >= CROWD_MIN_FACES:
        domains.append(Domain.CROWDS)
    if record.bw_candidate:
        domains.append(Domain.BLACK_AND_WHITE)
    if record.low_light_candidate:
        domains.append(Domain.LOW_LIGHT)
    if record.flat_color_candidate:
        domains.append(Domain.CHARTS)
    if (
        dense_edge_min is not None
        and record.edge_density is not None
        and record.edge_density >= dense_edge_min
        and not record.flat_color_candidate
    ):
        domains.append(Domain.DENSE_SCENE)
    return tuple(domains)


def _to_candidate(
    record: ImageRecord,
    source: Source,
    domains: tuple[Domain, ...],
    confidence: Confidence,
    face_counts: Mapping[str, int],
) -> Candidate:
    face_count, face_count_source = face_count_of(record, face_counts)
    return Candidate(
        path=record.path,
        sha256=record.sha256,
        source=source,
        strata=domains,
        confidence=confidence,
        public_figure_root=is_public_figure_root(record, source),
        celeb_name=celeb_label(record, source),
        face_count=face_count,
        face_count_source=face_count_source,
    )


# Per-stratum sort key: the feature that decided membership, most-confident first.
# Records whose deciding feature is None are dropped before ranking (an unreadable
# image has no feature to rank on), so these never see None. Every ranker takes the
# effective-face-count lookup as its second argument, so the face strata rank on the
# same number that decided their membership rather than on XMP alone.
_RANKERS: dict[Domain, tuple[Callable[[ImageRecord, Callable[[ImageRecord], int]], float | None], bool]] = {
    Domain.BLACK_AND_WHITE: (lambda r, _fc: r.mean_saturation, False),
    Domain.LOW_LIGHT: (lambda r, _fc: r.mean_value, False),
    Domain.CHARTS: (lambda r, _fc: r.flat_color_coverage, True),
    Domain.DENSE_SCENE: (lambda r, _fc: r.edge_density, True),
    Domain.PEOPLE: (lambda r, fc: fc(r), True),
    Domain.CROWDS: (lambda r, fc: fc(r), True),
}


def _rank(
    domain: Domain, rows: list[tuple[ImageRecord, Source]], face_count: Callable[[ImageRecord], int]
) -> list[tuple[ImageRecord, Source]]:
    if domain is Domain.FACES:
        return _rank_faces(rows)
    feature, descending = _RANKERS[domain]
    rankable = [row for row in rows if feature(row[0], face_count) is not None]
    # Path breaks every tie so repeated runs emit byte-identical shortlists.
    rankable.sort(key=lambda row: row[0].path)
    rankable.sort(key=lambda row: feature(row[0], face_count), reverse=descending)
    return rankable


def _rank_faces(rows: list[tuple[ImageRecord, Source]]) -> list[tuple[ImageRecord, Source]]:
    """Publishable public figures first, spread across distinct identities.

    Face count cannot rank this stratum: membership means "exactly one face", so the
    count is 1 for every non-celebs member and sorting on it is noise. Worse,
    descending count floats the highest-face-count images to the top of a
    SINGLE-face stratum — it put zero public figures in the top 40 of the real
    corpus, starving the very stratum that feeds identification P/R.

    Plain path order then fails the other way: it returned 40 photos of Al Pacino,
    one figure out of 111. Identification P/R needs distinct people, so the celebs
    are round-robined by identity.
    """
    celebs = [row for row in rows if row[1] is Source.CELEBS01]
    others = [row for row in rows if row[1] is not Source.CELEBS01]
    return _diverse_order(celebs) + _diverse_order(others)


def _group_key(record: ImageRecord, source: Source) -> str:
    """The axis a browse set spreads across: identity for celebs, folder for uploads.

    celebs01 is one flat directory, so a folder key collapses all 2327 images into a
    single group and yields no spread at all — the shortlist came back as 40 photos
    of Al Pacino. Its real axis of variety is the person.
    """
    if source is Source.CELEBS01 and record.celeb_name:
        return f"{source}/{record.celeb_name}"
    return f"{source}/{Path(record.path).parent}"


def _diverse_order(rows: list[tuple[ImageRecord, Source]]) -> list[tuple[ImageRecord, Source]]:
    """Round-robin across groups, so a browse set spans the corpus.

    A path-sorted head would return one folder — the operator would review 40 images
    from a single upload month and see none of the corpus's actual variety.
    """
    groups: dict[str, list[tuple[ImageRecord, Source]]] = defaultdict(list)
    for row in rows:
        groups[_group_key(row[0], row[1])].append(row)
    for group in groups.values():
        group.sort(key=lambda row: row[0].path)
    ordered: list[tuple[ImageRecord, Source]] = []
    for depth in range(max((len(g) for g in groups.values()), default=0)):
        for key in sorted(groups):
            if depth < len(groups[key]):
                ordered.append(groups[key][depth])
    return ordered


def build_report(
    records: Iterable[tuple[ImageRecord, Source]],
    *,
    per_stratum: int = 40,
    operator_sample: int = 200,
    operator_sources: tuple[Source, ...] = OPERATOR_SOURCES,
    exclude_sha256: frozenset[str] = frozenset(),
    face_counts: Mapping[str, int] = {},
) -> StrataReport:
    """Bucket a tagged inventory into ranked offline shortlists + an operator browse set.

    ``face_counts`` (sha256 -> model face count, from ``face_pass``) fills the face
    signal for images carrying no XMP regions. Without it the people/faces/crowds
    strata see only the 2320 celebs01 + 219 uploads that happen to have embedded
    face data, and report the other ~6,400 uploads as peopleless.
    """
    rows = [(r, s) for r, s in records if r.sha256 not in exclude_sha256 and is_eligible(r)]
    # Dedupe across BOTH roots at once: the same bytes can sit in either. Prefer the
    # celebs01 copy on a cross-root collision so identical bytes keep their public-figure
    # label regardless of --inventory argument order (stable sort leaves within-source
    # order untouched; the kept filter then preserves the original row order).
    dedup_order = sorted(rows, key=lambda rs: 0 if rs[1] is Source.CELEBS01 else 1)
    kept = {id(r) for r in dedupe_by_sha256([r for r, _ in dedup_order])}
    rows = [(r, s) for r, s in rows if id(r) in kept]

    dense_edge_min = _quantile([r.edge_density for r, _ in rows if r.edge_density is not None], DENSE_EDGE_QUANTILE)
    face_count_by_record: dict[str, int] = {r.sha256: face_count_of(r, face_counts)[0] for r, _ in rows}

    def face_count(record: ImageRecord) -> int:
        return face_count_by_record[record.sha256]

    buckets: dict[Domain, list[tuple[ImageRecord, Source]]] = {d: [] for d in OFFLINE_DOMAINS}
    domains_by_row: dict[int, tuple[Domain, ...]] = {}
    for record, source in rows:
        domains = _domains_for(record, source, dense_edge_min=dense_edge_min, face_count=face_count(record))
        domains_by_row[id(record)] = domains
        for domain in domains:
            buckets[domain].append((record, source))

    offline: dict[Domain, Shortlist] = {}
    for domain in OFFLINE_DOMAINS:
        ranked = _rank(domain, buckets[domain], face_count)
        offline[domain] = Shortlist(
            domain=domain,
            confidence=Confidence.OFFLINE,
            pool_size=len(ranked),
            candidates=[
                _to_candidate(r, s, domains_by_row[id(r)], Confidence.OFFLINE, face_counts)
                for r, s in ranked[:per_stratum]
            ],
        )

    browse_pool = [row for row in rows if row[1] in operator_sources]
    browse = _diverse_order(browse_pool)[:operator_sample]
    operator_review = Shortlist(
        domain=Domain.ABSTRACT,  # nominal anchor; the set serves every OPERATOR_DOMAINS member
        confidence=Confidence.NEEDS_OPERATOR,
        pool_size=len(browse_pool),
        candidates=[
            _to_candidate(r, s, domains_by_row[id(r)], Confidence.NEEDS_OPERATOR, face_counts) for r, s in browse
        ],
    )
    return StrataReport(
        offline=offline,
        operator_review=operator_review,
        operator_domains=OPERATOR_DOMAINS,
        pool_size=len(rows),
    )


def _candidate_json(candidate: Candidate) -> dict:
    return {
        "path": candidate.path,
        "sha256": candidate.sha256,
        "source": str(candidate.source),
        "strata": [str(d) for d in candidate.strata],
        "confidence": str(candidate.confidence),
        "public_figure_root": candidate.public_figure_root,
        "celeb_name": candidate.celeb_name,
        "face_count": candidate.face_count,
        "face_count_source": str(candidate.face_count_source),
    }


def report_json(report: StrataReport) -> dict:
    return {
        "pool_size": report.pool_size,
        "offline": {
            str(domain): {
                "confidence": str(shortlist.confidence),
                "pool_size": shortlist.pool_size,
                "thin": shortlist.thin,
                "candidates": [_candidate_json(c) for c in shortlist.candidates],
            }
            for domain, shortlist in report.offline.items()
        },
        "operator_review": {
            "serves_domains": [str(d) for d in report.operator_domains],
            "confidence": str(report.operator_review.confidence),
            "pool_size": report.operator_review.pool_size,
            "candidates": [_candidate_json(c) for c in report.operator_review.candidates],
        },
    }


def _parse_inventory_arg(value: str) -> tuple[Source, Path]:
    source, _, path = value.partition("=")
    if not path:
        raise argparse.ArgumentTypeError(f"expected <source>=<path.jsonl>, got: {value!r}")
    try:
        return Source(source), Path(path)
    except ValueError:
        choices = ", ".join(str(s) for s in Source)
        raise argparse.ArgumentTypeError(f"unknown source {source!r}; expected one of: {choices}") from None


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bucket a corpus inventory into per-stratum shortlists.")
    parser.add_argument(
        "--inventory",
        action="append",
        required=True,
        type=_parse_inventory_arg,
        metavar="SOURCE=PATH",
        help="repeatable, e.g. celebs01=inv.jsonl",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-stratum", type=int, default=40)
    parser.add_argument("--operator-sample", type=int, default=200)
    parser.add_argument(
        "--face-counts",
        type=Path,
        default=None,
        help="face_pass JSONL checkpoint; without it the face strata see XMP only",
    )
    args = parser.parse_args(argv)

    rows: list[tuple[ImageRecord, Source]] = []
    for source, path in args.inventory:
        if not path.is_file():
            parser.error(f"inventory not found: {path}")
        rows.extend(load_inventory(path, source))

    face_counts: dict[str, int] = {}
    if args.face_counts is not None:
        if not args.face_counts.is_file():
            parser.error(f"face counts not found: {args.face_counts}")
        from scripts.eval_harness.face_pass import load_face_counts  # local: avoids an import cycle

        face_counts = load_face_counts(args.face_counts)

    report = build_report(
        rows, per_stratum=args.per_stratum, operator_sample=args.operator_sample, face_counts=face_counts
    )
    args.out.write_text(json.dumps(report_json(report), indent=2))

    print(f"pool {report.pool_size} images -> {args.out}")
    unlooked = sum(1 for r, _ in rows if face_count_of(r, face_counts)[1] is FaceCountSource.NONE)
    if unlooked:
        # Loud by default: the face strata below are the one place where "no signal"
        # and "no people" render identically, and only this line tells them apart.
        print(
            f"WARNING: {unlooked}/{len(rows)} images have NO face signal (no XMP regions, no face_pass "
            "row) and count as 0 faces; people/faces/crowds below are provisional until face_pass covers them",
            file=sys.stderr,
        )
    print(f"{'domain':<18} {'confidence':<15} {'pool':>6} {'listed':>7}")
    for domain, shortlist in report.offline.items():
        flag = "  <- THIN" if shortlist.thin else ""
        print(f"{domain:<18} {shortlist.confidence:<15} {shortlist.pool_size:>6} {len(shortlist.candidates):>7}{flag}")
    served = ", ".join(str(d) for d in report.operator_domains)
    print(
        f"{'operator_review':<18} {Confidence.NEEDS_OPERATOR:<15} {report.operator_review.pool_size:>6} "
        f"{len(report.operator_review.candidates):>7}  serves: {served}"
    )
    for domain in report.thin_domains():
        print(
            f"WARNING: stratum {domain} has {report.offline[domain].pool_size} candidates, "
            f"below the {MIN_STRATUM_POOL}-image floor",
            file=sys.stderr,
        )
    return 0


# --- Sealed eval split (VLM-6 S1 / EVAL-07 / MLDATA-09 / EVAL-10) -------------
# Keyed by image CONTENT hash so later-procured images get a half at ingestion
# with no human choosing. The RULE is frozen; membership is derived from it.

ASSIGNMENT_RULE = "hmac-sha256(seed, image_sha256)[:8]/2**64 < held_out_fraction"
SUPPORTED_SPLIT_SCHEMA_VERSION = 1
SPLIT_PROTECTION = (
    "forward-from-draw-timestamp: any image, identity or curation decision first "
    "observed after draw_timestamp is protected by this split; entries listed in "
    "pre_split_exposure were already exposed"
)
SPLIT_DISJOINTNESS_NOTE = (
    "identity labels are per-image, not per-cluster; a person in both halves means "
    "their images were split by content hash — acceptable for description eval, "
    "must be resolved (move to train) before any face-identification eval uses held_out"
)
SPLIT_PARTITION_PROVENANCE = "pre-audit, buffalo-derived merge-only"


class SplitHalf(StrEnum):
    """Which sealed-split half an image belongs to (sr-007)."""

    HELD_OUT = "held_out"
    TRAIN = "train"


def assign_split(sha256: str, *, seed: str, held_out_fraction: float) -> SplitHalf:
    """Assign an image to a half from hmac(seed, content-sha256). Accepts closed [0, 1]."""
    digest = hmac.new(seed.encode(), sha256.lower().encode(), hashlib.sha256).digest()
    bucket = int.from_bytes(digest[:8], "big")
    if bucket / 2**64 < held_out_fraction:
        return SplitHalf.HELD_OUT
    return SplitHalf.TRAIN


def _half_payload(entries: Sequence[GoldenEntry]) -> dict:
    return {
        "media_ids": sorted(entry.media_id for entry in entries),
        "sha256": sorted(entry.sha256 for entry in entries),
        "identities": sorted({ident for entry in entries for ident in entry.present_identities}),
    }


def _identities_spanning_both_halves(held_out: Sequence[GoldenEntry], train: Sequence[GoldenEntry]) -> list[str]:
    held_ids = {ident for entry in held_out for ident in entry.present_identities}
    train_ids = {ident for entry in train for ident in entry.present_identities}
    return sorted(held_ids & train_ids)


def _partition_entries(manifest, *, seed: str, held_out_fraction: float) -> tuple[list[GoldenEntry], list[GoldenEntry]]:
    held_out: list[GoldenEntry] = []
    train: list[GoldenEntry] = []
    for entry in manifest.entries:
        half = assign_split(entry.sha256, seed=seed, held_out_fraction=held_out_fraction)
        if half is SplitHalf.HELD_OUT:
            held_out.append(entry)
        else:
            train.append(entry)
    return held_out, train


def draw_eval_split(
    manifest,
    *,
    seed: str,
    held_out_fraction: float,
    draw_timestamp: str,
    source_manifest_path: str,
    source_manifest_sha256: str,
    pre_split_exposure: list[str],
) -> dict:
    """Freeze a sealed eval split derived from image content hashes."""
    held_out, train = _partition_entries(manifest, seed=seed, held_out_fraction=held_out_fraction)
    return {
        "schema_version": SUPPORTED_SPLIT_SCHEMA_VERSION,
        "seed": seed,
        "held_out_fraction": held_out_fraction,
        "assignment_rule": ASSIGNMENT_RULE,
        "draw_timestamp": draw_timestamp,
        "protection": SPLIT_PROTECTION,
        "source_manifest": {"path": source_manifest_path, "sha256": source_manifest_sha256},
        "pre_split_exposure": list(pre_split_exposure),
        "held_out": _half_payload(held_out),
        "train": _half_payload(train),
        "disjointness": {
            "status": "provisional",
            "partition_provenance": SPLIT_PARTITION_PROVENANCE,
            "identities_spanning_both_halves": _identities_spanning_both_halves(held_out, train),
            "note": SPLIT_DISJOINTNESS_NOTE,
        },
    }


def verify_eval_split(artifact: dict, manifest) -> list[str]:
    """Recompute every entry's half; return human-readable violations (empty = OK)."""
    violations: list[str] = []
    schema_version = artifact.get("schema_version")
    if schema_version != SUPPORTED_SPLIT_SCHEMA_VERSION:
        violations.append(f"unsupported schema_version: {schema_version!r}")
    if artifact.get("assignment_rule") != ASSIGNMENT_RULE:
        violations.append(f"unsupported assignment_rule: {artifact.get('assignment_rule')!r}")

    held = artifact.get("held_out") or {}
    train = artifact.get("train") or {}
    held_ids = set(held.get("media_ids") or [])
    train_ids = set(train.get("media_ids") or [])
    held_shas = set(held.get("sha256") or [])
    train_shas = set(train.get("sha256") or [])

    both_ids = sorted(held_ids & train_ids)
    if both_ids:
        violations.append(f"media_id in both halves: {both_ids}")
    both_shas = sorted(held_shas & train_shas)
    if both_shas:
        violations.append(f"sha256 in both halves: {both_shas}")

    manifest_ids = {entry.media_id for entry in manifest.entries}
    neither = sorted(manifest_ids - held_ids - train_ids)
    if neither:
        violations.append(f"media_id in manifest but in neither half: {neither}")

    seed = artifact.get("seed")
    fraction = artifact.get("held_out_fraction")
    if isinstance(seed, str) and isinstance(fraction, (int, float)) and not isinstance(fraction, bool):
        expected_held, expected_train = _partition_entries(manifest, seed=seed, held_out_fraction=float(fraction))
        expected_held_ids = {entry.media_id for entry in expected_held}
        expected_train_ids = {entry.media_id for entry in expected_train}
        for media_id in sorted(expected_held_ids - held_ids):
            violations.append(f"membership mismatch: media_id {media_id} recomputes held_out but is not in held_out")
        for media_id in sorted(expected_train_ids - train_ids):
            violations.append(f"membership mismatch: media_id {media_id} recomputes train but is not in train")
        for media_id in sorted((held_ids - expected_held_ids) & manifest_ids):
            violations.append(f"membership mismatch: media_id {media_id} is in held_out but recomputes train")
        for media_id in sorted((train_ids - expected_train_ids) & manifest_ids):
            violations.append(f"membership mismatch: media_id {media_id} is in train but recomputes held_out")
        expected_span = _identities_spanning_both_halves(expected_held, expected_train)
        recorded_span = list((artifact.get("disjointness") or {}).get("identities_spanning_both_halves") or [])
        if recorded_span != expected_span:
            violations.append(
                f"identities_spanning_both_halves drifted: recorded={recorded_span} recomputed={expected_span}"
            )
    return violations


if __name__ == "__main__":
    sys.exit(_main())
