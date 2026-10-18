"""Fake files/pixels and model kernels; actual S0/S1/S2/S3 and public CLI boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from recognition import config
from recognition.application.embedding.manifest import EmbeddingModelManifest
from recognition.config.settings import RecognitionSettings
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as frames
from scripts.eval_harness import firbench_legs as legs

ROOT = Path(__file__).resolve().parents[4]
KINDS = (fc.LegKind.sface, fc.LegKind.auraface, fc.LegKind.insightface)
ARMS = (fc.Arm.native, fc.Arm.gt_crop_redetect, fc.Arm.cached_yunet_landmark_replay)
AT = "2026-10-15T08:00:00+00:00"


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def runtime_files(tmp_path, monkeypatch, request):
    """Minimal binding: separate hash-bound population source and template inventory.

    Media paths are repo-relative; each template explicitly names identity, box,
    media IDs, image hash and occluders. Query paths are a separate image-ID map.
    No fixture contains names, image bytes or encoded images in source control.
    """
    import cv2

    # S3's installed IO resolves raw decision paths against its native source tree.
    # Exercise that actual CLI deployment context in the end-to-end scoring test.
    native = request.node.name == "test_default_run_and_actual_score"
    repo = ROOT if native else tmp_path / "repo"
    private = repo / "benchmarks/private/firbench"
    if native:
        private = private / "fake-s6a-integration-score"
    private.mkdir(parents=True, exist_ok=False)
    manifests = private / "manifests" if native else repo / "benchmarks/manifests"
    manifests.mkdir(parents=True)
    (manifests / "fir-gate-contract-v1.json").write_bytes(
        (ROOT / "benchmarks/manifests/fir-gate-contract-v1.json").read_bytes()
    )
    payload = json.loads((ROOT / "benchmarks/manifests/fir-bench-decision-v1.json").read_text())
    images, faces, templates, query_images = [], [], [], {}
    for index in range(30):
        identity = f"id-{index:04d}"
        for purpose in ("query", "template"):
            pixels = np.full((24, 24, 3), index + 1, dtype=np.uint8)
            pixels[0, 0, 1] = 1 if purpose == "query" else 2
            ok, encoded = cv2.imencode(".png", pixels)
            assert ok
            path = private / f"{purpose}-{index:04d}.png"
            path.write_bytes(encoded.tobytes())
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            relative = path.relative_to(repo).as_posix()
            if purpose == "query":
                image_id = f"image-{index:04d}"
                query_images[image_id] = {"path": relative, "media_ids": [index]}
                images.append(
                    {
                        "image_id": image_id,
                        "sha256": sha,
                        "sampling_arm": "probability",
                        "inclusion_probability": 1.0,
                        "duplicate_group": None,
                    }
                )
                faces.append(
                    {
                        "face_id": f"face-{index:04d}",
                        "image_id": image_id,
                        "box": [0, 0, 24, 24],
                        "identity_status": "named",
                        "identity_id": identity,
                        "cohort": None,
                        "annotation": {"occluders": ["mask", "sunglasses"] if index % 2 else []},
                    }
                )
            else:
                templates.append(
                    {
                        "template_id": f"template-{index:04d}",
                        "identity_id": identity,
                        "media_ids": [1000 + index],
                        "path": relative,
                        "sha256": sha,
                        "box": [0, 0, 24, 24],
                        "occluders": [],
                    }
                )
    source_path = private / "source.json"
    source_sha = write_json(source_path, {"images": images, "faces": faces})
    template_path = private / "templates.json"
    template_sha = write_json(template_path, {"schema": "firbench-templates/v1", "templates": templates})
    binding = {
        "schema": "firbench-inputs/v1",
        "query_source": {
            "kind": "population_draft",
            "path": source_path.relative_to(repo).as_posix(),
            "sha256": source_sha,
        },
        "gallery_templates": {"path": template_path.relative_to(repo).as_posix(), "sha256": template_sha},
        "query_images": query_images,
    }
    binding_path = repo / "benchmarks/private/firbench/inputs/fake-only.json"
    assert not binding_path.exists(), "never overwrite an operator binding"
    write_json(binding_path, binding)
    payload["frames"] = [
        {
            "frame_id": "fake-only",
            "admissibility": "development",
            "sealed": False,
            "source_sha256": source_sha,
            "exhaustive": True,
        }
    ]
    payload["gallery_lineage"]["templates_sha256"] = template_sha
    decision_path = manifests / "decision.json"
    write_json(decision_path, payload)
    settings = RecognitionSettings()
    settings.face_pipeline.profile = "face_pipeline"
    settings.face_pipeline.face_similarity_threshold = 0.73
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "_head_sha", lambda _: "1" * 40)
    callbacks, loads = [], []

    def factory(kind, *, models_dir, embedder_models_dir=None):
        loads.append(kind)
        dimensions = 128 if kind is fc.LegKind.sface else 512

        class Detector:
            def detect(self, batch):
                for pixel in batch:
                    if pixel[0, 0, 1] == 1:
                        callbacks.append(pixel[0, 0, 0])
                        run = private / "run"
                        assert (run / "frame.json").is_file()
                        manifest = json.loads((run / "manifest.json").read_text())["firbench"]
                        assert len(manifest["gallery_membership"]) >= len(KINDS) * len(ARMS) * 5
                        fc.validate_interchange("frame-v1", json.loads((run / "frame.json").read_text()))
                return [[SimpleNamespace(bbox=(0, 0, 24, 24), landmarks=np.zeros((5, 2)), score=1.0)] for _ in batch]

        class Embedder:
            embedding_dim = dimensions

            def embed(self, batch):
                return SimpleNamespace(vectors=np.array([np.eye(dimensions)[int(p[0, 0, 0]) - 1] for p in batch]))

        return legs.build_face_pipeline_leg(
            kind,
            manifest=EmbeddingModelManifest("fake", kind.value, dimensions, "l2", "cosine"),
            detector=Detector(),
            aligner=SimpleNamespace(align=lambda p, _: SimpleNamespace(crop=p)),
            embedder=Embedder(),
            weights_sha256=hashlib.sha256(kind.value.encode()).hexdigest(),
            preprocessing=None,
            opencv_version="fake-cv",
            ort_version="fake-ort",
        )

    monkeypatch.setattr(legs, "load_pinned_face_pipeline_leg", factory)
    from scripts.eval_harness import firbench_runtime as runtime

    def buffalo(_settings):
        detection = legs.DetectedFace((0, 0, 24, 24), np.zeros((5, 2)), 1.0)

        def process(pixel):
            # A declared fake fused model kernel, never a claim of a real judge run.
            if pixel[0, 0, 1] == 1:
                assert (private / "run/frame.json").is_file()
            return [
                {
                    "bbox_px": detection.bbox_px,
                    "landmarks_px": detection.landmarks_px,
                    "det_score": 1.0,
                    "embedding": np.eye(512)[int(pixel[0, 0, 0]) - 1],
                }
            ]

        return legs.BuffaloLeg(
            process=process,
            embedding_dim=512,
            weights_sha256="b" * 64,
            opencv_version="fake-cv",
            ort_version="fake-ort",
        )

    monkeypatch.setattr(runtime, "_load_buffalo_leg", buffalo)
    files = SimpleNamespace(
        repo=repo,
        private=private,
        decision=decision_path,
        binding=binding,
        binding_path=binding_path,
        source=source_path,
        templates=template_path,
        loads=loads,
        callbacks=callbacks,
        settings=settings,
    )
    try:
        yield files
    finally:
        if native:
            import shutil

            shutil.rmtree(private)
            binding_path.unlink(missing_ok=True)


def run(files, **overrides):
    args = {
        "frame_id": "fake-only",
        "decision_path": files.decision,
        "legs": KINDS,
        "arms": ARMS,
        "subset": None,
        "subset_seed": None,
        "out_dir": files.private / "run",
        "repo_root": files.repo,
        "created_at": AT,
    }
    args.update(overrides)
    return cli.run_frame(**args)


def test_default_run_and_actual_score(runtime_files):
    f = runtime_files
    directory = run(f)
    assert f.loads == list(KINDS[:2])
    assert f.callbacks
    declaration = json.loads((directory / "manifest.json").read_text())["firbench"]
    assert declaration["similarity_threshold"] == 0.73
    assert len(declaration["gallery_membership"]) == 45
    for key in declaration["leg_keys"]:
        ledger = [json.loads(s) for s in (directory / "ledger" / f"{key}.jsonl").read_text().splitlines()]
        assert len(ledger) == 30
        assert {r["face_id"] for r in ledger} == {f"face-{index:04d}" for index in range(30)}
        assert all(
            set(row) == {"face_id", "leg_key", "arm", "stage_reached", "arm_availability", "alignment_mode"}
            for row in ledger
        )
        if key.startswith("insightface__") and "__native__" not in key:
            assert all(r["arm_availability"] == "unavailable_fused" and r["stage_reached"] is None for r in ledger)
    # Score must use persisted inventory, never reopen pixels, binding or GT.
    for path in f.private.glob("*.png"):
        path.unlink()
    f.source.unlink()
    f.templates.unlink()
    f.binding_path.unlink()
    receipt = (directory / "timings.json").read_bytes()
    score_path = cli.score_run(directory, repo_root=f.repo)
    first_score = score_path.read_bytes()
    score = json.loads(first_score)
    assert cli.score_run(directory, repo_root=f.repo).read_bytes() == first_score
    assert (directory / "timings.json").read_bytes() == receipt
    fc.validate_interchange("scores-v1", score)
    assert len(score["legs"]) == 3
    assert score["verdict"]["state"] == "unratified"
    assert all(row["state"] is None and row["interval"] is None for row in score["hypotheses"])


def test_missing_binding_is_named_refusal(runtime_files):
    f = runtime_files
    f.binding_path.unlink()
    with pytest.raises(fc.FrameContractError, match="binding"):
        run(f)
    assert not f.callbacks


def rebind_source(f, payload):
    digest = write_json(f.source, payload)
    f.binding["query_source"]["sha256"] = digest
    write_json(f.binding_path, f.binding)
    decision = json.loads(f.decision.read_text())
    decision["frames"][0]["source_sha256"] = digest
    write_json(f.decision, decision)


def rebind_templates(f, payload):
    digest = write_json(f.templates, payload)
    f.binding["gallery_templates"]["sha256"] = digest
    write_json(f.binding_path, f.binding)
    decision = json.loads(f.decision.read_text())
    decision["gallery_lineage"]["templates_sha256"] = digest
    write_json(f.decision, decision)


@pytest.mark.parametrize(
    "case",
    ["source_hash", "template_hash", "source_missing", "template_missing", "pixel_missing", "gt", "unresolved_hash"],
)
def test_missing_or_unbound_inputs_refuse_before_query(runtime_files, case):
    f = runtime_files
    expected = "sha256"
    if case == "source_hash":
        f.source.write_text(f.source.read_text() + " ")
    elif case == "template_hash":
        f.templates.write_text(f.templates.read_text() + " ")
    elif case == "source_missing":
        f.source.unlink()
        expected = "asset"
    elif case == "template_missing":
        f.templates.unlink()
        expected = "asset"
    elif case == "pixel_missing":
        next(f.private.glob("query-*.png")).unlink()
        expected = "asset"
    elif case == "gt":
        source = json.loads(f.source.read_text())
        source.pop("faces")
        rebind_source(f, source)
        expected = "faces"
    else:
        decision = json.loads(f.decision.read_text())
        decision["frames"][0]["source_sha256"] = None
        write_json(f.decision, decision)
    with pytest.raises(fc.FrameContractError, match=expected):
        run(f)
    assert not f.callbacks
    assert not (f.private / "run/manifest.json").exists()


@pytest.mark.parametrize("overlap", ["hash", "path", "media"])
def test_enrollment_overlap_is_refused(runtime_files, overlap):
    f = runtime_files
    doc = json.loads(f.templates.read_text())
    row = doc["templates"][0]
    if overlap == "hash":
        row["sha256"] = json.loads(f.source.read_text())["images"][0]["sha256"]
    elif overlap == "path":
        row["path"] = f.binding["query_images"]["image-0000"]["path"]
    else:
        # Golden's numeric image IDs are an independent media-ID inventory.
        source = json.loads(f.source.read_text())
        source["images"][0]["image_id"] = "1000"
        source["faces"][0]["image_id"] = "1000"
        f.binding["query_images"]["1000"] = f.binding["query_images"].pop("image-0000")
        f.binding["query_images"]["1000"]["media_ids"] = [1000]
        rebind_source(f, source)
    rebind_templates(f, doc)
    with pytest.raises(fc.FrameContractError, match="overlap"):
        run(f)
    assert not f.callbacks


@pytest.mark.parametrize("refusal", ["public_output", "nonempty", "sealed_canary", "no_token", "timestamp"])
def test_static_refusals_do_not_read_inputs_or_write(runtime_files, monkeypatch, refusal):
    f = runtime_files
    arguments = {}
    if refusal == "public_output":
        arguments["out_dir"] = f.repo / "public-run"
    elif refusal == "nonempty":
        (f.private / "run").mkdir()
        (f.private / "run/keep").write_text("keep")
    elif refusal in {"sealed_canary", "no_token"}:
        decision = json.loads(f.decision.read_text())
        decision["frames"][0]["sealed"] = True
        write_json(f.decision, decision)
        if refusal == "sealed_canary":
            arguments["legs"] = (*KINDS, fc.LegKind.canary)
    else:
        arguments["created_at"] = None
    before = {p.relative_to(f.private): p.read_bytes() for p in f.private.rglob("*") if p.is_file()}
    original = Path.read_bytes

    def guarded(path):
        if path == f.binding_path or path == f.source or path == f.templates or path.suffix == ".png":
            pytest.fail("private input read before static refusal/authorization")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    with pytest.raises(fc.FirBenchError):
        run(f, **arguments)
    monkeypatch.setattr(Path, "read_bytes", original)
    after = {p.relative_to(f.private): p.read_bytes() for p in f.private.rglob("*") if p.is_file()}
    assert before == after


def test_single_driver_authorization_and_ram_reuse(runtime_files, monkeypatch):
    from dataclasses import asdict

    from scripts.eval_harness import firbench_runtime as runtime

    f = runtime_files
    decision = json.loads(f.decision.read_text())
    decision["frames"][0]["sealed"] = True
    write_json(f.decision, decision)
    token = fc.UnsealToken(
        frame_id="fake-only",
        frame_sha256=decision["frames"][0]["source_sha256"],
        decision_sha256=hashlib.sha256(f.decision.read_bytes()).hexdigest(),
        run_id="run",
        code_sha="1" * 40,
        scorer_sha=runtime.scorer_sha256(),
        consumed_at=None,
    )
    (f.private / "unseal-ledger.jsonl").write_text(json.dumps(asdict(token)) + "\n")
    actual_authorize = cli.require_frame_read_allowed
    calls, reads = [], []

    def authorize(*args, **kwargs):
        calls.append(args[0].frame_id)
        return actual_authorize(*args, **kwargs)

    actual_read = Path.read_bytes

    def read(path):
        if path.suffix == ".png":
            assert calls == ["fake-only"]
            reads.append(path)
        return actual_read(path)

    monkeypatch.setattr(cli, "require_frame_read_allowed", authorize)
    monkeypatch.setattr(Path, "read_bytes", read)
    run(f)
    assert calls == ["fake-only"]
    assert len(reads) == len(set(reads)) == 60
    with pytest.raises(fc.SealedFrameReadError):
        run(f, out_dir=f.private / "second")
    assert len(reads) == 60


def test_gallery_fold_registry_uses_actual_partition(runtime_files):
    from scripts.eval_harness import gallery_split

    f = runtime_files
    directory = run(f)
    declaration = json.loads((directory / "manifest.json").read_text())["firbench"]
    frame = json.loads((directory / "frame.json").read_text())
    foldmap = {r["identity_id"]: r["fold"] for r in frame["identity_folds"]}
    templates = json.loads(f.templates.read_text())["templates"]
    for fold in range(5):
        roster = {
            r["identity_id"]: [gallery_split.Template(r["template_id"], r["identity_id"], tuple(r["media_ids"]))]
            for r in templates
            if foldmap[r["identity_id"]] == fold
        }
        expected = set(gallery_split.build_disjoint_galleries(templates_by_subject=roster, seed=2468935812).g1)
        rows = [r for r in declaration["gallery_membership"] if r["fold"] == fold]
        assert len(rows) == 9
        assert all(set(r["enrolled_identity_ids"]) == expected for r in rows)
        assert all(r["identity_folds"] == foldmap for r in rows)
        for row in rows:
            key = row["leg_key"]
            searches = [json.loads(s) for s in (directory / "legs" / key / "searches.jsonl").read_text().splitlines()]
            for search in (s for s in searches if s["fold"] == fold):
                assert {hit[0] for hit in search["top_k"]} <= expected
                assert search["gallery_sha256"] == row["gallery_sha256"]
                assert search["fold_role"] == ("test" if fold == 0 else "fit")
    basis = declaration["gallery_hash_basis"]
    assert basis.startswith("sface__native__")
    assert {r["fold"]: r["sha256"] for r in frame["gallery_sha256_by_fold"]} == {
        r["fold"]: r["gallery_sha256"] for r in declaration["gallery_membership"] if r["leg_key"] == basis
    }
    assert frame["n_eff"] == 30  # whole fixed GT inventory, never detections


def test_bad_query_timing_retains_declaration_only(runtime_files, monkeypatch):
    f = runtime_files
    # Fault only the clock beneath the actual S2 producer.
    import itertools

    ticks = itertools.cycle([0.0, float("nan")])
    monkeypatch.setattr(legs, "perf_counter", lambda: next(ticks))
    with pytest.raises(fc.FrameContractError, match="finite"):
        run(f)
    assert {p.name for p in (f.private / "run").iterdir()} == {"frame.json", "manifest.json", "attempt-failure.json"}
    failure = json.loads((f.private / "run/attempt-failure.json").read_text())
    assert failure["phase"] == "query_outcomes"


def test_tier_a_reference_string_is_not_qualified_evidence(runtime_files):
    f = runtime_files
    source = json.loads(f.source.read_text())
    source["faces"][0]["annotation"].update(annotation_tier="a", observation_ref="fake-ref", qc_ref="fake-ref")
    rebind_source(f, source)
    with pytest.raises(fc.FrameContractError, match="qualified S7"):
        run(f)
    assert not f.callbacks


@pytest.mark.parametrize("flag", [None, "1"])
def test_honest_optional_bench_refusal_without_model_or_query_reads(monkeypatch, flag):
    import importlib.util

    from scripts.eval_harness import firbench_runtime as runtime

    if flag is None:
        monkeypatch.delenv("ACX_EVAL_BENCH", raising=False)
        message = "ACX_EVAL_BENCH"
    else:
        assert importlib.util.find_spec("insightface") is None, "verification must use clean dev-only environment"
        monkeypatch.setenv("ACX_EVAL_BENCH", flag)
        message = "bench.*extra|insightface is required"
    with pytest.raises(fc.FrameContractError, match=message):
        runtime._load_buffalo_leg(RecognitionSettings())


def test_actual_canary_declares_one_derangement_and_binds_search_hash(runtime_files):
    f = runtime_files
    directory = run(f, legs=(*KINDS, fc.LegKind.canary))
    manifest = json.loads((directory / "manifest.json").read_text())["firbench"]
    native_key = next(key for key in manifest["leg_keys"] if key.startswith("sface__native__"))
    canary_key = next(key for key in manifest["leg_keys"] if key.startswith("canary__native__"))
    native = [json.loads(s) for s in (directory / "legs" / native_key / "searches.jsonl").read_text().splitlines()]
    canary = [json.loads(s) for s in (directory / "legs" / canary_key / "searches.jsonl").read_text().splitlines()]
    assert len(native) == len(canary) == 30
    for row, original in zip(canary, native, strict=True):
        permutation = manifest["canary_permutations"][str(row["fold"])]
        assert all(k != v for k, v in permutation.items())
        assert set(permutation) == set(permutation.values())
        # A single relabel preserves scores and changes exactly the corresponding names.
        assert sorted(row["top_k"]) == sorted([[permutation[name], score] for name, score in original["top_k"]])
        declaration = next(
            r for r in manifest["gallery_membership"] if r["leg_key"] == canary_key and r["fold"] == row["fold"]
        )
        assert row["gallery_sha256"] == declaration["gallery_sha256"]
        assert row["gallery_sha256"] != original["gallery_sha256"]


def test_declared_identity_fold_map_cannot_contradict_s1_psus(runtime_files):
    f = runtime_files
    source = frames.load_population_draft(f.source)
    components = frames.build_psu_components(source.images, source.faces)
    identities = frames.identity_to_component(source.faces, components)
    foldmap = frames.identity_disjoint_folds(components, identities, k=5, seed=2406466110)
    f.binding["identity_folds"] = {identity: foldmap[psu] for identity, psu in identities.items()}
    first = next(iter(f.binding["identity_folds"]))
    f.binding["identity_folds"][first] = (f.binding["identity_folds"][first] + 1) % 5
    write_json(f.binding_path, f.binding)
    with pytest.raises(fc.FrameContractError, match="identity_folds"):
        run(f)
    assert not f.callbacks


def test_missing_required_hypothesis_leg_is_refused(runtime_files):
    f = runtime_files
    with pytest.raises(fc.FrameContractError, match="hypothesis legs.*insightface"):
        run(f, legs=KINDS[:2])
    assert not f.callbacks


def test_template_only_identity_map_is_persisted_before_query(runtime_files):
    f = runtime_files
    # Add five template-only identities, explicitly one per fold.
    source = frames.load_population_draft(f.source)
    components = frames.build_psu_components(source.images, source.faces)
    identities = frames.identity_to_component(source.faces, components)
    foldmap = frames.identity_disjoint_folds(components, identities, k=5, seed=2406466110)
    full = {identity: foldmap[psu] for identity, psu in identities.items()}
    doc = json.loads(f.templates.read_text())
    for fold in range(5):
        row = dict(next(r for r in doc["templates"] if full[r["identity_id"]] == fold))
        row["identity_id"] = f"id-template-only-{fold}"
        row["template_id"] = f"template-only-{fold}"
        full[row["identity_id"]] = fold
        doc["templates"].append(row)
    f.binding["identity_folds"] = full
    rebind_templates(f, doc)
    directory = run(f)
    declaration = json.loads((directory / "manifest.json").read_text())["firbench"]
    assert all(r["identity_folds"] == full for r in declaration["gallery_membership"])


def test_default_collaborator_creation_does_not_load_models_or_private_inputs(runtime_files, monkeypatch):
    f = runtime_files
    original = Path.read_bytes

    def read(path):
        assert not path.is_relative_to(f.private)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    collaborators = cli._load_collaborators()
    assert callable(collaborators.prepare_run)
    assert not f.loads and not f.callbacks


def test_actual_pinned_factory_missing_assets_is_a_named_offline_refusal(tmp_path):
    from scripts.eval_harness import firbench_runtime as runtime

    settings = RecognitionSettings()
    settings.face_pipeline.models_dir = tmp_path / "missing-models"
    settings.auraface_models_dir = tmp_path / "missing-aura"
    with pytest.raises(fc.FrameContractError, match="pinned runtime/assets unavailable"):
        runtime._native(fc.LegKind.sface, settings)
    assert not settings.face_pipeline.models_dir.exists()


def test_nonpseudonymous_source_identity_is_refused(runtime_files):
    f = runtime_files
    source = json.loads(f.source.read_text())
    source["faces"][0]["identity_id"] = "subject-without-alias"
    rebind_source(f, source)
    with pytest.raises(fc.FrameContractError, match="pseudonymous identity"):
        run(f)
    assert not (f.private / "run/frame.json").exists()
