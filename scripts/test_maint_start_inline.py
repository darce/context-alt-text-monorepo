from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "_maint_start_inline.py"
    spec = importlib.util.spec_from_file_location("maint_start_inline_under_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["maint_start_inline_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_build_maint_task_ref_normalizes_slug() -> None:
    mod = _load_module()
    assert (
        mod.build_maint_task_ref("  LocalWP Admin Assets  ", today=date(2026, 4, 27))
        == "MAINT-localwp-admin-assets-20260427"
    )


def test_build_maint_task_ref_rejects_empty_slug() -> None:
    mod = _load_module()
    try:
        mod.build_maint_task_ref("---", today=date(2026, 4, 27))
    except ValueError as exc:
        assert "slug" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError for empty normalized slug")


def test_main_registers_task_and_renders_views(monkeypatch, tmp_path, capsys) -> None:
    mod = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("SLUG", "agent-ergo")
    monkeypatch.setenv("OBJECTIVE", "Resolve startup friction")

    class DummyRuntimeConfig:
        @staticmethod
        def for_repo(path):
            return {"repo": str(path)}

    calls: dict[str, object] = {}

    monkeypatch.setattr(mod, "RuntimeConfig", DummyRuntimeConfig)
    monkeypatch.setattr(mod, "configure_runtime", lambda runtime: calls.setdefault("runtime", runtime))
    monkeypatch.setattr(mod, "get_handoff_state", lambda sections=None: {"data": {"active": None}})
    monkeypatch.setattr(mod, "switch_task", lambda **kwargs: {"ok": True, "data": {"active": {"revision": 4}}})

    def fake_set_handoff_state(**kwargs):
        calls["set_handoff_state"] = kwargs
        return {"ok": True, "data": {"active": {"revision": 4}}}

    render_calls: list[dict[str, object]] = []

    def fake_render_handoff(**kwargs):
        render_calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(mod, "set_handoff_state", fake_set_handoff_state)
    monkeypatch.setattr(mod, "render_handoff", fake_render_handoff)

    assert mod.main() == 0

    out = capsys.readouterr().out
    assert "MAINT-agent-ergo-" in out
    assert calls["set_handoff_state"] == {
        "task_ref": out.split("task=")[1].split()[0],
        "objective": "Resolve startup friction",
        "status": "in_progress",
        "target_branch": "main",
        "target_worktree_path": str(repo_root),
        "expected_revision": None,
    }
    assert render_calls == [
        {"kind": "current_task", "task_ref": out.split("task=")[1].split()[0]},
        {"kind": "dashboard"},
    ]