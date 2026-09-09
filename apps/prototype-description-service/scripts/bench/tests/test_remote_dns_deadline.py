"""Stalled DNS must lose to the whole-fetch deadline.

GPU-LAUNCH-2163176-A-02. `_fetch_remote` currently invokes the resolver
synchronously with no remaining-budget wrap ([API-04] Latency, [RES-02],
[RES-03]). `_default_resolve` is unbounded `socket.getaddrinfo`. A blocked
resolve can hold the fetch past `deadline_at`, then pin a late answer and
start I/O. Intended contract: typed `media_resource_failed` at the caller
deadline, no fetcher, no pin of a late (including non-public) answer
([TEST-15] [DATA-13]).
"""

from __future__ import annotations

import threading
import time

from scripts.bench import corpus as corpus_mod
from scripts.bench.corpus import reset_media_host_pins
from scripts.bench.stack_pair import BenchError

_URL = "https://media.example.com/remote.jpg"
_HOST = "media.example.com"
_LATE_PRIVATE = "10.0.0.5"
_DEADLINE_S = 0.2
_SAFETY_S = 1.5
_SLACK_S = 0.45


class _BoundedStallResolver:
    """Resolver that blocks until released, with a finite safety watchdog."""

    def __init__(self, answer: list[str], *, safety_s: float) -> None:
        self._answer = list(answer)
        self._safety_s = safety_s
        self.release = threading.Event()
        self.entered = threading.Event()
        self.returned = threading.Event()
        self.host: str | None = None
        self._watchdog = threading.Timer(safety_s, self.release.set)
        self._watchdog.daemon = True

    def start(self) -> None:
        self._watchdog.start()

    def __call__(self, host: str) -> list[str]:
        self.host = host
        self.entered.set()
        self.release.wait(timeout=self._safety_s)
        self.returned.set()
        return list(self._answer)

    def close(self) -> None:
        self.release.set()
        self._watchdog.cancel()
        self.returned.wait(timeout=self._safety_s + 0.5)


def test_stalled_resolver_returns_deadline_before_late_answer() -> None:
    """Whole-fetch deadline must win over a blocked resolver ([API-04]).

    The stall is event-gated and watchdog-bounded so cleanup cannot hang.
    A late RFC1918 answer must not be pinned or fetched ([RES-02]).
    """
    reset_media_host_pins()
    stall = _BoundedStallResolver([_LATE_PRIVATE], safety_s=_SAFETY_S)
    fetch_calls: list[tuple[str, set[str]]] = []

    def fetcher(url: str, addrs: set[str]) -> bytes:
        fetch_calls.append((url, set(addrs)))
        return b"must-not-fetch-after-stalled-dns"

    stall.start()
    started = time.monotonic()
    deadline_at = started + _DEADLINE_S
    error: BenchError | None = None
    try:
        try:
            corpus_mod._fetch_remote(
                _URL,
                allow_private_source=False,
                resolver=stall,
                fetcher=fetcher,
                deadline_at=deadline_at,
            )
        except BenchError as exc:
            error = exc
        elapsed = time.monotonic() - started
    finally:
        stall.close()
        pinned_hosts_after = {host: set(addrs) for host, addrs in corpus_mod._PINNED_HOSTS.items()}
        pinned_after_late_answer = {addr for addrs in pinned_hosts_after.values() for addr in addrs}
        reset_media_host_pins()

    assert error is not None, (
        "expected media_resource_failed at the caller deadline; "
        f"_fetch_remote completed in {elapsed:.3f}s without a typed failure "
        f"(resolver returned={stall.returned.is_set()})"
    )
    assert elapsed <= _DEADLINE_S + _SLACK_S, (
        "synchronous DNS stall violated the whole-fetch deadline "
        f"(elapsed {elapsed:.3f}s > budget {_DEADLINE_S}+{_SLACK_S}s; "
        f"code={error.code!r} message={error!s})"
    )
    assert error.code == "media_resource_failed"
    assert "deadline" in str(error).lower()
    assert fetch_calls == []
    assert stall.entered.is_set()
    assert _LATE_PRIVATE not in pinned_after_late_answer
    assert _HOST not in pinned_hosts_after
    assert _HOST.lower() not in pinned_hosts_after
    assert corpus_mod._is_non_public(_LATE_PRIVATE) is True
    assert corpus_mod._is_non_public("203.0.113.10") is False
