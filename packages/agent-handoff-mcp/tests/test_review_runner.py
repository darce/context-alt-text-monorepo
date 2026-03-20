from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "review_runner.py"


def _load_review_runner_module():
    spec = importlib.util.spec_from_file_location("review_runner", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load review_runner module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_is_valid_json_schema_object() -> None:
    module = _load_review_runner_module()
    schema = module.REVIEW_OUTPUT_SCHEMA
    assert schema["type"] == "object"
    assert "findings" in schema["properties"]
    assert "summary" in schema["properties"]
    assert set(schema["required"]) == {"findings", "summary"}


def test_schema_findings_items_require_severity_category_file_description() -> None:
    module = _load_review_runner_module()
    items_schema = module.REVIEW_OUTPUT_SCHEMA["properties"]["findings"]["items"]
    assert set(items_schema["required"]) == {"severity", "category", "file_path", "description"}


def test_schema_serializes_to_valid_json() -> None:
    module = _load_review_runner_module()
    serialized = json.dumps(module.REVIEW_OUTPUT_SCHEMA)
    roundtrip = json.loads(serialized)
    assert roundtrip == module.REVIEW_OUTPUT_SCHEMA


# ---------------------------------------------------------------------------
# Convergence tests
# ---------------------------------------------------------------------------


def test_findings_converged_empty_list() -> None:
    module = _load_review_runner_module()
    assert module.findings_converged([]) is True


def test_findings_converged_single_low() -> None:
    module = _load_review_runner_module()
    assert module.findings_converged([{"severity": "low"}]) is True


def test_findings_converged_two_low_fails() -> None:
    module = _load_review_runner_module()
    assert module.findings_converged([{"severity": "low"}, {"severity": "low"}]) is False


def test_findings_converged_one_medium_fails() -> None:
    module = _load_review_runner_module()
    assert module.findings_converged([{"severity": "medium"}]) is False


def test_findings_converged_one_high_fails() -> None:
    module = _load_review_runner_module()
    assert module.findings_converged([{"severity": "high"}]) is False


def test_backend_choices_come_from_registry() -> None:
    module = _load_review_runner_module()
    assert "codex-cli" in module.BACKEND_CHOICES
    assert "codex-subagent" in module.BACKEND_CHOICES
    assert "copilot-host" in module.BACKEND_CHOICES


# ---------------------------------------------------------------------------
# Stack guide detection tests
# ---------------------------------------------------------------------------


def test_detect_python_guide() -> None:
    module = _load_review_runner_module()
    guides = module._detect_stack_guides(["apps/service/main.py", "apps/service/tests/test_main.py"])
    assert guides == ["branch-review-python.md"]


def test_detect_typescript_guide() -> None:
    module = _load_review_runner_module()
    guides = module._detect_stack_guides(["js/src/App.tsx", "js/src/utils.ts"])
    assert guides == ["branch-review-typescript.md"]


def test_detect_php_guide() -> None:
    module = _load_review_runner_module()
    guides = module._detect_stack_guides(["src/Controller.php"])
    assert guides == ["branch-review-php.md"]


def test_detect_mixed_guides_deduplicates() -> None:
    module = _load_review_runner_module()
    guides = module._detect_stack_guides([
        "apps/service/main.py",
        "js/src/App.tsx",
        "js/src/utils.ts",
        "src/Plugin.php",
    ])
    assert "branch-review-python.md" in guides
    assert "branch-review-typescript.md" in guides
    assert "branch-review-php.md" in guides
    assert len(guides) == 3


def test_detect_no_guides_for_unknown_extensions() -> None:
    module = _load_review_runner_module()
    guides = module._detect_stack_guides(["README.md", "Makefile", "config.json"])
    assert guides == []


# ---------------------------------------------------------------------------
# Prompt rendering tests
# ---------------------------------------------------------------------------


def test_prompt_includes_changed_files() -> None:
    module = _load_review_runner_module()
    prompt = module._build_review_prompt(
        changed_files=["src/main.py", "src/utils.py"],
        diff_stat="2 files changed, 10 insertions(+)",
        stack_guides=[],
        lane_id="backend-domain",
    )
    assert "src/main.py" in prompt
    assert "src/utils.py" in prompt
    assert "Lane: backend-domain" in prompt


def test_prompt_omits_stack_section_when_no_matching_guides() -> None:
    module = _load_review_runner_module()
    prompt = module._build_review_prompt(
        changed_files=["README.md"],
        diff_stat="",
        stack_guides=[],
        lane_id=None,
    )
    assert "BRANCH REVIEW GUIDE" in prompt
    # No stack guide sections when none match
    assert "BRANCH-REVIEW-PYTHON" not in prompt
    assert "BRANCH-REVIEW-TYPESCRIPT" not in prompt
    assert "BRANCH-REVIEW-PHP" not in prompt


def test_prompt_includes_diff_stat() -> None:
    module = _load_review_runner_module()
    prompt = module._build_review_prompt(
        changed_files=["src/main.py"],
        diff_stat="1 file changed, 5 insertions(+), 2 deletions(-)",
        stack_guides=[],
    )
    assert "5 insertions(+), 2 deletions(-)" in prompt


def test_prompt_no_diff_stat_section_when_empty() -> None:
    module = _load_review_runner_module()
    prompt = module._build_review_prompt(
        changed_files=["src/main.py"],
        diff_stat="",
        stack_guides=[],
    )
    assert "DIFF STAT" not in prompt


# ---------------------------------------------------------------------------
# Result validation tests
# ---------------------------------------------------------------------------


def test_validate_valid_result() -> None:
    module = _load_review_runner_module()
    result = {
        "findings": [
            {
                "severity": "medium",
                "category": "GAP",
                "file_path": "src/main.py",
                "description": "Missing error handling.",
                "line_start": 42,
                "fix": "Add try/except block.",
            }
        ],
        "summary": "One medium finding about error handling.",
    }
    validated = module._validate_review_result(result)
    assert validated == result


def test_validate_empty_findings_ok() -> None:
    module = _load_review_runner_module()
    result = {"findings": [], "summary": "Clean review."}
    validated = module._validate_review_result(result)
    assert validated["findings"] == []


def test_validate_missing_findings_key_fails() -> None:
    module = _load_review_runner_module()
    import pytest

    with pytest.raises(RuntimeError, match="missing required 'findings' key"):
        module._validate_review_result({"summary": "oops"})


def test_validate_missing_summary_key_fails() -> None:
    module = _load_review_runner_module()
    import pytest

    with pytest.raises(RuntimeError, match="missing required 'summary' key"):
        module._validate_review_result({"findings": []})


def test_validate_invalid_severity_fails() -> None:
    module = _load_review_runner_module()
    import pytest

    with pytest.raises(RuntimeError, match="invalid severity 'critical'"):
        module._validate_review_result({
            "findings": [
                {"severity": "critical", "category": "GAP", "file_path": "f.py", "description": "bad"}
            ],
            "summary": "Review",
        })


def test_validate_invalid_category_fails() -> None:
    module = _load_review_runner_module()
    import pytest

    with pytest.raises(RuntimeError, match="invalid category 'BUG'"):
        module._validate_review_result({
            "findings": [
                {"severity": "high", "category": "BUG", "file_path": "f.py", "description": "bad"}
            ],
            "summary": "Review",
        })


def test_validate_empty_description_fails() -> None:
    module = _load_review_runner_module()
    import pytest

    with pytest.raises(RuntimeError, match="empty description"):
        module._validate_review_result({
            "findings": [
                {"severity": "low", "category": "DEAD_CODE", "file_path": "f.py", "description": "  "}
            ],
            "summary": "Review",
        })


# ---------------------------------------------------------------------------
# Finding ID generation tests
# ---------------------------------------------------------------------------


def test_finding_id_format() -> None:
    module = _load_review_runner_module()
    fid = module._generate_finding_id("backend-domain", 0, {"severity": "high"})
    assert fid == "BACKEN-H-01"


def test_finding_id_increments() -> None:
    module = _load_review_runner_module()
    fid = module._generate_finding_id("frontend", 4, {"severity": "low"})
    assert fid == "FRONTE-L-05"


def test_finding_id_no_lane() -> None:
    module = _load_review_runner_module()
    fid = module._generate_finding_id(None, 0, {"severity": "medium"})
    assert fid == "REVIEW-M-01"


# ---------------------------------------------------------------------------
# run_review dry-run shape
# ---------------------------------------------------------------------------


def test_run_review_dry_run_returns_full_shape(tmp_path: Path) -> None:
    module = _load_review_runner_module()
    import unittest.mock as mock

    with mock.patch.object(module, "_changed_files", return_value=["a.py"]), \
         mock.patch.object(module, "_diff_stat", return_value="1 file changed"), \
         mock.patch.object(module, "_detect_stack_guides", return_value=["rules/testing-python.md"]):
        result = module.run_review(
            worktree_path=tmp_path,
            lane_id="test-lane",
            dry_run=True,
        )

    assert result["dry_run"] is True
    assert result["findings"] == []
    assert result["converged"] is True
    assert "Dry-run" in result["summary"]
    assert "prompt" in result
    assert result["changed_files"] == ["a.py"]
    assert result["stack_guides"] == ["rules/testing-python.md"]


def test_run_review_record_findings_records_ids_and_line_refs(tmp_path: Path) -> None:
    module = _load_review_runner_module()
    import unittest.mock as mock

    mock_ahm = mock.MagicMock()
    mock_ahm.RuntimeConfig.for_workspace.return_value = mock.MagicMock()
    mock_ahm.configure_runtime = mock.MagicMock()
    mock_ahm.record_review_finding.return_value = json.dumps({"ok": True})

    raw_result = {
        "findings": [
            {
                "severity": "medium",
                "category": "GAP",
                "file_path": "src/main.py",
                "description": "Missing validation.",
                "line_start": 10,
                "line_end": 12,
                "fix": "Validate the payload before use.",
            }
        ],
        "summary": "One medium finding.",
    }

    with mock.patch.object(module, "_changed_files", return_value=["src/main.py"]), \
         mock.patch.object(module, "_diff_stat", return_value="1 file changed"), \
         mock.patch.object(module, "_detect_stack_guides", return_value=["branch-review-python.md"]), \
         mock.patch.object(module, "_codex_exec", return_value=raw_result), \
         mock.patch.dict(sys.modules, {"agent_handoff_mcp": mock_ahm}):
        result = module.run_review(
            worktree_path=tmp_path,
            lane_id="backend-domain",
            task_ref="daemon-1-review-runner",
            session="record-review-test",
            orchestrator_root=tmp_path,
            record_findings=True,
        )

    assert result["recorded_finding_ids"] == ["BACKEN-M-01"]
    kwargs = mock_ahm.record_review_finding.call_args.kwargs
    assert kwargs["task_ref"] == "daemon-1-review-runner"
    assert kwargs["details"]["line_start"] == 10
    assert kwargs["details"]["line_end"] == 12
    assert kwargs["details"]["fix"] == "Validate the payload before use."


def test_run_review_subagent_backend_uses_subagent_exec(tmp_path: Path) -> None:
    module = _load_review_runner_module()
    import unittest.mock as mock

    raw_result = {
        "findings": [],
        "summary": "Clean review.",
    }

    with (
        mock.patch.object(module, "_changed_files", return_value=["src/main.py"]),
        mock.patch.object(module, "_diff_stat", return_value="1 file changed"),
        mock.patch.object(module, "_detect_stack_guides", return_value=["branch-review-python.md"]),
        mock.patch.object(module, "_subagent_exec", return_value=raw_result) as mock_subagent_exec,
        mock.patch.object(module, "_codex_exec") as mock_codex_exec,
    ):
        result = module.run_review(
            worktree_path=tmp_path,
            lane_id="backend-domain",
            backend="codex-subagent",
        )

    assert result["summary"] == "Clean review."
    assert result["converged"] is True
    mock_subagent_exec.assert_called_once()
    assert mock_subagent_exec.call_args.args[0] == "codex-subagent"
    mock_codex_exec.assert_not_called()


def test_run_review_subagent_backend_passes_runtime_env(tmp_path: Path) -> None:
    module = _load_review_runner_module()
    import unittest.mock as mock

    raw_result = {
        "findings": [],
        "summary": "Clean review.",
    }

    with (
        mock.patch.object(module, "_changed_files", return_value=["src/main.py"]),
        mock.patch.object(module, "_diff_stat", return_value="1 file changed"),
        mock.patch.object(module, "_detect_stack_guides", return_value=["branch-review-python.md"]),
        mock.patch.object(module, "_subagent_exec", return_value=raw_result) as mock_subagent_exec,
    ):
        module.run_review(
            worktree_path=tmp_path,
            lane_id="backend-domain",
            task_ref="phase-5-retention-export-and-audit-controls",
            orchestrator_root=REPO_ROOT,
            backend="codex-subagent",
            reasoning_effort="xhigh",
        )

    assert mock_subagent_exec.call_args.args[0] == "codex-subagent"
    env = mock_subagent_exec.call_args.kwargs["env"]
    assert env["TMPDIR"].endswith("/.task-state/tmp/backend-domain")
    assert env["PYENV_VERSION"] == "description-service"
    assert env["CODEX_REASONING_EFFORT"] == "xhigh"


def test_subagent_exec_falls_back_when_bridge_does_not_accept_env(tmp_path: Path) -> None:
    module = _load_review_runner_module()
    import unittest.mock as mock

    def legacy_runner(*, prompt: str, schema: dict[str, Any], cwd: str) -> dict[str, Any]:
        return {"findings": [], "summary": "Clean review."}

    fake_runner = mock.Mock(side_effect=legacy_runner)

    with mock.patch.object(module, "resolve_bridge", return_value=fake_runner):
        result = module._subagent_exec("codex-subagent", "Prompt", tmp_path, env={"TMPDIR": "/tmp/lane"})

    assert result == {"findings": [], "summary": "Clean review."}
    assert fake_runner.call_count == 2
    assert "env" not in fake_runner.call_args.kwargs
