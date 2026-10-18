"""S2: deterministic seeded DescriptionAdapter behind the runtime_checkable protocol."""

from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.domain.description import DescriptionAdapterKind

IMG = b"\x89PNG\r\n seeded test image bytes"


def test_conforms_to_protocol():
    assert isinstance(SeededDescriptionAdapter(), DescriptionAdapter)


def test_identity_properties():
    a = SeededDescriptionAdapter()
    assert a.kind is DescriptionAdapterKind.SEEDED
    assert a.model_id and a.model_version and a.prompt_or_task_version


def test_deterministic_for_same_inputs():
    a = SeededDescriptionAdapter()
    ctx = {"title": "Cat", "caption": "x"}
    r1 = a.describe(image_bytes=IMG, context=ctx)
    r2 = a.describe(image_bytes=IMG, context=ctx)
    assert r1 == r2
    assert isinstance(r1, AdapterResult)
    assert r1.caption and r1.alt_text_draft


def test_context_key_order_insensitive():
    a = SeededDescriptionAdapter()
    r1 = a.describe(image_bytes=IMG, context={"title": "Cat", "caption": "x"})
    r2 = a.describe(image_bytes=IMG, context={"caption": "x", "title": "Cat"})
    assert r1 == r2


def test_context_used_empty_but_typed():
    r = SeededDescriptionAdapter().describe(image_bytes=IMG, context={"title": "Cat"})
    assert r.context_sources == ()
    assert r.context_applied is False


def test_prompt_version_bump_changes_output():
    # Deterministic (sha256-seeded), not flaky: a fixed set of versions over the pool.
    captions = {
        SeededDescriptionAdapter(prompt_or_task_version=str(v)).describe(image_bytes=IMG, context=None).caption
        for v in range(1, 9)
    }
    assert len(captions) > 1


def test_different_images_generally_differ():
    a = SeededDescriptionAdapter()
    out = {a.describe(image_bytes=bytes([i]) * 32, context=None).caption for i in range(8)}
    assert len(out) > 1
