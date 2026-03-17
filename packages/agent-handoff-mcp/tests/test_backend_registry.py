from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "backend_registry.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("backend_registry", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load backend_registry module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_get_backend_choices_returns_tuple() -> None:
    mod = _load_module()
    choices = mod.get_backend_choices()
    assert isinstance(choices, tuple)
    assert choices == ("codex-cli", "codex-subagent")


def test_validate_backend_accepts_registered_backend() -> None:
    mod = _load_module()
    assert mod.validate_backend("codex-cli") == "codex-cli"


def test_validate_backend_rejects_unknown_backend() -> None:
    mod = _load_module()
    with pytest.raises(RuntimeError, match="Unsupported execution backend 'unknown'"):
        mod.validate_backend("unknown")


def test_get_backend_spec_returns_registered_spec() -> None:
    mod = _load_module()
    spec = mod.get_backend_spec("codex-subagent")
    assert spec.kind == "bridge"
    assert spec.module == "codex_subagent_bridge"


def test_resolve_bridge_rejects_cli_backend() -> None:
    mod = _load_module()
    with pytest.raises(RuntimeError, match="does not expose a bridge runner"):
        mod.resolve_bridge("codex-cli")


def test_resolve_bridge_rejects_unknown_backend() -> None:
    mod = _load_module()
    with pytest.raises(RuntimeError, match="Unsupported execution backend 'unknown'"):
        mod.resolve_bridge("unknown")


def test_resolve_bridge_reports_missing_module() -> None:
    mod = _load_module()
    with mock.patch.object(mod.importlib, "import_module", side_effect=ImportError("missing")):
        with pytest.raises(RuntimeError, match="codex-subagent backend is unavailable"):
            mod.resolve_bridge("codex-subagent")


def test_resolve_bridge_returns_runner() -> None:
    mod = _load_module()
    runner = mock.Mock()
    fake_bridge = mock.Mock(run_subagent=runner)
    with mock.patch.object(mod.importlib, "import_module", return_value=fake_bridge):
        assert mod.resolve_bridge("codex-subagent") is runner
