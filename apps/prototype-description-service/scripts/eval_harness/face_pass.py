"""Model-derived face counts for the people/faces/crowds strata (VLM-6 S1).

``corpus_inventory``'s only face signal is embedded XMP/MWG face regions. Those
exist on 2320 of 2327 celebs01 images but on just 219 uploads — roughly 6,400
uploads carry no face data whatsoever. Bucketing people/faces/crowds on XMP alone
therefore does not report "few people in the uploads"; it reports *nothing looked*,
while presenting the result in the same shape as a real signal. This pass closes
that gap by letting the remote recognition service look at a bounded, deterministic
slice of the uploads pool, recording one face count per image.

What the count is, precisely: faces the pipeline could EMBED. ``scan/service.py``
skips detections whose embedding is None, so the count is a LOWER BOUND on faces
present, and ``crowds`` means "3+ embeddable faces". Like every ``corpus_inventory``
feature this is a shortlisting signal the operator confirms, never ground truth.

Operational shape:

- **Bounded** (RES-05): ``--limit`` caps the pass; the pool is ~6,400 images and
  nothing here may grow to meet it.
- **Sequential** (one image per job by default): the live box serves the demo and
  is memory-pressured. This knowingly accepts a chatty remote interface (RES-12) —
  ``--batch`` raises it — because degrading the demo box costs more than wall-clock.
- **Idempotent** (RES-01, DATA-13): re-analyzing a media_id re-matches by bbox IoU
  and deletes orphaned rows (``scan/service.py`` step 6), so a resumed or retried
  item converges on the same count instead of accumulating duplicate faces.
- **Checkpointed** (AGT-10): rows stream to JSONL and flush per item, so a kill
  under memory pressure resumes rather than restarts.
- **Fail-closed on tenant** (``assert_scratch_tenant``): the pass WRITES face rows,
  so it must not run against the roster-seeded eval tenant.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Protocol

from scripts.eval_harness.cli import _extract_identities
from scripts.eval_harness.corpus_inventory import ImageRecord, dedupe_by_sha256, load_records
from scripts.eval_harness.strata import Source, is_eligible

# The analyze route funnels media ids through `_extract_media_id`, which keeps only
# the LAST SIX DIGITS (`int(digits[-6:])`). A 7-digit id is not rejected — it is
# silently truncated, so 1_000_000 becomes 0 and every image's faces collapse onto
# one row. Ids must stay <= 999_999; the base sits far above the golden manifest's
# ids (which continue from 39) so the two never share a row.
MEDIA_ID_BASE = 900_000
MEDIA_ID_CEILING = 999_999
DEFAULT_STALL_LIMIT = 5
DEFAULT_BATCH = 1


class SeededTenantError(Exception):
    """Target tenant holds labeled clusters — refusing to write face rows into it."""


class FacePassStalledError(RuntimeError):
    """Aborted after too many consecutive per-item failures (rg-007).

    Distinct from ``cli.BoundedStallError``, which carries a run-record dict: this
    pass's durable artifact is its JSONL checkpoint, so it names that instead of
    fabricating a run-record shape it does not produce (rg-015).
    """

    def __init__(self, message: str, checkpoint: Path, rows: Sequence[FacePassRow]) -> None:
        super().__init__(message)
        self.checkpoint = checkpoint
        self.rows = list(rows)


class FaceClient(Protocol):
    """The RemoteSceneClient surface this pass needs (TEST-04 seam: fake it in tests)."""

    def analyze(self, images: list[tuple[int, str, bytes]]) -> str: ...

    def wait_job(self, job_id: str) -> dict[str, Any]: ...

    def media_identities(self, media_ids: list[int]) -> Any: ...

    def clusters(self, labeled_only: bool = False) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class FacePassRow:
    sha256: str
    path: str
    source: str
    media_id: int
    face_count: int | None  # None iff the item errored
    names: list[str]
    error: str | None


def assert_scratch_tenant(client: FaceClient) -> None:
    """Refuse a tenant that has a curated roster.

    This pass persists MediaIdentity rows. Run against the roster-seeded eval
    tenant, the next clustering job would merge hundreds of stranger faces into
    labeled celeb clusters and silently corrupt the identification P/R baseline
    the whole bake-off reports. A labeled cluster is the roster's fingerprint, so
    its presence is the fail-closed signal — mirroring Provenance.is_publishable.
    """
    labeled = client.clusters(labeled_only=True)
    if labeled:
        raise SeededTenantError(
            f"target tenant has {len(labeled)} labeled cluster(s): this looks like the "
            "roster-seeded eval tenant, and this pass writes face rows that the next "
            "clustering run would merge into those labeled clusters, corrupting "
            "identification P/R. Point --tenant-id at a scratch tenant (POST /admin/tenants "
            "is upsert-by-id), or pass --force if you accept contaminating this roster."
        )


def select_candidates(
    rows: Iterable[tuple[ImageRecord, Source]],
    *,
    limit: int | None = None,
    sources: tuple[Source, ...] = (Source.LOCALWP_UPLOADS,),
    done_sha256: frozenset[str] = frozenset(),
) -> list[tuple[ImageRecord, Source]]:
    """The eligible images with no face signal at all, sampled representatively, bounded.

    Only records whose XMP face count is zero are candidates: an embedded face
    region is human/Apple-Photos-authored and beats a model count, so XMP wins
    where it exists and the model fills the silence.

    Ordered by sha256 — deliberately NOT strata's ``_diverse_order``. That function
    round-robins folders to maximize variety per image reviewed, which is right for
    a human browsing 200 images and wrong here. Round-robin gives every folder equal
    billing regardless of size, so on the real uploads tree a 142-image folder (2.4%
    of the pool) would claim a third of a bounded budget. This pass is a machine
    sampling a pool to find people at their base rate, so it wants a REPRESENTATIVE
    sample: content-hash order is uniformly distributed, so any prefix is
    proportional to folder size in expectation, deterministic, and stable across
    resumes — with no folder heuristics to keep in sync with the corpus.
    """
    pool = [
        (r, s)
        for r, s in rows
        if s in sources and r.xmp_face_count == 0 and r.sha256 not in done_sha256 and is_eligible(r)
    ]
    kept = {id(r) for r in dedupe_by_sha256([r for r, _ in pool])}
    pool = [(r, s) for r, s in pool if id(r) in kept]
    ordered = sorted(pool, key=lambda row: row[0].sha256)
    return ordered[:limit] if limit is not None else ordered


def assign_media_ids(
    candidates: Sequence[tuple[ImageRecord, Source]],
    *,
    existing: Mapping[str, int] = {},
) -> list[tuple[ImageRecord, Source, int]]:
    """Stable media id per image; ids already on the checkpoint are authoritative.

    Reusing a checkpoint's id keeps a resumed pass writing to the same server-side
    rows it wrote before (the re-analyze path then updates in place rather than
    stranding an orphan set under an id nothing will ever query again).
    """
    used = set(existing.values())
    out: list[tuple[ImageRecord, Source, int]] = []
    next_id = MEDIA_ID_BASE
    for record, source in candidates:
        media_id = existing.get(record.sha256)
        if media_id is None:
            while next_id in used:
                next_id += 1
            media_id = next_id
            used.add(media_id)
        if media_id > MEDIA_ID_CEILING:
            raise ValueError(
                f"media id {media_id} exceeds {MEDIA_ID_CEILING}: the analyze route truncates ids to "
                "their last 6 digits, so this would silently collide with another image's faces"
            )
        out.append((record, source, media_id))
    return out


_ROW_FIELDS = {f.name for f in fields(FacePassRow)}


def load_face_pass_rows(path: Path) -> list[FacePassRow]:
    """Read a checkpoint back. A truncated final line (killed mid-write) is dropped."""
    if not path.exists():
        return []
    rows: list[FacePassRow] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict) or set(raw) != _ROW_FIELDS:
            continue
        rows.append(FacePassRow(**raw))
    return rows


def load_face_counts(path: Path) -> dict[str, int]:
    """sha256 -> model face count, successful rows only.

    An errored row carries no count and must not read as "zero faces" — that would
    turn a network failure into the claim that an image has no people in it.
    """
    return {row.sha256: row.face_count for row in load_face_pass_rows(path) if row.error is None and row.face_count is not None}


def _append_row(handle: Any, row: FacePassRow) -> None:
    handle.write(json.dumps(asdict(row)) + "\n")
    handle.flush()  # checkpoint: a kill must not lose completed work


def write_rows(path: Path, rows: Iterable[FacePassRow]) -> None:
    with path.open("w") as handle:
        for row in rows:
            _append_row(handle, row)


def run_face_pass(
    candidates: Sequence[tuple[ImageRecord, Source, int]],
    client: FaceClient,
    *,
    roots: Mapping[Source, Path],
    out: Path,
    resume_rows: Sequence[FacePassRow] = (),
    stall_limit: int = DEFAULT_STALL_LIMIT,
    on_progress: Callable[[int, FacePassRow], None] | None = None,
) -> list[FacePassRow]:
    """Analyze each candidate, record its face count, checkpoint every row.

    Per-item failures are isolated and recorded (rg-007): one unreadable file or
    one 500 must not abandon the other 800 images. ``stall_limit`` consecutive
    failures aborts the pass — a dead tunnel or an expired key would otherwise
    write hundreds of identical error rows and call it a completed pass.
    """
    write_rows(out, resume_rows)  # drops any truncated tail before appending
    done = list(resume_rows)
    consecutive_failures = 0
    with out.open("a") as handle:
        for index, (record, source, media_id) in enumerate(candidates):
            try:
                image_path = roots[source] / record.path
                image_bytes = image_path.read_bytes()
                job_id = client.analyze([(media_id, image_path.name, image_bytes)])
                client.wait_job(job_id)
                names, face_count = _extract_identities(client.media_identities([media_id]), media_id)
                row = FacePassRow(
                    sha256=record.sha256,
                    path=record.path,
                    source=str(source),
                    media_id=media_id,
                    face_count=face_count,
                    names=names,
                    error=None,
                )
            except Exception as exc:  # noqa: BLE001 — per-item isolation is the contract
                row = FacePassRow(
                    sha256=record.sha256,
                    path=record.path,
                    source=str(source),
                    media_id=media_id,
                    face_count=None,
                    names=[],
                    error=f"{type(exc).__name__}: {exc}",
                )
            _append_row(handle, row)
            done.append(row)
            if on_progress is not None:
                on_progress(index, row)
            if row.error is None:
                consecutive_failures = 0
                continue
            consecutive_failures += 1
            if consecutive_failures >= stall_limit:
                raise FacePassStalledError(
                    f"{consecutive_failures} consecutive item failures (last error: {row.error}); "
                    f"aborting face pass — {len(done)} rows checkpointed to {out}",
                    out,
                    done,
                )
    return done


def summarize(rows: Sequence[FacePassRow]) -> dict[str, Any]:
    ok = [r for r in rows if r.error is None and r.face_count is not None]
    counts = [r.face_count for r in ok]
    return {
        "scanned": len(rows),
        "ok": len(ok),
        "errors": len(rows) - len(ok),
        "with_faces": sum(1 for c in counts if c >= 1),
        "crowds": sum(1 for c in counts if c >= 3),
        "faces_found": sum(counts),
    }


def _main(argv: Sequence[str] | None = None) -> int:
    from scripts.eval_harness.remote_client import RemoteSceneClient  # local: keeps import cost off test paths
    from scripts.eval_harness.strata import _parse_inventory_arg

    parser = argparse.ArgumentParser(description="Fill model face counts for images with no XMP face data.")
    parser.add_argument(
        "--inventory", action="append", required=True, type=_parse_inventory_arg, metavar="SOURCE=PATH"
    )
    parser.add_argument("--root", action="append", required=True, metavar="SOURCE=DIR", help="image root per source")
    parser.add_argument("--out", type=Path, required=True, help="JSONL checkpoint")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--tenant-id", required=True, help="a SCRATCH tenant; never the roster-seeded eval tenant")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stall-limit", type=int, default=DEFAULT_STALL_LIMIT)
    parser.add_argument("--force", action="store_true", help="run even if the tenant has labeled clusters")
    args = parser.parse_args(argv)

    roots: dict[Source, Path] = {}
    for value in args.root:
        source, _, path = value.partition("=")
        if not path:
            parser.error(f"expected <source>=<dir>, got: {value!r}")
        roots[Source(source)] = Path(path)

    rows: list[tuple[ImageRecord, Source]] = []
    for source, path in args.inventory:
        if not path.is_file():
            parser.error(f"inventory not found: {path}")
        if source not in roots:
            parser.error(f"no --root given for source {source}")
        rows.extend((record, source) for record in load_records(path))

    client = RemoteSceneClient(args.base_url, args.api_key, tenant_id=args.tenant_id)
    try:
        if not args.force:
            assert_scratch_tenant(client)
        resume_rows = load_face_pass_rows(args.out) if args.resume else []
        done_sha = frozenset(r.sha256 for r in resume_rows if r.error is None)
        candidates = select_candidates(rows, limit=args.limit, done_sha256=done_sha)
        with_ids = assign_media_ids(candidates, existing={r.sha256: r.media_id for r in resume_rows})
        print(f"{len(with_ids)} candidates (resumed {len(resume_rows)}) -> {args.out}", flush=True)

        def progress(index: int, row: FacePassRow) -> None:
            if (index + 1) % 25 == 0:
                print(f"  {index + 1}/{len(with_ids)} ...", flush=True)

        done = run_face_pass(
            with_ids,
            client,
            roots=roots,
            out=args.out,
            resume_rows=resume_rows,
            stall_limit=args.stall_limit,
            on_progress=progress,
        )
    except SeededTenantError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except FacePassStalledError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 3
    finally:
        client.close()

    summary = summarize(done)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
