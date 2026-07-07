"""VLM-2B bake-off transport: candidate llama.cpp endpoints -> acx-eval/v1 run records.

Throwaway benchmark code (task VLM-2B) — NOT a ``DescriptionAdapter`` and never
registered in ``PROFILE_SPECS``. ``BakeoffClient`` subclasses
``RemoteSceneClient`` to inherit its Nygard discipline (per-request timeout,
3-strike breaker, 429 backoff) and swaps ``describe()`` for a llama.cpp
``/v1/chat/completions`` call; the face-metric legs (``analyze``/``wait_job``/
``media_identities``) are inert no-op stubs — face metrics are out-of-band for
this task (scope §5), so the REPORT's face sections are vacuous by design.

The prompt renders the manifest ``context_pack`` under the anchor-visual/
inject-factual contract: every injected roster name reaches the candidate
prompt verbatim, the model weaves supplied names (never guesses), and pixels
win over conflicting context. Decoding is greedy (temperature 0) with
``/no_think`` appended for reasoning-tuned candidates, identical across
candidates for comparability.

The ``__main__`` drives the UNCHANGED ``cli.fetch_run_record`` walker —
per-item isolation and bounded-stall exit (rg-007) come from it, not from a
fork.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .cli import DEFAULT_STALL_LIMIT, BoundedStallError, _head_sha, fetch_run_record
from .manifest import ManifestError, load_manifest
from .remote_client import RemoteClientError, RemoteSceneClient

_CAPTION_MAX_TOKENS = 512

_SYSTEM_PROMPT = (
    "You write alt text for images on a personal website. Describe only what is "
    "visible in the image, in 2-4 plain sentences. A context block may accompany "
    "the image: treat it as trusted editorial metadata. Weave the people's names "
    "and factual details it supplies into the description where they fit naturally. "
    "Never name or guess about anyone the context does not name. If the context "
    "conflicts with what the image shows, describe what the image shows."
)


class BakeoffClient(RemoteSceneClient):
    """Candidate llama.cpp transport with ``RemoteSceneClient``'s failure discipline.

    Reuses the inherited ``_request`` (timeout, 3-strike breaker, 429 backoff);
    only the route and payload differ. Duck-type compatible with
    ``cli.fetch_run_record``'s client contract.
    """

    def __init__(
        self,
        base_url: str,
        *,
        model_id: str,
        model_version: str | None = None,
        no_think: bool = False,
        timeout_s: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"transport": transport}
        if timeout_s is not None:
            kwargs["timeout_s"] = timeout_s
        super().__init__(base_url, api_key="", **kwargs)
        self.model_id = model_id
        self.model_version = model_version
        self.no_think = no_think

    def describe(
        self,
        *,
        image_bytes: bytes,
        filename: str,
        media_id: int,
        context_pack: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /v1/chat/completions -> describe dict scoreable by ``report``."""
        payload = self._request_dict(
            "POST",
            "/v1/chat/completions",
            json={
                "model": self.model_id,
                "temperature": 0,
                "max_tokens": _CAPTION_MAX_TOKENS,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": _data_url(image_bytes, filename)},
                            },
                            {"type": "text", "text": self._user_text(context_pack)},
                        ],
                    },
                ],
            },
        )
        caption = _extract_caption(payload)
        return {
            "alt_text_draft": caption,
            "adapter": "bakeoff",
            "model_id": self.model_id,
            "model_version": self.model_version,
        }

    def _user_text(self, context_pack: dict[str, Any]) -> str:
        lines = ["Write the alt text for this image."]
        rendered = _render_context(context_pack)
        if rendered:
            lines.append("Context block:")
            lines.append(rendered)
        else:
            lines.append("No context is available for this image.")
        if self.no_think:
            lines.append("/no_think")
        return "\n".join(lines)

    # Face metrics are out-of-band for VLM-2B (scope §5): inert stubs keep the
    # reused walker's analyze/wait/identities legs no-ops without a fork.
    def analyze(self, images: list[tuple[int, str, bytes]]) -> str:
        return "bakeoff-noop"

    def wait_job(self, job_id: str) -> dict[str, Any]:
        return {}

    def media_identities(self, media_ids: list[int]) -> Any:
        return []


def _render_context(context_pack: dict[str, Any]) -> str:
    """Render every context_pack field verbatim — injected names must reach the model."""
    lines = []
    for key, value in context_pack.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _data_url(image_bytes: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".") or "jpeg"
    mime = {"jpg": "jpeg"}.get(suffix, suffix)
    return f"data:image/{mime};base64,{base64.b64encode(image_bytes).decode()}"


def _extract_caption(payload: dict[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RemoteClientError(f"chat completion missing choices[0].message.content: {payload!r}") from exc
    if not isinstance(content, str) or not content.strip():
        raise RemoteClientError(f"chat completion returned empty caption: {payload!r}")
    return content.strip()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bakeoff", description=__doc__)
    parser.add_argument("--endpoint", required=True, help="candidate llama.cpp base URL, e.g. http://host:8080")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-version", default=None, help="e.g. GGUF quant tag Q4_K_M")
    parser.add_argument("--no-think", action="store_true", help="append /no_think (reasoning-tuned candidates)")
    parser.add_argument("--manifest", default="scene/tests/seed/bakeoff_golden.json")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--stall-limit", type=int, default=DEFAULT_STALL_LIMIT)
    parser.add_argument("--timeout", type=float, default=None, help="per-request wall-clock seconds")
    parser.add_argument("--out", default=None, help="run-record path (default: out/bakeoff-<model>-<stamp>.json)")
    args = parser.parse_args(argv)

    if os.environ.get("ACX_EVAL_LIVE") != "1":
        sys.exit("bakeoff fetch requires ACX_EVAL_LIVE=1 (safety gate, as VLM-2A live pattern)")
    images_dir = os.environ.get("GOLDEN_IMAGES_DIR", "")
    if not images_dir:
        sys.exit("GOLDEN_IMAGES_DIR is not set — see scene/tests/seed/README.md for the rsync bootstrap")

    manifest = load_manifest(args.manifest, images_dir=images_dir)
    client = BakeoffClient(
        args.endpoint,
        model_id=args.model_id,
        model_version=args.model_version,
        no_think=args.no_think,
        timeout_s=args.timeout,
    )
    started_at = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = started_at.replace(":", "").replace("-", "").replace("T", "-").rstrip("Z")
    out_dir = Path(__file__).parent / "out"
    out_dir.mkdir(exist_ok=True)
    record_path = Path(args.out) if args.out else out_dir / f"bakeoff-{args.model_id}-{stamp}.json"

    try:
        record = fetch_run_record(
            manifest,
            images_dir,
            client,
            head_sha=_head_sha(),
            limit=args.limit,
            stall_limit=args.stall_limit,
            started_at=started_at,
        )
    except BoundedStallError as exc:
        aborted_path = record_path.with_name(record_path.stem + "-aborted.json")
        aborted_path.write_text(json.dumps(exc.partial_record, indent=2, sort_keys=True) + "\n")
        sys.exit(f"BoundedStallError: {exc} — partial record saved to {aborted_path}")
    finally:
        client.close()

    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(record_path)


if __name__ == "__main__":
    try:
        main()
    except (ManifestError, RemoteClientError) as exc:
        sys.exit(f"{type(exc).__name__}: {exc}")
