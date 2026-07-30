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
benchmarked commit; large-ft is unpinned upstream, so the resolved commit is
logged at load time for provenance.

Durability semantics mirror ``scripts/eval_harness/describe_baseline.py``:
resumable JSONL append (complete rows keyed by attachment+model+task skipped on
restart; error rows and incomplete keys are retried; torn last line tolerated),
per-item error isolation, and a bounded consecutive-failure abort (rg-007) with
a distinct exit code so a rerun resumes cleanly.

Usage (on-box):
    python3 florence_describe.py \
        --images-dir ~/corpus \
        --tsv vlm-corpus-attachments-20260716.tsv \
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
DoneKey = tuple[int, str, str, str | None, str]


def done_ids(jsonl_path: Path) -> set[DoneKey]:
    """Complete (attachment, model, version, revision, task) keys already recorded.

    A row counts as done only when ``error`` is unset/null; error rows are retried.
    Rows missing any resume-key field are not matches and must be retried (never
    assumed compatible across models).
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
            if not all(
                k in row
                for k in ("attachment_id", "model_id", "model_version", "model_revision", "task")
            ):
                continue
            keys.add(
                (
                    int(row["attachment_id"]),
                    str(row["model_id"]),
                    str(row["model_version"]),
                    row["model_revision"],
                    str(row["task"]),
                )
            )
    return keys


def _resume_key(
    attachment_id: int,
    *,
    model_id: str,
    model_version: str,
    model_revision: str | None,
    task: str,
) -> DoneKey:
    return (attachment_id, model_id, model_version, model_revision, task)


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
    """Caption ``rows`` into ``out_jsonl`` (append, per-item flush, resumable)."""
    done = done_ids(out_jsonl)

    def _is_done(mid: int) -> bool:
        return (
            _resume_key(
                mid,
                model_id=spec.model_id,
                model_version=spec.model_version,
                model_revision=resolved_revision,
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
                "model_revision": resolved_revision,
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

    return {
        "total": len(rows),
        "already_done": already_done,
        "missing": len(missing),
        "captioned_ok": ok,
        "errors": errors,
        "mean_latency_s": round(sum(latencies) / len(latencies), 3) if latencies else None,
    }


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

    spec = MODEL_SPECS[args.model]
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
