"""DESCBAKE-1 B1: additive bake-off candidate intake and checkpoint audit.

Every test here is offline. The Hugging Face fetch is injected, and the
default-fetch tests replace ``urllib.request.urlopen`` so nothing leaves the
sandbox.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from scripts.eval_harness.bakeoff_intake import (
    DEFAULT_INTAKE_PATH,
    DEFAULT_TIMEOUT_S,
    AuditStatus,
    ComparisonGroup,
    FetchResult,
    IntakeError,
    IntakeReport,
    ResearchRow,
    audit_one,
    build_report,
    comparison_group,
    default_fetch,
    generation_eligible,
    generation_roster,
    load_intake,
    main,
    md_cell,
    render_markdown,
    runnable_candidate_ids,
)

from scripts.eval_harness.bakeoff_candidates import CandidateRole, default_registry_path, load_bakeoff_candidates

FIXED_UTC = "2026-10-17T02:48:11Z"

# Exact model-page URLs as supplied in the research brief. Hard-coded on
# purpose: deriving them from the repo names would make the URL test circular.
SUPPLIED_RESEARCH_URLS = {
    "google/embeddinggemma-2": "https://huggingface.co/google/embeddinggemma-2",
    "XiaomiMiMo/MiMo-V2.6-Pro-RL": "https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-RL",
    "XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B": "https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B",
    "XiaomiMiMo/MiMo-V2.6-Flash-RL": "https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Flash-RL",
    "bartowski/MiMo-V2.6-Distill-Qwen-9B-GGUF": "https://huggingface.co/bartowski/MiMo-V2.6-Distill-Qwen-9B-GGUF",
    "deepseek-ai/DeepSeek-V4.1-Flash": "https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash",
    "unsloth/DeepSeek-V4-Flash-0731-GGUF": "https://huggingface.co/unsloth/DeepSeek-V4-Flash-0731-GGUF",
    "ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF": "https://huggingface.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF",
    "unsloth/Muse-Glimmer-30B-GGUF": "https://huggingface.co/unsloth/Muse-Glimmer-30B-GGUF",
    "unsloth/Qwen3.8-Flash-Next-GGUF": "https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF",
}

# Latest main shas observed in the supplied public audit for the three sealed
# rows whose pins were behind main at that time.
SUPPLIED_OUTDATED_LATEST = {
    "openbmb/MiniCPM-V-4_5-gguf": "8bfaecb5b1a65f068b86c32b997a3d5d8902eb36",
    "unsloth/Qwen3.8-27B-GGUF": "4ca720788d1e01f1bff70c033e0d0028fd02e502",
    "openbmb/MiniCPM-V-4_6-gguf": "afe9accb78d2995d214cd912920c9c92f4015faa",
}


def _sha(ch: str) -> str:
    return ch * 40


def _ok(sha: str, *, pipeline_tag: str | None = None, license_id: str | None = "mit") -> FetchResult:
    payload = {"sha": sha, "pipeline_tag": pipeline_tag, "cardData": {"license": license_id}}
    return FetchResult(status=200, payload=payload, error=None)


def _fake_fetch(
    table: Mapping[str, FetchResult],
    calls: list[tuple[str, float]] | None = None,
) -> Callable[[str, float], FetchResult]:
    def fetch(repo: str, timeout: float) -> FetchResult:
        if calls is not None:
            calls.append((repo, timeout))
        return table.get(repo, FetchResult(status=404, payload=None, error=None))

    return fetch


def _baseline_table() -> dict[str, FetchResult]:
    """Every sealed and research repo answers with its own baseline sha."""
    registry = load_bakeoff_candidates(default_registry_path())
    intake = load_intake()
    table = {entry.repo: _ok(entry.revision) for entry in registry.entries}
    table.update({row.repo: _ok(row.observed_sha) for row in intake.research_rows})
    return table


def _research(name: str = "text-only-probe", **overrides: Any) -> dict[str, Any]:
    repo = f"example/{name}"
    base: dict[str, Any] = {
        "id": name,
        "repo": repo,
        "source_url": f"https://huggingface.co/{repo}",
        "role": "generator",
        "pipeline_tag": "text-generation",
        "license": "mit",
        "hf_tags": ["text-generation", "transformers"],
        "observed_sha": _sha("c"),
        "observed_fetched_utc": FIXED_UTC,
        "observed_http_status": 200,
        "observed_source": f"https://huggingface.co/api/models/{repo}",
        "status": "pending_verification",
        "runnable": False,
        "allowed_use": "research only; pending serving and acceptance evidence",
    }
    base.update(overrides)
    return base


def _table_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("|"):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _unescaped_pipes(line: str) -> list[str]:
    return re.findall(r"(?<!\\)\|", line)


# --- offline default grid ---------------------------------------------------


def test_default_grid_lists_all_sixteen_sealed_rows_with_pinned_identity() -> None:
    registry = load_bakeoff_candidates(default_registry_path())
    report = build_report()

    assert len(report.sealed) == 16
    assert report.refreshed is False
    assert report.audit is None
    for shown, entry in zip(report.sealed, registry.entries, strict=True):
        assert shown.id == entry.id
        assert (shown.repo, shown.revision, shown.quant, shown.artifact) == (
            entry.repo,
            entry.revision,
            entry.quant,
            entry.artifact,
        )
        assert shown.tiers == [tier.value for tier in entry.tiers]


def test_default_grid_research_rows_are_exactly_the_supplied_ten_with_exact_urls() -> None:
    report = build_report()

    assert len(report.research) == 10
    assert {row.repo: row.source_url for row in report.research} == SUPPLIED_RESEARCH_URLS


def test_default_run_is_offline_and_does_not_import_huggingface_hub(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("default run must not touch the network")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    sys.modules.pop("huggingface_hub", None)

    assert main(["--format", "json"]) == 0
    assert "huggingface_hub" not in sys.modules
    report = IntakeReport.model_validate_json(capsys.readouterr().out)
    assert report.audit is None


def test_default_markdown_marks_every_research_row_pending_and_not_runnable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out

    assert out.count("pending_verification") == 10
    assert "Not performed" in out


# --- research intake rules --------------------------------------------------


def test_committed_intake_file_is_schema_valid_with_unique_ids() -> None:
    assert DEFAULT_INTAKE_PATH.name == "bakeoff_intake.json"
    doc = load_intake()

    assert doc.schema_id == "bakeoff-intake/v1"
    assert doc.observation.schema_id == "public-model-research/v1"
    assert doc.observation.fetched_utc == "2026-10-17T02:48:11.934939+00:00"
    ids = [row.id for row in doc.research_rows]
    assert len(ids) == len(set(ids)) == 10


def test_research_rows_are_pending_and_never_runnable() -> None:
    for row in load_intake().research_rows:
        assert row.status == "pending_verification"
        assert row.runnable is False


def test_research_row_cannot_be_declared_runnable() -> None:
    with pytest.raises(ValidationError):
        ResearchRow.model_validate(_research(runnable=True))


def test_docs_url_cannot_stand_in_for_a_model_row() -> None:
    with pytest.raises(ValidationError):
        ResearchRow.model_validate(_research(source_url="https://unsloth.ai/docs/some-guide"))


def test_malformed_observed_sha_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ResearchRow.model_validate(_research(observed_sha="abc|def"))


def test_docs_links_are_source_links_and_never_add_model_rows(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_INTAKE_PATH.read_text(encoding="utf-8"))
    raw["docs_links"] = [{"label": "guide", "url": "https://docs.example.invalid/guide", "kind": "docs"}]
    path = tmp_path / "intake.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    report = build_report(intake_path=path)

    assert len(report.research) == 10
    assert [link.url for link in report.docs_links] == ["https://docs.example.invalid/guide"]
    assert all("docs.example" not in row.source_url for row in report.research)


def test_invalid_intake_file_fails_fast(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_INTAKE_PATH.read_text(encoding="utf-8"))
    raw["research_rows"][0]["runnable"] = True
    path = tmp_path / "intake.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(IntakeError):
        build_report(intake_path=path)


def test_projector_provenance_is_kept_for_quantized_vision_rows() -> None:
    rows = {row.repo: row for row in load_intake().research_rows}

    assert {(p.path, p.size_bytes) for p in rows["bartowski/MiMo-V2.6-Distill-Qwen-9B-GGUF"].projectors} == {
        ("mmproj-MiMo-V2.6-Distill-Qwen-9B-bf16.gguf", 921704992),
        ("mmproj-MiMo-V2.6-Distill-Qwen-9B-f16.gguf", 918166048),
    }
    assert {(p.path, p.size_bytes) for p in rows["ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF"].projectors} == {
        ("mmproj-Qwen3.8-27B-BF16.gguf", 931146528),
    }
    assert len(rows["unsloth/Muse-Glimmer-30B-GGUF"].projectors) == 3
    assert len(rows["unsloth/Qwen3.8-Flash-Next-GGUF"].projectors) == 2
    assert rows["unsloth/DeepSeek-V4-Flash-0731-GGUF"].projectors == []


# --- runnable and generation roster boundaries ------------------------------


def test_runnable_candidates_come_only_from_the_sealed_registry() -> None:
    registry = load_bakeoff_candidates(default_registry_path())
    ids = runnable_candidate_ids(registry)

    assert ids == [e.id for e in registry.entries if e.role is CandidateRole.CANDIDATE and e.competing]
    assert len(ids) == 13  # phi4-mm is a non-competing candidate in the sealed roster
    research_repos = {row.repo for row in load_intake().research_rows}
    assert research_repos.isdisjoint({e.repo for e in registry.entries})


def test_research_encoder_never_enters_the_generation_roster() -> None:
    intake = load_intake()
    encoders = [row for row in intake.research_rows if row.role == "encoder"]

    assert [row.repo for row in encoders] == ["google/embeddinggemma-2"]
    assert comparison_group(encoders[0]) is ComparisonGroup.ENCODER
    assert generation_eligible(encoders[0]) is False
    assert generation_roster(intake) == []


def test_no_research_row_is_generation_eligible() -> None:
    for row in load_intake().research_rows:
        assert generation_eligible(row) is False


def test_comparison_groups_keep_text_only_and_vision_generators_apart() -> None:
    text_only = ResearchRow.model_validate(_research("text-only-probe"))
    vision = ResearchRow.model_validate(
        _research("vision-probe", pipeline_tag="image-text-to-text", hf_tags=["image-text-to-text"])
    )
    conflicting = ResearchRow.model_validate(
        _research("conflict-probe", pipeline_tag="text-generation", hf_tags=["vision-language"])
    )

    assert comparison_group(text_only) is ComparisonGroup.GENERATION_TEXT_ONLY
    assert comparison_group(vision) is ComparisonGroup.GENERATION_VISION
    assert comparison_group(conflicting) is ComparisonGroup.UNRESOLVED_MODALITY


def test_supplied_rows_group_without_guessing_modality() -> None:
    groups = {row.repo: comparison_group(row) for row in load_intake().research_rows}

    assert groups["google/embeddinggemma-2"] is ComparisonGroup.ENCODER
    assert groups["XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B"] is ComparisonGroup.GENERATION_VISION
    # Declared text-generation pipeline against vision-language tags: unresolved, not guessed.
    assert groups["XiaomiMiMo/MiMo-V2.6-Pro-RL"] is ComparisonGroup.UNRESOLVED_MODALITY
    # No pipeline tag and no vision evidence: unresolved, not text-only.
    assert groups["unsloth/DeepSeek-V4-Flash-0731-GGUF"] is ComparisonGroup.UNRESOLVED_MODALITY


# --- checkpoint audit classification ----------------------------------------


def test_audit_status_vocabulary_has_no_missing_state() -> None:
    assert {status.value for status in AuditStatus} == {"unchanged", "outdated", "unverified", "error"}


@pytest.mark.parametrize(
    ("result", "status", "reason"),
    [
        (FetchResult(status=200, payload={"sha": _sha("a")}), AuditStatus.UNCHANGED, None),
        (FetchResult(status=200, payload={"sha": _sha("b")}), AuditStatus.OUTDATED, None),
        (FetchResult(status=401, payload=None), AuditStatus.UNVERIFIED, "auth_required"),
        (FetchResult(status=403, payload=None), AuditStatus.UNVERIFIED, "inaccessible"),
        (FetchResult(status=404, payload=None), AuditStatus.UNVERIFIED, "http_404"),
        (FetchResult(status=429, payload=None), AuditStatus.UNVERIFIED, "http_429"),
        (FetchResult(status=503, payload=None), AuditStatus.UNVERIFIED, "http_5xx"),
        (FetchResult(status=None, payload=None, error="timeout"), AuditStatus.UNVERIFIED, "timeout"),
        (FetchResult(status=None, payload=None, error="network_error"), AuditStatus.UNVERIFIED, "network_error"),
        (FetchResult(status=200, payload={"sha": "abc|\nxyz"}), AuditStatus.ERROR, "malformed_sha"),
        (FetchResult(status=200, payload={}), AuditStatus.ERROR, "malformed_sha"),
        (FetchResult(status=200, payload=None), AuditStatus.ERROR, "malformed_json"),
        (FetchResult(status=418, payload=None), AuditStatus.ERROR, "unexpected_http_status"),
    ],
)
def test_audit_classification_distinguishes_auth_inaccessible_404_timeout_and_errors(
    result: FetchResult, status: AuditStatus, reason: str | None
) -> None:
    record = audit_one(
        kind="sealed",
        ident="row",
        repo="o/r",
        baseline_kind="pinned",
        baseline_sha=_sha("a"),
        result=result,
        fetched_utc=FIXED_UTC,
    )

    assert record.status is status
    assert record.reason == reason
    assert record.baseline_sha == _sha("a")
    assert record.fetched_utc == FIXED_UTC


def test_http_404_is_unverified_and_never_reported_as_missing() -> None:
    record = audit_one(
        kind="research",
        ident="row",
        repo="o/r",
        baseline_kind="observed",
        baseline_sha=_sha("a"),
        result=FetchResult(status=404, payload=None),
        fetched_utc=FIXED_UTC,
    )

    assert record.status is AuditStatus.UNVERIFIED
    assert record.reason == "http_404"
    assert "missing" not in {status.value for status in AuditStatus}


def test_malformed_remote_sha_is_never_echoed_into_latest() -> None:
    record = audit_one(
        kind="sealed",
        ident="row",
        repo="o/r",
        baseline_kind="pinned",
        baseline_sha=_sha("a"),
        result=FetchResult(status=200, payload={"sha": "abc|\nxyz"}),
        fetched_utc=FIXED_UTC,
    )

    assert record.latest_main_sha is None


def test_refresh_reports_latest_separately_and_leaves_pins_untouched() -> None:
    registry = load_bakeoff_candidates(default_registry_path())
    before = registry.model_dump()
    table = _baseline_table()
    for repo, latest in SUPPLIED_OUTDATED_LATEST.items():
        table[repo] = _ok(latest)

    report = build_report(refresh=True, fetch=_fake_fetch(table), clock=lambda: FIXED_UTC)

    assert report.refreshed is True
    assert report.audit is not None and len(report.audit) == 26
    sealed_audit = {rec.repo: rec for rec in report.audit if rec.kind == "sealed"}
    for repo, latest in SUPPLIED_OUTDATED_LATEST.items():
        assert sealed_audit[repo].status is AuditStatus.OUTDATED
        assert sealed_audit[repo].latest_main_sha == latest
        assert sealed_audit[repo].baseline_kind == "pinned"
    unchanged = [rec for rec in sealed_audit.values() if rec.repo not in SUPPLIED_OUTDATED_LATEST]
    assert len(unchanged) == 13
    assert all(rec.status is AuditStatus.UNCHANGED for rec in unchanged)
    assert load_bakeoff_candidates(default_registry_path()).model_dump() == before
    shown_pins = {row.id: row.revision for row in report.sealed}
    assert shown_pins == {entry.id: entry.revision for entry in registry.entries}


def test_research_observation_drift_is_reported_and_never_promotes() -> None:
    table = _baseline_table()
    table["deepseek-ai/DeepSeek-V4.1-Flash"] = _ok(_sha("b"))

    report = build_report(refresh=True, fetch=_fake_fetch(table), clock=lambda: FIXED_UTC)

    drift = next(rec for rec in report.audit or [] if rec.repo == "deepseek-ai/DeepSeek-V4.1-Flash")
    assert drift.kind == "research"
    assert drift.baseline_kind == "observed"
    assert drift.status is AuditStatus.OUTDATED
    row = next(row for row in report.research if row.repo == "deepseek-ai/DeepSeek-V4.1-Flash")
    assert row.runnable is False
    assert row.status == "pending_verification"
    assert row.generation_eligible is False


def test_unavailable_or_timeout_audit_is_unverified_and_timeouts_are_bounded() -> None:
    calls: list[float] = []

    def always_timeout(repo: str, timeout: float) -> FetchResult:
        calls.append(timeout)
        return FetchResult(status=None, payload=None, error="timeout")

    report = build_report(refresh=True, fetch=always_timeout, clock=lambda: FIXED_UTC)

    assert report.audit is not None and len(report.audit) == 26
    assert len(calls) == 26
    assert all(0 < timeout <= 30 for timeout in calls)
    assert all(rec.status is AuditStatus.UNVERIFIED and rec.reason == "timeout" for rec in report.audit)
    assert all(rec.latest_main_sha is None for rec in report.audit)


# --- default fetch: no credentials, bounded, error mapping ------------------


class _FakeResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def read(self, _size: int = -1) -> bytes:
        return self._body


def test_default_fetch_sends_no_credentials_and_uses_a_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float | None = None) -> _FakeResponse:
        seen["headers"] = {key.lower(): value for key, value in request.header_items()}
        seen["timeout"] = timeout
        seen["url"] = request.full_url
        return _FakeResponse(json.dumps({"sha": _sha("a")}).encode("utf-8"))

    monkeypatch.setenv("HF_TOKEN", "hf_secret_must_not_leak")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = default_fetch("google/embeddinggemma-2")

    assert result.status == 200
    assert result.payload == {"sha": _sha("a")}
    assert seen["url"] == "https://huggingface.co/api/models/google/embeddinggemma-2"
    assert "authorization" not in seen["headers"]
    assert all("hf_secret_must_not_leak" not in value for value in seen["headers"].values())
    assert seen["timeout"] == DEFAULT_TIMEOUT_S
    assert 0 < seen["timeout"] <= 30


@pytest.mark.parametrize(
    ("raised", "status", "error"),
    [
        (urllib.error.HTTPError("https://huggingface.co/x", 404, "Not Found", {}, None), 404, None),
        (urllib.error.URLError(TimeoutError("timed out")), None, "timeout"),
        (urllib.error.URLError(ConnectionRefusedError("refused")), None, "network_error"),
        (TimeoutError("read timed out"), None, "timeout"),
    ],
)
def test_default_fetch_maps_transport_failures_without_claiming_absence(
    monkeypatch: pytest.MonkeyPatch,
    raised: BaseException,
    status: int | None,
    error: str | None,
) -> None:
    def fake_urlopen(*_args: Any, **_kwargs: Any) -> None:
        raise raised

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = default_fetch("o/r")

    assert result.status == status
    assert result.error == error


# --- --output safety and sealed-roster immutability -------------------------


def test_refresh_with_output_writes_only_the_requested_file(tmp_path: Path) -> None:
    registry_path = default_registry_path()
    registry_before = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    intake_before = hashlib.sha256(DEFAULT_INTAKE_PATH.read_bytes()).hexdigest()
    out = tmp_path / "intake.md"

    code = main(["--refresh", "--output", str(out)], fetch=_fake_fetch(_baseline_table()))

    assert code == 0
    assert "Checkpoint audit" in out.read_text(encoding="utf-8")
    assert hashlib.sha256(registry_path.read_bytes()).hexdigest() == registry_before
    assert hashlib.sha256(DEFAULT_INTAKE_PATH.read_bytes()).hexdigest() == intake_before


@pytest.mark.parametrize("protected", [default_registry_path(), DEFAULT_INTAKE_PATH])
def test_output_cannot_overwrite_the_sealed_registry_or_the_intake_file(protected: Path) -> None:
    before = protected.read_bytes()
    code = main(["--output", str(protected)])

    assert code == 2
    assert protected.read_bytes() == before


# --- Markdown safety --------------------------------------------------------


def test_md_cell_escapes_pipes_and_collapses_newlines() -> None:
    assert md_cell("a|b\nc\r\nd") == "a\\|b c d"
    assert md_cell(None) == "n/a"


def test_markdown_tables_stay_well_formed_for_hostile_remote_metadata() -> None:
    registry = load_bakeoff_candidates(default_registry_path())
    table = _baseline_table()
    hostile_repo = registry.entries[0].repo
    table[hostile_repo] = _ok(
        registry.entries[0].revision,
        pipeline_tag="image|text\nbreak",
        license_id="MIT | evil\nrow",
    )

    report = build_report(refresh=True, fetch=_fake_fetch(table), clock=lambda: FIXED_UTC)
    text = render_markdown(report)

    assert "MIT \\| evil row" in text
    blocks = _table_blocks(text)
    assert blocks
    for block in blocks:
        assert len({len(_unescaped_pipes(line)) for line in block}) == 1


# --- JSON output schema -----------------------------------------------------


def test_json_output_round_trips_as_the_report_schema(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--format", "json"]) == 0
    report = IntakeReport.model_validate_json(capsys.readouterr().out)

    assert report.schema_id == "bakeoff-intake-report/v1"
    assert len(report.sealed) == 16
    assert len(report.research) == 10


# --- second-dispatch regressions (synthetic HTTP / filesystem failures) -----


def test_supplied_unsloth_docs_are_recovered_without_model_admission() -> None:
    expected = {
        "https://unsloth.ai/docs",
        "https://unsloth.ai/docs/models/qwen3.8",
        "https://unsloth.ai/docs/models/muse-glimmer",
        "https://unsloth.ai/docs/models/qwen3.8-next",
    }
    report = build_report()
    assert {link.url for link in report.docs_links} == expected, "supplied docs links were lost"
    assert len(report.docs_links) == 4
    assert all(link.kind == "docs" and link.label for link in report.docs_links)
    for url in expected:
        assert url in render_markdown(report)
        assert url in report.model_dump_json()
    assert len(report.sealed) == 16
    assert len(report.research) == 10
    assert generation_roster(load_intake()) == []
    assert all(row.status == "pending_verification" and row.runnable is False for row in report.research)


class _HTTPBytesSocket:
    """Synthetic wire bytes; HTTPResponse itself parses and reads the response."""

    def __init__(self, wire: bytes) -> None:
        self.wire = wire

    def makefile(self, *_args: Any, **_kwargs: Any) -> io.BytesIO:
        return io.BytesIO(self.wire)


def _http_response(body: bytes, *, incomplete: bool = False) -> http.client.HTTPResponse:
    if incomplete:
        # A declared 100-byte chunk with only 7 bytes exercises the real read exception.
        wire = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n64\r\npartial"
    else:
        wire = b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    response = http.client.HTTPResponse(_HTTPBytesSocket(wire))
    response.begin()
    return response


@pytest.mark.parametrize("output_format", ["json", "markdown"])
@pytest.mark.parametrize(
    ("fault", "status", "reason"),
    [
        ("incomplete", "unverified", "network_error"),
        ("pipeline_high", "error", "malformed_json"),
        ("pipeline_low", "error", "malformed_json"),
        ("license_high", "error", "malformed_json"),
        ("license_low", "error", "malformed_json"),
        ("array", "error", "malformed_json"),
        ("null", "error", "malformed_json"),
        ("invalid_utf8", "error", "malformed_json"),
        ("bad_sha", "error", "malformed_sha"),
    ],
)
def test_real_http_failures_keep_every_audit_row_and_both_renderers_usable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    output_format: str,
    fault: str,
    status: str,
    reason: str,
) -> None:
    table = _baseline_table()
    repos = list(table)
    calls: list[str] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> http.client.HTTPResponse:
        repo = request.full_url.removeprefix("https://huggingface.co/api/models/")
        calls.append(repo)
        assert timeout == DEFAULT_TIMEOUT_S
        payload = dict(table[repo].payload or {})
        payload["pipeline_tag"] = "image-text-to-text"
        payload["cardData"] = {"license": "mit"}
        if repo == repos[0]:
            if fault.startswith("pipeline_"):
                payload["pipeline_tag"] = "\ud800" if fault.endswith("high") else "\udfff"
            elif fault.startswith("license_"):
                payload["cardData"] = {"license": "\ud800" if fault.endswith("high") else "\udfff"}
            elif fault == "bad_sha":
                payload["sha"] = []
        body = json.dumps(payload).encode("utf-8")
        if repo == repos[0]:
            body = {"array": b"[]", "null": b"null", "invalid_utf8": b"\xff"}.get(fault, body)
        return _http_response(body, incomplete=repo == repos[0] and fault == "incomplete")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    out = tmp_path / f"audit.{output_format}"
    assert main(["--refresh", "--format", output_format, "--output", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert calls == repos
    assert len(calls) == 26
    if output_format == "json":
        report = IntakeReport.model_validate_json(text)
        assert report.audit is not None
        assert len(report.audit) == 26
        assert (report.audit[0].status, report.audit[0].reason) == (status, reason)
        assert report.audit[0].latest_main_sha is None
        assert all(row.status is AuditStatus.UNCHANGED for row in report.audit[1:])
    else:
        audit_lines = text.split("## Checkpoint audit", 1)[1]
        assert f"| {status} | {reason} |" in audit_lines
        assert audit_lines.count("| unchanged |") == 25
    assert "partial" not in text
    assert "\\ud800" not in text and "\\udfff" not in text
    text.encode("utf-8")


def test_valid_unicode_metadata_is_preserved_in_both_renderers(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"sha": _sha("a"), "pipeline_tag": "vision-\U0001f30d", "cardData": {"license": "许可"}}
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *_args, **_kwargs: _http_response(json.dumps(payload).encode())
    )
    report = build_report(refresh=True, clock=lambda: FIXED_UTC)
    assert report.audit is not None and len(report.audit) == 26
    assert all(row.remote_pipeline_tag == "vision-\U0001f30d" and row.remote_license == "许可" for row in report.audit)
    assert "vision-\U0001f30d" in report.model_dump_json()
    assert "许可" in render_markdown(report)


@pytest.mark.parametrize("field", ["pipeline_tag", "license"])
def test_injected_fetch_cannot_bypass_unicode_validation(field: str) -> None:
    table = _baseline_table()
    repo = next(iter(table))
    payload = dict(table[repo].payload or {})
    if field == "license":
        payload["cardData"] = {"license": "\ud800"}
    else:
        payload[field] = "\ud800"
    table[repo] = FetchResult(status=200, payload=payload)
    report = build_report(refresh=True, fetch=_fake_fetch(table), clock=lambda: FIXED_UTC)
    # Initial RED prediction: PydanticSerializationError wrapping UnicodeEncodeError.
    IntakeReport.model_validate_json(report.model_dump_json())
    render_markdown(report).encode("utf-8")
    assert report.audit is not None and len(report.audit) == 26
    assert report.audit[0].status is AuditStatus.ERROR
    assert report.audit[0].reason == "malformed_json"
    assert all(row.status is AuditStatus.UNCHANGED for row in report.audit[1:])


@pytest.mark.parametrize("output_format", ["json", "markdown"])
def test_cli_missing_output_parent_is_a_concise_error(tmp_path: Path, output_format: str) -> None:
    out = tmp_path / "missing-parent" / "audit.json"
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.eval_harness.bakeoff_intake", "--format", output_format, "--output", str(out)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 1
    assert proc.stderr == "FAIL: cannot write report\n", "report write escaped the CLI error boundary"
    assert proc.stdout == ""
    assert not out.exists()


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_failed_output_preserves_prior_report_and_cleans_temporary_sibling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    out = tmp_path / "audit.json"
    prior = b"previous complete audit\n"
    out.write_bytes(prior)
    real_open = io.open
    probes: list[str] = []

    class FailingWriter:
        def __init__(self, stream: Any) -> None:
            self.stream = stream

        def __getattr__(self, name: str) -> Any:
            return getattr(self.stream, name)

        def __enter__(self) -> FailingWriter:
            return self

        def __exit__(self, *_args: object) -> None:
            self.stream.close()

        def write(self, text: str) -> int:
            probes.append("write")
            self.stream.write(text[:20])
            self.stream.flush()
            raise OSError("synthetic-full-disk /secret/path hf_secret")

    def open_with_failure(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        stream = real_open(file, mode, *args, **kwargs)
        if failure == "write" and "w" in mode and "b" not in mode:
            return FailingWriter(stream)
        return stream

    def replace_with_failure(source: Any, target: Any) -> None:
        probes.append("replace")
        assert Path(target) == out
        assert Path(source).parent == out.parent
        assert Path(source) != out
        IntakeReport.model_validate_json(Path(source).read_bytes())
        assert out.read_bytes() == prior
        raise OSError("synthetic-replace-denied /secret/path hf_secret")

    monkeypatch.setattr(io, "open", open_with_failure)
    if failure == "replace":
        monkeypatch.setattr(os, "replace", replace_with_failure)
    code = main(["--format", "json", "--output", str(out)])
    assert code == 1, "failed atomic report emission must return 1"
    assert probes == [failure]
    assert out.read_bytes() == prior
    assert set(tmp_path.iterdir()) == {out}
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "FAIL: cannot write report\n"


def test_successful_output_atomically_replaces_prior_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "audit.json"
    prior = b"previous complete audit\n"
    out.write_bytes(prior)
    real_replace = os.replace
    probes: list[Path] = []

    def observe_replace(source: Any, target: Any) -> None:
        temporary = Path(source)
        assert temporary.parent == out.parent and temporary != out
        assert Path(target) == out
        assert out.read_bytes() == prior
        IntakeReport.model_validate_json(temporary.read_bytes())
        probes.append(temporary)
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", observe_replace)
    assert main(["--format", "json", "--output", str(out)]) == 0
    assert len(probes) == 1, "report must replace from a complete temporary sibling"
    assert len(IntakeReport.model_validate_json(out.read_bytes()).sealed) == 16
    assert set(tmp_path.iterdir()) == {out}
