"""WBUX-4 S6-01: HTTP-level coverage for the describe-run status-poll and cancel
routes.

The INT-03 stream removal (commit 9b9aa45) deleted test_describe_run_stream.py,
which also carried the ONLY route-level test for GET /scene/describe/run/{id}
(status poll) and DELETE /scene/describe/run/{id} (cancel). This restores that
coverage without the removed SSE stream assertions.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager

import pytest

import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import DescribeRunStatus
from scene.domain.description import DescriptionResultTier
from scene.tests.demo_quota_harness import demo_quota_client
from scene.tests.demo_quota_harness import recognition_used as _used
from scene.tests.test_describe_run_worker import TENANT_ID, _client, _submit


def _no_worker(monkeypatch):
    async def _noop(**_):
        return None

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop)


def _create_run(client) -> str:
    response = _submit(client, [70])
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def test_submit_omitted_recognition_enabled_defaults_true(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, sf):
        response = _submit(client, [70])
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["recognition_enabled"] is True

        async def _assert_row():
            async with sf() as s:
                run = await DescribeRunRepository(s).get_run(
                    tenant_id=uuid.UUID(body["tenant_id"]), run_id=uuid.UUID(body["run_id"])
                )
            assert run is not None
            assert run.recognition_enabled is True

        asyncio.run(_assert_row())


def test_submit_persists_recognition_enabled_false(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, sf):
        files = [("image_70", ("70.png", b"\x89PNG\r\n\x1a\n", "image/png"))]
        data = {"tenant_id": str(TENANT_ID), "media_ids": json.dumps([70]), "recognition_enabled": "false"}
        response = client.post("/scene/describe/run", data=data, files=files)
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["recognition_enabled"] is False

        async def _assert_row():
            async with sf() as s:
                run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=uuid.UUID(body["run_id"]))
            assert run is not None
            assert run.recognition_enabled is False

        asyncio.run(_assert_row())


@pytest.mark.parametrize("raw", ["maybe", "yes", "on", "1", "0", "no", "off"])
def test_submit_rejects_non_bool_recognition_enabled(monkeypatch, raw):
    """Contract boolean: only true/false (case-insensitive) or omitted; lax tokens 422."""
    _no_worker(monkeypatch)
    with _client() as (client, _):
        files = [("image_70", ("70.png", b"\x89PNG\r\n\x1a\n", "image/png"))]
        data = {"tenant_id": str(TENANT_ID), "media_ids": json.dumps([70]), "recognition_enabled": raw}
        response = client.post("/scene/describe/run", data=data, files=files)
        assert response.status_code == 422, response.text
        assert "recognition_enabled" in response.text
        assert "boolean" in response.text


@pytest.mark.parametrize("raw, expected", [("TRUE", True), ("False", False)])
def test_submit_accepts_case_insensitive_true_false_recognition_enabled(monkeypatch, raw, expected):
    """true/false remain valid after strip + case-fold; PHP sends exactly those tokens."""
    _no_worker(monkeypatch)
    with _client() as (client, sf):
        files = [("image_70", ("70.png", b"\x89PNG\r\n\x1a\n", "image/png"))]
        data = {"tenant_id": str(TENANT_ID), "media_ids": json.dumps([70]), "recognition_enabled": raw}
        response = client.post("/scene/describe/run", data=data, files=files)
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["recognition_enabled"] is expected

        async def _assert_row():
            async with sf() as s:
                run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=uuid.UUID(body["run_id"]))
            assert run is not None
            assert run.recognition_enabled is expected

        asyncio.run(_assert_row())


def _spy_fusion_loader(monkeypatch, loads: list, result):
    """Bind the loader spy to every reference a Stage-2 leak could reach.

    Patching only `describe_run_mod.load_fusion_naming_inputs` is vacuous: the
    router module does not import that symbol, so `raising=False` invents a
    fresh attribute nobody reads and `loads == []` can never go red. Patch the
    definition site (late/dynamic imports) *and* the worker's module-level
    binding with `raising=True` so a moved or renamed symbol fails loudly, and
    keep the router patch as the belt for a re-added module-level import.
    """
    import scene.application.describe_run_worker as wmod
    import scene.application.naming_preview_service as nps

    async def spy(**kwargs):
        loads.append(kwargs)
        return result

    monkeypatch.setattr(nps, "load_fusion_naming_inputs", spy, raising=True)
    monkeypatch.setattr(wmod, "load_fusion_naming_inputs", spy, raising=True)
    monkeypatch.setattr(describe_run_mod, "load_fusion_naming_inputs", spy, raising=False)


def _fusion_aware_fake_service(captured: dict):
    """Stage-2 fake that injects roster names only when fusion inputs are present.

    A mutant that always writes a roster name into the draft/provenance stays
    GREEN unless the identity-off test asserts injected_names and empty kwargs.
    """

    class _FakeFacts:
        caption = "cap"

    class _FakeService:
        last_phrase_boxes = ()
        last_attachments = ()

        def __init__(self, **kwargs):
            pass

        async def describe(self, **kwargs):
            captured["kwargs"] = kwargs
            faces = list(kwargs.get("confirmed_faces") or [])
            policy = kwargs.get("naming_policy")
            if faces and policy is not None:
                names = [getattr(face, "label", None) or str(face) for face in faces]
            else:
                names = []
            captured["injected_names"] = names
            draft = f"draft with {', '.join(names)}" if names else "draft"

            class _FakeResponse:
                adapter = "seeded"
                model_id = "m"
                model_version = "v"
                prompt_or_task_version = "p"
                image_hash = "h"
                context_hash = "c"
                cached = False
                duration_ms = 1
                alt_text_draft = draft
                visual_facts = _FakeFacts()
                injected_names = names
                # Seeded/CPU adapter: mirrors VisualFactsService's non-GPU tier.
                tier = DescriptionResultTier.PROVISIONAL_CPU

            return _FakeResponse()

    return _FakeService


ROSTER_NAME = "Ada"


class _NoCacheDescriptionRepository:
    """Persistence-only stub for the ImageDescription cache seam.

    The run-route harness DB creates tenant + run tables only, so a real
    ImageDescriptionRepository would raise on the cache read before any naming
    code executed. Stubbing *only* persistence keeps VisualFactsService itself
    real, so the draft, phrase boxes, attachments and provenance the assertions
    read are produced by production code rather than by a fake that echoes its
    own inputs back (TEST-06: a proxy that can diverge from the real behavior
    certifies zero).
    """

    def __init__(self, session) -> None:
        self._session = session

    async def get_by_cache_key(self, **_kwargs):
        return None

    async def insert_or_get_existing(self, record):
        return record, True


class _NoopAuditSink:
    """Audit table is absent in this harness; the sink is not under test."""

    def __init__(self, _repository=None) -> None:
        pass

    async def record(self, **_kwargs) -> None:
        return None


def _context_capturing_adapter(calls: list):
    """Wrap the REAL seeded adapter and record the context handed to the model.

    `context` is the entire non-image payload the description model receives, so
    a name that reaches it is a name that reaches the prompt (SEC-01: the
    app->LLM crossing is a trust boundary and must be asserted at the crossing).
    """
    from scene.application.seeded_adapter import SeededDescriptionAdapter

    inner = SeededDescriptionAdapter()

    class _Recording:
        kind = inner.kind
        model_id = inner.model_id
        model_version = inner.model_version
        prompt_or_task_version = inner.prompt_or_task_version

        def describe(self, *, image_bytes, context):
            calls.append({"image_bytes": image_bytes, "context": context})
            return inner.describe(image_bytes=image_bytes, context=context)

    return _Recording()


def _recording_real_visual_facts_service(calls: list):
    """Subclass (not replace) the real service so describe() kwargs are observable."""
    real = describe_run_mod.VisualFactsService

    class _Recording(real):  # type: ignore[valid-type, misc]
        async def describe(self, **kwargs):
            calls.append(kwargs)
            return await super().describe(**kwargs)

    return _Recording


def _leak_surface(outcome, adapter_calls: list) -> str:
    """Every operator/model-visible surface Stage-2 can leak a name through."""
    return json.dumps(
        {
            "alt_text_draft": outcome.alt_text_draft,
            "caption": outcome.caption,
            "provenance": outcome.provenance,
            "phrase_boxes": [str(box) for box in (outcome.phrase_boxes or ())],
            "attachments": [str(att) for att in (outcome.attachments or ())],
            "adapter_context": [call["context"] for call in adapter_calls],
        },
        default=str,
    )


def test_stage2_leaks_no_roster_name_to_the_model_when_recognition_disabled(monkeypatch):
    """Identity-off Stage-2 must not load fusion inputs nor leak a roster name.

    Privacy invariant (SEC-01 + RLSE-05): with recognition disabled, no roster
    name may reach the description model's context or any surface derived from
    it. Driven through the REAL VisualFactsService and the REAL seeded adapter
    so the assertions read production output, not a fake's echo of its own
    kwargs (TEST-15: the green must be able to go red on a real leak).
    """
    loads: list = []
    service_calls: list = []
    adapter_calls: list = []

    _spy_fusion_loader(monkeypatch, loads, ([ROSTER_NAME], object()))
    monkeypatch.setattr(describe_run_mod, "ImageDescriptionRepository", _NoCacheDescriptionRepository)
    monkeypatch.setattr(describe_run_mod, "_DescriptionAuditSink", _NoopAuditSink)
    monkeypatch.setattr(describe_run_mod, "VisualFactsService", _recording_real_visual_facts_service(service_calls))

    with _client() as (_http, sf):
        describe_one = describe_run_mod._build_describe_one(
            session_factory=sf,
            tenant_id=TENANT_ID,
            adapter=_context_capturing_adapter(adapter_calls),
            recognition_enabled=False,
        )
        outcome = asyncio.run(describe_one(1, b"\x89PNG\r\n\x1a\nbytes", "image/png"))

    # 1. No fusion naming load may fire at all on the identity-off path.
    assert loads == [], f"recognition-disabled Stage-2 loaded fusion naming inputs: {loads!r}"

    # 2. Nothing name-bearing may cross into the service.
    assert len(service_calls) == 1, f"expected exactly one describe() call, got {len(service_calls)}"
    kwargs = service_calls[0]
    assert kwargs.get("confirmed_faces") == [], f"roster faces crossed into Stage-2: {kwargs.get('confirmed_faces')!r}"
    assert kwargs.get("naming_policy") is None, "naming policy crossed into Stage-2 with recognition disabled"

    # 3. The model actually ran, and its context carried no identity payload.
    assert len(adapter_calls) == 1, f"expected exactly one adapter call, got {len(adapter_calls)}"
    assert adapter_calls[0]["context"] is None, f"identity-off describe sent context {adapter_calls[0]['context']!r}"

    # 4. End-to-end: the name appears on no produced surface.
    assert outcome.alt_text_draft, "real adapter produced no draft; the leak check would be vacuous"
    assert ROSTER_NAME not in _leak_surface(outcome, adapter_calls), (
        f"roster name {ROSTER_NAME!r} leaked with recognition disabled: {_leak_surface(outcome, adapter_calls)}"
    )


def test_stage2_loads_fusion_naming_inputs_once_and_injects_names_when_recognition_enabled(monkeypatch):
    """Positive twin: identity-on Stage-2 reuses the preloaded snapshot and injects names."""
    from types import SimpleNamespace

    loads: list = []
    captured: dict = {}
    policy = object()

    _spy_fusion_loader(monkeypatch, loads, (["Ada"], policy))
    monkeypatch.setattr(describe_run_mod, "VisualFactsService", _fusion_aware_fake_service(captured))

    with _client() as (_http, sf):
        describe_one = describe_run_mod._build_describe_one(
            session_factory=sf,
            tenant_id=TENANT_ID,
            adapter=SimpleNamespace(kind="seeded"),
            recognition_enabled=True,
        )
        outcome = asyncio.run(describe_one(1, b"bytes", "image/png", naming_inputs=(["Ada"], policy)))
    assert loads == []
    kwargs = captured["kwargs"]
    assert kwargs.get("confirmed_faces") == ["Ada"]
    assert kwargs.get("naming_policy") is policy
    assert captured["injected_names"] == ["Ada"]
    assert "Ada" in outcome.alt_text_draft


def test_stage2_fails_closed_when_recognition_enabled_and_naming_inputs_missing(monkeypatch):
    """DATA-19: recognition-on Stage-2 must not reload; missing snapshot fails closed."""
    from types import SimpleNamespace

    from scene.application.describe_run_worker import MissingNamingSnapshotError

    loads: list = []
    captured: dict = {}

    _spy_fusion_loader(monkeypatch, loads, (["Ada"], object()))
    monkeypatch.setattr(describe_run_mod, "VisualFactsService", _fusion_aware_fake_service(captured))

    with _client() as (_http, sf):
        describe_one = describe_run_mod._build_describe_one(
            session_factory=sf,
            tenant_id=TENANT_ID,
            adapter=SimpleNamespace(kind="seeded"),
            recognition_enabled=True,
        )
        with pytest.raises(MissingNamingSnapshotError, match="naming_inputs"):
            asyncio.run(describe_one(1, b"bytes", "image/png"))
    assert loads == []
    assert "kwargs" not in captured


def test_status_route_returns_run_snapshot(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        run_id = _create_run(client)
        status_response = client.get(f"/scene/describe/run/{run_id}")
        assert status_response.status_code == 200, status_response.text
        body = status_response.json()
        assert body["run_id"] == run_id
        assert body["status"] == DescribeRunStatus.PENDING
        assert "eta_seconds" in body


def test_status_route_404_for_unknown_run(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        missing = uuid.uuid4()
        resp = client.get(f"/scene/describe/run/{missing}")
        assert resp.status_code == 404


def test_cancel_route_flags_cancel_requested(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        run_id = _create_run(client)
        cancel_response = client.delete(f"/scene/describe/run/{run_id}")
        assert cancel_response.status_code == 200, cancel_response.text
        body = cancel_response.json()
        assert body["cancel_requested"] is True
        # A cancel on a still-PENDING run resolves terminal-CANCELLED immediately.
        assert body["status"] == DescribeRunStatus.CANCELLED


def test_cancel_route_404_for_unknown_run(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        missing = uuid.uuid4()
        resp = client.delete(f"/scene/describe/run/{missing}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DS-2B: demo shared compute budget on describe/run (batch all-or-nothing)
# ---------------------------------------------------------------------------


@contextmanager
def _demo_run_client(*, recognition_quota: int = 5, non_demo: bool = False):
    """Describe/run client — shared harness with run tables (DS2B-PM-H-02)."""
    with demo_quota_client(recognition_quota=recognition_quota, non_demo=non_demo, tables="run") as ctx:
        yield ctx


def _submit_run(client, tenant_id: str, media_ids: list[int]):
    files = [(f"image_{m}", (f"{m}.png", b"\x89PNG\r\n\x1a\n", "image/png")) for m in media_ids]
    data = {"tenant_id": str(tenant_id), "media_ids": json.dumps(media_ids)}
    return client.post("/scene/describe/run", data=data, files=files or None)


def test_demo_quota_run_all_or_nothing_and_success(monkeypatch):
    _no_worker(monkeypatch)
    # budget N-1 → 429, used unchanged; then budget >= N → 202 and used += N
    with _demo_run_client(recognition_quota=2) as (client, sf, _p, tenant_id, slug):
        fail = _submit_run(client, tenant_id, [1, 2, 3])
        assert fail.status_code == 429, fail.text
        detail = fail.json()["detail"]
        assert detail["code"] == "demo_quota_exceeded"
        assert detail["quota_remaining"] == 2
        assert _used(sf, slug) == 0

        ok = _submit_run(client, tenant_id, [1, 2])
        assert ok.status_code == 202, ok.text
        assert _used(sf, slug) == 2


def test_demo_quota_run_empty_media_ids_422_no_consume(monkeypatch):
    _no_worker(monkeypatch)
    with _demo_run_client(recognition_quota=5) as (client, sf, _p, tenant_id, slug):
        # Explicit empty JSON array; no image parts.
        resp = client.post(
            "/scene/describe/run",
            data={"tenant_id": str(tenant_id), "media_ids": "[]"},
        )
        assert resp.status_code == 422, resp.text
        assert "'media_ids' must be non-empty" in resp.text
        assert _used(sf, slug) == 0


def test_demo_quota_run_non_demo_key_unaffected(monkeypatch):
    _no_worker(monkeypatch)
    with _demo_run_client(recognition_quota=1, non_demo=True) as (client, sf, _p, tenant_id, slug):
        resp = _submit_run(client, tenant_id, [7, 8])
        assert resp.status_code == 202, resp.text
        assert _used(sf, slug) == 0


def test_demo_quota_run_lifecycle_get_delete_consume_nothing(monkeypatch):
    _no_worker(monkeypatch)
    with _demo_run_client(recognition_quota=5) as (client, sf, _p, tenant_id, slug):
        created = _submit_run(client, tenant_id, [70])
        assert created.status_code == 202, created.text
        run_id = created.json()["run_id"]
        used = _used(sf, slug)
        assert used == 1

        status_resp = client.get(f"/scene/describe/run/{run_id}")
        assert status_resp.status_code == 200, status_resp.text
        assert _used(sf, slug) == used

        cancel_resp = client.delete(f"/scene/describe/run/{run_id}")
        assert cancel_resp.status_code == 200, cancel_resp.text
        assert _used(sf, slug) == used


def test_demo_quota_run_duplicate_media_ids_charge_unique_only(monkeypatch):
    """Duplicates must not over-charge (DS2B-PM-S2-04): units = unique media_ids."""
    _no_worker(monkeypatch)
    with _demo_run_client(recognition_quota=5) as (client, sf, _p, tenant_id, slug):
        # Three listed ids, two unique — charge 2.
        resp = _submit_run(client, tenant_id, [1, 1, 2])
        assert resp.status_code == 202, resp.text
        assert _used(sf, slug) == 2


def test_bulk_endpoints_404_for_single_run_kind(monkeypatch):
    """Design (g): single-run ids are unreachable via bulk get/items/cancel."""
    _no_worker(monkeypatch)
    with _client() as (client, sf):
        # Create a single-run directly in the shared test DB.
        async def _seed():
            from scene.application.describe_run_repository import DescribeRunRepository
            from scene.tests.test_describe_run_worker import TENANT_ID as _TENANT

            async with sf() as s:
                repo = DescribeRunRepository(s)
                run_id = await repo.create_single_run(tenant_id=_TENANT, media_id=9001, image_bytes=b"single")
                await s.commit()
                return str(run_id)

        import asyncio

        run_id = asyncio.run(_seed())
        for path in (
            f"/scene/describe/run/{run_id}",
            f"/scene/describe/run/{run_id}/items",
        ):
            resp = client.get(path)
            assert resp.status_code == 404, (path, resp.text)
        cancel = client.delete(f"/scene/describe/run/{run_id}")
        assert cancel.status_code == 404, cancel.text


@pytest.mark.parametrize(
    "media_ids, part_ids, part_size, unknown_size, expected",
    [
        ([1], [1, 999], 31, False, 202),
        ([1], [1, 1], 31, False, 202),
        ([1], [999, 998], 31, False, 422),
        ([1], [1], 2 * 1024 * 1024, True, 413),
        ([1, 2], [1, 2], 33, False, 413),
        ([1, 2], [1, 2], 32, False, 202),
        ([], [999], 31, False, 422),
    ],
)
def test_submit_bounds_image_reads(monkeypatch, media_ids, part_ids, part_size, unknown_size, expected):
    from starlette.datastructures import UploadFile
    from starlette.requests import Request

    _no_worker(monkeypatch)
    cap = 32
    settings = describe_run_mod.DescriptionSettings(max_description_image_bytes=cap)
    monkeypatch.setattr(describe_run_mod, "DescriptionSettings", lambda: settings)
    original_form = Request.form
    original_read = UploadFile.read
    reads = []
    served = 0

    async def bounded_form(self, *args, **kwargs):
        form = await original_form(self, *args, **kwargs)
        if unknown_size:
            for _, value in form.multi_items():
                if isinstance(value, UploadFile):
                    value.size = None
        return form

    async def spy_read(self, size=-1):
        nonlocal served
        media_id = int(self.filename.split(".")[0])
        assert media_id in media_ids, "must not be read"
        assert size == 1024 * 1024
        reads.append(self)
        data = await original_read(self, size)
        served += len(data)
        return data

    monkeypatch.setattr(Request, "form", bounded_form)
    monkeypatch.setattr(UploadFile, "read", spy_read)
    with _client() as (client, _):
        response = client.post(
            "/scene/describe/run",
            data={"tenant_id": str(TENANT_ID), "media_ids": json.dumps(media_ids)},
            files=[(f"image_{i}", (f"{i}.png", b"x" * part_size, "image/png")) for i in part_ids],
        )
    assert response.status_code == expected, response.text
    if expected == 413:
        assert served <= cap + 1024 * 1024
        if not unknown_size:
            assert not reads
    if part_ids == [1, 1]:
        assert len({id(upload) for upload in reads}) == 1
    if part_ids == [999, 998]:
        assert response.json()["detail"] == "missing image_<media_id> part(s) for media_ids: [1]"
        assert not reads
    if not media_ids:
        assert not reads
