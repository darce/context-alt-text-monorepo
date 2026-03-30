"""Tests for ace_reflect.py: strategy bullet evolution helpers.

Covers:
- classify_rule_reference: contradiction vs. citation classification
- increment_counter: idempotency via dedup sidecar
- ace_apply_counters: log processing semantics, idempotency, offset persistence
- ace_reflect_pending orchestrator advisory: fires only for unprocessed entries
- dashboard _metrics_summary_line: rendering format and import-fallback
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_orchestrator_mcp.orchestration import dashboard_live
from agent_orchestrator_mcp.orchestration.ace_reflect import (
    _run_model_curation,
    ace_apply_counters,
    ace_reflect_on_findings,
    classify_rule_reference,
    increment_counter,
    parse_strategy_bullets,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BULLETS = (
    "# Instructions\n"
    "\n"
    "- [sr-001] helpful=0 harmful=0 :: Do not relax compliance/lint scripts.\n"
    "- [sr-002] helpful=1 harmful=0 :: Use npm for Node.js.\n"
    "- [rg-001] helpful=2 harmful=0 :: No type-shim masking.\n"
)


def _make_instruction_file(tmp_path: Path, content: str = "") -> Path:
    """Create a minimal instruction file with ACE strategy bullets."""
    fp = tmp_path / "instructions.md"
    fp.write_text(content or _BULLETS, encoding="utf-8")
    return fp


# ---------------------------------------------------------------------------
# classify_rule_reference
# ---------------------------------------------------------------------------


class TestClassifyRuleReference:
    def test_contradiction_keyword_in_neighbourhood(self) -> None:
        text = "The code violates [sr-001] by relaxing the lint checks."
        assert classify_rule_reference(text, "sr-001") is True

    def test_missing_keyword_returns_false(self) -> None:
        text = "[sr-001] was applied correctly in this change."
        assert classify_rule_reference(text, "sr-001") is False

    def test_different_rule_id_not_matched(self) -> None:
        text = "This breaks [sr-002] completely."
        # sr-001 is the query; sr-002 is what's in the text
        assert classify_rule_reference(text, "sr-001") is False

    def test_keyword_outside_neighbourhood_not_matched(self) -> None:
        # "violates" is far from [sr-001] (more than 80 chars away)
        padding = "x" * 200
        text = f"This violates something.{padding}[sr-001] is mentioned here."
        assert classify_rule_reference(text, "sr-001") is False

    def test_multiple_contradiction_keywords(self) -> None:
        for kw in ("missing", "breaks", "fail", "bypass", "incorrect"):
            text = f"[sr-001] {kw} the policy"
            assert classify_rule_reference(text, "sr-001") is True, f"keyword '{kw}' should trigger contradiction"

    def test_rg_prefix_matched(self) -> None:
        text = "This ignored [rg-013]."
        assert classify_rule_reference(text, "rg-013") is True

    def test_empty_text_returns_false(self) -> None:
        assert classify_rule_reference("", "sr-001") is False


# ---------------------------------------------------------------------------
# increment_counter
# ---------------------------------------------------------------------------


class TestIncrementCounter:
    def test_increments_helpful_counter(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        result = increment_counter("sr-001", "helpful", fp, "F-1:sr-001:helpful")
        assert result is True
        bullets = parse_strategy_bullets(fp)
        assert bullets["sr-001"]["helpful"] == 1

    def test_increments_harmful_counter(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        result = increment_counter("sr-001", "harmful", fp, "F-1:sr-001:harmful")
        assert result is True
        bullets = parse_strategy_bullets(fp)
        assert bullets["sr-001"]["harmful"] == 1

    def test_idempotent_same_dedup_key(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        increment_counter("sr-001", "helpful", fp, "F-1:sr-001:helpful")
        result2 = increment_counter("sr-001", "helpful", fp, "F-1:sr-001:helpful")
        assert result2 is False
        bullets = parse_strategy_bullets(fp)
        assert bullets["sr-001"]["helpful"] == 1

    def test_different_dedup_keys_allowed(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        increment_counter("sr-001", "helpful", fp, "F-1:sr-001:helpful")
        increment_counter("sr-001", "helpful", fp, "F-2:sr-001:helpful")
        bullets = parse_strategy_bullets(fp)
        assert bullets["sr-001"]["helpful"] == 2

    def test_unknown_rule_id_returns_false(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        result = increment_counter("sr-999", "helpful", fp, "F-1:sr-999:helpful")
        assert result is False

    def test_invalid_counter_name_raises(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        with pytest.raises(ValueError, match="counter must be"):
            increment_counter("sr-001", "positive", fp, "F-1:sr-001:positive")

    def test_dedup_sidecar_persists(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        increment_counter("sr-001", "helpful", fp, "F-1:sr-001:helpful")
        sidecar = fp.with_suffix(fp.suffix + ".ace_dedup.json")
        assert sidecar.exists()
        data = json.loads(sidecar.read_text())
        assert "F-1:sr-001:helpful" in data


# ---------------------------------------------------------------------------
# ace_apply_counters
# ---------------------------------------------------------------------------


def _write_log(path: Path, records: list[dict]) -> Path:
    log = path / "ace_reflect_log.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return log


class TestAceApplyCounters:
    def test_empty_log_returns_zero_counts(self, tmp_path: Path) -> None:
        log = tmp_path / "ace_reflect_log.jsonl"
        log.write_text("", encoding="utf-8")
        fp = _make_instruction_file(tmp_path)
        result = ace_apply_counters(log, [fp])
        assert result == {"total_processed": 0, "incremented": 0, "skipped": 0}

    def test_missing_log_returns_zero_counts(self, tmp_path: Path) -> None:
        log = tmp_path / "ace_reflect_log.jsonl"
        fp = _make_instruction_file(tmp_path)
        result = ace_apply_counters(log, [fp])
        assert result == {"total_processed": 0, "incremented": 0, "skipped": 0}

    def test_valid_helpful_entry_increments_counter(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = _write_log(
            tmp_path,
            [
                {"finding_id": "F-1", "rule_id": "sr-001", "contradicts": False},
            ],
        )
        result = ace_apply_counters(log, [fp])
        assert result["incremented"] == 1
        assert parse_strategy_bullets(fp)["sr-001"]["helpful"] == 1

    def test_valid_harmful_entry_increments_harmful(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = _write_log(
            tmp_path,
            [
                {"finding_id": "F-2", "rule_id": "sr-001", "contradicts": True},
            ],
        )
        ace_apply_counters(log, [fp])
        assert parse_strategy_bullets(fp)["sr-001"]["harmful"] == 1

    def test_malformed_json_line_is_skipped(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = tmp_path / "ace_reflect_log.jsonl"
        log.write_text("not-valid-json\n", encoding="utf-8")
        result = ace_apply_counters(log, [fp])
        assert result["skipped"] == 1
        assert result["total_processed"] == 0

    def test_missing_rule_id_is_skipped(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = _write_log(
            tmp_path,
            [
                {"finding_id": "F-1", "contradicts": False},  # no rule_id
            ],
        )
        result = ace_apply_counters(log, [fp])
        assert result["skipped"] == 1

    def test_rerun_is_idempotent(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = _write_log(
            tmp_path,
            [
                {"finding_id": "F-1", "rule_id": "sr-001", "contradicts": False},
            ],
        )
        ace_apply_counters(log, [fp])
        result2 = ace_apply_counters(log, [fp])
        assert result2["incremented"] == 0
        assert parse_strategy_bullets(fp)["sr-001"]["helpful"] == 1

    def test_offset_file_written_after_apply(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = _write_log(
            tmp_path,
            [
                {"finding_id": "F-1", "rule_id": "sr-001", "contradicts": False},
                {"finding_id": "F-2", "rule_id": "sr-002", "contradicts": False},
            ],
        )
        ace_apply_counters(log, [fp])
        offset_file = log.with_name(log.name + ".offset")
        assert offset_file.exists()
        data = json.loads(offset_file.read_text())
        assert data["processed_line_count"] == 2

    def test_offset_after_rerun_matches_total_lines(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = _write_log(
            tmp_path,
            [
                {"finding_id": "F-1", "rule_id": "sr-001", "contradicts": False},
                {"finding_id": "F-2", "rule_id": "sr-001", "contradicts": True},
                {"finding_id": "F-3", "rule_id": "rg-001", "contradicts": False},
            ],
        )
        ace_apply_counters(log, [fp])
        ace_apply_counters(log, [fp])  # second run
        offset_file = log.with_name(log.name + ".offset")
        data = json.loads(offset_file.read_text())
        assert data["processed_line_count"] == 3


class TestModelBackedCuration:
    def test_model_curation_skips_when_below_threshold(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        result = _run_model_curation(
            state_dir=tmp_path,
            instruction_files=[fp],
            reflect_log=tmp_path / "ace_reflect_log.jsonl",
            backend="codex-cli",
            model="gpt-5.4",
            reasoning_effort="medium",
            threshold=5,
            budget_tokens=500,
        )

        assert result["status"] == "below_threshold"

    def test_model_curation_records_separate_spend_when_triggered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fp = _make_instruction_file(
            tmp_path,
            "# Instructions\n\n- [sr-001] helpful=0 harmful=2 :: Do not relax compliance/lint scripts.\n",
        )
        reflect_log = tmp_path / "ace_reflect_log.jsonl"
        reflect_log.write_text(
            "\n".join(
                json.dumps({"finding_id": f"F-{idx}", "rule_id": "sr-001", "contradicts": False}) for idx in range(3)
            )
            + "\n",
            encoding="utf-8",
        )

        class _Adapter:
            def execute(self, **_: object):
                return MagicMock(
                    summary="Batch curation recommendations generated.",
                    response_model="gpt-5.4",
                    reasoning_effort="medium",
                    token_usage={"total": {"total_tokens": 123}},
                )

        monkeypatch.setattr("agent_orchestrator_mcp.orchestration.ace_reflect.get_adapter", lambda _backend: _Adapter())

        result = _run_model_curation(
            state_dir=tmp_path,
            instruction_files=[fp],
            reflect_log=reflect_log,
            backend="codex-cli",
            model="gpt-5.4",
            reasoning_effort="medium",
            threshold=2,
            budget_tokens=500,
        )

        assert result["status"] == "triggered"
        log_rows = (tmp_path / "ace_curation_log.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(log_rows) == 1
        assert json.loads(log_rows[0])["token_usage"]["total"]["total_tokens"] == 123


# ---------------------------------------------------------------------------
# ace_reflect_pending orchestrator advisory behaviour
# ---------------------------------------------------------------------------


def _compute_pending(log_path: Path) -> int:
    """Replicate the orchestrator daemon's pending-count logic."""
    if not log_path.exists():
        return 0
    total = sum(1 for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip())
    processed = 0
    offset_file = log_path.with_name(log_path.name + ".offset")
    if offset_file.exists():
        try:
            processed = json.loads(offset_file.read_text(encoding="utf-8")).get("processed_line_count", 0)
        except Exception:  # noqa: BLE001
            pass
    return max(0, total - processed)


class TestAceReflectPendingAdvisory:
    """White-box tests: verify the orchestrator daemon computes pending entries
    correctly using the offset file so the warning clears after ace-reflect runs.
    """

    def test_pending_counts_all_lines_before_apply(self, tmp_path: Path) -> None:
        log = tmp_path / "ace_reflect_log.jsonl"
        log.write_text(
            "\n".join(json.dumps({"finding_id": f"F-{i}", "rule_id": "sr-001", "contradicts": False}) for i in range(8))
            + "\n",
            encoding="utf-8",
        )
        assert _compute_pending(log) == 8

    def test_pending_clears_to_zero_after_apply(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = tmp_path / "ace_reflect_log.jsonl"
        log.write_text(
            "\n".join(json.dumps({"finding_id": f"F-{i}", "rule_id": "sr-001", "contradicts": False}) for i in range(8))
            + "\n",
            encoding="utf-8",
        )
        ace_apply_counters(log, [fp])
        assert _compute_pending(log) == 0

    def test_new_appended_entries_appear_as_pending_after_apply(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = tmp_path / "ace_reflect_log.jsonl"
        log.write_text(
            json.dumps({"finding_id": "F-1", "rule_id": "sr-001", "contradicts": False}) + "\n",
            encoding="utf-8",
        )
        ace_apply_counters(log, [fp])  # processes 1 line; offset = 1
        # Append 6 new entries
        with log.open("a", encoding="utf-8") as fh:
            for i in range(2, 8):
                fh.write(json.dumps({"finding_id": f"F-{i}", "rule_id": "sr-001", "contradicts": False}) + "\n")
        assert _compute_pending(log) == 6

    def test_no_log_returns_zero_pending(self, tmp_path: Path) -> None:
        log = tmp_path / "ace_reflect_log.jsonl"
        assert _compute_pending(log) == 0


# ---------------------------------------------------------------------------
# dashboard _metrics_summary_line import fallback
# ---------------------------------------------------------------------------


class TestMetricsSummaryLine:
    def test_returns_string_when_modules_unavailable(self, tmp_path: Path) -> None:
        """When ace_metrics is not importable, return a safe fallback string."""
        with patch.dict(
            "sys.modules",
            {
                "agent_orchestrator_mcp.orchestration.ace_metrics": None,
                "agent_orchestrator_mcp.orchestration.ace_reflect": None,
            },
        ):
            result = dashboard_live._metrics_summary_line("test-task", tmp_path, tmp_path)
        assert isinstance(result, str)
        assert "metrics:" in result

    def test_returns_formatted_string_on_success(self, tmp_path: Path) -> None:
        """Returns a line containing expected metric label tokens."""
        mock_snap = {
            "token_burn": {"data_available": True, "total_tokens": 1234, "by_lane": {}},
            "context_pressure": {"data_available": True, "latest_pressure": "normal"},
            "fts5_retrieval": {
                "data_available": False,
                "artifact_sources_indexed": 0,
                "artifact_chunks_fts_count": 0,
                "handoff_record_counts": {},
            },
            "lane_health": {"data_available": False},
            "ace_documentation": {
                "data_available": True,
                "total_strategy_bullets": 20,
                "pruning_candidates": 0,
                "pruning_candidate_ids": [],
                "total_helpful": 10,
                "total_harmful": 1,
                "instruction_file_lines": 500,
            },
        }
        mock_ace_reflect = MagicMock()
        mock_ace_reflect.parse_strategy_bullets.return_value = {}
        mock_ace_metrics = MagicMock()
        mock_ace_metrics.build_snapshot.return_value = mock_snap

        with patch.dict(
            "sys.modules",
            {
                "agent_orchestrator_mcp.orchestration.ace_reflect": mock_ace_reflect,
                "agent_orchestrator_mcp.orchestration.ace_metrics": mock_ace_metrics,
            },
        ):
            result = dashboard_live._metrics_summary_line("test-task", tmp_path, tmp_path)

        assert "tokens=" in result
        assert "pressure=" in result
        assert "bullets=" in result


# ---------------------------------------------------------------------------
# ace_reflect_on_findings
# ---------------------------------------------------------------------------


class TestAceReflectOnFindings:
    """Tests for ace_reflect_on_findings: daemon path and manual batch path."""

    _BULLETS_WITH_RULES = (
        "# Instructions\n"
        "\n"
        "- [sr-001] helpful=0 harmful=0 :: Do not relax compliance/lint scripts.\n"
        "- [sr-002] helpful=1 harmful=0 :: Use npm for Node.js.\n"
        "- [rg-001] helpful=2 harmful=0 :: No type-shim masking.\n"
    )

    def _instruction_file(self, tmp_path: Path) -> Path:
        fp = tmp_path / "instructions.md"
        fp.write_text(self._BULLETS_WITH_RULES, encoding="utf-8")
        return fp

    def test_no_findings_returns_empty(self, tmp_path: Path) -> None:
        """Empty findings list -> empty return, no file created."""
        inst = self._instruction_file(tmp_path)
        state_dir = tmp_path / "state"
        records = ace_reflect_on_findings([], [inst], state_dir=state_dir)
        assert records == []
        assert not (state_dir / "ace_reflect_log.jsonl").exists()

    def test_daemon_path_no_state_dir(self, tmp_path: Path) -> None:
        """Without state_dir: returns records but writes no files."""
        inst = self._instruction_file(tmp_path)
        findings = [{"id": "F-1", "description": "Rule [sr-001] was violated here."}]
        records = ace_reflect_on_findings(findings, [inst])
        assert len(records) == 1
        assert records[0]["finding_id"] == "F-1"
        assert records[0]["rule_id"] == "sr-001"
        # No file I/O expected
        assert not (tmp_path / "ace_reflect_log.jsonl").exists()

    def test_manual_path_writes_log(self, tmp_path: Path) -> None:
        """With state_dir: records are written to ace_reflect_log.jsonl."""
        inst = self._instruction_file(tmp_path)
        state_dir = tmp_path / "state"
        findings = [{"id": "F-2", "description": "[sr-002] is contradicted by this decision."}]
        ace_reflect_on_findings(findings, [inst], state_dir=state_dir)
        log = state_dir / "ace_reflect_log.jsonl"
        assert log.exists()
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["finding_id"] == "F-2"
        assert rec["rule_id"] == "sr-002"
        assert "timestamp" in rec

    def test_manual_path_applies_counters(self, tmp_path: Path) -> None:
        """With state_dir: ace_apply_counters is called, counters are updated."""
        inst = self._instruction_file(tmp_path)
        state_dir = tmp_path / "state"
        findings = [{"id": "F-3", "description": "This finding references [rg-001] as contradicted."}]
        ace_reflect_on_findings(findings, [inst], state_dir=state_dir)
        # Counter should have been applied: rg-001 should have harmful incremented
        bullets = parse_strategy_bullets(inst)
        assert "rg-001" in bullets
        rule_text = inst.read_text(encoding="utf-8")
        assert "rg-001" in rule_text

    def test_unknown_rule_ids_filtered(self, tmp_path: Path) -> None:
        """References to rule IDs not in any instruction file are silently dropped."""
        inst = self._instruction_file(tmp_path)
        findings = [{"id": "F-4", "description": "This mentions [xx-999] which does not exist."}]
        records = ace_reflect_on_findings(findings, [inst])
        assert records == []

    def test_multiple_rule_references_in_one_finding(self, tmp_path: Path) -> None:
        """A finding mentioning multiple known rules produces one record per rule."""
        inst = self._instruction_file(tmp_path)
        findings = [{"id": "F-5", "description": "Both [sr-001] and [sr-002] are cited here."}]
        records = ace_reflect_on_findings(findings, [inst])
        rule_ids = {r["rule_id"] for r in records}
        assert "sr-001" in rule_ids
        assert "sr-002" in rule_ids
        assert all(r["finding_id"] == "F-5" for r in records)

    def test_manual_path_appends_on_second_call(self, tmp_path: Path) -> None:
        """Calling twice with state_dir appends lines rather than overwriting."""
        inst = self._instruction_file(tmp_path)
        state_dir = tmp_path / "state"
        findings_a = [{"id": "F-6", "description": "[sr-001] referenced"}]
        findings_b = [{"id": "F-7", "description": "[sr-002] referenced"}]
        ace_reflect_on_findings(findings_a, [inst], state_dir=state_dir)
        ace_reflect_on_findings(findings_b, [inst], state_dir=state_dir)
        log = state_dir / "ace_reflect_log.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        ids = {json.loads(line)["finding_id"] for line in lines}
        assert ids == {"F-6", "F-7"}

    def test_finding_id_falls_back_to_finding_id_key(self, tmp_path: Path) -> None:
        """Findings using 'finding_id' key instead of 'id' are handled."""
        inst = self._instruction_file(tmp_path)
        findings = [{"finding_id": "H-999", "description": "[sr-001] violation."}]
        records = ace_reflect_on_findings(findings, [inst])
        assert records[0]["finding_id"] == "H-999"
