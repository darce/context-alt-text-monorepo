"""Local-CPU VLM eval/benchmark (E19-1 S10).

Runs the Florence-2 local-CPU DescriptionAdapter on one or more images, measuring
cold-load time and per-image inference latency, and printing the generated visual
facts so description quality can be evaluated *before any UI is built*. Emits a
JSON artifact. Refuses to run without the ``[vlm]`` extra.

Usage:
    uv run python scripts/benchmark_local_vlm.py IMAGE [IMAGE ...] [--num-beams 3]
        [--max-edge 1024] [--tasks "<MORE_DETAILED_CAPTION>,<OD>"] [--device cpu]
        [--json-out path.json]
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import time
from pathlib import Path


def _peak_rss_mb() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports kilobytes.
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(raw / divisor, 1)


def main(argv: list[str] | None = None) -> int:
    from scene.config.profiles import DescriptionProfile, get_profile_spec

    small = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    ap = argparse.ArgumentParser(description="Local-CPU Florence-2 description eval/benchmark.")
    ap.add_argument("images", nargs="+", help="image file paths to describe")
    ap.add_argument("--device", default="cpu", help="torch device (cpu mirrors the OCI A1 target)")
    ap.add_argument("--num-beams", type=int, default=3)
    ap.add_argument("--max-edge", type=int, default=1024, help="downsample longest edge to N px")
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--model-id", default=small.model_id, help="Hugging Face model id (florence_small default)")
    ap.add_argument(
        "--model-revision",
        default=small.model_revision,
        help="Hugging Face revision for the trust_remote_code model",
    )
    ap.add_argument("--tasks", default="<MORE_DETAILED_CAPTION>,<OD>")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    from scene.infrastructure.vlm.florence_local_adapter import (
        LocalCpuDescriptionAdapter,
        LocalVlmUnavailableError,
    )

    adapter = LocalCpuDescriptionAdapter(
        device=args.device,
        tasks=tuple(t.strip() for t in args.tasks.split(",") if t.strip()),
        max_image_edge_px=args.max_edge,
        num_beams=args.num_beams,
        max_new_tokens=args.max_new_tokens,
        model_id=args.model_id,
        model_revision=args.model_revision,
    )

    print(f"Loading {adapter.model_id} (device={args.device}, beams={args.num_beams})...", flush=True)
    t0 = time.perf_counter()
    try:
        adapter.ensure_loaded()
    except LocalVlmUnavailableError as exc:
        print(f"VLM unavailable — install with `uv sync --extra vlm`: {exc}", file=sys.stderr)
        return 2
    cold_load_s = round(time.perf_counter() - t0, 1)
    print(f"  cold load: {cold_load_s}s\n", flush=True)

    results = []
    for path in args.images:
        data = Path(path).read_bytes()
        t = time.perf_counter()
        out = adapter.describe(image_bytes=data, context=None)
        latency_s = round(time.perf_counter() - t, 2)
        results.append(
            {
                "image": path,
                "bytes": len(data),
                "latency_s": latency_s,
                "caption": out.caption,
                "objects": list(out.objects),
                "alt_text_draft": out.alt_text_draft,
            }
        )
        print(f"=== {path}  ({latency_s}s) ===")
        print(f"  caption: {out.caption}")
        print(f"  objects: {list(out.objects)}\n", flush=True)

    latencies = [r["latency_s"] for r in results]
    artifact = {
        "model_id": adapter.model_id,
        "model_revision": args.model_revision,
        "model_version": adapter.model_version,
        "prompt_or_task_version": adapter.prompt_or_task_version,
        "device": args.device,
        "num_beams": args.num_beams,
        "max_image_edge_px": args.max_edge,
        "host": {
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
        },
        "cold_load_s": cold_load_s,
        "peak_rss_mb": _peak_rss_mb(),
        "images_count": len(results),
        "latency_s": {
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
            "mean": round(sum(latencies) / len(latencies), 2) if latencies else None,
        },
        "results": results,
        "note": (
            "Mac CPU is an optimistic proxy for the OCI A1 ARM target; the binding "
            "A1 benchmark runs on the deployed host. Decision (keep_seeded / "
            "enable_local_cpu / defer_to_hosted_gpu) is recorded in the decision memo."
        ),
    }
    print("---\n" + json.dumps(artifact["latency_s"], indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(artifact, indent=2))
        print(f"\nwrote {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
