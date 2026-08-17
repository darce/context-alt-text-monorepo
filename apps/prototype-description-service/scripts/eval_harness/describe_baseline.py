#!/usr/bin/env python3
"""VLM-6 baseline describe pass — remote Florence CPU (OCI VM), no GPU.

Drives the tested harness ``fetch_run_record`` (describe + face-identity legs) in
small chunks so a multi-hour CPU run is durable, resumable, and appends to the
report as each chunk's descriptions arrive. Reads the canonical attachment
originals list (WP get_attached_file), sends each image to the remote description
service (ACX_EVAL_* creds), and captures caption + identities + face_count +
per-image describe latency into a JSONL + a structured md/json report.

Env: BASELINE_LIMIT (0=all), CHUNK (default 12), HEAD_SHA, BASELINE_UPLOADS
(WordPress uploads root; required unless --uploads is set).

``HEAD_SHA`` must be a real 40-char hex git SHA when set. There is no fabricated
40-zero default (S4-06 / rg-015 / VLM6-F-04): unset → ``None`` in the report;
explicit forty zeros are refused. Fixture freezes use typed
``fixture_revision`` in the anchor generators — not this live baseline path.

Fail-closed (VLM6-RH-01 / RH-02):
- Missing corpus => non-zero exit; never overwrites a non-empty report with empty.
- Remote write path reuses ``face_pass.assert_scratch_tenant`` (scratch tenant only).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRATCH = HERE / "out"  # gitignored: progressive/resumable JSONL only
# Durable, git-committed results dir (NOT scratchpad — the face-pass was lost once
# by living only in /tmp). JSONL stays in out/ as the progressive/resumable log.
RESULTS = HERE.parents[3] / "docs" / "tasks" / "vlm" / "bakeoff-results"
# No hardcoded operator-laptop uploads path (VLM6-RH-01). Resolve via --uploads
# or BASELINE_UPLOADS only.
ATTACH_TSV = HERE / "vlm-corpus-attachments-20260716.tsv"
JSONL = SCRATCH / "vlm-baseline-descriptions-20260716.jsonl"
REPORT_JSON = RESULTS / "vlm-baseline-descriptions-20260716.json"
REPORT_MD = RESULTS / "vlm-baseline-descriptions-20260716.md"

CHUNK = int(os.environ.get("CHUNK", "12"))
LIMIT = int(os.environ.get("BASELINE_LIMIT", "0"))  # 0 = all
# Resolved at use time via resolve_head_sha() — never default to forty zeros (S4-06).
# Module-level name retained so tests/callers can monkeypatch a concrete value.
HEAD_SHA: str | None = None
# Bake-off transport (llama.cpp /v1/chat/completions) selected when BAKEOFF_BASE_URL
# is set; else the api.altcontext.com describe route (ACX_EVAL_*).
BAKEOFF_BASE_URL = os.environ.get("BAKEOFF_BASE_URL", "")
BAKEOFF_MODEL_ID = os.environ.get("BAKEOFF_MODEL_ID", "Qwen3-VL-30B-A3B-Instruct")
BAKEOFF_MODEL_VERSION = os.environ.get("BAKEOFF_MODEL_VERSION", "Q4_K_M")

def resolve_head_sha(raw: str | None = None) -> str | None:
    """Return an explicit real HEAD SHA, or None when unset (never forty zeros).

    Delegates format / zero-sentinel / git-verify rules to
    ``provenance_sha.normalize_head_sha`` so this path cannot drift from
    ``promote_atomic.validate_live_head_sha`` (fx6 / rg-015).

    - Unset / empty → ``None`` (report writes null; no fabrication).
    - Explicit ``0`` * 40 → hard refuse (S4-06 / rg-015).
    - Any other value must be 40 lowercase hex chars (uppercased input is
      accepted and lowercased).
    - Git verify is **default-on** with degrade when git is missing or cwd is
      not a work tree (RV3-05 / TEST-15).

    Resolution order when *raw* is omitted: ``HEAD_SHA`` env, then the
    module-level ``HEAD_SHA`` (tests may monkeypatch the latter).
    """
    from scripts.eval_harness.provenance_sha import normalize_head_sha

    if raw is None:
        raw = os.environ.get("HEAD_SHA")
        if raw is None:
            raw = HEAD_SHA
    return normalize_head_sha(
        raw,
        empty_policy="none",
        verify_git=True,
        label="HEAD_SHA",
    )

_UPLOADS_MARKERS = ("/wp-content/uploads/", "/uploads/")


def resolve_uploads_root(cli_value: str | None = None) -> Path:
    """Resolve the WordPress uploads corpus root (flag > env; no laptop default).

    Raises SystemExit with an OBS-04 remedy when unset or not a directory.
    """
    raw = (cli_value or "").strip() or os.environ.get("BASELINE_UPLOADS", "").strip()
    if not raw:
        raise SystemExit(
            "uploads corpus root not set: pass --uploads DIR or set BASELINE_UPLOADS "
            "to the WordPress wp-content/uploads directory that holds the corpus images"
        )
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(
            f"uploads corpus root does not exist or is not a directory: {path}. "
            "Pass --uploads DIR or set BASELINE_UPLOADS to a real uploads tree"
        )
    return path


def reanchor_attachment_path(recorded: Path, uploads: Path) -> Path:
    """Map a TSV-recorded absolute path onto the configured uploads root."""
    text = recorded.as_posix()
    for marker in _UPLOADS_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            return uploads / text[idx + len(marker) :]
    if recorded.is_absolute():
        try:
            return uploads / recorded.relative_to(uploads)
        except ValueError:
            return recorded
    return uploads / recorded


def parse_cost_per_image_usd(raw: str | None) -> float | None:
    """Parse an explicit cost-per-image rate; absent/empty => None (never invent)."""
    if raw is None or str(raw).strip() == "":
        return None
    return float(raw)


def cost_report_fields(
    *,
    cost_per_image_usd: float | None,
    paid_describe_calls: int,
) -> dict[str, float | None]:
    """Total + per-image cost fields for the baseline report (null when no rate)."""
    if cost_per_image_usd is None:
        return {"cost_per_image_usd": None, "total_cost_usd": None}
    return {
        "cost_per_image_usd": cost_per_image_usd,
        "total_cost_usd": round(cost_per_image_usd * paid_describe_calls, 6),
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _done_ids() -> set[int]:
    if not JSONL.exists():
        return set()
    ids: set[int] = set()
    for line in JSONL.read_text().splitlines():
        if line.strip():
            # Tolerate a torn last line (partially flushed JSONL append).
            with contextlib.suppress(Exception):
                ids.add(int(json.loads(line)["media_id"]))
    return ids


def _latency_line(block: dict | None) -> str:
    """Render the canonical latency block (VLM6-RH-04). ``None`` = no timed samples."""
    if not block:
        return "- describe latency: no timed samples · wall-clock: n/a"
    return (
        f"- describe latency ({block['unit']}): n={block['n']} mean={block['mean']} "
        f"p50={block['p50']} p95={block['p95']} p99={block['p99']} max={block['max']} · "
        f"wall-clock: {block.get('wall_clock_s')}s · throughput: {block.get('images_per_min')} images/min"
    )


# Structured mask/sunglasses notation derived from the caption. Word-boundary anchored
# so "unmasked"/"mascara" don't false-positive. First-pass signal only — the operator's
# curation tags are the ground truth; a caption that omits the mask still shows here as
# absent, so treat this as recall-limited by what the VLM chose to mention.
_MASK_RE = re.compile(r"\b(masks?|masked|face[- ]?covering|n95|respirators?)\b", re.IGNORECASE)
_SUN_RE = re.compile(r"\b(sun[- ]?glasses|dark glasses|shades)\b", re.IGNORECASE)


def _caption_flags(caption: str) -> list[str]:
    flags = []
    if _MASK_RE.search(caption):
        flags.append("mask")
    if _SUN_RE.search(caption):
        flags.append("sunglasses")
    return flags


def _paid_describe_calls(rows: list[dict[str, object]]) -> int:
    """Count describe attempts; refund cache hits (mirrors cli.fetch_run_record billing).

    cli bills on attempt (``paid_calls += 1`` at cli.py:249, immediately after
    ``describe_started = time.monotonic()`` at :247). ``latency_s`` is the durable
    signal of that attempt: initialised ``None`` (:232), written on success (:256),
    and on the error path only when ``describe_started is not None`` (:270-271).
    Rows that die before describe (missing file, bad dimensions, …) keep
    ``latency_s is None`` and must not be billed — counting every non-cache-hit
    row over-reports on NFC/NFD path failures (FL30-A-16). Refund rule unchanged:
    ``describe.get("cached") is True`` still means refunded. Walk *all* rows so
    thrown describes (``latency_s`` set, ``error`` set) still charge (FL30-A-13).
    """
    paid = 0
    for r in rows:
        if not isinstance(r.get("latency_s"), (int, float)):
            continue
        describe = r.get("describe")
        if isinstance(describe, dict) and describe.get("cached") is True:
            continue
        paid += 1
    return paid


def _atomic_write_text(path: Path, text: str) -> None:
    """Write via temp file + replace so a crash cannot leave a half-written report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _refuse_empty_clobber(path: Path, *, new_empty: bool) -> None:
    """Refuse to replace a non-empty committed report with an empty one (VLM6-RH-01)."""
    if not new_empty:
        return
    if path.exists() and path.stat().st_size > 0:
        raise RuntimeError(
            f"refusing to overwrite non-empty report {path} with an empty report "
            f"(0 items in JSONL). Fix --uploads / BASELINE_UPLOADS so the corpus is "
            f"found before writing, or remove the report only if empty overwrite is intentional"
        )


# Default golden corpus for offline Δ reporting (EVAL-01 / VLM6-C-06).
_DEFAULT_GOLDEN = HERE.parent.parent / "scene" / "tests" / "seed" / "golden.json"


def score_rows_against_golden(
    rows: list[dict[str, object]],
    *,
    golden_path: Path | None = None,
    caption_of: Callable[[dict[str, object]], str] | None = None,
) -> dict[str, object]:
    """Score baseline JSONL rows against the real golden rubric (EVAL-01).

    Returns absolute metrics plus Δ versus a zero-rule (empty-caption) reference
    arm on the same matched media_ids. Fail-closed: when zero rows match the
    golden corpus the delta block is ``status=undefined`` — never a green
    absolute-only report dressed as an improvement claim (VLM6-C-06).
    """
    from scripts.eval_harness.caption_metrics import (
        insertion_rate,
        mean_gated_score,
        score_caption,
    )
    from scripts.eval_harness.manifest import load_manifest

    path = golden_path if golden_path is not None else _DEFAULT_GOLDEN
    if not path.is_file():
        return {
            "status": "undefined",
            "reason": f"golden corpus missing at {path}",
            "matched": 0,
            "candidate": None,
            "zero_rule": None,
            "delta": None,
        }

    manifest = load_manifest(str(path), skip_hash_verification=True)
    by_media = {int(e.media_id): e for e in manifest.entries}
    roster = list(manifest.roster)

    def _cap(row: dict[str, object]) -> str:
        if caption_of is not None:
            return str(caption_of(row) or "")
        describe = row.get("describe") if isinstance(row.get("describe"), dict) else {}
        return str((describe or {}).get("alt_text_draft") or "")

    candidate_scores = []
    zero_scores = []
    matched = 0
    for row in rows:
        if row.get("error"):
            continue
        mid = row.get("media_id")
        try:
            mid_int = int(mid)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        entry = by_media.get(mid_int)
        if entry is None:
            continue
        matched += 1
        policy = entry.policy
        recognition = bool(policy.recognition_enabled) if policy is not None else True
        kwargs = dict(
            present_identities=list(entry.present_identities),
            must_right=list(entry.must_right),
            easy_wrong=list(entry.easy_wrong),
            recognition_enabled=recognition,
            roster=roster,
        )
        candidate_scores.append(score_caption(_cap(row), **kwargs))
        zero_scores.append(score_caption("", **kwargs))

    if matched == 0:
        return {
            "status": "undefined",
            "reason": "no baseline rows matched golden media_ids; cannot compute Δ (EVAL-01)",
            "matched": 0,
            "candidate": None,
            "zero_rule": None,
            "delta": None,
        }

    def _arm(scores: list) -> dict[str, object]:
        must_failed = sum(1 for s in scores if s.must_right_failures)
        wrong = sum(1 for s in scores if s.named_wrong_person)
        return {
            "n": len(scores),
            "insertion_rate": insertion_rate(scores),
            "mean_gated_score": mean_gated_score(scores),
            "must_right_failed_images": must_failed,
            "wrong_name_images": wrong,
        }

    cand = _arm(candidate_scores)
    zero = _arm(zero_scores)

    def _delta(key: str) -> float | None:
        c, z = cand.get(key), zero.get(key)
        if c is None or z is None:
            return None
        return float(c) - float(z)  # type: ignore[arg-type]

    return {
        "status": "ok",
        "reason": None,
        "matched": matched,
        "reference_arm": "zero_rule_empty_caption",
        "candidate": cand,
        "zero_rule": zero,
        "delta": {
            # Positive Δ on gated score / negative Δ on failure rates = improvement.
            "mean_gated_score": _delta("mean_gated_score"),
            "insertion_rate": _delta("insertion_rate"),
            "must_right_failed_images": _delta("must_right_failed_images"),
            "wrong_name_images": _delta("wrong_name_images"),
        },
    }


def _write_report(
    *,
    cost_per_image_usd: float | None = None,
    uploads: Path | None = None,
    golden_path: Path | None = None,
) -> None:
    # Import from report, not cli: report owns the single definition (VLM6-RH-07).
    # Going via cli would pull the whole argparse entrypoint in for one normalizer.
    from scripts.eval_harness.face_metrics import latency_summary
    from scripts.eval_harness.report import identity_names

    rows = [json.loads(ln) for ln in JSONL.read_text().splitlines() if ln.strip()] if JSONL.exists() else []
    if not rows:
        _refuse_empty_clobber(REPORT_JSON, new_empty=True)
        _refuse_empty_clobber(REPORT_MD, new_empty=True)
        raise RuntimeError(
            "refusing to write empty baseline report (0 JSONL rows). "
            "Describe at least one image, or fix --uploads / BASELINE_UPLOADS so the corpus is found"
        )
    for r in rows:  # derive structured mask/sunglasses flags from each caption (report-only)
        r["caption_flags"] = _caption_flags((r.get("describe") or {}).get("alt_text_draft") or "")
    lat = [r["latency_s"] for r in rows if isinstance(r.get("latency_s"), (int, float))]
    ok = [r for r in rows if not r.get("error")]
    with_faces = [r for r in ok if int(r.get("face_count") or 0) > 0]
    completed = [r["completed_at"] for r in rows if r.get("completed_at")]
    wall = (max(completed) - min(completed)) if len(completed) >= 2 else 0.0
    models = sorted(
        {(r.get("describe") or {}).get("model_id") for r in ok if (r.get("describe") or {}).get("model_id")}
    )
    # All rows: runner bills every describe attempt, including failed ones (A-13).
    paid_describe_calls = _paid_describe_calls(rows)
    cost_fields = cost_report_fields(
        cost_per_image_usd=cost_per_image_usd,
        paid_describe_calls=paid_describe_calls,
    )
    # Offline Δ vs zero-rule captioner on the real golden rubric (EVAL-01 / VLM6-C-06).
    rubric_delta = score_rows_against_golden(rows, golden_path=golden_path)
    summary = {
        "total": len(rows),
        "described_ok": len(ok),
        "errors": len(rows) - len(ok),
        "images_with_faces": len(with_faces),
        "distinct_named_identities": len({n for r in ok for n in identity_names(r.get("identities"))}),
        "images_with_mask": sum(1 for r in ok if "mask" in r.get("caption_flags", [])),
        "images_with_sunglasses": sum(1 for r in ok if "sunglasses" in r.get("caption_flags", [])),
        # Canonical cross-runner block (VLM6-RH-04): same schema face_pass and
        # florence_describe emit, so bake-off numbers stack in one table without a
        # per-runner adapter. Replaces the old flat describe_latency_s +
        # top-level wall_clock_s/images_per_min — runs recorded before this change
        # (e.g. vlm-baseline-descriptions-20260716.json) carry the old shape.
        "latency": latency_summary(
            lat,
            unit="s",
            wall_clock_s=wall,
            throughput_n=len(rows),
        ),
        "cost_per_image_usd": cost_fields["cost_per_image_usd"],
        "total_cost_usd": cost_fields["total_cost_usd"],
        "base_url": BAKEOFF_BASE_URL or os.environ.get("ACX_EVAL_BASE_URL"),
        "tenant_id": os.environ.get("ACX_EVAL_TENANT_ID"),
        "model_ids": models,
        # Real git SHA or null — never fabricated forty zeros (S4-06 / rg-015).
        "head_sha": resolve_head_sha(),
        "rubric_delta": rubric_delta,
    }
    payload = json.dumps({"summary": summary, "items": rows}, indent=2, sort_keys=True) + "\n"
    _atomic_write_text(REPORT_JSON, payload)

    if cost_fields["cost_per_image_usd"] is None:
        cost_line = (
            "- cost: total_cost_usd=null · cost_per_image_usd=null "
            "(no rate supplied; pass --cost-per-image or COST_PER_IMAGE_USD — never invent)"
        )
    else:
        cost_line = (
            f"- cost: total=${summary['total_cost_usd']} · "
            f"per-image=${summary['cost_per_image_usd']} "
            f"({paid_describe_calls} paid describe calls)"
        )
    # Δ surface (EVAL-01): never imply improvement from absolute counts alone.
    if rubric_delta.get("status") != "ok":
        delta_line = (
            f"- rubric Δ vs zero-rule: **undefined** "
            f"(matched={rubric_delta.get('matched', 0)}; {rubric_delta.get('reason')})"
        )
    else:
        d = rubric_delta["delta"] or {}
        c = rubric_delta["candidate"] or {}
        delta_line = (
            f"- rubric Δ vs zero-rule empty caption (matched={rubric_delta['matched']}): "
            f"mean_gated_score={c.get('mean_gated_score')} (Δ={d.get('mean_gated_score')}) · "
            f"must_right_failed={c.get('must_right_failed_images')} "
            f"(Δ={d.get('must_right_failed_images')}) · "
            f"insertion_rate={c.get('insertion_rate')} (Δ={d.get('insertion_rate')}) · "
            f"wrong_name_images={c.get('wrong_name_images')} (Δ={d.get('wrong_name_images')})"
        )
    uploads_display = uploads if uploads is not None else Path("(uploads unset)")
    lines = [
        f"# VLM-6 baseline descriptions — `{', '.join(models) or 'model'}` @ `{summary['base_url']}`",
        "",
        f"- source: `{uploads_display}` (all {summary['total']} attachment originals) · "
        f"model provenance: `{', '.join(models) or 'unknown'}` (`{BAKEOFF_MODEL_VERSION}`, adapter=bakeoff)",
        f"- progress: **{summary['described_ok']}/{summary['total']}** described "
        f"({summary['errors']} errors) · images_with_faces: {summary['images_with_faces']} · "
        f"distinct named identities: {summary['distinct_named_identities']}",
        _latency_line(summary["latency"]),
        cost_line,
        delta_line,
        f"- caption-derived flags (first-pass; operator tags = ground truth): "
        f"**mask={summary['images_with_mask']}**, **sunglasses={summary['images_with_sunglasses']}**",
        "",
        "| media_id | file | face_count | identities | flags | latency_s | caption / error |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        fname = Path(r.get("path", "")).name
        cap = (r.get("describe") or {}).get("alt_text_draft") or ""
        cell = r["error"] if r.get("error") else cap.replace("|", "\\|").replace("\n", " ")[:160]
        ids = ", ".join(identity_names(r.get("identities"))) or "—"
        flags = ", ".join(r.get("caption_flags") or []) or "—"
        lines.append(
            f"| {r.get('media_id')} | {fname} | {r.get('face_count')} | {ids} | {flags} | {r.get('latency_s')} | {cell} |"
        )
    _atomic_write_text(REPORT_MD, "\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    from scripts.eval_harness.cli import BoundedStallError, fetch_run_record
    from scripts.eval_harness.face_pass import SeededTenantError, assert_scratch_tenant
    from scripts.eval_harness.manifest import (
        SUPPORTED_MANIFEST_VERSION,
        AnnotationMode,
        GoldenEntry,
        GoldenManifest,
    )

    env = os.environ
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--cost-per-image",
        type=float,
        default=None,
        help="provider per-request price (USD); stamps total_cost_usd / cost_per_image_usd "
        "(or set COST_PER_IMAGE_USD). Omit to emit null cost fields.",
    )
    parser.add_argument(
        "--uploads",
        default=None,
        help="WordPress wp-content/uploads root holding the corpus "
        "(or set BASELINE_UPLOADS). Required; no laptop-absolute default.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="skip assert_scratch_tenant (accept writing face rows into a roster-seeded tenant)",
    )
    args = parser.parse_args(argv)
    cost_per_image_usd = args.cost_per_image
    if cost_per_image_usd is None:
        cost_per_image_usd = parse_cost_per_image_usd(env.get("COST_PER_IMAGE_USD"))

    uploads = resolve_uploads_root(args.uploads)

    RESULTS.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[int, Path]] = []
    for line in ATTACH_TSV.read_text().splitlines():
        if "\t" in line:
            sid, path = line.split("\t", 1)
            rows.append((int(sid), reanchor_attachment_path(Path(path), uploads)))

    found = [(mid, p) for (mid, p) in rows if p.exists()]
    if not found:
        print(
            f"no corpus images found under uploads root {uploads} "
            f"(0 of {len(rows)} attachment paths exist on disk). "
            f"Pass --uploads DIR or set BASELINE_UPLOADS to the WordPress "
            f"wp-content/uploads directory that holds this corpus.",
            file=sys.stderr,
        )
        return 1

    done = _done_ids()
    todo = [(mid, p) for (mid, p) in found if mid not in done]
    if LIMIT:
        todo = todo[:LIMIT]
    print(
        f"baseline: {len(rows)} attachments, {len(found)} on disk, "
        f"{len(done)} already done, {len(todo)} to describe (chunk={CHUNK}) "
        f"uploads={uploads}"
    )

    if not todo:
        # Resume-complete refresh only when JSONL already has work; never invent empty.
        try:
            _write_report(cost_per_image_usd=cost_per_image_usd, uploads=uploads)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print("done (nothing new).")
        return 0

    if BAKEOFF_BASE_URL:
        from scripts.eval_harness.bakeoff import BakeoffClient

        client = BakeoffClient(
            base_url=BAKEOFF_BASE_URL,
            model_id=BAKEOFF_MODEL_ID,
            model_version=BAKEOFF_MODEL_VERSION,
            timeout_s=900,
        )
        # BakeoffClient.analyze is a no-op stub — no MediaIdentity writes.
        needs_tenant_guard = False
    else:
        from scripts.eval_harness.remote_client import RemoteSceneClient

        # VLM-6-S2A-B-11: parity with cli.py and face_pass.py. Reading the key
        # straight from os.environ silently misses vault-backed secrets under
        # RECOGNITION_SECRET_BACKEND=oci_vault, where the provider deliberately
        # refuses env fallback — and the seam guard in
        # recognition/tests/unit/test_no_raw_secret_reads.py fails on the raw read.
        from shared.secrets import get_secret_provider

        base = os.environ.get("ACX_EVAL_BASE_URL", "")
        key = get_secret_provider().get_secret_optional("ACX_EVAL_API_KEY", "") or ""
        tenant = os.environ.get("ACX_EVAL_TENANT_ID", "")
        if not (base and key and tenant):
            sys.exit("missing ACX_EVAL_BASE_URL / ACX_EVAL_API_KEY / ACX_EVAL_TENANT_ID")
        client = RemoteSceneClient(base_url=base, api_key=key, tenant_id=tenant)
        # fetch_run_record -> client.analyze persists face rows (VLM6-RH-02).
        needs_tenant_guard = True

    started = datetime.now(UTC).isoformat()
    work_started = False
    try:
        if needs_tenant_guard and not args.force:
            try:
                assert_scratch_tenant(client)
            except SeededTenantError as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return 2

        for i in range(0, len(todo), CHUNK):
            chunk = todo[i : i + CHUNK]
            entries = []
            for mid, abspath in chunk:
                rel = str(abspath.relative_to(uploads))
                entries.append(
                    GoldenEntry(
                        path=rel,
                        sha256=_sha256(abspath),
                        media_id=mid,
                        face_count=0,
                        present_identities=[],
                        must_right=[],
                        easy_wrong=[],
                        policy={"recognition_enabled": True},
                    )
                )
            # describe_baseline dispatches images only -- it never scores, so no
            # face_boxes exist; roster_only is the neutral no-coverage-claim mode
            # (FIR-11: annotation_mode is a required document-level field).
            manifest = GoldenManifest(
                manifest_version=SUPPORTED_MANIFEST_VERSION,
                annotation_mode=AnnotationMode.ROSTER_ONLY,
                roster=[],
                entries=entries,
            )
            partial = False
            try:
                rec = fetch_run_record(
                    manifest,
                    str(uploads),
                    client,
                    head_sha=resolve_head_sha(),  # None when unset — never "" (HARM-03)
                    started_at=started,
                    cost_per_image_usd=cost_per_image_usd,
                )
                items = rec["items"]
            except BoundedStallError as exc:
                items = exc.partial_record["items"]
                partial = True
            now = time.time()
            with JSONL.open("a") as f:
                for it in items:
                    it["completed_at"] = now
                    f.write(json.dumps(it) + "\n")
            work_started = True
            _write_report(cost_per_image_usd=cost_per_image_usd, uploads=uploads)
            print(f"  chunk {i // CHUNK + 1}: +{len(items)} items ({i + len(chunk)}/{len(todo)})", flush=True)
            if partial:
                print("  bounded-stall abort (endpoint likely down); stopping — rerun to resume.", flush=True)
                break
    finally:
        client.close()
        # Only rewrite reports after real work; never empty-clobber on pre-work failure.
        if work_started:
            try:
                _write_report(cost_per_image_usd=cost_per_image_usd, uploads=uploads)
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 1
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
