"""VLM-2B bake-off: manifest invariants (Slice 1) + BakeoffClient transport (Slice 3).

The bake-off subset manifest must make insertion rate *measurable*: every
recognition-enabled entry with labeled identities carries those names in the
``context_pack`` text the candidate model actually sees. Policy-disabled and
no-context entries are deliberate traps and are asserted separately.

Transport tests stub the candidate llama.cpp endpoint (httpx.MockTransport, no
network) and verify the prompt-render contract: every injected context name
reaches the candidate prompt verbatim, decoding is greedy, and the face-metric
methods are inert no-ops. Per-item isolation + bounded-stall stay covered by
the reused ``cli.fetch_run_record`` tests — not duplicated here.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from scripts.eval_harness.bakeoff import BakeoffClient, _extract_caption
from scripts.eval_harness.cli import BoundedStallError, fetch_run_record
from scripts.eval_harness.manifest import GoldenEntry, GoldenManifest, load_manifest
from scripts.eval_harness.remote_client import RemoteClientError
from scripts.eval_harness.report import build_reports

BAKEOFF_MANIFEST = Path(__file__).parent / "seed" / "bakeoff_golden.json"
GOLDEN_MANIFEST = Path(__file__).parent / "seed" / "golden.json"


@pytest.fixture(scope="module")
def manifest() -> GoldenManifest:
    return load_manifest(str(BAKEOFF_MANIFEST))


def _context_text(entry: GoldenEntry) -> str:
    pack = entry.context_pack.model_dump(exclude_none=True)
    return " ".join(str(v) for v in pack.values())


def _insertion_cohort(manifest: GoldenManifest) -> list[GoldenEntry]:
    return [e for e in manifest.entries if e.policy.recognition_enabled and e.present_identities]


def test_manifest_loads_and_is_bakeoff_sized(manifest: GoldenManifest) -> None:
    assert 8 <= len(manifest.entries) <= 12


def test_insertion_cohort_context_packs_carry_every_present_identity(manifest: GoldenManifest) -> None:
    cohort = _insertion_cohort(manifest)
    assert cohort, "bake-off manifest has no insertion-rate cohort; insertion rate is unmeasurable"
    for entry in cohort:
        text = _context_text(entry)
        assert text.strip(), f"{entry.path}: insertion-cohort entry has an empty context pack"
        for name in entry.present_identities:
            assert name in text, f"{entry.path}: injected name {name!r} missing from context_pack text"


def test_must_right_names_are_supplied_in_context(manifest: GoldenManifest) -> None:
    for entry in manifest.entries:
        if not entry.policy.recognition_enabled:
            continue
        text = _context_text(entry)
        for name in entry.must_right:
            assert name in text, (
                f"{entry.path}: must_right {name!r} not supplied in context_pack; "
                "the gate would demand a name the model never saw"
            )


def test_policy_disabled_trap_exists_and_leaks_no_names(manifest: GoldenManifest) -> None:
    disabled = [e for e in manifest.entries if not e.policy.recognition_enabled]
    assert disabled, "bake-off manifest needs at least one policy-disabled trap entry"
    for entry in disabled:
        text = _context_text(entry)
        for name in entry.present_identities:
            assert name not in text, f"{entry.path}: policy-disabled entry leaks {name!r} into context"
        # policy is the sole disabled-naming trap; a must_right on a policy-disabled entry is
        # self-contradictory ground truth (score_caption zeroes must_right when recognition is off).
        assert not entry.must_right, (
            f"{entry.path}: policy-disabled entry must not carry a must_right name — the gate can never demand it"
        )


def test_no_context_degradation_entry_exists(manifest: GoldenManifest) -> None:
    empty = [e for e in manifest.entries if not _context_text(e).strip()]
    assert empty, "bake-off manifest needs a no-context degradation entry"


def test_rubrics_are_not_vacuous(manifest: GoldenManifest) -> None:
    assert any(e.must_right or e.easy_wrong for e in manifest.entries)


# main golden.json has no rubrics until VLM-2C populates it; that warning is its, not ours
@pytest.mark.filterwarnings("ignore::scripts.eval_harness.manifest.RubricEmptyWarning")
def test_entries_reuse_golden_corpus_images(manifest: GoldenManifest) -> None:
    golden = load_manifest(str(GOLDEN_MANIFEST))
    golden_by_path = {e.path: e for e in golden.entries}
    for entry in manifest.entries:
        assert entry.path in golden_by_path, f"{entry.path}: not in golden corpus (new image needs README bootstrap)"
        gold = golden_by_path[entry.path]
        # Do not fork ground truth: image bytes AND identity labels must match the golden corpus,
        # since the analyze contract keys uploads/identity reads by media_id (a drifted id would
        # misattribute identities in any future non-stub run).
        assert entry.sha256 == gold.sha256, f"{entry.path}: sha256 drifted from golden corpus"
        assert entry.media_id == gold.media_id, f"{entry.path}: media_id drifted from golden corpus"
        assert entry.face_count == gold.face_count, f"{entry.path}: face_count drifted from golden corpus"
        assert entry.present_identities == gold.present_identities, (
            f"{entry.path}: present_identities drifted from golden corpus"
        )


def test_manifest_covers_discriminating_classes(manifest: GoldenManifest) -> None:
    """Pin the §6b discriminating classes so a later 'reuse VLM-2C packs' edit cannot silently
    delete the entries that give the bake-off its discriminating power."""
    entries = manifest.entries
    # two-roster-plus-strangers association: more faces than named present identities.
    assert any(e.face_count > len(e.present_identities) and len(e.present_identities) >= 2 for e in entries), (
        "manifest lost its multi-person-plus-strangers association entry"
    )
    # abstract / hallucination-pressure: no faces but an attribution must_right.
    assert any(e.face_count == 0 and e.must_right for e in entries), (
        "manifest lost its abstract/attribution (face_count 0 + must_right) entry"
    )
    # context-conflicts-pixels: the plane-crash entry whose context labels a garden picnic.
    assert any(e.path.endswith("mcm-planecrash.jpg") for e in entries), (
        "manifest lost its context-conflicts-pixels (mcm-planecrash) entry"
    )


# --- Slice 3: BakeoffClient transport (stubbed endpoint, no network) ---


def _chat_transport(captured: list[dict], content: str = "A caption naming Caitlin Weaver.") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append({"path": request.url.path, "payload": payload})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler)


def _client(
    captured: list[dict], *, no_think: bool = False, content: str = "A caption naming Caitlin Weaver."
) -> BakeoffClient:
    return BakeoffClient(
        base_url="http://candidate.test:8080",
        model_id="qwen3-vl-4b-instruct",
        model_version="Q4_K_M",
        no_think=no_think,
        transport=_chat_transport(captured, content=content),
    )


def _describe(client: BakeoffClient, context_pack: dict) -> dict:
    return client.describe(
        image_bytes=b"\x89PNG fake bytes",
        filename="img.jpg",
        media_id=7,
        context_pack=context_pack,
    )


def test_describe_returns_scoreable_shape() -> None:
    captured: list[dict] = []
    describe = _describe(_client(captured), {"caption": "Caitlin Weaver in Antarctica."})
    assert describe["alt_text_draft"] == "A caption naming Caitlin Weaver."
    assert describe["adapter"] == "bakeoff"
    assert describe["model_id"] == "qwen3-vl-4b-instruct"
    assert describe["model_version"] == "Q4_K_M"


def test_context_pack_names_render_into_prompt_verbatim() -> None:
    captured: list[dict] = []
    pack = {
        "title": "Antarctica expedition",
        "caption": "Caitlin Weaver on the peninsula.",
        "description": "Erika Hansen Miller took the photo.",
    }
    _describe(_client(captured), pack)
    prompt_text = json.dumps(captured[0]["payload"])
    for fragment in ("Caitlin Weaver", "Erika Hansen Miller", "Antarctica expedition"):
        assert fragment in prompt_text, f"injected context {fragment!r} never reached the candidate prompt"


def test_decoding_is_greedy_and_no_think_is_optional() -> None:
    captured: list[dict] = []
    _describe(_client(captured), {})
    payload = captured[0]["payload"]
    assert payload["temperature"] == 0
    assert "/no_think" not in json.dumps(payload)

    captured.clear()
    _describe(_client(captured, no_think=True), {})
    assert "/no_think" in json.dumps(captured[0]["payload"])


def test_context_block_is_fenced_and_no_think_precedes_it() -> None:  # S6-04
    captured: list[dict] = []
    pack = {"caption": "Caitlin Weaver\n- injected: spoof", "description": "multi\nline"}
    _describe(_client(captured, no_think=True), pack)
    user_text = captured[0]["payload"]["messages"][1]["content"][1]["text"]
    assert "<<<CONTEXT>>>" in user_text and "<<<END_CONTEXT>>>" in user_text
    no_think_at = user_text.index("/no_think")
    context_at = user_text.index("<<<CONTEXT>>>")
    assert no_think_at < context_at, "/no_think must precede untrusted context"
    # multi-line values JSON-escaped so they cannot dissolve structure
    assert "\\n" in user_text or '"multi\\nline"' in user_text or "multi\\nline" in user_text


def test_face_metric_methods_are_inert_stubs() -> None:
    captured: list[dict] = []
    client = _client(captured)
    job_id = client.analyze([(7, "img.jpg", b"bytes")])
    assert isinstance(job_id, str)
    assert client.wait_job(job_id) == {}
    assert client.media_identities([7]) == []
    assert captured == [], "face-metric stubs must not touch the network"


def test_fetch_run_record_with_bakeoff_client_scores_deterministically(tmp_path: Path) -> None:
    manifest = GoldenManifest.model_validate(
        {
            "manifest_version": 2,
            "roster": ["Caitlin Weaver"],
            "entries": [
                {
                    "path": "img.jpg",
                    "sha256": "0" * 64,
                    "media_id": 7,
                    "face_count": 1,
                    "present_identities": ["Caitlin Weaver"],
                    "context_pack": {"caption": "Caitlin Weaver in Antarctica."},
                    "must_right": ["Caitlin Weaver"],
                    "easy_wrong": [],
                    "policy": {"recognition_enabled": True},
                    "provenance": {"source": "operator", "license": "mock_entity"},
                }
            ],
        }
    )
    (tmp_path / "img.jpg").write_bytes(b"fake image bytes")
    captured: list[dict] = []
    record = fetch_run_record(manifest, str(tmp_path), _client(captured), head_sha="deadbeef")

    assert record["items"][0]["error"] is None
    assert record["items"][0]["describe"]["alt_text_draft"] == "A caption naming Caitlin Weaver."
    assert record["provenance"]["base_url"] == "http://candidate.test:8080"

    entries = [e.model_dump() for e in manifest.entries]
    first = build_reports(record, entries)
    second = build_reports(record, entries)
    assert first == second, "re-score must be bit-identical"
    scored = json.loads(first[0])
    assert scored["caption"]["insertion_rate"] == 1.0
    assert "qwen3-vl-4b-instruct" in scored["provenance"]["model"]["model_ids"]


# --- Slice 3: extraction + transport failure modes ---


def test_extract_caption_reasoning_only_names_reasoning_content() -> None:
    """The observed live MiniCPM failure: 200 with empty content + filled reasoning_content."""
    payload = {"choices": [{"message": {"content": "", "reasoning_content": "long chain of thought"}}]}
    with pytest.raises(RemoteClientError, match="reasoning_content"):
        _extract_caption(payload)


def test_extract_caption_content_none_is_empty_error() -> None:
    payload = {"choices": [{"message": {"content": None}}]}
    with pytest.raises(RemoteClientError, match="empty caption"):
        _extract_caption(payload)


def test_extract_caption_joins_content_parts_array() -> None:
    payload = {
        "choices": [{"message": {"content": [{"type": "text", "text": "Caitlin"}, {"type": "text", "text": "Weaver"}]}}]
    }
    assert _extract_caption(payload) == "Caitlin Weaver"


def test_timeout_wires_through_to_httpx_client() -> None:
    """--timeout must reach the underlying httpx client, not silently fall back to the 60s default."""
    client = BakeoffClient(
        base_url="http://candidate.test:8080",
        model_id="qwen3-vl-4b-instruct",
        timeout_s=900.0,
        transport=_chat_transport([]),
    )
    try:
        assert client._client.timeout.read == 900.0
    finally:
        client.close()


def _status_transport(status: int, json_body: dict | None = None) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=json_body if json_body is not None else {"error": "boom"})

    return httpx.MockTransport(handler)


def test_fetch_run_record_surfaces_transport_error_as_per_item_error(tmp_path: Path) -> None:
    """A non-2xx from the candidate must isolate to a per-item error string, not crash the walk."""
    manifest = GoldenManifest.model_validate(
        {
            "manifest_version": 2,
            "roster": ["Caitlin Weaver"],
            "entries": [
                {
                    "path": "img.jpg",
                    "sha256": "0" * 64,
                    "media_id": 7,
                    "face_count": 1,
                    "present_identities": ["Caitlin Weaver"],
                    "context_pack": {"caption": "Caitlin Weaver in Antarctica."},
                    "must_right": ["Caitlin Weaver"],
                    "easy_wrong": [],
                    "policy": {"recognition_enabled": True},
                    "provenance": {"source": "operator", "license": "mock_entity"},
                }
            ],
        }
    )
    (tmp_path / "img.jpg").write_bytes(b"fake image bytes")
    client = BakeoffClient(base_url="http://candidate.test:8080", model_id="m", transport=_status_transport(500))
    try:
        record = fetch_run_record(manifest, str(tmp_path), client, head_sha="deadbeef")
    finally:
        client.close()
    assert record["items"][0]["describe"] is None
    assert record["items"][0]["error"] is not None
    assert "RemoteClientError" in record["items"][0]["error"]


def test_fetch_run_record_bounded_stall_aborts_on_repeated_failures(tmp_path: Path) -> None:
    entries = []
    for i in range(6):
        (tmp_path / f"img{i}.jpg").write_bytes(b"fake image bytes")
        entries.append(
            {
                "path": f"img{i}.jpg",
                "sha256": f"{i}" * 64,
                "media_id": 100 + i,
                "face_count": 0,
                "present_identities": [],
                "context_pack": {"caption": "x"},
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "provenance": {"source": "operator", "license": "mock_entity"},
            }
        )
    manifest = GoldenManifest.model_validate({"manifest_version": 2, "roster": ["Caitlin Weaver"], "entries": entries})
    client = BakeoffClient(base_url="http://candidate.test:8080", model_id="m", transport=_status_transport(500))
    try:
        with pytest.raises(BoundedStallError) as excinfo:
            fetch_run_record(manifest, str(tmp_path), client, head_sha="deadbeef", stall_limit=3)
    finally:
        client.close()
    assert excinfo.value.partial_record["aborted"] is True
    assert all(item["error"] is not None for item in excinfo.value.partial_record["items"])


# --- ALTQ-1: fetch-time eval-mode transforms ---


def test_ablate_names_replaces_word_boundary_case_insensitive() -> None:
    from scripts.eval_harness.bakeoff import _ablate_names

    pack = {
        "title": "Antarctica expedition",
        "caption": "CAITLIN WEAVER on the peninsula.",
        "description": "Caitlin Weaver reached the peninsula. Caitlin Weavers' gear stayed aboard.",
    }
    out, ablated = _ablate_names(pack, ["Caitlin Weaver"])
    assert ablated == ["Caitlin Weaver"]
    assert out["caption"] == "someone on the peninsula."
    assert out["description"].startswith("someone reached the peninsula.")
    # word boundary (S2-06): "Caitlin Weavers'" is a different token and must survive.
    assert "Caitlin Weavers'" in out["description"]
    assert "Caitlin Weaver reached" not in out["description"]
    assert out["title"] == "Antarctica expedition"


def test_ablate_names_reports_only_names_found() -> None:
    from scripts.eval_harness.bakeoff import _ablate_names

    out, ablated = _ablate_names({"caption": "A quiet lake."}, ["Caitlin Weaver"])
    assert ablated == []
    assert out == {"caption": "A quiet lake."}


def test_inject_distractor_picks_first_easy_wrong() -> None:
    from scripts.eval_harness.bakeoff import _inject_distractor

    pack, injected = _inject_distractor({"caption": "By a pool."}, ["Mallory Trap", "Ned Nemo"])
    assert injected == "Mallory Trap"
    assert pack["also_pictured"] == "Mallory Trap"
    assert pack["caption"] == "By a pool."


def test_inject_distractor_none_without_easy_wrong() -> None:
    from scripts.eval_harness.bakeoff import _inject_distractor

    pack, injected = _inject_distractor({"caption": "By a pool."}, [])
    assert injected is None
    assert pack == {"caption": "By a pool."}


def _eval_mode_client(captured: list[dict], mode: str, traits: dict) -> BakeoffClient:
    return BakeoffClient(
        base_url="http://candidate.test:8080",
        model_id="qwen3-vl-4b-instruct",
        transport=_chat_transport(captured),
        eval_mode=mode,
        entry_traits=traits,
    )


def test_name_ablation_mode_strips_names_from_prompt_and_stamps() -> None:
    captured: list[dict] = []
    client = _eval_mode_client(captured, "name_ablation", {7: {"present": ["Caitlin Weaver"], "easy_wrong": []}})
    describe = _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    prompt_text = json.dumps(captured[0]["payload"])
    assert "Caitlin Weaver" not in prompt_text
    assert "someone" in prompt_text
    assert describe["ablated_names"] == ["Caitlin Weaver"]


def test_context_distractor_mode_injects_and_stamps() -> None:
    captured: list[dict] = []
    client = _eval_mode_client(
        captured, "context_distractor", {7: {"present": ["Caitlin Weaver"], "easy_wrong": ["Mallory Trap"]}}
    )
    describe = _describe(client, {"caption": "Caitlin Weaver on the peninsula."})
    prompt_text = json.dumps(captured[0]["payload"])
    assert "Mallory Trap" in prompt_text
    assert "also_pictured" in prompt_text
    assert describe["injected_distractor"] == "Mallory Trap"


def test_context_distractor_without_easy_wrong_stamps_nothing() -> None:
    captured: list[dict] = []
    client = _eval_mode_client(captured, "context_distractor", {7: {"present": [], "easy_wrong": []}})
    describe = _describe(client, {"caption": "A quiet lake."})
    assert "injected_distractor" not in describe


def test_standard_mode_default_leaves_context_untouched() -> None:
    captured: list[dict] = []
    describe = _describe(_client(captured), {"caption": "Caitlin Weaver on the peninsula."})
    assert "ablated_names" not in describe
    assert "injected_distractor" not in describe
    assert "Caitlin Weaver" in json.dumps(captured[0]["payload"])


def test_unknown_eval_mode_rejected_at_construction() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError):
        BakeoffClient(
            base_url="http://candidate.test:8080",
            model_id="m",
            transport=_chat_transport([]),
            eval_mode="bogus",
        )
    with _pytest.raises(ValueError):
        BakeoffClient(
            base_url="http://candidate.test:8080",
            model_id="m",
            transport=_chat_transport([]),
            eval_mode="name_ablation",  # requires entry_traits
        )
