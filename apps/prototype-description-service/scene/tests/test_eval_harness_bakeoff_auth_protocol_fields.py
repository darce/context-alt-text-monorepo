"""Valid RAW credentials must not change response grammar or measured usage.

Exercise the real public client and CLI with identical external response bytes.
Only httpx and the credential-file observer are substituted/observed.
"""

from __future__ import annotations

import json

import httpx
import pytest

from scene.tests import test_eval_harness_bakeoff_raw_auth as approved
from scripts.eval_harness import bakeoff

cli_case = approved.cli_case
CONTROL = "distinct-key-01"
COLLISIONS = [(key, False) for key in ("usage", "message", "content", "title", "{")] + [("text", True)]
FACTS = json.dumps({"people": [], "setting": "harbour", "legible_text": []})
SURFACES = {"title": "Harbour view", "alt": "Boats at dusk.", "caption": "Clouds over quiet water."}
BODIES = tuple(
    json.dumps(
        {
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        }
    ).encode()
    for text in (FACTS, json.dumps(SURFACES))
)
TOKENS = {
    "prompt_tokens": 22,
    "completion_tokens": 14,
    "total_tokens": 36,
    "model_calls": 2,
    "passes_missing_usage": 0,
    "complete": True,
}


class Producer:
    def __init__(self, key, parts=False):
        self.key = key
        self.parts = parts
        self.requests = []
        self.responses = []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request):
        assert request.headers.get("authorization") == "Bearer " + self.key
        assert not request.headers.get("x-api-key")
        assert str(request.url) == approved.ENDPOINT + "/v1/chat/completions"
        body = BODIES[len(self.requests) % 2]
        if self.parts:
            payload = json.loads(body)
            message = payload["choices"][0]["message"]
            message["content"] = [{"type": "text", "text": message["content"]}]
            body = json.dumps(payload).encode()
        self.requests.append(request)
        self.responses.append(body)
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})


def assert_result(result):
    assert result["alt_text_title"] == SURFACES["title"]
    assert result["alt_text_draft"] == SURFACES["alt"]
    assert result["tokens"] == TOKENS


@pytest.fixture
def observed_http_clients(monkeypatch):
    """Observe closure at the external HTTP dependency, including warmup clients."""
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


@pytest.mark.parametrize(("collision", "parts"), COLLISIONS)
def test_describe_preserves_protocol_fields_and_usage(collision, parts, observed_http_clients):
    producers = []
    for key in (CONTROL, collision):
        producer = Producer(key, parts)
        producers.append(producer)
        raw = bakeoff.BakeoffClient(
            approved.ENDPOINT,
            model_id="synthetic-model",
            prompt_variant="v3",
            two_pass=True,
            server_api_key=key,
            transport=producer.transport,
            timeout_s=0.2,
        )
        try:
            result = raw.describe(image_bytes=b"", filename="empty.jpg", media_id=7, context_pack={})
        finally:
            raw.close()
        assert_result(result)
    assert producers[0].responses == producers[1].responses
    assert len(producers[0].responses) == 2
    assert [r.content for r in producers[0].requests] == [r.content for r in producers[1].requests]


@pytest.mark.parametrize(("collision", "parts"), COLLISIONS)
def test_cli_preserves_protocol_fields_usage_and_warmup(collision, parts, cli_case, monkeypatch, observed_http_clients):
    run, root = cli_case
    producers = []
    for key in (CONTROL, collision):
        producer = Producer(key, parts)
        producers.append(producer)
        path = approved.key_file(root, key.encode())
        observer = approved.CredentialReads(monkeypatch, path)
        try:
            record = run(producer, path)
        finally:
            try:
                observer.verify()
            finally:
                observer.close_remaining()
        assert_result(record["items"][0]["describe"])
        assert record["timing"]["warmup"]["succeeded"] == 1
        assert record["timing"]["warmup"]["failed"] == 0
        assert not record.get("aborted")
        assert len(producer.requests) == 4
    assert producers[0].responses == producers[1].responses
    assert len(producers[0].responses) == 4
    assert [r.content for r in producers[0].requests] == [r.content for r in producers[1].requests]
