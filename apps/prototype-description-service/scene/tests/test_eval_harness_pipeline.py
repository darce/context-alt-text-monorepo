"""ALTQ-1 Slice 2: prompt-variant registry, two-pass describe-then-ground,
long-first dual-length generation, and harness-side face-gated naming.

All transport tests stub the candidate llama.cpp endpoint (httpx.MockTransport,
no network) using the same OpenAI chat-completions payload shape as the live
endpoint and the Slice-1 tests. Score-side tests prove every new run-record
field is additive: an old-shape record scores byte-identically.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from scripts.eval_harness.bakeoff import (
    _CAPTION_MAX_TOKENS,
    _PASS1_MAX_TOKENS,
    DEFAULT_PROMPT_VARIANT,
    PROMPT_VARIANTS,
    BakeoffClient,
    PassOneJSONError,
    ThreeSurfaceParseError,
    WeaveBenchRecordError,
    WeaveBenchSourceError,
    _apply_face_gate,
    _load_weave_bench_source,
    _parse_pass1_json,
    _parse_three_surface_json,
    _stamp_pipeline_provenance,
    main,
    weave_bench_run_record,
)
from scripts.eval_harness.cli import BoundedStallError, fetch_run_record
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


def test_two_pass_pass1_gets_larger_token_budget_than_the_caption() -> None:
    # regression: pass-1 emits a full facts JSON (legible_text) that truncated at
    # the caption budget on text-dense images -> PassOneJSONError (646-run: 5 lost).
    assert _PASS1_MAX_TOKENS > _CAPTION_MAX_TOKENS
    captured: list[dict] = []
    client = _client(captured, [_FACTS_JSON, "Caitlin Weaver stands at the waterline."], two_pass=True)
    _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    assert captured[0]["payload"]["max_tokens"] == _PASS1_MAX_TOKENS  # describe_facts
    assert captured[1]["payload"]["max_tokens"] == _CAPTION_MAX_TOKENS  # ground_weave


def test_single_pass_caption_keeps_the_caption_token_budget() -> None:
    captured: list[dict] = []
    _describe(_client(captured, ["A plain caption."]), {})
    assert captured[0]["payload"]["max_tokens"] == _CAPTION_MAX_TOKENS


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
                "provenance": {"source": "fixture", "license": "fixture"},
            }
        )
    manifest = GoldenManifest.model_validate({"manifest_version": 3,
            "annotation_mode": "roster_only", "roster": [], "entries": entries})
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


def test_apply_face_gate_keys_on_normalized_name_not_raw_str() -> None:
    """Padded GT box name must still intersect roster form (wE4 residual / wF2).

    Pre-fix: matched keyed by raw ``str(name)`` so ``\" Alice \"`` never
    intersected roster ``\"Alice\"`` — gate silently under-counted eligible.
    """
    pack = {
        "caption": "Alice is on the left.",
        "people_present": "Alice",
        "description": "Alice stands near the water.",
    }
    face_boxes = [
        {"x": 0.2, "y": 0.4, "w": 0.1, "h": 0.15, "name": " Alice ", "source": "iptc"},
    ]
    roster = ["Alice", "Bob Builder"]
    out_pack, stamp = _apply_face_gate(pack, face_boxes, roster)
    assert stamp["eligible_names"] == ["Alice"], (
        f"padded face-box name must match roster Alice; got stamp={stamp!r}"
    )
    assert stamp["suppressed_names"] == []
    assert out_pack["people_present"].startswith("Alice,")


def test_apply_face_gate_keys_bom_zwsp_name_to_roster() -> None:
    """BOM/ZWSP-prefixed box names normalize to roster form under named_box_name."""
    pack = {"caption": "Alice waves.", "people_present": "Alice"}
    face_boxes = [
        {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1, "name": "\ufeffAlice", "source": "iptc"},
    ]
    _out, stamp = _apply_face_gate(pack, face_boxes, ["Alice"])
    assert stamp["eligible_names"] == ["Alice"], stamp


def test_apply_face_gate_detects_roster_normalization_collision() -> None:
    """Normalizing both sides must not silently merge distinct roster strings.

    If ``\"Alice\"`` and ``\"Alice \"`` both appear on the roster they collapse to
    one key after namedness normalization — fail closed with ValueError rather
    than change identity counts by merge (wave F fail-closed posture).
    """
    pack = {"caption": "Alice is here.", "people_present": "Alice"}
    face_boxes = [
        {"x": 0.2, "y": 0.4, "w": 0.1, "h": 0.15, "name": "Alice", "source": "iptc"},
    ]
    colliding_roster = ["Alice", "Alice "]
    with pytest.raises(ValueError, match="collision|normalize"):
        _apply_face_gate(pack, face_boxes, colliding_roster)


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


# --- ALTQ-1 Slice 3: --weave-bench replay (pass-2 text-only, no image) ---------

_WEAVE_CAPTION = "Caitlin Weaver stands at the waterline."


def _weave_source_item(media_id: int, path: str, facts: str = _FACTS_JSON) -> dict:
    """One item of a --two-pass GPU run record: passes[0] carries the pass-1 facts."""
    return {
        "media_id": media_id,
        "path": path,
        "describe": {
            "adapter": "bakeoff",
            "model_id": "qwen3-vl-30b",
            "model_version": None,
            "prompt_variant": "v2",
            "alt_text_draft": _WEAVE_CAPTION,
            "passes": [
                {"pass": "describe_facts", "raw": facts, "latency_s": 8.1},
                {"pass": "ground_weave", "raw": _WEAVE_CAPTION, "latency_s": 11.2},
            ],
        },
        "identities": [],
        "face_count": 0,
        "error": None,
        "latency_s": 19.3,
    }


def _weave_source_record(items: list[dict]) -> dict:
    return {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "f" * 64,
            "base_url": "http://gpu.test:8080",
            "head_sha": "a" * 40,
            "started_at": "2026-07-16T00:00:00Z",
            "prompt_variant": "v2",
            "two_pass": True,
        },
        "items": items,
    }


def _weave_manifest(media_ids: list[int]) -> GoldenManifest:
    entries = []
    for i, media_id in enumerate(media_ids):
        entries.append(
            {
                "path": f"img{i}.jpg",
                "sha256": f"{i}" * 64,
                "media_id": media_id,
                "face_count": 0,
                "present_identities": [],
                "context_pack": {"caption": "Caitlin Weaver on the peninsula."},
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "fixture", "license": "fixture"},
            }
        )
    return GoldenManifest.model_validate({"manifest_version": 3,
            "annotation_mode": "roster_only", "roster": ["Caitlin Weaver"], "entries": entries})


def test_weave_bench_messages_match_live_pass2_without_image() -> None:
    """The replay weave message is byte-identical to live pass-2 minus ONLY the image part."""
    pack = {"caption": "Caitlin Weaver on the peninsula."}
    captured_live: list[dict] = []
    live = _client(captured_live, [_FACTS_JSON, _WEAVE_CAPTION], two_pass=True, prompt_variant="v2")
    _describe(live, dict(pack))
    live_pass2 = captured_live[1]["payload"]

    captured_bench: list[dict] = []
    bench = _client(captured_bench, [_WEAVE_CAPTION], prompt_variant="v2")
    bench.weave_bench_describe(media_id=7, facts_raw=_FACTS_JSON, context_pack=dict(pack))
    bench_payload = captured_bench[0]["payload"]

    assert _system_text(bench_payload) == _system_text(live_pass2)  # variant system + weave few-shot
    assert _user_text(bench_payload) == _user_text(live_pass2)  # same fenced facts + context
    assert "Maria Chen" in _system_text(bench_payload)  # mismatch few-shot present
    assert _has_image_part(live_pass2)
    assert not _has_image_part(bench_payload), "weave-bench must never send an image part"


def test_weave_bench_describe_returns_scoreable_single_pass_shape() -> None:
    captured: list[dict] = []
    client = _client(captured, [_WEAVE_CAPTION], prompt_variant="v2")
    describe = client.weave_bench_describe(media_id=7, facts_raw=_FACTS_JSON, context_pack={"caption": "x"})
    assert describe["alt_text_draft"] == _WEAVE_CAPTION
    assert describe["adapter"] == "bakeoff"
    assert describe["prompt_variant"] == "v2"
    assert [p["pass"] for p in describe["passes"]] == ["weave_bench"]
    assert isinstance(describe["passes"][0]["latency_s"], float)


def test_weave_bench_applies_context_distractor_transform_and_stamp() -> None:
    """The replay shares the live fetch-time transforms — a distractor cell replays as one."""
    captured: list[dict] = []
    client = _client(
        captured,
        [_WEAVE_CAPTION],
        eval_mode="context_distractor",
        entry_traits={7: {"present": [], "easy_wrong": ["Mallory Trap"]}},
    )
    describe = client.weave_bench_describe(media_id=7, facts_raw=_FACTS_JSON, context_pack={"caption": "x"})
    assert describe["injected_distractor"] == "Mallory Trap"
    assert "Mallory Trap" in _user_text(captured[0]["payload"])


def test_weave_bench_run_record_replays_and_stamps_source_provenance() -> None:
    source = _weave_source_record([_weave_source_item(101, "img0.jpg"), _weave_source_item(102, "img1.jpg")])
    manifest = _weave_manifest([101, 102])
    captured: list[dict] = []
    client = _client(captured, [_WEAVE_CAPTION, "A second caption."], prompt_variant="v2")
    try:
        record = weave_bench_run_record(
            source, manifest, client, source_path="out/run-gpu.json", source_sha256="c" * 64, head_sha="deadbeef"
        )
    finally:
        client.close()
    prov = record["provenance"]
    assert prov["weave_bench"] is True
    assert prov["weave_bench_source"] == {
        "path": "out/run-gpu.json",
        "sha256": "c" * 64,
        "manifest_sha256": "f" * 64,
        "head_sha": "a" * 40,
        "started_at": "2026-07-16T00:00:00Z",
    }
    assert record["kind"] == "run_record"
    assert [i["error"] for i in record["items"]] == [None, None]
    assert record["items"][0]["describe"]["alt_text_draft"] == _WEAVE_CAPTION
    assert all(isinstance(i["latency_s"], float) for i in record["items"])
    # scoring works UNCHANGED on the output — it is a normal caption run record
    entries = [e.model_dump() for e in manifest.entries]
    a = build_reports(record, entries)
    b = build_reports(record, entries)
    assert a == b, "re-score must stay bit-identical"
    scored = json.loads(a[0])
    assert scored["counts"] == {"total": 2, "scored": 2, "failed": 0}
    assert scored["provenance"]["weave_bench"] is True
    assert scored["latency"]["images_timed"] == 2  # Slice-3 latency axis rides the replay record
    assert "weave-bench replay" in a[1]  # markdown attribution banner


def test_weave_bench_missing_facts_is_typed_failure_and_run_continues() -> None:
    no_passes = _weave_source_item(101, "img0.jpg")
    del no_passes["describe"]["passes"]
    fetch_failed = _weave_source_item(102, "img1.jpg")
    fetch_failed["describe"] = None
    fetch_failed["error"] = "RemoteClientError: timeout"
    wrong_first = _weave_source_item(103, "img2.jpg")
    wrong_first["describe"]["passes"] = [{"pass": "caption", "raw": "a dual-length long", "latency_s": 1.0}]
    good = _weave_source_item(104, "img3.jpg")
    source = _weave_source_record([no_passes, fetch_failed, wrong_first, good])
    manifest = _weave_manifest([101, 102, 103, 104])
    captured: list[dict] = []
    client = _client(captured, [_WEAVE_CAPTION])
    try:
        record = weave_bench_run_record(
            source, manifest, client, source_path="s.json", source_sha256="c" * 64, head_sha="d"
        )
    finally:
        client.close()
    errors = [i["error"] for i in record["items"]]
    assert all(e is not None and "WeaveBenchSourceError" in e for e in errors[:3])
    assert errors[3] is None
    assert record["items"][3]["describe"]["alt_text_draft"] == _WEAVE_CAPTION
    assert len(captured) == 1, "only the replayable item may reach the endpoint"


def test_weave_bench_media_id_missing_from_manifest_is_per_item_failure() -> None:
    source = _weave_source_record([_weave_source_item(999, "img0.jpg")])
    manifest = _weave_manifest([101])
    client = _client([], [_WEAVE_CAPTION])
    try:
        record = weave_bench_run_record(
            source, manifest, client, source_path="s.json", source_sha256="c" * 64, head_sha="d"
        )
    finally:
        client.close()
    assert "WeaveBenchSourceError" in record["items"][0]["error"]
    assert "999" in record["items"][0]["error"]


def test_weave_bench_bounded_stall_aborts_with_partial_record() -> None:
    items = []
    for i in range(4):
        item = _weave_source_item(101 + i, f"img{i}.jpg")
        del item["describe"]["passes"]
        items.append(item)
    source = _weave_source_record(items)
    manifest = _weave_manifest([101, 102, 103, 104])
    client = _client([], [_WEAVE_CAPTION])
    try:
        with pytest.raises(BoundedStallError) as excinfo:
            weave_bench_run_record(
                source, manifest, client, source_path="s.json", source_sha256="c" * 64, head_sha="d", stall_limit=3
            )
    finally:
        client.close()
    partial = excinfo.value.partial_record
    assert partial["aborted"] is True
    assert partial["provenance"]["weave_bench"] is True
    assert len(partial["items"]) == 3
    assert all(i["error"] is not None for i in partial["items"])


def test_load_weave_bench_source_returns_record_and_file_sha(tmp_path: Path) -> None:
    source = _weave_source_record([_weave_source_item(101, "img0.jpg")])
    path = tmp_path / "run.json"
    path.write_text(json.dumps(source))
    record, sha = _load_weave_bench_source(path)
    assert record["items"][0]["media_id"] == 101
    assert sha == hashlib.sha256(path.read_bytes()).hexdigest()


def test_load_weave_bench_source_rejects_malformed_records(tmp_path: Path) -> None:
    """Malformed source record => clear whole-run abort, never a silent partial replay."""
    not_json = tmp_path / "bad.json"
    not_json.write_text("{nope")
    with pytest.raises(WeaveBenchRecordError, match="not readable JSON"):
        _load_weave_bench_source(not_json)

    not_object = tmp_path / "list.json"
    not_object.write_text("[1, 2]")
    with pytest.raises(WeaveBenchRecordError, match="JSON object"):
        _load_weave_bench_source(not_object)

    report_doc = tmp_path / "report.json"
    report_doc.write_text(json.dumps({"schema": "acx-eval/v1", "kind": "report", "provenance": {}, "items": [{}]}))
    with pytest.raises(WeaveBenchRecordError, match="run_record"):
        _load_weave_bench_source(report_doc)

    no_items = tmp_path / "empty.json"
    no_items.write_text(json.dumps({"schema": "acx-eval/v1", "kind": "run_record", "provenance": {}, "items": []}))
    with pytest.raises(WeaveBenchRecordError, match="no items"):
        _load_weave_bench_source(no_items)

    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(WeaveBenchRecordError, match="not readable"):
        _load_weave_bench_source(missing)


def test_weave_bench_facts_missing_raw_is_typed_failure() -> None:
    item = _weave_source_item(101, "img0.jpg")
    item["describe"]["passes"][0]["raw"] = None  # failed pass-1 recorded raw=None
    source = _weave_source_record([item, _weave_source_item(102, "img1.jpg")])
    manifest = _weave_manifest([101, 102])
    captured: list[dict] = []
    client = _client(captured, [_WEAVE_CAPTION])
    try:
        record = weave_bench_run_record(
            source, manifest, client, source_path="s.json", source_sha256="c" * 64, head_sha="d"
        )
    finally:
        client.close()
    assert "WeaveBenchSourceError" in record["items"][0]["error"]
    assert record["items"][1]["error"] is None


def test_weave_bench_cli_flag_rejects_two_pass_and_dual_length() -> None:
    for extra in ("--two-pass", "--dual-length"):
        with pytest.raises(SystemExit) as excinfo:
            main(["--endpoint", "http://x", "--model-id", "m", "--weave-bench", "r.json", extra])
        assert "--weave-bench" in str(excinfo.value)


def test_weave_bench_cli_aborts_on_malformed_source_without_images_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The replay is text-only: GOLDEN_IMAGES_DIR must not be required, and a malformed
    source aborts loudly before any manifest load or endpoint call."""
    monkeypatch.setenv("ACX_EVAL_LIVE", "1")
    monkeypatch.delenv("GOLDEN_IMAGES_DIR", raising=False)
    bad = tmp_path / "source.json"
    bad.write_text("{not json")
    with pytest.raises(SystemExit) as excinfo:
        main(["--endpoint", "http://x", "--model-id", "m", "--weave-bench", str(bad)])
    assert "WeaveBenchRecordError" in str(excinfo.value)


# --- ALTQ-1 v3: three-surface weave (title + WCAG alt + evocative caption) -----

_V3_SURFACES = {
    "title": "Woman at a rocky shoreline",
    "alt": "Caitlin Weaver stands at the waterline of a rocky shoreline in a red jacket.",
    "caption": (
        "Caitlin Weaver pauses where the rocks meet the water, her red jacket bright "
        "against the grey. The sky hangs low and overcast. The shoreline is quiet."
    ),
}
_V3_JSON = json.dumps(_V3_SURFACES)
_V3_FENCED = f"```json\n{_V3_JSON}\n```"


def _v3_client(captured: list[dict], responses: list[object]) -> BakeoffClient:
    return _client(captured, responses, prompt_variant="v3", two_pass=True)


def test_v3_registered_three_surface_and_inherits_v2_style_rules() -> None:
    v3 = PROMPT_VARIANTS["v3"]
    assert v3.three_surface is True
    assert v3.system == PROMPT_VARIANTS["v2"].system  # findings §3 style rules inherited, not forked
    assert not PROMPT_VARIANTS["v1"].three_surface and not PROMPT_VARIANTS["v2"].three_surface


def test_v3_requires_two_pass_and_rejects_dual_length_at_construction() -> None:  # rg-008 fail-fast
    with pytest.raises(ValueError, match="two_pass"):
        _client([], ["x"], prompt_variant="v3")
    with pytest.raises(ValueError, match="dual_length"):
        _client([], ["x"], prompt_variant="v3", two_pass=True, dual_length=True)


def test_v3_cli_rejects_without_two_pass_and_with_dual_length() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--endpoint", "http://x", "--model-id", "m", "--prompt-variant", "v3"])
    assert "--two-pass" in str(excinfo.value)
    with pytest.raises(SystemExit) as excinfo:
        main(["--endpoint", "http://x", "--model-id", "m", "--prompt-variant", "v3", "--two-pass", "--dual-length"])
    assert "--dual-length" in str(excinfo.value)


def test_v3_weave_message_carries_three_field_contract_facts_and_context() -> None:
    captured: list[dict] = []
    _describe(_v3_client(captured, [_FACTS_JSON, _V3_FENCED]), {"caption": "Caitlin Weaver on the peninsula."})
    assert len(captured) == 2
    system = _system_text(captured[1]["payload"])
    # structured three-field output contract
    assert '"title"' in system and '"alt"' in system and '"caption"' in system
    assert "3-8 word" in system and "125" in system and "2-5 sentences" in system
    assert "Never invent specifics" in system  # CapRL fabrication anti-pattern fenced out
    # shared weave scaffolding EXTENDED, not forked: v2 style base + mismatch few-shot + never-guess
    assert system.startswith(PROMPT_VARIANTS["v2"].system)
    assert "Maria Chen" in system and "leave that name out" in system
    assert "Never name or guess about anyone the context does not name." in system
    user = _user_text(captured[1]["payload"])
    assert "<<<FACTS>>>" in user and "rocky shoreline" in user
    assert "<<<CONTEXT>>>" in user and "Caitlin Weaver" in user
    # pass-1 stays context-free and unchanged by v3
    assert "Caitlin Weaver" not in json.dumps(captured[0]["payload"])


def test_v3_happy_path_parses_three_surfaces_into_describe_keys() -> None:
    captured: list[dict] = []
    describe = _describe(_v3_client(captured, [_FACTS_JSON, _V3_FENCED]), {"caption": "x"})
    assert describe["alt_text_title"] == _V3_SURFACES["title"]
    assert describe["alt_text_draft"] == _V3_SURFACES["alt"]
    assert describe["alt_text_long"] == _V3_SURFACES["caption"]
    assert describe["prompt_variant"] == "v3"  # provenance stamp, same mechanism as v1/v2
    assert [p["pass"] for p in describe["passes"]] == ["describe_facts", "ground_weave"]
    assert describe["passes"][1]["raw"] == _V3_FENCED  # raw weave output preserved for replay/triage


def test_v3_malformed_or_incomplete_weave_json_is_typed_per_item_failure_and_run_continues(
    tmp_path: Path,
) -> None:
    """[AGT-10] degrade loudly: a bad three-surface weave fails ONE item, not the run (rg-007)."""
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
                "provenance": {"source": "fixture", "license": "fixture"},
            }
        )
    manifest = GoldenManifest.model_validate({"manifest_version": 3,
            "annotation_mode": "roster_only", "roster": [], "entries": entries})
    captured: list[dict] = []
    # item 0: weave JSON missing the "caption" field; item 1: valid three-surface JSON.
    missing_key = json.dumps({"title": "A title of five words", "alt": "An alt."})
    client = _v3_client(captured, [_FACTS_JSON, missing_key, _FACTS_JSON, _V3_FENCED])
    try:
        record = fetch_run_record(manifest, str(tmp_path), client, head_sha="deadbeef")
    finally:
        client.close()
    assert record["items"][0]["describe"] is None
    assert "ThreeSurfaceParseError" in record["items"][0]["error"]
    assert "caption" in record["items"][0]["error"]
    assert record["items"][1]["describe"]["alt_text_title"] == _V3_SURFACES["title"]
    assert record["items"][1]["describe"]["alt_text_draft"] == _V3_SURFACES["alt"]


def test_parse_three_surface_json_accepts_fenced_and_bare_json() -> None:
    for raw in (_V3_JSON, _V3_FENCED):
        assert _parse_three_surface_json(raw) == _V3_SURFACES


def test_parse_three_surface_json_rejects_malformed_missing_and_non_string() -> None:
    with pytest.raises(ThreeSurfaceParseError, match="malformed"):
        _parse_three_surface_json("Sure! Here are your three surfaces.")
    with pytest.raises(ThreeSurfaceParseError, match="expected an object"):
        _parse_three_surface_json("[1, 2]")
    with pytest.raises(ThreeSurfaceParseError, match="caption"):
        _parse_three_surface_json(json.dumps({"title": "A short title here", "alt": "An alt."}))
    with pytest.raises(ThreeSurfaceParseError, match="alt"):
        _parse_three_surface_json(json.dumps({"title": "T", "alt": ["not", "a", "string"], "caption": "C."}))
    with pytest.raises(ThreeSurfaceParseError, match="title"):
        _parse_three_surface_json(json.dumps({"title": "   ", "alt": "An alt.", "caption": "C."}))


def test_v3_provenance_stamp_matches_v1_v2_mechanism() -> None:
    provenance: dict = {}
    _stamp_pipeline_provenance(
        provenance, prompt_variant="v3", two_pass=True, dual_length=False, face_gate=False, eval_mode="standard"
    )
    assert provenance == {"prompt_variant": "v3", "two_pass": True}


# --- v3 score side: title quality axis (additive, closed-roster name scan) -----


def _v3_record(title: str) -> dict:
    record = _old_shape_record()
    record["provenance"]["prompt_variant"] = "v3"
    record["provenance"]["two_pass"] = True
    record["items"][0]["describe"].update(
        {
            "prompt_variant": "v3",
            "alt_text_title": title,
            "alt_text_draft": "Alice Example relaxes by a pool.",
            "alt_text_long": "Alice Example relaxes by a sunlit pool. The water is calm. She smiles.",
        }
    )
    return record


def test_title_quality_block_counts_presence_and_word_band() -> None:
    scored = score_run_record(_v3_record("Alice Example by the pool"), _entries())
    assert scored["quality"]["title"] == {
        "title_present": 1,
        "word_band": [3, 8],
        "word_band_violations": 0,
        "hallucinated_name_images": 0,
        "hallucinated_names": [],
    }
    # 2 words < band minimum and 9 words > band maximum both violate
    scored = score_run_record(_v3_record("Pool day"), _entries())
    assert scored["quality"]["title"]["word_band_violations"] == 1
    scored = score_run_record(_v3_record("Alice Example relaxing by the pool on summer afternoon"), _entries())
    assert scored["quality"]["title"]["word_band_violations"] == 1


def test_title_hallucinated_name_scan_uses_closed_roster() -> None:
    """A roster name the entry does not account for appearing in a TITLE is flagged
    by the SAME closed-roster trap used for captions (planted out-of-entry name)."""
    roster = ["Alice Example", "Bob Builder"]
    scored = score_run_record(_v3_record("Bob Builder at the pool"), _entries(), manifest_roster=roster)
    q = scored["quality"]["title"]
    assert q["hallucinated_name_images"] == 1
    assert q["hallucinated_names"] == ["Bob Builder"]
    # the present identity in the title never trips the trap
    scored = score_run_record(_v3_record("Alice Example by the pool"), _entries(), manifest_roster=roster)
    assert scored["quality"]["title"]["hallucinated_name_images"] == 0
    assert scored["quality"]["title"]["hallucinated_names"] == []


def test_title_axis_absent_keeps_report_shape_unchanged() -> None:
    """Additive-schema proof, mirroring the Slice-2 old-record test: no titles, no keys."""
    scored = score_run_record(_old_shape_record(), _entries())
    assert "title" not in scored["quality"]
    _json_doc, md = build_reports(_old_shape_record(), _entries())
    assert "titles present" not in md
    # a titled v3 record re-scores bit-identically (report determinism preserved)
    record = _v3_record("Alice Example by the pool")
    assert build_reports(record, _entries()) == build_reports(record, _entries())


def test_title_metrics_render_in_markdown() -> None:
    _json_doc, md = build_reports(
        _v3_record("Bob Builder at the pool"), _entries(), manifest_roster=["Alice Example", "Bob Builder"]
    )
    assert "titles present: 1" in md
    assert "title word band [3, 8] violations: 0" in md
    assert "title hallucinated-name images: 1 (Bob Builder)" in md
    assert "prompt variant: `v3`" in md
