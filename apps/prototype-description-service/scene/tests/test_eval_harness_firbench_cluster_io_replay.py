"""Private, synthetic replay through the actual S2 cache writer and S4/schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scene.tests import test_eval_harness_firbench_cluster_io as fixtures
from scripts.eval_harness import firbench_cluster_io as fci
from scripts.eval_harness import firbench_clusters as fcl
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness.firbench_legs import CachedObservation, LegCache


def _run(root: Path, *, run_id: str = "run-0001") -> Path:
    frame = fixtures._frame()
    observations = tuple(
        CachedObservation(
            leg_key=fixtures.SFACE,
            record_id=face.face_id,
            image_id=face.image_id,
            image_sha256=fixtures._sha(face.image_id),
            gt_face_id=face.face_id,
            stage="embedded",
            arm_availability="available",
            bbox_px=face.box,
            landmarks_px=tuple(tuple(point) for point in fixtures.LANDMARKS),
            detector_score=0.99,
            embedding=tuple(float(value) for value in vector),
        )
        for face, vector in zip(frame.faces, fixtures.GT_VECTORS, strict=True)
    )
    # The shared fixture packs and stores these through the actual strict S2 writer.
    return fixtures._write_run(root, frame=frame, run_id=run_id, observations={fixtures.SFACE: observations})


def _private(repo: Path, name: str = "run") -> Path:
    return repo / "benchmarks" / "private" / "firbench" / name


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _expected(root: Path, *, config=None, prior=None) -> bytes:
    # Derive from the actual combined source, including any sibling coverage fields.
    run = fci._load_run(root)
    previous = None if prior is None else fci._load_run(prior)
    diagnostic = fci.DiagnosticConfig() if config is None else config
    entries = [fci._leg_entry(run, previous, key, diagnostic) for key in run.leg_keys]
    payload = fcl.build_clusters_payload(entries)
    fc.validate_interchange("clusters-v1", payload)
    return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode()


def test_second_report_materialization_returns_same_path_and_exact_canonical_bytes(tmp_path):
    repo = tmp_path / "external-repository"
    root = _run(_private(repo))
    prior = _run(_private(repo, "prior"), run_id="run-previous")
    expected = _expected(root, prior=prior)
    first = fci.materialize_clusters(root, prior_run_dir=prior)
    assert first == root / "clusters.json"
    assert first.read_bytes() == expected
    payload = json.loads(expected)
    leg = fixtures._entry(payload, fixtures.SFACE)
    assert leg["partition_metrics"]["status"] == "available"
    assert leg["partition_metrics"]["data"]["named_faces"] == 4
    assert leg["companions"]["linear_cka"]["status"] == "available"
    before = _snapshot(repo)
    stat = first.stat()
    assert fci.materialize_clusters(root, prior_run_dir=prior) == first
    assert _snapshot(repo) == before
    assert (first.stat().st_ino, first.stat().st_mtime_ns) == (stat.st_ino, stat.st_mtime_ns)


@pytest.mark.parametrize("change", ["cache", "config", "prior", "scores", "frame", "invalid_config", "invalid_cache"])
def test_existing_output_never_bypasses_actual_input_validation(tmp_path, change):
    repo = tmp_path / "repo"
    root = _run(_private(repo))
    prior = _run(_private(repo, "prior"), run_id="run-previous")
    target = fci.materialize_clusters(root, prior_run_dir=prior)
    original = target.read_bytes()
    config = None
    if change in {"cache", "invalid_cache", "prior"}:
        changed = prior if change == "prior" else root
        cache = LegCache(changed / "legs" / fixtures.SFACE / "cache.npz", leg_key=fixtures.SFACE)
        if change == "invalid_cache":
            cache.path.write_bytes(b"corrupt cache")
        else:
            arrays = cache.load()
            arrays["vectors"][0] = [0.0, 0.0, 1.0]
            cache.store(arrays)
    elif change in {"config", "invalid_config"}:
        config = fci.DiagnosticConfig(knn_k=2 if change == "config" else 0)
    else:
        path = root / ("scores.json" if change == "scores" else "frame.json")
        payload = json.loads(path.read_text())
        if change == "scores":
            payload["legs"][0]["tau"]["data"]["value"] = 0.51
        else:
            del payload["faces"]
        path.write_text(json.dumps(payload))
    before = _snapshot(repo)
    reason = {"invalid_config": "knn_k", "invalid_cache": "cache", "frame": "frame-v1"}.get(change, "already exists")
    with pytest.raises(fc.FrameContractError, match=reason):
        fci.materialize_clusters(root, prior_run_dir=prior, config=config)
    assert target.read_bytes() == original
    assert _snapshot(repo) == before


@pytest.mark.parametrize("existing", [b"{}\n", b"broken JSON", b"", b"canonical_without_newline", b"noncanonical"])
def test_conflicting_or_corrupt_existing_output_preserves_all_bytes(tmp_path, existing):
    repo = tmp_path / "repo"
    root = _run(_private(repo))
    expected = _expected(root)
    if existing == b"canonical_without_newline":
        existing = expected.rstrip(b"\n")
    elif existing == b"noncanonical":
        existing = json.dumps(json.loads(expected)).encode()
    target = root / "clusters.json"
    target.write_bytes(existing)
    before = _snapshot(repo)
    with pytest.raises(fc.FrameContractError, match="already exists"):
        fci.materialize_clusters(root)
    assert _snapshot(repo) == before


@pytest.mark.parametrize("location", ["public", "arbitrary", "repository_root", "private_root", "traversal", "root"])
def test_nonprivate_or_traversing_run_is_refused_before_writing(tmp_path, location):
    repo = tmp_path / "repo"
    choices = {
        "public": repo / "benchmarks" / "public" / "run",
        "arbitrary": repo / "run",
        "repository_root": repo,
        "private_root": repo / "benchmarks" / "private",
        "traversal": _private(repo) / ".." / "run",
        "root": Path("/"),
    }
    root = choices[location]
    if location != "root":
        # The run is otherwise valid, so refusal exercises the output boundary.
        _run(_private(repo) if location == "traversal" else root)
    before = _snapshot(repo) if repo.exists() else {}
    with pytest.raises(fc.NonPrivateOutputError):
        fci.materialize_clusters(root)
    assert (_snapshot(repo) if repo.exists() else {}) == before


@pytest.mark.parametrize(
    "redirect", ["repository", "benchmarks", "private", "run", "inner_private", "output", "dangling_output"]
)
def test_symlinked_private_context_or_output_is_refused_without_mutation(tmp_path, redirect):
    repo = tmp_path / "repo"
    root = _run(_private(repo))
    external = tmp_path / "elsewhere"
    external.mkdir()
    if redirect == "repository":
        alias = tmp_path / "alias"
        alias.symlink_to(repo, target_is_directory=True)
        requested = _private(alias)
    elif redirect in {"benchmarks", "private", "run"}:
        link = {"benchmarks": repo / "benchmarks", "private": repo / "benchmarks" / "private", "run": root}[redirect]
        moved = external / "moved"
        link.rename(moved)
        link.symlink_to(moved, target_is_directory=True)
        requested = root
    elif redirect == "inner_private":
        alias = _private(repo, "alias")
        alias.symlink_to(root, target_is_directory=True)
        requested = alias
    else:
        destination = external / "untouched.json"
        if redirect == "output":
            destination.write_bytes(b"preserve me")
        (root / "clusters.json").symlink_to(destination)
        requested = root
    before = _snapshot(tmp_path)
    with pytest.raises(fc.NonPrivateOutputError):
        fci.materialize_clusters(requested)
    assert _snapshot(tmp_path) == before


def test_relative_private_run_uses_actual_temporary_repository(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    root = _run(_private(repo))
    monkeypatch.chdir(repo)
    target = fci.materialize_clusters(root.relative_to(repo))
    assert target == root / "clusters.json"
    assert target.read_bytes() == _expected(root)


def test_nonprivate_prior_is_refused_without_creating_current_output(tmp_path):
    repo = tmp_path / "repo"
    root = _run(_private(repo))
    prior = _run(repo / "benchmarks" / "public" / "prior", run_id="run-previous")
    before = _snapshot(repo)
    with pytest.raises(fc.NonPrivateOutputError):
        fci.materialize_clusters(root, prior_run_dir=prior)
    assert _snapshot(repo) == before


@pytest.mark.parametrize("identical", [True, False])
def test_concurrent_publication_never_replaces_another_writers_bytes(tmp_path, monkeypatch, identical):
    repo = tmp_path / "repo"
    root = _run(_private(repo))
    target = root / "clusters.json"
    incoming = _expected(root) if identical else b"another writer's artifact\n"
    link = fci.os.link
    before = _snapshot(repo)

    def publish_after_competing_writer(staging, destination):
        assert destination == target
        target.write_bytes(incoming)
        link(staging, destination)  # Real exclusive publication must refuse replacement.

    monkeypatch.setattr(fci.os, "link", publish_after_competing_writer)
    if identical:
        assert fci.materialize_clusters(root) == target
    else:
        with pytest.raises(fc.FrameContractError, match="already exists"):
            fci.materialize_clusters(root)
    assert _snapshot(repo) == {**before, str(target.relative_to(repo)): incoming}
    assert not list(root.glob(".clusters*"))
