"""Refuse writes against stacks that are not the two named bench stacks (CF-2)."""

from __future__ import annotations

from collections.abc import Iterable

from scripts.bench.stack_pair import BenchError, FIR23_STACK_ALLOWLIST, StackEndpoint


def assert_named_bench_stack(endpoint: StackEndpoint, allowlist: Iterable[str] | None = None) -> None:
    allowed = frozenset(allowlist) if allowlist is not None else frozenset(FIR23_STACK_ALLOWLIST)
    if endpoint.stack_id not in allowed:
        raise BenchError(
            "unnamed_bench_stack",
            f"refusing writes to {endpoint.stack_id!r}; not a named bench stack",
        )
