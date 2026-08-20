"""E20-FUSION S3: attachment provenance on VisualFactsResponse (additive-optional).

Real producer shapes: ContextPack (requests.py), VisualFactsPrior path via the
service Stage-1/2 fuse, Attachment from reconcile.py.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from pydantic import ValidationError

from scene.application.identity_merge import NamingPolicy, NormalizedBox
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.application.visual_facts_service import VisualFactsService
from scene.interface_adapters.http.schemas.requests import (
    ContextPack,
    IdentityContext,
    IdentityContextItem,
    IdentityPolicyContext,
    ProductContext,
    TaxonomyTermContext,
)
from scene.interface_adapters.http.schemas.responses import (
    AttachmentFactProvenance,
    AttachmentProvenance,
    VisualFactsResponse,
)
from scene.tests.identity_merge_helpers import make_face, make_phrase_box

TENANT = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
CAPTION = "A person standing outdoors near greenery."
PERSON_BOX = NormalizedBox(x=0.3, y=0.1, width=0.3, height=0.7)
FACE_BOX = NormalizedBox(x=0.4, y=0.2, width=0.05, height=0.08)


class _CaptionAdapter:
    """Adapter that returns a fixed caption + optional phrase boxes (real shapes)."""

    kind = SeededDescriptionAdapter.kind
    model_id = "fusion-test"
    model_version = "1"
    prompt_or_task_version = "1"

    def __init__(self, *, caption: str = CAPTION, phrase_boxes=(), objects=("person",)):
        self._caption = caption
        self._phrase_boxes = tuple(phrase_boxes)
        self._objects = tuple(objects)
        self.calls = 0
        self.last_context = None

    def describe(self, *, image_bytes, context):
        self.calls += 1
        self.last_context = context
        from scene.application.description_adapter import AdapterResult

        return AdapterResult(
            caption=self._caption,
            objects=self._objects,
            ocr_text=None,
            alt_text_draft=self._caption,
            context_sources=("context_pack",) if context else (),
            context_applied=bool(context),
            phrase_boxes=self._phrase_boxes,
        )


def _identity_pack(*, person_naming: str = "allowed") -> ContextPack:
    return ContextPack(
        identity=IdentityContext(
            policy=IdentityPolicyContext(person_naming=person_naming),
            identities=[
                IdentityContextItem(
                    name="Slate Willow",
                    identity_id="identity-maria",
                    cluster_id="cluster-maria",
                    source="roster",
                )
            ],
            review_reasons=[],
        ),
        product=ProductContext(name="Trail Jacket"),
        taxonomy_terms=[
            TaxonomyTermContext(taxonomy="event", name="Garden picnic", slug="garden-picnic"),
            TaxonomyTermContext(taxonomy="place", name="Meadow", slug="meadow"),
        ],
    )


def test_attachment_provenance_field_is_optional_and_extra_forbid():
    """Additive-optional: absent OK; unknown keys rejected (extra=forbid)."""
    sample = {
        "tenant_id": str(TENANT),
        "media_id": 42,
        "image_hash": "a" * 64,
        "context_hash": "b" * 64,
        "adapter": "seeded",
        "model_id": "seeded-fixtures",
        "model_version": "1",
        "prompt_or_task_version": "1",
        "visual_facts": {"caption": "x", "objects": [], "ocr_text": None},
        "alt_text_draft": "x",
        "context_used": {"sources": [], "applied": False},
        "provider_disclosure": {"provider": "none", "left_service_boundary": False},
        "cached": False,
        "duration_ms": 1,
        "retention_class": "retain_all",
    }
    r = VisualFactsResponse.model_validate(sample)
    assert r.attachment_provenance is None

    sample["attachment_provenance"] = {
        "facts": [
            {
                "fact_id": "product:name:Trail Jacket",
                "fact_source": "product",
                "fact_label": "Trail Jacket",
                "decision": "caption",
                "altitude": "caption",
                "target_evidence": None,
                "review_reason": None,
                "visible": False,
            }
        ]
    }
    r2 = VisualFactsResponse.model_validate(sample)
    assert r2.attachment_provenance is not None
    assert len(r2.attachment_provenance.facts) == 1
    assert r2.attachment_provenance.facts[0].decision == "caption"

    bad = dict(sample)
    bad["attachment_provenance"] = {"facts": [], "sneaky": True}
    with pytest.raises(ValidationError):
        VisualFactsResponse.model_validate(bad)

    bad_fact = dict(sample)
    bad_fact["attachment_provenance"] = {
        "facts": [
            {
                "fact_id": "x",
                "fact_source": "product",
                "fact_label": "x",
                "decision": "caption",
                "altitude": "caption",
                "extra_key": 1,
            }
        ]
    }
    with pytest.raises(ValidationError):
        VisualFactsResponse.model_validate(bad_fact)


def test_service_surfaces_provenance_for_context_pack_facts():
    """Generated describe with ContextPack → attachment_provenance.facts populated."""
    pack = _identity_pack()
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)
    adapter = _CaptionAdapter(phrase_boxes=[phrase])
    face = make_face(
        "Slate Willow",
        box=FACE_BOX,
        cluster_id="cluster-maria",
        identity_id="identity-maria",
        roster_id="roster-maria",
    )

    async def body():
        svc = VisualFactsService(adapter=adapter, repository=None)
        return await svc.describe(
            tenant_id=TENANT,
            media_id=7,
            image_bytes=b"\x89PNG fusion-prov",
            context=pack.model_dump(exclude_none=True),
            confirmed_faces=[face],
            naming_policy=NamingPolicy(agreement_enabled=True),
        )

    response = asyncio.run(body())
    assert adapter.calls == 1  # interactive tier: caption-derived Stage-1, no second pass
    assert response.attachment_provenance is not None
    facts = {f.fact_id: f for f in response.attachment_provenance.facts}
    assert "identity:cluster:cluster-maria" in facts
    identity = facts["identity:cluster:cluster-maria"]
    assert identity.decision == "object"
    assert identity.altitude == "object"
    assert identity.visible is True
    assert identity.target_evidence == "person"
    assert identity.review_reason is None

    product = facts["product:name:Trail Jacket"]
    assert product.decision == "caption"
    assert product.visible is False

    event = facts["event:garden-picnic"]
    assert event.decision == "caption"
    assert event.fact_source == "event"
    assert event.visible is False

    place = facts["place:meadow"]
    assert place.decision == "caption"
    assert place.fact_source == "place"


def test_service_empty_context_yields_empty_facts_not_required():
    """No ContextPack → empty facts list; field still additive-optional shape."""
    adapter = _CaptionAdapter()

    async def body():
        svc = VisualFactsService(adapter=adapter, repository=None)
        return await svc.describe(
            tenant_id=TENANT,
            media_id=1,
            image_bytes=b"x",
            context=None,
        )

    response = asyncio.run(body())
    assert response.attachment_provenance is not None
    assert response.attachment_provenance.facts == []
    assert isinstance(response.attachment_provenance, AttachmentProvenance)


def test_legacy_context_dict_yields_empty_facts():
    """Legacy free-form context is not a ContextPack → no typed facts (degrade)."""
    adapter = _CaptionAdapter()

    async def body():
        svc = VisualFactsService(adapter=adapter, repository=None)
        return await svc.describe(
            tenant_id=TENANT,
            media_id=1,
            image_bytes=b"x",
            context={"title": "Legacy", "caption": "old shape"},
        )

    response = asyncio.run(body())
    assert response.attachment_provenance is not None
    assert response.attachment_provenance.facts == []


def test_face_not_detected_drops_identity_with_review_reason():
    """Detector-backed conflict: pack identity without matching face → dropped."""
    pack = _identity_pack()
    adapter = _CaptionAdapter()

    async def body():
        svc = VisualFactsService(adapter=adapter, repository=None)
        return await svc.describe(
            tenant_id=TENANT,
            media_id=1,
            image_bytes=b"x",
            context=pack.model_dump(exclude_none=True),
            confirmed_faces=[],  # no faces → face_not_detected
            naming_policy=NamingPolicy(agreement_enabled=True),
        )

    response = asyncio.run(body())
    facts = {f.fact_id: f for f in response.attachment_provenance.facts}
    identity = facts["identity:cluster:cluster-maria"]
    assert identity.decision == "dropped"
    assert identity.altitude == "none"
    assert identity.review_reason == "face_not_detected"
    assert identity.visible is False


class _TierAdapter(_CaptionAdapter):
    """Adapter double whose context=None pass returns a DIFFERENT caption.

    Retained to prove the fusion stage never issues a context=None inference:
    if a second (isolation) pass ever regressed back in, ``calls`` would exceed
    one and the isolation caption would surface. ``isolation_caption`` is the
    canary text that must never reach reconcile.
    """

    def __init__(self, *, main_caption: str, isolation_caption: str, phrase_boxes=()):
        super().__init__(caption=main_caption, phrase_boxes=phrase_boxes)
        self._isolation_caption = isolation_caption
        self.contexts: list = []

    def describe(self, *, image_bytes, context):
        self.contexts.append(context)
        if context is None:
            self.calls += 1
            from scene.application.description_adapter import AdapterResult

            return AdapterResult(
                caption=self._isolation_caption,
                objects=self._objects,
                ocr_text=None,
                alt_text_draft=self._isolation_caption,
                context_sources=(),
                context_applied=False,
                phrase_boxes=(),
            )
        return super().describe(image_bytes=image_bytes, context=context)


class _FakeRepo:
    """In-memory ImageDescriptionRepository shape (cache-key lookup + insert race)."""

    def __init__(self):
        self._rows: dict = {}

    async def get_by_cache_key(
        self, *, tenant_id, image_hash, adapter, model_version, prompt_or_task_version, context_hash
    ):
        return self._rows.get((str(tenant_id), image_hash, adapter, context_hash))

    async def insert_or_get_existing(self, record):
        key = (str(record.tenant_id), record.image_hash, record.adapter, record.context_hash)
        if key in self._rows:
            return self._rows[key], False
        self._rows[key] = record
        return record, True


def _describe(svc, *, context, confirmed_faces=(), naming_policy=None, media_id=7):
    async def body():
        return await svc.describe(
            tenant_id=TENANT,
            media_id=media_id,
            image_bytes=b"\x89PNG fusion-prov",
            context=context,
            confirmed_faces=list(confirmed_faces),
            naming_policy=naming_policy,
        )

    return asyncio.run(body())


def _maria_face():
    return make_face(
        "Slate Willow",
        box=FACE_BOX,
        cluster_id="cluster-maria",
        identity_id="identity-maria",
        roster_id="roster-maria",
    )


def test_async_tier_runs_single_inference_no_isolation_pass():
    """EH-02: async tiers must NOT run a second (discarded) inference.

    reconcile reads only the main-pass caption, so the removed Stage-1 isolation
    pass could never change the outcome. Assert exactly one adapter call even on
    an async tier with context facts, and that identity still object-attaches.
    """
    from scene.config.profiles import DescriptionProfile

    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)
    adapter = _TierAdapter(
        main_caption=CAPTION,
        isolation_caption="Totally different isolation caption text.",
        phrase_boxes=[phrase],
    )
    svc = VisualFactsService(adapter=adapter, repository=None, profile=DescriptionProfile.FLORENCE_LARGE)
    response = _describe(
        svc,
        context=_identity_pack().model_dump(exclude_none=True),
        confirmed_faces=[_maria_face()],
        naming_policy=NamingPolicy(agreement_enabled=True),
    )
    assert adapter.calls == 1  # EH-02: single inference; no discarded isolation pass
    facts = {f.fact_id: f for f in response.attachment_provenance.facts}
    identity = facts["identity:cluster:cluster-maria"]
    assert identity.decision == "object"
    assert identity.review_reason is None
    assert identity.target_evidence == "person"


def test_zero_context_facts_yield_no_provenance():
    """No ContextPack (or a pack yielding zero facts) → empty provenance, one inference."""
    from scene.config.profiles import DescriptionProfile

    adapter = _TierAdapter(main_caption=CAPTION, isolation_caption="unused")
    svc = VisualFactsService(adapter=adapter, repository=None, profile=DescriptionProfile.FLORENCE_LARGE)
    response = _describe(svc, context=None)
    assert adapter.calls == 1
    assert response.attachment_provenance.facts == []

    adapter2 = _TierAdapter(main_caption=CAPTION, isolation_caption="unused")
    svc2 = VisualFactsService(adapter=adapter2, repository=None, profile=DescriptionProfile.FLORENCE_LARGE)
    response2 = _describe(svc2, context=ContextPack().model_dump(exclude_none=True))
    assert adapter2.calls == 1
    assert response2.attachment_provenance.facts == []


def test_fusion_stage_exception_fails_open(monkeypatch):
    """S3A-02: a fusion exception degrades to attachment_provenance=None — the
    successful generation is still returned, never a 500."""
    from scene.application import visual_facts_service as svc_module

    def boom(**kwargs):
        raise RuntimeError("reconcile exploded")

    monkeypatch.setattr(svc_module, "reconcile_context_facts", boom)
    adapter = _CaptionAdapter()
    svc = VisualFactsService(adapter=adapter, repository=None)
    response = _describe(
        svc,
        context=_identity_pack().model_dump(exclude_none=True),
        naming_policy=NamingPolicy(agreement_enabled=True),
    )
    assert response.attachment_provenance is None
    assert response.visual_facts.caption == CAPTION
    assert svc.last_attachments == ()


def test_cache_hit_carries_same_attachment_provenance():
    """S3A-03: a second identical request (cache hit) recomputes Stage-2 from the
    persisted row and returns the same attachment provenance, not null."""
    pack = _identity_pack()
    phrase = make_phrase_box("person", CAPTION, box=PERSON_BOX)
    repo = _FakeRepo()
    face = _maria_face()

    def run():
        svc = VisualFactsService(adapter=_CaptionAdapter(phrase_boxes=[phrase]), repository=repo)
        return svc, _describe(
            svc,
            context=pack.model_dump(exclude_none=True),
            confirmed_faces=[face],
            naming_policy=NamingPolicy(agreement_enabled=True),
        )

    _, first = run()
    svc2, second = run()
    assert first.cached is False
    assert second.cached is True
    assert first.attachment_provenance is not None
    assert second.attachment_provenance == first.attachment_provenance
    facts = {f.fact_id: f for f in second.attachment_provenance.facts}
    assert facts["identity:cluster:cluster-maria"].decision == "object"
    assert svc2.last_attachments  # cache hits keep Stage-2 decisions for Stage-3 consistency


def test_attachment_fact_provenance_model_extra_forbid():
    with pytest.raises(ValidationError):
        AttachmentFactProvenance.model_validate(
            {
                "fact_id": "x",
                "fact_source": "product",
                "fact_label": "x",
                "decision": "caption",
                "altitude": "caption",
                "unknown": True,
            }
        )
