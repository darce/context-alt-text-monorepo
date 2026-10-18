"""Tests for the user-facing controlled-vocabulary lint gate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "scripts" / "check_controlled_vocabulary.py"
CURRENT_CONFIG = REPO_ROOT / "docs" / "workbay" / "contracts" / "controlled-vocabulary.json"
CURRENT_SOURCE_ROOT = REPO_ROOT / "apps" / "prototype-wp-alt-context"


def _vocabulary(*, known_violations: list[dict] | None = None) -> dict:
    return {
        "schema_version": 1,
        "gate_mode": "baseline",
        "target_audience": "Non-expert WordPress site administrators.",
        "terms": [
            {
                "banned": "cluster",
                "forms": ["cluster", "clusters", "clustered", "clustering"],
                "say": {"noun": "face group", "verb": "group faces"},
                "definition": "A set of photos that appear to show the same person.",
                "rationale": "Names the visible faces and the grouping action in everyday words.",
            }
        ],
        "known_violations": known_violations or [],
    }


def _run_checker(tmp_path: Path, source_files: dict[str, str], vocabulary: dict) -> subprocess.CompletedProcess[str]:
    source_root = tmp_path / "source"
    for relative_path, content in source_files.items():
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    config_path = tmp_path / "controlled-vocabulary.json"
    config_path.write_text(json.dumps(vocabulary))
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--config",
            str(config_path),
            "--source-root",
            str(source_root),
        ],
        capture_output=True,
        check=False,
        text=True,
    )


def test_banned_translatable_fixture_fails_with_location_and_suggestion(tmp_path: Path) -> None:
    result = _run_checker(
        tmp_path,
        {"banned.php": "<?php\n$message = __( 'Cluster the latest results', 'alt-context' );\n"},
        _vocabulary(),
    )

    assert result.returncode == 1
    assert "banned.php:2" in result.stdout
    assert "face group" in result.stdout
    assert "group faces" in result.stdout


def test_clean_fixture_and_non_translatable_internal_terms_pass(tmp_path: Path) -> None:
    result = _run_checker(
        tmp_path,
        {
            "clean.ts": """import { __ } from '@wordpress/i18n';
const cluster_id = 'cluster-internal';
// __('Cluster debugging detail', 'alt-context') is not executable copy.
export const label = __('Group the latest faces', 'alt-context');
""",
            "tests/banned-fixture.php": "<?php\n__( 'Cluster fixture', 'alt-context' );\n",
        },
        _vocabulary(),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No new controlled-vocabulary violations" in result.stdout


def test_plural_and_context_translation_arguments_are_scanned(tmp_path: Path) -> None:
    result = _run_checker(
        tmp_path,
        {
            "messages.ts": """import { _n, _x } from '@wordpress/i18n';
const count = _n('%d face', '%d clusters', 2, 'alt-context');
const title = _x('Cluster result', 'noun: result title', 'alt-context');
""",
        },
        _vocabulary(),
    )

    assert result.returncode == 1
    assert "messages.ts:2" in result.stdout
    assert "messages.ts:3" in result.stdout


def test_tracked_baseline_violation_warns_but_new_violation_fails(tmp_path: Path) -> None:
    vocabulary = _vocabulary(
        known_violations=[
            {
                "path": "legacy.php",
                "message": "Cluster results",
                "banned": "cluster",
                "occurrences": 1,
            }
        ]
    )
    baseline = _run_checker(
        tmp_path,
        {"legacy.php": "<?php\n__( 'Cluster results', 'alt-context' );\n"},
        vocabulary,
    )
    introduced = _run_checker(
        tmp_path,
        {
            "legacy.php": (
                "<?php\n__( 'Cluster results', 'alt-context' );\n__( 'Another cluster appeared', 'alt-context' );\n"
            )
        },
        vocabulary,
    )

    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    assert "1 known violation" in baseline.stdout
    assert "KNOWN legacy.php" not in baseline.stdout
    assert introduced.returncode == 1
    assert "legacy.php:3" in introduced.stdout


def test_baseline_allowance_is_consumed_across_duplicate_strings(tmp_path: Path) -> None:
    vocabulary = _vocabulary(
        known_violations=[
            {
                "path": "legacy.php",
                "message": "Cluster results",
                "banned": "cluster",
                "occurrences": 1,
            }
        ]
    )

    result = _run_checker(
        tmp_path,
        {"legacy.php": ("<?php\n__( 'Cluster results', 'alt-context' );\n__( 'Cluster results', 'alt-context' );\n")},
        vocabulary,
    )

    assert result.returncode == 1
    assert "legacy.php:3" in result.stdout


def test_malformed_vocabulary_fails_closed_at_load(tmp_path: Path) -> None:
    malformed = _vocabulary()
    del malformed["terms"][0]["rationale"]

    result = _run_checker(
        tmp_path,
        {"clean.php": "<?php\n__( 'Clean', 'alt-context' );\n"},
        malformed,
    )

    assert result.returncode == 2
    assert "terms[0].rationale" in result.stderr


def test_current_contract_is_baseline_aware_and_covers_current_plugin_source() -> None:
    payload = json.loads(CURRENT_CONFIG.read_text())

    assert payload["gate_mode"] == "baseline"
    assert payload["known_violations"], "the current debt must be explicit and reviewable"
    assert {term["banned"] for term in payload["terms"]} == {
        "cluster",
        "embedding",
        "tenant",
        "provenance",
        "outlier",
    }

    result = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--config",
            str(CURRENT_CONFIG),
            "--source-root",
            str(CURRENT_SOURCE_ROOT),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No new controlled-vocabulary violations" in result.stdout


def test_current_contract_baseline_has_unique_safe_entries() -> None:
    payload = json.loads(CURRENT_CONFIG.read_text())
    entries = payload["known_violations"]

    keys = {(entry["path"], entry["message"], entry["banned"]) for entry in entries}
    assert len(keys) == len(entries)
    assert all(not Path(entry["path"]).is_absolute() for entry in entries)
    assert all(".." not in Path(entry["path"]).parts for entry in entries)
