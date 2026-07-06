"""VLM-2A Slice 2: idempotent eval-tenant roster seeding (stub client, no network)."""

import pytest

from scripts.eval_harness.seed_roster import CROP_MEDIA_ID_BASE, seed


class StubClient:
    def __init__(self, clusters=None, members=None):
        self._clusters = clusters or []
        self._members = members or {}
        self.analyzed = []
        self.clustering_jobs = 0
        self.patched = []

    def analyze(self, images):
        self.analyzed.extend(images)
        return "job-1"

    def wait_job(self, job_id):
        return {"job_id": job_id, "status": "completed"}

    def clustering_job(self, tenant_id, mode="sync"):
        self.clustering_jobs += 1
        return {"status": "completed"}

    def clusters(self, labeled_only=False):
        if labeled_only:
            return [c for c in self._clusters if c.get("label")]
        return self._clusters

    def cluster_members(self, cluster_id):
        return self._members[cluster_id]

    def patch_cluster(self, cluster_id, tenant_id, label):
        self.patched.append((cluster_id, label))
        for c in self._clusters:
            if c["id"] == cluster_id:
                c["label"] = label


@pytest.fixture()
def entities_dir(tmp_path):
    d = tmp_path / "mock_entities"
    d.mkdir()
    (d / "entity-alice-example.jpg").write_bytes(b"a1")
    (d / "entity-alice-example-2.jpg").write_bytes(b"a2")
    (d / "entity-bob-builder.png").write_bytes(b"b1")
    return d


def test_fresh_tenant_full_seed(entities_dir):
    client = StubClient(
        clusters=[{"id": "c1", "label": None}, {"id": "c2", "label": None}],
        members={
            "c1": {"members": [{"media_id": CROP_MEDIA_ID_BASE + 0}, {"media_id": CROP_MEDIA_ID_BASE + 1}]},
            "c2": {"members": [{"media_id": CROP_MEDIA_ID_BASE + 2}]},
        },
    )
    summary = seed(str(entities_dir), client, tenant_id="eval-tenant")
    assert len(client.analyzed) == 3  # all crops uploaded
    assert client.clustering_jobs == 1
    assert sorted(client.patched) == [("c1", "Alice Example"), ("c2", "Bob Builder")]
    assert summary.labeled == {"c1": "Alice Example", "c2": "Bob Builder"}
    assert summary.already_labeled == {}


def test_idempotent_when_roster_fully_labeled(entities_dir):
    client = StubClient(
        clusters=[
            {"id": "c1", "label": "Alice Example"},
            {"id": "c2", "label": "Bob Builder"},
        ],
    )
    summary = seed(str(entities_dir), client, tenant_id="eval-tenant")
    assert client.analyzed == []  # no re-upload
    assert client.clustering_jobs == 0
    assert client.patched == []
    assert summary.already_labeled == {"c1": "Alice Example", "c2": "Bob Builder"}


def test_mixed_identity_cluster_left_unlabeled(entities_dir):
    client = StubClient(
        clusters=[{"id": "c1", "label": None}],
        members={
            "c1": {
                "members": [
                    {"media_id": CROP_MEDIA_ID_BASE + 0},  # alice crop
                    {"media_id": CROP_MEDIA_ID_BASE + 2},  # bob crop
                ]
            },
        },
    )
    summary = seed(str(entities_dir), client, tenant_id="eval-tenant")
    assert client.patched == []
    assert "c1" in summary.skipped_ambiguous


def test_crop_media_ids_do_not_collide_with_manifest_range(entities_dir):
    client = StubClient(clusters=[], members={})
    seed(str(entities_dir), client, tenant_id="eval-tenant")
    media_ids = [m for m, _, _ in client.analyzed]
    assert all(m >= CROP_MEDIA_ID_BASE for m in media_ids)
    assert CROP_MEDIA_ID_BASE > 38  # golden manifest uses 1..38
