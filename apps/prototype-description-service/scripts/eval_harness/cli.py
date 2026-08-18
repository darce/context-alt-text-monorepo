"""Eval-harness CLI: fetch / score / run / seed-roster / seed-scenes.

Split Phase: ``fetch`` walks the golden manifest against the remote OCI service
(concurrency 1) and writes a run record; ``score`` is pure and offline;
``run`` composes both. ``seed-roster`` is the one-time idempotent eval-tenant
setup. Live subcommands require ``ACX_EVAL_LIVE=1`` plus ``ACX_EVAL_BASE_URL``
and ``ACX_EVAL_API_KEY`` (the dedicated eval-tenant key — never the demo
tenant's) so unit tests and CI can never accidentally hit the service.

rg-007: one failing image never halts the run (per-item isolation), but
``stall_limit`` consecutive failures aborts with a non-zero exit.

LLM-judge tier: ``--llm-judge`` is accepted but is a stub (assessment §6c
tiers 3-4 are out of the MVP); it fails fast with a clear message.

Retention: run records/reports land in ``scripts/eval_harness/out/``
(git-ignored) and are pruned keep-last-N (default 10); the ignore-list file is
never pruned. Curated baselines are promoted to ``docs/tasks/vlm/`` by hand.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import Any, NamedTuple, NoReturn

from scene.config.profiles import PROFILE_SPECS, DescriptionProfile
from scene.domain.description import DescriptionAdapterKind
from shared.secrets import get_secret_provider

from .face_bakeoff import (
    CANDIDATE_MODEL_ID,
    build_candidate_leg,
    build_occlusion_twin_pairs,
    build_pinned_cache_detector,
    walk_face_run_record,
)
from .face_bakeoff import (
    BoundedStallError as FaceBoundedStallError,
)
from .face_run_record import FaceRunRecordError, validate_face_run_record
from .manifest import GoldenManifest, ManifestError, _resolve_image, load_manifest
from .perf_leg import PerfLegError
from .remote_client import RemoteClientError, RemoteSceneClient
from .report import (
    WRONG_NAME_RATE_FLOOR,
    Audience,
    IdentityOrdering,
    ReportError,
    ScoreVerdict,
    _total_wrong_name_count,
    build_face_reports,
    build_reports,
    face_wrong_name_rate,
    fabricated_fact_is_vacuous,  # noqa: F401 — shared S2-01 predicate (score/compare)
    identity_names,  # noqa: F401 — re-export for external callers; report owns it (VLM6-RH-07)
    occlusion_inputs_from_record,
    score_run_record,
    score_vacuous_category_labels,
)
from .report import (
    _markdown as _score_report_markdown,
)
from .schema import SCHEMA, DocKind
from .seed_roster import seed, seed_scenes

DEFAULT_KEEP = 10
DEFAULT_STALL_LIMIT = 5
# Refused detection/identification is not clean eval evidence. CI that checks
# only process status must see a non-zero exit unless the caller opts in.
REFUSED_METRIC_EXIT_CODE = 3


class RefusedMetric(StrEnum):
    """Named honesty fields an operator may consent to skip (sr-007)."""

    DETECTION = "detection"
    IDENTIFICATION = "identification"


# Bare ``--allow-refused`` is strictly equivalent to naming every member.
ALLOW_REFUSED_ALL = "*"

OUT_DIR = Path(__file__).parent / "out"
IGNORE_LIST_NAME = "ignore-list.json"
_RUN_STAMP_RE = re.compile(r"^run-(\d{8}-\d{6})")
# Must-Right caption hard gate mode (VLM-6 S2A F1b-2 / F1-12). enforce = exit
# non-zero when any must_right image fails; skip = bypass that gate only.
# Seeded/harness-shakedown runs are exempt by explicit operator declaration
# (--rubric-gate skip), not by adapter/model_id inference (rg-009) and not by
# a derived mean_gated threshold (garbage captions share the seeded mean shape
# on real golden.json — F1-11 conjunction was false-green on plain garbage).
RUBRIC_GATE_ENFORCE = "enforce"
RUBRIC_GATE_SKIP = "skip"
# F1-4 / r08116b50: hard-key gate inputs. Soft defaults (.get(..., 0) / is False)
# fail open when report.py renames a field — the gate cannot go red (TEST-15).
# ---------------------------------------------------------------------------
# Class-unique score* gate prefixes (VLM6-R2-F-01 / F-03 / rg-006 / rg-015).
# One constant per exit class — caption and face share the same prefix so a
# single log grep catches both paths. Distinguishing tokens go in the suffix.
# Documented in README.md § "Score non-zero exit prefixes"; the drift test
# ``test_score_gate_prefixes_documented_in_readme`` fails if a constant is
# added without a README entry.
# ---------------------------------------------------------------------------
SCORE_GATE_PREFIX_SCHEMA_ERROR = "score schema error:"
SCORE_GATE_PREFIX_ABORTED_RECORD = "score aborted-record gate:"
SCORE_GATE_PREFIX_ZERO_SCORED = "score zero-scored gate:"
SCORE_GATE_PREFIX_FAILED_ITEMS = "score failed-items gate:"
SCORE_GATE_PREFIX_TRUNCATION = "score truncation gate:"
SCORE_GATE_PREFIX_MANIFEST_MISMATCH = "score manifest-mismatch gate:"
SCORE_GATE_PREFIX_MANIFEST_DRIFT = "score manifest-drift gate:"
SCORE_GATE_PREFIX_MANIFEST_RELABEL = "score manifest-relabel gate:"
SCORE_GATE_PREFIX_EMPTY_RUBRIC = "score empty-rubric gate:"
SCORE_GATE_PREFIX_MUST_RIGHT_FAILURES = "score must-right failures gate:"
SCORE_GATE_PREFIX_WRONG_NAME_FLOOR_VACUITY = "score wrong-name floor vacuity gate:"
SCORE_GATE_PREFIX_WRONG_NAME_FLOOR = "score wrong-name floor gate:"
SCORE_GATE_PREFIX_QUALITY_FLOOR = "score quality-floor gate:"
SCORE_GATE_PREFIX_CATEGORY_VACUITY = "score category-vacuity gate:"
SCORE_GATE_PREFIX_FREEZE_CERT_REFUSED = "score freeze-certification refused:"
SCORE_GATE_PREFIX_FACE_REPORT_READBACK = "score face-report-readback gate:"
# Pre-write freeze protection (VLM6-E-05 / RF-04): label is a *suffix* so caption
# and face share one greppable class token (rg-015). Never f"{label} refuse-…".
SCORE_GATE_PREFIX_REFUSE_OVERWRITE = "score refuse-overwrite gate:"
# ``run`` multi-record wrapper (RF-05): fixed prefixes; record path after colon.
SCORE_GATE_PREFIX_RUN_RECORD = "run score gate failed:"
SCORE_GATE_PREFIX_RUN_SUMMARY = "run score gates failed:"
# Frozen set consumed by the README drift test (do not hand-copy strings there).
SCORE_GATE_PREFIXES: frozenset[str] = frozenset(
    {
        SCORE_GATE_PREFIX_SCHEMA_ERROR,
        SCORE_GATE_PREFIX_ABORTED_RECORD,
        SCORE_GATE_PREFIX_ZERO_SCORED,
        SCORE_GATE_PREFIX_FAILED_ITEMS,
        SCORE_GATE_PREFIX_TRUNCATION,
        SCORE_GATE_PREFIX_MANIFEST_MISMATCH,
        SCORE_GATE_PREFIX_MANIFEST_DRIFT,
        SCORE_GATE_PREFIX_MANIFEST_RELABEL,
        SCORE_GATE_PREFIX_EMPTY_RUBRIC,
        SCORE_GATE_PREFIX_MUST_RIGHT_FAILURES,
        SCORE_GATE_PREFIX_WRONG_NAME_FLOOR_VACUITY,
        SCORE_GATE_PREFIX_WRONG_NAME_FLOOR,
        SCORE_GATE_PREFIX_QUALITY_FLOOR,
        SCORE_GATE_PREFIX_CATEGORY_VACUITY,
        SCORE_GATE_PREFIX_FREEZE_CERT_REFUSED,
        SCORE_GATE_PREFIX_FACE_REPORT_READBACK,
        SCORE_GATE_PREFIX_REFUSE_OVERWRITE,
        SCORE_GATE_PREFIX_RUN_RECORD,
        SCORE_GATE_PREFIX_RUN_SUMMARY,
    }
)
# Back-compat alias (schema hard-key token without trailing colon was historical).
_SCORE_SCHEMA_ERROR_TOKEN = SCORE_GATE_PREFIX_SCHEMA_ERROR.rstrip(":")

# VLM6-GATE-INT-01: category-vacuity reason prefixes (see
# report.py::build_score_vacuity_reasons) that are pure restatements of a
# refused identification block — raise_if_unconsented_refusals already reports
# these per-metric, so the category-vacuity gate must not re-hard-fail on them
# when identification refused. Never used to suppress an unrelated category.
_IDENTIFICATION_DERIVED_VACUITY_PREFIXES = (
    "category-vacuity: positional",
    "category-vacuity: identity_ordering",
    "category-vacuity: face_identification.precision",
    "category-vacuity: face_identification.recall",
)
# Detection-derived: a restatement of the refusal only when detection *also*
# refused (S2R5-13 case B keeps a detection-only refusal surgical).
_DETECTION_DERIVED_VACUITY_PREFIXES = (
    "category-vacuity: face_detection.precision",
    "category-vacuity: face_detection.recall",
)


def _is_identification_restatement_reason(reason: str, *, detection_refused: bool) -> bool:
    """True when ``reason`` only restates a refused identification/detection.

    Every other category-vacuity or sample-size reason (placement,
    fabricated_fact, caption categories, ...) is independent of face refusal
    state and must survive unconditionally (VLM6-GATE-INT-01).
    """
    text = str(reason)
    if text.startswith(_IDENTIFICATION_DERIVED_VACUITY_PREFIXES):
        return True
    if detection_refused and text.startswith(_DETECTION_DERIVED_VACUITY_PREFIXES):
        return True
    return False


class ScoreGateError(RuntimeError):
    """A score integrity/quality gate failed after reports were written (B-10).

    Raised instead of ``sys.exit`` so ``run`` can score every provider record
    and exit once with a per-record summary. ``main`` maps this to SystemExit.
    """


def _score_gate_fail(message: str) -> NoReturn:
    """Fail a post-write score gate with a class-unique operator message."""
    raise ScoreGateError(message)


def _score_schema_error_message(dotted_path: str, expected: str) -> str:
    """Class-unique schema-error exit text (never soft-falls through)."""
    return f"{SCORE_GATE_PREFIX_SCHEMA_ERROR} {dotted_path} missing or not a {expected}"


def _score_schema_error(dotted_path: str, expected: str) -> NoReturn:
    """Fail naming the missing/wrong-type dotted path (never falls through)."""
    _score_gate_fail(_score_schema_error_message(dotted_path, expected))


def _hard_key(container: Mapping[str, Any] | None, *path: str, expected: str, check) -> Any:
    """Require ``path`` present under container with a value passing ``check``."""
    dotted = ".".join(path)
    cur: Any = container
    for key in path:
        if not isinstance(cur, Mapping) or key not in cur:
            _score_schema_error(dotted, expected)
        cur = cur[key]
    if not check(cur):
        _score_schema_error(dotted, expected)
    return cur


def _schema_hard_key_error(container: Mapping[str, Any] | None, *path: str, expected: str, check) -> str | None:
    """Return schema-error message when ``path`` is missing/wrong-type; else None."""
    dotted = ".".join(path)
    cur: Any = container
    for key in path:
        if not isinstance(cur, Mapping) or key not in cur:
            return _score_schema_error_message(dotted, expected)
        cur = cur[key]
    if not check(cur):
        return _score_schema_error_message(dotted, expected)
    return None


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_number(value: Any) -> bool:
    # bool is a subclass of int — reject it so True/False never soft-pass as 1/0.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _fold_schema_errors_into_verdict(scored: dict[str, Any]) -> str | None:
    """Hard-key gate inputs into the persisted verdict before serialisation (F1d-1).

    Returns the first schema-error exit message when any required field is missing
    or mistyped; mutates ``scored["verdict"]`` to ``fail`` with a class-unique
    reason so the on-disk artifact cannot report pass while the process exits 1.
    """
    checks: list[tuple[tuple[str, ...], str, Any]] = [
        (("provenance", "manifest_matches_fetch"), "bool", _is_bool),
        (("caption", "must_right_failed_images"), "number", _is_number),
        (("verdict", "wrong_name_rate"), "number", _is_number),
    ]
    first_msg: str | None = None
    schema_reasons: list[str] = []
    for path, expected, check in checks:
        err = _schema_hard_key_error(scored, *path, expected=expected, check=check)
        if err is None:
            continue
        if first_msg is None:
            first_msg = err
        # Machine-readable reason mirrors the exit token class (OBS-04).
        schema_reasons.append(err)
    if first_msg is None:
        return None
    verdict = dict(scored.get("verdict") or {})
    prior = [r for r in (verdict.get("reasons") or []) if r not in schema_reasons]
    verdict["verdict"] = ScoreVerdict.FAIL.value
    verdict["reasons"] = schema_reasons + prior
    scored["verdict"] = verdict
    return first_msg


def _fold_evidence_gates_into_verdict(scored: dict[str, Any], record: Mapping[str, Any]) -> str | None:
    """Fold aborted / zero-scored evidence failures into the on-disk verdict (A-02).

    Returns the first gate exit message when evidence is vacuous; mutates
    ``scored["verdict"]`` to fail so the artifact cannot claim pass (OBS-04).
    """
    reasons: list[str] = []
    first_msg: str | None = None
    if record.get("aborted"):
        first_msg = (
            f"{SCORE_GATE_PREFIX_ABORTED_RECORD} run-record is aborted "
            "(partial evidence only); refusing to certify"
        )
        reasons.append("aborted-record: run was aborted before completion")
    scored_n = int((scored.get("counts") or {}).get("scored") or 0)
    if scored_n == 0:
        msg = f"{SCORE_GATE_PREFIX_ZERO_SCORED} scored=0 items; no evidence to certify"
        if first_msg is None:
            first_msg = msg
        reasons.append("zero-scored: no items scored — no evidence")
    if first_msg is None:
        return None
    verdict = dict(scored.get("verdict") or {})
    prior = list(verdict.get("reasons") or [])
    # Prepend evidence reasons so they are visible first in the artifact.
    merged = reasons + [r for r in prior if r not in reasons]
    verdict["verdict"] = ScoreVerdict.FAIL.value
    verdict["reasons"] = merged
    scored["verdict"] = verdict
    return first_msg


def _fold_manifest_drift_into_verdict(
    scored: dict[str, Any],
    *,
    allow_manifest_relabel: bool,
) -> str | None:
    """Fold fetch/score manifest drift into the verdict (VLM6-F-03 / EVAL-13).

    Default: hard-fail — numbers scored under a changed judging protocol are not
    certifiable. Archival relabel (``--allow-manifest-relabel``) persists a
    distinct ``non_comparable`` verdict that ``compare`` rejects; never ``pass``.
    Returns an exit message when the hard-fail path applies; None when ok or
    when archival relabel rewrote the verdict to non_comparable.
    """
    if scored.get("provenance", {}).get("manifest_matches_fetch") is not False:
        return None
    fetch_sha = (scored.get("provenance") or {}).get("manifest_sha256")
    score_sha = (scored.get("provenance") or {}).get("score_manifest_sha256")
    # Missing fetch-time sha is a distinct class token (manifest-mismatch gate);
    # do not absorb it into the drift gate (OBS-04 / class uniqueness).
    if not fetch_sha:
        return None
    if allow_manifest_relabel:
        verdict = dict(scored.get("verdict") or {})
        reason = (
            f"manifest-relabel: scored under score_manifest_sha256={score_sha} but "
            f"fetched under {fetch_sha}; numbers are not adoption-comparable (EVAL-13)"
        )
        prior = [r for r in (verdict.get("reasons") or []) if r != reason]
        verdict["verdict"] = ScoreVerdict.NON_COMPARABLE.value
        verdict["reasons"] = [reason] + prior
        scored["verdict"] = verdict
        return None
    return (
        f"{SCORE_GATE_PREFIX_MANIFEST_DRIFT} scored against "
        f"score_manifest_sha256={score_sha} "
        f"but fetched under {fetch_sha} (manifest_matches_fetch=false); numbers are not "
        f"comparable to a baseline scored on the fetch-time corpus (EVAL-13). "
        f"Pass --allow-manifest-relabel only for archival relabelling (persists "
        f"verdict={ScoreVerdict.NON_COMPARABLE.value}, rejected by compare)"
    )


RUBRIC_GATE_CHOICES = (RUBRIC_GATE_ENFORCE, RUBRIC_GATE_SKIP)


def _keep_arg(raw: str) -> int:
    """argparse type for ``--keep``: at least 1 so a run never prunes its own record (S3-07)."""
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _limit_arg(raw: str) -> int:
    """argparse type for ``--limit``: positive int; reject 0/negative (S8-03 / S6-02).

    ``limit=0`` is falsy and previously silently ran the full corpus; negative
    values silently sliced the tail off. Fail at parse time instead.
    """
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _provider_value(raw: str) -> str:
    """argparse type for ``--provider``: a registered hosted description profile (rg-008, sr-007)."""
    value = raw.strip()
    try:
        profile = DescriptionProfile(value)
    except ValueError:
        hosted = [p.value for p, s in PROFILE_SPECS.items() if s.adapter_kind is DescriptionAdapterKind.HOSTED_PROVIDER]
        raise argparse.ArgumentTypeError(f"{raw!r} is not a description profile; hosted profiles: {hosted}") from None
    if PROFILE_SPECS[profile].adapter_kind is not DescriptionAdapterKind.HOSTED_PROVIDER:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a hosted profile (adapter_kind != hosted_provider)")
    return value


class BoundedStallError(RuntimeError):
    """Aborted after too many consecutive per-item failures (rg-007).

    Carries the partial run record (``aborted: true``) so an aborted run is
    still diagnosable — the per-item errors are the whole point of the abort.
    """

    def __init__(self, message: str, partial_record: dict[str, Any]) -> None:
        super().__init__(message)
        self.partial_record = partial_record


class MaxCostExceededError(RuntimeError):
    """Aborted before a paid provider call would push estimated spend past ``--max-cost`` (E20-11).

    Like ``BoundedStallError``, carries the partial record so the capped run is
    still scoreable evidence.
    """

    def __init__(self, message: str, partial_record: dict[str, Any]) -> None:
        super().__init__(message)
        self.partial_record = partial_record


class ProviderMismatchError(RuntimeError):
    """The service's describe response does not corroborate the claimed ``--provider`` (rg-015).

    The flag cannot switch the server profile (that is fixed by
    ``ACX_DESCRIPTION_ADAPTER`` on the service), so the harness verifies each
    item's ``provider_disclosure`` and aborts rather than stamping mislabeled
    benchmark evidence. Carries the partial record for diagnosis.
    """

    def __init__(self, message: str, partial_record: dict[str, Any]) -> None:
        super().__init__(message)
        self.partial_record = partial_record


def fetch_run_record(
    manifest: GoldenManifest,
    images_dir: str,
    client: Any,
    *,
    head_sha: str | None,
    limit: int | None = None,
    stall_limit: int = DEFAULT_STALL_LIMIT,
    started_at: str = "1970-01-01T00:00:00Z",
    provider: str | None = None,
    cost_per_image_usd: float | None = None,
    max_cost_usd: float | None = None,
    spent_usd: float = 0.0,
) -> dict[str, Any]:
    """Walk manifest entries sequentially; isolate per-item failures; bound stalls.

    E20-11: ``provider`` stamps the hosted description profile under test into the
    provenance and is *verified* against each item's ``provider_disclosure``
    (``ProviderMismatchError`` on drift — the flag cannot switch the server
    profile, so unverified stamping would fabricate evidence, rg-015).
    ``cost_per_image_usd`` (the provider's published per-request price) is billed
    per *attempted, non-cached* describe call — cache hits (``cached: true``) are
    refunded and analyze/identity calls are provider-free — yielding
    ``est_cost_usd``/``paid_describe_calls``; ``max_cost_usd`` aborts *before* the
    paid call that would push ``spent_usd`` + this run's estimate past the cap
    (``spent_usd`` carries spend from earlier legs of a matrix invocation).
    ``latency_s`` times the describe call only, not the recognition job polling.
    """
    images_root = Path(images_dir)
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    entries = manifest.entries[:limit] if limit is not None else manifest.entries
    items: list[dict[str, Any]] = []
    consecutive_failures = 0
    paid_calls = 0
    expected_model_id: str | None = None
    if provider is not None:
        try:
            expected_model_id = PROFILE_SPECS[DescriptionProfile(provider)].model_id
        except ValueError:
            expected_model_id = None  # direct callers may pass labels outside the registry

    def _record(aborted: bool = False) -> dict[str, Any]:
        provenance: dict[str, Any] = {
            "manifest_sha256": _manifest_sha(manifest),
            "base_url": getattr(client, "base_url", "unknown"),
            "head_sha": head_sha,
            "started_at": started_at,
        }
        if provider is not None:
            provenance["provider"] = provider
        if cost_per_image_usd is not None:
            provenance["cost_per_image_usd"] = cost_per_image_usd
            provenance["paid_describe_calls"] = paid_calls
            provenance["est_cost_usd"] = round(cost_per_image_usd * paid_calls, 6)
        record: dict[str, Any] = {
            "schema": SCHEMA,
            "kind": DocKind.RUN_RECORD.value,
            "provenance": provenance,
            "items": items,
        }
        if aborted:
            record["aborted"] = True
        return record

    for entry in entries:
        if max_cost_usd is not None and cost_per_image_usd is not None:
            # Pre-call the cache state is unknown, so the projection is conservative:
            # the next describe is assumed paid.
            projected = spent_usd + cost_per_image_usd * (paid_calls + 1)
            if projected > max_cost_usd:
                raise MaxCostExceededError(
                    f"next paid call would raise estimated spend to ${projected:.4f} "
                    f"(> --max-cost ${max_cost_usd:.4f}); aborting before {entry.path}",
                    partial_record=_record(aborted=True),
                )
        # NFC/NFD-tolerant resolve (same as hash verify / seed_scenes) so a
        # Linux host whose fixture copy flipped normalization still reads bytes
        # after load_manifest(images_dir=...) passed (S6-03 / S7-01).
        image_path = _resolve_image(images_root, entry.path)
        item: dict[str, Any] = {
            "media_id": entry.media_id,
            "path": entry.path,
            "describe": None,
            "identities": [],
            "face_count": 0,
            "error": None,
            "latency_s": None,
            # A-08: absolute-pixel bboxes are only well-defined with image size.
            "image_width": None,
            "image_height": None,
            # A-07: "positional" | "degraded" once identities are extracted.
            "identity_ordering": None,
        }
        describe_started: float | None = None
        try:
            if image_path is None:
                raise FileNotFoundError(f"image file missing after NFC/NFD resolve: {entry.path}")
            image_bytes = image_path.read_bytes()
            width, height = _image_dimensions(image_bytes)
            item["image_width"] = width
            item["image_height"] = height
            describe_started = time.monotonic()
            # Billed on attempt (a failed call may still charge); refunded on cache hit.
            paid_calls += 1
            item["describe"] = client.describe(
                image_bytes=image_bytes,
                filename=image_path.name,
                media_id=entry.media_id,
                context_pack=entry.context_pack.model_dump(exclude_none=True),
            )
            item["latency_s"] = round(time.monotonic() - describe_started, 3)
            if isinstance(item["describe"], dict) and item["describe"].get("cached") is True:
                paid_calls -= 1
            job_id = client.analyze([(entry.media_id, image_path.name, image_bytes)])
            client.wait_job(job_id)
            identities_payload = client.media_identities([entry.media_id])
            # VLM6-B-03: pass capture size so wire extract uses centre-x order
            # (same canonical rule as face_metrics / report positional path).
            identities, face_count, ordering_source = _extract_identities(
                identities_payload,
                entry.media_id,
                image_width=item.get("image_width"),
                image_height=item.get("image_height"),
            )
            item["identities"] = identities
            item["face_count"] = face_count
            item["identity_ordering"] = ordering_source
        except Exception as exc:  # noqa: BLE001 — per-item isolation is the contract (rg-007)
            item["error"] = f"{type(exc).__name__}: {exc}"
            if item["latency_s"] is None and describe_started is not None:
                item["latency_s"] = round(time.monotonic() - describe_started, 3)
            consecutive_failures += 1
            if consecutive_failures >= stall_limit:
                items.append(item)
                raise BoundedStallError(
                    f"{consecutive_failures} consecutive item failures (last: {entry.path}); aborting run",
                    partial_record=_record(aborted=True),
                ) from exc
        else:
            consecutive_failures = 0
            if provider is not None:
                describe = item["describe"] if isinstance(item["describe"], dict) else {}
                disclosure = describe.get("provider_disclosure")
                response_model = describe.get("model_id")
                corroborated = (
                    isinstance(disclosure, dict)
                    and disclosure.get("provider") == "hosted"
                    and disclosure.get("left_service_boundary") is True
                    # Disambiguate WHICH hosted profile when both sides expose a model id.
                    and (response_model is None or expected_model_id is None or response_model == expected_model_id)
                )
                if not corroborated:
                    items.append(item)
                    raise ProviderMismatchError(
                        f"--provider {provider!r} claimed but {entry.path}'s describe response does not "
                        f"corroborate it (provider_disclosure={disclosure!r}, model_id={response_model!r}, "
                        f"expected model {expected_model_id!r}); the service profile is fixed server-side "
                        "by ACX_DESCRIPTION_ADAPTER — refusing to stamp mislabeled evidence",
                        partial_record=_record(aborted=True),
                    )
        items.append(item)

    return _record()


def _parse_identity_bbox(raw: Any) -> dict[str, int | float] | None:
    """Validate wire bbox {x, y, width, height}; never invent or accept w/h aliases (rg-015)."""
    if not isinstance(raw, dict):
        return None
    try:
        x, y, width, height = raw["x"], raw["y"], raw["width"], raw["height"]
    except KeyError:
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y, width, height)):
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _image_dimensions(image_bytes: bytes) -> tuple[int | None, int | None]:
    """Read (width, height) from image bytes; (None, None) when undecodable (A-08)."""
    try:
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as im:
            width, height = im.size
        return int(width), int(height)
    except Exception:  # noqa: BLE001 — non-image fixtures in unit tests; stamp None
        return None, None


def _identity_row_from_wire(row: dict[str, Any], *, name: str, bbox: dict[str, int | float] | None) -> dict[str, Any]:
    """Build a stored identity row, preserving wire ``identity_id`` when present (A-09)."""
    stored: dict[str, Any] = {
        "name": name,
        "bbox": bbox,
        "unpositioned": bbox is None,
    }
    if "identity_id" in row:
        stored["identity_id"] = row["identity_id"]
    return stored


def _extract_identities(
    payload: Any,
    media_id: int,
    *,
    image_width: float | None = None,
    image_height: float | None = None,
) -> tuple[list[dict[str, Any]], int, str]:
    """Normalize /media/identities rows for one media_id -> (identities, face_count, ordering).

    Wire shape (MediaIdentityService.list_by_media_ids): each row carries
    ``cluster_label`` and ``is_auto_label`` (inverted ``user_confirmed``). There
    is no ``user_confirmed`` key on this route — filter confirmed labels via
    ``is_auto_label is not True`` (S8-01 / rg-005).

    Confirmed names are bound to faces by **normalized centre-x** L→R order
    (VLM6-B-03 / VLM6-RH-03) — the same ``sort_identity_rows_by_normalized_centre``
    rule used by face_pass and report positional scoring. Corner-x and centre-x
    disagree when face widths differ; this path must not fork a third sort key.
    Each entry carries its bbox and the wire ``identity_id`` when present (A-09).
    Rows with missing/malformed bbox are kept, marked unpositioned, and sorted
    after positioned rows — never dropped and never given a fabricated bbox
    (rg-015). When any confirmed row is unpositioned the ordering_source is
    ``IdentityOrdering.DEGRADED`` so callers/report can surface the fall-back
    rather than silently reinstating alphabetical order (A-07 / VLM6-RH-06).

    ``image_width`` / ``image_height`` come from the capture stamp (A-08). When
    either is missing, unit dims are used so absolute centre-x order within the
    image is preserved (order-equivalent to normalized centre for one frame).
    """
    # Late import: face_metrics is the single ordering owner (VLM6-B-03); keep
    # cli free of a circular import at module load.
    from scripts.eval_harness.face_metrics import sort_identity_rows_by_normalized_centre

    if not isinstance(payload, list):
        raise RemoteClientError(
            f"media_identities returned {type(payload).__name__}, expected a list of "
            "identity rows (rg-015) — per-item isolation records this as an item error"
        )
    confirmed: list[dict[str, Any]] = []
    face_count = 0
    for row in payload:
        if not isinstance(row, dict) or int(row.get("media_id", -1)) != media_id:
            continue
        face_count += 1
        label = row.get("cluster_label") or row.get("label") or row.get("name")
        # Confirmed labels only: is_auto_label True => auto-propagated, skip.
        # Missing key treated as confirmed (legacy/test fixtures without the field).
        if not label or row.get("is_auto_label") is True:
            continue
        name = str(label)
        bbox = _parse_identity_bbox(row.get("bbox"))
        confirmed.append(_identity_row_from_wire(row, name=name, bbox=bbox))
    order_w = float(image_width) if image_width is not None else 1.0
    order_h = float(image_height) if image_height is not None else 1.0
    identities = sort_identity_rows_by_normalized_centre(
        confirmed, image_width=order_w, image_height=order_h
    )
    has_unpositioned = any(bool(r.get("unpositioned")) for r in identities)
    ordering_source = (
        IdentityOrdering.DEGRADED.value if has_unpositioned else IdentityOrdering.POSITIONAL.value
    )
    return identities, face_count, ordering_source


def _manifest_sha(manifest: GoldenManifest) -> str:
    canonical = json.dumps(manifest.model_dump(), sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


def prune_out_dir(out_dir: str, *, keep: int = DEFAULT_KEEP) -> list[str]:
    """Keep the newest ``keep`` runs; delete each stale run's record + reports together.

    Group every ``run-<stamp>*`` file (record, ``-report.json``, ``-report.md``,
    ``-aborted.json``) by its timestamp and prune whole stale runs, so markdown
    reports no longer accumulate unbounded and a report is never deleted while its
    record survives (S3-02). ``keep`` must be >= 1 so a run flow can never delete
    the record it just wrote (S3-07); the ignore list is never touched.
    """
    if keep < 1:
        raise ValueError(f"keep must be >= 1, got {keep}")
    root = Path(out_dir)
    groups: dict[str, list[Path]] = {}
    for path in root.glob("run-*"):
        if path.name == IGNORE_LIST_NAME:
            continue
        match = _RUN_STAMP_RE.match(path.name)
        if match:
            groups.setdefault(match.group(1), []).append(path)
    removed: list[str] = []
    for stamp in sorted(groups)[:-keep]:
        for path in groups[stamp]:
            path.unlink()
            removed.append(path.name)
    return removed


def _require_live_env() -> tuple[str, str, str]:
    if os.environ.get("ACX_EVAL_LIVE") != "1":
        sys.exit("live subcommand requires ACX_EVAL_LIVE=1 (safety gate; see README)")
    base_url = os.environ.get("ACX_EVAL_BASE_URL", "")
    api_key = get_secret_provider().get_secret_optional("ACX_EVAL_API_KEY", "") or ""
    tenant_id = os.environ.get("ACX_EVAL_TENANT_ID", "")
    if not base_url or not api_key or not tenant_id:
        sys.exit(
            "ACX_EVAL_BASE_URL, ACX_EVAL_API_KEY, and ACX_EVAL_TENANT_ID are required — "
            "use the dedicated eval tenant, never the demo tenant"
        )
    return base_url, api_key, tenant_id


def _head_sha() -> str | None:
    """Resolve live git HEAD, or None when unresolvable (never fabricate).

    Unresolvable means missing git binary, non-repo cwd, or rev-parse failure.
    Callers store null in provenance — not ``\"unknown\"`` or forty zeros
    (HARM-03 / RV2-06 / S4-06 / rg-015).
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if not out or out == "0" * 40:
        return None
    return out


def _images_dir() -> str:
    images_dir = os.environ.get("GOLDEN_IMAGES_DIR", "")
    if not images_dir:
        sys.exit("GOLDEN_IMAGES_DIR is not set — see scene/tests/seed/README.md for the rsync bootstrap")
    return images_dir


def _load_ignore_list(source_dir: Path) -> dict[str, Any] | None:
    """Load ``ignore-list.json`` from beside the run record being scored.

    Reading it from the record's own directory (not always ``OUT_DIR``) removes an
    ambient input that silently changed a committed baseline's re-score depending
    on the machine's ``out/`` contents (S3-05c). Structure is validated fail-fast:
    a malformed ``wrong_names`` value can no longer no-op silently (S3-05a, rg-008).

    Known limitation (S3-05b): ignored pairs are keyed on (path, name) with no
    expiry/commit binding, so a pair triaged once stays suppressed even if the
    same wrong-name later genuinely regresses. Every suppressed pair is still
    surfaced under ``ignored_wrong_names`` in the report so it is never invisible.
    Presentation-only (F1-5): the wrong-name floor rate counts live + ignored;
    this file cannot certify a model that asserts wrong names on every image.
    """
    path = source_dir / IGNORE_LIST_NAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ManifestError(f"{path} must contain a JSON object")
    wrong = payload.get("wrong_names", [])
    if not isinstance(wrong, list) or not all(
        isinstance(pair, list) and len(pair) == 2 and all(isinstance(part, str) for part in pair) for pair in wrong
    ):
        raise ManifestError(f"{path}: 'wrong_names' must be a list of [path, name] string pairs")
    return payload


def _parse_allow_refused_metric(raw: str) -> str:
    """argparse type: a RefusedMetric value, or the all-metrics sentinel."""
    token = raw.strip()
    if token in {ALLOW_REFUSED_ALL, "all"}:
        return ALLOW_REFUSED_ALL
    try:
        return RefusedMetric(token).value
    except ValueError:
        names = ", ".join(member.value for member in RefusedMetric)
        raise argparse.ArgumentTypeError(
            f"{raw!r} is not a refused metric; expected one of: {names} "
            "(bare --allow-refused names every metric)"
        ) from None


def consented_refused_metrics(raw: list[str] | None) -> frozenset[str]:
    """Resolve repeatable ``--allow-refused`` values to a metric set.

    Bare ``--allow-refused`` stores ``ALLOW_REFUSED_ALL`` and equals naming
    every ``RefusedMetric`` member. Consenting to one metric never implies
    another (S2R5-05).
    """
    if not raw:
        return frozenset()
    if ALLOW_REFUSED_ALL in raw:
        return frozenset(member.value for member in RefusedMetric)
    return frozenset(raw)


def collect_refused_metrics(scored: Mapping[str, Any]) -> dict[str, str]:
    """Return ``{metric: invariant}`` for refused honesty fields on a report."""
    refused: dict[str, str] = {}
    faces = scored.get("faces")
    faces = faces if isinstance(faces, Mapping) else {}
    detection = faces.get("detection")
    if not isinstance(detection, Mapping):
        detection = scored.get("detection")
    if isinstance(detection, Mapping) and detection.get("refused"):
        refused[RefusedMetric.DETECTION.value] = str(detection.get("invariant") or "unknown")
    identification = faces.get("identification") if isinstance(faces, Mapping) else None
    if isinstance(identification, Mapping) and identification.get("refused"):
        refused[RefusedMetric.IDENTIFICATION.value] = str(
            identification.get("invariant") or "unknown"
        )
    slices = scored.get("slices")
    if isinstance(slices, Mapping):
        for key in (
            "headline_identification",
            "full_corpus_identification",
            "unknown_rejection",
            "demographic",
        ):
            block = slices.get(key)
            if isinstance(block, Mapping) and block.get("refused"):
                refused.setdefault(
                    RefusedMetric.IDENTIFICATION.value,
                    str(block.get("invariant") or "unknown"),
                )
                break
    return refused


def raise_if_aborted_run(record: Mapping[str, Any], *, command: str) -> None:
    """A partial run is not a corpus (S2R5-12 / AUDIT-08). Exit 1, not 3."""
    if record.get("aborted"):
        print(
            f"{command} gate failed: run record is aborted; a partial run is not a corpus",
            file=sys.stderr,
        )
        raise SystemExit(1)


def raise_if_unconsented_refusals(
    scored: Mapping[str, Any],
    raw_allow: list[str] | None,
    *,
    command: str,
) -> None:
    """Exit 3 unless every refused metric was named (or bare-flagged)."""
    blocked = {
        name: invariant
        for name, invariant in collect_refused_metrics(scored).items()
        if name not in consented_refused_metrics(raw_allow)
    }
    if not blocked:
        return
    print(
        f"{command} gate failed: refused metric(s) ("
        + ", ".join(f"{name}={invariant}" for name, invariant in blocked.items())
        + "); pass --allow-refused=METRIC to accept a run with no score "
        "for those metrics (bare --allow-refused names every metric)",
        file=sys.stderr,
    )
    raise SystemExit(REFUSED_METRIC_EXIT_CODE)


def _reject_llm_judge(args: argparse.Namespace) -> None:
    """Reject the stub LLM-judge tier before any live work (§6c tiers 3-4 out of MVP).

    Checked at the top of fetch/run/score so ``run --llm-judge`` and
    ``fetch --llm-judge`` fail fast instead of burning 38 remote calls first (S3-06).
    """
    if getattr(args, "llm_judge", False):
        sys.exit("--llm-judge is a stub: the LLM-judge tier is not implemented in this MVP (§6c)")


def _cmd_fetch(args: argparse.Namespace) -> list[str]:
    """Fetch one run record per ``--provider`` value (or a single unstamped run)."""
    _reject_llm_judge(args)
    base_url, api_key, tenant_id = _require_live_env()
    images_dir = _images_dir()
    manifest = load_manifest(args.manifest, images_dir=images_dir)
    # Dedupe (order-preserving): a repeated matrix value would overwrite its own
    # same-second record path and double-spend for identical evidence.
    providers: list[str | None] = list(dict.fromkeys(args.provider)) if args.provider else [None]
    OUT_DIR.mkdir(exist_ok=True)
    record_paths: list[str] = []
    spent_usd = 0.0
    for provider in providers:
        client = RemoteSceneClient(base_url=base_url, api_key=api_key, tenant_id=tenant_id)
        started_at = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        stamp = started_at.replace(":", "").replace("-", "").replace("T", "-").rstrip("Z")
        suffix = f"-{provider}" if provider else ""
        record_path = OUT_DIR / f"run-{stamp}{suffix}.json"
        try:
            record = fetch_run_record(
                manifest,
                images_dir,
                client,
                head_sha=_head_sha(),
                limit=args.limit,
                stall_limit=args.stall_limit,
                started_at=started_at,
                provider=provider,
                cost_per_image_usd=args.cost_per_image,
                max_cost_usd=args.max_cost,
                spent_usd=spent_usd,
            )
        except (BoundedStallError, MaxCostExceededError, ProviderMismatchError) as exc:
            aborted_path = OUT_DIR / f"run-{stamp}{suffix}-aborted.json"
            aborted_path.write_text(json.dumps(exc.partial_record, indent=2, sort_keys=True) + "\n")
            sys.exit(f"{type(exc).__name__}: {exc} — partial record saved to {aborted_path}")
        finally:
            client.close()
        if args.cost_per_image is not None:
            # --max-cost caps the whole invocation, not each matrix leg; est_cost_usd
            # already excludes cache hits and never-issued calls.
            spent_usd += record["provenance"].get("est_cost_usd", 0.0)
        record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        record_paths.append(str(record_path))
        print(record_path)
    # Never prune records this invocation just wrote (S3-07 across the matrix).
    prune_out_dir(str(OUT_DIR), keep=max(args.keep, len(record_paths)))
    return record_paths


# Child subprocess budget for cross-process determinism guards (C-03).
# The child imports scripts.eval_harness.cli which can pull face_bakeoff ->
# cv2/onnxruntime; a stalled model/cache resolve must not hang the gate forever.
_DETERMINISM_CHILD_TIMEOUT_S = 120
# Default child PYTHONHASHSEED set for cross-process determinism (C-05).
# Substituted when a seed collides with the parent's fixed regime so coverage
# is never silently narrowed (e.g. CI exporting PYTHONHASHSEED=0).
_DEFAULT_DETERMINISM_CHILD_SEEDS: tuple[str, ...] = ("0", "1", "42")


def _parent_hash_seed_regime() -> tuple[str, str | None]:
    """Name the parent interpreter's PYTHONHASHSEED regime (C-05 / OBS-04).

    Returns ``(regime_label, fixed_seed_or_None)``.

    - ``fixed:<n>`` when ``PYTHONHASHSEED`` is an integer (including 0) — the
      baseline is reconstructible under that seed.
    - ``randomized`` when hash randomization is on and no fixed numeric seed is
      set — baseline is process-local and not a child-seed duplicate.
    """
    env_val = os.environ.get("PYTHONHASHSEED")
    if env_val is not None and env_val.isdigit():
        return f"fixed:{env_val}", env_val
    if sys.flags.hash_randomization:
        return "randomized", None
    # Hash randomization off without a numeric env (unusual); treat as fixed:0
    # so collision handling still keeps child coverage distinct.
    return "fixed:0", "0"


def _resolve_determinism_child_seeds(
    parent_fixed: str | None,
    requested: tuple[str, ...] = _DEFAULT_DETERMINISM_CHILD_SEEDS,
) -> tuple[str, ...]:
    """Return child seeds with parent-fixed collisions substituted (C-05).

    When the parent baseline runs under a fixed ``PYTHONHASHSEED`` that is also
    in the requested child set, that child leg is a byte-for-byte duplicate of
    the baseline configuration. Replace only the colliding entries with the
    lowest unused integer seeds so the child set still contributes
    ``len(requested)`` *distinct* configurations.
    """
    if parent_fixed is None:
        return tuple(requested)
    occupied: set[str] = {parent_fixed}
    out: list[str] = []
    placeholder_idxs: list[int] = []
    # Not ``seed`` — that name is the module-level seed_roster import (F402).
    for child_seed in requested:
        if child_seed == parent_fixed:
            placeholder_idxs.append(len(out))
            out.append("")  # filled below
        else:
            out.append(child_seed)
            occupied.add(child_seed)
    next_i = 0
    for idx in placeholder_idxs:
        while str(next_i) in occupied:
            next_i += 1
        sub = str(next_i)
        out[idx] = sub
        occupied.add(sub)
        next_i += 1
    return tuple(out)


def _determinism_regime_clause(baseline_regime: str, child_seeds: tuple[str, ...]) -> str:
    """Operator-facing baseline + child seed claim fragment (C-05)."""
    return f"baseline={baseline_regime}; child_seeds={','.join(child_seeds)}"


def _run_determinism_children(
    child_script: str,
    argv: list[str],
    *,
    label: str,
    base_json: str,
    base_md: str,
    artifact_dir: Path,
    expected_build_reports_file: str,
    announce_pass: bool = True,
) -> str:
    """Shared cross-process determinism substrate for score / score-face (C-08).

    Holds the seed tuple, env handling, subprocess invocation with a pinned
    import root (F2c / C-01), out-of-band payload transport (F2b / C-04),
    timeout, and the ERROR/FAILED error taxonomy (C-03 / OBS-04).

    Payload transport: parent allocates a tempfile path per seed, appends it as
    the final argv entry, and the child writes a JSON dict
    ``{"json": <str>, "md": <str>, "build_reports_file": <str>}`` there. Dict
    shape (not a 2-tuple) carries provenance without a positional refactor.
    Child stdout is intentionally unused for comparison — banners/warnings
    cannot contaminate the verdict, and free-form caption text cannot forge a
    framing delimiter.

    Import root pin (F2c): ``python -c`` puts the caller's cwd at
    ``sys.path[0]`` ahead of ``PYTHONPATH``, so an unpinned child can bind a
    decoy ``scripts/`` under cwd while the parent scores with its own
    checkout. Both ``cwd`` and a prepended ``PYTHONPATH`` are forced to
    ``Path(__file__).resolve().parents[2]`` (package root). The child also
    reports ``build_reports.__code__.co_filename`` (or face equivalent); the
    parent resolves and compares paths — mismatch is ERROR (environment
    drift), not FAILED (build regression) (OBS-04).

    Seed regime (C-05): the parent's baseline regime is named in every
    pass/FAILED/ERROR message and in mismatch artifacts so a red run is
    reconstructible. Child seeds that collide with a fixed parent seed are
    substituted so coverage is not silently narrowed.

    ``label`` (``score`` / ``score-face``) is interpolated into every operator
    message so CI lines name which gate fired.

    Taxonomy:
    - ``determinism check ERROR [label]: ...`` — child could not run, timed out,
      produced no readable/parseable payload, or bound a different
      ``build_reports`` module than the parent (operator action: environment).
      Sub-cases name missing / unreadable / unparseable / provenance distinctly.
    - ``determinism check FAILED [label]: ...`` — genuine byte mismatch
      (build regression). Names JSON vs MD, writes a side-by-side artifact, and
      includes stderr.
    - ``determinism check ANCHOR_MISMATCH [label]: ...`` — optional third
      outcome when ``--expect-report`` is set (F5 / B-06); emitted by the
      caller after seed-stability, not here.

    Returns the regime clause string so callers that defer the pass line
    (frozen-anchor compare) can print a single combined message (OBS-04).
    """
    # <root>/scripts/eval_harness/cli.py → parents[2] is the package root
    # (apps/prototype-description-service). Pin once; never inherit Path.cwd().
    import_root = Path(__file__).resolve().parents[2]
    parent_reports_file = Path(expected_build_reports_file).resolve()
    baseline_regime, parent_fixed = _parent_hash_seed_regime()
    child_seeds = _resolve_determinism_child_seeds(parent_fixed)
    regime = _determinism_regime_clause(baseline_regime, child_seeds)
    for hash_seed in child_seeds:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = hash_seed
        # Prepend pin even though cwd=import_root already puts that tree first
        # under ``python -c``: a hostile inherited PYTHONPATH entry must not
        # outrank the package root for non-cwd lookups.
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(import_root) if not existing_pp else f"{import_root}{os.pathsep}{existing_pp}"
        # Allocate a unique path the child must create; do not pre-write content
        # (absence must be distinguishable from empty/unparseable). Do not place
        # under artifact_dir — that may be read-only and already owns FAILED diffs.
        fd, payload_name = tempfile.mkstemp(prefix="det-payload-", suffix=".json")
        os.close(fd)
        payload_path = Path(payload_name)
        try:
            # Ensure missing until the child writes (mkstemp creates an empty file).
            payload_path.unlink(missing_ok=True)
            child_argv = [*argv, str(payload_path)]
            try:
                proc = subprocess.run(
                    [sys.executable, "-c", child_script, *child_argv],
                    capture_output=True,
                    text=True,
                    env=env,
                    cwd=str(import_root),
                    timeout=_DETERMINISM_CHILD_TIMEOUT_S,
                )
            except subprocess.TimeoutExpired as exc:
                stderr_snip = ""
                if exc.stderr is not None:
                    stderr_snip = (
                        exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", errors="replace")
                    )
                sys.exit(
                    f"determinism check ERROR [{label}]: subprocess timed out "
                    f"seed={hash_seed} after {_DETERMINISM_CHILD_TIMEOUT_S}s "
                    f"({regime}): {stderr_snip}"
                )
            if proc.returncode != 0:
                sys.exit(
                    f"determinism check ERROR [{label}]: subprocess seed={hash_seed} "
                    f"rc={proc.returncode} ({regime}): {proc.stderr}"
                )
            if not payload_path.is_file():
                sys.exit(
                    f"determinism check ERROR [{label}]: payload file missing "
                    f"seed={hash_seed} path={payload_path} ({regime}); "
                    f"stderr={proc.stderr!r}"
                )
            try:
                payload_text = payload_path.read_text(encoding="utf-8")
            except OSError as read_exc:
                sys.exit(
                    f"determinism check ERROR [{label}]: payload file unreadable "
                    f"seed={hash_seed} path={payload_path}: {read_exc} ({regime}); "
                    f"stderr={proc.stderr!r}"
                )
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError as dec_exc:
                sys.exit(
                    f"determinism check ERROR [{label}]: payload file unparseable "
                    f"seed={hash_seed} path={payload_path}: {dec_exc} ({regime}); "
                    f"stderr={proc.stderr!r}"
                )
            if not isinstance(payload, dict) or "json" not in payload or "md" not in payload:
                sys.exit(
                    f"determinism check ERROR [{label}]: payload file unparseable "
                    f"seed={hash_seed} path={payload_path}: expected object with "
                    f"'json' and 'md' keys ({regime}); stderr={proc.stderr!r}"
                )
            sub_json = payload["json"]
            sub_md = payload["md"]
            if not isinstance(sub_json, str) or not isinstance(sub_md, str):
                sys.exit(
                    f"determinism check ERROR [{label}]: payload file unparseable "
                    f"seed={hash_seed} path={payload_path}: 'json' and 'md' must be "
                    f"strings ({regime}); stderr={proc.stderr!r}"
                )
            # F2c / C-01: prove the child bound the same build_reports module as
            # the parent. Missing/mismatched provenance is environment drift → ERROR.
            child_reports_raw = payload.get("build_reports_file")
            if not isinstance(child_reports_raw, str) or not child_reports_raw:
                sys.exit(
                    f"determinism check ERROR [{label}]: payload missing "
                    f"build_reports_file provenance seed={hash_seed} "
                    f"path={payload_path} ({regime}); stderr={proc.stderr!r}"
                )
            child_reports_file = Path(child_reports_raw).resolve()
            if child_reports_file != parent_reports_file:
                sys.exit(
                    f"determinism check ERROR [{label}]: child build_reports module "
                    f"differs from parent (environment/import-root drift) "
                    f"seed={hash_seed} parent={parent_reports_file} "
                    f"child={child_reports_file} ({regime}); stderr={proc.stderr!r}"
                )
            json_differs = sub_json != base_json
            md_differs = sub_md != base_md
            if not json_differs and not md_differs:
                continue
            docs: list[str] = []
            if json_differs:
                docs.append("JSON")
            if md_differs:
                docs.append("MD")
            which = "+".join(docs)
            artifact = artifact_dir / f"determinism-mismatch-{label}-seed{hash_seed}.diff.txt"
            body = "\n".join(
                [
                    f"gate={label}",
                    f"baseline_regime={baseline_regime}",
                    f"child_seeds={','.join(child_seeds)}",
                    f"PYTHONHASHSEED={hash_seed}",
                    f"differed={which}",
                    f"stderr={proc.stderr!r}",
                    "",
                    "=== baseline JSON ===",
                    base_json,
                    "=== subprocess JSON ===",
                    sub_json,
                    "=== baseline MD ===",
                    base_md,
                    "=== subprocess MD ===",
                    sub_md,
                    "",
                ]
            )
            try:
                artifact.write_text(body)
                artifact_ref = str(artifact)
            except OSError as write_exc:
                artifact_ref = f"(could not write artifact: {write_exc})"
            sys.exit(
                f"determinism check FAILED [{label}]: cross-process re-score differs "
                f"under PYTHONHASHSEED={hash_seed} "
                f"({regime}; document={which}; artifact={artifact_ref}; "
                f"stderr={proc.stderr!r})"
            )
        finally:
            with contextlib.suppress(OSError):
                payload_path.unlink(missing_ok=True)
    if announce_pass:
        print(
            f"determinism check passed [{label}]: cross-process re-score is "
            f"bit-identical under varied PYTHONHASHSEED ({regime})"
        )
    return regime


# Opt-in frozen-report regeneration commands named in ANCHOR_MISMATCH (OBS-04).
# Caption and face freezes have distinct generators; _check_expect_report takes
# regen_cmd so the remedy line names the right module (no helper fork).
_DETERMINISM_ANCHOR_REGEN_CMD = "python -m scripts.eval_harness.generate_determinism_anchor"
_FACE_DETERMINISM_ANCHOR_REGEN_CMD = "python -m scripts.eval_harness.generate_face_determinism_anchor"


def _determinism_artifact_dir() -> Path:
    """Home for non-promoted determinism diagnostics (FAILED / ANCHOR_MISMATCH).

    Always ``scripts/eval_harness/out/`` (gitignored, PROV-01). Never derive from
    the run-record or --expect-report path — those often live under committed
    ``docs/tasks/vlm/bakeoff-results/``, and a red gate must not dirty the tree
    (F7-01). Absolute path is printed in the operator message (OBS-04).
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR.resolve()


def _check_expect_report(
    base_json: str,
    expect_report: Path,
    *,
    label: str,
    regime: str,
    artifact_dir: Path,
    regen_cmd: str = _DETERMINISM_ANCHOR_REGEN_CMD,
) -> None:
    """Third determinism outcome: compare certified JSON to a frozen report (F5/F6 / B-06).

    Seed-stability (ERROR / FAILED / passed) only proves the scoring function is
    stable across interpreters. Without an external reference, a corrupted
    run-record or report is re-scored the same way by parent and children and
    still "passes". ``--expect-report`` is that external reference — opt-in and
    path-explicit (no sibling-filename inference).

    Taxonomy (OBS-04) — distinct from ERROR and FAILED:
    - missing/unreadable expect path → ERROR (operator path/env action)
    - readable but bytes differ → ANCHOR_MISMATCH (corrupt freeze/record *or*
      deliberate scoring change; message names both remedies and the regen cmd)

    Mismatch artifacts land under ``artifact_dir`` (callers pass
    ``_determinism_artifact_dir()`` → gitignored ``out/``), never beside a
    committed freeze path, so a red compare cannot dirty the worktree (F7-01).

    ``regen_cmd`` defaults to the caption generator; face callers pass
    ``_FACE_DETERMINISM_ANCHOR_REGEN_CMD`` so the ANCHOR_MISMATCH remedy names
    the synthetic face regenerator (parameterised helper — not forked).
    """
    resolved = expect_report.resolve()
    if not resolved.is_file():
        sys.exit(
            f"determinism check ERROR [{label}]: --expect-report path missing or not a file: {resolved} ({regime})"
        )
    try:
        expected = resolved.read_text(encoding="utf-8")
    except OSError as read_exc:
        sys.exit(
            f"determinism check ERROR [{label}]: --expect-report unreadable path={resolved}: {read_exc} ({regime})"
        )
    if expected == base_json:
        print(
            f"determinism check passed [{label}]: cross-process re-score is "
            f"bit-identical under varied PYTHONHASHSEED ({regime}); "
            f"matches --expect-report {resolved}"
        )
        return
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = (artifact_dir / f"determinism-anchor-mismatch-{label}.diff.txt").resolve()
    body = "\n".join(
        [
            f"gate={label}",
            f"regime={regime}",
            f"expect_report={resolved}",
            "outcome=ANCHOR_MISMATCH",
            "",
            "=== expected (--expect-report) JSON ===",
            expected,
            "=== certified (fresh re-score) JSON ===",
            base_json,
            "",
        ]
    )
    try:
        artifact.write_text(body)
        artifact_ref = str(artifact)
    except OSError as write_exc:
        artifact_ref = f"(could not write artifact: {write_exc})"
    sys.exit(
        f"determinism check ANCHOR_MISMATCH [{label}]: fresh re-score does not "
        f"match --expect-report {resolved} ({regime}; artifact={artifact_ref}). "
        f"This is neither seed divergence (FAILED) nor environment drift (ERROR). "
        f"Two legitimate causes — choose carefully: "
        f"(1) the frozen report or the run-record was corrupted — investigate, "
        f"do NOT regenerate (regenerating destroys the evidence); "
        f"(2) scoring was deliberately changed and the freeze is now stale — "
        f"regenerate on purpose via `{regen_cmd}` and commit "
        f"the new freeze."
    )


def _check_score_determinism_cross_process(
    record_path: Path,
    manifest_path: str,
    *,
    rubric_gate: str = RUBRIC_GATE_ENFORCE,
    audience: Audience = Audience.LOCAL,
    label: str = "score",
    expect_report: Path | None = None,
) -> tuple[str, str]:
    """Re-run caption score in a FRESH process under varied PYTHONHASHSEED (§G).

    Baseline is computed in-process from the persisted run-record with the same
    ``rubric_gate`` and ``audience`` the command will write (F2d / GATE-05);
    each subprocess re-loads that same path from disk so hash-ordering,
    import-order, and mutated-anchor failures are visible. Subprocess loop lives
    in ``_run_determinism_children`` (C-08).

    When ``expect_report`` is set (CLI ``--expect-report``), after seed-stability
    the certified JSON is compared to those frozen bytes (F5 / B-06). Mismatch
    is ``ANCHOR_MISMATCH`` — a third outcome, not ERROR or FAILED (OBS-04).

    Returns the certified ``(json_doc, md_doc)`` pair so the caller can write
    *those* bytes — one build, not a second uncertified serialisation.

    Labels: ``score`` for the full LOCAL report; ``score-public`` for the
    additive redacted PUBLIC export under ``--audience public``.
    """
    # F2C-01: resolve data paths before handing them to a child whose cwd is
    # pinned to the package root (F2c). Relative argv would resolve against the
    # pin, not the caller's cwd, and FileNotFoundError as ERROR.
    resolved_record = record_path.resolve()
    resolved_manifest = Path(manifest_path).resolve()
    # Baseline: current process, reading the persisted anchor with the real
    # operator parameters (not the build_reports defaults).
    record = json.loads(resolved_record.read_text())
    # Metadata-only: build_reports reads rubrics/roster/policy, never opens image bytes.
    manifest = load_manifest(str(resolved_manifest), skip_hash_verification=True)
    # VLM6-DELTA-06: mirror _cmd_score's stamp-fill (S2R6E-04 / FIR-11-S2-01) —
    # GoldenEntry forbids a per-entry annotation_mode field, so model_dump()
    # always omits it; without this fill, detection unconditionally refuses
    # with DETECTION_REQUIRES_ANNOTATION_MODE regardless of the manifest's
    # real document-level mode (missing stamp, not roster_only). Unconditional
    # assign would clobber a real per-entry stamp were one ever present.
    entries = []
    for e in manifest.entries:
        row = e.model_dump()
        if row.get("annotation_mode") is None:
            row["annotation_mode"] = manifest.annotation_mode
        entries.append(row)
    manifest_sha = _manifest_sha(manifest)
    ignore_list = _load_ignore_list(resolved_record.parent)
    roster = sorted(set(getattr(manifest, "roster", []) or []))
    audience_value = audience.value if isinstance(audience, Audience) else str(audience)
    audience_enum = Audience(audience_value)
    base_json, base_md = build_reports(
        record,
        entries,
        ignore_list=ignore_list,
        score_manifest_sha256=manifest_sha,
        manifest_roster=roster,
        audience=audience_enum,
        rubric_gate=rubric_gate,
    )

    # Final argv entry is the parent-allocated payload path (F2b out-of-band).
    # build_reports_file provenance (F2c) proves the child bound this module.
    # argv: record, manifest, rubric_gate, audience, [payload]
    script = (
        "import json,sys; "
        "from pathlib import Path; "
        "from scripts.eval_harness.manifest import load_manifest; "
        "from scripts.eval_harness.cli import _manifest_sha, _load_ignore_list; "
        "from scripts.eval_harness.report import build_reports, Audience; "
        "rec_path=Path(sys.argv[1]); "
        "rec=json.loads(rec_path.read_text()); "
        # Metadata-only: child re-score never opens image bytes (must_right/roster only).
        "man=load_manifest(sys.argv[2],skip_hash_verification=True); "
        "rg=sys.argv[3]; "
        "aud=Audience(sys.argv[4]); "
        # VLM6-DELTA-06: mirror _cmd_score's stamp-fill (S2R6E-04) in the child
        # too, or the subprocess re-score refuses detection with
        # DETECTION_REQUIRES_ANNOTATION_MODE while the parent baseline passes.
        # Single-expression form (no def) to stay a valid `python -c` one-liner.
        "entries=[dict(d,annotation_mode=(d.get('annotation_mode') or man.annotation_mode)) "
        "for d in (e.model_dump() for e in man.entries)]; "
        "sha=_manifest_sha(man); "
        "ignore=_load_ignore_list(rec_path.parent); "
        "roster=sorted(set(getattr(man,'roster',None) or [])); "
        "j,m=build_reports(rec,entries,ignore_list=ignore,"
        "score_manifest_sha256=sha,manifest_roster=roster,"
        "audience=aud,rubric_gate=rg); "
        "Path(sys.argv[5]).write_text(json.dumps({"
        "'json':j,'md':m,"
        "'build_reports_file':build_reports.__code__.co_filename}))"
    )
    # Defer the seed-stability pass line when a frozen compare follows so the
    # operator sees one terminal outcome (OBS-04), not pass-then-mismatch.
    # Diagnostics always land in out/ — never beside a committed freeze (F7-01).
    det_artifact_dir = _determinism_artifact_dir()
    regime = _run_determinism_children(
        script,
        [str(resolved_record), str(resolved_manifest), rubric_gate, audience_value],
        label=label,
        base_json=base_json,
        base_md=base_md,
        artifact_dir=det_artifact_dir,
        expected_build_reports_file=build_reports.__code__.co_filename,
        announce_pass=expect_report is None,
    )
    if expect_report is not None:
        _check_expect_report(
            base_json,
            Path(expect_report),
            label=label,
            regime=regime,
            artifact_dir=det_artifact_dir,
        )
    return base_json, base_md


def _serialize_score_docs(
    scored: dict[str, Any],
    *,
    tolerate_renderer_error: bool = False,
) -> tuple[str, str]:
    """Serialize a scored report dict to the on-disk JSON + markdown pair.

    VLM6-A-08 / sr-006: renderer exceptions (KeyError / TypeError / AttributeError)
    must not become a silent green-looking stub. Default: re-raise so a renderer
    regression cannot green-exit. Schema-degraded fail paths may pass
    ``tolerate_renderer_error=True`` to persist JSON with a loud **RENDERER ERROR**
    markdown marker (verdict already fail) — never the pre-fix soft stub.
    """
    json_doc = json.dumps(scored, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        md_doc = _score_report_markdown(scored)
    except (KeyError, TypeError, AttributeError) as exc:
        if not tolerate_renderer_error:
            raise
        md_doc = (
            f"# score report\n\n"
            f"**RENDERER ERROR** ({type(exc).__name__}: {exc}) — markdown omitted; "
            f"JSON verdict is authoritative. Not a green report.\n"
        )
    return json_doc, md_doc


# Committed freeze tree: ordinary score must not write beside a run-record that
# lives here (VLM6-E-05 / rg-002). Diagnostics already force out/; primary reports
# must do the same so `make eval-anchor-check` cannot clobber the freeze.
_COMMITTED_SCORE_REPORT_MARKERS: tuple[str, ...] = (
    "/docs/tasks/vlm/bakeoff-results",
    "docs/tasks/vlm/bakeoff-results",
)
# golden.json harness size — not Golden-100; adoption PASS is refused (EVAL-04).
_HARNESS_ANCHOR_CORPUS_SIZE = 37


def _is_committed_report_tree(path: Path) -> bool:
    """True when ``path`` resolves under the committed bakeoff-results freeze tree."""
    resolved = path.resolve().as_posix()
    return any(marker in resolved for marker in _COMMITTED_SCORE_REPORT_MARKERS)


def _score_report_base(record_path: Path) -> Path:
    """Stem path for caption/face report artifacts written by score / score-face.

    VLM6-E-05: when the run-record lives under the committed freeze tree, write
    reports to git-ignored ``OUT_DIR`` instead of beside the freeze. Elsewhere
    (tmp/out operator runs) keep the historical sibling-of-record layout.
    """
    record_path = Path(record_path)
    if _is_committed_report_tree(record_path.parent):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        return OUT_DIR / record_path.stem
    return record_path.with_suffix("")


def _refuse_report_overwrite(paths: list[Path], *, allow: bool, label: str) -> None:
    """Fail closed when an ordinary score would clobber a committed freeze (VLM6-E-05).

    Operator tmp/out re-scores may overwrite freely. Only paths under the committed
    bakeoff-results tree are protected (rg-002).
    """
    if allow:
        return
    protected = [p for p in paths if p.exists() and _is_committed_report_tree(p)]
    if not protected:
        return
    listed = ", ".join(str(p) for p in protected)
    # Stable class token first (RF-04 / rg-015); label is suffix only.
    _score_gate_fail(
        f"{SCORE_GATE_PREFIX_REFUSE_OVERWRITE} {label}: existing committed "
        f"report(s) would be clobbered ({listed}); pass --allow-overwrite-report "
        f"to opt in (freezes must not be rewritten by ordinary score; reports "
        f"for freeze run-records default to OUT_DIR)"
    )


def _cmd_score(args: argparse.Namespace) -> None:
    _reject_llm_judge(args)
    record_path = Path(args.run_record)
    record = json.loads(record_path.read_text())
    # Metadata-only: score_run_record/build_reports use must_right/easy_wrong/roster/policy;
    # image bytes already live in the run-record and are never re-opened here.
    manifest = load_manifest(args.manifest, skip_hash_verification=True)
    # Fill document annotation_mode only when the dump has no stamp.
    # Unconditional assign clobbers a real per-entry stamp (S2R6E-04).
    # No explicit kwarg — the stamp is the only score-time source
    # (FIR-11-S2-01 / S2R2-10).
    entries = []
    for e in manifest.entries:
        row = e.model_dump()
        if row.get("annotation_mode") is None:
            row["annotation_mode"] = manifest.annotation_mode
        entries.append(row)
    # Stamp the report with the manifest actually scored against, and verify it
    # against the run record's fetch-time sha instead of copying it blind (S3-04).
    manifest_sha = _manifest_sha(manifest)
    ignore_list = _load_ignore_list(record_path.parent)
    roster = sorted(set(getattr(manifest, "roster", []) or []))
    # Operator-declared Must-Right gate mode (F1b-2 / F1-12). Default enforce.
    # Harness-shakedown / seeded-stub runs must pass --rubric-gate skip explicitly;
    # never infer exemption from adapter/model_id (rg-009).
    rubric_gate = getattr(args, "rubric_gate", RUBRIC_GATE_ENFORCE) or RUBRIC_GATE_ENFORCE
    is_public = getattr(args, "audience", Audience.LOCAL.value) == Audience.PUBLIC.value
    # F2d / GATE-05: when --check-determinism is set, the documents written are
    # exactly the documents the cross-process guard certified (one build).
    # rubric_gate + audience must match the operator flags — pre-F2d the guard
    # always certified LOCAL/enforce while disk could say skip/public.
    public_json: str | None = None
    public_md: str | None = None
    # F5 / B-06: --expect-report is opt-in frozen JSON for the LOCAL document only
    # (PUBLIC has no committed caption anchor; face freeze is score-face path).
    # Requires --check-determinism.
    expect_report_raw = getattr(args, "expect_report", None)
    # fx8: --freeze-certification is byte-stability certification only. It must
    # pair with --expect-report (and therefore --check-determinism). Without an
    # external freeze, the flag would silently skip adoption gates with no
    # byte-stability claim left to certify (TEST-15 / EVAL-13).
    freeze_certification = bool(getattr(args, "freeze_certification", False))
    if freeze_certification and not expect_report_raw:
        sys.exit("score: --freeze-certification requires --expect-report")
    if expect_report_raw and not args.check_determinism:
        sys.exit("score: --expect-report requires --check-determinism")
    expect_report = Path(expect_report_raw) if expect_report_raw else None
    allow_manifest_relabel = bool(getattr(args, "allow_manifest_relabel", False))
    allow_overwrite_report = bool(getattr(args, "allow_overwrite_report", False))
    # Post-cert folds that re-serialise the document (schema / evidence / relabel).
    # When True under --freeze-certification the certified bytes are not the
    # written bytes — refuse freeze exit (S1-03 / OBS-04).
    degraded = False
    if args.check_determinism:
        local_json, local_md = _check_score_determinism_cross_process(
            record_path,
            args.manifest,
            rubric_gate=rubric_gate,
            audience=Audience.LOCAL,
            label="score",
            expect_report=expect_report,
        )
        scored = json.loads(local_json)
        # Schema hard-keys fold into the verdict before write. On a clean report
        # this is a no-op and certified bytes == written bytes. On hard-key drift
        # the fold mutates the in-memory dict; we re-serialize so the fail
        # artifact is correct (OBS-04). That re-serialize is post-certification
        # and only fires when schema hard-keys are already broken — not the
        # normal determinism path.
        schema_exit = _fold_schema_errors_into_verdict(scored)
        evidence_exit = _fold_evidence_gates_into_verdict(scored, record)
        relabel_exit = _fold_manifest_drift_into_verdict(
            scored, allow_manifest_relabel=allow_manifest_relabel
        )
        degraded = schema_exit is not None or evidence_exit is not None or relabel_exit is not None
        if degraded:
            # Schema-degraded docs may lack hard keys the MD renderer expects;
            # tolerate only when verdict is already fail (JSON remains authoritative).
            local_json, local_md = _serialize_score_docs(scored, tolerate_renderer_error=True)
        if is_public:
            # No --expect-report on PUBLIC: committed freeze is LOCAL only.
            public_json, public_md = _check_score_determinism_cross_process(
                record_path,
                args.manifest,
                rubric_gate=rubric_gate,
                audience=Audience.PUBLIC,
                label="score-public",
            )
    else:
        # F1d-1 / OBS-04: score once, fold every exit condition into the verdict,
        # THEN serialise. No gate may fire against a report that still claims pass.
        scored = score_run_record(
            record,
            entries,
            ignore_list=ignore_list,
            score_manifest_sha256=manifest_sha,
            manifest_roster=roster,
            rubric_gate=rubric_gate,
        )
        schema_exit = _fold_schema_errors_into_verdict(scored)
        evidence_exit = _fold_evidence_gates_into_verdict(scored, record)
        relabel_exit = _fold_manifest_drift_into_verdict(
            scored, allow_manifest_relabel=allow_manifest_relabel
        )
        degraded = schema_exit is not None or evidence_exit is not None or relabel_exit is not None
        local_json, local_md = _serialize_score_docs(scored, tolerate_renderer_error=degraded)
        if is_public:
            public_json, public_md = build_reports(
                record,
                entries,
                ignore_list=ignore_list,
                score_manifest_sha256=manifest_sha,
                manifest_roster=roster,
                audience=Audience.PUBLIC,
                rubric_gate=rubric_gate,
            )
    # VLM6-A-04: PUBLIC must carry the same folded LOCAL verdict so the two
    # artifacts can never disagree (schema/evidence/manifest-relabel folds).
    if is_public and public_json is not None:
        public_scored = json.loads(public_json)
        public_scored["verdict"] = dict(scored.get("verdict") or {})
        public_degraded = (scored.get("verdict") or {}).get("verdict") == ScoreVerdict.FAIL.value
        public_json, public_md = _serialize_score_docs(
            public_scored, tolerate_renderer_error=public_degraded
        )
    # VLM6-E-05: do not write beside a committed freeze by default; refuse
    # overwrite of any existing report without an explicit opt-in.
    base = _score_report_base(record_path)
    json_path, md_path = Path(f"{base}-report.json"), Path(f"{base}-report.md")
    public_json_path = Path(f"{base}-report.public.json")
    public_md_path = Path(f"{base}-report.public.md")
    overwrite_targets = [json_path, md_path]
    if is_public:
        overwrite_targets.extend([public_json_path, public_md_path])
    _refuse_report_overwrite(overwrite_targets, allow=allow_overwrite_report, label="score")
    # JSON is the load-bearing Slice-2 artifact (OBS-04). Write it first so a
    # schema-degraded document still leaves a fail verdict on disk even if the
    # human markdown renderer cannot tolerate missing hard-keyed fields.
    json_path.write_text(local_json)
    md_path.write_text(local_md)
    # VLM-6 S5 W1 (VLM6-C-01 / VLM6-F-03): audience-aware export. Additive — the
    # full LOCAL report above is always written (operator triage + the failure gate
    # below score the whole corpus); --audience public ALSO emits a redacted,
    # publishable-only artifact. This is the sole sanctioned eval->public path,
    # the prerequisite that makes the rd.altcontext.com gallery (RND-1) safe.
    if is_public and public_json is not None and public_md is not None:
        public_json_path.write_text(public_json)
        public_md_path.write_text(public_md)
        print(public_md_path)
    print(md_path)
    verdict = scored.get("verdict") or {}
    det = scored["faces"]["detection"]
    if det.get("refused"):
        det_bit = f"detection=REFUSED({det.get('invariant')})"
    else:
        det_bit = (
            f"detection_p={det.get('precision')} "
            f"detection_r={det.get('recall')}"
        )
    ident = scored["faces"]["identification"]
    if ident.get("refused"):
        id_bit = f"identification=REFUSED({ident.get('invariant')})"
    else:
        id_bit = f"wrong_names={len(ident['wrong_names'])}"
    print(
        f"scored={scored['counts']['scored']}/{scored['counts']['total']} "
        f"insertion_rate={scored['caption']['insertion_rate']} "
        f"{id_bit} "
        f"{det_bit} "
        f"verdict={verdict.get('verdict', 'unknown')} "
        f"wrong_name_rate={verdict.get('wrong_name_rate')} "
        f"wrong_name_rate_floor={verdict.get('wrong_name_rate_floor', WRONG_NAME_RATE_FLOOR)} "
        f"rubric_gate={rubric_gate}"
    )
    # --- Measurement-integrity gates (always exit-determining) ---
    # S1-01 / S1-02: --freeze-certification softens adoption quality only. Schema,
    # aborted, failed-items, zero-scored, truncation, and manifest integrity still
    # set exit status — byte-stability of a measurement that did not run is not
    # a certification (EVAL-13 / TEST-15 / rg-005).
    if schema_exit is not None:
        _score_gate_fail(schema_exit)
    # evidence_exit / relabel_exit are folded into the written verdict above;
    # path-bearing messages below are the operator-facing class tokens (TEST-15).
    _ = evidence_exit
    # VLM6-F-03 / EVAL-13: fetch/score manifest drift hard-fails unless the
    # operator explicitly opted into archival relabel (non_comparable verdict).
    if relabel_exit is not None:
        _score_gate_fail(f"{relabel_exit} (see {json_path})")
    # VLM6-S2A-A-02: aborted records must never green-exit (partial evidence).
    if record.get("aborted"):
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_ABORTED_RECORD} run-record is aborted "
            f"(partial evidence only; see {json_path}); refusing to certify"
        )
    # Fail loud when any item was skipped from scoring (S7-01): a "passing" run
    # that dropped NFC-miss / remote errors must not look like full-corpus evidence.
    # Gate names are distinct so a red run says which corruption class fired (VLM-6 S2A).
    # Order: failed-items before zero-scored so all-error items keep the
    # failed-items class token (scored=0 ∧ failed>0 is not vacuous evidence —
    # it is a partial failure surface). Zero-scored covers empty items only.
    failed = int(scored["counts"]["failed"])
    if failed > 0:
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_FAILED_ITEMS} {failed} item(s) not scored "
            f"(see failures[] in {json_path}); "
            "refusing to treat a partial corpus as full eval evidence"
        )
    scored_n = int(scored["counts"]["scored"])
    if scored_n == 0:
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_ZERO_SCORED} scored=0 items (counts.total="
            f"{scored['counts'].get('total', 0)}); no evidence to certify "
            f"(see {json_path})"
        )
    # Corpus truncation via partial run-record (fetch --limit N): media-id multiset
    # must match the score-time manifest. counts.total alone is self-referential
    # (scored=5/5) and previously exited 0 with a full-corpus fetch sha (F1-2 / r08116b50).
    # F1d-4: corpus-integrity keys live under scored["corpus"], not counts.
    corpus = scored.get("corpus") or {}
    media_id_missing = int(corpus.get("media_id_missing") or 0)
    media_id_extra = int(corpus.get("media_id_extra") or 0)
    if media_id_missing or media_id_extra:
        manifest_n = int(corpus.get("manifest_entries") or 0)
        record_n = int(scored.get("counts", {}).get("total") or 0)
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_TRUNCATION} run-record media-id multiset differs "
            f"from manifest "
            f"(missing={media_id_missing}, extra={media_id_extra}; "
            f"record_items={record_n}, manifest_entries={manifest_n}; see {json_path})"
        )
    # Fetch-time provenance self-consistency (record must name its own manifest).
    # Score-time vs fetch-time digest equality is the VLM6-F-03 hard gate above
    # (relabel_exit / --allow-manifest-relabel); do not soft-warn here.
    fetch_manifest_sha = scored.get("provenance", {}).get("manifest_sha256")
    if not fetch_manifest_sha:
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_MANIFEST_MISMATCH} run-record provenance missing "
            f"fetch-time "
            f"manifest_sha256 — record is not self-consistent with its fetch provenance "
            f"(see {json_path})"
        )
    # Archival relabel path: verdict is non_comparable and must not green-exit as
    # a certifiable pass (compare rejects it; process still exits non-zero so an
    # operator cannot mistake it for adoption-ready output).
    if (scored.get("verdict") or {}).get("verdict") == ScoreVerdict.NON_COMPARABLE.value:
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_MANIFEST_RELABEL} "
            f"verdict={ScoreVerdict.NON_COMPARABLE.value} "
            f"(archival relabel only; not adoption-comparable; see {json_path})"
        )
    # fx8 / gx1 / EVAL-13 / TEST-15: under --freeze-certification the exit code
    # means scoring-path byte-stability once measurement integrity has passed.
    # Adoption gates below stay computed and printed (verdict / wrong_name_rate /
    # coverage gaps) but do not set exit status — the freeze is often a
    # deliberately imperfect non-evidential fixture. Live score without this flag
    # keeps every gate hard (sr-001).
    # S1-03: refuse freeze-cert when a post-cert fold re-serialised the document
    # (certified bytes ≠ written bytes). Integrity gates above usually already
    # failed for those folds; this is the explicit boundary.
    if freeze_certification:
        if degraded:
            _score_gate_fail(
                f"{SCORE_GATE_PREFIX_FREEZE_CERT_REFUSED} post-cert fold re-serialised "
                "the document (schema/evidence/relabel); certified bytes are not "
                f"the written bytes (see {json_path}); not a frozen scoring path"
            )
        print(
            "freeze-certification passed [score]: scoring-path is byte-stable "
            f"(matches --expect-report); nothing certified about model quality, "
            f"face recognition, or adoption readiness "
            f"(artifact verdict={verdict.get('verdict', 'unknown')}; "
            "integrity gates enforced above; adoption gates computed below, "
            "not exit-determining)"
        )
        return
    # --- Adoption-quality gates (soft under --freeze-certification) ---
    # Empty rubric: Must-Right and Easy-Wrong vacuity are independent. Emptying
    # only must_right while easy_wrong remains used to leave the OR'd counter
    # non-zero and exit 0 (F1-1 / r08116b50). A warning is not a gate.
    must_right_defined = int(scored.get("caption", {}).get("must_right_defined_images") or 0)
    easy_wrong_defined = int(scored.get("caption", {}).get("easy_wrong_defined_images") or 0)
    if must_right_defined == 0:
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_EMPTY_RUBRIC} must_right is vacuous corpus-wide "
            f"(must_right_defined_images=0); caption hard gate is vacuous (see {json_path})"
        )
    if easy_wrong_defined == 0:
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_EMPTY_RUBRIC} easy_wrong is vacuous corpus-wide "
            f"(easy_wrong_defined_images=0); wrong-name trap is vacuous (see {json_path})"
        )
    # Schema hard-keys already folded above (pre-write). Re-read gate inputs from
    # the validated scored dict for the remaining exit messages.
    must_right_failed = int(scored["caption"]["must_right_failed_images"])
    # F1b-2 / F1-12: simple must-right failures gate. Any failed must_right image
    # exits non-zero under --rubric-gate enforce (default). The F1-11 conjunction
    # (rate==1.0 ∧ mean_gated==0.0) was false-green on plain garbage against real
    # golden.json: mean_gated measures easy_wrong trap avoidance, and the 3
    # no-must_right entries score gated 1.0 regardless of caption content
    # (garbage and seeded both ~0.0811). Content-based discrimination is
    # impossible here — the seeded stub's captions have near-zero overlap with
    # base_caption — so harness-shakedown exemption is an explicit operator
    # declaration (--rubric-gate skip), recorded in the artifact, never inferred
    # from adapter/model_id (rg-009). The seeded report already discloses it is
    # "harness-shakedown numbers, NOT a caption-model baseline."
    if rubric_gate == RUBRIC_GATE_ENFORCE and must_right_failed > 0:
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_MUST_RIGHT_FAILURES} {must_right_failed} image(s) "
            f"failed Must-Right "
            f"caption hard-gate (caption corruption / missing required names; see {json_path})"
        )
    # F1-5 / EVAL-19: wrong-name floor is vacuous when images were scored but zero
    # entered identification counting (recognition_enabled false corpus-wide).
    # Distinct token from empty-rubric so a red run names the correct class.
    ident_block = (scored.get("faces") or {}).get("identification") or {}
    identification_evaluated = int(ident_block.get("evaluated_images") or 0)
    # VLM6-DELTA-03: a structurally refused identification block (boxed GT
    # missing / roster_only mode) serialises evaluated_images=None, which
    # collapses to int(0) above — indistinguishable from a genuinely
    # evaluated-but-zero corpus (recognition_enabled false corpus-wide).
    # Refusal already has its own consent-gated exit via
    # raise_if_unconsented_refusals below; this vacuity gate must not
    # pre-empt that per-metric consent check for the refused case, or
    # --allow-refused=identification becomes structurally unreachable
    # whenever identification is refused (see test_cli_exit_gates.py
    # S2R5-05 tests).
    if scored_n > 0 and not ident_block.get("refused") and identification_evaluated == 0:
        excluded_n = len(ident_block.get("excluded_images") or [])
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_WRONG_NAME_FLOOR_VACUITY} identification denominator "
            f"is empty "
            f"(evaluated_images=0, excluded_images={excluded_n}); "
            f"wrong-name floor is vacuous — no image contributed to identification "
            f"(recognition_enabled false corpus-wide or none scored; see {json_path})"
        )
    # VLM-6 S2A: wrong-name floor — hallucinated human names on photographs are
    # the highest-severity failure this harness detects; gate, do not merely report.
    # F1-7: never gate on the rounded serialised rate. When floor is 0.0, gate on
    # wrong-name *count* so 1 wrong among ≥20001 images cannot round to 0.0 and
    # silence the floor (TEST-15). Unrounded rate is used only for non-zero floors.
    # Rate numerator includes ignore-list-triaged pairs (F1-5 / OBS-04).
    floor = float(verdict.get("wrong_name_rate_floor", WRONG_NAME_RATE_FLOOR))
    wrong_n = _total_wrong_name_count(ident_block)
    unrounded_rate = face_wrong_name_rate(scored)
    if floor == 0.0:
        floor_breach = wrong_n > 0
    else:
        floor_breach = unrounded_rate > floor
    if floor_breach:
        ignored_n = len(ident_block.get("ignored_wrong_names") or [])
        # Message shows the display rate from the artifact for operator triage,
        # but the breach decision above did not consume the rounded value.
        display_rate = verdict.get("wrong_name_rate", unrounded_rate)
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_WRONG_NAME_FLOOR} wrong_name_rate={display_rate} "
            f"exceeds "
            f"floor={floor} (ignored_wrong_names={ignored_n}; see {json_path})"
        )
    # VLM6-OBS-04 (live path): process exit must match the persisted artifact.
    # A corpus with vacuous critical categories writes verdict=not_ready;
    # green-exiting over that artifact re-opens the same class of defect one
    # layer out (EVAL-23). Adoption-eligible exits remain pass / pass_ungated
    # only. Under --freeze-certification the return above already ran after
    # integrity gates: adoption fail/not_ready may green-exit by design when
    # scoring-path bytes match the freeze (fx8); integrity failures still
    # non-zero so process exit matches the integrity half of the artifact.
    verdict_value = (scored.get("verdict") or {}).get("verdict")
    # RV1-01 / S2-02 / EVAL-04: quality-floor breaches are stamped into the
    # artifact as verdict=fail + quality-floor: reasons by report.py, but were
    # never wired into the exit path. Sample-size vacuity (not_ready) already
    # exits non-zero; quality floors must use the same gate machinery so a
    # shell that keys on score's exit status cannot green-light a failing run.
    # Soft under --freeze-certification (return above). Class-unique prefix
    # SCORE_GATE_PREFIX_QUALITY_FLOOR matches the exit-prefix table in README.
    verdict_reasons = list((scored.get("verdict") or {}).get("reasons") or [])
    quality_floor_reasons = [r for r in verdict_reasons if str(r).startswith("quality-floor:")]
    if quality_floor_reasons:
        reason_hint = "; ".join(quality_floor_reasons[:3])
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_QUALITY_FLOOR} {reason_hint} "
            f"(verdict={ScoreVerdict.FAIL.value}; not adoption-eligible; see {json_path})"
        )
    # VLM6-DELTA-03 / VLM6-GATE-INT-01 (category-vacuity / identification-refused
    # interaction): a refused identification block (boxed GT missing / unboxed
    # roster) drags identification-derived categories (positional,
    # identity_ordering, face_identification.*) into not_ready — the
    # category-vacuity message for *those* categories would be a noisy
    # restatement of the same refusal already reported, per-metric, by
    # raise_if_unconsented_refusals below. A structurally refused detection
    # (roster_only) does the same for face_detection.* — but only when
    # detection *also* refused; detection-only refusal (roster_only mode,
    # identification still boxed/measurable) stays surgical, so
    # face_detection.* keeps firing there (S2R5-13 case B). Narrowing the
    # exemption to identification/detection-derived reasons — instead of
    # skipping the whole gate whenever identification refuses — is required so
    # an UNRELATED vacuous category (sample-size, placement, fabricated_fact,
    # caption categories) still hard-fails even when identification is
    # structurally refused (VLM6-GATE-INT-01: skipping the entire gate let a
    # not_ready artifact with e.g. sample-size/placement vacuity exit 0).
    # --allow-refused must also stay per-metric (S2R5-05): naming only one of
    # two refused metrics must still reach raise_if_unconsented_refusals's
    # per-metric message/exit 3, and naming both must reach its clean-return
    # exit 0 — a category-vacuity gate blind to consent state would hard-fail
    # both cases identically.
    if verdict_value == ScoreVerdict.NOT_READY.value:
        reasons = list((scored.get("verdict") or {}).get("reasons") or [])
        if ident_block.get("refused"):
            detection_block = (scored.get("faces") or {}).get("detection") or {}
            detection_refused = bool(detection_block.get("refused"))
            reasons = [
                r
                for r in reasons
                if not _is_identification_restatement_reason(
                    r, detection_refused=detection_refused
                )
            ]
        if reasons:
            reason_hint = "; ".join(reasons[:3])
            _score_gate_fail(
                f"{SCORE_GATE_PREFIX_CATEGORY_VACUITY} "
                f"verdict={ScoreVerdict.NOT_READY.value} "
                f"({reason_hint}; not adoption-eligible; see {json_path})"
            )
    raise_if_unconsented_refusals(
        scored, getattr(args, "allow_refused", None), command="score"
    )



def _cmd_run(args: argparse.Namespace) -> None:
    # C-06 / OBS-04: --check-determinism is honoured per scored leg (each
    # provider matrix record is an independent artifact). Announce the child
    # multiplier *before* paid fetch and before the first child spawns so the
    # operator sees legs × seeds before wall clock pays — not a silent tax.
    # Per-leg (not once) is deliberate: a single check would leave other legs
    # uncertified under a flag that claims certification.
    if getattr(args, "check_determinism", False):
        providers: list[str | None] = list(dict.fromkeys(args.provider)) if args.provider else [None]
        n_legs = len(providers)
        n_seeds = len(_DEFAULT_DETERMINISM_CHILD_SEEDS)
        is_public = getattr(args, "audience", Audience.LOCAL.value) == Audience.PUBLIC.value
        audiences_per_leg = 2 if is_public else 1
        n_children = n_legs * n_seeds * audiences_per_leg
        if audiences_per_leg > 1:
            mult = f"{n_legs} legs × {n_seeds} seeds × {audiences_per_leg} audiences"
        else:
            mult = f"{n_legs} legs × {n_seeds} seeds"
        print(
            f"run --check-determinism: per-leg certification — {mult} "
            f"= {n_children} fresh interpreter(s) before scoring completes"
        )
    # VLM6-S2A-B-10: score every fetched record; do not abort the loop on the
    # first gate failure. Collect per-record gate messages and exit once.
    gate_failures: list[str] = []
    for record_path in _cmd_fetch(args):
        args.run_record = record_path
        try:
            _cmd_score(args)
        except ScoreGateError as exc:
            gate_failures.append(f"{record_path}: {exc}")
            # Fixed prefix; path after colon (RF-05 / rg-006).
            print(
                f"{SCORE_GATE_PREFIX_RUN_RECORD} {record_path}: {exc}",
                file=sys.stderr,
            )
    if gate_failures:
        summary = "; ".join(gate_failures)
        sys.exit(
            f"{SCORE_GATE_PREFIX_RUN_SUMMARY} {len(gate_failures)} record(s): {summary}"
        )


def _cmd_seed_roster(args: argparse.Namespace) -> None:
    base_url, api_key, tenant_id = _require_live_env()
    client = RemoteSceneClient(base_url=base_url, api_key=api_key, tenant_id=tenant_id)
    try:
        summary = seed(args.entities, client, tenant_id=tenant_id)
    finally:
        client.close()
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    if summary.unlabeled_roster_names:
        sys.exit(f"seeding incomplete: unlabeled roster names {summary.unlabeled_roster_names}")


def _cmd_seed_scenes(args: argparse.Namespace) -> None:
    base_url, api_key, tenant_id = _require_live_env()
    images_dir = _images_dir()
    client = RemoteSceneClient(base_url=base_url, api_key=api_key, tenant_id=tenant_id)
    try:
        summary = seed_scenes(args.manifest, images_dir, client)
    finally:
        client.close()
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True))
    if summary.unverified_media_ids:
        sys.exit(f"seeding incomplete: no identity rows detected for media_ids {summary.unverified_media_ids}")


class _FaceLegBundle(NamedTuple):
    """One bake-off leg wired for the walker + twin pass (leg-parameterized provenance)."""

    detector: Any
    aligner: Any
    embedder: Any
    model_id: str
    leg_mode: str | None
    # Non-candidate legs pin the twin landmark cache to the candidate-family
    # YuNet (EXP-08); None → the leg detector doubles as the cache detector.
    cache_detector: Any | None


_EVAL_BENCH_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _build_buffalo_leg() -> _FaceLegBundle:
    """Preflight + construct the fused buffalo_l baseline leg (FIR-1 head-to-head).

    PROV-01: buffalo run-records hold 512D embeddings of private images — they
    stay in git-ignored ``out/``; only score reports are promoted to
    ``docs/tasks/vlm/bakeoff-results/``.
    """
    if os.environ.get("ACX_EVAL_BENCH", "").strip().lower() not in _EVAL_BENCH_TRUTHY:
        sys.exit(
            "face-bakeoff --leg buffalo requires ACX_EVAL_BENCH=1 (SC-1: the buffalo_l "
            "incumbent is an eval-only reference leg). Set ACX_EVAL_BENCH=1 and install "
            "the [bench] extra first: uv sync --extra bench"
        )
    if importlib.util.find_spec("insightface") is None:
        sys.exit(
            "face-bakeoff --leg buffalo: insightface is not installed. Install the "
            "[bench] extra (uv sync --extra bench) and keep ACX_EVAL_BENCH=1. Model "
            "weights resolve via INSIGHTFACE_CACHE_DIR / INSIGHTFACE_HOME (root dir "
            "containing models/buffalo_l/), else ~/.insightface"
        )
    from .buffalo_bench import BUFFALO_LEG_MODE, BUFFALO_MODEL_ID, build_baseline_leg

    detector, aligner, embedder = build_baseline_leg()
    return _FaceLegBundle(
        detector=detector,
        aligner=aligner,
        embedder=embedder,
        model_id=BUFFALO_MODEL_ID,
        leg_mode=BUFFALO_LEG_MODE,
        cache_detector=build_pinned_cache_detector(),
    )


def _build_face_leg(leg: str) -> _FaceLegBundle:
    if leg == "buffalo":
        return _build_buffalo_leg()
    detector, aligner, embedder = build_candidate_leg()
    return _FaceLegBundle(
        detector=detector,
        aligner=aligner,
        embedder=embedder,
        model_id=CANDIDATE_MODEL_ID,
        leg_mode=None,
        cache_detector=None,
    )


def _cmd_face_bakeoff(args: argparse.Namespace) -> None:
    """Offline leg walk → face_run_record JSON in out/ (no tenant writes)."""
    # Leg preflight first: --leg buffalo failures (env flag / [bench] extra) must
    # surface before unrelated GOLDEN_IMAGES_DIR / manifest errors.
    leg = _build_face_leg(args.leg)
    images_dir = _images_dir()
    # Pixel path: walk_face_run_record / build_occlusion_twin_pairs read image bytes.
    manifest = load_manifest(args.manifest, images_dir=images_dir)
    detector, aligner, embedder = leg.detector, leg.aligner, leg.embedder
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    try:
        record = walk_face_run_record(
            manifest,
            images_dir,
            detector=detector,
            embedder=embedder,
            aligner=aligner,
            model_id=leg.model_id,
            head_sha=_head_sha(),
            limit=args.limit,
            stall_limit=args.stall_limit,
            started_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            # rg-015: dim comes from the leg's embedder (the producer), so an
            # injected leg with a different space cannot mislabel the record.
            embedding_dim=getattr(embedder, "embedding_dim", None),
            leg=args.leg,
            leg_mode=leg.leg_mode,
        )
    except FaceBoundedStallError as exc:
        record = exc.partial_record
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"face-run-{stamp}-aborted.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        prune_out_dir(str(OUT_DIR), keep=args.keep)
        print(path)
        sys.exit(f"FaceBoundedStallError: {exc}")
    # FIR5GL-01: synthetic occlusion twin pass — generate/render twins from the
    # frozen landmark cache, re-detect+embed the occluded pixels with the SAME
    # leg, and stamp document-level pair inputs (never items — EVAL-16 firewall).
    twin_pairs, twin_prov = build_occlusion_twin_pairs(
        manifest,
        images_dir,
        detector=detector,
        embedder=embedder,
        aligner=aligner,
        limit=args.limit,
        # EXP-08: non-candidate legs keep the twin universe pinned to the
        # candidate-family YuNet cache (None → leg detector, candidate case).
        cache_detector=leg.cache_detector,
    )
    record["provenance"]["occlusion_twin_pass"] = twin_prov
    if twin_pairs:
        record["occlusion_twin_pairs_by_tag"] = twin_pairs
    record = validate_face_run_record(record)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"face-run-{stamp}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    prune_out_dir(str(OUT_DIR), keep=args.keep)
    print(path)
    print(
        f"face-bakeoff items={len(record['items'])} "
        f"leg={record['provenance'].get('leg')} "
        f"model_id={record['provenance'].get('model_id')} "
        f"occlusion_twin_pairs={twin_prov['n_pairs']} "
        f"twin_errors={len(twin_prov['errors'])}"
    )


def _face_score_once(
    record: dict[str, Any],
    manifest: GoldenManifest,
    *,
    score_manifest_sha256: str,
    public: bool,
) -> tuple[str, str]:
    # FIR5GL-01: twins ride the record; real pairs derive from tagged entries.
    synth_pairs, real_pairs = occlusion_inputs_from_record(record, manifest)
    return build_face_reports(
        record,
        manifest,
        score_manifest_sha256=score_manifest_sha256,
        occlusion_pairs_by_tag=synth_pairs,
        real_occlusion_pairs_by_tag=real_pairs,
        public=public,
    )


def _check_face_determinism_cross_process(
    record_path: Path,
    manifest_path: str,
    *,
    public: bool,
    expect_report: Path | None = None,
) -> tuple[str, str]:
    """Re-run score-face in a FRESH process under varied PYTHONHASHSEED (§G).

    Subprocess loop lives in ``_run_determinism_children`` (C-08) so caption and
    face gates share seed/env/timeout/error taxonomy and differ only by label.

    When ``expect_report`` is set (CLI ``--expect-report``), after seed-stability
    the certified face JSON is compared to those frozen bytes (F6 / B-06). Same
    three outcomes as caption (ERROR / FAILED / ANCHOR_MISMATCH) via the shared
    ``_check_expect_report`` helper — no fork. Mismatch is ANCHOR_MISMATCH.
    """
    # F2C-01: resolve data paths; child cwd is package-root pin (F2c).
    resolved_record = record_path.resolve()
    resolved_manifest = Path(manifest_path).resolve()
    # Baseline: current process
    record = json.loads(resolved_record.read_text())
    # Metadata-only: face score uses face_count/tags/boxes from record + manifest fields;
    # never opens image files (embeddings already in the face run-record).
    manifest = load_manifest(str(resolved_manifest), skip_hash_verification=True)
    manifest_sha = _manifest_sha(manifest)
    base_json, base_md = _face_score_once(record, manifest, score_manifest_sha256=manifest_sha, public=public)

    # Final argv entry is the parent-allocated payload path (F2b out-of-band).
    # build_reports_file carries build_face_reports provenance (F2c).
    script = (
        "import json,sys; "
        "from pathlib import Path; "
        "from scripts.eval_harness.manifest import load_manifest; "
        "from scripts.eval_harness.cli import _manifest_sha; "
        "from scripts.eval_harness.report import build_face_reports, occlusion_inputs_from_record; "
        "rec=json.loads(open(sys.argv[1]).read()); "
        # Metadata-only: child face re-score never opens image bytes.
        "man=load_manifest(sys.argv[2],skip_hash_verification=True); "
        "pub=sys.argv[3]=='1'; "
        "sp,rp=occlusion_inputs_from_record(rec,man); "
        "j,m=build_face_reports(rec,man,score_manifest_sha256=_manifest_sha(man),"
        "occlusion_pairs_by_tag=sp,real_occlusion_pairs_by_tag=rp,public=pub); "
        "Path(sys.argv[4]).write_text(json.dumps({"
        "'json':j,'md':m,"
        "'build_reports_file':build_face_reports.__code__.co_filename}))"
    )
    # Defer seed-stability pass when a frozen compare follows (same as caption).
    # Diagnostics always land in out/ — never beside a committed freeze (F7-01).
    det_artifact_dir = _determinism_artifact_dir()
    regime = _run_determinism_children(
        script,
        [str(resolved_record), str(resolved_manifest), "1" if public else "0"],
        label="score-face",
        base_json=base_json,
        base_md=base_md,
        artifact_dir=det_artifact_dir,
        expected_build_reports_file=build_face_reports.__code__.co_filename,
        announce_pass=expect_report is None,
    )
    if expect_report is not None:
        _check_expect_report(
            base_json,
            Path(expect_report),
            label="score-face",
            regime=regime,
            artifact_dir=det_artifact_dir,
            regen_cmd=_FACE_DETERMINISM_ANCHOR_REGEN_CMD,
        )
    return base_json, base_md


def _cmd_score_face(args: argparse.Namespace) -> None:
    """Pure offline face score over the full unfiltered corpus (§G)."""
    record_path = Path(args.run_record)
    record = json.loads(record_path.read_text())
    if record.get("kind") == DocKind.FACE_RUN_RECORD.value:
        validate_face_run_record(record)
    # Metadata-only: score_face_run_record / build_face_reports use tags, face_count,
    # present_identities, and record-side embeddings — never open image bytes.
    manifest = load_manifest(args.manifest, skip_hash_verification=True)
    manifest_sha = _manifest_sha(manifest)
    public = bool(getattr(args, "public", False))
    allow_overwrite_report = bool(getattr(args, "allow_overwrite_report", False))
    # F6 / B-06: --expect-report is opt-in frozen face-report JSON. Requires
    # --check-determinism (same coupling as caption score).
    expect_report_raw = getattr(args, "expect_report", None)
    # fx8: same freeze-certification contract as caption score (byte-stability
    # exit only; requires --expect-report).
    freeze_certification = bool(getattr(args, "freeze_certification", False))
    if freeze_certification and not expect_report_raw:
        sys.exit("score-face: --freeze-certification requires --expect-report")
    if expect_report_raw and not args.check_determinism:
        sys.exit("score-face: --expect-report requires --check-determinism")
    expect_report = Path(expect_report_raw) if expect_report_raw else None
    # When --check-determinism is set, write the certified documents (one build).
    if args.check_determinism:
        json_doc, md_doc = _check_face_determinism_cross_process(
            record_path,
            args.manifest,
            public=public,
            expect_report=expect_report,
        )
    else:
        json_doc, md_doc = _face_score_once(record, manifest, score_manifest_sha256=manifest_sha, public=public)
    # VLM6-A-06: audience-suffixed face report paths (mirror caption reports).
    # --public must not clobber the unsuffixed LOCAL artifact.
    base = _score_report_base(record_path)
    if public:
        json_path = Path(f"{base}-face-report.public.json")
        md_path = Path(f"{base}-face-report.public.md")
    else:
        json_path = Path(f"{base}-face-report.json")
        md_path = Path(f"{base}-face-report.md")
    _refuse_report_overwrite([json_path, md_path], allow=allow_overwrite_report, label="score-face")
    json_path.write_text(json_doc)
    md_path.write_text(md_doc)
    # VLM6-A-07 / TEST-15: gate on a read-back of the written artifact — never a
    # second score_face_run_record re-derive. Serialisation bugs must go red.
    try:
        scored = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_FACE_REPORT_READBACK} cannot read back written "
            f"face report {json_path}: {exc}"
        )
    if not isinstance(scored, dict):
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_FACE_REPORT_READBACK} written face report is not "
            f"a JSON object (see {json_path})"
        )
    scored_n = int((scored.get("counts") or {}).get("scored") or 0)
    failed = int((scored.get("counts") or {}).get("failed") or 0)
    total_n = int((scored.get("counts") or {}).get("total") or 0)
    matched_faces = (scored.get("counts") or {}).get("matched_faces", "?")
    occlusion_eligible = 0
    slices = scored.get("slices") or {}
    for block in (slices.get("occlusion") or {}).values():
        if isinstance(block, dict):
            occlusion_eligible += int((block.get("synthetic") or {}).get("n_eligible") or 0)
    directional_excluded = len((scored.get("gate_proposal") or {}).get("excluded_directional") or [])
    print(md_path)
    print(
        f"scored={scored_n}/{total_n} "
        f"matched_faces={matched_faces} "
        f"occlusion_n_eligible={occlusion_eligible} "
        f"directional_excluded={directional_excluded}"
    )
    # --- Measurement-integrity gates (always exit-determining; S1-01) ---
    # Face score has no adoption-quality gates today — freeze-certification only
    # softens a future adoption surface; integrity stays hard under the flag.
    # Shared prefixes with caption score (VLM6-R2-F-03 / rg-015): face-specific
    # tokens live in the suffix so one grep still catches both paths.
    if record.get("aborted"):
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_ABORTED_RECORD} score-face: run-record is aborted "
            f"(partial evidence only; see {json_path}); refusing to certify"
        )
    if scored_n == 0:
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_ZERO_SCORED} score-face: scored=0 items "
            f"(counts.total={total_n}); "
            f"no evidence to certify (see {json_path})"
        )
    if failed > 0:
        _score_gate_fail(
            f"{SCORE_GATE_PREFIX_FAILED_ITEMS} score-face: {failed} item(s) not "
            f"scored (see failures[] in {json_path})"
        )
    # fx8 / gx1 / EVAL-13: under --freeze-certification exit = scoring-path
    # byte-stability after integrity gates above have passed.
    if freeze_certification:
        print(
            "freeze-certification passed [score-face]: scoring-path is byte-stable "
            "(matches --expect-report); nothing certified about model quality, "
            "face recognition, or adoption readiness "
            "(integrity gates enforced above; not an adoption softener)"
        )
        return
    raise_if_unconsented_refusals(
        scored, getattr(args, "allow_refused", None), command="score-face"
    )


# Adoption meet-or-beat metric tables (VLM6-E-01 / A-03 / EVAL-23).
# insertion_rate is LOWER-is-better: inserted / (inserted + missing) counts
# hallucinated identities (VLM6-E-01 polarity fix).
# Higher candidate values meet-or-beat the baseline.
_COMPARE_HIGHER_IS_BETTER: tuple[tuple[str, ...], ...] = (
    ("caption", "mean_gated_score"),
    ("faces", "detection", "precision"),
    ("faces", "detection", "recall"),
    ("faces", "identification", "precision"),
    ("faces", "identification", "recall"),
    ("faces", "identification", "positional", "position_accuracy"),
    ("faces", "identification", "positional", "exact_order_rate"),
    ("placement", "accuracy"),
    ("faces", "identity_ordering", "positional_images"),
)
# Lower candidate values meet-or-beat the baseline.
_COMPARE_LOWER_IS_BETTER: tuple[tuple[str, ...], ...] = (
    ("caption", "insertion_rate"),
    ("caption", "must_right_failed_images"),
    ("verdict", "wrong_name_rate"),
    ("hallucination", "fabricated_fact_rate"),
    ("hallucination", "fabricated_fact_rate_trapped"),
    ("faces", "identity_ordering", "degraded_images"),
)
# Baseline verdicts that may anchor an adoption decision (rg-005 / sr-007).
_COMPARE_ADOPTION_ELIGIBLE_VERDICTS: frozenset[str] = frozenset({ScoreVerdict.PASS.value})
# Protocol pins that must match across baseline and candidate (EVAL-13).
_COMPARE_PROTOCOL_PATHS: tuple[tuple[str, ...], ...] = (
    ("eval_mode",),
    ("provenance", "score_manifest_sha256"),
    ("verdict", "rubric_gate"),
    ("provenance", "prompt_variant"),
    ("provenance", "two_pass"),
    ("provenance", "dual_length"),
    ("provenance", "face_gate"),
)


def _nested_get(doc: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = doc
    for key in path:
        if not isinstance(cur, Mapping) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _nested_number(doc: Mapping[str, Any], path: tuple[str, ...]) -> float | None:
    cur = _nested_get(doc, path)
    if isinstance(cur, bool) or not isinstance(cur, (int, float)):
        return None
    return float(cur)


def _compare_require_caption_report(doc: Mapping[str, Any], *, role: str) -> list[str]:
    """Structural checks for a caption score report (rg-005 / rg-008)."""
    errors: list[str] = []
    schema = doc.get("schema")
    kind = doc.get("kind")
    if schema != SCHEMA:
        errors.append(f"{role}: not a caption score report (schema={schema!r}, expected {SCHEMA!r})")
    if kind != DocKind.REPORT.value:
        errors.append(f"{role}: not a caption score report (kind={kind!r}, expected {DocKind.REPORT.value!r})")
    counts = doc.get("counts")
    if not isinstance(counts, Mapping):
        errors.append(f"{role}: counts missing or not an object")
    else:
        for key in ("total", "scored", "failed"):
            if not isinstance(counts.get(key), int) or isinstance(counts.get(key), bool):
                errors.append(f"{role}: counts.{key} missing or not an int")
    if not isinstance(doc.get("provenance"), Mapping):
        errors.append(f"{role}: provenance missing or not an object")
    if not isinstance(doc.get("verdict"), Mapping):
        errors.append(f"{role}: verdict missing or not an object")
    if not isinstance(doc.get("caption"), Mapping):
        errors.append(f"{role}: caption missing or not an object")
    if not isinstance(doc.get("faces"), Mapping):
        errors.append(f"{role}: faces missing or not an object")
    return errors


def _compare_non_degenerate_corpus(doc: Mapping[str, Any], *, role: str) -> list[str]:
    """Refuse vacuous / truncated corpus counts (EVAL-04)."""
    errors: list[str] = []
    counts = doc.get("counts") or {}
    total = counts.get("total")
    scored = counts.get("scored")
    failed = counts.get("failed")
    if not isinstance(total, int) or total <= 0:
        errors.append(f"{role}: non-degenerate corpus requires counts.total > 0 (got {total!r})")
    if not isinstance(scored, int) or scored <= 0:
        errors.append(f"{role}: non-degenerate corpus requires counts.scored > 0 (got {scored!r})")
    if isinstance(failed, int) and failed > 0:
        errors.append(f"{role}: non-degenerate corpus requires counts.failed == 0 (got {failed})")
    corpus = doc.get("corpus") or {}
    if isinstance(corpus, Mapping):
        missing = corpus.get("media_id_missing")
        extra = corpus.get("media_id_extra")
        if isinstance(missing, int) and missing > 0:
            errors.append(f"{role}: corpus.media_id_missing={missing} (truncated / partial record)")
        if isinstance(extra, int) and extra > 0:
            errors.append(f"{role}: corpus.media_id_extra={extra} (record not on manifest)")
    return errors


def _compare_protocol_mismatches(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    """Pin judging protocol equality (EVAL-13): manifest digest / mode / audience keys."""
    errors: list[str] = []
    for path in _COMPARE_PROTOCOL_PATHS:
        label = ".".join(path)
        b = _nested_get(baseline, path)
        c = _nested_get(candidate, path)
        # Absent-on-both is fine (pre-Slice-2 anchors); present-on-one or diverge is not.
        if b is None and c is None:
            continue
        if b != c:
            errors.append(f"protocol mismatch {label}: baseline={b!r} candidate={c!r}")
    # Audience redaction stamp (when either side is a PUBLIC export).
    b_aud = ((baseline.get("redaction") or {}) if isinstance(baseline.get("redaction"), Mapping) else {}).get(
        "audience"
    )
    c_aud = ((candidate.get("redaction") or {}) if isinstance(candidate.get("redaction"), Mapping) else {}).get(
        "audience"
    )
    if b_aud != c_aud:
        errors.append(f"protocol mismatch redaction.audience: baseline={b_aud!r} candidate={c_aud!r}")
    return errors


def _compare_vacuous_categories(doc: Mapping[str, Any], *, role: str) -> list[str]:
    """Categories whose claim units have π=0 must block adoption (AUDIT-07 / EVAL-23).

    Shared with ``build_score_verdict`` via ``score_vacuous_category_labels`` /
    ``fabricated_fact_is_vacuous`` (S2-01 / S2-06 / rg-005): score and compare
    must not disagree on which axes are non-observable.
    """
    labels = score_vacuous_category_labels(doc, include_verdict_fields=True)
    hall = doc.get("hallucination") if isinstance(doc.get("hallucination"), Mapping) else {}
    traps = int(hall.get("images_with_traps") or 0)
    out: list[str] = []
    for label in labels:
        if label == "placement":
            out.append(f"{role}:placement (accuracy=None or claims=0; π=0 on spatial_facts)")
        elif label == "positional_identification":
            out.append(f"{role}:positional_identification (position_accuracy=None or compared_images=0)")
        elif label == "identity_ordering":
            out.append(f"{role}:identity_ordering (positional_images=0; order metric non-observable)")
        elif label == "fabricated_fact":
            out.append(
                f"{role}:fabricated_fact (no trap denominator or rate=None; images_with_traps={traps})"
            )
        else:
            out.append(f"{role}:{label} (None — category not observed)")
    return out


def _compare_harness_anchor_size(doc: Mapping[str, Any]) -> bool:
    """True when counts match the 37-item golden.json harness (not Golden-100)."""
    counts = doc.get("counts") or {}
    scored = counts.get("scored")
    total = counts.get("total")
    return scored == _HARNESS_ANCHOR_CORPUS_SIZE and total == _HARNESS_ANCHOR_CORPUS_SIZE


def _cmd_compare(args: argparse.Namespace) -> None:
    """Meet-or-beat adoption gate: candidate vs baseline caption score report.

    Fail-closed on protocol / corpus / vacuity / polarity (VLM6-E-01 / A-02 / A-03;
    EVAL-13 / EVAL-23 / EVAL-04 / rg-005 / rg-008). Exit non-zero on any regression
    or non-adoption status — never print adoption PASS for a category that was
    not observed.
    """
    baseline_path = Path(args.baseline)
    candidate_path = Path(args.candidate)
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"compare: failed to load report JSON: {exc}")
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        sys.exit("compare: baseline and candidate must be JSON objects")

    # --- same-corpus / schema / protocol hard checks (VLM6-A-02 / F-02) ---
    structural: list[str] = []
    structural.extend(_compare_require_caption_report(baseline, role="baseline"))
    structural.extend(_compare_require_caption_report(candidate, role="candidate"))
    if structural:
        sys.exit("compare same-corpus gate: " + "; ".join(structural))

    structural.extend(_compare_non_degenerate_corpus(baseline, role="baseline"))
    structural.extend(_compare_non_degenerate_corpus(candidate, role="candidate"))
    if structural:
        sys.exit("compare same-corpus gate: " + "; ".join(structural))

    protocol = _compare_protocol_mismatches(baseline, candidate)
    if protocol:
        sys.exit("compare same-corpus gate: " + "; ".join(protocol))

    b_verdict = (baseline.get("verdict") or {}).get("verdict")
    if b_verdict not in _COMPARE_ADOPTION_ELIGIBLE_VERDICTS:
        sys.exit(
            f"compare adoption gate: baseline verdict={b_verdict!r} is not adoption-eligible "
            f"(require one of {sorted(_COMPARE_ADOPTION_ELIGIBLE_VERDICTS)}; "
            f"pass_ungated / non_comparable / fail baselines cannot certify a candidate)"
        )
    c_verdict = (candidate.get("verdict") or {}).get("verdict")
    if c_verdict == ScoreVerdict.NON_COMPARABLE.value:
        sys.exit(
            f"compare adoption gate: candidate verdict={ScoreVerdict.NON_COMPARABLE.value} "
            f"(archival relabel; not adoption-comparable)"
        )
    # fail is still comparable for regression reporting; other statuses block.
    if c_verdict not in _COMPARE_ADOPTION_ELIGIBLE_VERDICTS and c_verdict != ScoreVerdict.FAIL.value:
        sys.exit(
            f"compare adoption gate: candidate verdict={c_verdict!r} is not adoption-comparable"
        )

    # --- harness-37 / Golden-100 readiness (VLM6-A-03 / EVAL-04) ---
    if _compare_harness_anchor_size(baseline) or _compare_harness_anchor_size(candidate):
        sys.exit(
            f"compare adoption: NOT_ADOPTION_ELIGIBLE corpus=harness-{_HARNESS_ANCHOR_CORPUS_SIZE} "
            f"(golden.json anchor; Golden-100 required for adoption-shaped PASS; EVAL-04)"
        )

    # --- vacuous categories block adoption (VLM6-A-03 / EVAL-23) ---
    vacuous = _compare_vacuous_categories(baseline, role="baseline") + _compare_vacuous_categories(
        candidate, role="candidate"
    )
    if vacuous:
        sys.exit(
            "compare adoption: BLOCKED non_observable_categories — "
            + "; ".join(vacuous)
            + " (a gate that cannot observe a category must not certify it; EVAL-23)"
        )

    # --- polarity-correct meet-or-beat across every adoption category ---
    regressions: list[str] = []
    comparisons: list[str] = []
    for path in _COMPARE_HIGHER_IS_BETTER:
        label = ".".join(path)
        b = _nested_number(baseline, path)
        c = _nested_number(candidate, path)
        if b is None or c is None:
            regressions.append(f"{label}: missing/vacuous (baseline={b}, candidate={c})")
            continue
        comparisons.append(f"{label}: baseline={b} candidate={c} (higher-better)")
        if c + 1e-12 < b:
            regressions.append(f"{label}: candidate {c} < baseline {b}")
    for path in _COMPARE_LOWER_IS_BETTER:
        label = ".".join(path)
        b = _nested_number(baseline, path)
        c = _nested_number(candidate, path)
        if b is None or c is None:
            regressions.append(f"{label}: missing/vacuous (baseline={b}, candidate={c})")
            continue
        comparisons.append(f"{label}: baseline={b} candidate={c} (lower-better)")
        if c > b + 1e-12:
            regressions.append(f"{label}: candidate {c} > baseline {b}")

    for line in comparisons:
        print(line)
    if regressions:
        sys.exit("compare regression gate: candidate fails meet-or-beat vs baseline — " + "; ".join(regressions))
    print(f"compare meet-or-beat: PASS candidate={candidate_path} baseline={baseline_path}")


def _held_out_fraction_arg(raw: str) -> float:
    """argparse type: open interval (0, 1). Pure assign_split accepts the closed range."""
    value = float(raw)
    if not 0 < value < 1:
        raise argparse.ArgumentTypeError("must satisfy 0 < f < 1")
    return value


def _service_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_manifest_path_for_artifact(manifest_arg: str) -> str:
    """Path relative to the service dir when under it; otherwise the argument as given."""
    given = Path(manifest_arg)
    try:
        return given.resolve().relative_to(_service_root()).as_posix()
    except ValueError:
        return manifest_arg


def _collect_exposure_notes(notes: list[str] | None, exposure_file: str | None) -> list[str]:
    collected = list(notes or [])
    if exposure_file:
        collected.extend(Path(exposure_file).read_text().splitlines())
    return collected


_SPLIT_HASH_SKIP_REASON = "split seal pins sha256 metadata; image bytes never opened"
_DEFAULT_HELD_OUT_FRACTION = 0.5


def _cmd_draw_eval_split(args: argparse.Namespace) -> None:
    """Draw or verify a sealed eval split. Sealed artifacts are never silently redrawn."""
    from .strata import draw_eval_split, verify_eval_split

    # images_dir="" disables GOLDEN_IMAGES_DIR resolution (manifest.py order 1
    # beats env). Metadata-only: seal pins sha256; image bytes never opened.
    manifest = load_manifest(
        args.manifest,
        images_dir="",
        skip_hash_verification=True,
        hash_skip_reason=_SPLIT_HASH_SKIP_REASON,
    )
    out = Path(args.out)
    if args.check:
        artifact = json.loads(out.read_text())
        source_sha = hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest()
        violations = verify_eval_split(
            artifact,
            manifest,
            source_manifest_sha256=source_sha,
            expected_seed=args.seed,
            expected_held_out_fraction=args.held_out_fraction,
            expected_draw_timestamp=args.draw_timestamp,
            expected_partition_provenance=args.partition_provenance,
        )
        for message in violations:
            print(message)
        if violations:
            raise SystemExit(1)
        return

    if not args.seed or not args.draw_timestamp:
        print("draw mode requires --seed and --draw-timestamp", file=sys.stderr)
        raise SystemExit(2)
    if not args.partition_provenance:
        print("draw mode requires --partition-provenance", file=sys.stderr)
        raise SystemExit(2)
    if out.exists() and not args.force:
        print(f"refusing to overwrite sealed split {out} without --force", file=sys.stderr)
        raise SystemExit(3)

    fraction = args.held_out_fraction if args.held_out_fraction is not None else _DEFAULT_HELD_OUT_FRACTION
    source_path = _source_manifest_path_for_artifact(args.manifest)
    source_sha = hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest()
    artifact = draw_eval_split(
        manifest,
        seed=args.seed,
        held_out_fraction=fraction,
        draw_timestamp=args.draw_timestamp,
        source_manifest_path=source_path,
        source_manifest_sha256=source_sha,
        pre_split_exposure=_collect_exposure_notes(args.exposure_note, args.exposure_file),
        partition_provenance=args.partition_provenance,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="eval_harness", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--manifest",
            default="scene/tests/seed/golden.json",
            help=(
                "score/fetch-time corpus man (default: shared 37-entry golden seed). "
                "Caption determinism freeze must pass the bakeoff-results caption man "
                "S2A-determinism-anchor-manifest-* (golden+media-39 trap), not bare "
                "golden.json — otherwise manifest-drift / scored=37/38 (wG3 / rg-006). "
                "Live run/fetch keep the golden default."
            ),
        )
        p.add_argument("--limit", type=_limit_arg, default=None, help="cap images (must be >= 1)")
        p.add_argument("--stall-limit", type=int, default=DEFAULT_STALL_LIMIT)
        p.add_argument("--keep", type=_keep_arg, default=DEFAULT_KEEP)
        p.add_argument("--llm-judge", action="store_true", help="stub — not implemented (§6c)")
        # C-06: --check-determinism is NOT on _common. Only score/run/score-face
        # honour it; fetch accepting it was a silent no-op (paid green that
        # certified nothing). argparse free-rejects unknown flags — keep that.

    def _check_determinism_flag(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--check-determinism",
            action="store_true",
            help=(
                "re-score in a fresh process under varied PYTHONHASHSEED; "
                "bit-identical JSON/MD required before the report is trusted"
            ),
        )

    def _audience_flag(p: argparse.ArgumentParser) -> None:
        # score/run only. LOCAL (default) writes the full operator report unchanged;
        # PUBLIC additionally emits a redacted publishable-only public artifact.
        p.add_argument(
            "--audience",
            choices=(Audience.LOCAL.value, Audience.PUBLIC.value),
            default=Audience.LOCAL.value,
            help=(
                "local (default) writes the full operator report; public ALSO emits a "
                "redacted publishable-only <run>-report.public.{json,md} (the only sanctioned "
                "eval->public path)"
            ),
        )

    def _provider_flags(p: argparse.ArgumentParser) -> None:
        # fetch/run only — score is pure/offline and must not accept paid-run flags.
        p.add_argument(
            "--provider",
            action="append",
            type=_provider_value,
            default=None,
            help=(
                "hosted description profile the target service is serving; verified against each "
                "response's provider_disclosure. Repeatable, but the server profile is fixed per "
                "deployment — each matrix leg needs the service reconfigured between invocations"
            ),
        )
        p.add_argument(
            "--cost-per-image",
            type=float,
            default=None,
            help="provider's published per-request price (USD); stamps est_cost_usd into provenance",
        )
        p.add_argument(
            "--max-cost",
            type=float,
            default=None,
            help="whole-invocation cap: abort before any paid call that would push estimated spend (USD) past it",
        )

    fetch_p = sub.add_parser("fetch", help="manifest -> remote calls -> run record")
    _common(fetch_p)
    _provider_flags(fetch_p)
    fetch_p.set_defaults(func=_cmd_fetch)

    def _rubric_gate_flag(p: argparse.ArgumentParser) -> None:
        # score/run only. enforce (default) hard-gates on any must_right failure;
        # skip bypasses that gate only (other gates still fire). Mode is recorded
        # in the report/verdict so a skipped run is never readable as a gated pass.
        p.add_argument(
            "--rubric-gate",
            choices=RUBRIC_GATE_CHOICES,
            default=RUBRIC_GATE_ENFORCE,
            help=(
                "enforce (default): exit non-zero when any must_right image fails; "
                "skip: bypass the must-right failures gate only (harness-shakedown / "
                "seeded-stub exemption by declaration; recorded in report.verdict)"
            ),
        )

    def _allow_refused_flag(p: argparse.ArgumentParser) -> None:
        named = ", ".join(member.value for member in RefusedMetric)
        p.add_argument(
            "--allow-refused",
            action="append",
            nargs="?",
            const=ALLOW_REFUSED_ALL,
            type=_parse_allow_refused_metric,
            metavar="METRIC",
            help=(
                "exit 0 for the named refused metric. Repeatable "
                f"(--allow-refused=detection --allow-refused=identification). "
                f"Bare --allow-refused is equivalent to naming every metric "
                f"({named}). Default: refused metrics exit 3 — a missing "
                "score is not clean evaluation evidence"
            ),
        )

    score_p = sub.add_parser("score", help="run record -> reports (pure, offline)")
    _common(score_p)
    _audience_flag(score_p)
    _rubric_gate_flag(score_p)
    _check_determinism_flag(score_p)
    score_p.add_argument("--run-record", required=True)
    score_p.add_argument(
        "--expect-report",
        default=None,
        metavar="PATH",
        help=(
            "with --check-determinism: require the certified LOCAL score JSON to "
            "match this frozen report byte-for-byte (opt-in; no sibling inference). "
            "Mismatch is ANCHOR_MISMATCH — corrupt freeze/record or deliberate "
            "scoring change — not seed FAILED and not environment ERROR"
        ),
    )
    score_p.add_argument(
        "--freeze-certification",
        action="store_true",
        help=(
            "byte-stability certification mode (fx8 / EVAL-13): requires "
            "--expect-report; exit code is determined solely by the determinism + "
            "expect-report comparison. Adoption quality gates are still computed "
            "and printed but do not set the exit status. Certifies scoring-path "
            "byte-stability only — not model quality or adoption readiness. "
            "Live score without this flag keeps every adoption gate hard (sr-001)"
        ),
    )
    score_p.add_argument(
        "--allow-manifest-relabel",
        action="store_true",
        help=(
            "archival only (VLM6-F-03 / EVAL-13): allow scoring when "
            "provenance.manifest_matches_fetch is false; persists verdict=non_comparable "
            "(rejected by compare). Default: hard-fail the score gate on manifest drift"
        ),
    )
    score_p.add_argument(
        "--allow-overwrite-report",
        action="store_true",
        help=(
            "permit overwriting an existing score report beside the run-record "
            "(VLM6-E-05). Default: refuse so committed freezes cannot be clobbered"
        ),
    )
    _allow_refused_flag(score_p)
    score_p.set_defaults(func=_cmd_score)

    run_p = sub.add_parser("run", help="fetch then score")
    _common(run_p)
    _provider_flags(run_p)
    _audience_flag(run_p)
    _rubric_gate_flag(run_p)
    _check_determinism_flag(run_p)
    _allow_refused_flag(run_p)
    run_p.set_defaults(func=_cmd_run)

    seed_p = sub.add_parser("seed-roster", help="idempotent eval-tenant roster seeding")
    seed_p.add_argument("--entities", required=True, help="<GOLDEN_IMAGES_DIR>/mock_entities")
    seed_p.set_defaults(func=_cmd_seed_roster)

    scenes_p = sub.add_parser("seed-scenes", help="idempotent eval-tenant scene-image seeding (E19-4a bboxes)")
    scenes_p.add_argument("--manifest", default="scene/tests/seed/golden.json")
    scenes_p.set_defaults(func=_cmd_seed_scenes)

    face_bo = sub.add_parser(
        "face-bakeoff",
        help="offline face walk (detect→align→embed) → face_run_record (FIR-5; no tenant writes)",
    )
    face_bo.add_argument("--manifest", default="scene/tests/seed/golden.json")
    face_bo.add_argument("--limit", type=_limit_arg, default=None)
    face_bo.add_argument("--stall-limit", type=int, default=DEFAULT_STALL_LIMIT)
    face_bo.add_argument("--keep", type=_keep_arg, default=DEFAULT_KEEP)
    face_bo.add_argument(
        "--leg",
        choices=("candidate", "buffalo"),
        default="candidate",
        help=(
            "face leg (candidate=YuNet+SFace; buffalo=InsightFace buffalo_l fused baseline — "
            "requires ACX_EVAL_BENCH=1 + the [bench] extra; PROV-01: buffalo run-records hold "
            "512D embeddings of private images and stay in git-ignored out/)"
        ),
    )
    face_bo.set_defaults(func=_cmd_face_bakeoff)

    score_face_p = sub.add_parser(
        "score-face",
        help="face run-record → face report (pure, offline; full unfiltered corpus)",
    )
    score_face_p.add_argument(
        "--manifest",
        default="scene/tests/seed/golden.json",
        help=(
            "score-time face man (default: golden seed — unsuitable for the synthetic "
            "face freeze: golden has 0 face_boxes). Face freeze must pass "
            "S2A-face-determinism-anchor-manifest-* under bakeoff-results (see README)."
        ),
    )
    score_face_p.add_argument("--run-record", required=True)
    score_face_p.add_argument(
        "--check-determinism",
        action="store_true",
        help="re-score in a fresh process under varied PYTHONHASHSEED; bit-identical JSON/MD required",
    )
    score_face_p.add_argument(
        "--expect-report",
        default=None,
        metavar="PATH",
        help=(
            "with --check-determinism: require the certified face score JSON to "
            "match this frozen report byte-for-byte (opt-in; no sibling inference). "
            "Mismatch is ANCHOR_MISMATCH — corrupt freeze/record or deliberate "
            "scoring change — not seed FAILED and not environment ERROR"
        ),
    )
    score_face_p.add_argument(
        "--freeze-certification",
        action="store_true",
        help=(
            "byte-stability certification mode (fx8 / EVAL-13): requires "
            "--expect-report; exit code is determined solely by the determinism + "
            "expect-report comparison. Integrity/adoption gates are still printed "
            "but do not set the exit status. Certifies scoring-path byte-stability "
            "only — not model quality or adoption readiness"
        ),
    )
    score_face_p.add_argument(
        "--public",
        action="store_true",
        help="post-score redact via redact_face_report_for_public (never pre-score drop)",
    )
    score_face_p.add_argument(
        "--allow-overwrite-report",
        action="store_true",
        help=(
            "permit overwriting an existing face score report (VLM6-E-05). "
            "Default: refuse so committed freezes cannot be clobbered"
        ),
    )
    _allow_refused_flag(score_face_p)
    score_face_p.set_defaults(func=_cmd_score_face)

    # VLM6-R2-08: baseline-vs-candidate meet-or-beat surface for adoption decisions.
    compare_p = sub.add_parser(
        "compare",
        help="meet-or-beat regression gate: candidate report vs baseline report (offline)",
    )
    compare_p.add_argument(
        "--baseline",
        required=True,
        metavar="PATH",
        help="incumbent score report JSON (same corpus as candidate)",
    )
    compare_p.add_argument(
        "--candidate",
        required=True,
        metavar="PATH",
        help="candidate score report JSON to check against baseline",
    )
    compare_p.set_defaults(func=_cmd_compare)

    draw_split_p = sub.add_parser(
        "draw-eval-split",
        help="draw or verify a sealed eval split (VLM-6 S1; EVAL-07 / MLDATA-09 / EVAL-10)",
    )
    draw_split_p.add_argument("--manifest", required=True)
    draw_split_p.add_argument("--out", required=True)
    draw_split_p.add_argument("--seed", default=None)
    draw_split_p.add_argument("--held-out-fraction", type=_held_out_fraction_arg, default=None)
    draw_split_p.add_argument(
        "--draw-timestamp",
        default=None,
        help="ISO-8601 timestamp; required in draw mode; never defaulted to now",
    )
    draw_split_p.add_argument(
        "--partition-provenance",
        default=None,
        help="required in draw mode; in --check, must equal the artifact when supplied",
    )
    draw_split_p.add_argument("--exposure-note", action="append", default=None)
    draw_split_p.add_argument("--exposure-file", default=None, help="one pre-split exposure note per line")
    draw_split_p.add_argument("--force", action="store_true", help="permit overwriting an existing sealed split")
    draw_split_p.add_argument("--check", action="store_true", help="verify an existing artifact against --manifest")
    draw_split_p.set_defaults(func=_cmd_draw_eval_split)

    args = parser.parse_args(argv)
    if getattr(args, "max_cost", None) is not None and getattr(args, "cost_per_image", None) is None:
        parser.error("--max-cost requires --cost-per-image (the cap is estimated spend; without a price it is a no-op)")
    try:
        args.func(args)
    except ScoreGateError as exc:
        # B-10: score gates raise; standalone score/score-face map to SystemExit
        # so existing tests and operators still see non-zero exits with messages.
        sys.exit(str(exc))
    except (
        ManifestError,
        RemoteClientError,
        BoundedStallError,
        FaceBoundedStallError,
        MaxCostExceededError,
        ProviderMismatchError,
        ReportError,
        FaceRunRecordError,
        PerfLegError,
    ) as exc:
        invariant = getattr(exc, "invariant", None)
        suffix = f" [{invariant}]" if invariant else ""
        sys.exit(f"{type(exc).__name__}: {exc}{suffix}")


if __name__ == "__main__":
    main()
