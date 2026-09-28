from __future__ import annotations

import importlib
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def load_module(name: str):
    """Import env.<name> lazily so the suite collects before the implementation exists."""
    return importlib.import_module(f"env.{name}")


@pytest.fixture
def write_manifest(tmp_path: Path):
    """Write targets.toml plus named fragments under tmp_path/manifest.d; return the root."""

    def _write(targets: str, **fragments: str) -> Path:
        root = tmp_path / "envroot"
        mdir = root / "manifest.d"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "targets.toml").write_text(textwrap.dedent(targets), encoding="utf-8")
        for filename, body in fragments.items():
            (mdir / f"{filename}.toml").write_text(textwrap.dedent(body), encoding="utf-8")
        return root

    return _write
