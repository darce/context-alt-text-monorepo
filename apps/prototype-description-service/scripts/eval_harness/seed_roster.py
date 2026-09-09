"""Idempotent eval-tenant roster seeding.

One-time setup so identification-level scoring has server-side ground truth:
ingest the entity crops (`entity-<name>*` files), run a clustering job, then
label the resulting clusters with the entity names. Labeling a cluster via
PATCH /recognition/clusters/{id} sets ``user_confirmed`` server-side
(cluster_mutations: ``user_confirmed = bool(label)``) — the same operation the
WP roster sync performs. Safe to re-run: if every roster name already has a
labeled cluster, nothing is uploaded or mutated.

Crops get synthetic media_ids starting at CROP_MEDIA_ID_BASE so they can never
collide with golden-manifest scene ids (1..38) and so clusters can be mapped
back to a single person via member media_ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ._pathtext import _printable_path
from .manifest import ManifestError, _resolve_image, load_manifest
from .naming import IMAGE_EXTS, display_name, entity_slug
from .remote_client import RemoteClientError

CROP_MEDIA_ID_BASE = 1001

_LABEL_CONFLICT_STATUS = 409


class SeedClient(Protocol):
    def analyze(self, images: list[tuple[int, str, bytes]]) -> str: ...
    def wait_job(self, job_id: str) -> dict[str, Any]: ...
    def clustering_job(self, tenant_id: str, mode: str = "sync") -> dict[str, Any]: ...
    def clusters(self, labeled_only: bool = False) -> list[dict[str, Any]]: ...
    def cluster_members(self, cluster_id: str) -> dict[str, Any]: ...
    def patch_cluster(self, cluster_id: str, tenant_id: str, label: str) -> Any: ...


@dataclass(frozen=True)
class SeedSummary:
    roster: list[str]
    already_labeled: dict[str, str] = field(default_factory=dict)
    labeled: dict[str, str] = field(default_factory=dict)
    skipped_ambiguous: dict[str, list[str]] = field(default_factory=dict)
    skipped_conflict: dict[str, str] = field(default_factory=dict)
    unlabeled_roster_names: list[str] = field(default_factory=list)


def _load_crops(entities_dir: Path) -> list[tuple[int, str, bytes, str]]:
    """(media_id, filename, bytes, display_name) per crop, name-sorted for stable ids."""
    crops = []
    files = sorted(
        (p for p in entities_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS),
        key=lambda p: p.name,
    )
    for offset, path in enumerate(files):
        name = display_name(entity_slug(path.name))
        crops.append((CROP_MEDIA_ID_BASE + offset, path.name, path.read_bytes(), name))
    return crops


def seed(entities_dir: str, client: SeedClient, *, tenant_id: str) -> SeedSummary:
    root = Path(entities_dir)
    if not root.is_dir():
        raise ManifestError(
            f"entities dir not found: {_printable_path(root)} — set GOLDEN_IMAGES_DIR and pass "
            "<GOLDEN_IMAGES_DIR>/mock_entities (see scene/tests/seed/README.md)"
        )
    crops = _load_crops(root)
    if not crops:
        raise ManifestError(f"no entity crops found under {_printable_path(root)}")
    roster = sorted({name for _, _, _, name in crops})

    existing = {str(c["id"]): str(c["label"]) for c in client.clusters(labeled_only=True) if c.get("label")}
    existing_names = set(existing.values())
    if all(name in existing_names for name in roster):
        return SeedSummary(roster=roster, already_labeled=existing)

    job_id = client.analyze([(m, f, b) for m, f, b, _ in crops])
    client.wait_job(job_id)
    client.clustering_job(tenant_id, mode="sync")

    media_to_name = {m: name for m, _, _, name in crops}
    labeled: dict[str, str] = {}
    skipped: dict[str, list[str]] = {}
    conflicts: dict[str, str] = {}
    for cluster in client.clusters():
        cluster_id = str(cluster["id"])
        if cluster.get("label"):
            continue
        envelope = client.cluster_members(cluster_id)
        names = sorted(
            {
                media_to_name[int(member["media_id"])]
                for member in envelope.get("members", [])
                if int(member.get("media_id", -1)) in media_to_name
            }
        )
        if len(names) == 1:
            # Only a genuine 409 label conflict is a per-cluster skip: the name is
            # already covered by another cluster (e.g. duplicate clusters from a
            # re-uploaded crop set). A circuit-open, transport error, or 5xx is a
            # systemic failure — not a per-unit conflict — and must halt the seed
            # (S2-04) rather than silently leaving the eval tenant unlabeled; the
            # bare `except Exception` masked all of them as conflicts.
            try:
                client.patch_cluster(cluster_id, tenant_id, names[0])
            except RemoteClientError as exc:
                if exc.status_code != _LABEL_CONFLICT_STATUS:
                    raise
                conflicts[cluster_id] = names[0]
            else:
                labeled[cluster_id] = names[0]
        elif len(names) > 1:
            skipped[cluster_id] = names

    covered = (
        existing_names
        | set(labeled.values())
        | {str(c["label"]) for c in client.clusters(labeled_only=True) if c.get("label")}
    )
    return SeedSummary(
        roster=roster,
        already_labeled=existing,
        labeled=labeled,
        skipped_ambiguous=skipped,
        skipped_conflict=conflicts,
        unlabeled_roster_names=[n for n in roster if n not in covered],
    )


class SceneSeedClient(Protocol):
    def analyze(self, images: list[tuple[int, str, bytes]]) -> str: ...
    def wait_job(self, job_id: str) -> dict[str, Any]: ...
    def media_identities(self, media_ids: list[int]) -> Any: ...


@dataclass(frozen=True)
class SceneSeedSummary:
    seeded: list[int]
    already_present: list[int]
    skipped_zero_face: list[int]
    unverified_media_ids: list[int]
    total_scenes: int


def seed_scenes(manifest_path: str, images_dir: str, client: SceneSeedClient) -> SceneSeedSummary:
    """Idempotently ingest golden-manifest scene images into the eval tenant.

    Parallel to :func:`seed` (crop clusters): uploads each scene under its golden
    ``media_id`` so recognition holds server-side ``MediaIdentity`` face regions
    keyed on the same ids the run record and phrase-box fixture use (E19-4a's
    SQL join input). A scene whose ``media_id`` already has identity rows on the
    tenant is skipped, preserving the idempotent re-run contract. Scenes with
    ``face_count == 0`` are excluded up front: they can never produce identity
    rows, so the presence probe cannot distinguish "not ingested" from
    "ingested, no faces" and they would re-upload on every run — and they
    contribute no ``MediaIdentity`` bboxes for E19-4a anyway.
    """
    manifest = load_manifest(manifest_path, images_dir=images_dir)
    seedable = [entry for entry in manifest.entries if entry.face_count > 0]
    ids = [entry.media_id for entry in seedable]
    rows = client.media_identities(ids)
    if not isinstance(rows, list):
        raise ManifestError(
            f"media_identities returned {type(rows).__name__}, expected a list of "
            "identity rows — refusing to treat a malformed payload as an empty tenant (rg-015)"
        )
    present = {
        int(row["media_id"]) for row in rows if isinstance(row, dict) and int(row.get("media_id", -1)) in set(ids)
    }
    root = Path(images_dir)
    to_seed = [entry for entry in seedable if entry.media_id not in present]
    if to_seed:
        images = []
        for entry in to_seed:
            image_path = _resolve_image(root, entry.path)
            if image_path is None:
                raise ManifestError(
                    f"image file missing: {_printable_path(entry.path)} "
                    f"(under {_printable_path(root)})"
                )
            images.append((entry.media_id, image_path.name, image_path.read_bytes()))
        job_id = client.analyze(images)
        client.wait_job(job_id)
    # Post-seed verification: a face_count>0 scene with no identity rows after
    # analyze is a persistent detector miss — surface it instead of silently
    # re-uploading on every future run.
    unverified: list[int] = []
    if to_seed:
        after = client.media_identities([entry.media_id for entry in to_seed])
        if not isinstance(after, list):
            raise ManifestError(
                f"media_identities returned {type(after).__name__} during post-seed "
                "verification, expected a list of identity rows (rg-015)"
            )
        found = {int(row["media_id"]) for row in after if isinstance(row, dict) and "media_id" in row}
        unverified = [entry.media_id for entry in to_seed if entry.media_id not in found]
    return SceneSeedSummary(
        seeded=[entry.media_id for entry in to_seed],
        already_present=sorted(present),
        skipped_zero_face=[e.media_id for e in manifest.entries if e.face_count == 0],
        unverified_media_ids=unverified,
        total_scenes=len(manifest.entries),
    )
