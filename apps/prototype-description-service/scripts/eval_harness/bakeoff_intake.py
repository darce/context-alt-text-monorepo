"""DESCBAKE-1 B1: additive bake-off candidate intake and checkpoint audit.

Two inputs feed one report, and neither is written:

* ``bakeoff_candidates.yaml`` is the sealed roster. It is read through
  :func:`load_bakeoff_candidates`, and its pinned revisions are immutable.
* ``bakeoff_intake.json`` holds research rows observed from public Hugging
  Face metadata. Each row is ``pending_verification`` and ``runnable: false``,
  so none can become a bake-off candidate or enter a generation roster.

``--refresh`` is the only network path. It queries public model metadata
anonymously with a bounded timeout and reports the latest ``main`` sha beside
the pinned sha (sealed rows) or the observed sha (research rows). It never
repins. An HTTP error is reported as ``unverified`` with a reason; it is never
reported as proof that a repo is missing.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from scripts.eval_harness.bakeoff_candidates import (
    BakeoffCandidateRegistry,
    CandidateEntry,
    CandidateRole,
    RegistryError,
    default_registry_path,
    load_bakeoff_candidates,
)

INTAKE_SCHEMA = "bakeoff-intake/v1"
REPORT_SCHEMA = "bakeoff-intake-report/v1"
DEFAULT_INTAKE_PATH = Path(__file__).with_name("bakeoff_intake.json")
HF_WEB_BASE = "https://huggingface.co/"
HF_API_BASE = "https://huggingface.co/api/models/"
DEFAULT_TIMEOUT_S = 10.0
MAX_METADATA_BYTES = 8 * 1024 * 1024
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# Tags that name vision input. A declared text-generation pipeline alongside
# any of these is a conflict, so the row stays unresolved instead of guessed.
_VISION_TAGS = frozenset({"vision", "vision-language", "multimodal", "image-text-to-text"})
_USER_AGENT = "bakeoff-intake-audit/1 (public metadata; no credentials)"


class IntakeError(Exception):
    """Research intake file failed validation."""


class AuditStatus(StrEnum):
    """Outcome of comparing a fetched latest sha with its baseline."""

    UNCHANGED = "unchanged"
    OUTDATED = "outdated"
    UNVERIFIED = "unverified"
    ERROR = "error"


class AuditReason(StrEnum):
    """Why a fetch did not yield a comparable sha. None of these is absence proof."""

    AUTH_REQUIRED = "auth_required"
    INACCESSIBLE = "inaccessible"
    HTTP_404 = "http_404"
    RATE_LIMITED = "http_429"
    SERVER_ERROR = "http_5xx"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    MALFORMED_JSON = "malformed_json"
    MALFORMED_SHA = "malformed_sha"
    OVERSIZED = "oversized_response"
    UNEXPECTED_HTTP_STATUS = "unexpected_http_status"


class ResearchRole(StrEnum):
    GENERATOR = "generator"
    ENCODER = "encoder"


class ComparisonGroup(StrEnum):
    """Rows in different groups are never placed in one comparison."""

    ENCODER = "encoder"
    GENERATION_VISION = "generation_vision"
    GENERATION_TEXT_ONLY = "generation_text_only"
    UNRESOLVED_MODALITY = "unresolved_modality"


@dataclass(frozen=True)
class FetchResult:
    """One metadata fetch. ``error`` is set when no HTTP response was usable."""

    status: int | None
    payload: Mapping[str, Any] | None
    error: str | None = None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DocsLink(_Strict):
    """A documentation link. Never a model row and never counted as one."""

    label: str
    url: str
    kind: Literal["docs"]


class Observation(_Strict):
    schema_id: Literal["public-model-research/v1"] = Field(alias="schema")
    fetched_utc: str
    network_authentication: str
    scope: str


class ArtifactFile(_Strict):
    path: str
    size_bytes: int = Field(ge=0)


class ResearchRow(_Strict):
    id: str
    repo: str
    source_url: str
    role: ResearchRole
    pipeline_tag: str | None
    license: str | None
    hf_tags: list[str]
    observed_sha: str
    observed_fetched_utc: str
    observed_http_status: int
    observed_source: str
    gguf_variants: list[str] = Field(default_factory=list)
    auxiliary_gguf: list[str] = Field(default_factory=list)
    projectors: list[ArtifactFile] = Field(default_factory=list)
    listed_weight_bytes_total: int | None = None
    status: Literal["pending_verification"]
    runnable: Literal[False]
    allowed_use: str
    notes: str | None = None

    @model_validator(mode="after")
    def _exact_hf_urls_and_pin_shape(self) -> ResearchRow:
        if self.source_url != model_page_url(self.repo):
            raise ValueError(f"{self.id}: source_url must be the exact model page {model_page_url(self.repo)}")
        if self.observed_source != model_api_url(self.repo):
            raise ValueError(f"{self.id}: observed_source must be {model_api_url(self.repo)}")
        if not _SHA_RE.fullmatch(self.observed_sha):
            raise ValueError(f"{self.id}: observed_sha must be a 40-char lowercase hex sha")
        return self


class IntakeDocument(_Strict):
    schema_id: Literal["bakeoff-intake/v1"] = Field(alias="schema")
    description: str
    observation: Observation
    docs_links: list[DocsLink] = Field(default_factory=list)
    research_rows: list[ResearchRow]

    @model_validator(mode="after")
    def _unique_ids_and_repos(self) -> IntakeDocument:
        ids = [row.id for row in self.research_rows]
        repos = [row.repo for row in self.research_rows]
        if len(set(ids)) != len(ids):
            raise ValueError("research row ids must be unique")
        if len(set(repos)) != len(repos):
            raise ValueError("research repos must be unique")
        return self


class SealedView(_Strict):
    id: str
    role: str
    competing: bool
    repo: str
    revision: str
    quant: str
    artifact: str
    artifact_gb: float
    mmproj: str | None
    license: str
    prompt_template: str
    stack: str
    tiers: list[str]


class ResearchView(ResearchRow):
    comparison_group: ComparisonGroup
    generation_eligible: bool


class AuditRecord(_Strict):
    kind: Literal["sealed", "research"]
    id: str
    repo: str
    source: str
    baseline_kind: Literal["pinned", "observed"]
    baseline_sha: str
    latest_main_sha: str | None
    status: AuditStatus
    reason: AuditReason | None
    http_status: int | None
    remote_pipeline_tag: str | None
    remote_license: str | None
    fetched_utc: str


class IntakeReport(_Strict):
    schema_id: Literal["bakeoff-intake-report/v1"] = Field(alias="schema")
    generated_utc: str
    refreshed: bool
    sealed: list[SealedView]
    research: list[ResearchView]
    docs_links: list[DocsLink]
    audit: list[AuditRecord] | None


def model_page_url(repo: str) -> str:
    return f"{HF_WEB_BASE}{repo}"


def model_api_url(repo: str) -> str:
    return f"{HF_API_BASE}{repo}"


def load_intake(path: str | Path | None = None) -> IntakeDocument:
    """Load and validate the research intake. Raises :class:`IntakeError`."""
    intake_path = Path(path) if path is not None else DEFAULT_INTAKE_PATH
    try:
        raw = json.loads(intake_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IntakeError(f"research intake not found: {intake_path.name}") from exc
    except (OSError, ValueError) as exc:
        raise IntakeError(f"research intake unreadable or malformed JSON: {intake_path.name}") from exc
    try:
        return IntakeDocument.model_validate(raw)
    except ValidationError as exc:
        raise IntakeError(f"research intake schema violation: {exc}") from exc


def comparison_group(row: ResearchRow) -> ComparisonGroup:
    """Place a research row in the one comparison group its evidence supports."""
    if row.role is ResearchRole.ENCODER:
        return ComparisonGroup.ENCODER
    tags = set(row.hf_tags)
    vision = row.pipeline_tag == "image-text-to-text" or bool(row.projectors) or bool(tags & _VISION_TAGS)
    text = row.pipeline_tag == "text-generation"
    if vision and text:
        return ComparisonGroup.UNRESOLVED_MODALITY
    if vision:
        return ComparisonGroup.GENERATION_VISION
    if text:
        return ComparisonGroup.GENERATION_TEXT_ONLY
    return ComparisonGroup.UNRESOLVED_MODALITY


def generation_eligible(row: ResearchRow) -> bool:
    """Research rows never enter a generation roster from this intake.

    ``runnable`` is ``False`` by schema. Promotion into the sealed roster is a
    separate reviewed change, so this always answers ``False`` for intake rows.
    """
    return row.runnable and row.role is ResearchRole.GENERATOR


def generation_roster(intake: IntakeDocument) -> list[str]:
    return [row.id for row in intake.research_rows if generation_eligible(row)]


def runnable_candidate_ids(registry: BakeoffCandidateRegistry) -> list[str]:
    """Sealed competing candidates: the only rows a bake-off run may execute."""
    return [entry.id for entry in registry.entries if entry.role is CandidateRole.CANDIDATE and entry.competing]


def default_fetch(repo: str, timeout: float = DEFAULT_TIMEOUT_S) -> FetchResult:
    """Anonymous public metadata fetch. Never reads a token or credential."""
    request = urllib.request.Request(
        model_api_url(repo),
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https host
            status = int(response.status)
            body = response.read(MAX_METADATA_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return FetchResult(status=exc.code, payload=None)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return FetchResult(status=None, payload=None, error="timeout")
        return FetchResult(status=None, payload=None, error="network_error")
    except TimeoutError:
        return FetchResult(status=None, payload=None, error="timeout")
    except (OSError, http.client.IncompleteRead):
        return FetchResult(status=None, payload=None, error="network_error")
    if len(body) > MAX_METADATA_BYTES:
        return FetchResult(status=status, payload=None, error="oversized")
    try:
        payload = json.loads(body)
    except ValueError:
        return FetchResult(status=status, payload=None)
    return FetchResult(status=status, payload=payload if isinstance(payload, dict) else None)


def _text_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    # JSON escapes can decode to lone surrogates that neither renderer can emit.
    value.encode("utf-8")
    return value


def audit_one(
    *,
    kind: Literal["sealed", "research"],
    ident: str,
    repo: str,
    baseline_kind: Literal["pinned", "observed"],
    baseline_sha: str,
    result: FetchResult,
    fetched_utc: str,
) -> AuditRecord:
    """Classify one fetch against its baseline. Pure: no I/O and no clock."""
    base: dict[str, Any] = {
        "kind": kind,
        "id": ident,
        "repo": repo,
        "source": model_api_url(repo),
        "baseline_kind": baseline_kind,
        "baseline_sha": baseline_sha,
        "fetched_utc": fetched_utc,
        "http_status": result.status,
    }

    def record(
        status: AuditStatus,
        reason: AuditReason | None = None,
        *,
        latest: str | None = None,
        pipeline: str | None = None,
        license_id: str | None = None,
    ) -> AuditRecord:
        return AuditRecord(
            **base,
            status=status,
            reason=reason,
            latest_main_sha=latest,
            remote_pipeline_tag=pipeline,
            remote_license=license_id,
        )

    if result.error == "timeout":
        return record(AuditStatus.UNVERIFIED, AuditReason.TIMEOUT)
    if result.error == "network_error":
        return record(AuditStatus.UNVERIFIED, AuditReason.NETWORK_ERROR)
    if result.error is not None:
        return record(AuditStatus.ERROR, AuditReason.OVERSIZED)

    http_status = result.status
    unverified = {
        401: AuditReason.AUTH_REQUIRED,
        403: AuditReason.INACCESSIBLE,
        404: AuditReason.HTTP_404,
        429: AuditReason.RATE_LIMITED,
    }
    if http_status in unverified:
        return record(AuditStatus.UNVERIFIED, unverified[http_status])
    if http_status is not None and 500 <= http_status <= 599:
        return record(AuditStatus.UNVERIFIED, AuditReason.SERVER_ERROR)
    if http_status != 200:
        return record(AuditStatus.ERROR, AuditReason.UNEXPECTED_HTTP_STATUS)

    payload = result.payload
    if payload is None:
        return record(AuditStatus.ERROR, AuditReason.MALFORMED_JSON)
    try:
        pipeline = _text_or_none(payload.get("pipeline_tag"))
        card = payload.get("cardData")
        license_id = _text_or_none(card.get("license")) if isinstance(card, dict) else None
    except UnicodeEncodeError:
        return record(AuditStatus.ERROR, AuditReason.MALFORMED_JSON)
    sha = payload.get("sha")
    if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha.strip().lower()):
        return record(AuditStatus.ERROR, AuditReason.MALFORMED_SHA, pipeline=pipeline, license_id=license_id)
    latest = sha.strip().lower()
    status = AuditStatus.UNCHANGED if latest == baseline_sha else AuditStatus.OUTDATED
    return record(status, latest=latest, pipeline=pipeline, license_id=license_id)


def _sealed_view(entry: CandidateEntry) -> SealedView:
    return SealedView(
        id=entry.id,
        role=entry.role.value,
        competing=entry.competing,
        repo=entry.repo,
        revision=entry.revision,
        quant=entry.quant,
        artifact=entry.artifact,
        artifact_gb=entry.artifact_gb,
        mmproj=entry.recipe.mmproj,
        license=entry.license,
        prompt_template=entry.prompt_template,
        stack=entry.recipe.stack.value,
        tiers=[tier.value for tier in entry.tiers],
    )


def _research_view(row: ResearchRow) -> ResearchView:
    return ResearchView(
        **row.model_dump(),
        comparison_group=comparison_group(row),
        generation_eligible=generation_eligible(row),
    )


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_report(
    *,
    registry_path: str | Path | None = None,
    intake_path: str | Path | None = None,
    refresh: bool = False,
    fetch: Callable[[str, float], FetchResult] | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    clock: Callable[[], str] | None = None,
) -> IntakeReport:
    """Build the intake report. Only ``refresh=True`` touches the network."""
    registry = load_bakeoff_candidates(registry_path)
    intake = load_intake(intake_path)
    now = clock if clock is not None else _utc_now

    audit: list[AuditRecord] | None = None
    if refresh:
        fetcher = fetch if fetch is not None else default_fetch
        audit = [
            audit_one(
                kind="sealed",
                ident=entry.id,
                repo=entry.repo,
                baseline_kind="pinned",
                baseline_sha=entry.revision,
                result=fetcher(entry.repo, timeout),
                fetched_utc=now(),
            )
            for entry in registry.entries
        ]
        audit += [
            audit_one(
                kind="research",
                ident=row.id,
                repo=row.repo,
                baseline_kind="observed",
                baseline_sha=row.observed_sha,
                result=fetcher(row.repo, timeout),
                fetched_utc=now(),
            )
            for row in intake.research_rows
        ]

    return IntakeReport(
        schema_id=REPORT_SCHEMA,
        generated_utc=now(),
        refreshed=refresh,
        sealed=[_sealed_view(entry) for entry in registry.entries],
        research=[_research_view(row) for row in intake.research_rows],
        docs_links=intake.docs_links,
        audit=audit,
    )


def md_cell(value: object) -> str:
    """Render one Markdown table cell. Remote text may hold pipes or newlines."""
    if value is None:
        return "n/a"
    text = " ".join(str(value).split())
    return text.replace("\\", "\\\\").replace("|", "\\|")


def _row(*cells: object) -> str:
    return "| " + " | ".join(md_cell(cell) for cell in cells) + " |"


def _render_sealed(report: IntakeReport) -> list[str]:
    lines = [
        "## Sealed roster (read-only; pinned identity)",
        "",
        "| id | role | competing | repo | pinned revision | quant | artifact | artifact GB | mmproj | tiers | license | stack |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in report.sealed:
        lines.append(
            _row(
                row.id,
                row.role,
                "yes" if row.competing else "no",
                row.repo,
                row.revision,
                row.quant,
                row.artifact,
                row.artifact_gb,
                row.mmproj,
                ", ".join(row.tiers),
                row.license,
                row.stack,
            )
        )
    return lines


def _render_research(report: IntakeReport) -> list[str]:
    lines = [
        "## Research intake (pending verification; never runnable)",
        "",
        "Rows in different comparison groups are never compared in one table.",
        "",
    ]
    for group in ComparisonGroup:
        rows = [row for row in report.research if row.comparison_group is group]
        if not rows:
            continue
        lines += [
            f"### Comparison group: {group.value}",
            "",
            "| id | repo | role | pipeline tag | license | observed main sha | projectors | status | runnable | source | allowed use |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for row in rows:
            projectors = [f"{p.path} ({p.size_bytes} B)" for p in row.projectors]
            lines.append(
                _row(
                    row.id,
                    row.repo,
                    row.role.value,
                    row.pipeline_tag,
                    row.license,
                    row.observed_sha,
                    "; ".join(projectors) if projectors else "none listed",
                    row.status,
                    "yes" if row.runnable else "no",
                    row.source_url,
                    row.allowed_use,
                )
            )
        lines.append("")
    if report.docs_links:
        lines += ["### Docs links (source links only; not models)", ""]
        lines += [f"- {md_cell(link.label)}: {md_cell(link.url)}" for link in report.docs_links]
        lines.append("")
    return lines


def _render_audit(report: IntakeReport) -> list[str]:
    lines = ["## Checkpoint audit (latest main sha vs baseline)", ""]
    if report.audit is None:
        lines += ["Not performed. Run with --refresh to query public Hugging Face metadata.", ""]
        return lines
    lines += [
        "| kind | id | repo | baseline kind | baseline sha | latest main sha | status | reason | http | remote pipeline tag | remote license | fetched UTC | source |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rec in report.audit:
        lines.append(
            _row(
                rec.kind,
                rec.id,
                rec.repo,
                rec.baseline_kind,
                rec.baseline_sha,
                rec.latest_main_sha,
                rec.status.value,
                rec.reason,
                rec.http_status,
                rec.remote_pipeline_tag,
                rec.remote_license,
                rec.fetched_utc,
                rec.source,
            )
        )
    lines.append("")
    return lines


def render_markdown(report: IntakeReport) -> str:
    refresh_note = "yes" if report.refreshed else "no (offline)"
    lines = [
        "# Bake-off candidate intake",
        "",
        f"Generated (UTC): {md_cell(report.generated_utc)}. Refresh: {refresh_note}.",
        "",
        *_render_sealed(report),
        "",
        *_render_research(report),
        *_render_audit(report),
    ]
    return "\n".join(lines) + "\n"


def _is_protected(path: Path) -> bool:
    protected = {default_registry_path().resolve(), DEFAULT_INTAKE_PATH.resolve()}
    return path.resolve() in protected


def _write_report(path: Path, text: str) -> None:
    """Replace a prior report only after a complete sibling has been closed."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(
    argv: list[str] | None = None,
    *,
    fetch: Callable[[str, float], FetchResult] | None = None,
) -> int:
    """Print the intake (Markdown or JSON), optionally refreshing public metadata."""
    parser = argparse.ArgumentParser(description="Candidate intake and checkpoint audit for the VLM-6 bake-off")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="explicit network: query public Hugging Face metadata (anonymous, bounded timeout)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write here instead of stdout; never the sealed registry or the intake file",
    )
    args = parser.parse_args(argv)
    if args.output is not None and _is_protected(args.output):
        print("FAIL: --output must not name the sealed registry or the research intake", file=sys.stderr)
        return 2
    try:
        report = build_report(refresh=args.refresh, fetch=fetch)
    except (RegistryError, IntakeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        text = report.model_dump_json(indent=2, by_alias=True) + "\n"
    else:
        text = render_markdown(report)
    if args.output is None:
        sys.stdout.write(text)
    else:
        try:
            _write_report(args.output, text)
        except OSError:
            print("FAIL: cannot write report", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
