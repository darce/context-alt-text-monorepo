"""Composed generated strings stay private at describe, HTTP and CLI boundaries."""

from __future__ import annotations

import json

import httpx
import pytest

from scene.tests import test_eval_harness_bakeoff_raw_auth as approved
from scripts.eval_harness import bakeoff

cli_case = approved.cli_case
CONTROL = "distinct-key-01"
KEY = 'scalar-reflection-unique-94da"\\Q'
FACTS = {"people": [], "setting": "harbour", "legible_text": []}
SURFACES = {"title": "Harbour view", "alt": "Boats at dusk.", "caption": "Quiet water."}
USAGE = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
TOKENS = {**{k: v * 2 for k, v in USAGE.items()}, "model_calls": 2, "passes_missing_usage": 0, "complete": True}


def encode(value, depth):
    for _ in range(depth):
        value = json.dumps(value)
    return value


def decoded_strings(value):
    """Losslessly recover public JSON strings without depending on a marker."""
    pending = [(value, 0)]
    while pending:
        value, depth = pending.pop()
        assert depth < 128, "public encoding oracle exceeded its finite depth"
        if isinstance(value, dict):
            pending.extend((v, depth + 1) for pair in value.items() for v in pair)
        elif isinstance(value, list):
            pending.extend((v, depth + 1) for v in value)
        elif isinstance(value, str):
            yield value
            try:
                decoded = json.loads(value)
            except ValueError:
                continue
            if decoded != value:
                pending.append((decoded, depth + 1))


class Producer:
    """Fixed bytes, independent of the credential supplied by the caller."""

    def __init__(self, key, depth, location="existing", *, oversized=None):
        self.key, self.depth, self.location = key, depth, location
        self.oversized = oversized
        self.requests, self.responses = [], []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        assert request.method == "POST"
        assert str(request.url) == approved.ENDPOINT + "/v1/chat/completions"
        assert request.headers.get("authorization") == "Bearer " + self.key
        assert not request.headers.get("x-api-key")
        phase = len(self.requests) % 2
        fields = dict(FACTS if phase == 0 else SURFACES)
        if self.depth >= 0:
            reflected = encode(KEY, self.depth)
            if self.location == "existing":
                fields["setting" if phase == 0 else "caption"] = reflected
            elif self.location == "container":
                fields["extra"] = [{"encoded": encode({"echo": reflected}, 1)}]
            else:
                fields[encode(KEY, self.depth)] = "observed"
        if self.oversized == "depth":
            fields["extra"] = json.loads("[" * 80 + "null" + "]" * 80)
        elif self.oversized == "size":
            fields["extra"] = "x" * (2 * 1024 * 1024)
        elif self.oversized == "nodes":
            fields["extra"] = [None] * 20000
        body = json.dumps({"choices": [{"message": {"content": json.dumps(fields)}}], "usage": USAGE}).encode()
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


def invoke(surface, producer, cli_case, monkeypatch, capsys, *, refusal=False):
    if surface == "describe":
        raw = bakeoff.BakeoffClient(
            approved.ENDPOINT,
            model_id="synthetic-model",
            server_api_key=producer.key,
            prompt_variant="v3",
            two_pass=True,
            timeout_s=0.2,
            transport=producer.transport,
        )
        try:
            if refusal:
                with pytest.raises(bakeoff.RemoteClientError) as caught:
                    approved.describe(raw)
                assert caught.value.__cause__ is None and caught.value.__context__ is None
                assert not any(KEY in s for s in decoded_strings(approved.diagnostics(caught.value)))
                return None
            return approved.describe(raw)
        finally:
            raw.close()
    run, root = cli_case
    path = approved.key_file(root, producer.key.encode())
    with monkeypatch.context() as observation:
        observer = approved.CredentialReads(observation, path)
        try:
            if refusal:
                with pytest.raises(SystemExit) as caught:
                    run(producer, path)
                assert "BoundedStallError" in str(caught.value)
                record = json.loads((root / "results/record-aborted.json").read_text())
                assert record["aborted"] and record["items"][0]["describe"] is None
                assert record["items"][0]["error"].startswith("RemoteClientError:")
                assert record["timing"]["warmup"]["failed"] == 1
            else:
                record = run(producer, path)
                assert not record.get("aborted")
                assert record["timing"]["warmup"]["succeeded"] == 1
                assert record["timing"]["warmup"]["failed"] == 0
                assert record == json.loads((root / "results/record.json").read_text())
        finally:
            try:
                observer.verify()
            finally:
                observer.close_remaining()
    captured = capsys.readouterr()
    if producer.key == KEY:
        assert not any(KEY in s for s in decoded_strings(captured.out + captured.err))
        assert not any(KEY in s for s in decoded_strings(record)), "credential recoverable from persisted record"
    return None if refusal else record["items"][0]["describe"]


@pytest.mark.parametrize("surface", ["describe", "cli"])
@pytest.mark.parametrize("depth", [2, 3, 6])
@pytest.mark.parametrize("location", ["existing", "container", "property"])
def test_composed_scalar_reflection_is_private(
    surface, depth, location, cli_case, monkeypatch, capsys, observed_http_clients
):
    # Healthy/raw/single controls use the same producer and actual transport.
    for encoding_depth in (-1, 0, 1, depth):
        producers, results = [], []
        for supplied in (CONTROL, KEY):
            producer = Producer(supplied, encoding_depth, location)
            producers.append(producer)
            result = invoke(surface, producer, cli_case, monkeypatch, capsys)
            assert result["alt_text_title"] == SURFACES["title"]
            assert result["alt_text_draft"] == SURFACES["alt"]
            assert result["tokens"] == TOKENS
            assert len(producer.requests) == (2 if surface == "describe" else 4)
            results.append(result)
        assert producers[0].responses == producers[1].responses
        assert producers[0].requests[0].content == producers[1].requests[0].content
        # Public facts forwarded to pass two must be private as well.
        if encoding_depth >= 0:
            assert any(KEY in s for s in decoded_strings(results[0]))
            for request in producers[1].requests:
                assert not any(KEY in s for s in decoded_strings(json.loads(request.content)))
            if location == "existing":
                assert encode(KEY, encoding_depth) == results[0]["alt_text_long"]
        assert not any(KEY in s for s in decoded_strings(results[1])), "credential recoverable from public describe"


@pytest.mark.parametrize("surface", ["describe", "cli"])
@pytest.mark.parametrize("limit", ["depth", "size", "nodes"])
def test_excessive_generated_encoding_is_privately_refused(
    surface, limit, cli_case, monkeypatch, capsys, observed_http_clients
):
    producer = Producer(KEY, -1, oversized=limit)
    invoke(surface, producer, cli_case, monkeypatch, capsys, refusal=True)
    assert len(producer.requests) == (1 if surface == "describe" else 2)
