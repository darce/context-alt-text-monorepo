"""E17-9 Slice 3: cross-vendor BackendAdapter equivalence.

Asserts that the parallel-review pattern produces the same MCP-shaped
result across every registered backend that is actually available at
test time. The matrix is anchored by ``structured-turn`` — an
always-available in-repo adapter that composes
``agent_orchestrator_mcp.run_structured_turn`` without a host bridge —
so default CI never degenerates to an all-skip green. Per-vendor
bridges and CLIs (``codex-subagent``, ``copilot-host``, ``codex-cli``,
``claude-code``) skip cleanly when their host prerequisite is missing.

The equivalence tuple is ``(count, severity_distribution,
verified_commit_sha)`` on the reviewer response. An adapter wrapper
that silently drops one of those fields must break the equivalence
assertion (drift test).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable
from unittest import mock

import pytest

from agent_orchestrator_mcp.orchestration import backend_registry
from agent_orchestrator_mcp.orchestration.backend_adapter import BackendAdapter, BackendResult

CANONICAL_RESPONSE: dict[str, Any] = {
    "handoff_action": "needs_guidance",
    "summary": "3 findings (1H/1M/1L)",
    "details": "See review_findings rows under REV-A task_ref.",
    "tests_run": [],
    "blockers": [],
    "changed_files": [],
    "count": 3,
    "severity_distribution": {"high": 1, "medium": 1, "low": 1},
    "verified_commit_sha": "0123456789abcdef0123456789abcdef01234567",
}

EXPECTED_TUPLE = (
    CANONICAL_RESPONSE["count"],
    CANONICAL_RESPONSE["severity_distribution"],
    CANONICAL_RESPONSE["verified_commit_sha"],
)


def _extract_tuple(result: BackendResult) -> tuple[int, dict[str, int], str]:
    raw = result.raw_payload or {}
    return (
        raw.get("count"),
        raw.get("severity_distribution"),
        raw.get("verified_commit_sha"),
    )


def _structured_turn_available() -> bool:
    return "structured-turn" in backend_registry.get_backend_choices()


def _codex_subagent_available() -> bool:
    try:
        backend_registry.resolve_bridge("codex-subagent")
    except RuntimeError:
        return False
    return True


def _copilot_host_available() -> bool:
    try:
        backend_registry.resolve_bridge("copilot-host")
    except RuntimeError:
        return False
    return True


def _codex_cli_available() -> bool:
    return shutil.which("codex") is not None


def _claude_code_available() -> bool:
    return shutil.which("claude") is not None


def _drive_structured_turn(prompt: str, schema: dict[str, Any], worktree: Path) -> BackendResult:
    adapter_cls = backend_registry.get_backend_spec("structured-turn").adapter_class
    if not isinstance(adapter_cls, type):
        adapter_cls = adapter_cls()
    adapter = adapter_cls(runner=mock.Mock(return_value=dict(CANONICAL_RESPONSE)))
    return adapter.execute(prompt, schema, worktree)


def _drive_subagent_bridge(kind: str, prompt: str, schema: dict[str, Any], worktree: Path) -> BackendResult:
    runner = mock.Mock(return_value=dict(CANONICAL_RESPONSE))
    with mock.patch.object(backend_registry, "resolve_bridge", return_value=runner):
        adapter = backend_registry.get_adapter(kind)
    return adapter.execute(prompt, schema, worktree)


def _drive_codex_cli(prompt: str, schema: dict[str, Any], worktree: Path) -> BackendResult:
    adapter = backend_registry.get_adapter("codex-cli")

    def fake_run(cmd, stdin_fh, env, heartbeat_interval, progress_callback):  # type: ignore[no-untyped-def]
        res_idx = cmd.index("-o") + 1
        Path(cmd[res_idx]).write_text(json.dumps(dict(CANONICAL_RESPONSE)))
        return mock.Mock(returncode=0, stdout="")

    with mock.patch.object(adapter, "_run_codex_process", side_effect=fake_run):
        return adapter.execute(prompt, schema, worktree)


def _drive_claude_code(prompt: str, schema: dict[str, Any], worktree: Path) -> BackendResult:
    adapter = backend_registry.get_adapter("claude-code")
    completed = mock.Mock(returncode=0, stdout=json.dumps(dict(CANONICAL_RESPONSE)), stderr="")
    with mock.patch("subprocess.run", return_value=completed):
        return adapter.execute(prompt, schema, worktree)


MATRIX: list[tuple[str, Callable[[], bool], Callable[[str, dict[str, Any], Path], BackendResult]]] = [
    ("structured-turn", _structured_turn_available, _drive_structured_turn),
    (
        "codex-subagent",
        _codex_subagent_available,
        lambda p, s, w: _drive_subagent_bridge("codex-subagent", p, s, w),
    ),
    (
        "copilot-host",
        _copilot_host_available,
        lambda p, s, w: _drive_subagent_bridge("copilot-host", p, s, w),
    ),
    ("codex-cli", _codex_cli_available, _drive_codex_cli),
    ("claude-code", _claude_code_available, _drive_claude_code),
]


def test_structured_turn_registered_in_backend_registry() -> None:
    """Default CI always covers ≥1 matrix row — structured-turn anchors that promise."""
    assert "structured-turn" in backend_registry.get_backend_choices()
    spec = backend_registry.get_backend_spec("structured-turn")
    assert spec is not None


def test_structured_turn_adapter_is_importable_and_instantiable() -> None:
    """The adapter class must resolve and instantiate without a host bridge."""
    adapter_factory_or_cls = backend_registry.get_backend_spec("structured-turn").adapter_class
    cls = adapter_factory_or_cls() if not isinstance(adapter_factory_or_cls, type) else adapter_factory_or_cls
    instance = cls(runner=mock.Mock(return_value=dict(CANONICAL_RESPONSE)))
    assert hasattr(instance, "execute") and hasattr(instance, "resolve_reasoning_effort")


@pytest.mark.parametrize("kind,availability,driver", MATRIX, ids=[row[0] for row in MATRIX])
def test_backend_equivalence_on_canonical_response(
    tmp_path: Path,
    kind: str,
    availability: Callable[[], bool],
    driver: Callable[[str, dict[str, Any], Path], BackendResult],
) -> None:
    """Every available backend must produce the canonical equivalence tuple."""
    if not availability():
        pytest.skip(f"{kind} backend not available in this environment")

    worktree = tmp_path / "wt"
    worktree.mkdir()
    result = driver("review this diff", {"type": "object"}, worktree)

    assert _extract_tuple(result) == EXPECTED_TUPLE, (
        f"{kind} produced a different equivalence tuple — adapter is dropping fields."
    )


def test_matrix_never_fully_skips() -> None:
    """Default CI must always run at least one matrix row (structured-turn)."""
    available = [kind for kind, avail, _ in MATRIX if avail()]
    assert "structured-turn" in available, (
        "structured-turn MUST always be available so the matrix never all-skip greens."
    )
    assert len(available) >= 1


def test_structured_turn_rejects_unavailable_backend_envelope(tmp_path: Path) -> None:
    """E17-9-BR-01: {ok:false,error:...} envelope must surface as a hard failure, not
    silently default to handoff_action='needs_guidance'."""
    adapter_cls = backend_registry.get_backend_spec("structured-turn").adapter_class
    if not isinstance(adapter_cls, type):
        adapter_cls = adapter_cls()

    unavailable_envelope = {
        "ok": False,
        "error": "codex-subagent backend is unavailable in this runtime. Provide a host bridge module.",
        "backend": "codex-subagent",
    }
    adapter = adapter_cls(runner=mock.Mock(return_value=unavailable_envelope))

    worktree = tmp_path / "wt"
    worktree.mkdir()
    with pytest.raises(RuntimeError, match="codex-subagent"):
        adapter.execute("review", {"type": "object"}, worktree)


def test_drift_test_catches_silently_dropped_fields(tmp_path: Path) -> None:
    """An adapter wrapper that drops severity_distribution must fail the equivalence assertion."""
    adapter_cls = backend_registry.get_backend_spec("structured-turn").adapter_class
    if not isinstance(adapter_cls, type):
        adapter_cls = adapter_cls()

    class DriftedWrapper:
        """Intentionally drops severity_distribution — simulates a silently broken vendor adapter."""

        def __init__(self, inner: BackendAdapter):
            self._inner = inner

        def execute(self, *args: Any, **kwargs: Any) -> BackendResult:
            result: BackendResult = self._inner.execute(*args, **kwargs)
            payload = dict(result.raw_payload)
            payload.pop("severity_distribution", None)
            return BackendResult(
                handoff_action=result.handoff_action,
                summary=result.summary,
                details=result.details,
                tests_run=result.tests_run,
                blockers=result.blockers,
                changed_files=result.changed_files,
                merge_ready=result.merge_ready,
                token_usage=result.token_usage,
                response_model=result.response_model,
                reasoning_effort=result.reasoning_effort,
                raw_payload=payload,
            )

    inner = adapter_cls(runner=mock.Mock(return_value=dict(CANONICAL_RESPONSE)))
    drifted = DriftedWrapper(inner)

    worktree = tmp_path / "wt"
    worktree.mkdir()
    result = drifted.execute("review", {"type": "object"}, worktree)

    assert _extract_tuple(result) != EXPECTED_TUPLE, (
        "drift test failed to detect a dropped field — equivalence guard is ineffective."
    )
