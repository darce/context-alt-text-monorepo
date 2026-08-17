"""S2R5-24 — operator-owned surfaces share one exit-contract spelling."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[5]
_ENV = _REPO_ROOT / "scripts" / "eval_exit_contract.env"
_PY = _REPO_ROOT / "scripts" / "eval_exit_contract.py"
_REGEN = _REPO_ROOT / "scripts" / "regen_eval_report.py"
_WRAPPER = _REPO_ROOT / "scripts" / "eval-captions.sh"
_MAKEFILE = _REPO_ROOT / "Makefile"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_contract_numbers_are_0_1_2_3() -> None:
    contract = _load(_PY, "eval_exit_contract_under_test")
    assert contract.EXIT_CLEAN == 0
    assert contract.EXIT_PARTIAL == 1
    assert contract.EXIT_USAGE == 2
    assert contract.EXIT_REFUSED == 3
    env = _ENV.read_text(encoding="utf-8")
    assert "EVAL_EXIT_CLEAN=0" in env
    assert "EVAL_EXIT_PARTIAL=1" in env
    assert "EVAL_EXIT_USAGE=2" in env
    assert "EVAL_EXIT_REFUSED=3" in env


def test_regen_imports_shared_contract() -> None:
    regen = _load(_REGEN, "regen_eval_report_contract_under_test")
    contract = _load(_PY, "eval_exit_contract_under_test")
    assert regen.CLI_EXIT_CLEAN == contract.EXIT_CLEAN
    assert regen.CLI_EXIT_PARTIAL == contract.EXIT_PARTIAL
    assert regen.CLI_EXIT_USAGE == contract.EXIT_USAGE
    assert regen.CLI_EXIT_REFUSED == contract.EXIT_REFUSED
    source = _REGEN.read_text(encoding="utf-8")
    assert "CLI_EXIT_CLEAN = 0" not in source
    assert "from eval_exit_contract import" in source


def test_wrapper_and_makefile_source_the_env() -> None:
    wrapper = _WRAPPER.read_text(encoding="utf-8")
    makefile = _MAKEFILE.read_text(encoding="utf-8")
    assert "eval_exit_contract.env" in wrapper
    assert 'eq "$EVAL_EXIT_REFUSED"' in wrapper
    assert "include $(ROOT_MAKEFILE_DIR)/scripts/eval_exit_contract.env" in makefile
