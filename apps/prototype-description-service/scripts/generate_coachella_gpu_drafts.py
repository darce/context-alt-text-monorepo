#!/usr/bin/env python3
"""Generate the four recorded GPU draft variants for the second guide scenario.

This is an operator-only harness. Run it inside the deployed description-service
dev container after the normal GPU bulk/describe-run path has started the GPU:

    python scripts/generate_coachella_gpu_drafts.py \
        --image-path /path/to/katy-perry-and-justin-trudeau-at-coachella-v0-z697qk161rug1.webp \
        --output-path /path/to/coachella-gpu-drafts.json

The harness calls ``get_gpu_description_adapter().describe`` directly four times
in a fixed, sequential order. It does not call a public API, start or stop a GPU,
read SSH credentials, retry failed calls, or invent a missing draft. Each successful
row contains the direct AdapterResult plus the upstream response when the resolved
adapter exposes its private HTTP seam. ``rawoutputs`` therefore remains an
operator artifact, never UI copy.

The identity labels in the context are user-supplied labels for this fixture. They
are editorial input, not an independent face-recognition result. The script exits
non-zero when any variant fails; an incomplete JSON artifact is still written with
the failed rows explicitly marked so it cannot be published as a complete fixture.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


# Make ``python scripts/<this-file>`` work from a source checkout as well as from
# an installed dev container. No dependency or credential discovery happens here.
SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from scene.application.description_adapter import AdapterResult  # noqa: E402
from scene.interface_adapters.http.deps import get_gpu_description_adapter  # noqa: E402


SCHEMA = "altcontext-guided-coachella-gpu-drafts/v1"
DEFAULT_TENANT_ID = "00000000-0000-4000-8000-0000000000f1"
SOURCE_FIXTURE = (
    "docs/assessments/current/demo/v2/"
    "katy-perry-and-justin-trudeau-at-coachella-v0-z697qk161rug1.webp"
)
PAGE_TITLE = "User-supplied festival photo (event not independently verified)"
PAGE_CONTEXT = (
    "The image was supplied for a second guided scenario. Its original caption, "
    "date, location and credit are unavailable."
)
IDENTITY_NOTE = (
    "Justin Trudeau is the user-supplied label for the person on the left and Katy "
    "Perry is the user-supplied label for the person on the right. These labels are "
    "not independently verified face recognition."
)

VARIANT_CONTEXTS: tuple[tuple[str, dict[str, str]], ...] = (
    (
        "none",
        {
            "page_title": PAGE_TITLE,
            "page_context": PAGE_CONTEXT,
            "user_supplied_identities": f"{IDENTITY_NOTE} Do not include either name in this draft.",
        },
    ),
    (
        "justin-trudeau",
        {
            "page_title": PAGE_TITLE,
            "page_context": PAGE_CONTEXT,
            "user_supplied_identities": (
                f"{IDENTITY_NOTE} Include only the label Justin Trudeau for the person on the left; "
                "leave the person on the right unnamed."
            ),
        },
    ),
    (
        "katy-perry",
        {
            "page_title": PAGE_TITLE,
            "page_context": PAGE_CONTEXT,
            "user_supplied_identities": (
                f"{IDENTITY_NOTE} Include only the label Katy Perry for the person on the right; "
                "leave the person on the left unnamed."
            ),
        },
    ),
    (
        "both",
        {
            "page_title": PAGE_TITLE,
            "page_context": PAGE_CONTEXT,
            "user_supplied_identities": (
                f"{IDENTITY_NOTE} Include the supplied labels Justin Trudeau on the left and Katy "
                "Perry on the right."
            ),
        },
    ),
)

FACE_CROPS: dict[str, dict[str, Any]] = {
    "left": {
        "label": "Justin Trudeau",
        "box": {"x": 190, "y": 150, "width": 115, "height": 160},
        "source": "Approximate crop checked visually against the supplied 640 x 852 image; not detector output.",
    },
    "right": {
        "label": "Katy Perry",
        "box": {"x": 370, "y": 175, "width": 115, "height": 150},
        "source": "Approximate crop checked visually against the supplied 640 x 852 image; not detector output.",
    },
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_path_arg", nargs="?", help="path to the supplied WebP fixture")
    parser.add_argument("--image-path", dest="image_path_option", help="path to the supplied WebP fixture")
    parser.add_argument(
        "--output-path",
        "--outputpath",
        "--json-out",
        dest="output_path",
        required=True,
        help="JSON artifact path; successful rows are written atomically",
    )
    parser.add_argument(
        "--tenant-id",
        default=DEFAULT_TENANT_ID,
        help=f"tenant recorded in the operator artifact (default: {DEFAULT_TENANT_ID})",
    )
    args = parser.parse_args(argv)
    if args.image_path_arg and args.image_path_option and Path(args.image_path_arg) != Path(args.image_path_option):
        parser.error("provide one image path, not two different paths")
    image_path = args.image_path_option or args.image_path_arg
    if not image_path:
        parser.error("an image path is required via IMAGE_PATH or --image-path")
    args.image_path = image_path
    return args


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_value(value: Any) -> Any:
    """Convert the adapter's small dataclass/tuple surface without editing it."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _adapter_result_value(result: AdapterResult) -> dict[str, Any]:
    """Serialize the direct AdapterResult, before any guide/UI transformation."""
    return {
        "caption": result.caption,
        "objects": list(result.objects),
        "ocr_text": result.ocr_text,
        "alt_text_draft": result.alt_text_draft,
        "context_sources": list(result.context_sources),
        "context_applied": result.context_applied,
        "phrase_boxes": _json_value(result.phrase_boxes),
        "alt_text_long": result.alt_text_long,
    }


def _model_metadata(adapter: Any) -> dict[str, Any]:
    kind = getattr(adapter, "kind", None)
    kind_value = getattr(kind, "value", kind)
    metadata = {
        "adapter_kind": str(kind_value) if kind_value is not None else None,
        "model_id": getattr(adapter, "model_id", None),
        "model_revision": getattr(adapter, "model_revision", None),
        "hub_repo": getattr(adapter, "hub_repo", None),
        "model_version": getattr(adapter, "model_version", None),
        "quantization": getattr(adapter, "model_version", None),
        "prompt_or_task_version": getattr(adapter, "prompt_or_task_version", None),
    }
    required = ("model_id", "model_revision", "quantization", "prompt_or_task_version")
    missing = [key for key in required if not isinstance(metadata[key], str) or not metadata[key].strip()]
    if missing:
        raise RuntimeError(
            "GPU adapter did not expose required provenance fields: "
            + ", ".join(missing)
            + ". Refusing to create an unauditable draft artifact."
        )
    if metadata["adapter_kind"] != "gpu":
        raise RuntimeError(
            f"resolved adapter kind is {metadata['adapter_kind']!r}, not 'gpu'; "
            "refusing to label non-GPU output as a GPU draft"
        )
    return metadata


def _install_raw_response_capture(adapter: Any, rawoutputs: dict[str, dict[str, Any]]) -> Callable[[str], None] | None:
    """Capture upstream JSON when the resolved GPU adapter exposes ``_post``.

    ``GpuRemoteDescriptionAdapter`` intentionally returns only ``AdapterResult``
    at its public seam. Wrapping its private transport locally lets an operator
    retain the raw response without changing production code. Other adapters are
    left untouched and still record the direct AdapterResult.
    """
    original_post = getattr(adapter, "_post", None)
    if not callable(original_post):
        return None

    current_variant: list[str | None] = [None]

    def set_variant(key: str) -> None:
        current_variant[0] = key

    def recording_post(*, json: dict[str, Any], headers: dict[str, str]) -> Any:
        response = original_post(json=json, headers=headers)
        key = current_variant[0]
        if key is not None:
            try:
                body: Any = response.json()
            except (TypeError, ValueError):
                body = {"unparsed_text": response.text}
            rawoutputs.setdefault(key, {})["upstream_http_response"] = _json_value(body)
        return response

    setattr(adapter, "_post", recording_post)
    return set_variant


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
        temporary_path = Path(temporary_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _base_artifact(*, image_path: Path, image_bytes: bytes, tenant_id: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "not_started",
        "generated_at_utc": _utc_now(),
        "tenant_id": tenant_id,
        "inputs": {
            "image_path": str(image_path),
            "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
            "image_bytes": len(image_bytes),
            "source_fixture": SOURCE_FIXTURE,
            "page_title": PAGE_TITLE,
            "page_context": PAGE_CONTEXT,
            "identity_source": {
                "kind": "user-supplied",
                "labels": {"left": "Justin Trudeau", "right": "Katy Perry"},
                "source": SOURCE_FIXTURE,
                "note": IDENTITY_NOTE,
            },
            "face_crops": FACE_CROPS,
        },
        "required_variant_count": len(VARIANT_CONTEXTS),
        "variant_order": [key for key, _ in VARIANT_CONTEXTS],
        "variants": {},
        "rawoutputs": {},
        "provenance": {
            "method": (
                "Four sequential direct calls to get_gpu_description_adapter().describe; "
                "no public API integration, no recognition pass, no retries and no UI edits."
            ),
            "raw_output_boundary": "Direct AdapterResult and, when available, the upstream HTTP response body.",
            "identity_boundary": "Names are user-supplied editorial labels, not independently verified face recognition.",
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    image_path = Path(args.image_path).expanduser().resolve()
    output_path = Path(args.output_path).expanduser().resolve()
    if image_path == output_path:
        print("image path and output path must be different", file=sys.stderr)
        return 2
    if not image_path.is_file():
        print(f"image path is not a file: {image_path}", file=sys.stderr)
        return 2
    image_bytes = image_path.read_bytes()
    if not image_bytes:
        print(f"image file is empty: {image_path}", file=sys.stderr)
        return 2

    artifact = _base_artifact(image_path=image_path, image_bytes=image_bytes, tenant_id=args.tenant_id)
    run_started_ns = time.monotonic_ns()
    artifact["timing"] = {
        "clock": "time.monotonic_ns",
        "started_monotonic_ns": run_started_ns,
    }

    try:
        adapter = get_gpu_description_adapter()
        artifact["model"] = _model_metadata(adapter)
    except Exception as exc:  # noqa: BLE001 - emit a typed operator artifact on setup failure
        run_finished_ns = time.monotonic_ns()
        artifact["status"] = "failed_before_generation"
        artifact["error"] = f"{type(exc).__name__}: {exc}"
        artifact["timing"].update(
            {
                "finished_monotonic_ns": run_finished_ns,
                "elapsed_monotonic_ns": run_finished_ns - run_started_ns,
                "elapsed_monotonic_ms": round((run_finished_ns - run_started_ns) / 1_000_000, 3),
            }
        )
        _write_json_atomic(output_path, artifact)
        print(f"GPU adapter setup failed; wrote {output_path}", file=sys.stderr)
        return 2

    rawoutputs: dict[str, dict[str, Any]] = artifact["rawoutputs"]
    set_variant = _install_raw_response_capture(adapter, rawoutputs)
    failures: list[str] = []

    for key, context in VARIANT_CONTEXTS:
        if set_variant is not None:
            set_variant(key)
        started_ns = time.monotonic_ns()
        variant_record: dict[str, Any] = {
            "status": "started",
            "input": {
                "name_choice": key,
                "context": context,
            },
            "timing": {
                "clock": "time.monotonic_ns",
                "started_monotonic_ns": started_ns,
            },
        }
        try:
            result = adapter.describe(image_bytes=image_bytes, context=context)
        except Exception as exc:  # noqa: BLE001 - preserve failure per choice and continue bounded four-call run
            finished_ns = time.monotonic_ns()
            failures.append(key)
            variant_record.update(
                {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "timing": {
                        "clock": "time.monotonic_ns",
                        "started_monotonic_ns": started_ns,
                        "finished_monotonic_ns": finished_ns,
                        "elapsed_monotonic_ns": finished_ns - started_ns,
                        "elapsed_monotonic_ms": round((finished_ns - started_ns) / 1_000_000, 3),
                    },
                }
            )
            artifact["variants"][key] = variant_record
            continue

        finished_ns = time.monotonic_ns()
        rawoutputs[key] = {
            **rawoutputs.get(key, {}),
            "adapter_result": _adapter_result_value(result),
            "note": "Unedited direct adapter output; no caption or identity post-processing was applied by this harness.",
        }
        variant_record.update(
            {
                "status": "ok",
                "rawoutput_ref": f"rawoutputs.{key}",
                "timing": {
                    "clock": "time.monotonic_ns",
                    "started_monotonic_ns": started_ns,
                    "finished_monotonic_ns": finished_ns,
                    "elapsed_monotonic_ns": finished_ns - started_ns,
                    "elapsed_monotonic_ms": round((finished_ns - started_ns) / 1_000_000, 3),
                },
            }
        )
        artifact["variants"][key] = variant_record

    run_finished_ns = time.monotonic_ns()
    artifact["status"] = "incomplete" if failures else "complete"
    artifact["successful_variant_count"] = len(VARIANT_CONTEXTS) - len(failures)
    artifact["failed_variant_count"] = len(failures)
    artifact["timing"].update(
        {
            "finished_monotonic_ns": run_finished_ns,
            "elapsed_monotonic_ns": run_finished_ns - run_started_ns,
            "elapsed_monotonic_ms": round((run_finished_ns - run_started_ns) / 1_000_000, 3),
        }
    )
    _write_json_atomic(output_path, artifact)
    print(
        f"wrote {output_path}: {artifact['successful_variant_count']}/{len(VARIANT_CONTEXTS)} "
        f"GPU variants ({artifact['status']})"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
