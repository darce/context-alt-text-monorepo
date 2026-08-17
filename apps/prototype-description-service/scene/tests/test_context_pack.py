"""E20-9: typed context-pack contract and seeded adapter enrichment."""

import asyncio
import json
import threading
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.application.visual_facts_service import VisualFactsService
from scene.interface_adapters.http.deps import get_description_adapter
from scene.interface_adapters.http.router import router as scene_router
from scene.interface_adapters.http.schemas.requests import DescribeImageEnvelope

TENANT_ID = "00000000-0000-0000-0000-0000000000bb"
IMG = b"\x89PNG\r\n context pack test image bytes"


class _Auth:
    tenant_claim = None
    user_id = None


class CapturingAdapter:
    kind = SeededDescriptionAdapter.kind
    model_id = SeededDescriptionAdapter().model_id
    model_version = SeededDescriptionAdapter().model_version
    prompt_or_task_version = SeededDescriptionAdapter().prompt_or_task_version

    def __init__(self):
        self.inner = SeededDescriptionAdapter()
        self.context = None

    def describe(self, *, image_bytes, context):
        self.context = context
        return self.inner.describe(image_bytes=image_bytes, context=context)


def _context_pack():
    return {
        "attachment": {
            "title": "Summer sale hero",
            "caption": "Model wearing a red jacket beside the trail.",
            "filename": "summer-sale-red-jacket.jpg",
        },
        "post": {
            "title": "Trail jackets for spring",
            "post_type": "product",
            "status": "publish",
        },
        "taxonomy_terms": [
            {"taxonomy": "product_cat", "name": "Jackets", "slug": "jackets"},
            {"taxonomy": "product_tag", "name": "Spring", "slug": "spring"},
        ],
        "identity": {
            "policy": {"person_naming": "disabled"},
            "identities": [],
            "review_reasons": ["person_naming_policy_disabled"],
        },
    }


def test_request_accepts_typed_context_pack_and_rejects_unbounded_terms():
    envelope = DescribeImageEnvelope.model_validate(
        {"tenant_id": TENANT_ID, "media_id": 7, "context_pack": _context_pack()}
    )

    assert envelope.context_pack is not None
    assert envelope.context_pack.attachment is not None
    assert envelope.context_pack.attachment.title == "Summer sale hero"
    assert envelope.context_pack.taxonomy_terms[0].name == "Jackets"
    assert envelope.context_pack.identity is not None
    assert envelope.context_pack.identity.policy.person_naming == "disabled"
    assert envelope.context_pack.identity.review_reasons == ["person_naming_policy_disabled"]

    bad = {"tenant_id": TENANT_ID, "media_id": 7, "context_pack": {"taxonomy_terms": []}}
    bad["context_pack"]["taxonomy_terms"] = [
        {"taxonomy": "product_tag", "name": f"Tag {i}", "slug": f"tag-{i}"} for i in range(21)
    ]
    try:
        DescribeImageEnvelope.model_validate(bad)
    except ValidationError as exc:
        assert "taxonomy_terms" in str(exc)
    else:
        raise AssertionError("taxonomy_terms must be bounded")


def test_seeded_adapter_applies_context_pack_sources():
    generic = SeededDescriptionAdapter().describe(image_bytes=IMG, context=None)
    contextual = SeededDescriptionAdapter().describe(image_bytes=IMG, context=_context_pack())

    assert contextual.context_applied is True
    assert contextual.context_sources == ("attachment.title", "attachment.caption", "post.title", "taxonomy_terms")
    assert "Summer sale hero" in contextual.alt_text_draft
    assert contextual.alt_text_draft != generic.alt_text_draft


def test_service_reports_context_used_from_adapter():
    async def body():
        response = await VisualFactsService(adapter=SeededDescriptionAdapter()).describe(
            tenant_id=uuid.UUID(TENANT_ID),
            media_id=7,
            image_bytes=IMG,
            context=_context_pack(),
        )
        assert response.context_used.applied is True
        assert response.context_used.sources == [
            "attachment.title",
            "attachment.caption",
            "post.title",
            "taxonomy_terms",
        ]
        assert "Summer sale hero" in response.alt_text_draft

    asyncio.run(body())


class DescribeClientDidNotFinish(TimeoutError):
    """Named hang: in-process ASGI portal/handler, not an HTTP socket timeout."""


def _scene_describe_app(adapter):
    app = FastAPI()
    app.include_router(scene_router, prefix="/scene")
    app.dependency_overrides[require_write_access] = lambda: _Auth()
    app.dependency_overrides[enforce_demo_quota] = lambda: None
    app.dependency_overrides[get_optional_session] = lambda: None
    app.dependency_overrides[get_description_adapter] = lambda: adapter
    return app


def _post_describe_bounded(app, *, timeout_s: float = 8.0):
    """Drive /scene/describe/multipart through TestClient, fail named on stall.

    Starlette TestClient is in-process ASGI (``_TestClientTransport``). It does
    not bind a port or open an HTTP socket; ``client.post(..., timeout=)`` is
    ignored (starlette#1108). ``with TestClient`` does call
    ``socket.socketpair()`` to build the asyncio self-pipe — a sandbox that
    blocks that call hangs in ``TestClient.__enter__`` until the job timeout.
    """
    payload = {
        "request": json.dumps(
            {"tenant_id": TENANT_ID, "media_id": 7, "context_pack": _context_pack()}
        )
    }
    files = {"image_7": ("x.jpg", IMG, "image/jpeg")}
    box: dict = {}

    def _run() -> None:
        try:
            with TestClient(app) as client:
                box["response"] = client.post(
                    "/scene/describe/multipart",
                    data=payload,
                    files=files,
                )
        except Exception as exc:  # noqa: BLE001 — re-raised on the caller thread
            box["error"] = exc

    worker = threading.Thread(target=_run, name="r6e3-testclient-describe", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise DescribeClientDidNotFinish(
            f"TestClient /scene/describe/multipart did not finish in {timeout_s}s. "
            "This client is in-process ASGI (_TestClientTransport); it does not "
            "bind a port or open an HTTP socket. timeout= on client.post is "
            "ignored (starlette#1108). Hang is TestClient.__enter__ (anyio "
            "portal → asyncio socketpair) or an ASGI handler that never returns."
        )
    if "error" in box:
        raise box["error"]
    return box["response"]


def test_route_passes_normalized_context_pack_to_adapter():
    adapter = CapturingAdapter()
    response = _post_describe_bounded(_scene_describe_app(adapter))

    assert response.status_code == 200, response.text
    assert adapter.context == _context_pack()
    assert response.json()["context_used"]["applied"] is True
