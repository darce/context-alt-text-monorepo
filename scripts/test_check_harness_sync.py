from __future__ import annotations

import copy
import json
import textwrap
from pathlib import Path

import pytest
import yaml

from scripts.check_harness_sync import (
    _check_branch_isolation,
    _check_cold_start,
    _load_contract,
    run_checks,
)


def _valid_contract(repo_root: Path) -> dict:
    return {
        "version": 1,
        "cold_start": {
            "shared_steps": [
                {
                    "id": "make-context",
                    "description": "run make context at session start",
                    "phrase": "make context",
                    "references": ["CLAUDE.md", "copilot.md"],
                },
            ],
        },
        "branch_isolation": {
            "protected_branches": ["main", "master"],
            "code_roots": ["apps/", "packages/"],
            "protected_extensions": [".py", ".sh"],
            "enforcers": [
                {"path": "hooks/py_guard.py", "harness": "vscode"},
                {"path": "hooks/sh_guard.sh", "harness": "claude"},
            ],
        },
        "hooks": {"pre_tool_use": [], "post_tool_use": []},
    }


def _write_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "hooks").mkdir(parents=True)
    (repo / "CLAUDE.md").write_text("Run make context at session start.\n")
    (repo / "copilot.md").write_text("Remember: make context.\n")
    (repo / "hooks" / "py_guard.py").write_text(
        textwrap.dedent(
            '''
            _PROTECTED_ROOTS = ("apps/", "packages/")
            _CODE_EXTENSIONS = {".py", ".sh"}
            if branch in {"main", "master"}:
                pass
            '''
        )
    )
    (repo / "hooks" / "sh_guard.sh").write_text(
        textwrap.dedent(
            '''
            if [ "$BRANCH" != "main" ] && [ "$BRANCH" != "master" ]; then
              exit 0
            fi
            if [[ "$REL" =~ \\.(py|sh)$ ]] && [[ "$REL" =~ ^(apps/|packages/) ]]; then
              exit 2
            fi
            '''
        )
    )
    return repo


def test_cold_start_passes_when_phrase_present_in_references(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract(repo)
    errors = _check_cold_start(contract, repo_root=repo)
    assert errors == []


def test_cold_start_fails_when_phrase_missing_from_reference(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "copilot.md").write_text("no phrase here\n")
    contract = _valid_contract(repo)
    errors = _check_cold_start(contract, repo_root=repo)
    assert any("copilot.md" in err and "make context" in err for err in errors)


def test_cold_start_fails_when_reference_missing(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract(repo)
    contract["cold_start"]["shared_steps"][0]["references"].append("missing.md")
    errors = _check_cold_start(contract, repo_root=repo)
    assert any("missing.md" in err and "not found" in err for err in errors)


def test_cold_start_requires_phrase_and_references(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract(repo)
    contract["cold_start"]["shared_steps"] = [{"id": "broken"}]
    errors = _check_cold_start(contract, repo_root=repo)
    assert any("broken" in err and "phrase" in err for err in errors)


def test_branch_isolation_passes_against_both_harness_enforcers(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract(repo)
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert errors == []


def test_branch_isolation_fails_when_enforcer_missing_code_root(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    (repo / "hooks" / "sh_guard.sh").write_text('BRANCH="main"\n"master"\n\\.(py|sh)$\n')
    contract = _valid_contract(repo)
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert any("sh_guard.sh" in err and "apps/" in err for err in errors)


def test_branch_isolation_fails_when_enforcer_file_missing(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    contract = _valid_contract(repo)
    contract["branch_isolation"]["enforcers"].append(
        {"path": "hooks/not_there.sh", "harness": "claude"}
    )
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert any("not_there.sh" in err and "not found" in err for err in errors)


def test_branch_isolation_accepts_bare_extension_token_in_regex_alternation(tmp_path: Path) -> None:
    repo = _write_repo(tmp_path)
    # Shell uses `\.(py|sh)$` — the `py` and `sh` tokens appear bare in a regex
    # alternation. The validator should treat this as a valid reference.
    (repo / "hooks" / "sh_guard.sh").write_text(
        'BRANCH="main" or "master"; apps/ packages/; \\.(py|sh)$\n'
    )
    contract = _valid_contract(repo)
    errors = _check_branch_isolation(contract, repo_root=repo)
    assert errors == []


def test_real_contract_passes_run_checks() -> None:
    """Safety net: the committed harness-protocol.yaml plus real surfaces must pass."""
    contract = _load_contract()
    errors = run_checks(contract, check_api_surface=True)
    assert errors == [], errors
