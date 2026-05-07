from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script_module():
    script_path = REPO_ROOT / "scripts" / "_slice_start_inline.py"
    spec = importlib.util.spec_from_file_location("slice_start_inline_under_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["slice_start_inline_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_record_slice_start_records_failing_test_and_renders_dashboard() -> None:
    mod = _load_script_module()
    calls: dict[str, Any] = {}

    def configure_runtime_stub(runtime: object) -> None:
        calls["runtime"] = runtime

    def record_event_stub(*, event: dict[str, Any]) -> dict[str, Any]:
        calls["event"] = event
        return {"ok": True, "event_kind": event["event_kind"]}

    def render_handoff_stub(**kwargs: Any) -> dict[str, Any]:
        calls.setdefault("render", []).append(kwargs)
        return {"ok": True, "kind": kwargs["kind"]}

    test_command = 'cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/__tests__/DashboardPage.test.tsx -t "renders source-backed replay recency details when conflicts and failures are present"'

    result = mod.record_slice_start(
        repo_root=REPO_ROOT,
        task_ref="E15-20",
        session="E15-20-slice-start",
        test_command=test_command,
        result="Expected failing test before implementation begins.",
        exit_code=1,
        runtime_factory=lambda path: ("runtime", path),
        configure_runtime_fn=configure_runtime_stub,
        record_event_fn=record_event_stub,
        render_handoff_fn=render_handoff_stub,
    )

    assert calls["event"] == {
        "event_kind": "test_result",
        "task_ref": "E15-20",
        "session": "E15-20-slice-start",
        "command": test_command,
        "passed": False,
        "result": "Expected failing test before implementation begins.",
        "exit_code": 1,
    }
    assert calls["render"] == [{"kind": "dashboard"}]
    assert result["record_event"]["event_kind"] == "test_result"