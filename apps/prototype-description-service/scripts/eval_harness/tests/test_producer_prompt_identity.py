from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from scripts.eval_harness.cli import fetch_run_record
import scripts.eval_harness.fusion_runner as fusion_runner
from scripts.eval_harness.fusion_runner import (
    manifest_entries_as_dicts,
    run_fusion_eval,
)
from scripts.eval_harness.manifest import load_manifest
from scripts.eval_harness.report import build_reports
from scripts.eval_harness.tests.test_cli_exit_gates import _manifest_doc


_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_BAKEOFF_MANIFEST = _SERVICE_ROOT / "scene" / "tests" / "seed" / "bakeoff_golden.json"


class _LiveDescribeClient:
    base_url = "https://api.example.com"

    def __init__(
        self,
        *,
        include_prompt_or_task_version: bool = True,
        prompt_or_task_version: str | None = "service-prompt-v7",
    ) -> None:
        self.include_prompt_or_task_version = include_prompt_or_task_version
        self.prompt_or_task_version = prompt_or_task_version

    def describe(self, **_kwargs: Any) -> dict[str, Any]:
        # This mirrors VisualFactsResponse: the API exposes the prompt stamp as
        # prompt_or_task_version and has no prompt digest field.
        response = {
            "alt_text_draft": "Alice Example stands near a garden.",
            "visual_facts": {"objects": ["garden"]},
            "adapter": "seeded",
            "model_id": "seeded-fixtures",
            "model_version": "1",
            "cached": False,
        }
        if self.include_prompt_or_task_version:
            response["prompt_or_task_version"] = self.prompt_or_task_version
        return response

    def analyze(self, _items: list[tuple[int, str, bytes]]) -> str:
        return "job-1"

    def wait_job(self, _job_id: str) -> None:
        return None

    def media_identities(self, _media_ids: list[int]) -> list[dict[str, Any]]:
        return []


def _report_model(record: dict[str, Any], manifest: Any) -> dict[str, Any]:
    report, _markdown = build_reports(record, manifest_entries_as_dicts(manifest))
    return json.loads(report)["provenance"]["model"]


def test_live_producer_maps_service_prompt_version_into_attributed_report(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest_doc(mode="exhaustive", boxed=True)), encoding="utf-8")
    manifest = load_manifest(
        str(manifest_path),
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="test uses a synthetic image",
    )
    image_path = tmp_path / "mock_images" / "alice1.jpg"
    image_path.parent.mkdir()
    Image.new("RGB", (100, 100), color="white").save(image_path, format="JPEG")

    record = fetch_run_record(
        manifest,
        str(tmp_path),
        _LiveDescribeClient(),
        head_sha="1" * 40,
    )

    describe = record["items"][0]["describe"]
    assert "prompt_sha256" not in describe
    assert describe["prompt_or_task_version"] == "service-prompt-v7"
    assert describe["prompt_version"] == "service-prompt-v7"
    model = _report_model(record, manifest)
    assert model["prompt_versions"] == ["service-prompt-v7"]
    assert "attribution" not in model


@pytest.mark.parametrize(
    ("include_prompt_or_task_version", "prompt_or_task_version"),
    [(False, None), (True, None)],
    ids=["identity-absent", "identity-null"],
)
def test_live_producer_preserves_missing_prompt_identity_and_score_gate_refuses_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    include_prompt_or_task_version: bool,
    prompt_or_task_version: str | None,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest_doc(mode="exhaustive", boxed=True)), encoding="utf-8")
    manifest = load_manifest(
        str(manifest_path),
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="test uses a synthetic image",
    )
    image_path = tmp_path / "mock_images" / "alice1.jpg"
    image_path.parent.mkdir()
    Image.new("RGB", (100, 100), color="white").save(image_path, format="JPEG")

    record = fetch_run_record(
        manifest,
        str(tmp_path),
        _LiveDescribeClient(
            include_prompt_or_task_version=include_prompt_or_task_version,
            prompt_or_task_version=prompt_or_task_version,
        ),
        head_sha="1" * 40,
    )

    describe = record["items"][0]["describe"]
    assert ("prompt_or_task_version" in describe) is include_prompt_or_task_version
    if include_prompt_or_task_version:
        assert describe["prompt_or_task_version"] is None
    assert "prompt_version" not in describe
    assert record["provenance"].get("prompt_free") is not True
    model = _report_model(record, manifest)
    assert model["attribution"] == {
        "status": "unattributed",
        "missing_dimensions": ["prompt identity"],
    }

    record_path = tmp_path / "run-record.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    import scripts.eval_harness.cli as cli_mod

    monkeypatch.setattr(cli_mod, "OUT_DIR", tmp_path / "out")
    report_path = record_path.with_name("run-record-report.json")
    with pytest.raises(SystemExit) as exc:
        cli_mod.main(["score", "--manifest", str(manifest_path), "--run-record", str(record_path)])

    assert isinstance(exc.value.code, str)
    assert exc.value.code.startswith(cli_mod.SCORE_GATE_PREFIX_PRODUCER_IDENTITY)
    assert "missing dimensions: prompt identity" in exc.value.code
    published = json.loads(report_path.read_text(encoding="utf-8"))
    assert published["provenance"]["model"]["attribution"] == {
        "status": "unattributed",
        "missing_dimensions": ["prompt identity"],
    }


@pytest.mark.parametrize("mode", ["staged", "adhoc"])
def test_fusion_producer_stamps_prompt_version_into_attributed_report(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def describe_stub(_service: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            alt_text_draft="A person stands by the garden.",
            visual_facts=SimpleNamespace(
                caption="A person stands by the garden.",
                objects=("person", "garden"),
            ),
            adapter="seeded",
            model_id="fusion-eval-stub",
            model_version="1",
            prompt_or_task_version="e20-fusion-slice4",
            cached=False,
            attachment_provenance=None,
        )

    monkeypatch.setattr(fusion_runner.VisualFactsService, "describe", describe_stub)
    manifest = load_manifest(
        str(_BAKEOFF_MANIFEST),
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="fusion records use synthetic image bytes",
    )
    manifest = manifest.model_copy(update={"entries": manifest.entries[:1]})
    record = run_fusion_eval(manifest, mode=mode, head_sha="1" * 40, limit=1)

    describe = record["items"][0]["describe"]
    assert record["items"][0].get("error") is None
    assert describe["prompt_version"] == "e20-fusion-slice4"
    model = _report_model(record, manifest)
    assert model["prompt_versions"] == ["e20-fusion-slice4"]
    assert "attribution" not in model


@pytest.mark.parametrize("mode", ["staged", "adhoc"])
def test_fusion_producer_empty_prompt_version_is_unattributed(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def describe_stub(_service: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            alt_text_draft="A person stands by the garden.",
            visual_facts=SimpleNamespace(
                caption="A person stands by the garden.",
                objects=("person", "garden"),
            ),
            adapter="seeded",
            model_id="fusion-eval-stub",
            model_version="1",
            # VisualFactsResponse requires str (responses.py:236) but does not
            # reject an empty string, so this is the missing-identity case the
            # fusion producer can actually emit.
            prompt_or_task_version="",
            cached=False,
            attachment_provenance=None,
        )

    monkeypatch.setattr(fusion_runner.VisualFactsService, "describe", describe_stub)
    manifest = load_manifest(
        str(_BAKEOFF_MANIFEST),
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="fusion records use synthetic image bytes",
    )
    manifest = manifest.model_copy(update={"entries": manifest.entries[:1]})
    record = run_fusion_eval(manifest, mode=mode, head_sha="1" * 40, limit=1)

    describe = record["items"][0]["describe"]
    assert record["items"][0].get("error") is None
    assert describe["prompt_version"] == ""
    model = _report_model(record, manifest)
    assert model["attribution"] == {
        "status": "unattributed",
        "missing_dimensions": ["prompt identity"],
    }
