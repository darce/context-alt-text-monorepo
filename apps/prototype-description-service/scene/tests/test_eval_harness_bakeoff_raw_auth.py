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
def test_cli_private_file_reaches_both_passes_and_normal_warmup(cli_case, capsys, mode, payload):
    run, root = cli_case
    token = payload.removesuffix(b"\n").decode("ascii")
    endpoint = Endpoint(protected=False)
    path = key_file(root, payload, mode)
    record = run(endpoint, path)
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
def test_cli_invalid_file_refuses_privately_before_network_or_output(cli_case, monkeypatch, capsys, case):
    run, root = cli_case
    endpoint = Endpoint()
    path = key_file(root)
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
        payloads = {
            "empty": b"",
            "oversize": b"a" * 4097,
            "multiline": b"one\ntwo",
            "two-lfs": KEY.encode() + b"\n\n",
            "crlf": KEY.encode() + b"\r\n",
            "space": b" key ",
            "control": b"key\x00",
            "nonascii": b"key\xff",
        }
        path.write_bytes(payloads[case])
    real_open, real_fstat = os.open, os.fstat
    opened = set()

    def checked_open(name, flags, *args, **kwargs):
        if os.fspath(name) == str(path):
            assert flags & os.O_NOFOLLOW
            assert flags & os.O_NONBLOCK  # fail before any accidental blocking FIFO open
            if case == "unreadable":
                raise PermissionError(13, "synthetic unreadable", str(path))
            fd = real_open(name, flags, *args, **kwargs)
            opened.add(fd)
            return fd
        return real_open(name, flags, *args, **kwargs)

    def checked_fstat(fd):
        result = real_fstat(fd)
        if fd in opened and case == "foreign-owner":
            fields = list(result)
            fields[4] = os.getuid() + 1
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(os, "open", checked_open)
    monkeypatch.setattr(os, "fstat", checked_fstat)
    with pytest.raises((ValueError, SystemExit)) as caught:
        run(endpoint, path)
    if isinstance(caught.value, SystemExit):
        assert caught.value.code != 0
    captured = capsys.readouterr()
    no_leak(diagnostics(caught.value) + captured.out + captured.err, KEY, str(path), path.name)
    assert not endpoint.requests
    assert not (root / "results").exists()
    assert not (root / "module/out").exists()


def test_cli_descriptor_survives_path_replacement_without_reopen(cli_case, monkeypatch):
    run, root = cli_case
    endpoint = Endpoint()
    path = key_file(root)
    replacement = root / "different-private-key"
    replacement.write_text(WRONG)
    replacement.chmod(0o600)
    real_open, real_fstat, real_read = os.open, os.fstat, os.read
    handles, validated, reads = [], [], []
    identity = path.stat()

    def credential_descriptor(fd):
        try:
            observed = real_fstat(fd)
        except OSError:
            return False
        return (observed.st_dev, observed.st_ino) == (identity.st_dev, identity.st_ino)

    def observed_open(name, flags, *args, **kwargs):
        fd = real_open(name, flags, *args, **kwargs)
        if os.fspath(name) == str(path):
            assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
            handles.append(fd)
        return fd

    def observed_fstat(fd):
        result = real_fstat(fd)
        if fd in handles and credential_descriptor(fd) and not validated:
            validated.append(fd)
            path.unlink()
            path.symlink_to(replacement)
        return result

    def bounded_read(fd, size):
        if fd in handles and credential_descriptor(fd):
            assert fd in validated, "credential bytes read before fstat validation"
            assert 0 < size <= 4097
            reads.append(size)
            assert sum(reads) <= 4097
        return real_read(fd, size)

    class DescriptorReader:
        def __init__(self, stream):
            self.stream = stream

        def read(self, size=-1):
            assert self.stream.fileno() in validated
            assert 0 < size <= 4097
            reads.append(size)
            assert sum(reads) <= 4097
            return self.stream.read(size)

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

    def observe_stream_open(original):
        def stream_open(name, *args, **kwargs):
            if not isinstance(name, int):
                assert os.fspath(name) != str(path), "credential reopened by pathname"
            stream = original(name, *args, **kwargs)
            return (
                DescriptorReader(stream)
                if isinstance(name, int) and name in handles and credential_descriptor(name)
                else stream
            )

        return stream_open

    monkeypatch.setattr(os, "read", bounded_read)
    monkeypatch.setattr(builtins, "open", observe_stream_open(builtins.open))
    monkeypatch.setattr(io, "open", observe_stream_open(io.open))
    monkeypatch.setattr(os, "open", observed_open)
    monkeypatch.setattr(os, "fstat", observed_fstat)
    record = run(endpoint, path)
    assert validated and reads and len(handles) == 1
    assert len(endpoint.requests) == 4
    assert record["items"][0]["describe"]["alt_text_title"] == "Fixture title"
    assert all(r.headers.get("authorization") == "Bearer " + KEY for r in endpoint.requests)
    for fd in handles:
        with pytest.raises(OSError):
            real_fstat(fd)  # no credential descriptor remains open after main


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
def test_cli_requires_exact_private_mode(cli_case, capsys, mode):
    run, root = cli_case
    endpoint = Endpoint()
    path = key_file(root, mode=mode)
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
