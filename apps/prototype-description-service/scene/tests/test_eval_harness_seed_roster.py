"""VLM-2A Slice 2: idempotent eval-tenant roster seeding (stub client, no network)."""

import pytest

from scripts.eval_harness.remote_client import CircuitOpenError, RemoteClientError
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


def test_systemic_patch_failure_halts_seed(entities_dir):  # S2-04
    client = StubClient(
        clusters=[{"id": "c1", "label": None}],
        members={"c1": {"members": [{"media_id": CROP_MEDIA_ID_BASE + 0}]}},
    )

    def boom(cluster_id, tenant_id, label):
        raise CircuitOpenError("circuit open after 3 consecutive failures")

    client.patch_cluster = boom
    # a breaker-open / outage is not a per-unit conflict; it must halt the seed
    # rather than be swallowed as skipped_conflict.
    with pytest.raises(CircuitOpenError):
        seed(str(entities_dir), client, tenant_id="eval-tenant")


def test_409_label_conflict_recorded_not_raised(entities_dir):  # S2-04
    client = StubClient(
        clusters=[{"id": "c1", "label": None}],
        members={"c1": {"members": [{"media_id": CROP_MEDIA_ID_BASE + 0}]}},
    )

    def conflict(cluster_id, tenant_id, label):
        raise RemoteClientError("PATCH /clusters/c1 failed: 409 label taken", status_code=409)

    client.patch_cluster = conflict
    summary = seed(str(entities_dir), client, tenant_id="eval-tenant")
    assert summary.skipped_conflict == {"c1": "Alice Example"}


# --- VLM-2C Slice 3: scene-image seeding (server-side MediaIdentity bboxes) ---

from scripts.eval_harness.seed_roster import seed_scenes  # noqa: E402


class SceneStubClient:
    def __init__(self, existing_rows=None):
        self._rows = list(existing_rows or [])
        self.analyzed = []
        self.identity_queries = []

    def analyze(self, images):
        self.analyzed.extend(images)
        for media_id, _fname, _data in images:
            self._rows.append({"media_id": media_id, "label": None})
        return "job-scenes"

    def wait_job(self, job_id):
        return {"job_id": job_id, "status": "completed"}

    def media_identities(self, media_ids):
        self.identity_queries.append(list(media_ids))
        return [r for r in self._rows if r["media_id"] in media_ids]


def _scene_fixture(tmp_path):
    import hashlib
    import json

    images = tmp_path / "images" / "mock_images"
    images.mkdir(parents=True)
    entries = []
    for media_id, name in [(1, "alice-pool.jpg"), (2, "bob-beach.jpg")]:
        body = name.encode()
        (images / name).write_bytes(body)
        entries.append(
            {
                "path": f"mock_images/{name}",
                "sha256": hashlib.sha256(body).hexdigest(),
                "media_id": media_id,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "context_pack": {"title": "t"},
                "base_caption": "",
                "must_right": ["Alice Example"],
                "easy_wrong": ["Bob Example"],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "fixture", "license": "fixture"},
            }
        )
    manifest = {"manifest_version": 3,
            "annotation_mode": "roster_only", "roster": ["Alice Example", "Bob Example"], "entries": entries}
    manifest_path = tmp_path / "golden.json"
    manifest_path.write_text(json.dumps(manifest))
    return str(manifest_path), str(tmp_path / "images")


def test_seed_scenes_fresh_uploads_all(tmp_path):
    manifest_path, images_dir = _scene_fixture(tmp_path)
    client = SceneStubClient()
    summary = seed_scenes(manifest_path, images_dir, client)
    assert summary.seeded == [1, 2]
    assert summary.already_present == []
    assert summary.skipped_zero_face == []
    assert summary.unverified_media_ids == []
    assert summary.total_scenes == 2
    assert [m for m, _, _ in client.analyzed] == [1, 2]


def test_seed_scenes_zero_face_scene_never_uploaded(tmp_path):  # VLM-2C-S3-BR-01
    import hashlib
    import json

    manifest_path, images_dir = _scene_fixture(tmp_path)
    with open(manifest_path) as handle:
        data = json.loads(handle.read())
    body = b"no-faces"
    (tmp_path / "images" / "mock_images" / "landscape.jpg").write_bytes(body)
    data["entries"].append(
        {
            "path": "mock_images/landscape.jpg",
            "sha256": hashlib.sha256(body).hexdigest(),
            "media_id": 3,
            "face_count": 0,
            "present_identities": [],
            "context_pack": {"title": "t"},
            "base_caption": "",
            "must_right": [],
            "easy_wrong": ["Bob Example"],
            "policy": {"recognition_enabled": True},
            "provenance": {"source": "fixture", "license": "fixture"},
        }
    )
    with open(manifest_path, "w") as handle:
        handle.write(json.dumps(data))
    client = SceneStubClient()
    first = seed_scenes(manifest_path, images_dir, client)
    assert first.seeded == [1, 2]
    assert first.skipped_zero_face == [3]
    client.analyzed.clear()
    second = seed_scenes(manifest_path, images_dir, client)
    assert second.seeded == []
    assert client.analyzed == [], "zero-face scene must not re-upload on re-run"


def test_seed_scenes_rejects_non_list_identities_payload(tmp_path):  # VLM-2C-S3-BR-02
    from scripts.eval_harness.manifest import ManifestError

    manifest_path, images_dir = _scene_fixture(tmp_path)
    client = SceneStubClient()
    client.media_identities = lambda media_ids: {"error": "boom"}
    with pytest.raises(ManifestError, match="media_identities"):
        seed_scenes(manifest_path, images_dir, client)


def test_seed_scenes_idempotent_rerun_uploads_nothing(tmp_path):
    manifest_path, images_dir = _scene_fixture(tmp_path)
    client = SceneStubClient()
    seed_scenes(manifest_path, images_dir, client)
    client.analyzed.clear()
    summary = seed_scenes(manifest_path, images_dir, client)
    assert summary.seeded == []
    assert summary.already_present == [1, 2]
    assert client.analyzed == []


def test_seed_scenes_partial_seeds_only_missing(tmp_path):
    manifest_path, images_dir = _scene_fixture(tmp_path)
    client = SceneStubClient(existing_rows=[{"media_id": 1, "label": "Alice Example"}])
    summary = seed_scenes(manifest_path, images_dir, client)
    assert summary.seeded == [2]
    assert summary.already_present == [1]
    assert [m for m, _, _ in client.analyzed] == [2]


def test_seed_scenes_reports_detector_misses_as_unverified(tmp_path):  # VLM-2C-R2-S3/S5-BR-01
    manifest_path, images_dir = _scene_fixture(tmp_path)
    client = SceneStubClient()
    real_analyze = client.analyze

    def analyze_missing_media_2(images):
        job = real_analyze(images)
        client._rows = [r for r in client._rows if r["media_id"] != 2]
        return job

    client.analyze = analyze_missing_media_2
    summary = seed_scenes(manifest_path, images_dir, client)
    assert summary.seeded == [1, 2]
    assert summary.unverified_media_ids == [2], "detector miss must be surfaced, not masked"


def test_seed_scenes_resolves_nfd_filenames(tmp_path):  # VLM-2C-R2-HARM-BR-01
    import hashlib
    import json
    import unicodedata

    manifest_path, images_dir = _scene_fixture(tmp_path)
    with open(manifest_path) as handle:
        data = json.loads(handle.read())
    body = b"glacier"
    nfd_name = unicodedata.normalize("NFD", "Brei\u00f0amerkurj\u00f6kull.jpg")
    nfc_name = unicodedata.normalize("NFC", "Brei\u00f0amerkurj\u00f6kull.jpg")
    (tmp_path / "images" / "mock_images" / nfd_name).write_bytes(body)
    data["entries"].append(
        {
            "path": f"mock_images/{nfc_name}",
            "sha256": hashlib.sha256(body).hexdigest(),
            "media_id": 4,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "context_pack": {"title": "t"},
            "base_caption": "",
            "must_right": ["Alice Example"],
            "easy_wrong": ["Bob Example"],
            "policy": {"recognition_enabled": True},
            "provenance": {"source": "fixture", "license": "fixture"},
        }
    )
    with open(manifest_path, "w") as handle:
        handle.write(json.dumps(data))
    client = SceneStubClient()
    summary = seed_scenes(manifest_path, images_dir, client)
    assert 4 in summary.seeded, "NFC manifest path must resolve an NFD file on disk"
