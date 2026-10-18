"""Executable NEW raw-only auth contract; expected RED until separately implemented.

Only the HTTP/OS dependencies are controlled. The real BakeoffClient, parser,
main, manifest loader, walker, warmup clone and request encoder run unchanged.
Synthetic tokens and a pinned empty file exercise no media or inference.
"""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
import stat
import traceback
from pathlib import Path

import httpx
import pytest

from scripts.eval_harness import bakeoff

KEY = "0123456789abcdef" * 4
WRONG = "fedcba9876543210" * 4
FACTS = json.dumps({"people": [], "setting": "fixture", "action": "", "legible_text": [], "atmosphere": ""})
SURFACES = json.dumps({"title": "Fixture title", "alt": "Fixture alt", "caption": "Fixture caption."})
ENDPOINT = "http://raw-auth.invalid:8080"


class Endpoint:
    """Strict external server policy; never supplies or repairs client auth."""

    def __init__(self, *, protected=True, status=None, reflection=""):
        self.protected = protected
        self.status = status
        self.reflection = reflection
        self.requests = []
        self.accepted = 0
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        self.requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == ENDPOINT + "/v1/chat/completions"
        if self.protected and request.headers.get("authorization") != "Bearer " + KEY:
            return httpx.Response(401, text=self.reflection or "refused")
        if self.status is not None:
            return httpx.Response(
                self.status,
                text=self.reflection,
                extensions={"reason_phrase": self.reflection.encode("ascii")} if self.reflection else {},
                headers={"location": "http://other-host.invalid/stolen"} if self.status == 307 else {},
            )
        content = FACTS if self.accepted % 2 == 0 else SURFACES
        if self.reflection:
            fields = json.loads(content)
            fields["setting" if self.accepted % 2 == 0 else "caption"] = self.reflection
            content = json.dumps(fields)
        self.accepted += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def client(endpoint, **kwargs):
    return bakeoff.BakeoffClient(
        ENDPOINT,
        model_id="synthetic-model",
        model_version="fixture",
        model_revision="synthetic-revision",
        seed=17,
        no_think=True,
        prompt_variant="v3",
        two_pass=True,
        timeout_s=0.2,
        transport=endpoint.transport,
        **kwargs,
    )


def describe(raw):
    return raw.describe(image_bytes=b"", filename="empty.jpg", media_id=7, context_pack={"caption": "fixture"})


def no_leak(value, *private):
    text = str(value)
    for secret in private:
        assert secret not in text
        assert repr(secret)[1:-1] not in text


def diagnostics(exc):
    return str(exc) + repr(exc) + "".join(traceback.format_exception(exc))


@pytest.fixture
def cli_case(tmp_path, monkeypatch):
    """Normal v3 loader gates stay active, including the actual image digest."""
    images = tmp_path / "images"
    images.mkdir()
    (images / "empty.jpg").write_bytes(b"")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "annotation_mode": "roster_only",
                "roster": [],
                "entries": [
                    {
                        "path": "empty.jpg",
                        "sha256": hashlib.sha256(b"").hexdigest(),
                        "media_id": 7,
                        "base_caption": "",
                        "face_count": 0,
                        "present_identities": [],
                        "context_pack": {"caption": "fixture"},
                        "must_right": [],
                        "easy_wrong": [],
                        "policy": {"recognition_enabled": False},
                        "provenance": {"source": "fixture", "license": "fixture"},
                    }
                ],
            }
        )
    )
    monkeypatch.setenv("ACX_EVAL_LIVE", "1")  # MockTransport only, no sockets.
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(images))
    # main's ordinary out/pruning directory must also be owned temporary data.
    module_path = tmp_path / "module" / "bakeoff.py"
    module_path.parent.mkdir()
    monkeypatch.setattr(bakeoff, "__file__", str(module_path))
    real_client = httpx.Client

    def run(endpoint, keyfile=None, *, warmup=1):
        def http_client(*args, **kwargs):
            # Dependency seam only: leave the real encoder/headers/auth untouched.
            kwargs["transport"] = endpoint.transport
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", http_client)
        output = tmp_path / "results" / "record.json"
        argv = [
            "--endpoint",
            ENDPOINT,
            "--model-id",
            "synthetic-model",
            "--manifest",
            str(manifest),
            "--out",
            str(output),
            "--prompt-variant",
            "v3",
            "--two-pass",
            "--no-think",
            "--timeout",
            "0.2",
            "--stall-limit",
            "1",
            "--warmup",
            str(warmup),
            "--vram-sample-interval-s",
            "0",
        ]
        if keyfile is not None:
            argv += ["--server-api-key-file", str(keyfile)]
        bakeoff.main(argv)
        return json.loads(output.read_text())

    return run, tmp_path


def key_file(root, payload=KEY.encode(), mode=0o600):
    path = root / "private-key-sentinel"
    path.write_bytes(payload)
    path.chmod(mode)
    return path


class CredentialReads:
    """Observe owned descriptor I/O without reading or validating for the caller.

    Offset deltas include buffered read-ahead; requested sizes are not bytes read.
    Violations are checked after the caller returns, never converted to refusal.
    """

    content_methods = {"read", "readall", "read1", "readinto", "readinto1", "readline", "readlines", "peek"}

    def __init__(self, monkeypatch, path, *, foreign_owner=False, unreadable=False, replacement=None, forbid=False):
        self.path = path
        self.handles = []
        self.validated = {}
        self.attempts = []
        self.forbid = forbid
        self.depth = 0
        self.replaced = False
        self.unchecked_opens = []
        self.real_open, self.real_fstat, self.real_stat = os.open, os.fstat, os.stat
        self.real_close, self.real_lseek = os.close, os.lseek
        observer = self

        def same_path(name):
            return not isinstance(name, int) and os.path.abspath(os.fsdecode(name)) == str(path.absolute())

        def observed_open(name, flags, *args, **kwargs):
            if same_path(name):
                assert flags & os.O_NOFOLLOW
                assert flags & os.O_NONBLOCK  # never block on the synthetic FIFO
                if unreadable:
                    raise PermissionError(13, "synthetic unreadable", str(path))
            fd = self.real_open(name, flags, *args, **kwargs)
            if same_path(name):
                self.handles.append((fd, self.identity(fd)))
                self.validated.pop(fd, None)
            return fd

        def metadata(fd, result):
            if self.tracked(fd):
                if foreign_owner:
                    fields = list(result)
                    fields[4] = os.getuid() + 1
                    result = os.stat_result(fields)
                eligible = (
                    stat.S_ISREG(result.st_mode)
                    and result.st_uid == os.getuid()
                    and stat.S_IMODE(result.st_mode) in {0o400, 0o600}
                )
                self.validated[fd] = eligible
                if replacement is not None and eligible and not self.replaced:
                    self.replaced = True
                    path.unlink()
                    path.symlink_to(replacement)
            return result

        def observed_fstat(fd):
            return metadata(fd, self.real_fstat(fd))

        def observed_stat(name, *args, **kwargs):
            result = self.real_stat(name, *args, **kwargs)
            return metadata(name, result) if isinstance(name, int) else result

        def descriptor_call(original):
            def call(fd, *args, **kwargs):
                return self.observe(fd, lambda: original(fd, *args, **kwargs), stream=False)

            return call

        def stream_open(original):
            def open_stream(name, *args, **kwargs):
                if replacement is not None and same_path(name) and self.handles:
                    raise AssertionError("credential reopened by pathname")
                stream = original(name, *args, **kwargs)
                if same_path(name) and not self.tracked(stream.fileno()):
                    self.handles.append((stream.fileno(), self.identity(stream.fileno())))
                    self.unchecked_opens.append(stream.fileno())
                return self.wrap(stream)

            return open_stream

        real_fileio = io.FileIO

        class ObservedFileIO(real_fileio):
            def __init__(self, name, *args, **kwargs):
                if replacement is not None and same_path(name) and observer.handles:
                    raise AssertionError("credential reopened by pathname")
                super().__init__(name, *args, **kwargs)
                if same_path(name) and not observer.tracked(self.fileno()):
                    observer.handles.append((self.fileno(), observer.identity(self.fileno())))
                    observer.unchecked_opens.append(self.fileno())

            def __getattribute__(self, name):
                value = super().__getattribute__(name)
                if name in observer.content_methods:
                    return lambda *args, **kwargs: observer.observe(
                        self.fileno(), lambda: value(*args, **kwargs), stream=True
                    )
                return value

        monkeypatch.setattr(os, "open", observed_open)
        monkeypatch.setattr(os, "fstat", observed_fstat)
        monkeypatch.setattr(os, "stat", observed_stat)
        for name in ("read", "readv", "pread", "preadv"):
            if hasattr(os, name):
                monkeypatch.setattr(os, name, descriptor_call(getattr(os, name)))
        monkeypatch.setattr(builtins, "open", stream_open(builtins.open))
        monkeypatch.setattr(io, "open", stream_open(io.open))
        monkeypatch.setattr(os, "fdopen", stream_open(os.fdopen))
        monkeypatch.setattr(io, "FileIO", ObservedFileIO)

    def identity(self, fd):
        result = self.real_fstat(fd)
        return result.st_dev, result.st_ino

    def tracked(self, fd):
        try:
            return any(handle == fd and identity == self.identity(fd) for handle, identity in self.handles)
        except OSError:
            return False

    def position(self, fd):
        try:
            return self.real_lseek(fd, 0, os.SEEK_CUR)
        except OSError:
            return None

    def observe(self, fd, operation, *, stream):
        if not self.tracked(fd) or self.depth:
            return operation()
        event = {"fd": fd, "eligible": self.validated.get(fd, False), "bytes": 0}
        self.attempts.append(event)  # even a read that raises is an attempted read
        before = self.position(fd)
        self.depth += 1
        result = None
        try:
            result = operation()
            return result
        finally:
            self.depth -= 1
            after = self.position(fd)
            if stream and before is not None and after is not None:
                event["bytes"] = max(0, after - before)
            elif isinstance(result, int):
                event["bytes"] = result
            elif result is not None:
                event["bytes"] = len(result)

    def wrap(self, stream):
        if not self.tracked(stream.fileno()):
            return stream
        observer = self

        class DescriptorStream:
            def __getattr__(self, name):
                value = getattr(stream, name)
                if name in observer.content_methods:
                    return lambda *args, **kwargs: observer.observe(
                        stream.fileno(), lambda: value(*args, **kwargs), stream=True
                    )
                if name in {"raw", "buffer"}:
                    return observer.wrap(value)
                if name == "detach":
                    return lambda: observer.wrap(value())
                return value

            def __enter__(self):
                stream.__enter__()
                return self

            def __exit__(self, *args):
                return stream.__exit__(*args)

            def __iter__(self):
                return self

            def __next__(self):
                return observer.observe(stream.fileno(), lambda: next(stream), stream=True)

        return DescriptorStream()

    def assert_closed(self):
        assert not any(self.tracked(fd) for fd, _ in self.handles), "credential descriptor left open"

    def verify(self):
        if self.forbid:
            assert not self.attempts, "content read attempted on invalid credential metadata"
        assert all(event["eligible"] for event in self.attempts), "credential read before eligible descriptor metadata"
        assert sum(event["bytes"] for event in self.attempts) <= 4097, "credential content read exceeded 4097 bytes"
        assert not self.unchecked_opens, "credential open lacked observed no-follow/nonblocking flags"
        self.assert_closed()

    def close_remaining(self):
        for fd, _ in self.handles:
            if self.tracked(fd):
                self.real_close(fd)


@pytest.fixture
def credential_reads(monkeypatch):
    """Independent OS observer; no knowledge of any future loader method."""
    observers = []

    def install(path, **kwargs):
        assert not observers  # one credential boundary per test; no stacked patches
        observer = CredentialReads(monkeypatch, path, **kwargs)
        observers.append(observer)
        return observer

    yield install
    try:
        for observer in observers:
            observer.verify()
    finally:
        for observer in observers:
            observer.close_remaining()


@pytest.mark.parametrize("auth", ["omitted", "none", "valid"])
def test_public_v3_two_pass_preserves_anonymous_payload_and_treatment(auth):
    endpoint = Endpoint(protected=auth == "valid")
    kwargs = {} if auth == "omitted" else {"server_api_key": KEY if auth == "valid" else None}
    raw = client(endpoint, **kwargs)
    try:
        result = describe(raw)
        config = raw.run_configuration()
    finally:
        raw.close()
    assert result["alt_text_title"] == "Fixture title"
    assert result["alt_text_draft"] == "Fixture alt"
    assert len(result["passes"]) == 2
    assert len(endpoint.requests) == 2
    for request, budget in zip(endpoint.requests, [1536, 512], strict=True):
        assert request.headers.get("authorization") == ("Bearer " + KEY if auth == "valid" else None)
        assert not request.headers.get("x-api-key")
        body = json.loads(request.content)
        assert body["model"] == "synthetic-model"
        assert body["temperature"] == 0
        assert body["seed"] == 17
        assert body["max_tokens"] == budget
        assert set(body) == {"model", "messages", "temperature", "max_tokens", "seed"}
        assert set(request.extensions["timeout"].values()) == {0.2}
    assert result["prompt_variant"] == "v3"
    no_leak(json.dumps([config, result]), KEY)


@pytest.mark.parametrize("auth", ["omitted", "wrong"])
def test_protected_refusal_is_401_then_three_strike_breaker_without_fallback(auth):
    endpoint = Endpoint()
    raw = client(endpoint, **({} if auth == "omitted" else {"server_api_key": WRONG}))
    try:
        for _ in range(3):
            with pytest.raises(bakeoff.RemoteClientError) as caught:
                describe(raw)
            assert caught.value.status_code == 401
            no_leak(diagnostics(caught.value), KEY, WRONG)
        with pytest.raises(bakeoff.RemoteClientError, match="circuit open"):
            describe(raw)
    finally:
        raw.close()
    assert len(endpoint.requests) == 3
    assert all(
        r.headers.get("authorization") == (None if auth == "omitted" else "Bearer " + WRONG) for r in endpoint.requests
    )


@pytest.mark.parametrize(
    "token", ["", "space token", "\tkey", "key\r\nInjected: yes", "key\x00", "key\x7f", "nonasciié"]
)
def test_explicit_invalid_key_is_typed_and_private_before_http(token):
    endpoint = Endpoint()
    with pytest.raises(ValueError) as caught:
        raw = client(endpoint, server_api_key=token)
        try:
            pytest.fail("invalid explicit key accepted")
        finally:
            raw.close()
    assert not endpoint.requests
    if token:
        no_leak(diagnostics(caught.value), token)


@pytest.mark.parametrize(
    "mode,payload",
    [(0o400, KEY.encode()), (0o600, KEY.encode() + b"\n"), (0o600, b"visible!#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")],
)
def test_cli_private_file_reaches_both_passes_and_normal_warmup(cli_case, capsys, credential_reads, mode, payload):
    run, root = cli_case
    token = payload.removesuffix(b"\n").decode("ascii")
    endpoint = Endpoint(protected=False)
    path = key_file(root, payload, mode)
    reads = credential_reads(path)
    record = run(endpoint, path)
    assert reads.attempts and sum(event["bytes"] for event in reads.attempts) > 0
    assert len(endpoint.requests) == 4
    assert all(r.headers.get("authorization") == "Bearer " + token for r in endpoint.requests)
    assert record["items"][0]["describe"]["alt_text_title"] == "Fixture title"
    assert not record["items"][0].get("error")
    assert stat.S_IMODE(path.stat().st_mode) == mode
    captured = capsys.readouterr()
    no_leak(json.dumps(record) + captured.out + captured.err, token, str(path), path.name)


def test_cli_anonymous_control_reaches_real_loader_warmup_and_record(cli_case):
    run, _ = cli_case
    endpoint = Endpoint(protected=False)
    record = run(endpoint)
    assert len(endpoint.requests) == 4
    assert all("authorization" not in r.headers for r in endpoint.requests)
    assert record["items"][0]["describe"]["alt_text_title"] == "Fixture title"


@pytest.mark.parametrize("credential", ["missing", "wrong", "valid"])
def test_cli_protected_discrimination_and_bounded_partial_record(cli_case, capsys, credential):
    run, root = cli_case
    endpoint = Endpoint()
    path = None if credential == "missing" else key_file(root, (KEY if credential == "valid" else WRONG).encode())
    if credential == "valid":
        record = run(endpoint, path)
        assert len(endpoint.requests) == 4  # warmup two passes + scored two passes
        assert record["items"][0]["describe"]["alt_text_title"] == "Fixture title"
    else:
        with pytest.raises(SystemExit) as caught:
            run(endpoint, path)
        assert caught.value.code != 0
        assert "BoundedStallError" in str(caught.value)
        record = json.loads((root / "results/record-aborted.json").read_text())
        assert record["aborted"] is True
        assert record["items"][0]["describe"] is None
        assert "401" in record["items"][0]["error"]
        assert len(endpoint.requests) == 2  # warmup refusal, scoring refusal
    captured = capsys.readouterr()
    no_leak(json.dumps(record) + captured.out + captured.err, KEY, WRONG, *([str(path), path.name] if path else []))


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "unreadable",
        "symlink",
        "fifo",
        "directory",
        "foreign-owner",
        "insecure-mode",
        "empty",
        "oversize",
        "multiline",
        "two-lfs",
        "crlf",
        "space",
        "control",
        "nonascii",
    ],
)
def test_cli_invalid_file_refuses_privately_before_network_or_output(cli_case, credential_reads, capsys, case):
    run, root = cli_case
    endpoint = Endpoint()
    path = key_file(root)
    private_content = [KEY]
    if case == "missing":
        path.unlink()
    elif case == "symlink":
        target = root / "target"
        path.rename(target)
        path.symlink_to(target)
    elif case in {"fifo", "directory"}:
        path.unlink()
        os.mkfifo(path, 0o600) if case == "fifo" else path.mkdir()
    elif case == "insecure-mode":
        path.chmod(0o640)
    elif case in {"empty", "oversize", "multiline", "two-lfs", "crlf", "space", "control", "nonascii"}:
        sentinel = f"raw-auth-{case}-credential-sentinel"
        token = sentinel.encode("ascii")
        payloads = {
            "empty": b"",
            "oversize": token + b"a" * (4097 - len(token)),
            "multiline": token + b"\nsecond-line",
            "two-lfs": KEY.encode() + b"\n\n",
            "crlf": KEY.encode() + b"\r\n",
            "space": b" " + token + b" ",
            "control": token + b"\x00",
            "nonascii": token + b"\xff",
        }
        path.write_bytes(payloads[case])
        if case in {"oversize", "multiline", "space", "control", "nonascii"}:
            private_content.append(sentinel)
    credential_reads(
        path,
        foreign_owner=case == "foreign-owner",
        unreadable=case == "unreadable",
        forbid=case in {"foreign-owner", "insecure-mode", "fifo", "directory"},
    )
    with pytest.raises((ValueError, SystemExit)) as caught:
        run(endpoint, path)
    if isinstance(caught.value, SystemExit):
        assert caught.value.code != 0
    captured = capsys.readouterr()
    no_leak(diagnostics(caught.value) + captured.out + captured.err, *private_content, str(path), path.name)
    assert not endpoint.requests
    assert not (root / "results").exists()
    assert not (root / "module/out").exists()


def test_cli_descriptor_survives_path_replacement_without_reopen(cli_case, credential_reads):
    run, root = cli_case
    endpoint = Endpoint()
    path = key_file(root)
    replacement = root / "different-private-key"
    replacement.write_text(WRONG)
    replacement.chmod(0o600)
    reads = credential_reads(path, replacement=replacement)
    record = run(endpoint, path)
    assert reads.replaced and reads.attempts and len(reads.handles) == 1
    assert sum(event["bytes"] for event in reads.attempts) == len(KEY.encode())
    assert len(endpoint.requests) == 4
    assert record["items"][0]["describe"]["alt_text_title"] == "Fixture title"
    assert all(r.headers.get("authorization") == "Bearer " + KEY for r in endpoint.requests)
    reads.assert_closed()


def test_cli_oversize_content_read_stays_bounded(cli_case, credential_reads, capsys):
    run, root = cli_case
    endpoint = Endpoint()
    path = key_file(root, KEY.encode() * 130)  # larger than a 4097-byte overflow probe
    credential_reads(path)
    with pytest.raises((ValueError, SystemExit)) as caught:
        run(endpoint, path)
    if isinstance(caught.value, SystemExit):
        assert caught.value.code != 0
    captured = capsys.readouterr()
    no_leak(diagnostics(caught.value) + captured.out + captured.err, KEY, str(path), path.name)
    assert not endpoint.requests
    assert not (root / "results").exists()
    assert not (root / "module/out").exists()


@pytest.mark.parametrize("failure", ["http-reflection", "transport-reflection", "redirect", "rate-limit", "timeout"])
def test_raw_failures_redact_chains_and_preserve_bounds(failure, monkeypatch):
    reflection = "reflected " + KEY
    endpoint = Endpoint(
        status={"http-reflection": 401, "redirect": 307, "rate-limit": 429}.get(failure), reflection=reflection
    )
    if failure in {"transport-reflection", "timeout"}:

        def fail(request):
            endpoint.requests.append(request)
            error = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
            raise error(reflection, request=request)

        endpoint.transport = httpx.MockTransport(fail)
    raw = client(endpoint, server_api_key=KEY)
    try:
        if failure == "rate-limit":
            # Existing parent configuration seam; eliminate sleep only, not retries.
            monkeypatch.setattr(bakeoff.time, "sleep", lambda seconds: None)
        with pytest.raises(bakeoff.RemoteClientError) as caught:
            describe(raw)
        no_leak(diagnostics(caught.value), KEY)
        assert len(endpoint.requests) == (5 if failure == "rate-limit" else 1)
        assert all(r.headers.get("authorization") == "Bearer " + KEY for r in endpoint.requests)
    finally:
        raw.close()


def test_warmup_refusals_do_not_open_scoring_breaker(cli_case):
    _, root = cli_case
    endpoint = Endpoint()
    original_handle = endpoint.handle

    def fail_warmup(request):
        if len(endpoint.requests) < 3:
            endpoint.requests.append(request)
            return httpx.Response(401)
        return original_handle(request)

    endpoint.transport = httpx.MockTransport(fail_warmup)
    manifest = bakeoff.load_manifest(str(root / "manifest.json"), images_dir=str(root / "images"))
    raw = client(endpoint, server_api_key=KEY)
    try:
        # The real helper called by main must clone the injected transport and
        # credential without sharing the scoring client's breaker state.
        warmup = bakeoff._run_warmup(raw, manifest, str(root / "images"), 3)
        result = describe(raw)
    finally:
        raw.close()
    assert warmup["failed"] == 3 and warmup["succeeded"] == 0
    assert len(endpoint.requests) == 5
    assert all(r.headers.get("authorization") == "Bearer " + KEY for r in endpoint.requests)
    assert result["alt_text_title"] == "Fixture title"


def test_existing_service_auth_remains_x_api_key():
    observed = []

    def handle(request):
        observed.append(request)
        return httpx.Response(200, json={})

    service = bakeoff.RemoteSceneClient(ENDPOINT, api_key=KEY, transport=httpx.MockTransport(handle))
    try:
        service._request("GET", "/control")
    finally:
        service.close()
    assert observed[0].headers["x-api-key"] == KEY
    assert "authorization" not in observed[0].headers


def test_auth_changes_only_wire_credential_not_payload_or_treatment():
    anonymous, protected = Endpoint(protected=False), Endpoint()
    clients = []
    try:
        clients.append(client(anonymous))
        clients.append(client(protected, server_api_key=KEY))
        results = [describe(raw) for raw in clients]
        assert clients[0].run_configuration() == clients[1].run_configuration()
        assert [r.content for r in anonymous.requests] == [r.content for r in protected.requests]
        for field in ("prompt_variant", "prompt_sha256", "model_id", "model_version", "alt_text_draft"):
            assert results[0][field] == results[1][field]
    finally:
        for raw in clients:
            raw.close()


def test_cli_reflected_key_and_private_path_are_absent_from_aborted_record_and_diagnostics(cli_case, capsys):
    run, root = cli_case
    path = key_file(root)
    endpoint = Endpoint(status=401, reflection="reflected " + KEY + " " + str(path))
    with pytest.raises(SystemExit) as caught:
        run(endpoint, path)
    assert "BoundedStallError" in str(caught.value)
    record = json.loads((root / "results/record-aborted.json").read_text())
    assert record["aborted"] is True
    assert "401" in record["items"][0]["error"]
    assert len(endpoint.requests) == 2
    captured = capsys.readouterr()
    no_leak(json.dumps(record) + diagnostics(caught.value) + captured.out + captured.err, KEY, str(path), path.name)


def test_cli_accepts_exact_4096_byte_file_without_truncation(cli_case):
    run, root = cli_case
    token = "A" * 4096
    endpoint = Endpoint(protected=False)
    run(endpoint, key_file(root, token.encode()))
    assert len(endpoint.requests) == 4
    assert all(r.headers.get("authorization") == "Bearer " + token for r in endpoint.requests)


@pytest.mark.parametrize("mode", [0o644, 0o700, 0o4600])
def test_cli_requires_exact_private_mode(cli_case, capsys, credential_reads, mode):
    run, root = cli_case
    endpoint = Endpoint()
    path = key_file(root, mode=mode)
    credential_reads(path, forbid=True)
    with pytest.raises((ValueError, SystemExit)) as caught:
        run(endpoint, path)
    if isinstance(caught.value, SystemExit):
        assert caught.value.code != 0
    captured = capsys.readouterr()
    no_leak(diagnostics(caught.value) + captured.out + captured.err, KEY, str(path), path.name)
    assert not endpoint.requests
    assert not (root / "results").exists()
    assert not (root / "module/out").exists()


def test_cli_successful_reflection_cannot_serialize_credentials_or_private_path(cli_case, capsys):
    run, root = cli_case
    path = key_file(root)
    endpoint = Endpoint(reflection="reflected " + KEY + " " + str(path))
    record = run(endpoint, path)
    assert len(endpoint.requests) == 4
    assert record["items"][0]["describe"] is not None
    captured = capsys.readouterr()
    no_leak(json.dumps(record) + captured.out + captured.err, KEY, str(path), path.name)
