"""ALTQ-1 Slice 2: prompt-variant registry, two-pass describe-then-ground,
long-first dual-length generation, and harness-side face-gated naming.

All transport tests stub the candidate llama.cpp endpoint (httpx.MockTransport,
no network) using the same OpenAI chat-completions payload shape as the live
endpoint and the Slice-1 tests. Score-side tests prove every new run-record
field is additive: an old-shape record scores byte-identically.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from scripts.eval_harness.bakeoff import (
    DEFAULT_PROMPT_VARIANT,
    PROMPT_VARIANTS,
    BakeoffClient,
    PassOneJSONError,
    _apply_face_gate,
    _parse_pass1_json,
    _stamp_pipeline_provenance,
    main,
)
from scripts.eval_harness.cli import fetch_run_record
from scripts.eval_harness.manifest import GoldenManifest
from scripts.eval_harness.report import build_reports, score_run_record

_FACTS_JSON = json.dumps(
    {
        "people": [{"position": "left", "appearance": "woman in a red jacket"}],
        "setting": "rocky shoreline",
        "action": "standing at the waterline",
        "legible_text": [],
        "atmosphere": "overcast",
    }
)


def _sequenced_transport(captured: list[dict], responses: list[object]) -> httpx.MockTransport:
    """Each call consumes the next response spec: str -> chat content, int -> HTTP status."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append({"path": request.url.path, "payload": payload})
        spec = responses[len(captured) - 1] if len(captured) <= len(responses) else responses[-1]
        if isinstance(spec, int):
            return httpx.Response(spec, json={"error": "boom"})
        return httpx.Response(200, json={"choices": [{"message": {"content": spec}}]})

    return httpx.MockTransport(handler)


def _client(captured: list[dict], responses: list[object], **kwargs) -> BakeoffClient:
    return BakeoffClient(
        base_url="http://candidate.test:8080",
        model_id="qwen3-vl-30b",
        transport=_sequenced_transport(captured, responses),
        **kwargs,
    )


def _describe(client: BakeoffClient, context_pack: dict) -> dict:
    return client.describe(
        image_bytes=b"\x89PNG fake bytes",
        filename="img.jpg",
        media_id=7,
        context_pack=context_pack,
    )


def _system_text(payload: dict) -> str:
    return payload["messages"][0]["content"]


def _user_text(payload: dict) -> str:
    content = payload["messages"][1]["content"]
    if isinstance(content, str):
        return content
    return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")


def _has_image_part(payload: dict) -> bool:
    content = payload["messages"][1]["content"]
    return isinstance(content, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in content)


# --- Deliverable 1: prompt v2 + variant registry + --prompt-variant ----------


def test_prompt_variant_registry_has_v1_and_v2_default_v1() -> None:
    assert set(PROMPT_VARIANTS) >= {"v1", "v2"}
    assert DEFAULT_PROMPT_VARIANT == "v1"
    for name, variant in PROMPT_VARIANTS.items():
        assert variant.name == name
        assert variant.system and variant.system_long


def test_v1_variant_is_the_unchanged_baseline_prompt() -> None:
    v1 = PROMPT_VARIANTS["v1"]
    assert "2-4 plain sentences" in v1.system
    assert "Never name or guess" in v1.system
    assert "<<<CONTEXT>>>" in v1.system
    # long-first counterpart differs only in the sentence band
    assert v1.system_long == v1.system.replace("2-4 plain sentences", "4-8 plain sentences")


def test_v2_variant_encodes_findings_style_rules() -> None:
    v2 = PROMPT_VARIANTS["v2"].system
    assert "Front-load" in v2  # findings §3: subject + action first
    assert "'photo of'" in v2 and "'image of'" in v2  # no artifact prefix
    assert "overview" in v2  # general -> specific
    assert "emotion" in v2.lower()  # emotion/atmosphere legitimate
    # never-guess contract preserved verbatim intent (may only tighten)
    assert "Never name or guess about anyone the context does not name." in v2
    assert "describe what the image shows" in v2  # pixels win
    assert "restating" in v2  # complement, don't duplicate
    assert "4-8" in PROMPT_VARIANTS["v2"].system_long


def test_unknown_prompt_variant_rejected_at_construction() -> None:  # rg-008 fail-fast
    with pytest.raises(ValueError, match="prompt_variant"):
        _client([], ["x"], prompt_variant="v99")


def test_selected_variant_reaches_system_message() -> None:
    captured: list[dict] = []
    _describe(_client(captured, ["A caption."], prompt_variant="v2"), {})
    assert _system_text(captured[0]["payload"]) == PROMPT_VARIANTS["v2"].system

    captured.clear()
    _describe(_client(captured, ["A caption."]), {})
    assert _system_text(captured[0]["payload"]) == PROMPT_VARIANTS["v1"].system


def test_describe_stamps_prompt_variant() -> None:
    captured: list[dict] = []
    describe = _describe(_client(captured, ["A caption."], prompt_variant="v2"), {})
    assert describe["prompt_variant"] == "v2"


def test_cli_rejects_unknown_prompt_variant() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--endpoint", "http://x", "--model-id", "m", "--prompt-variant", "bogus"])
    assert excinfo.value.code == 2  # argparse choices rejection, before any env gate


def test_provenance_stamp_records_variant_and_enabled_pipeline_flags() -> None:
    provenance: dict = {}
    _stamp_pipeline_provenance(
        provenance, prompt_variant="v2", two_pass=True, dual_length=False, face_gate=True, eval_mode="standard"
    )
    assert provenance == {"prompt_variant": "v2", "two_pass": True, "face_gate": True}

    provenance = {}
    _stamp_pipeline_provenance(
        provenance,
        prompt_variant="v1",
        two_pass=False,
        dual_length=True,
        face_gate=False,
        eval_mode="context_distractor",
    )
    assert provenance == {"prompt_variant": "v1", "dual_length": True, "eval_mode": "context_distractor"}


# --- Deliverable 2: two-pass describe-then-ground -----------------------------


def test_two_pass_pass1_sees_no_context_and_asks_objective_json() -> None:
    captured: list[dict] = []
    client = _client(captured, [_FACTS_JSON, "Caitlin Weaver stands at the waterline."], two_pass=True)
    _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    assert len(captured) == 2
    pass1 = captured[0]["payload"]
    assert _has_image_part(pass1)
    assert "Caitlin Weaver" not in json.dumps(pass1), "pass-1 must be context-free (describe-first)"
    assert "JSON object" in _system_text(pass1)
    assert "Do not name anyone" in _system_text(pass1)


def test_two_pass_pass2_carries_facts_context_and_mismatch_fewshot() -> None:
    captured: list[dict] = []
    client = _client(captured, [_FACTS_JSON, "Caitlin Weaver stands at the waterline."], two_pass=True)
    _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    pass2 = captured[1]["payload"]
    assert _has_image_part(pass2)
    user = _user_text(pass2)
    assert "<<<FACTS>>>" in user and "<<<END_FACTS>>>" in user
    assert "rocky shoreline" in user  # committed pass-1 facts reach the weave
    assert "Caitlin Weaver" in user  # context reaches the weave
    assert "<<<CONTEXT>>>" in user
    system = _system_text(pass2)
    assert "Maria Chen" in system, "mismatch few-shot exemplar missing from weave prompt (findings §2.4)"
    assert "leave that name out" in system


def test_two_pass_final_caption_is_pass2_output() -> None:
    captured: list[dict] = []
    client = _client(captured, [_FACTS_JSON, "Caitlin Weaver stands at the waterline."], two_pass=True)
    describe = _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    assert describe["alt_text_draft"] == "Caitlin Weaver stands at the waterline."


def test_two_pass_records_per_pass_raw_and_latency() -> None:
    captured: list[dict] = []
    client = _client(captured, [_FACTS_JSON, "Caitlin Weaver stands at the waterline."], two_pass=True)
    describe = _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    passes = describe["passes"]
    assert [p["pass"] for p in passes] == ["describe_facts", "ground_weave"]
    assert passes[0]["raw"] == _FACTS_JSON
    assert passes[1]["raw"] == "Caitlin Weaver stands at the waterline."
    assert all(isinstance(p["latency_s"], float) and p["latency_s"] >= 0 for p in passes)


def test_two_pass_malformed_pass1_json_is_typed_per_item_failure_and_run_continues(tmp_path: Path) -> None:
    """[AGT-10] degrade loudly: malformed pass-1 JSON fails ONE item, not the run (rg-007)."""
    entries = []
    for i, name in enumerate(["img0.jpg", "img1.jpg"]):
        (tmp_path / name).write_bytes(b"fake image bytes")
        entries.append(
            {
                "path": name,
                "sha256": f"{i}" * 64,
                "media_id": 100 + i,
                "face_count": 0,
                "present_identities": [],
                "context_pack": {"caption": "x"},
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
            }
        )
    manifest = GoldenManifest.model_validate({"manifest_version": 2, "roster": [], "entries": entries})
    captured: list[dict] = []
    # item 0: pass-1 malformed; item 1: valid facts then a caption.
    client = _client(captured, ["not json at all", _FACTS_JSON, "A quiet shoreline."], two_pass=True)
    try:
        record = fetch_run_record(manifest, str(tmp_path), client, head_sha="deadbeef")
    finally:
        client.close()
    assert record["items"][0]["describe"] is None
    assert "PassOneJSONError" in record["items"][0]["error"]
    assert record["items"][1]["describe"]["alt_text_draft"] == "A quiet shoreline."


def test_parse_pass1_json_accepts_fenced_json() -> None:
    parsed = _parse_pass1_json(f"```json\n{_FACTS_JSON}\n```")
    assert parsed["setting"] == "rocky shoreline"


def test_parse_pass1_json_rejects_non_object() -> None:
    with pytest.raises(PassOneJSONError, match="expected an object"):
        _parse_pass1_json("[1, 2, 3]")
    with pytest.raises(PassOneJSONError, match="malformed"):
        _parse_pass1_json("Sure! Here is the description you asked for.")


# --- Deliverable 3: long-first generation + text-only compression -------------

_LONG_TEXT = (
    "Caitlin Weaver stands at the waterline of a rocky shoreline in a red jacket. "
    "The sky is overcast and the water is calm. She looks toward the horizon."
)
_SHORT_TEXT = "Caitlin Weaver stands at a rocky shoreline in a red jacket."


def test_dual_length_long_generated_first_then_text_only_compression() -> None:
    captured: list[dict] = []
    client = _client(captured, [_LONG_TEXT, _SHORT_TEXT], dual_length=True)
    describe = _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    assert len(captured) == 2
    # generation call asks for the long surface and carries the image
    assert _has_image_part(captured[0]["payload"])
    assert "4-8" in _system_text(captured[0]["payload"])
    # compression call is text-only (no image part) and carries the committed long
    compress = captured[1]["payload"]
    assert not _has_image_part(compress)
    assert _LONG_TEXT in _user_text(compress)
    assert "125" in _system_text(compress)
    assert describe["alt_text_long"] == _LONG_TEXT
    assert describe["alt_text_draft"] == _SHORT_TEXT


def test_dual_length_records_compress_pass_timing() -> None:
    captured: list[dict] = []
    client = _client(captured, [_LONG_TEXT, _SHORT_TEXT], dual_length=True)
    describe = _describe(client, {})
    assert [p["pass"] for p in describe["passes"]] == ["caption", "compress_short"]


def test_dual_length_compression_failure_keeps_long_and_marks_short() -> None:
    """[AGT-10] degrade loudly: compression 500 keeps the long surface + a typed short_error stamp."""
    captured: list[dict] = []
    client = _client(captured, [_LONG_TEXT, 500], dual_length=True)
    describe = _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    assert describe["alt_text_long"] == _LONG_TEXT
    assert "alt_text_draft" not in describe
    assert describe["short_error"].startswith("RemoteClientError:")
    failed_pass = describe["passes"][-1]
    assert failed_pass["pass"] == "compress_short" and failed_pass["raw"] is None


def test_two_pass_plus_dual_length_compose_three_passes() -> None:
    captured: list[dict] = []
    client = _client(captured, [_FACTS_JSON, _LONG_TEXT, _SHORT_TEXT], two_pass=True, dual_length=True)
    describe = _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    assert [p["pass"] for p in describe["passes"]] == ["describe_facts", "ground_weave", "compress_short"]
    # the weave (pass 2) generates the LONG surface when dual-length is on
    assert "4-8" in _system_text(captured[1]["payload"])
    assert describe["alt_text_long"] == _LONG_TEXT
    assert describe["alt_text_draft"] == _SHORT_TEXT


# --- Deliverable 4: face-gated naming (harness-side simulation) ---------------

_FACE_BOXES = [
    # real FaceBox shape (manifest.py): normalized centre x/y + w/h, name, source
    {"x": 0.2, "y": 0.4, "w": 0.1, "h": 0.15, "name": "Caitlin Weaver", "source": "iptc"},
    {"x": 0.8, "y": 0.4, "w": 0.1, "h": 0.15, "name": None, "source": "mwg"},  # anonymous stranger
]
_ROSTER = ["Caitlin Weaver", "Erika Hansen Miller", "Bob Builder"]


def _gate_client(captured: list[dict], responses: list[object], fixtures: dict, **kwargs) -> BakeoffClient:
    return _client(captured, responses, face_gate=True, face_fixtures=fixtures, roster=_ROSTER, **kwargs)


def test_face_gate_requires_fixtures_and_known_names() -> None:  # rg-008 fail-fast
    with pytest.raises(ValueError, match="face_fixtures"):
        _client([], ["x"], face_gate=True, roster=_ROSTER)
    with pytest.raises(ValueError, match="roster"):
        _client([], ["x"], face_gate=True, face_fixtures={7: _FACE_BOXES})


def test_face_gate_suppresses_context_names_without_face_match() -> None:
    captured: list[dict] = []
    client = _gate_client(captured, ["A caption."], {7: _FACE_BOXES})
    describe = _describe(
        client,
        {"caption": "Caitlin Weaver on the peninsula.", "description": "Erika Hansen Miller took the photo."},
    )
    prompt = json.dumps(captured[0]["payload"])
    assert "Caitlin Weaver" in prompt  # face-confirmed: eligible
    assert "Erika Hansen Miller" not in prompt, "name without a face match must never reach the prompt"
    assert describe["face_gate"] == {
        "eligible_names": ["Caitlin Weaver"],
        "suppressed_names": ["Erika Hansen Miller"],
    }


def test_face_gate_fails_closed_with_no_face_matches() -> None:
    captured: list[dict] = []
    # no boxes for this media_id at all -> nothing eligible
    client = _gate_client(captured, ["A caption."], {})
    describe = _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    assert "Caitlin Weaver" not in json.dumps(captured[0]["payload"])
    assert describe["face_gate"]["eligible_names"] == []
    assert describe["face_gate"]["suppressed_names"] == ["Caitlin Weaver"]

    captured.clear()
    # anonymous-only boxes (name=None) are NOT matches -> still fail closed
    client = _gate_client(captured, ["A caption."], {7: [_FACE_BOXES[1]]})
    describe = _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    assert "Caitlin Weaver" not in json.dumps(captured[0]["payload"])
    assert describe["face_gate"]["eligible_names"] == []


def test_face_gate_adds_positional_binding_for_eligible_names() -> None:
    captured: list[dict] = []
    boxes = [
        {"x": 0.15, "y": 0.4, "w": 0.1, "h": 0.15, "name": "Caitlin Weaver", "source": "iptc"},
        {"x": 0.85, "y": 0.4, "w": 0.1, "h": 0.15, "name": "Bob Builder", "source": "iptc"},
    ]
    client = _gate_client(captured, ["A caption."], {7: boxes})
    _describe(client, {"caption": "Caitlin Weaver and Bob Builder at the shoreline."})
    user = _user_text(captured[0]["payload"])
    assert "Caitlin Weaver, on the left" in user
    assert "Bob Builder, on the right" in user


def test_face_gate_never_adds_names_absent_from_context() -> None:
    """Conservative by construction: eligible = context ∩ face-matched — a face match
    alone (Bob Builder) must not inject a name the context never supplied."""
    captured: list[dict] = []
    boxes = [
        {"x": 0.2, "y": 0.4, "w": 0.1, "h": 0.15, "name": "Caitlin Weaver", "source": "iptc"},
        {"x": 0.8, "y": 0.4, "w": 0.1, "h": 0.15, "name": "Bob Builder", "source": "iptc"},
    ]
    client = _gate_client(captured, ["A caption."], {7: boxes})
    describe = _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    assert "Bob Builder" not in json.dumps(captured[0]["payload"])
    assert describe["face_gate"]["eligible_names"] == ["Caitlin Weaver"]


def test_face_gate_composes_with_name_ablation_without_reintroducing_names() -> None:
    """never-guess may only tighten: ablation strips names first, so the gate must
    find nothing in context and add no people_present line."""
    captured: list[dict] = []
    client = _gate_client(
        captured,
        ["A caption."],
        {7: _FACE_BOXES},
        eval_mode="name_ablation",
        entry_traits={7: {"present": ["Caitlin Weaver"], "easy_wrong": []}},
    )
    describe = _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    prompt = json.dumps(captured[0]["payload"])
    assert "Caitlin Weaver" not in prompt
    assert "people_present" not in prompt
    assert describe["face_gate"]["eligible_names"] == []


def test_apply_face_gate_is_pure_and_deterministic() -> None:
    pack = {"caption": "Caitlin Weaver on the peninsula.", "description": "Erika Hansen Miller took the photo."}
    first = _apply_face_gate(pack, _FACE_BOXES, _ROSTER)
    second = _apply_face_gate(pack, _FACE_BOXES, _ROSTER)
    assert first == second
    assert pack["caption"] == "Caitlin Weaver on the peninsula."  # input never mutated


# --- Score side: additive fields, old records unchanged -----------------------


def _old_shape_record() -> dict:
    """Pre-Slice-2 run record: no prompt_variant, no passes, no short_error."""
    return {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "https://api.example.com",
            "head_sha": "0" * 40,
            "started_at": "2026-07-06T00:00:00Z",
        },
        "items": [
            {
                "media_id": 1,
                "path": "mock_images/alice-pool.jpg",
                "describe": {
                    "alt_text_draft": "Alice Example relaxes by a pool.",
                    "adapter": "bakeoff",
                    "model_id": "qwen3-vl-30b",
                    "model_version": None,
                },
                "identities": [],
                "face_count": 0,
                "error": None,
            }
        ],
    }


def _entries() -> list[dict]:
    return [
        {
            "path": "mock_images/alice-pool.jpg",
            "media_id": 1,
            "face_count": 1,
            "present_identities": ["Alice Example"],
            "context_pack": {"caption": "Alice Example by the pool."},
            "must_right": ["Alice Example"],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
        }
    ]


def test_old_run_record_scores_unchanged_without_slice2_keys() -> None:
    """Additive-schema proof: an old-shape record produces no Slice-2 report keys."""
    scored = score_run_record(_old_shape_record(), _entries())
    assert scored["counts"] == {"total": 1, "scored": 1, "failed": 0}
    assert scored["caption"]["insertion_rate"] == 1.0
    assert "short_failed_images" not in scored["caption"]
    assert all("short_error" not in row for row in scored["per_image"])
    json_a, md_a = build_reports(_old_shape_record(), _entries())
    json_b, md_b = build_reports(_old_shape_record(), _entries())
    assert (json_a, md_a) == (json_b, md_b)  # bit-identical re-score preserved
    assert "prompt variant" not in md_a


def test_short_error_item_scores_long_surface_only() -> None:
    record = _old_shape_record()
    record["items"][0]["describe"] = {
        "alt_text_long": "Alice Example relaxes by a sunlit pool. She wears a wide hat.",
        "short_error": "RemoteClientError: POST /v1/chat/completions failed: 500",
        "adapter": "bakeoff",
        "model_id": "qwen3-vl-30b",
        "model_version": None,
        "prompt_variant": "v2",
    }
    scored = score_run_record(record, _entries())
    assert scored["counts"]["scored"] == 1  # long surface kept and scored
    row = scored["per_image"][0]
    assert row["short_error"].startswith("RemoteClientError:")
    assert row["gated_score"] is None and row["sentence_count"] is None
    assert row["long"]["inserted_identities"] == ["Alice Example"]
    assert scored["caption"]["short_failed_images"] == 1
    assert scored["caption_long"]["images_with_long"] == 1
    # short-surface corpus metrics exclude the failed short instead of charging it
    assert scored["caption"]["insertion_rate"] is None
    _json_doc, md = build_reports(record, _entries())
    assert "short-surface compression failed" in md


def test_prompt_variant_provenance_renders_in_markdown() -> None:
    record = _old_shape_record()
    record["provenance"]["prompt_variant"] = "v2"
    record["provenance"]["two_pass"] = True
    record["provenance"]["face_gate"] = True
    json_doc, md = build_reports(record, _entries())
    assert "prompt variant: `v2`" in md
    assert "two_pass" in md and "face_gate" in md
    assert json.loads(json_doc)["provenance"]["prompt_variant"] == "v2"


def test_new_shape_record_rescore_bit_identical() -> None:
    record = _old_shape_record()
    record["provenance"]["prompt_variant"] = "v1"
    record["items"][0]["describe"]["passes"] = [{"pass": "caption", "raw": "x", "latency_s": 0.5}]
    a = build_reports(record, _entries())
    b = build_reports(record, _entries())
    assert a == b
