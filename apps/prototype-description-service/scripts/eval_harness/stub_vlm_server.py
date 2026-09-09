"""Loopback OpenAI-compatible stub VLM server (VLM-6 S2).

Stdlib only. Deterministic captions from the request-body sha256 so two dry-runs
against the same inputs produce byte-identical captions. No GPU, no weights,
no off-box network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import signal
import socket
import threading
import time
from enum import StrEnum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


class HealthStatus(StrEnum):
    OK = "ok"


class OpenAIObject(StrEnum):
    LIST = "list"
    CHAT_COMPLETION = "chat.completion"


class FinishReason(StrEnum):
    STOP = "stop"


class StubErrorType(StrEnum):
    SERVER_ERROR = "server_error"
    INVALID_REQUEST = "invalid_request_error"


_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_MODEL_ID = "stub"
_READY_TIMEOUT_S = 2.0


class _CompletionCounter:
    """Thread-safe 1-based count of POST /v1/chat/completions (fail-every)."""

    def __init__(self) -> None:
        self._n = 0
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._n += 1
            return self._n


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


def _caption_for_body(body: bytes) -> str:
    return f"Stub caption {hashlib.sha256(body).hexdigest()[:12]}."


def _usage_for_body(body: bytes, caption: str) -> dict[str, int]:
    """Deterministic token block derived from the request, not a guessed average.

    Stub-measured: hashed body length plus caption word count. Totals always
    equal prompt + completion so `_extract_usage` accepts the block (rg-015).
    """
    digest = hashlib.sha256(body).digest()
    prompt_tokens = 16 + digest[0]
    completion_tokens = max(1, len(caption.split()))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _validate_serve_kwargs(*, latency_ms: int, fail_every: int) -> None:
    # rg-008: fail at bind time, not on the first request.
    if latency_ms < 0:
        raise ValueError(f"--latency-ms must be >= 0, got {latency_ms}")
    if fail_every < 0:
        raise ValueError(f"--fail-every must be >= 0, got {fail_every}")


class _StubHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _make_handler(
    *,
    model_id: str,
    latency_ms: int,
    fail_every: int,
    counter: _CompletionCounter,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return

        def _delay(self) -> None:
            if latency_ms > 0:
                time.sleep(latency_ms / 1000.0)

        def _write_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _route(self) -> str:
            return urlparse(self.path).path

        def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler verb hook
            self._delay()
            route = self._route()
            if route == "/health":
                self._write_json(200, {"status": HealthStatus.OK.value})
                return
            if route == "/v1/models":
                self._write_json(
                    200,
                    {
                        "object": OpenAIObject.LIST.value,
                        "data": [{"id": model_id}],
                    },
                )
                return
            self._write_json(
                404,
                {
                    "error": {
                        "message": f"unknown route {route}",
                        "type": StubErrorType.INVALID_REQUEST.value,
                    }
                },
            )

        def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler verb hook
            route = self._route()
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length) if length > 0 else b""
            self._delay()
            if route != "/v1/chat/completions":
                self._write_json(
                    404,
                    {
                        "error": {
                            "message": f"unknown route {route}",
                            "type": StubErrorType.INVALID_REQUEST.value,
                        }
                    },
                )
                return
            seq = counter.next()
            if fail_every > 0 and seq % fail_every == 0:
                self._write_json(
                    500,
                    {
                        "error": {
                            "message": f"stub fail-every {fail_every} (request {seq})",
                            "type": StubErrorType.SERVER_ERROR.value,
                        }
                    },
                )
                return
            caption = _caption_for_body(body)
            self._write_json(
                200,
                {
                    "id": f"chatcmpl-stub-{hashlib.sha256(body).hexdigest()[:12]}",
                    "object": OpenAIObject.CHAT_COMPLETION.value,
                    "model": model_id,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": caption},
                            "finish_reason": FinishReason.STOP.value,
                        }
                    ],
                    "usage": _usage_for_body(body, caption),
                },
            )

    return Handler


def _wait_accepting(host: str, port: int, *, timeout_s: float = _READY_TIMEOUT_S) -> None:
    """OBS-08: bind is not readiness. Refuse to return until the socket accepts."""
    deadline = time.monotonic() + timeout_s
    last: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return
        except OSError as exc:
            last = exc
            time.sleep(0.01)
    raise RuntimeError(f"stub server did not accept connections on {host}:{port}: {last}")


def bind_server(
    host: str = _DEFAULT_HOST,
    port: int = 0,
    *,
    model_id: str = _DEFAULT_MODEL_ID,
    latency_ms: int = 0,
    fail_every: int = 0,
) -> _StubHTTPServer:
    _validate_serve_kwargs(latency_ms=latency_ms, fail_every=fail_every)
    handler = _make_handler(
        model_id=model_id,
        latency_ms=latency_ms,
        fail_every=fail_every,
        counter=_CompletionCounter(),
    )
    return _StubHTTPServer((host, port), handler)


def serve_in_thread(
    host: str = _DEFAULT_HOST,
    port: int = 0,
    *,
    model_id: str = _DEFAULT_MODEL_ID,
    latency_ms: int = 0,
    fail_every: int = 0,
) -> tuple[ThreadingHTTPServer, str]:
    """Start the stub on a background thread. Returns (server, base_url)."""
    server = bind_server(
        host,
        port,
        model_id=model_id,
        latency_ms=latency_ms,
        fail_every=fail_every,
    )
    bound_host, bound_port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, name="stub-vlm-server", daemon=True)
    thread.start()
    _wait_accepting(str(bound_host), int(bound_port))
    return server, f"http://{bound_host}:{bound_port}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stub_vlm_server", description=__doc__)
    parser.add_argument("--host", default=_DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=0, help="0 = ephemeral; prints PORT=<n>")
    parser.add_argument("--model-id", default=_DEFAULT_MODEL_ID)
    parser.add_argument("--latency-ms", type=int, default=0, help="fixed per-request delay (PERF-03 open-loop)")
    parser.add_argument(
        "--fail-every",
        type=int,
        default=0,
        help="every Nth completion returns HTTP 500 (0 = never; AGT-06 skip none)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _validate_serve_kwargs(latency_ms=args.latency_ms, fail_every=args.fail_every)
    except ValueError as exc:
        parser.error(str(exc))
    server = bind_server(
        args.host,
        args.port,
        model_id=args.model_id,
        latency_ms=args.latency_ms,
        fail_every=args.fail_every,
    )
    bound_port = int(server.server_address[1])
    print(f"PORT={bound_port}", flush=True)

    def _stop(_signum: int, _frame: object | None) -> None:
        threading.Thread(target=server.shutdown, name="stub-vlm-shutdown", daemon=True).start()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    raise SystemExit(0)


if __name__ == "__main__":
    main()
