"""Regression tests for the Vault secret writer entry point."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

MODULE_PATH = Path(__file__).parents[1] / "_vault_put_secret.py"
SPEC = importlib.util.spec_from_file_location("vault_put_secret", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
vault_put_secret = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vault_put_secret)


@pytest.mark.parametrize("timeout", ["-1", "nan", "inf", "-inf"])
def test_invalid_readable_timeout_is_rejected_before_vault_mutation(monkeypatch, timeout):
    vaults_client = Mock()
    fake_oci = SimpleNamespace(
        vault=SimpleNamespace(VaultsClient=Mock(return_value=vaults_client)),
    )
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setattr(
        sys,
        "argv",
        ["_vault_put_secret.py", "--secret-name", "OCIR_AUTH_TOKEN", "--readable-timeout", timeout],
    )

    with pytest.raises(SystemExit) as exc_info:
        vault_put_secret.main()

    assert exc_info.value.code == 2
    vaults_client.create_secret.assert_not_called()
    vaults_client.update_secret.assert_not_called()
