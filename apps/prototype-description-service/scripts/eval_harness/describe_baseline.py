#!/usr/bin/env python3
"""VLM-6 baseline describe pass — remote Florence CPU (OCI VM), no GPU.

Drives the tested harness ``fetch_run_record`` (describe + face-identity legs) in
small chunks so a multi-hour CPU run is durable, resumable, and appends to the
report as each chunk's descriptions arrive. Reads the canonical attachment
originals list (WP get_attached_file), sends each image to the remote description
service (ACX_EVAL_* creds), and captures caption + identities + face_count +
per-image describe latency into a JSONL + a structured md/json report.

Env: BASELINE_LIMIT (0=all), CHUNK (default 12), HEAD_SHA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

from shared.secrets import get_secret_provider

HERE = Path(__file__).resolve().parent
SCRATCH = HERE / "out"  # gitignored: progressive/resumable JSONL only
# Durable, git-committed results dir (NOT scratchpad — the face-pass was lost once
# by living only in /tmp). JSONL stays in out/ as the progressive/resumable log.
RESULTS = HERE.parents[3] / "docs" / "tasks" / "vlm" / "bakeoff-results"
UPLOADS = Path("/Volumes/Butter/WP/vlm/app/public/wp-content/uploads")
ATTACH_TSV = HERE / "vlm-corpus-attachments-20260716.tsv"
JSONL = SCRATCH / "vlm-baseline-descriptions-20260716.jsonl"
REPORT_JSON = RESULTS / "vlm-baseline-descriptions-20260716.json"
REPORT_MD = RESULTS / "vlm-baseline-descriptions-20260716.md"

CHUNK = int(os.environ.get("CHUNK", "12"))
LIMIT = int(os.environ.get("BASELINE_LIMIT", "0"))  # 0 = all
HEAD_SHA = os.environ.get("HEAD_SHA", "0" * 40)
# Bake-off transport (llama.cpp /v1/chat/completions) selected when BAKEOFF_BASE_URL
# is set; else the api.altcontext.com describe route (ACX_EVAL_*).
BAKEOFF_BASE_URL = os.environ.get("BAKEOFF_BASE_URL", "")
BAKEOFF_MODEL_ID = os.environ.get("BAKEOFF_MODEL_ID", "Qwen3-VL-30B-A3B-Instruct")
BAKEOFF_MODEL_VERSION = os.environ.get("BAKEOFF_MODEL_VERSION", "Q4_K_M")


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
            try:
                ids.add(int(json.loads(line)["media_id"]))
            except Exception:  # noqa: BLE001 — tolerate a torn last line
                pass
    return ids


def _pct(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(q * len(s)))], 3)


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


def _write_report(*, cost_per_image_usd: float | None = None) -> None:
    # Shared with report.py scoring (sr-007): one normalizer for both identity shapes.
    from scripts.eval_harness.cli import identity_names

    rows = [json.loads(ln) for ln in JSONL.read_text().splitlines() if ln.strip()] if JSONL.exists() else []
    for r in rows:  # derive structured mask/sunglasses flags from each caption (report-only)
        r["caption_flags"] = _caption_flags((r.get("describe") or {}).get("alt_text_draft") or "")
    lat = [r["latency_s"] for r in rows if isinstance(r.get("latency_s"), (int, float))]
    ok = [r for r in rows if not r.get("error")]
    with_faces = [r for r in ok if int(r.get("face_count") or 0) > 0]
    completed = [r["completed_at"] for r in rows if r.get("completed_at")]
    wall = (max(completed) - min(completed)) if len(completed) >= 2 else 0.0
    models = sorted({(r.get("describe") or {}).get("model_id") for r in ok if (r.get("describe") or {}).get("model_id")})
    # All rows: runner bills every describe attempt, including failed ones (A-13).
    paid_describe_calls = _paid_describe_calls(rows)
    cost_fields = cost_report_fields(
        cost_per_image_usd=cost_per_image_usd,
        paid_describe_calls=paid_describe_calls,
    )
    summary = {
        "total": len(rows),
        "described_ok": len(ok),
        "errors": len(rows) - len(ok),
        "images_with_faces": len(with_faces),
        "distinct_named_identities": len({n for r in ok for n in identity_names(r.get("identities"))}),
        "images_with_mask": sum(1 for r in ok if "mask" in r.get("caption_flags", [])),
        "images_with_sunglasses": sum(1 for r in ok if "sunglasses" in r.get("caption_flags", [])),
        "describe_latency_s": {
            "mean": round(mean(lat), 3) if lat else None,
            "p50": round(median(lat), 3) if lat else None,
            "p95": _pct(lat, 0.95),
            "p99": _pct(lat, 0.99),
            "max": round(max(lat), 3) if lat else None,
        },
        "wall_clock_s": round(wall, 1),
        "images_per_min": round(len(rows) / (wall / 60), 1) if wall > 0 else None,
        "cost_per_image_usd": cost_fields["cost_per_image_usd"],
        "total_cost_usd": cost_fields["total_cost_usd"],
        "base_url": BAKEOFF_BASE_URL or os.environ.get("ACX_EVAL_BASE_URL"),
        "tenant_id": os.environ.get("ACX_EVAL_TENANT_ID"),
        "model_ids": models,
        "head_sha": HEAD_SHA,
    }
    REPORT_JSON.write_text(json.dumps({"summary": summary, "items": rows}, indent=2, sort_keys=True) + "\n")

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
    lines = [
        f"# VLM-6 baseline descriptions — `{', '.join(models) or 'model'}` @ `{summary['base_url']}`",
        "",
        f"- source: `{UPLOADS}` (all {summary['total']} attachment originals) · "
        f"model provenance: `{', '.join(models) or 'unknown'}` (`{BAKEOFF_MODEL_VERSION}`, adapter=bakeoff)",
        f"- progress: **{summary['described_ok']}/{summary['total']}** described "
        f"({summary['errors']} errors) · images_with_faces: {summary['images_with_faces']} · "
        f"distinct named identities: {summary['distinct_named_identities']}",
        f"- describe latency (s): mean={summary['describe_latency_s']['mean']} "
        f"p50={summary['describe_latency_s']['p50']} p95={summary['describe_latency_s']['p95']} "
        f"p99={summary['describe_latency_s']['p99']} max={summary['describe_latency_s']['max']}",
        f"- wall-clock: {summary['wall_clock_s']}s · throughput: {summary['images_per_min']} images/min",
        cost_line,
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
    REPORT_MD.write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    from scripts.eval_harness.bakeoff import BakeoffClient
    from scripts.eval_harness.cli import BoundedStallError, fetch_run_record
    from scripts.eval_harness.manifest import GoldenEntry, GoldenManifest
    from scripts.eval_harness.remote_client import RemoteSceneClient

    env = os.environ
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--cost-per-image",
        type=float,
        default=None,
        help="provider per-request price (USD); stamps total_cost_usd / cost_per_image_usd "
        "(or set COST_PER_IMAGE_USD). Omit to emit null cost fields.",
    )
    args = parser.parse_args(argv)
    cost_per_image_usd = args.cost_per_image
    if cost_per_image_usd is None:
        cost_per_image_usd = parse_cost_per_image_usd(env.get("COST_PER_IMAGE_USD"))

    RESULTS.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[int, Path]] = []
    for line in ATTACH_TSV.read_text().splitlines():
        if "\t" in line:
            sid, path = line.split("\t", 1)
            rows.append((int(sid), Path(path)))

    done = _done_ids()
    todo = [(mid, p) for (mid, p) in rows if mid not in done and p.exists()]
    if LIMIT:
        todo = todo[:LIMIT]
    print(f"baseline: {len(rows)} attachments, {len(done)} already done, {len(todo)} to describe (chunk={CHUNK})")

    if BAKEOFF_BASE_URL:
        client = BakeoffClient(
            base_url=BAKEOFF_BASE_URL,
            model_id=BAKEOFF_MODEL_ID,
            model_version=BAKEOFF_MODEL_VERSION,
            timeout_s=900,
        )
    else:
        base = os.environ.get("ACX_EVAL_BASE_URL", "")
        # Through SecretProvider (same as face_pass.py / cli.py) — never raw env for secret names.
        key = get_secret_provider().get_secret_optional("ACX_EVAL_API_KEY", "") or ""
        tenant = os.environ.get("ACX_EVAL_TENANT_ID", "")
        if not (base and key and tenant):
            sys.exit("missing ACX_EVAL_BASE_URL / ACX_EVAL_API_KEY / ACX_EVAL_TENANT_ID")
        client = RemoteSceneClient(base_url=base, api_key=key, tenant_id=tenant)
    started = datetime.now(UTC).isoformat()
    try:
        for i in range(0, len(todo), CHUNK):
            chunk = todo[i : i + CHUNK]
            entries = []
            for mid, abspath in chunk:
                rel = str(abspath.relative_to(UPLOADS))
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
            manifest = GoldenManifest(manifest_version=2, roster=[], entries=entries)
            partial = False
            try:
                rec = fetch_run_record(
                    manifest,
                    str(UPLOADS),
                    client,
                    head_sha=HEAD_SHA,
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
            _write_report(cost_per_image_usd=cost_per_image_usd)
            print(f"  chunk {i // CHUNK + 1}: +{len(items)} items ({i + len(chunk)}/{len(todo)})", flush=True)
            if partial:
                print("  bounded-stall abort (endpoint likely down); stopping — rerun to resume.", flush=True)
                break
    finally:
        client.close()
        _write_report(cost_per_image_usd=cost_per_image_usd)
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
