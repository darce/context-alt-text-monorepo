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
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from scripts.eval_harness.corpus_inventory import ImageRecord, dedupe_by_sha256, load_records
from scripts.eval_harness.manifest import Domain


class Source(StrEnum):
    """Which root an inventory was scanned from. Governs identity + publishability."""

    CELEBS01 = "celebs01"
    LOCALWP_UPLOADS = "localwp_uploads"


class Confidence(StrEnum):
    """Whether an offline feature can decide the stratum, or a human must look."""

    OFFLINE = "offline"
    NEEDS_OPERATOR = "needs_operator"


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
    publishable: bool
    celeb_name: str | None


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


def celeb_label(record: ImageRecord, source: Source) -> str | None:
    """Identity label, or None. ONLY celebs01 filenames are identity labels.

    An uploads filename can parse as a plausible name while naming nobody (scraped
    social handles did exactly that), so the label is gated on the source root
    rather than on the parser's confidence.
    """
    return record.celeb_name if source is Source.CELEBS01 else None


def is_publishable(record: ImageRecord, source: Source) -> bool:
    """Fail-closed publishability: only the public-figure root publishes.

    The private-personal signal is the UPLOADS root, not the presence of an XMP
    name. celebs01 embeds a (noisy, partial) name on 2320/2327 of its images —
    "Al" for al_pacino — so treating any XMP name as personal would mark 99.7% of
    the publishable corpus unpublishable. Uploads are False regardless, which is
    what actually keeps the 219 named personal photos local-only.
    """
    return source is Source.CELEBS01


def _quantile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank quantile. No numpy; deterministic on ties."""
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(int(q * len(ordered)), len(ordered) - 1)
    return ordered[index]


def _domains_for(record: ImageRecord, source: Source, *, dense_edge_min: float | None) -> tuple[Domain, ...]:
    domains: list[Domain] = []
    if record.xmp_face_count >= 1:
        domains.append(Domain.PEOPLE)
    # celebs01 is a public-figure portrait set by construction; uploads need a face
    # region to prove a single face is present.
    if source is Source.CELEBS01 or record.xmp_face_count == 1:
        domains.append(Domain.FACES)
    if record.xmp_face_count >= CROWD_MIN_FACES:
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
    record: ImageRecord, source: Source, domains: tuple[Domain, ...], confidence: Confidence
) -> Candidate:
    return Candidate(
        path=record.path,
        sha256=record.sha256,
        source=source,
        strata=domains,
        confidence=confidence,
        publishable=is_publishable(record, source),
        celeb_name=celeb_label(record, source),
    )


# Per-stratum sort key: the feature that decided membership, most-confident first.
# Records whose deciding feature is None are dropped before ranking (an unreadable
# image has no feature to rank on), so these never see None.
_RANKERS = {
    Domain.BLACK_AND_WHITE: (lambda r: r.mean_saturation, False),
    Domain.LOW_LIGHT: (lambda r: r.mean_value, False),
    Domain.CHARTS: (lambda r: r.flat_color_coverage, True),
    Domain.DENSE_SCENE: (lambda r: r.edge_density, True),
    Domain.PEOPLE: (lambda r: r.xmp_face_count, True),
    Domain.CROWDS: (lambda r: r.xmp_face_count, True),
}


def _rank(domain: Domain, rows: list[tuple[ImageRecord, Source]]) -> list[tuple[ImageRecord, Source]]:
    if domain is Domain.FACES:
        return _rank_faces(rows)
    feature, descending = _RANKERS[domain]
    rankable = [row for row in rows if feature(row[0]) is not None]
    # Path breaks every tie so repeated runs emit byte-identical shortlists.
    rankable.sort(key=lambda row: row[0].path)
    rankable.sort(key=lambda row: feature(row[0]), reverse=descending)
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
) -> StrataReport:
    """Bucket a tagged inventory into ranked offline shortlists + an operator browse set."""
    rows = [(r, s) for r, s in records if r.sha256 not in exclude_sha256]
    # Dedupe across BOTH roots at once: the same bytes can sit in either.
    kept = {id(r) for r in dedupe_by_sha256([r for r, _ in rows])}
    rows = [(r, s) for r, s in rows if id(r) in kept]

    dense_edge_min = _quantile([r.edge_density for r, _ in rows if r.edge_density is not None], DENSE_EDGE_QUANTILE)

    buckets: dict[Domain, list[tuple[ImageRecord, Source]]] = {d: [] for d in OFFLINE_DOMAINS}
    domains_by_row: dict[int, tuple[Domain, ...]] = {}
    for record, source in rows:
        domains = _domains_for(record, source, dense_edge_min=dense_edge_min)
        domains_by_row[id(record)] = domains
        for domain in domains:
            buckets[domain].append((record, source))

    offline: dict[Domain, Shortlist] = {}
    for domain in OFFLINE_DOMAINS:
        ranked = _rank(domain, buckets[domain])
        offline[domain] = Shortlist(
            domain=domain,
            confidence=Confidence.OFFLINE,
            pool_size=len(ranked),
            candidates=[
                _to_candidate(r, s, domains_by_row[id(r)], Confidence.OFFLINE) for r, s in ranked[:per_stratum]
            ],
        )

    browse_pool = [row for row in rows if row[1] in operator_sources]
    browse = _diverse_order(browse_pool)[:operator_sample]
    operator_review = Shortlist(
        domain=Domain.ABSTRACT,  # nominal anchor; the set serves every OPERATOR_DOMAINS member
        confidence=Confidence.NEEDS_OPERATOR,
        pool_size=len(browse_pool),
        candidates=[_to_candidate(r, s, domains_by_row[id(r)], Confidence.NEEDS_OPERATOR) for r, s in browse],
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
        "publishable": candidate.publishable,
        "celeb_name": candidate.celeb_name,
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
    args = parser.parse_args(argv)

    rows: list[tuple[ImageRecord, Source]] = []
    for source, path in args.inventory:
        if not path.is_file():
            parser.error(f"inventory not found: {path}")
        rows.extend(load_inventory(path, source))

    report = build_report(rows, per_stratum=args.per_stratum, operator_sample=args.operator_sample)
    args.out.write_text(json.dumps(report_json(report), indent=2))

    print(f"pool {report.pool_size} images -> {args.out}")
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


if __name__ == "__main__":
    sys.exit(_main())
