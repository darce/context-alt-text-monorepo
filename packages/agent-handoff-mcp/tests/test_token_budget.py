"""Tests for the token_budget.py pre-commit hook.

Covers:
- _approx_tokens: character-to-token approximation
- check: returns empty list when all files are under budget; returns violating files when over
- main: exit 0 on pass, exit 1 on violation; handles missing files gracefully
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load token_budget as a module (it lives under .github/hooks, not a Python package)
_HOOK_PATH = Path(__file__).resolve().parents[3] / ".github" / "hooks" / "token_budget.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("token_budget", _HOOK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load token_budget from {_HOOK_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# _approx_tokens
# ---------------------------------------------------------------------------


class TestApproxTokens:
    def test_empty_string_returns_one(self) -> None:
        mod = _load_module()
        assert mod._approx_tokens("") == 1

    def test_four_chars_returns_one(self) -> None:
        mod = _load_module()
        assert mod._approx_tokens("abcd") == 1

    def test_eight_chars_returns_two(self) -> None:
        mod = _load_module()
        assert mod._approx_tokens("abcdefgh") == 2

    def test_large_text_proportional(self) -> None:
        mod = _load_module()
        text = "a" * 4000
        assert mod._approx_tokens(text) == 1000


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


class TestCheck:
    def test_file_under_budget_not_returned(self, tmp_path: Path) -> None:
        mod = _load_module()
        short_file = tmp_path / "short.md"
        short_file.write_text("# Hello\n" * 10, encoding="utf-8")  # ~80 chars -> ~20 tokens
        result = mod.check([short_file], budget=2000)
        assert result == []

    def test_file_over_budget_returned(self, tmp_path: Path) -> None:
        mod = _load_module()
        big_file = tmp_path / "big.md"
        big_file.write_text("x" * 40_000, encoding="utf-8")  # 10,000 tokens
        result = mod.check([big_file], budget=2000)
        assert len(result) == 1
        path, tokens = result[0]
        assert path == big_file
        assert tokens > 2000

    def test_missing_file_skipped(self, tmp_path: Path) -> None:
        mod = _load_module()
        missing = tmp_path / "nonexistent.md"
        result = mod.check([missing], budget=2000)
        assert result == []

    def test_exactly_at_budget_not_returned(self, tmp_path: Path) -> None:
        mod = _load_module()
        # 2000 tokens -> 8000 chars; should NOT be flagged (strictly greater than)
        at_limit = tmp_path / "at_limit.md"
        at_limit.write_text("a" * 8000, encoding="utf-8")
        result = mod.check([at_limit], budget=2000)
        assert result == []

    def test_one_over_one_under(self, tmp_path: Path) -> None:
        mod = _load_module()
        small = tmp_path / "small.md"
        large = tmp_path / "large.md"
        small.write_text("a" * 100, encoding="utf-8")  # 25 tokens
        large.write_text("a" * 100_000, encoding="utf-8")  # 25,000 tokens
        result = mod.check([small, large], budget=2000)
        assert len(result) == 1
        assert result[0][0] == large


# ---------------------------------------------------------------------------
# main (CLI): exit code behavior
# ---------------------------------------------------------------------------


class TestMain:
    def test_exit_zero_all_files_under_budget(self, tmp_path: Path) -> None:
        mod = _load_module()
        small = tmp_path / "ok.md"
        small.write_text("# Title\n", encoding="utf-8")
        rc = mod.main([str(small), "--budget", "2000"])
        assert rc == 0

    def test_exit_one_file_over_budget(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        mod = _load_module()
        large = tmp_path / "big.md"
        large.write_text("x" * 50_000, encoding="utf-8")
        rc = mod.main([str(large), "--budget", "2000"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "exceed" in captured.out.lower()

    def test_exit_zero_no_files_given(self) -> None:
        mod = _load_module()
        rc = mod.main(["--budget", "2000"])
        assert rc == 0

    def test_custom_budget_respected(self, tmp_path: Path) -> None:
        mod = _load_module()
        # 10 chars = 2 tokens; over budget=1, under budget=5
        f = tmp_path / "f.md"
        f.write_text("a" * 10, encoding="utf-8")
        assert mod.main([str(f), "--budget", "1"]) == 1
        assert mod.main([str(f), "--budget", "5"]) == 0

    def test_warning_message_names_file(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        mod = _load_module()
        over = tmp_path / "over_budget.md"
        over.write_text("z" * 40_000, encoding="utf-8")
        mod.main([str(over), "--budget", "2000"])
        captured = capsys.readouterr()
        assert over.name in captured.out
