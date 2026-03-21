from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "backend_registry.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
    assert "codex-cli" in choices
    assert "codex-subagent" in choices
    assert "copilot-host" in choices


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
    assert spec.adapter_class is not None


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


def test_get_adapter_returns_initialized_adapter() -> None:
    mod = _load_module()
    mock_cli = mock.Mock()
    mock_factory = mock.Mock(return_value=mock_cli)
    # Replace the adapter_class directly in the spec
    spec = mod.get_backend_spec("codex-cli")
    new_spec = mod.BackendSpec(
        kind=spec.kind,
        adapter_class=mock_factory,
        description=spec.description,
        capabilities=spec.capabilities,
    )
    with mock.patch.dict(mod.BACKENDS, {"codex-cli": new_spec}):
        adapter = mod.get_adapter("codex-cli", codex_bin="/path/to/codex")
        mock_factory.assert_called_once_with()
        mock_cli.assert_called_once_with(codex_bin="/path/to/codex")
        assert adapter is mock_cli.return_value


def test_get_adapter_for_bridge_returns_subagent_adapter() -> None:
    mod = _load_module()
    runner = mock.Mock()
    mock_sub = mock.Mock()
    spec = mod.get_backend_spec("codex-subagent")
    new_spec = mod.BackendSpec(
        kind=spec.kind,
        adapter_class=mock.Mock(return_value=mock_sub),
        description=spec.description,
        module=spec.module,
        capabilities=spec.capabilities,
    )
    with mock.patch.dict(mod.BACKENDS, {"codex-subagent": new_spec}):
        with mock.patch.object(mod, "resolve_bridge", return_value=runner):
            adapter = mod.get_adapter("codex-subagent")
            mock_sub.assert_called_once_with(runner, name="codex-subagent")
            assert adapter is mock_sub.return_value


def test_get_backend_choices_includes_copilot_host() -> None:
    mod = _load_module()
    choices = mod.get_backend_choices()
    assert "copilot-host" in choices


def test_backend_spec_has_capabilities() -> None:
    mod = _load_module()
    spec = mod.get_backend_spec("codex-subagent")
    assert spec.capabilities.supports_structured_output is True
    assert spec.capabilities.supports_sandbox is True
    assert spec.capabilities.supports_sync_turn is True


def test_copilot_host_capabilities() -> None:
    mod = _load_module()
    spec = mod.get_backend_spec("copilot-host")
    assert spec.kind == "bridge"
    assert spec.capabilities.supports_structured_output is False
    assert spec.capabilities.supports_sandbox is False
    assert spec.capabilities.supports_sync_turn is True


def test_cli_backend_capabilities() -> None:
    mod = _load_module()
    spec = mod.get_backend_spec("codex-cli")
    assert spec.capabilities.supports_sync_turn is False
    assert spec.capabilities.supports_sandbox is True


def test_register_backend_adds_new_entry() -> None:
    mod = _load_module()
    mock_adapter = mock.Mock()
    custom_spec = mod.BackendSpec(
        kind="bridge",
        adapter_class=mock_adapter,
        module="my_custom_bridge",
        description="Custom bridge for testing.",
        capabilities=mod.BackendCapabilities(
            supports_structured_output=True,
            supports_sandbox=False,
            supports_sync_turn=True,
        ),
    )
    mod.register_backend("my-custom", custom_spec)
    try:
        assert "my-custom" in mod.get_backend_choices()
        assert mod.get_backend_spec("my-custom") is custom_spec
    finally:
        del mod.BACKENDS["my-custom"]


def test_detect_runtime_returns_none_without_vscode_signals() -> None:
    mod = _load_module()
    with mock.patch.dict("os.environ", {}, clear=True):
        assert mod.detect_runtime() is None


def test_detect_runtime_returns_copilot_host_with_vscode_signals() -> None:
    mod = _load_module()
    env = {
        "VSCODE_PID": "12345",
        "VSCODE_AGENT_FOLDER": "/some/path/copilot-agent",
    }
    with mock.patch.dict("os.environ", env, clear=True):
        assert mod.detect_runtime() == "copilot-host"


def test_detect_runtime_returns_none_with_vscode_but_no_copilot() -> None:
    mod = _load_module()
    env = {"VSCODE_PID": "12345"}
    with mock.patch.dict("os.environ", env, clear=True):
        assert mod.detect_runtime() is None


def test_find_codex_from_search_paths(tmp_path: Path) -> None:
    mod = _load_module()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_bin = fake_home / ".local" / "bin" / "codex"
    fake_bin.parent.mkdir(parents=True)
    fake_bin.write_text("#!/bin/sh")
    fake_bin.chmod(0o755)

    def fake_exists(p):
        return str(p) == str(fake_bin)

    with (
        mock.patch("pathlib.Path.home", return_value=fake_home),
        mock.patch.object(mod.Path, "exists", autospec=True) as mock_exists
    ):
        mock_exists.side_effect = lambda self: str(self) == str(fake_bin)
        # find_codex should pick it up from {home}/.local/bin/codex
        # because we mocked exists() to only be True for that fake bin
        assert mod.find_codex() == str(fake_bin)


def test_probe_capabilities_codex_cli_not_found() -> None:
    mod = _load_module()
    with mock.patch.object(mod, "find_codex", side_effect=RuntimeError("not found")):
        caps = mod.probe_capabilities("codex-cli")
        assert caps.is_available is False
        assert caps.supports_reasoning_effort is False


def test_probe_capabilities_codex_cli_found_with_reasoning() -> None:
    mod = _load_module()
    fake_help = "Options:\n  --reasoning-effort [low|medium|high]"
    with (
        mock.patch.object(mod, "find_codex", return_value="/bin/codex"),
        mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=fake_help)),
    ):
        caps = mod.probe_capabilities("codex-cli")
        assert caps.is_available is True
        assert caps.supports_reasoning_effort is True


def test_probe_capabilities_codex_cli_found_without_reasoning() -> None:
    mod = _load_module()
    fake_help = "Options:\n  --model NAME"
    with (
        mock.patch.object(mod, "find_codex", return_value="/bin/codex"),
        mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=fake_help)),
    ):
        caps = mod.probe_capabilities("codex-cli")
        assert caps.is_available is True
        assert caps.supports_reasoning_effort is False
