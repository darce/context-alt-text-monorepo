"""C76 ABI-09/10/15 producer contracts; only inert transport-record doubles.

Missing proposed symbols are assertion REDs, not collection errors or skips.
The Record double supports attribute and mapping access without a model loader.
PROV-01: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/ml-systems.md#prov-01
WEB-16: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/security.md#web-16
"""
from __future__ import annotations

import asyncio
import dataclasses
import importlib.util
import sys
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class Record(dict):
    """Structural double, not a claim of a successful model observation."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


@pytest.fixture(autouse=True)
def isolated_import_state(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    for name in ("shared", "shared.source_identity", "shared.face_role_snapshot",
                 "recognition.application.face_acceptance_catalog"):
        # Register absent keys too, so transitive imports are removed on teardown.
        monkeypatch.setitem(sys.modules, name, None)
        monkeypatch.delitem(sys.modules, name)


def producer():
    path = ROOT / "shared/face_role_snapshot.py"
    assert path.is_file(), "CAUSAL_RED: missing shared/face_role_snapshot.py (ABI-09/15)"
    spec = importlib.util.spec_from_file_location("shared.face_role_snapshot", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def plain(value):
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return plain(value.model_dump())
    return value


def observation(generation, adapter):
    return Record(
        adapter_instance_id=adapter, usage_origin="serving", active=True,
        last_execution_at=None,
        runtime_record=Record(
            producer_abi_version=1, runtime_generation_id=generation,
            model_id="auraface+synthetic", effective_profile="auraface",
            declared_embedding_dimension=512, observed_embedding_dimension=None,
            preprocessing_id="synthetic-arcface", compatibility_sha256="a" * 64,
            config_sha256="b" * 64, sessions={}, frozen_preprocessing_spec={},
            execution_receipt=None, state="loaded_unexercised",
            reason_code="execution_missing", observed_at=NOW,
        ),
    )


def inputs(role="worker", process="worker-process", sequence=1, observations=None):
    return dict(
        role=role, process_instance_id=process, observation_sequence=sequence,
        captured_at=NOW,
        adapter_observations=tuple(observations or ()), source_identity=None,
        effective_settings=Record(runtime_mode="face_pipeline", profile="auraface"),
        serving_catalog=None,
    )


def build(**kwargs):
    module = producer()
    fn = getattr(module, "build_face_role_record", None)
    assert callable(fn), "CAUSAL_RED: missing build_face_role_record (ABI-09)"
    return plain(fn(**inputs(**kwargs)))


def test_positive_api_worker_pairs_keep_independent_retained_generations():
    api = build(role="api", process="api-process", observations=[observation("api-old", "api-adapter")])
    worker = build(observations=[observation("worker-old", "worker-adapter")])
    assert api["role"] == "api" and worker["role"] == "worker"
    assert api["process_instance_id"] != worker["process_instance_id"]
    a = api["adapter_observations"][0]["runtime_record"]
    w = worker["adapter_observations"][0]["runtime_record"]
    assert a["runtime_generation_id"] == "api-old"
    assert w["runtime_generation_id"] == "worker-old"
    assert a["compatibility_sha256"] == w["compatibility_sha256"]
    assert a["runtime_generation_id"] != w["runtime_generation_id"]
    assert a["observed_embedding_dimension"] is None
    assert a["state"] == w["state"] == "loaded_unexercised"


def test_multiple_api_generations_are_preserved_without_singleton_substitution():
    rows = [observation("api-old", "a"), observation("api-new", "b")]
    module = producer()
    raw = module.build_face_role_record(**inputs(role="api", process="api-process", observations=rows))
    rows[0]["runtime_record"]["runtime_generation_id"] = "mutated-input"
    result = plain(raw)
    assert {row["runtime_record"]["runtime_generation_id"] for row in result["adapter_observations"]} == {"api-old", "api-new"}
    assert result["adapter_observations"][0]["runtime_record"]["runtime_generation_id"] == "api-old"


def test_health_probe_is_never_a_serving_adapter():
    module = producer()
    options = complete_inputs()
    assert plain(module.build_face_role_record(**options))["collection_status"] == "complete"
    row = options["adapter_observations"][0]
    row["usage_origin"] = "health_probe_only"
    result = plain(module.build_face_role_record(**options))
    assert result["collection_status"] != "complete"
    assert not any(r["usage_origin"] == "serving" for r in result["adapter_observations"])


def test_absent_observations_source_and_catalog_remain_incomplete():
    result = build()
    assert result["source_identity"] is None
    assert result["serving_catalog"] is None
    assert result["adapter_observations"] == []
    assert result["collection_status"] == "incomplete"
    assert result["reason_code"]


@pytest.mark.parametrize("version", [None, 0, 2, True, "1"])
def test_unsupported_runtime_record_version_cannot_be_complete(version):
    module = producer()
    options = complete_inputs()
    baseline = plain(module.build_face_role_record(**options))
    assert baseline["collection_status"] == "complete"
    options["adapter_observations"][0]["runtime_record"]["producer_abi_version"] = version
    result = plain(module.build_face_role_record(**options))
    assert result["collection_status"] == "incomplete"
    assert result["reason_code"] == "incompatible_version"


@pytest.mark.parametrize("sequence", [-1, True, "1"])
def test_invalid_sequence_is_rejected(sequence):
    module = producer()
    with pytest.raises((ValueError, TypeError)):
        module.build_face_role_record(**inputs(sequence=sequence))


def test_repair_cannot_enter_loaded_role_publisher():
    module = producer()
    with pytest.raises((ValueError, TypeError)):
        module.build_face_role_record(**inputs(role="fix-blob-ownership"))


@pytest.mark.parametrize("field", ["connection_string", "authorization", "raw_environment"])
def test_unallowlisted_settings_are_rejected_or_excluded(field):
    module = producer()
    args = inputs()
    args["effective_settings"][field] = "REJECTED_SENTINEL"
    try:
        result = plain(module.build_face_role_record(**args))
    except (ValueError, TypeError):
        return
    serialized = json.dumps(result, sort_keys=True)
    assert "REJECTED_SENTINEL" not in serialized
    assert field not in result["effective_settings"]


def test_atomic_publication_uses_distinct_role_process_paths(tmp_path):
    module = producer()
    fn = getattr(module, "write_face_role_record", None)
    assert callable(fn), "CAUSAL_RED: missing write_face_role_record (ABI-15)"
    for role, process in [("api", "api-one"), ("api", "api-two"), ("worker", "worker-one")]:
        record = module.build_face_role_record(**inputs(role=role, process=process))
        fn(record, evidence_dir=tmp_path, max_record_bytes=16384, deadline_monotonic=time.monotonic() + 2)
    files = [p for p in tmp_path.iterdir() if p.is_file()]
    assert len(files) == 3
    records = [json.loads(p.read_text()) for p in files]
    assert {(r["role"], r["process_instance_id"]) for r in records} == {("api", "api-one"), ("api", "api-two"), ("worker", "worker-one")}
    assert all(p.stat().st_mode & 0o077 == 0 for p in files)
    assert all(r["producer_abi_version"] == 1 for r in records)


@pytest.mark.parametrize("expired,cap", [(True, 16384), (False, 1)])
def test_failed_publication_does_not_replace_previous_record(tmp_path, expired, cap):
    module = producer()
    fn = getattr(module, "write_face_role_record", None)
    assert callable(fn), "CAUSAL_RED: missing write_face_role_record (ABI-15)"
    record = module.build_face_role_record(**inputs())
    fn(record, evidence_dir=tmp_path, max_record_bytes=16384, deadline_monotonic=time.monotonic() + 2)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    next_record = module.build_face_role_record(**inputs(sequence=2))
    try:
        result = plain(fn(next_record, evidence_dir=tmp_path, max_record_bytes=cap,
                          deadline_monotonic=time.monotonic() + (-1 if expired else 2)))
    except (ValueError, TimeoutError):
        pass
    else:
        assert result["status"] != "complete"
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


def test_drifted_record_preserves_retained_loaded_hash_not_current_disk():
    module = producer()
    options = complete_inputs()
    row = options["adapter_observations"][0]
    runtime = row["runtime_record"]
    runtime["runtime_generation_id"] = "worker-old"
    for model, session_id, weight, license_hash in [
        ("yunet", "old-detector", "a", "c"),
        ("auraface", "old-embedder", "d", "e"),
    ]:
        runtime["sessions"][model].update(
            session_id=session_id, runtime_generation_id="worker-old",
            observed_weight_sha256=weight * 64, observed_license_sha256=license_hash * 64,
        )
    runtime["execution_receipt"].update(
        runtime_generation_id="worker-old", detector_session_id="old-detector",
        embedder_session_id="old-embedder",
    )
    assert plain(module.build_face_role_record(**options))["collection_status"] == "complete"
    row["runtime_record"]["state"] = "drifted"
    row["runtime_record"]["reason_code"] = "artifact_changed"
    result = plain(module.build_face_role_record(**options))
    retained = result["adapter_observations"][0]["runtime_record"]
    assert retained["state"] == "drifted"
    assert retained["sessions"]["auraface"]["observed_weight_sha256"] == "d" * 64
    assert retained["sessions"]["yunet"]["observed_license_sha256"] == "c" * 64
    assert result["collection_status"] != "complete"


def test_process_restart_has_new_transport_identity_and_preserves_old_record(tmp_path):
    module = producer()
    fn = getattr(module, "write_face_role_record", None)
    assert callable(fn), "CAUSAL_RED: missing write_face_role_record (ABI-15)"
    for process, sequence in [("old-worker", 12), ("new-worker", 1)]:
        record = module.build_face_role_record(**inputs(process=process, sequence=sequence))
        fn(record, evidence_dir=tmp_path, max_record_bytes=16384, deadline_monotonic=time.monotonic() + 2)
    records = [json.loads(path.read_text()) for path in tmp_path.iterdir() if path.is_file()]
    assert {(r["process_instance_id"], r["observation_sequence"]) for r in records} == {("old-worker", 12), ("new-worker", 1)}


def assert_offline_provider_imports(source, package):
    import ast

    node = ast.parse(source)
    imports = set()
    aliases = {}
    for entry in ast.walk(node):
        if isinstance(entry, ast.Import):
            for alias in entry.names:
                imports.add(alias.name)
                aliases[alias.asname or alias.name.split('.')[0]] = (
                    alias.name if alias.asname else alias.name.split('.')[0])
        elif isinstance(entry, ast.ImportFrom):
            module = importlib.util.resolve_name(
                '.' * entry.level + (entry.module or ''), package) if entry.level else entry.module
            if module:
                imports.add(module)
                for alias in entry.names:
                    name = module + '.' + alias.name
                    imports.add(name)
                    aliases[alias.asname or alias.name] = name

    def qualified(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return qualified(node.value) + '.' + node.attr
        return ''

    for entry in ast.walk(node):
        if isinstance(entry, ast.Attribute):
            imports.add(qualified(entry))
    calls = set()
    for entry in ast.walk(node):
        if isinstance(entry, ast.Call):
            name = qualified(entry.func)
            calls.add(name.rsplit('.', 1)[-1])
            imports.add(name)
            if name in {'importlib.import_module', '__import__'} and entry.args:
                target = entry.args[0]
                if isinstance(target, ast.Constant) and isinstance(target.value, str):
                    imports.add(importlib.util.resolve_name(target.value, package)
                                if target.value.startswith('.') else target.value)
    forbidden = (
        'onnxruntime', 'cv2', 'recognition.infrastructure.face_pipeline',
        'recognition.infrastructure.embeddings', 'recognition.infrastructure.embeddings.runtime_factory',
        'recognition.application.embedding.runtime_factory',
        'recognition.application.settings', 'recognition.config',
        'recognition.interface_adapters', 'shared.secrets',
        'db', 'api', 'requests', 'httpx', 'urllib', 'socket', 'asyncpg', 'psycopg',
        'sqlalchemy.create_engine', 'sqlalchemy.engine.create_engine',
        'sqlalchemy.engine.create.create_engine', 'sqlalchemy.engine_from_config',
        'sqlalchemy.engine.engine_from_config', 'sqlalchemy.engine.create.engine_from_config',
        'sqlalchemy.ext.asyncio.create_async_engine',
        'sqlalchemy.ext.asyncio.engine.create_async_engine',
        'sqlalchemy.ext.asyncio.async_engine_from_config',
    )
    assert not {name for name in imports
                if any(name == prefix or name.startswith(prefix + '.') for prefix in forbidden)}
    assert not calls & {'get_shared_face_pipeline_runtime', 'build_embedding_runtime',
                        'InferenceSession', 'get_observability_session', 'get_settings',
                        'create_engine', 'create_async_engine', 'engine_from_config',
                        'async_engine_from_config'}


def test_publisher_does_not_import_live_providers_or_construct_models():
    path = ROOT / "shared/face_role_snapshot.py"
    assert path.is_file(), "CAUSAL_RED: missing shared/face_role_snapshot.py (offline provider guard)"
    assert_offline_provider_imports(path.read_text(), "shared")
    producer()


def test_email_and_error_like_extra_settings_never_serialize():
    module = producer()
    args = inputs()
    args["effective_settings"]["contact"] = "rejected" + chr(64) + "invalid.example"
    args["effective_settings"]["exception"] = "REJECTED_ERROR_SENTINEL"
    try:
        result = plain(module.build_face_role_record(**args))
    except (ValueError, TypeError):
        return
    text = json.dumps(result)
    assert chr(64) not in text, "email-like input escaped allowlist"
    assert "REJECTED_ERROR_SENTINEL" not in text, "error input escaped allowlist"


def attested_observation(role):
    generation = role + "-generation"
    row = observation(generation, role + "-adapter")
    runtime = row["runtime_record"]
    runtime.update(state="attested", reason_code=None, observed_embedding_dimension=512)
    runtime["sessions"] = {}
    for model in ("yunet", "auraface"):
        runtime["sessions"][model] = Record(
            session_id=role + "-" + model, runtime_generation_id=generation,
            logical_model_name=model, constructed_at=NOW,
            observed_weight_sha256="1" * 64, observed_weight_size_bytes=16,
            observed_license_sha256="2" * 64, observed_license_size_bytes=8,
            manifest_expectation_sha256="3" * 64, frozen_preprocessing_sha256="4" * 64,
            numeric_runtime_fingerprint={}, actual_providers=["CPUExecutionProvider"],
            actual_input_metadata=[], actual_output_metadata=[], actual_session_options={},
            graph_analysis=Record(sha256="5" * 64, synthetic=True),
        )
    runtime["execution_receipt"] = Record(
        execution_id=role + "-execution", runtime_generation_id=generation,
        detector_session_id=role + "-yunet", embedder_session_id=role + "-auraface",
        captured_at=NOW, input_lineage=Record(fixture_id="synthetic",
            fixture_sha256="6" * 64, independent_reference_sha256="7" * 64),
        detector_input=Record(sha256="8" * 64, shape=[1, 3, 8, 8], dtype="float32",
                              contiguous=True, padding_geometry={}),
        detections_sha256="9" * 64,
        alignment=Record(landmarks_sha256="a" * 64, executing_spec_sha256="4" * 64,
                         template_sha256="b" * 64, affine_sha256="c" * 64, crop_sha256="d" * 64),
        embedder_input=Record(sha256="e" * 64, shape=[1, 3, 112, 112], dtype="float32",
                             contiguous=True, channel_samples=[], mean=127.5, scale=0.0078125),
        raw_output=Record(sha256="f" * 64, dimension=512, norm=2.0),
        normalized_output=Record(sha256="0" * 64, dimension=512, norm=1.0),
        graph_analysis_sha256="5" * 64, completion="complete",
    )
    return row


def complete_inputs():
    path = ROOT / "shared/source_identity.py"
    assert path.is_file(), "CAUSAL_RED: missing shared/source_identity.py (ABI-11)"
    source_module = importlib.import_module("shared.source_identity")
    source_type = getattr(source_module, "SourceIdentityV1", None)
    assert callable(source_type), "CAUSAL_RED: missing SourceIdentityV1 (ABI-11)"
    options = inputs(observations=[attested_observation("worker")])
    options["source_identity"] = source_type(
        source_identity_version=1, source_git_sha="1" * 40, source_tree="2" * 40,
        build_context_manifest_sha256="3" * 64, service_lock_sha256="4" * 64,
        image_variant="recognition", build_time="2026-01-01T00:00:00Z",
        identity_document_sha256="5" * 64,
    )
    # F09: preserve the catalog producer's transport type using only inert rows.
    from recognition.tests.unit.test_face_acceptance_catalog_capture import ServingSession, args, capture
    options["serving_catalog"] = asyncio.run(capture()(ServingSession(), **args()))
    return options


def replace_transport(record, **changes):
    if dataclasses.is_dataclass(record):
        return dataclasses.replace(record, **changes)
    if hasattr(record, "model_copy"):
        return record.model_copy(update=changes)
    return Record(record, **changes)


@pytest.mark.parametrize('subject', ['complete', 'healthy_pair'])
def test_positive_fixtures_preserve_producer_transport_types(tmp_path, monkeypatch, subject):
    """F09: a type-strict publisher must accept both positive fixture seams."""
    from types import ModuleType, SimpleNamespace
    from recognition.tests.unit import test_face_acceptance_catalog_capture as catalog_tests

    source_type = dataclasses.make_dataclass(
        'FixtureSource', [(name, object) for name in identity_args()], frozen=True)
    source_module = ModuleType('shared.source_identity')
    source_module.SourceIdentityV1 = source_type
    monkeypatch.setitem(sys.modules, 'shared.source_identity', source_module)
    (tmp_path / 'shared').mkdir()
    (tmp_path / 'shared/source_identity.py').touch()
    monkeypatch.setattr(sys.modules[__name__], 'ROOT', tmp_path)
    catalog_type = dataclasses.make_dataclass('FixtureCatalog', [('status', str), ('columns', tuple)], frozen=True)
    catalog = catalog_type('complete', tuple(Record(table_name=f'table_{i}', dimensions=512)
                                             for i in range(4)))

    async def capture_catalog(session, **options):
        assert isinstance(session, catalog_tests.ServingSession)
        assert options['role'] == 'worker'
        return catalog

    monkeypatch.setattr(catalog_tests, 'capture', lambda: capture_catalog)
    if subject == 'complete':
        options = complete_inputs()
        assert type(options['source_identity']) is source_type
        assert options['serving_catalog'] is catalog
        assert len(options['serving_catalog'].columns) == 4
    else:
        seen = []

        def build_strict(**options):
            assert type(options['source_identity']) is source_type
            seen.append(options['role'])
            return Record(options, collection_status='incomplete')

        monkeypatch.setattr(sys.modules[__name__], 'producer',
                            lambda: SimpleNamespace(build_face_role_record=build_strict))
        test_healthy_synthetic_role_pair_keeps_receipt_session_generation_joins()
        assert seen == ['api', 'worker']


def test_complete_synthetic_source_catalog_and_attested_observation():
    """Transport control only; all store and receipt evidence is synthetic."""
    module = producer()
    result = plain(module.build_face_role_record(**complete_inputs()))
    assert result["collection_status"] == "complete"
    assert result["reason_code"] is None
    assert result["source_identity"]["source_tree"] == "2" * 40
    assert result["serving_catalog"]["status"] == "complete"
    assert result["adapter_observations"][0]["runtime_record"]["state"] == "attested"


def test_healthy_synthetic_role_pair_keeps_receipt_session_generation_joins():
    """Positive transport control; synthetic receipts do not prove real execution."""
    module = producer()
    records = []
    for role in ("api", "worker"):
        row = attested_observation(role)
        args = inputs(role=role, process=role + "-process", observations=[row])
        args["source_identity"] = source_producer().SourceIdentityV1(
            source_identity_version=1, source_git_sha="1" * 40, source_tree="2" * 40,
            build_context_manifest_sha256="3" * 64, service_lock_sha256="4" * 64,
            image_variant="recognition", build_time="2026-01-01T00:00:00Z",
            identity_document_sha256="5" * 64,
        )
        records.append(plain(module.build_face_role_record(**args)))
    for record in records:
        role = record["role"]
        runtime = record["adapter_observations"][0]["runtime_record"]
        receipt = runtime["execution_receipt"]
        assert runtime["state"] == "attested"
        assert runtime["observed_embedding_dimension"] == 512
        assert receipt["runtime_generation_id"] == runtime["runtime_generation_id"] == role + "-generation"
        assert receipt["detector_session_id"] == runtime["sessions"]["yunet"]["session_id"]
        assert receipt["embedder_session_id"] == runtime["sessions"]["auraface"]["session_id"]
        assert receipt["raw_output"]["norm"] == 2.0
        assert receipt["normalized_output"]["norm"] == 1.0
        # Catalog is deliberately uncaptured: a healthy receipt cannot fill it.
        assert record["serving_catalog"] is None
        assert record["collection_status"] == "incomplete"


@pytest.mark.parametrize("process", ["../escape", "nested/process", "/absolute", "..\\escape"])
def test_process_instance_id_cannot_traverse_publication_directory(tmp_path, process):
    module = producer()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    sentinel = tmp_path / "escape"
    sentinel.write_bytes(b"unchanged")
    before = {path.relative_to(tmp_path): path.read_bytes()
              for path in tmp_path.rglob("*") if path.is_file()}
    try:
        record = module.build_face_role_record(**inputs(process=process))
        result = plain(module.write_face_role_record(
            record, evidence_dir=evidence, max_record_bytes=16384,
            deadline_monotonic=time.monotonic() + 2,
        ))
    except (ValueError, TypeError):
        pass
    else:
        assert result["status"] != "complete"
    after = {path.relative_to(tmp_path): path.read_bytes()
             for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


def test_record_double_supports_attribute_protocol_and_copy():
    import copy
    row = Record(nested=Record(value=1))
    assert not hasattr(row, "missing")
    assert getattr(row, "missing", None) is None
    with pytest.raises(AttributeError):
        row.missing
    assert copy.deepcopy(row) == row


def source_producer():
    path = ROOT / 'shared/source_identity.py'
    assert path.is_file(), 'CAUSAL_RED: missing shared/source_identity.py (ABI-11)'
    return importlib.import_module('shared.source_identity')


def identity_args():
    return dict(source_identity_version=1, source_git_sha='1' * 40, source_tree='2' * 40,
                build_context_manifest_sha256='3' * 64, service_lock_sha256='4' * 64,
                image_variant='recognition', build_time='2026-01-01T00:00:00Z',
                identity_document_sha256='5' * 64)


def baked_document():
    import hashlib
    document = identity_args()
    del document['identity_document_sha256']
    digest = hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return dict(document, identity_document_sha256=digest)


def loader(module):
    fn = getattr(module, 'load_baked_source_identity', None)
    assert callable(fn), 'CAUSAL_RED: missing load_baked_source_identity (ABI-11)'
    return fn


def clear_source_environment(monkeypatch):
    for name in ('GIT_COMMIT_SHA', 'APP_GIT_COMMIT_SHA', 'SOURCE_TREE',
                 'BUILD_CONTEXT_MANIFEST_SHA256', 'SERVICE_LOCK_SHA256', 'IMAGE_VARIANT', 'BUILD_TIME'):
        monkeypatch.delenv(name, raising=False)


def test_source_loader_preserves_valid_document(tmp_path, monkeypatch):
    module = source_producer()
    clear_source_environment(monkeypatch)
    path = tmp_path / 'identity.json'
    document = baked_document()
    path.write_text(json.dumps(document))
    assert plain(loader(module)(path)) == document


@pytest.mark.parametrize('fault', ['missing', 'malformed', 'array', 'extra', 'version',
                                   'missing_tree', 'bad_digest', 'environment_conflict'])
def test_source_loader_refuses_invalid_or_conflicting_document(tmp_path, monkeypatch, fault):
    module = source_producer()
    clear_source_environment(monkeypatch)
    path = tmp_path / 'identity.json'
    document = baked_document()
    if fault == 'extra':
        document['raw_environment'] = 'REJECTED_SENTINEL'
    elif fault == 'version':
        document['source_identity_version'] = True
    elif fault == 'missing_tree':
        del document['source_tree']
    elif fault == 'bad_digest':
        document['identity_document_sha256'] = '0' * 64
    elif fault == 'environment_conflict':
        monkeypatch.setenv('APP_GIT_COMMIT_SHA', '9' * 40)
    if fault != 'missing':
        path.write_text('{broken' if fault == 'malformed' else
                        '[]' if fault == 'array' else json.dumps(document))
    try:
        result = loader(module)(path)
    except (ValueError, TypeError, OSError):
        return
    assert result is None, 'invalid baked identity was accepted'


@pytest.mark.parametrize('field,value', [
    ('source_identity_version', 1.0), ('source_git_sha', 'z' * 40),
    ('source_tree', '2' * 39), ('build_context_manifest_sha256', 'z' * 64),
    ('service_lock_sha256', ''), ('identity_document_sha256', 'not-a-digest'),
    ('image_variant', 'unknown'), ('build_time', 'not-a-time'),
])
def test_source_identity_constructor_guards(field, value):
    module = source_producer()
    options = identity_args()
    options[field] = value
    with pytest.raises((ValueError, TypeError)):
        module.SourceIdentityV1(**options)


def identity_writer(module):
    fn = getattr(module, 'write_baked_source_identity', None)
    assert callable(fn), 'CAUSAL_RED: missing write_baked_source_identity (ABI-11 writer seam)'
    return fn


def test_source_writer_round_trip_has_readonly_mode(tmp_path, monkeypatch):
    module = source_producer()
    clear_source_environment(monkeypatch)
    path = tmp_path / 'identity.json'
    options = identity_args()
    del options['identity_document_sha256']
    identity_writer(module)(path, **options)
    assert path.stat().st_mode & 0o777 == 0o444
    result = plain(loader(module)(path))
    assert result is not None
    assert {key: result[key] for key in options} == options
    assert result['identity_document_sha256'] == baked_document()['identity_document_sha256']


@pytest.mark.parametrize('fault', ['missing_tree', 'bad_lock', 'extra', 'symlink', 'replace_failure'])
def test_source_writer_refuses_invalid_binding_and_preserves_previous(tmp_path, monkeypatch, fault):
    module = source_producer()
    options = identity_args()
    del options['identity_document_sha256']
    path = tmp_path / 'identity.json'
    old = b'previous-baked-document'
    target = tmp_path / 'target'
    if fault == 'symlink':
        target.write_bytes(old)
        path.symlink_to(target)
    else:
        path.write_bytes(old)
    if fault == 'missing_tree':
        del options['source_tree']
    elif fault == 'bad_lock':
        options['service_lock_sha256'] = 'invalid'
    elif fault == 'extra':
        options['raw_environment'] = 'REJECTED_SENTINEL'
    elif fault == 'replace_failure':
        import os
        def fail_replace(*args, **kwargs):
            raise OSError('synthetic replacement refusal')
        monkeypatch.setattr(os, 'replace', fail_replace)
    try:
        identity_writer(module)(path, **options)
    except (ValueError, TypeError, OSError):
        pass
    else:
        pytest.fail('invalid source publication was accepted')
    assert path.read_bytes() == old
    if fault == 'symlink':
        assert path.is_symlink()
        assert target.read_bytes() == old
    assert {p.name for p in tmp_path.iterdir()} == ({'identity.json', 'target'} if fault == 'symlink' else {'identity.json'})


def repair_inputs():
    return dict(producer_abi_version=1, role='fix-blob-ownership', captured_at=NOW,
                repair_invocation_id='repair-run', source_identity=source_producer().SourceIdentityV1(**identity_args()),
                image_record=Record(role='fix-blob-ownership', registry_manifest_digest='sha256:' + '6' * 64,
                                    digest_type='manifest', platform='linux/amd64',
                                    image_config_digest='sha256:' + '7' * 64, identity_document_sha256='5' * 64),
                collection_status='complete', reason_code=None)


@pytest.mark.parametrize('fault', ['version', 'role', 'invocation', 'source', 'image_missing',
    'image_extra', 'image_role', 'manifest_digest', 'digest_type', 'platform',
    'config_digest', 'document_join', 'loaded_field', 'nested_loaded_field'])
def test_repair_identity_guards_each_start_from_complete(fault):
    module = producer()
    cls = getattr(module, 'RepairIdentityRecordV1', None)
    assert callable(cls), 'CAUSAL_RED: missing RepairIdentityRecordV1 (ABI-11)'
    options = repair_inputs()
    assert plain(cls(**options))['collection_status'] == 'complete'
    if fault == 'version':
        options['producer_abi_version'] = True
    elif fault == 'role':
        options['role'] = 'worker'
        options['image_record']['role'] = 'worker'
    elif fault == 'invocation':
        options['repair_invocation_id'] = ''
    elif fault == 'source':
        options['source_identity'] = None
    elif fault == 'image_missing':
        options['image_record'] = None
    elif fault == 'image_extra':
        options['image_record']['uncontrolled'] = 'REJECTED_SENTINEL'
    elif fault == 'image_role':
        options['image_record']['role'] = 'api'
    elif fault == 'manifest_digest':
        options['image_record']['registry_manifest_digest'] = 'mutable-tag'
    elif fault == 'digest_type':
        options['image_record']['digest_type'] = 'config'
    elif fault == 'platform':
        options['image_record']['platform'] = ''
    elif fault == 'config_digest':
        options['image_record']['image_config_digest'] = 'mutable-tag'
    elif fault == 'document_join':
        options['image_record']['identity_document_sha256'] = '9' * 64
    elif fault == 'loaded_field':
        options['sessions'] = {}
    elif fault == 'nested_loaded_field':
        options['image_record']['metadata'] = {'sessions': {'yunet': {}}}
    try:
        result = plain(cls(**options))
    except (ValueError, TypeError):
        return
    assert result['collection_status'] != 'complete'


@pytest.mark.parametrize('fault', ['source', 'rows', 'catalog', 'catalog_status', 'catalog_role',
    'catalog_process', 'origin', 'inactive', 'state', 'dimension', 'receipt_missing',
    'receipt_completion', 'receipt_generation', 'detector_join', 'embedder_join',
    'detector_generation', 'embedder_generation', 'sessions_missing', 'runtime_version'])
def test_each_completion_conjunct_refuses_its_own_negative(fault):
    module = producer()
    options = complete_inputs()
    assert plain(module.build_face_role_record(**options))['collection_status'] == 'complete'
    row = options['adapter_observations'][0]
    runtime = row['runtime_record']
    if fault == 'source':
        options['source_identity'] = None
    elif fault == 'rows':
        options['adapter_observations'] = ()
    elif fault == 'catalog':
        options['serving_catalog'] = None
    elif fault.startswith('catalog_'):
        field = {'catalog_status': 'status', 'catalog_role': 'role',
                 'catalog_process': 'process_instance_id'}[fault]
        try:
            options['serving_catalog'] = replace_transport(
                options['serving_catalog'], **{field: 'contradictory'})
        except (ValueError, TypeError):
            return
    elif fault == 'origin':
        row['usage_origin'] = 'unregistered'
    elif fault == 'inactive':
        row['active'] = False
    elif fault == 'state':
        runtime['state'] = 'loaded_unexercised'
    elif fault == 'dimension':
        runtime['observed_embedding_dimension'] = None
    elif fault == 'receipt_missing':
        runtime['execution_receipt'] = None
    elif fault == 'receipt_completion':
        runtime['execution_receipt']['completion'] = 'incomplete'
    elif fault == 'receipt_generation':
        runtime['execution_receipt']['runtime_generation_id'] = 'other-generation'
    elif fault in {'detector_join', 'embedder_join'}:
        runtime['execution_receipt']['detector_session_id' if fault == 'detector_join' else 'embedder_session_id'] = 'other-session'
    elif fault in {'detector_generation', 'embedder_generation'}:
        runtime['sessions']['yunet' if fault == 'detector_generation' else 'auraface']['runtime_generation_id'] = 'other-generation'
    elif fault == 'sessions_missing':
        del runtime['sessions']['yunet']
    elif fault == 'runtime_version':
        runtime['producer_abi_version'] = 1.0
    result = plain(module.build_face_role_record(**options))
    assert result['collection_status'] == 'incomplete', fault


@pytest.mark.parametrize('version', [None, 0, 2, True, '1', 1.0])
def test_role_record_constructor_has_exact_version_guard(version):
    module = producer()
    raw = module.build_face_role_record(**inputs())
    assert plain(raw)['producer_abi_version'] == 1
    with pytest.raises((ValueError, TypeError)):
        dataclasses.replace(raw, producer_abi_version=version)


@pytest.mark.parametrize('process', ['../escape', 'nested/process', '/absolute', '..\\escape'])
def test_role_record_constructor_rejects_traversal_before_any_writer(process):
    module = producer()
    raw = module.build_face_role_record(**inputs())
    with pytest.raises((ValueError, TypeError)):
        dataclasses.replace(raw, process_instance_id=process)
    with pytest.raises((ValueError, TypeError)):
        module.build_face_role_record(**inputs(process=process))


@pytest.mark.parametrize('shape', ['mapping', 'list', 'tuple', 'dataclass'])
def test_publisher_recursively_copies_caller_inputs_before_serialization(shape):
    module = producer()
    options = complete_inputs()
    session = options['adapter_observations'][0]['runtime_record']['sessions']['yunet']
    if shape == 'mapping':
        value = {'nested': {'threads': 1}}
        mutate = lambda: value['nested'].update(threads=9)
    elif shape == 'list':
        value = [{'threads': 1}]
        mutate = lambda: value[0].update(threads=9)
    elif shape == 'tuple':
        value = ({'threads': 1},)
        mutate = lambda: value[0].update(threads=9)
    else:
        @dataclasses.dataclass
        class Options:
            threads: int = 1
        value = Options()
        mutate = lambda: setattr(value, 'threads', 9)
    session['actual_session_options'] = value
    raw = module.build_face_role_record(**options)
    before = plain(raw)
    mutate()
    assert plain(raw) == before


def publication(module, record, directory, **changes):
    options = dict(evidence_dir=directory, max_record_bytes=32768,
                   deadline_monotonic=time.monotonic() + 2)
    options.update(changes)
    return module.write_face_role_record(record, **options)


@pytest.mark.parametrize('fault', ['version', 'role', 'process', 'cap_bool', 'cap_float',
                                   'cap_string', 'cap_zero', 'deadline_nan', 'deadline_inf'])
def test_publication_revalidates_envelope_and_resource_guards(tmp_path, fault):
    module = producer()
    record = module.build_face_role_record(**inputs())
    changes = {}
    if fault in {'version', 'role', 'process'}:
        object.__setattr__(record, {'version': 'producer_abi_version', 'role': 'role',
                                  'process': 'process_instance_id'}[fault],
                           {'version': True, 'role': 'repair', 'process': '..\\escape'}[fault])
    else:
        name = 'max_record_bytes' if fault.startswith('cap_') else 'deadline_monotonic'
        changes[name] = {'cap_bool': True, 'cap_float': 32768.0, 'cap_string': '32768',
                         'cap_zero': 0, 'deadline_nan': float('nan'), 'deadline_inf': float('inf')}[fault]
    try:
        result = plain(publication(module, record, tmp_path, **changes))
    except (ValueError, TypeError, TimeoutError):
        pass
    else:
        assert result['status'] != 'complete'
    assert list(tmp_path.iterdir()) == []


def test_publication_expired_deadline_precedes_directory_or_serialization(tmp_path, monkeypatch):
    module = producer()
    record = module.build_face_role_record(**inputs())
    def forbidden(*args, **kwargs):
        pytest.fail('publication performed work before checking its expired deadline')
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'mkdir', forbidden)
        patch.setattr(json, 'dumps', forbidden)
        try:
            result = plain(publication(module, record, tmp_path / 'evidence', deadline_monotonic=time.monotonic() - 1))
        except (ValueError, TimeoutError):
            pass
        else:
            assert result['status'] != 'complete'
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('failure', ['replace', 'fsync'])
def test_publication_is_atomic_and_cleans_temporary_file_on_failure(tmp_path, monkeypatch, failure):
    import os
    module = producer()
    assert plain(publication(module, module.build_face_role_record(**inputs()), tmp_path))['status'] == 'complete'
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    seen = []
    original_replace = os.replace
    def replace(source, destination):
        assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.name in before} == before
        assert Path(source).stat().st_mode & 0o777 == 0o600
        seen.append('replace')
        if failure == 'replace':
            raise OSError('synthetic replace failure')
        original_replace(source, destination)
    def fsync(fd):
        seen.append('fsync')
        if failure == 'fsync':
            raise OSError('synthetic fsync failure')
    with monkeypatch.context() as patch:
        patch.setattr(os, 'replace', replace)
        patch.setattr(os, 'fsync', fsync)
        try:
            result = plain(publication(module, module.build_face_role_record(**inputs(sequence=2)), tmp_path))
        except OSError:
            pass
        else:
            assert result['status'] != 'complete'
    assert failure in seen
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_pending_parent_git_commit_sha_alone_has_no_complete_identity(tmp_path, monkeypatch):
    """PENDING_PARENT c79-face-g2-src-identity-r2; RLSE-08, no ENV backfill."""
    module = source_producer()
    clear_source_environment(monkeypatch)
    monkeypatch.setenv('GIT_COMMIT_SHA', '1' * 40)
    identity = loader(module)(tmp_path / 'missing-source-identity.json')
    assert identity is None
    publisher = producer()
    options = complete_inputs()
    assert plain(publisher.build_face_role_record(**options))['collection_status'] == 'complete'
    options['source_identity'] = identity
    assert plain(publisher.build_face_role_record(**options))['collection_status'] == 'incomplete'


@pytest.mark.parametrize('captured_at', [None, '2026-01-01T00:00:00Z', 0, datetime(2026, 1, 1)])
@pytest.mark.parametrize('subject', ['role', 'repair'])
def test_pending_parent_invalid_capture_time_is_never_complete(subject, captured_at):
    """PENDING_PARENT c79-face-g2-src-identity-r2; capture must be timezone-aware."""
    module = producer()
    options = complete_inputs() if subject == 'role' else repair_inputs()
    constructor = module.build_face_role_record if subject == 'role' else module.RepairIdentityRecordV1
    assert plain(constructor(**options))['collection_status'] == 'complete'
    options['captured_at'] = captured_at
    try:
        result = plain(constructor(**options))
    except (ValueError, TypeError):
        return
    assert result['collection_status'] != 'complete'


@pytest.mark.parametrize("source", ['import recognition.config as forbidden',
 'from recognition.application.embedding.runtime_factory import make as forbidden',
 'from recognition.interface_adapters.http.deps.services import provider as forbidden',
 'from recognition.config import get_settings as forbidden',
 'import recognition.interface_adapters.http.deps.session as forbidden',
 'from recognition.interface_adapters.http.deps.session import '
 'get_observability_session as forbidden',
 'from sqlalchemy import create_engine as forbidden',
 'from sqlalchemy.ext.asyncio import create_async_engine as forbidden',
 'from sqlalchemy import engine_from_config as forbidden',
 'import sqlalchemy as sa\nfactory = sa.create_engine\nfactory()',
 'import sqlalchemy.ext.asyncio as sa\nfactory = sa.create_async_engine\nfactory()',
 'import importlib as loader\nloader.import_module("recognition.config")',
 'from importlib import import_module as load\nload(".secrets")',
 '__import__("onnxruntime")',
 'get_shared_face_pipeline_runtime()', 'build_embedding_runtime()', 'InferenceSession()',
 'get_observability_session()', 'get_settings()', 'create_engine()',
 'create_async_engine()', 'engine_from_config()', 'async_engine_from_config()',
 'from .secrets import forbidden'])

def test_provider_guard_detects_aliases_and_relative_imports(source):
    with pytest.raises(AssertionError):
        assert_offline_provider_imports(source, 'shared')


@pytest.mark.parametrize('source', ['import json\njson.dumps({})',
                                  'from .source_identity import SourceIdentityV1',
                                  'from sqlalchemy import text\ntext("select 1")'])
def test_provider_guard_accepts_offline_transport_helpers(source):
    assert_offline_provider_imports(source, 'shared')


@pytest.mark.parametrize('subject', ['role', 'repair'])
def test_pending_parent_missing_capture_time_cannot_be_complete(subject):
    """PENDING_PARENT c79-face-g2-src-identity-r2; no synthesized capture time."""
    module = producer()
    options = complete_inputs() if subject == 'role' else repair_inputs()
    constructor = module.build_face_role_record if subject == 'role' else module.RepairIdentityRecordV1
    assert plain(constructor(**options))['collection_status'] == 'complete'
    del options['captured_at']
    with pytest.raises((ValueError, TypeError)):
        constructor(**options)


@pytest.mark.parametrize('field,value', [('source_identity_version', True), ('source_tree', ''),
    ('build_context_manifest_sha256', 'invalid'), ('service_lock_sha256', None)])
@pytest.mark.parametrize('subject', ['role', 'repair'])
def test_publishers_refuse_structural_source_with_invalid_binding(subject, field, value):
    module = producer()
    options = complete_inputs() if subject == 'role' else repair_inputs()
    constructor = module.build_face_role_record if subject == 'role' else module.RepairIdentityRecordV1
    assert plain(constructor(**options))['collection_status'] == 'complete'
    source = Record(identity_args())
    source[field] = value
    options['source_identity'] = source
    try:
        result = plain(constructor(**options))
    except (ValueError, TypeError):
        return
    assert result['collection_status'] != 'complete'


def test_publication_deadline_expiring_during_fsync_keeps_previous_record(tmp_path, monkeypatch):
    import os
    module = producer()
    assert plain(publication(module, module.build_face_role_record(**inputs()), tmp_path))['status'] == 'complete'
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    record = module.build_face_role_record(**inputs(sequence=2))
    clock = [time.monotonic()]
    deadline = clock[0] + 1
    def fsync(fd):
        clock[0] = deadline + 1
    with monkeypatch.context() as patch:
        patch.setattr(time, 'monotonic', lambda: clock[0])
        patch.setattr(os, 'fsync', fsync)
        try:
            result = plain(publication(module, record, tmp_path, deadline_monotonic=deadline))
        except (ValueError, TimeoutError):
            pass
        else:
            assert result['status'] != 'complete'
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def canonical_manifest_model_id():
    import ast
    from recognition.application.embedding.manifest import EmbeddingModelManifest
    from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST, NumericRuntimeFingerprint

    # Execute the production manifest factory without importing its native adapter graph.
    path = ROOT / 'recognition/infrastructure/embeddings/face_pipeline_adapter.py'
    node = next(node for node in ast.parse(path.read_text()).body
                if isinstance(node, ast.FunctionDef) and node.name == 'auraface_embedding_model_manifest')
    namespace = {'EmbeddingModelManifest': EmbeddingModelManifest, 'MODEL_MANIFEST': MODEL_MANIFEST}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    fingerprint = NumericRuntimeFingerprint(
        opencv_version='0.1.2', opencv_major=0, onnxruntime_version='3.4.5', numpy_version='6.7.8',
        scipy_version='fixture', pillow_version='fixture', hdbscan_version='fixture',
        pgvector_version='fixture',
    )
    return namespace['auraface_embedding_model_manifest'](_fingerprint=fingerprint).model_id


@pytest.mark.parametrize('complete', [True, False])
def test_canonical_manifest_model_id_survives_publication(tmp_path, complete):
    module = producer()
    options = complete_inputs()
    model_id = canonical_manifest_model_id()
    options['adapter_observations'][0]['runtime_record']['model_id'] = model_id
    catalog = options['serving_catalog']
    assert catalog.columns
    options['serving_catalog'] = replace_transport(
        catalog, columns=tuple(dict(column, model_ids=[model_id]) for column in catalog.columns))
    if not complete:
        options['adapter_observations'][0]['runtime_record']['state'] = 'loaded_unexercised'
    record = module.build_face_role_record(**options)
    assert record.collection_status == ('complete' if complete else 'incomplete')
    result = publication(module, record, tmp_path)
    saved = json.loads(Path(result.path).read_text())
    assert saved['adapter_observations'][0]['runtime_record']['model_id'] == model_id
    assert all(column['model_ids'] == [model_id] for column in saved['serving_catalog']['columns'])


def test_canonical_manifest_model_id_in_producer_dataclass(tmp_path):
    from recognition.infrastructure.face_pipeline.loaded_session import AdapterObservationV1, LoadedRuntimeRecordV1

    module = producer()
    row = observation('fixture-generation', 'fixture-adapter')
    model_id = canonical_manifest_model_id()
    row['runtime_record'].update(model_id=model_id, frozen_preprocessing_spec=None)
    row['runtime_record'] = LoadedRuntimeRecordV1(**row['runtime_record'])
    options = complete_inputs()
    options['adapter_observations'] = (AdapterObservationV1(**row),)
    record = module.build_face_role_record(**options)
    assert record.collection_status == 'incomplete'
    assert record.adapter_observations[0]['runtime_record']['model_id'] == model_id
    result = publication(module, record, tmp_path)
    saved = json.loads(Path(result.path).read_text())
    assert saved['adapter_observations'][0]['runtime_record']['model_id'] == model_id


@pytest.mark.parametrize('field', ['model_id', 'model_ids'])
@pytest.mark.parametrize('fault', [
    'control', 'newline', 'slash', 'backslash', 'traversal', 'extra_component',
    'missing_component', 'zero_dimension', 'noninteger_dimension', 'extra_at',
    'mail_shape', 'long_string',
])
def test_model_lineage_grammar_refuses_unsafe_strings(field, fault):
    module = producer()
    model_id = canonical_manifest_model_id()
    value = {
        'control': model_id + chr(0), 'newline': model_id + chr(10),
        'slash': '/' + model_id, 'backslash': model_id.replace('/', chr(92)),
        'traversal': '../' + model_id, 'extra_component': model_id + '/extra',
        'missing_component': model_id.rsplit('/', 1)[0],
        'zero_dimension': model_id.replace('@512d', '@0d'),
        'noninteger_dimension': model_id.replace('@512d', '@widthd'),
        'extra_at': model_id.replace('@', '@@'),
        'mail_shape': 'fixture' + chr(64) + 'invalid.example',
        'long_string': 'x' * 16385,
    }[fault]
    options = inputs(observations=[observation('generation', 'adapter')])
    options['adapter_observations'][0]['runtime_record'][field] = [value] if field == 'model_ids' else value
    with pytest.raises(ValueError, match='unsafe_record_string'):
        module.build_face_role_record(**options)


@pytest.mark.parametrize('field', ['reason_code', 'adapter_instance_id', 'profile', 'mapping_key'])
def test_non_model_fields_keep_at_sign_refusal(field):
    module = producer()
    options = inputs(observations=[observation('generation', 'adapter')])
    value = canonical_manifest_model_id()
    if field == 'profile':
        options['effective_settings'][field] = value
    elif field == 'mapping_key':
        options['adapter_observations'][0][value] = 'fixture'
    else:
        options['adapter_observations'][0][field] = value
    with pytest.raises(ValueError, match='unsafe_record_string'):
        module.build_face_role_record(**options)


# GTMC-C80A-G2S-M02 / TEST-15: these controls bind current source guards.
@pytest.mark.parametrize('fault', ['depth', 'wide_mapping', 'wide_list', 'wide_tuple',
    'long_string', 'nonfinite', 'naive_nested', 'unsafe_nested', 'nonstring_key'])
def test_structural_transport_limits_reject_before_publication(fault):
    module = producer()
    options = inputs()
    value = {'threads': 1}
    if fault == 'depth':
        for _ in range(34):
            value = {'nested': value}
    elif fault == 'wide_mapping':
        value = {str(i): i for i in range(1025)}
    elif fault == 'wide_list':
        value = [0] * 1025
    elif fault == 'wide_tuple':
        value = (0,) * 1025
    elif fault == 'long_string':
        value = 'x' * 16385
    elif fault == 'nonfinite':
        value = float('nan')
    elif fault == 'naive_nested':
        value = datetime(2026, 1, 1)
    elif fault == 'unsafe_nested':
        value = {'nested': {'password': 'REJECTED_SENTINEL'}}
    elif fault == 'nonstring_key':
        value = {1: 'synthetic'}
    options['effective_settings']['actual_session_options'] = value
    with pytest.raises(ValueError):
        module.build_face_role_record(**options)


@pytest.mark.parametrize('fault', ['settings_shape', 'rows_mapping', 'rows_scalar',
    'source_binding', 'runtime_version'])
def test_builder_rejects_invalid_envelope_with_named_reason(fault):
    module = producer()
    options = complete_inputs()
    reason = {'settings_shape': 'unallowlisted_settings', 'rows_mapping': 'invalid_observations',
              'rows_scalar': 'invalid_observations', 'source_binding': 'invalid_build_binding',
              'runtime_version': 'incompatible_version'}[fault]
    if fault == 'settings_shape':
        options['effective_settings'] = []
    elif fault == 'rows_mapping':
        options['adapter_observations'] = {}
    elif fault == 'rows_scalar':
        options['adapter_observations'] = [1]
    elif fault == 'source_binding':
        options['source_identity'] = Record(identity_args(), source_tree='invalid')
    else:
        options['adapter_observations'][0]['runtime_record']['producer_abi_version'] = 1.0
    if fault == 'runtime_version':
        record = module.build_face_role_record(**options)
        assert record.collection_status == 'incomplete'
        assert record.reason_code == 'incompatible_version'
    else:
        with pytest.raises(ValueError, match=reason):
            module.build_face_role_record(**options)


@pytest.mark.parametrize('fault', ['runtime_shape', 'runtime_version', 'generation',
    'receipt_shape', 'sessions_shape', 'extra_session', 'session_shape', 'empty_session_id',
    'dimension_bool', 'dimension_zero', 'dimension_mismatch', 'origin', 'active'])
def test_attested_predicate_has_positive_control_and_independent_negative(fault):
    module = producer()
    row = plain(attested_observation('worker'))
    assert module._attested(row) is True
    runtime = row['runtime_record']
    if fault == 'runtime_shape':
        row['runtime_record'] = []
    elif fault == 'runtime_version':
        runtime['producer_abi_version'] = True
    elif fault == 'generation':
        runtime['runtime_generation_id'] = ''
    elif fault == 'receipt_shape':
        runtime['execution_receipt'] = []
    elif fault == 'sessions_shape':
        runtime['sessions'] = []
    elif fault == 'extra_session':
        runtime['sessions']['extra'] = {}
    elif fault == 'session_shape':
        runtime['sessions']['yunet'] = []
    elif fault == 'empty_session_id':
        runtime['sessions']['yunet']['session_id'] = ''
        runtime['execution_receipt']['detector_session_id'] = ''
    elif fault.startswith('dimension_'):
        runtime['observed_embedding_dimension'] = {
            'dimension_bool': True, 'dimension_zero': 0, 'dimension_mismatch': 128}[fault]
    elif fault == 'origin':
        row['usage_origin'] = 'health_probe_only'
    elif fault == 'active':
        row['active'] = 1
    assert module._attested(row) is False, fault


@pytest.mark.parametrize('fault', ['status', 'image_shape', 'empty_value', 'document_digest',
    'required_field', 'invocation', 'reason', 'source'])
def test_repair_additional_guards_reject_with_named_reason(fault):
    module = producer()
    options = repair_inputs()
    assert plain(module.RepairIdentityRecordV1(**options))['collection_status'] == 'complete'
    reason = {'status': 'invalid_collection_status', 'image_shape': 'invalid_image_fields',
              'empty_value': 'invalid_image_value', 'document_digest': 'invalid_image_digest',
              'required_field': 'repair_binding_missing', 'invocation': 'invalid_process_identity',
              'reason': 'unsafe_record_field', 'source': 'invalid_build_binding'}[fault]
    if fault == 'status':
        options['collection_status'] = 'unknown'
    elif fault == 'image_shape':
        options['image_record'] = []
    elif fault == 'empty_value':
        options['image_record']['platform'] = ''
    elif fault == 'document_digest':
        options['collection_status'] = 'incomplete'
        options['image_record']['identity_document_sha256'] = 'bad'
    elif fault == 'required_field':
        del options['image_record']['platform']
    elif fault == 'invocation':
        options['repair_invocation_id'] = '../escape'
    elif fault == 'reason':
        options['reason_code'] = {'exception': 'REJECTED_SENTINEL'}
    elif fault == 'source':
        options['source_identity'] = Record(identity_args(), source_tree='bad')
    with pytest.raises(ValueError, match=reason):
        module.RepairIdentityRecordV1(**options)


@pytest.mark.parametrize('subject', ['role', 'repair'])
def test_capture_time_requires_zero_offset(subject):
    from datetime import timedelta, timezone
    module = producer()
    options = complete_inputs() if subject == 'role' else repair_inputs()
    constructor = module.build_face_role_record if subject == 'role' else module.RepairIdentityRecordV1
    assert plain(constructor(**options))['collection_status'] == 'complete'
    options['captured_at'] = NOW.astimezone(timezone(timedelta(hours=1)))
    with pytest.raises(ValueError, match='invalid_capture_time'):
        constructor(**options)


@pytest.mark.parametrize('fault', ['catalog_version', 'source_alias', 'settings_alias', 'catalog_alias'])
def test_completion_and_transport_copy_keep_independent_controls(fault):
    module = producer()
    options = complete_inputs()
    if fault == 'catalog_version':
        options['serving_catalog'] = replace_transport(options['serving_catalog'], producer_abi_version=True)
        assert plain(module.build_face_role_record(**options))['collection_status'] == 'incomplete'
        return
    if fault == 'source_alias':
        options['source_identity'] = Record(identity_args())
        target = options['source_identity']
        field = 'source_tree'
    elif fault == 'settings_alias':
        target = options['effective_settings']
        field = 'profile'
    else:
        options['serving_catalog'] = plain(options['serving_catalog'])
        target = options['serving_catalog']
        field = 'process_instance_id'
    raw = module.build_face_role_record(**options)
    assert plain(raw)['collection_status'] == 'complete'
    before = plain(raw)
    target[field] = 'mutated-input'
    assert plain(raw) == before


@pytest.mark.parametrize('process', ['', True, '../escape', '..\\escape', 'x' * 129])
def test_process_guard_rejects_invalid_identity_with_named_reason(process):
    module = producer()
    with pytest.raises(ValueError, match='invalid_process_identity'):
        module.build_face_role_record(**inputs(process=process))


@pytest.mark.parametrize('version', [None, True, 1.0, '1', 0, 2])
def test_version_predicate_is_exact_for_attestation_envelopes(version):
    module = producer()
    assert module._version(1) is True
    assert module._version(version) is False


@pytest.mark.parametrize('boundary', ['serialize', 'open_stream', 'flush'])
def test_publication_checks_deadline_before_next_io_boundary(tmp_path, monkeypatch, boundary):
    import os
    from contextlib import contextmanager
    module = producer()
    record = module.build_face_role_record(**inputs())
    clock = [time.monotonic()]
    deadline = clock[0] + 1
    original_dumps, original_open, original_fdopen, original_fsync = json.dumps, os.open, os.fdopen, os.fsync
    def dumps(*args, **kwargs):
        result = original_dumps(*args, **kwargs)
        if boundary == 'serialize':
            clock[0] = deadline + 1
        return result
    def open_file(*args, **kwargs):
        assert clock[0] < deadline, 'CAUSAL_RED: expired serialization opened a temporary file'
        return original_open(*args, **kwargs)
    @contextmanager
    def fdopen(fd, *args, **kwargs):
        with original_fdopen(fd, *args, **kwargs) as stream:
            if boundary == 'open_stream':
                clock[0] = deadline + 1
            class Stream:
                def write(self, payload):
                    assert clock[0] < deadline, 'CAUSAL_RED: expired stream wrote payload'
                    return stream.write(payload)
                def flush(self):
                    result = stream.flush()
                    if boundary == 'flush':
                        clock[0] = deadline + 1
                    return result
                def fileno(self):
                    return stream.fileno()
            yield Stream()
    def fsync(fd):
        assert clock[0] < deadline, 'CAUSAL_RED: expired flush invoked fsync'
        return original_fsync(fd)
    with monkeypatch.context() as patch:
        patch.setattr(time, 'monotonic', lambda: clock[0])
        patch.setattr(json, 'dumps', dumps)
        patch.setattr(os, 'open', open_file)
        patch.setattr(os, 'fdopen', fdopen)
        patch.setattr(os, 'fsync', fsync)
        with pytest.raises(TimeoutError, match='publication_deadline'):
            publication(module, record, tmp_path, deadline_monotonic=deadline)
    assert list(tmp_path.iterdir()) == []


def test_repair_record_copies_image_and_source_before_caller_mutation():
    module = producer()
    options = repair_inputs()
    options['source_identity'] = Record(identity_args())
    raw = module.RepairIdentityRecordV1(**options)
    before = plain(raw)
    options['source_identity']['source_tree'] = '9' * 40
    options['image_record']['platform'] = 'mutated-platform'
    assert plain(raw) == before


@pytest.mark.parametrize('fault', ['empty_generation', 'zero_dimension', 'boolean_dimension', 'unsupported_value'])
def test_attestation_rejects_self_consistent_but_invalid_observed_values(fault):
    module = producer()
    row = plain(attested_observation('worker'))
    assert module._attested(row) is True
    runtime = row['runtime_record']
    if fault == 'empty_generation':
        runtime['runtime_generation_id'] = ''
        runtime['execution_receipt']['runtime_generation_id'] = ''
        for session in runtime['sessions'].values():
            session['runtime_generation_id'] = ''
    elif fault in ('zero_dimension', 'boolean_dimension'):
        runtime['observed_embedding_dimension'] = runtime['declared_embedding_dimension'] = (
            0 if fault == 'zero_dimension' else True)
    else:
        options = inputs()
        options['effective_settings']['actual_session_options'] = object()
        with pytest.raises(TypeError, match='unsupported_record_value'):
            module.build_face_role_record(**options)
        return
    assert module._attested(row) is False


@pytest.mark.parametrize('symlink', [False, True])
def test_publication_refuses_preexisting_temporary_path(tmp_path, monkeypatch, symlink):
    from types import SimpleNamespace
    module = producer()
    record = module.build_face_role_record(**inputs())
    monkeypatch.setattr(module.uuid, 'uuid4', lambda: SimpleNamespace(hex='fixed'))
    temporary = tmp_path / '.worker-worker-process.json.fixed.tmp'
    if symlink:
        victim = tmp_path / 'victim'
        victim.write_bytes(b'unchanged')
        temporary.symlink_to(victim)
    else:
        temporary.write_bytes(b'unchanged')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(OSError):
        publication(module, record, tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
