"""Five separately selectable offline groups; genuine builders/parsers, stub curl only."""
import base64
import contextlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import threading
import time

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "benchmarks/tools/qwen_factorial_collect.py"
spec = importlib.util.spec_from_file_location("qwen_factorial_collect", SOURCE)
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)
REFS = Path(os.environ.get(
    "QWEN_FACTORIAL_REFERENCE_ROOT",
    "/home/gate/bakeoff-next-model-causal-r4-370182cb56ef4b8a93da5e3fa67710e4/references",
))
RESOURCE_CFG = {
    "service_dir": str(REFS / "service"),
    "loader_override": str(REFS / "baseline/depiction_lexicon.py"),
    "canon_root": str(REFS / "canon"),
    "original_producer": str(REFS / "producer/extraction_paired_client.py"),
}
FACTS = '```json\n{ "people": [], "setting": "synthetic", "action": "", "legible_text": [], "atmosphere": "" }\n```'
SURFACE_TEXT = '{"title":"Synthetic title","alt":"Synthetic alt.","caption":"Synthetic caption."}'
PROCESS = {"spawned": True, "returncode": 0, "interrupted": False}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else q.canonical(value) + b"\n"
    path.write_bytes(raw)
    return {"path": str(path), "sha256": q.sha(raw)}


def envelope(model="actual-a", text=FACTS, finish="stop", usage=True):
    out = {"model": model, "choices": [{"finish_reason": finish, "message": {"content": text}}]}
    if usage:
        out["usage"] = {"prompt_tokens": 13, "completion_tokens": 7, "total_tokens": 20}
    return out


@pytest.fixture(scope="session")
def genuine(tmp_path_factory):
    # These are public, digest-checked resources. No requests, auth or image files.
    # Any import-time native telemetry scratch stays in the approved test temp tree.
    with contextlib.chdir(tmp_path_factory.mktemp("genuine-import")):
        return q.Genuine(RESOURCE_CFG)


@pytest.fixture
def config(tmp_path, genuine):
    template = {"model": "qualified-model", "messages": [], "temperature": 0, "seed": 0,
                "top_p": 1, "max_tokens": 512, "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_object", "schema": copy.deepcopy(q.REQUIRED_SCHEMA)}}
    # An extra qualification property must survive cloning, not be reconstructed.
    template["response_format"]["schema"]["description"] = "synthetic qualified schema"
    cfg = {"resources": save(tmp_path / "resources.json", RESOURCE_CFG),
           "writer_template": save(tmp_path / "template.json", template),
           "header_file": "/synthetic/credential-file-never-opened", "timeout_s": 5,
           "cleanup_margin_s": 1, "max_parallel_models": 2, "models": []}
    model = {"id": "a", "endpoint": "http://127.0.0.1:19001", "request_model": "request-a",
             "expected_response_model": "actual-a", "precision": "bf16", "native_epoch": "synthetic-epoch",
             "profile": save(tmp_path / "profile-a.json", {"weights": "synthetic-a"}),
             "deadline_unix": 2000, "extractions": []}
    part = {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(b"synthetic opaque image").decode()}}
    client = genuine.client(model, False)
    try:
        request = {"model": model["request_model"], "temperature": 0, "seed": 0, "top_p": 1,
                   "max_tokens": 1536, "messages": genuine.extraction_messages(client, 0, part)}
    finally:
        client.close()
    model["extractions"].append({"image_id": "synthetic", "input_sha256": q.sha(b"synthetic opaque image"),
                                 "E": 0, "request": save(tmp_path / "extraction.json", request)})
    cfg["models"].append(model)
    return cfg


def collector(config, tmp_path, genuine, **kwargs):
    return q.Collector(config, tmp_path / "evidence", 2000, genuine=genuine, clock=lambda: 1000, **kwargs)


class NativeStub:
    """Stub Popen at the native boundary, retaining real Curl/supervision/acceptance."""

    def __init__(self, config, *, mutate=None, code=200, returncode=0, barrier=None):
        self.models = {m["request_model"]: m for m in config["models"]}
        self.calls = []
        self.mutate = mutate
        self.code = code
        self.returncode = returncode
        self.barrier = barrier
        self.lock = threading.Lock()
        self.active = set()
        self.max_active = 0

    def __call__(self, argv, **kwargs):
        assert argv[:2] == ["/usr/bin/curl", "-q"]
        assert kwargs.get("shell", False) is False
        request_path = Path(argv[argv.index("--data-binary") + 1][1:])
        request = q.strict_json(request_path.read_bytes())
        mid = request["model"]
        writing = request["max_tokens"] == 512
        with self.lock:
            assert mid not in self.active, "overlapping request within one model"
            self.active.add(mid)
            self.max_active = max(self.max_active, len(self.active))
            self.calls.append((argv, request, q.strict_json((request_path.parent / "intent.json").read_bytes())))
        if self.barrier and not writing:
            self.barrier.wait(timeout=3)
        payload = envelope(self.models[mid]["expected_response_model"], SURFACE_TEXT if writing else FACTS)
        if self.mutate:
            self.mutate(payload, writing)
        for flag, raw in (("--output", q.canonical(payload)), ("--dump-header", b"HTTP/1.1 200 OK\r\n\r\n")):
            fd = int(argv[argv.index(flag) + 1].rsplit("/", 1)[1])
            os.write(fd, raw)
        kwargs["stdout"].write(q.canonical({"http_code": self.code}))
        owner = self
        class Child:
            pid = 99999999
            returncode = None
            def poll(self):
                with owner.lock:
                    owner.active.discard(mid)
                self.returncode = owner.returncode
                return self.returncode
            def wait(self):
                return self.poll()
        return Child()


@pytest.fixture
def native(monkeypatch, config):
    stub = NativeStub(config)
    monkeypatch.setattr(q.subprocess, "Popen", stub)
    return stub


BOUNDARY_FILES = ("response.json", "metrics.json", "headers.txt")
SYNTHETIC_MODEL = {"endpoint": "http://127.0.0.1:19001"}
SYNTHETIC_HEADER = Path("/synthetic/credential-file-never-opened")
REOPENED = {"--output": b'{"synthetic":"response"}', "--dump-header": b"HTTP/1.1 200 OK\r\n\r\n"}


def boundary_dir(tmp_path):
    directory = tmp_path / "stage"
    q.mkdir(directory)
    return directory


def assert_sealed(directory):
    assert {name: stat.S_IMODE(os.stat(directory / name).st_mode) for name in BOUNDARY_FILES} == dict.fromkeys(
        BOUNDARY_FILES, 0o400)


class ReopenRunner:
    """Children-compatible boundary that writes the way curl does: reopen by path, not fd."""

    def __init__(self, outcome):
        self.outcome = outcome

    def run(self, argv, *, timeout, **kwargs):
        for flag, raw in REOPENED.items():
            fd = int(argv[argv.index(flag) + 1].rsplit("/", 1)[1])
            assert fd in kwargs["pass_fds"]
            assert os.fstat(fd).st_mode & 0o200, "boundary file is not owner-writable"
            if self.outcome == "raises":
                continue
            path = f"/proc/self/fd/{fd}" if sys.platform == "linux" else f"/dev/fd/{fd}"
            with open(path, "wb") as stream:
                stream.write(raw)
        if self.outcome == "raises":
            raise q.Invalid("supervisor stopped before spawn")
        kwargs["stdout"].write(q.canonical({"http_code": 200}))
        return {"ok": PROCESS, "transport": dict(PROCESS, returncode=28),
                "killed": dict(PROCESS, returncode=-9, interrupted=True)}[self.outcome]


# Mirrors curl: a by-path open failure is reported, then exit 23 (write error).
REOPEN_CHILD = r"""
import errno, json, sys
try:
    for path, raw in zip(sys.argv[1:3], (b'{"synthetic":"response"}', b"HTTP/1.1 200 OK\r\n\r\n")):
        with open(path, "wb") as stream:
            stream.write(raw)
except OSError as exc:
    sys.stdout.write(json.dumps({"errno": errno.errorcode.get(exc.errno, exc.errno)}))
    raise SystemExit(23)
sys.stdout.write(json.dumps({"http_code": 200}))
"""


class RealChildRunner:
    """Children-compatible runner: a real child opens curl's /proc/self/fd argv paths."""

    def __init__(self):
        self.children = q.Children(threading.Event())

    def run(self, argv, *, timeout, **kwargs):
        assert argv[:2] == ["/usr/bin/curl", "-q"]
        paths = [argv[argv.index(flag) + 1] for flag in REOPENED]
        assert all(path.startswith("/proc/self/fd/") for path in paths)
        return self.children.run([sys.executable, "-I", "-c", REOPEN_CHILD, *paths], timeout=timeout, **kwargs)


class TestBindingsAcceptance:
    def test_genuine_origin_and_bad_extraction(self, genuine, config):
        assert Path(genuine.b.__file__).resolve() == REFS / "service/scripts/eval_harness/bakeoff.py"
        assert genuine.lex.sha256 == q.DEPICTION_SHA
        with pytest.raises(genuine.b.PassOneJSONError):
            genuine.accept(q.canonical(envelope(text='{"people":[]}')), config["models"][0], False)
        assert genuine.accept(q.canonical(envelope()), config["models"][0], False)["text"] == FACTS

    @pytest.mark.parametrize("text", [
        '```json\n' + SURFACE_TEXT + '\n```',
        '{"title":"x","title":"y","alt":"x","caption":"x"}',
        '{"title":"x","alt":"x","caption":"x","extra":"x"}',
        '{"title":" ","alt":"x","caption":"x"}',
    ])
    def test_writer_strict_before_genuine_acceptance(self, text, genuine, config):
        with pytest.raises((q.Invalid, ValueError)):
            genuine.accept(q.canonical(envelope(text=text)), config["models"][0], True)
        assert genuine.accept(q.canonical(envelope(text=SURFACE_TEXT)), config["models"][0], True)["text"] == SURFACE_TEXT

    def test_data_url_and_request_bindings(self, config, tmp_path, genuine):
        config["models"][0]["extractions"][0]["input_sha256"] = "0" * 64
        with pytest.raises(q.Invalid, match="actual data URL"):
            collector(config, tmp_path, genuine)
        assert not (tmp_path / "evidence").exists()

    @pytest.mark.parametrize("value", [None, "other-weight-identity"])
    def test_wrong_model_native_path_quarantines_stream(self, value, config, tmp_path, genuine, monkeypatch):
        def wrong(payload, writing):
            if value is None:
                payload.pop("model")
            else:
                payload["model"] = value
        stub = NativeStub(config, mutate=wrong)
        monkeypatch.setattr(q.subprocess, "Popen", stub)
        report = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert report["stopped"] == "wrong_model"
        assert len(stub.calls) == 1 and report["verified_inference_receipts"] == 0
        assert report["received_responses"] == 1
        result = q.strict_json((tmp_path / "evidence/a/synthetic-E0/result.json").read_bytes())
        assert result["status"] == "quarantined_wrong_model"
        collector(config, tmp_path, genuine).run()
        assert len(stub.calls) == 1

    def test_profile_and_template_rejected_before_mutation(self, config, tmp_path, genuine):
        config["models"][0]["profile"]["sha256"] = "0" * 64
        with pytest.raises(q.Invalid, match="digest"):
            collector(config, tmp_path, genuine)
        config["models"][0]["profile"]["sha256"] = q.sha(Path(config["models"][0]["profile"]["path"]).read_bytes())
        payload = q.strict_json(Path(config["writer_template"]["path"]).read_bytes())
        del payload["response_format"]
        config["writer_template"] = save(tmp_path / "bad-template.json", payload)
        with pytest.raises(q.Invalid, match="response_format"):
            collector(config, tmp_path, genuine)

    def test_boolean_seed_does_not_satisfy_numeric_decoder(self, config, tmp_path, genuine):
        payload = q.strict_json(Path(config["writer_template"]["path"]).read_bytes())
        payload["seed"] = False
        config["writer_template"] = save(tmp_path / "bad-seed.json", payload)
        with pytest.raises(q.Invalid, match="decoder"):
            collector(config, tmp_path, genuine)
        assert not (tmp_path / "evidence").exists()

    def test_wrong_writer_model_stops_remaining_writer(self, config, tmp_path, genuine, monkeypatch):
        def wrong(payload, writing):
            if writing:
                payload["model"] = "same-build-fingerprint-different-weights"
        stub = NativeStub(config, mutate=wrong)
        monkeypatch.setattr(q.subprocess, "Popen", stub)
        report = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert report["stopped"] == "wrong_model" and len(stub.calls) == 2
        assert report["accepted"] == 1 and report["verified_inference_receipts"] == 1


class TestBoundsNoRetry:
    def test_deadline_requires_full_timeout_plus_cleanup(self, config, tmp_path, genuine, native):
        config["models"][0]["deadline_unix"] = 1006
        report = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert not native.calls and report["failed_or_skipped"] == 3
        collector(config, tmp_path, genuine).run()
        assert not native.calls

    @pytest.mark.parametrize("failure", ["http", "truncated", "transport"])
    def test_terminal_failure_and_dependency_skips(self, failure, config, tmp_path, genuine, monkeypatch):
        stub = NativeStub(config, code=503 if failure == "http" else 200,
                          returncode=28 if failure == "transport" else 0,
                          mutate=(lambda p, _: p["choices"][0].update(finish_reason="length"))
                          if failure == "truncated" else None)
        monkeypatch.setattr(q.subprocess, "Popen", stub)
        first = collector(config, tmp_path, genuine).run()["models"]["a"]
        second = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert first["native_http_attempts"] == 1 and first["received_responses"] == 1
        assert first["failed_or_skipped"] == 3 and second["native_http_attempts"] == 0
        assert len(stub.calls) == 1

    def test_native_argv_limits_and_credential_locator(self, config, tmp_path, genuine, native):
        collector(config, tmp_path, genuine).run()
        args = native.calls[0][0]
        for flag, value in (("--connect-timeout", "5"), ("--max-time", "5"), ("--retry", "0")):
            assert args[args.index(flag) + 1] == value
        assert "@/synthetic/credential-file-never-opened" in args
        assert "--location" not in args and "--insecure" not in args
        # The nonexistent locator was never read by the collector.
        assert not Path(config["header_file"]).exists()

    @pytest.mark.parametrize("outcome", ["ok", "transport", "killed", "raises"])
    def test_boundary_files_writable_by_path_then_sealed(self, outcome, tmp_path):
        directory = boundary_dir(tmp_path)
        curl = q.Curl(ReopenRunner(outcome))
        if outcome == "raises":
            with pytest.raises(q.Invalid):
                curl(SYNTHETIC_MODEL, SYNTHETIC_HEADER, directory, timeout=5, cleanup=1)
        else:
            process = curl(SYNTHETIC_MODEL, SYNTHETIC_HEADER, directory, timeout=5, cleanup=1)
            assert process["returncode"] == {"ok": 0, "transport": 28, "killed": -9}[outcome]
            assert (directory / "response.json").read_bytes() == REOPENED["--output"]
            assert (directory / "headers.txt").read_bytes() == REOPENED["--dump-header"]
        assert_sealed(directory)
        assert not SYNTHETIC_HEADER.exists()

    @pytest.mark.skipif(sys.platform != "linux" or os.geteuid() == 0,
                        reason="Linux /proc/self/fd reopen permission check; root bypasses it")
    def test_real_child_reopens_proc_fd_paths(self, tmp_path):
        directory = boundary_dir(tmp_path)
        process = q.Curl(RealChildRunner())(SYNTHETIC_MODEL, SYNTHETIC_HEADER, directory, timeout=30, cleanup=1)
        # A 0400 boundary file shows up here as {"errno": "EACCES"} with exit 23.
        assert q.strict_json((directory / "metrics.json").read_bytes()) == {"http_code": 200}
        assert process == PROCESS
        assert (directory / "response.json").read_bytes() == REOPENED["--output"]
        assert (directory / "headers.txt").read_bytes() == REOPENED["--dump-header"]
        assert_sealed(directory)
        assert not SYNTHETIC_HEADER.exists()

    def test_seal_failure_raises(self, tmp_path, monkeypatch):
        def refuse(fd, mode):
            raise PermissionError("synthetic fchmod failure")
        monkeypatch.setattr(q.os, "fchmod", refuse)
        with pytest.raises(PermissionError, match="synthetic fchmod"):
            q.Curl(ReopenRunner("ok"))(SYNTHETIC_MODEL, SYNTHETIC_HEADER, boundary_dir(tmp_path),
                                       timeout=5, cleanup=1)

    def test_unmeasured_response_is_not_inference_receipt(self, config, tmp_path, genuine, monkeypatch):
        stub = NativeStub(config, mutate=lambda p, _: p.pop("usage"))
        monkeypatch.setattr(q.subprocess, "Popen", stub)
        report = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert report["accepted"] == 3 and report["received_responses"] == 3
        assert report["verified_inference_receipts"] == 0


class TestCausalFactsLexicon:
    def test_end_to_end_three_native_boundaries_then_zero(self, config, tmp_path, genuine, native):
        first = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert first["native_http_attempts"] == first["received_responses"] == first["verified_inference_receipts"] == 3
        assert first["accepted"] == 3 and len(native.calls) == 3
        template = q.strict_json(Path(config["writer_template"]["path"]).read_bytes())
        facts_hashes = []
        order = []
        for _, request, intent in native.calls[1:]:
            assert FACTS in request["messages"][1]["content"][1]["text"]
            assert request["messages"][1]["content"][0] == native.calls[0][1]["messages"][1]["content"][0]
            assert {k: v for k, v in request.items() if k not in {"model", "messages"}} == {
                k: v for k, v in template.items() if k not in {"model", "messages"}}
            facts_hashes.append(intent["binding"]["facts_sha256"])
            order.append(intent["binding"]["W"])
        assert facts_hashes == [q.sha(FACTS), q.sha(FACTS)]
        expected = [0, 1] if int(config["models"][0]["extractions"][0]["input_sha256"][-1], 16) % 2 == 0 else [1, 0]
        assert order == expected
        second = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert second["native_http_attempts"] == 0 and second["reused"] == 3
        assert len(native.calls) == 3

    def test_e1_and_writer_lexicon_only_at_assigned_edges(self, config, tmp_path, genuine, native):
        model = config["models"][0]
        entry = model["extractions"][0]
        entry["E"] = 1
        raw = q.strict_json(Path(entry["request"]["path"]).read_bytes())
        client = genuine.client(model, False)
        try:
            raw["messages"] = genuine.extraction_messages(client, 1, raw["messages"][1]["content"][0])
        finally:
            client.close()
        entry["request"] = save(tmp_path / "e1.json", raw)
        collector(config, tmp_path, genuine).run()
        assert genuine.lex.render() in native.calls[0][1]["messages"][0]["content"]
        for _, request, intent in native.calls[1:]:
            assert (genuine.lex.render() in request["messages"][0]["content"]) == bool(intent["binding"]["W"])


class TestImmutableResumeEvidence:
    def test_partial_accepted_extraction_only_missing_writers(self, config, tmp_path, genuine, native):
        run = collector(config, tmp_path, genuine)
        model = config["models"][0]
        entry = model["extractions"][0]
        # Model a prior invocation interrupted after committing extraction acceptance.
        q.mkdir(run.evidence)
        raw, _ = run.prepared[("a", "synthetic", 0)]
        accepted = run.stage(model, entry, None, raw)
        assert accepted["status"] == "accepted" and len(native.calls) == 1
        report = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert len(native.calls) == 3 and report["native_http_attempts"] == 2
        assert report["reused"] == 1

    def test_incomplete_intent_never_resubmits(self, config, tmp_path, genuine, native):
        run = collector(config, tmp_path, genuine)
        directory = run.directory(config["models"][0], config["models"][0]["extractions"][0], None)
        q.mkdir(directory)
        q.write_new(directory / "intent.json", {"uncertain": True})
        report = run.run()["models"]["a"]
        assert report["stopped"] == "Invalid" and not native.calls

    def test_tamper_rejected_without_post(self, config, tmp_path, genuine, native):
        collector(config, tmp_path, genuine).run()
        path = tmp_path / "evidence/a/synthetic-E0/response.json"
        path.chmod(0o600)
        path.write_bytes(q.canonical(envelope(text=FACTS.replace("synthetic", "tampered"))))
        report = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert report["stopped"] == "Invalid" and len(native.calls) == 3

    def test_no_clobber_and_no_deadline_reset(self, config, tmp_path, genuine, native):
        collector(config, tmp_path, genuine).run()
        path = tmp_path / "evidence/a/synthetic-E0/result.json"
        prior = path.read_bytes()
        with pytest.raises(FileExistsError):
            q.write_new(path, {"replacement": True})
        assert path.read_bytes() == prior
        with pytest.raises(q.Invalid, match="no reset"):
            q.Collector(config, tmp_path / "evidence", 3000, genuine=genuine, clock=lambda: 1000).run()
        assert len(native.calls) == 3

    def test_explicit_legacy_adoption_feeds_missing_writers(self, config, tmp_path, genuine, native):
        run = collector(config, tmp_path, genuine)
        model, entry = config["models"][0], config["models"][0]["extractions"][0]
        raw, _ = run.prepared[("a", "synthetic", 0)]
        legacy_raw = json.dumps(q.strict_json(raw), indent=2).encode()
        binding = run.binding(model, entry, None, legacy_raw, None)
        legacy = tmp_path / "legacy"
        q.mkdir(legacy)
        artifacts = {"request.json": legacy_raw, "intent.json": {"binding": binding},
                     "response.json": q.canonical(envelope()), "metrics.json": {"http_code": 200}}
        pins = {name: save(legacy / name, value)["sha256"] for name, value in artifacts.items()}
        pins["result.json"] = save(legacy / "result.json", {"binding": binding, "accepted": True,
              "process": PROCESS, "files": {"response.json": pins["response.json"],
                                             "metrics.json": pins["metrics.json"]}})["sha256"]
        config["adopt"] = [{"model_id": "a", "image_id": "synthetic", "E": 0,
                            "directory": str(legacy), "sha256": pins,
                            "status_field": "/accepted", "accepted_value": True}]
        report = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert report["adopted"] == 1 and report["native_http_attempts"] == 2
        assert len(native.calls) == 2 and all(call[1]["max_tokens"] == 512 for call in native.calls)
        assert all(FACTS in call[1]["messages"][1]["content"][1]["text"] for call in native.calls)
        assert (tmp_path / "evidence/a/synthetic-E0/request.json").read_bytes() == legacy_raw
        assert (tmp_path / "evidence/a/synthetic-E0/legacy-result.json").read_bytes() == (legacy / "result.json").read_bytes()
        collector(config, tmp_path, genuine).run()
        assert len(native.calls) == 2

    def test_status_alone_cannot_adopt(self, config, tmp_path, genuine, native):
        legacy = tmp_path / "legacy"
        pins = {name: save(legacy / name, {"status": "accepted"})["sha256"] for name in
                ("request.json", "intent.json", "response.json", "metrics.json", "result.json")}
        config["adopt"] = [{"model_id": "a", "image_id": "synthetic", "E": 0,
                            "directory": str(legacy), "sha256": pins}]
        report = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert report["stopped"] == "Invalid" and not native.calls

    def test_symlinked_model_directory_is_not_followed(self, config, tmp_path, genuine, native):
        outside = tmp_path / "unowned"
        outside.mkdir()
        root = tmp_path / "evidence"
        root.mkdir()
        (root / "a").symlink_to(outside, target_is_directory=True)
        report = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert report["stopped"] == "Invalid" and not native.calls
        assert not list(outside.iterdir())


class TestConcurrencyHeartbeatCleanup:
    def test_two_streams_overlap_one_boundary_per_model(self, config, tmp_path, genuine, monkeypatch):
        other = copy.deepcopy(config["models"][0])
        other.update(id="b", request_model="request-b", expected_response_model="actual-b",
                     endpoint="http://127.0.0.1:19002", precision="f16")
        entry = other["extractions"][0]
        request = q.strict_json(Path(entry["request"]["path"]).read_bytes())
        request["model"] = "request-b"
        entry["request"] = save(tmp_path / "extraction-b.json", request)
        config["models"].append(other)
        stub = NativeStub(config, barrier=threading.Barrier(2))
        monkeypatch.setattr(q.subprocess, "Popen", stub)
        report = collector(config, tmp_path, genuine).run()["models"]
        assert stub.max_active == 2 and len(stub.calls) == 6
        assert report["a"]["accepted"] == report["b"]["accepted"] == 3

    def test_heartbeat_failure_stops_before_post(self, config, tmp_path, genuine, monkeypatch):
        config["heartbeat"] = {"argv": ["/synthetic/heartbeat", "--synthetic"], "timeout_s": 1,
                               "deadline_unix": 1500, "interval_s": 0.01, "max_count": 2}
        seen = []
        class Failed:
            pid = 99999999
            returncode = 1
            def __init__(self, argv, **kwargs):
                seen.append(argv)
                assert kwargs.get("shell", False) is False
            def poll(self): return 1
            def wait(self): return 1
        monkeypatch.setattr(q.subprocess, "Popen", Failed)
        report = collector(config, tmp_path, genuine).run()["models"]["a"]
        assert seen == [config["heartbeat"]["argv"]]
        assert report["native_http_attempts"] == 0 and report["stopped"] == "supervisor"
        assert (tmp_path / "evidence/invocation-00000/heartbeat-00000.json").exists()

    def test_successful_periodic_heartbeat_during_collection(self, config, tmp_path, genuine, monkeypatch):
        config["heartbeat"] = {"argv": ["/synthetic/heartbeat"], "timeout_s": 1,
                               "deadline_unix": 1500, "interval_s": 0.005, "max_count": 100}
        stub = NativeStub(config, mutate=lambda *_: time.sleep(0.02))
        heartbeats = []
        class Success:
            pid = 99999999
            returncode = 0
            def poll(self): return 0
            def wait(self): return 0
        def dispatch(argv, **kwargs):
            if argv[0] == "/synthetic/heartbeat":
                heartbeats.append(argv)
                return Success()
            return stub(argv, **kwargs)
        monkeypatch.setattr(q.subprocess, "Popen", dispatch)
        report = collector(config, tmp_path, genuine).run()
        assert len(heartbeats) >= 2 and len(stub.calls) == 3
        assert report["models"]["a"]["accepted"] == 3 and report["supervision_failure"] is None

    def test_expired_heartbeat_deadline_admits_no_command(self, config, tmp_path, genuine, native):
        config["heartbeat"] = {"argv": ["/synthetic/heartbeat"], "timeout_s": 1,
                               "deadline_unix": 1002, "interval_s": 0.005, "max_count": 100}
        report = collector(config, tmp_path, genuine).run()
        assert report["supervision_failure"] == "command_or_deadline_failure"
        assert not native.calls

    def test_heartbeat_count_exhaustion_is_finite(self, config, tmp_path, genuine, monkeypatch):
        config["heartbeat"] = {"argv": ["/synthetic/heartbeat"], "timeout_s": 1,
                               "deadline_unix": 1500, "interval_s": 0.001, "max_count": 2}
        run = collector(config, tmp_path, genuine)
        q.mkdir(run.evidence)
        run.heartbeat_evidence = run.evidence
        calls = []
        monkeypatch.setattr(run.children, "run", lambda argv, **kw: calls.append(argv) or PROCESS)
        run.heartbeat(threading.Event())
        assert len(calls) == 2 and run.stop.is_set()

    def test_supervisor_timeout_kills_only_own_child(self, monkeypatch):
        alive = {12345678: True, 87654321: True}
        killed = []
        class Hung:
            pid = 12345678
            returncode = None
            def __init__(self, *args, **kwargs):
                assert kwargs["start_new_session"] is True
            def poll(self):
                if not alive[self.pid]:
                    self.returncode = -9
                return self.returncode
            def wait(self): return self.poll()
        def kill(pid, sig):
            killed.append(pid)
            alive[pid] = False
        monkeypatch.setattr(q.subprocess, "Popen", Hung)
        monkeypatch.setattr(q.os, "killpg", kill)
        children = q.Children(threading.Event())
        result = children.run(["/synthetic/hung-child"], timeout=0.001)
        children.close()
        assert result["interrupted"] and result["spawned"]
        assert killed == [12345678] and alive[87654321] and not children.children

    def test_collector_fence_excludes_second_writer(self, config, tmp_path, genuine, native):
        directory = tmp_path / "evidence"
        q.mkdir(directory)
        fd = os.open(directory / ".collector.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            q.fcntl.flock(fd, q.fcntl.LOCK_EX | q.fcntl.LOCK_NB)
            with pytest.raises(BlockingIOError):
                collector(config, tmp_path, genuine).run()
            assert not native.calls
        finally:
            os.close(fd)
