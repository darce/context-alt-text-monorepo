from __future__ import annotations

import pytest

from recognition.infrastructure import embeddings


class _FakeAdapter:
    init_calls = 0
    load_calls = 0

    def __init__(self) -> None:
        type(self).init_calls += 1

    async def ensure_loaded(self) -> None:
        type(self).load_calls += 1


@pytest.mark.asyncio
async def test_get_shared_insightface_adapter_reuses_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embeddings, "InsightFaceAdapter", _FakeAdapter)
    embeddings.reset_shared_insightface_adapter_for_tests()
    _FakeAdapter.init_calls = 0
    _FakeAdapter.load_calls = 0

    first = await embeddings.get_shared_insightface_adapter()
    second = await embeddings.get_shared_insightface_adapter()

    assert first is second
    assert _FakeAdapter.init_calls == 1
    assert _FakeAdapter.load_calls == 1

    embeddings.reset_shared_insightface_adapter_for_tests()
