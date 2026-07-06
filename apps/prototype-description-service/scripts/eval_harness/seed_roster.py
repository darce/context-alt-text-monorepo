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

from .draft_labels import _display_name, _entity_slug
from .manifest import ManifestError

CROP_MEDIA_ID_BASE = 1001

_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


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
        (p for p in entities_dir.iterdir() if p.suffix.lower() in _IMAGE_EXTS),
        key=lambda p: p.name,
    )
    for offset, path in enumerate(files):
        name = _display_name(_entity_slug(path.name))
        crops.append((CROP_MEDIA_ID_BASE + offset, path.name, path.read_bytes(), name))
    return crops


def seed(entities_dir: str, client: SeedClient, *, tenant_id: str) -> SeedSummary:
    root = Path(entities_dir)
    if not root.is_dir():
        raise ManifestError(
            f"entities dir not found: {root} — set GOLDEN_IMAGES_DIR and pass "
            "<GOLDEN_IMAGES_DIR>/mock_entities (see scene/tests/seed/README.md)"
        )
    crops = _load_crops(root)
    if not crops:
        raise ManifestError(f"no entity crops found under {root}")
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
            # A name can already be taken by another cluster (e.g. duplicate
            # clusters from a re-uploaded crop set) — 409 there means the name
            # is covered; record and continue rather than failing the seed.
            try:
                client.patch_cluster(cluster_id, tenant_id, names[0])
            except Exception:  # noqa: BLE001 — per-cluster isolation; coverage re-checked below
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
