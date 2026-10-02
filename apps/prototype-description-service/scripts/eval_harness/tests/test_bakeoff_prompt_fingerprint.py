"""Prompt fingerprint coverage for the bake-off user-message templates."""

import httpx
import pytest

from scripts.eval_harness.bakeoff import BakeoffClient


def _new_client() -> BakeoffClient:
    return BakeoffClient(
        base_url="http://candidate.test:8080",
        model_id="fingerprint-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )


@pytest.mark.parametrize(
    "helper_name",
    ("_user_text", "_pass1_user_text", "_weave_user_text", "_compress_user_text"),
)
def test_prompt_fingerprint_changes_when_user_message_template_changes(monkeypatch, helper_name: str) -> None:
    baseline = _new_client()
    try:
        initial_fingerprint = baseline.prompt_sha256
        original_helper = getattr(BakeoffClient, helper_name)

        def changed_helper(self, *args, **kwargs):
            return f"{original_helper(self, *args, **kwargs)}\nUpdated static instruction."

        monkeypatch.setattr(BakeoffClient, helper_name, changed_helper)
        changed = _new_client()
        try:
            assert changed.prompt_sha256 != initial_fingerprint
        finally:
            changed.close()
    finally:
        baseline.close()


def test_prompt_fingerprint_is_stable_for_identical_inputs() -> None:
    first = _new_client()
    second = _new_client()
    try:
        assert first.prompt_sha256 == second.prompt_sha256
        assert first._prompt_fingerprint() == first.prompt_sha256
    finally:
        first.close()
        second.close()
