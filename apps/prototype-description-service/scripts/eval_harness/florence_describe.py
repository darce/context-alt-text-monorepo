#!/usr/bin/env python3
"""VLM-6 on-box Florence-2 describe driver (CPU-first matrix next-action #6).

Standalone: runs on a dedicated OCI CPU batch VM with only torch / transformers /
pillow installed (``infra/oci/cpu-batch-cloud-init.yaml`` provisions the venv).
No ``scene/`` imports, no service, no network beyond the one-time HF model
download. Copy this single file to the box and run it against the rsynced corpus.

Mirrors the load/generate surface of
``scene/infrastructure/vlm/florence_local_adapter.py`` (``<MORE_DETAILED_CAPTION>``,
num_beams=3, max_new_tokens=512, 1024 px longest-edge downsample, float32 CPU) and
the revision pins in ``scene/config/profiles.py``: base-ft is pinned to the
benchmarked commit; large-ft remains unpinned in profiles (pin-on-enablement)
and this driver refuses ``--model large-ft`` at argument-parse time until a
revision is pinned here (VLM6-RH-09 — fail before the ~1.5 GB download).

Durability semantics mirror ``scripts/eval_harness/describe_baseline.py``:
resumable JSONL append (complete rows keyed by attachment+model+task skipped on
restart; error rows and incomplete keys are retried; torn last line tolerated),
per-item error isolation, and a bounded consecutive-failure abort (rg-007) with
a distinct exit code so a rerun resumes cleanly.

Usage (on-box):
    python3 florence_describe.py \
        --images-dir ~/corpus \
        --tsv ../../../../benchmarks/private/vlm-corpus-attachments-20260716.tsv \
        --out-jsonl ~/results/florence-base-ft.jsonl

Every flag falls back to an env var: IMAGES_DIR, TSV, OUT_JSONL,
FLORENCE_MODEL (base-ft | large-ft), CHUNK (progress cadence, default 12),
LIMIT (0 = all).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Shared latency schema (VLM6-RH-04). Package import when run inside the monorepo;
# standalone single-file copies on the batch VM fall back to a local twin so the
# file remains copy-deployable without the eval_harness package.
try:
    from scripts.eval_harness.face_metrics import latency_summary as _latency_summary
except ImportError:  # pragma: no cover — standalone single-file deploy path

    def _latency_summary(  # type: ignore[misc]
        values: list[float],
        *,
        unit: str = "s",
        wall_clock_s: float | None = None,
        throughput_n: int | None = None,
        decimals: int = 3,
    ) -> dict[str, object] | None:
        if not values:
            return None
        ordered = sorted(float(v) for v in values)
        n = len(ordered)

        def _pct(q: float) -> float:
            return ordered[min(int(q * n), n - 1)]

        out: dict[str, object] = {
            "unit": unit,
            "n": n,
            "mean": round(sum(ordered) / n, decimals),
            "min": round(ordered[0], decimals),
            "p50": round(_pct(0.50), decimals),
            "p95": round(_pct(0.95), decimals),
            "p99": round(_pct(0.99), decimals),
            "max": round(ordered[-1], decimals),
        }
        if wall_clock_s is not None:
            wall = float(wall_clock_s)
            out["wall_clock_s"] = round(wall, 1)
            if throughput_n is not None and wall > 0 and throughput_n > 0:
                out["images_per_min"] = round(float(throughput_n) / (wall / 60.0), 1)
            else:
                out["images_per_min"] = None
        return out


CAPTION_TASK = "<MORE_DETAILED_CAPTION>"
DEFAULT_STALL_LIMIT = 5  # parity with scripts.eval_harness.cli.DEFAULT_STALL_LIMIT
MAX_IMAGE_EDGE_PX = 1024
NUM_BEAMS = 3
MAX_NEW_TOKENS = 512

Captioner = Callable[[Path], str]


class BoundedStallError(RuntimeError):
    """Aborted after too many consecutive per-item failures (rg-007)."""


@dataclass(frozen=True)
class ModelSpec:
    key: str
    model_id: str
    revision: str | None  # None => unpinned upstream; resolved commit logged at load
    model_version: str


# Revision pins mirror scene/config/profiles.py PROFILE_SPECS (FLORENCE_SMALL /
# FLORENCE_LARGE). test_florence_describe.py asserts parity so drift is caught.
MODEL_SPECS: dict[str, ModelSpec] = {
    "base-ft": ModelSpec(
        key="base-ft",
        model_id="microsoft/Florence-2-base-ft",
        revision="f6c1a25888ffc1d945ee8a1a77ac833c7303d46e",
        model_version="florence-2-base-ft",
    ),
    "large-ft": ModelSpec(
        key="large-ft",
        model_id="microsoft/Florence-2-large-ft",
        revision=None,
        model_version="florence-2-large-ft",
    ),
}


# --------------------------------------------------------------------- corpus
def resolve_image_path(raw: str, images_dir: Path) -> Path:
    """Map a TSV path onto the on-box corpus root.

    The vlm-corpus TSV carries laptop-absolute paths
    (``/Volumes/Butter/.../uploads/2026/07/x.png``) while Phase-1 step 10 rsyncs
    ``uploads/`` to ``~/corpus/`` preserving the year/month structure. Order:
    the path as-is, then the post-``uploads/`` suffix under ``images_dir``, then
    a relative join. A miss returns the best candidate; the caller's existence
    filter drops (and counts) it.
    """
    p = Path(raw)
    if p.is_absolute() and p.exists():
        return p
    parts = p.parts
    if "uploads" in parts:
        suffix = Path(*parts[parts.index("uploads") + 1 :])
        candidate = images_dir / suffix
        if candidate.exists():
            return candidate
    if not p.is_absolute():
        candidate = images_dir / p
        if candidate.exists():
            return candidate
        return candidate
    return p


def parse_tsv(text: str, images_dir: Path) -> list[tuple[int, Path]]:
    """Parse ``attachment_id<TAB>path`` rows; tolerate headers/malformed lines."""
    rows: list[tuple[int, Path]] = []
    for line in text.splitlines():
        if "\t" not in line:
            continue
        sid, raw_path = line.split("\t", 1)
        sid, raw_path = sid.strip(), raw_path.strip()
        if not raw_path:
            continue
        try:
            attachment_id = int(sid)
        except ValueError:
            continue  # header or malformed id column
        rows.append((attachment_id, resolve_image_path(raw_path, images_dir)))
    return rows


# Resume key: attachment alone is not enough — a base-ft row must not skip large-ft.
# model_revision is REQUIRED (non-null): an unresolved revision is a hard error so
# null-then-hash cannot silently break resume matching (A-05).
DoneKey = tuple[int, str, str, str, str]


def _row_resume_key(row: dict) -> DoneKey | None:
    """Extract a resume key from a JSONL row, or None if incomplete/unusable."""
    if not all(k in row for k in ("attachment_id", "model_id", "model_version", "model_revision", "task")):
        return None
    revision = row["model_revision"]
    if revision is None:
        return None  # unstable key — never treat as done (A-05)
    try:
        return (
            int(row["attachment_id"]),
            str(row["model_id"]),
            str(row["model_version"]),
            str(revision),
            str(row["task"]),
        )
    except (TypeError, ValueError):
        return None


def done_ids(jsonl_path: Path) -> set[DoneKey]:
    """Complete (attachment, model, version, revision, task) keys already recorded.

    A row counts as done only when ``error`` is unset/null; error rows are retried
    after the JSONL is rewritten to drop their prior row (A-03 — no unbounded
    append of duplicate keys). Rows missing any resume-key field, or with a null
    ``model_revision``, are not matches (A-05).
    """
    if not jsonl_path.exists():
        return set()
    keys: set[DoneKey] = set()
    for line in jsonl_path.read_text().splitlines():
        if not line.strip():
            continue
        with contextlib.suppress(Exception):  # tolerate a torn last line
            row = json.loads(line)
            if row.get("error"):
                continue
            key = _row_resume_key(row)
            if key is not None:
                keys.add(key)
    return keys


def _resume_key(
    attachment_id: int,
    *,
    model_id: str,
    model_version: str,
    model_revision: str,
    task: str,
) -> DoneKey:
    return (attachment_id, model_id, model_version, model_revision, task)


def _rewrite_jsonl_dropping_retry_errors(
    jsonl_path: Path,
    retry_keys: set[DoneKey],
) -> None:
    """Drop error rows whose resume key is about to be reprocessed (A-03).

    Without this, every resume re-appends a new error row for the same key and
    the JSONL grows without bound. Successful rows for non-retry keys are kept;
    a torn final line is dropped.
    """
    if not jsonl_path.exists() or not retry_keys:
        return
    kept: list[str] = []
    for line in jsonl_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # torn line
        key = _row_resume_key(row)
        if key is not None and key in retry_keys and row.get("error"):
            continue  # will be re-appended by this run
        kept.append(json.dumps(row))
    jsonl_path.write_text("\n".join(kept) + ("\n" if kept else ""))


# ---------------------------------------------------------------------- model
def load_captioner(spec: ModelSpec) -> tuple[Captioner, str | None]:
    """Load Florence-2 in-process (torch CPU) and return (captioner, resolved_rev).

    NEVER requires flash_attn: tries ``attn_implementation="eager"`` first (the
    oci-vlm-batch-compute-learnings.md gotcha — Florence-2 remote code may probe
    flash_attn on import) and falls back to the plain load for transformers
    versions whose trust_remote_code path rejects the kwarg.
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoProcessor

    torch.set_num_threads(max(1, torch.get_num_threads()))
    common: dict[str, object] = {
        "revision": spec.revision,
        "trust_remote_code": True,
        "torch_dtype": torch.float32,
    }
    try:
        model = AutoModelForCausalLM.from_pretrained(spec.model_id, attn_implementation="eager", **common)
    except (TypeError, ValueError):
        model = AutoModelForCausalLM.from_pretrained(spec.model_id, **common)
    model = model.to("cpu")
    model.eval()
    processor = AutoProcessor.from_pretrained(spec.model_id, revision=spec.revision, trust_remote_code=True)

    resolved = getattr(model.config, "_commit_hash", None) or spec.revision
    print(f"model loaded: {spec.model_id} revision={resolved or 'UNRESOLVED'} (pin={spec.revision})", flush=True)

    def captioner(path: Path) -> str:
        from PIL import Image

        image = Image.open(path).convert("RGB")
        w, h = image.size
        longest = max(w, h)
        if longest > MAX_IMAGE_EDGE_PX:
            scale = MAX_IMAGE_EDGE_PX / float(longest)
            image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        inputs = processor(text=CAPTION_TASK, images=image, return_tensors="pt")
        with torch.no_grad():
            generated_ids = model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=MAX_NEW_TOKENS,
                num_beams=NUM_BEAMS,
                do_sample=False,
            )
        text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        parsed = processor.post_process_generation(text, task=CAPTION_TASK, image_size=(image.width, image.height))
        value = parsed.get(CAPTION_TASK, parsed)
        return value.strip() if isinstance(value, str) else str(value)

    return captioner, resolved


# ------------------------------------------------------------------ run loop
def run(
    rows: list[tuple[int, Path]],
    captioner: Captioner,
    out_jsonl: Path,
    *,
    spec: ModelSpec,
    resolved_revision: str | None,
    chunk: int = 12,
    limit: int = 0,
    stall_limit: int = DEFAULT_STALL_LIMIT,
) -> dict[str, object]:
    """Caption ``rows`` into ``out_jsonl`` (append, per-item flush, resumable).

    ``resolved_revision`` must be a non-null commit/pin string: a null revision
    makes the resume key unstable across a later resolve (A-05) and is rejected
    before any write.
    """
    if resolved_revision is None:
        raise ValueError(
            f"model revision unresolved for {spec.model_id!r}: refusing to write "
            "rows with a null model_revision (resume key would not match a later "
            "resolved commit hash). Pin the revision or ensure the loaded config "
            "exposes _commit_hash."
        )
    revision = str(resolved_revision)
    done = done_ids(out_jsonl)

    def _is_done(mid: int) -> bool:
        return (
            _resume_key(
                mid,
                model_id=spec.model_id,
                model_version=spec.model_version,
                model_revision=revision,
                task=CAPTION_TASK,
            )
            in done
        )

    already_done = sum(1 for mid, _ in rows if _is_done(mid))
    missing = [(mid, p) for (mid, p) in rows if not _is_done(mid) and not p.exists()]
    todo = [(mid, p) for (mid, p) in rows if not _is_done(mid) and p.exists()]
    if limit:
        todo = todo[:limit]
    print(
        f"florence_describe: {len(rows)} attachments, {already_done} already done, "
        f"{len(missing)} missing on disk, {len(todo)} to caption (chunk={chunk})",
        flush=True,
    )

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    # A-03: drop prior error rows for keys we are about to reprocess so a resume
    # re-appends at most one row per key rather than growing unbounded.
    retry_keys = {
        _resume_key(
            mid,
            model_id=spec.model_id,
            model_version=spec.model_version,
            model_revision=revision,
            task=CAPTION_TASK,
        )
        for mid, _ in (*missing, *todo)
    }
    _rewrite_jsonl_dropping_retry_errors(out_jsonl, retry_keys)

    ok = errors = 0
    latencies: list[float] = []
    consecutive_failures = 0
    with out_jsonl.open("a") as f:

        def _base_row(mid: int, path: Path) -> dict[str, object]:
            return {
                "attachment_id": mid,
                "path": str(path),
                "model_id": spec.model_id,
                "model_version": spec.model_version,
                "model_revision": revision,
                "task": CAPTION_TASK,
                "caption": None,
                "latency_s": None,
                "error": None,
            }

        # Fail closed: record missing-on-disk outcomes rather than inferring from absence.
        for mid, path in missing:
            row = _base_row(mid, path)
            row["error"] = f"FileNotFoundError: image missing on disk: {path}"
            row["completed_at"] = time.time()
            f.write(json.dumps(row) + "\n")
            f.flush()
            errors += 1  # A-04: summary must count missing-on-disk as errors

        for i, (mid, path) in enumerate(todo):
            row = _base_row(mid, path)
            started = time.monotonic()
            try:
                caption = captioner(path)
            except Exception as exc:  # noqa: BLE001 — per-item isolation (rg-007)
                errors += 1
                consecutive_failures += 1
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["latency_s"] = round(time.monotonic() - started, 3)
                row["completed_at"] = time.time()
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(f"  item {mid} failed ({consecutive_failures}/{stall_limit}): {row['error']}", flush=True)
                if consecutive_failures >= stall_limit:
                    raise BoundedStallError(
                        f"{consecutive_failures} consecutive item failures (last: {path}); aborting run"
                    ) from exc
                continue
            consecutive_failures = 0
            ok += 1
            latency = round(time.monotonic() - started, 3)
            latencies.append(latency)
            row["caption"] = caption
            row["latency_s"] = latency
            row["completed_at"] = time.time()
            f.write(json.dumps(row) + "\n")
            f.flush()
            if (i + 1) % chunk == 0 or (i + 1) == len(todo):
                mean = round(sum(latencies) / len(latencies), 1) if latencies else None
                print(f"  {i + 1}/{len(todo)} captioned (mean {mean}s/img, {errors} errors)", flush=True)

    summary: dict[str, object] = {
        "total": len(rows),
        "already_done": already_done,
        "missing": len(missing),
        "captioned_ok": ok,
        "errors": errors,
        # Canonical nested block (VLM6-RH-04) — unit seconds, n/mean/min/p50/p95/p99/max.
        "latency": _latency_summary(latencies, unit="s"),
    }
    return summary


# ----------------------------------------------------------------------- cli
def main(argv: list[str] | None = None) -> int:
    env = os.environ
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images-dir", default=env.get("IMAGES_DIR"), help="corpus root (rsynced uploads/)")
    parser.add_argument("--tsv", default=env.get("TSV"), help="attachment_id<TAB>path inventory")
    parser.add_argument("--out-jsonl", default=env.get("OUT_JSONL"), help="resumable progressive output")
    parser.add_argument(
        "--model",
        default=env.get("FLORENCE_MODEL", "base-ft"),
        choices=sorted(MODEL_SPECS),
        help="Florence-2 checkpoint (default: base-ft, revision-pinned)",
    )
    parser.add_argument("--chunk", type=int, default=int(env.get("CHUNK", "12")), help="progress cadence")
    parser.add_argument("--limit", type=int, default=int(env.get("LIMIT", "0")), help="0 = all")
    parser.add_argument("--stall-limit", type=int, default=DEFAULT_STALL_LIMIT)
    args = parser.parse_args(argv)

    if not (args.images_dir and args.tsv and args.out_jsonl):
        parser.error("--images-dir, --tsv and --out-jsonl are required (flags or IMAGES_DIR/TSV/OUT_JSONL env)")

    # VLM6-RH-09: refuse unpinned specs before the HF download / CPU model load.
    # A null revision makes the A-05 resume key unstable; discovering that after
    # ~1.5 GB + full load on a billed VM is the expensive place to fail.
    spec = MODEL_SPECS[args.model]
    if spec.revision is None:
        parser.error(
            f"--model {args.model} has no pinned revision "
            f"(MODEL_SPECS[{args.model!r}].revision is None). Pin a benchmarked "
            "commit hash before running — refusing to download/load an unpinned "
            "checkpoint that would later fail closed on null model_revision (A-05)."
        )

    images_dir = Path(args.images_dir).expanduser()
    tsv_path = Path(args.tsv).expanduser()
    out_jsonl = Path(args.out_jsonl).expanduser()
    if not tsv_path.exists():
        print(f"TSV not found: {tsv_path}", file=sys.stderr)
        return 1
    rows = parse_tsv(tsv_path.read_text(), images_dir)
    if not rows:
        print(f"no parsable rows in {tsv_path}", file=sys.stderr)
        return 1

    captioner, resolved = load_captioner(spec)
    try:
        summary = run(
            rows,
            captioner,
            out_jsonl,
            spec=spec,
            resolved_revision=resolved,
            chunk=args.chunk,
            limit=args.limit,
            stall_limit=args.stall_limit,
        )
    except BoundedStallError as exc:
        print(f"bounded-stall abort: {exc} — rerun to resume (done ids are skipped)", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
