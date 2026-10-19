"""Response privacy through public describe and actual CLI record boundaries."""

from __future__ import annotations

import ast
import json
import traceback

import httpx
import pytest

from scene.tests import test_eval_harness_bakeoff_raw_auth as approved
from scripts.eval_harness import bakeoff

cli_case = approved.cli_case
CONTROL = "distinct-key-01"
KEY = 'reflection-boundary-7c61"\\Q'
FACTS = {"people": [], "setting": "harbour", "legible_text": []}
SURFACES = {"title": "Harbour view", "alt": "Boats at dusk.", "caption": "Quiet water."}
USAGE = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
TOKENS = {**{k: v * 2 for k, v in USAGE.items()}, "model_calls": 2, "passes_missing_usage": 0, "complete": True}


class Producer:
    """Fixed response bytes under two independently checked Bearer credentials."""

    def __init__(self, key, mode):
        self.key = key
        self.mode = mode
        self.requests = []
        self.responses = []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        assert request.method == "POST"
        assert str(request.url) == approved.ENDPOINT + "/v1/chat/completions"
        assert request.headers.get("authorization") == "Bearer " + self.key
        assert not request.headers.get("x-api-key")
        phase = len(self.requests) % 2
        fields = dict(FACTS if phase == 0 else SURFACES)
        if self.mode == "root-key":
            fields["external-reflection:" + KEY] = "observed"
        elif self.mode == "nested-key":
            fields["extra"] = [{"external-reflection:" + KEY: "observed"}]
        elif self.mode == "string-value":
            fields["setting" if phase == 0 else "caption"] = "external-reflection:" + KEY
        message = {"content": json.dumps(fields)}
        if self.mode in {"plain-error", "nested-error"}:
            message = {
                "content": "",
                "reasoning_content": KEY if self.mode == "plain-error" else json.dumps({"echo": KEY}),
            }
        body = json.dumps({"choices": [{"message": message}], "usage": USAGE}).encode()
        request.read()
        self.requests.append(request)
        self.responses.append(body)
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})


@pytest.fixture
def observed_http_clients(monkeypatch):
    clients = []
    original_init = httpx.Client.__init__

    def init(client, *args, **kwargs):
        original_init(client, *args, **kwargs)
        clients.append(client)

    monkeypatch.setattr(httpx.Client, "__init__", init)
    yield clients
    try:
        assert clients and all(client.is_closed for client in clients)
    finally:
        for client in clients:
            client.close()


def decoded_strings(value):
    """Decode public generated JSON, including arbitrary keys and nested JSON."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from decoded_strings(key)
            yield from decoded_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from decoded_strings(item)
    elif isinstance(value, str):
        yield value
        try:
            decoded = json.loads(value)
        except ValueError:
            return
        if decoded != value:
            yield from decoded_strings(decoded)


def diagnostic_discloses(text):
    # Demonstrate ordinary lossless recovery when a diagnostic carries a
    # Python-literal payload. No payload excerpt is required for a passing SUT.
    for offset, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload = ast.literal_eval(text[offset:].splitlines()[0])
        except (ValueError, SyntaxError):
            continue
        if any(KEY in item for item in decoded_strings(payload)):
            return True
    # Spellings derive solely from the external reflection, with no required
    # diagnostic layout. Include composed JSON/repr escaping, not just raw text.
    nested = json.dumps({"echo": KEY})
    spellings = (KEY, json.dumps(KEY)[1:-1], repr(KEY)[1:-1], repr(nested)[1:-1])
    return any(spelling in text for spelling in spellings)


def invoke(surface, producer, cli_case, monkeypatch, capsys):
    if surface == "describe":
        raw = bakeoff.BakeoffClient(
            approved.ENDPOINT,
            model_id="synthetic-model",
            server_api_key=producer.key,
            prompt_variant="v3",
            two_pass=True,
            transport=producer.transport,
            timeout_s=0.2,
        )
        try:
            try:
                result = approved.describe(raw)
            except bakeoff.RemoteClientError as exc:
                assert type(exc) is bakeoff.RemoteClientError
                assert exc.status_code is None
                assert exc.__cause__ is None and exc.__context__ is None
                return None, approved.diagnostics(exc)
        finally:
            raw.close()
        return result, ""

    run, root = cli_case
    path = approved.key_file(root, producer.key.encode())
    with monkeypatch.context() as observation:
        observer = approved.CredentialReads(observation, path)
        try:
            try:
                record = run(producer, path)
            except SystemExit as exc:
                assert "BoundedStallError" in str(exc)
                record = json.loads((root / "results/record-aborted.json").read_text())
                assert record["aborted"] and record["items"][0]["describe"] is None
                assert record["timing"]["warmup"]["failed"] == 1
                assert record["items"][0]["error"].startswith("RemoteClientError:")
                captured = capsys.readouterr()
                diagnostic = record["items"][0]["error"] + str(exc) + "".join(traceback.format_exception(exc))
                return None, diagnostic + captured.out + captured.err
        finally:
            try:
                observer.verify()
            finally:
                observer.close_remaining()
    assert not record.get("aborted")
    assert record["timing"]["warmup"]["succeeded"] == 1
    assert record["timing"]["warmup"]["failed"] == 0
    captured = capsys.readouterr()
    assert not diagnostic_discloses(captured.out + captured.err)
    return record["items"][0]["describe"], ""


def assert_success(result):
    assert result["alt_text_title"] == SURFACES["title"]
    assert result["alt_text_draft"] == SURFACES["alt"]
    assert result["tokens"] == TOKENS


@pytest.mark.parametrize("surface", ["describe", "cli"])
@pytest.mark.parametrize("location", ["root-key", "nested-key"])
def test_generated_property_names_are_private(surface, location, cli_case, monkeypatch, capsys, observed_http_clients):
    for mode in ("healthy", "string-value", location):
        producers = []
        results = []
        for key in (CONTROL, KEY):
            producer = Producer(key, mode)
            producers.append(producer)
            result, diagnostic = invoke(surface, producer, cli_case, monkeypatch, capsys)
            assert not diagnostic
            assert_success(result)
            assert len(producer.requests) == (2 if surface == "describe" else 4)
            results.append(result)
        assert producers[0].responses == producers[1].responses
        assert producers[0].requests[0].content == producers[1].requests[0].content
        if mode != "healthy":
            assert any(KEY in item for item in decoded_strings(results[0]))
        assert not any(KEY in item for item in decoded_strings(results[1]))


@pytest.mark.parametrize("surface", ["describe", "cli"])
def test_nested_reasoning_is_private_in_typed_errors(surface, cli_case, monkeypatch, capsys, observed_http_clients):
    for mode in ("healthy", "plain-error", "nested-error"):
        producers = []
        diagnostics = []
        for key in (CONTROL, KEY):
            producer = Producer(key, mode)
            producers.append(producer)
            result, diagnostic = invoke(surface, producer, cli_case, monkeypatch, capsys)
            if mode == "healthy":
                assert_success(result)
                assert not diagnostic
            else:
                assert result is None and diagnostic
            assert len(producer.requests) == (
                (2 if surface == "describe" else 4) if mode == "healthy" else (1 if surface == "describe" else 2)
            )
            diagnostics.append(diagnostic)
        assert producers[0].responses == producers[1].responses
        assert [r.content for r in producers[0].requests] == [r.content for r in producers[1].requests]
        assert not diagnostic_discloses(diagnostics[1])
