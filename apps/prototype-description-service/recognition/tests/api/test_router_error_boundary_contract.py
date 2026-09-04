"""Directory-wide structural guards on the HTTP client-facing boundary.

Two families live here: what a router may say when it fails (the error
boundary), and what a streaming router must tell a client about reconnecting.
Both are properties of the boundary itself rather than of any one endpoint.


Supersedes ``test_retention_router_has_no_501_catch_all``, which read exactly one
module (``retention.py``) and therefore certified a property it never checked:
``analyze.py`` kept a ``501`` catch-all through a wave that claimed to have
removed that class. ARCH-13 -- a property enforced only by discipline (or by a
guard scoped to the one file the last reviewer happened to look at) is
eventually violated -- so the guard is hoisted to the whole router package and
made fail-closed: if enumeration yields no modules, collection errors instead of
passing vacuously.

Properties enforced here:

* API-08 / API-05 -- ``501 Not Implemented`` is never used as a fault code. It
  tells clients and proxies the endpoint does not exist, which is the wrong
  retry/caching decision for a transient server fault.
* SEC-01 / API-05 -- the client is on the untrusted side of the HTTP boundary.
  A ``5xx`` ``detail`` must be a fixed string, never derived from the caught
  exception: driver text, file paths, and internal identifiers must stay in the
  server-side log record.

The checks are AST-based, not substring-based, so ``status_code=501`` written as
a bare int is caught as well as ``status.HTTP_501_NOT_IMPLEMENTED``.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from recognition.interface_adapters.http import routers as routers_pkg

ROUTERS_DIR = Path(routers_pkg.__file__).parent

# Modules that still leak exception text into a 5xx ``detail`` and live outside
# this lane's write-set. ``strict=True`` means the day another lane fixes one,
# the XPASS fails this suite and forces the entry to be deleted -- the debt is
# tracked by the structure, not by a comment somebody has to remember to remove
# (ARCH-13).
KNOWN_5XX_DETAIL_LEAKS = frozenset({"analyze_multipart"})


def _router_modules() -> list[Path]:
    """Every router module, or an exception. Never an empty list.

    Fail-closed: a glob that silently returns nothing would turn every
    parametrized property below into zero collected tests, which reports as
    green. That failure mode is exactly what this module exists to prevent.
    """
    modules = sorted(p for p in ROUTERS_DIR.glob("*.py") if p.name != "__init__.py")
    if not modules:
        raise RuntimeError(
            f"router module enumeration returned nothing under {ROUTERS_DIR}; refusing to report a vacuous pass"
        )
    return modules


ROUTER_MODULES = _router_modules()
MODULE_NAMES = [p.stem for p in ROUTER_MODULES]


def _param(path: Path, *, xfail_leaks: bool = False) -> object:
    if xfail_leaks and path.stem in KNOWN_5XX_DETAIL_LEAKS:
        return pytest.param(
            path,
            marks=pytest.mark.xfail(
                strict=True,
                reason=f"{path.stem} still interpolates exception text into a 5xx detail (SEC-01)",
            ),
            id=path.stem,
        )
    return pytest.param(path, id=path.stem)


def _http_exception_calls(source: str) -> list[ast.Call]:
    tree = ast.parse(source)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "HTTPException")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "HTTPException")
        )
    ]


def _kwarg(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _status_int(node: ast.expr | None) -> int | None:
    """Resolve a ``status_code`` expression to its numeric value when possible."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Attribute) and node.attr.startswith("HTTP_"):
        digits = node.attr.split("_")[1]
        return int(digits) if digits.isdigit() else None
    return None


def _caught_exception_names(source: str) -> set[str]:
    """Every name bound by an ``except ... as <name>`` clause in the module.

    These are the only values in a handler that carry text the server produced
    for itself: driver messages, SQL fragments, absolute paths, internal ids.
    They are what must not cross the boundary.
    """
    return {node.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ExceptHandler) and node.name}


def test_router_enumeration_is_non_empty() -> None:
    """The guard below is only as good as the set it iterates."""
    assert ROUTER_MODULES, "no router modules enumerated"
    assert {"retention", "analyze"} <= set(MODULE_NAMES), f"router enumeration looks wrong; got {MODULE_NAMES}"


@pytest.mark.parametrize("module_path", [_param(p) for p in ROUTER_MODULES])
def test_router_never_raises_501_as_a_fault_code(module_path: Path) -> None:
    """API-08: no router may answer a server fault with 501 Not Implemented.

    501 is a statement about the endpoint's existence. A client or proxy that
    reads it stops retrying and may cache the negative answer, so a transient
    database fault becomes a permanent-looking feature gap.
    """
    source = module_path.read_text(encoding="utf-8")
    offenders = [
        node.lineno for node in _http_exception_calls(source) if _status_int(_kwarg(node, "status_code")) == 501
    ]
    assert not offenders, (
        f"{module_path.name} raises HTTP 501 as a fault code at line(s) {offenders}; "
        "use 500 for an unexpected server fault"
    )


@pytest.mark.parametrize("module_path", [_param(p, xfail_leaks=True) for p in ROUTER_MODULES])
def test_router_5xx_detail_never_carries_caught_exception_text(module_path: Path) -> None:
    """SEC-01 / API-05: no internal exception text crosses the HTTP boundary.

    Trust changes at this crossing. ``detail=str(exc)`` and
    ``detail=f"...{exc}"`` ship DB-driver messages, absolute file paths, and
    internal identifiers to an untrusted caller. The information is not lost --
    the handlers keep ``logger.exception`` -- it is redirected to the side of
    the boundary allowed to see it.

    The property is *exception-derived*, not *literal*: API-05 wants
    machine-actionable error envelopes, so a structured ``detail`` built from
    the caller's own request (the 503 circuit-breaker body, for instance) is
    the desired shape and must not be pushed back to a bare string. What is
    forbidden is any reference, at any depth, to a name bound by an
    ``except ... as`` clause.
    """
    source = module_path.read_text(encoding="utf-8")
    exception_names = _caught_exception_names(source)
    offenders: list[tuple[int, str]] = []

    for call in _http_exception_calls(source):
        code = _status_int(_kwarg(call, "status_code"))
        if code is None or code < 500:
            continue
        detail = _kwarg(call, "detail")
        if detail is None:
            continue
        referenced = {n.id for n in ast.walk(detail) if isinstance(n, ast.Name)} & exception_names
        if referenced:
            offenders.append((call.lineno, ast.unparse(detail)))

    assert not offenders, (
        f"{module_path.name} builds a 5xx detail from caught-exception text at {offenders}; "
        "log the exception server-side and return a fixed message"
    )


def test_analyze_unexpected_fault_is_500_without_leaking_internals(api_client, tenant_id, monkeypatch) -> None:
    """Behavioural counterpart to the two structural properties above.

    The source guards say the code no longer *can* answer 501 or echo exception
    text; this drives the real catch-all and observes what a client sees.
    """
    from recognition.interface_adapters.http.routers import analyze as analyze_router

    async def _boom(**_kwargs: object) -> object:
        raise RuntimeError('psycopg: relation "identity_scan_jobs" does not exist')

    monkeypatch.setattr(analyze_router, "_schedule_analysis", _boom)

    response = api_client.post(
        "/recognition/analyze",
        json={"media_ids": ["11111111-1111-4111-8111-111111111111"], "tenant_id": tenant_id},
    )

    assert response.status_code == 500, response.text
    assert response.status_code != 501
    assert "psycopg" not in response.text
    assert "identity_scan_jobs" not in response.text
    assert response.json()["detail"] == analyze_router.INTERNAL_ERROR_DETAIL


# ---------------------------------------------------------------------------
# Streaming boundary: reconnect policy
# ---------------------------------------------------------------------------


async def _drain_prelude(gen) -> list[str]:  # noqa: ANN001 - async generator
    """Collect the frames the SSE generator emits before it blocks on the broadcaster."""
    frames: list[str] = []
    for _ in range(2):
        frames.append(await gen.__anext__())
    return frames


@pytest.mark.asyncio
async def test_sse_stream_sends_a_jittered_retry_field() -> None:
    """RES-06 / API-08: the server owns the reconnect policy, and it is spread.

    With no ``retry:`` field every browser uses its own fixed built-in default
    (~3s, no jitter), so a restart or LB event makes every connected tab
    reconnect in lockstep -- a self-inflicted thundering herd on an instance
    that is still coming up. Asserting only "a retry field exists" would pass
    against a hardcoded constant, so this also requires the value to vary
    across connections and to stay inside the declared window.
    """
    from recognition.interface_adapters.http.routers import events as events_router

    class _AlwaysConnected:
        async def is_disconnected(self) -> bool:
            return False

    seen: set[int] = set()
    for _ in range(40):
        gen = events_router._event_generator(cast(Any, _AlwaysConnected()), "tenant-1")
        try:
            frames = await asyncio.wait_for(_drain_prelude(gen), timeout=5)
        finally:
            await gen.aclose()

        retry_frames = [f for f in frames if f.startswith("retry:")]
        assert retry_frames, f"SSE stream sent no retry: field; frames={frames!r}"
        assert frames[0].startswith("retry:"), (
            f"retry: must precede any data so it is in force if the stream drops at once; frames={frames!r}"
        )

        value = int(retry_frames[0].split(":", 1)[1].strip())
        low = events_router.SSE_RETRY_BASE_MS
        high = events_router.SSE_RETRY_BASE_MS + events_router.SSE_RETRY_JITTER_MS
        assert low <= value <= high, f"retry {value}ms outside the declared window [{low}, {high}]"
        seen.add(value)

    assert len(seen) > 1, (
        "every connection was told the same reconnect delay; a constant retry: field still reconnects "
        f"the whole herd in lockstep (saw {seen})"
    )


def test_sse_retry_window_is_actually_jittered() -> None:
    """A zero-width jitter window would make the value constant and the guard above moot."""
    from recognition.interface_adapters.http.routers import events as events_router

    assert events_router.SSE_RETRY_JITTER_MS > 0
    assert events_router.SSE_RETRY_BASE_MS > 0
