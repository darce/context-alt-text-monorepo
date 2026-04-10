"""Tests for scripts/ace/ace_reflect.py: strategy bullet evolution helpers.

Run with: python -m pytest scripts/ace/test_ace_reflect.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add scripts/ace to path so the standalone module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ace_reflect import (  # noqa: E402
    ace_apply_counters,
    ace_reflect_on_findings,
    classify_rule_reference,
    increment_counter,
    parse_strategy_bullets,
)

_BULLETS = (
    "# Instructions\n"
    "\n"
    "- [sr-001] helpful=0 harmful=0 :: Do not relax compliance/lint scripts.\n"
    "- [sr-002] helpful=1 harmful=0 :: Use npm for Node.js.\n"
    "- [rg-001] helpful=2 harmful=0 :: No type-shim masking.\n"
)


def _make_instruction_file(tmp_path: Path, content: str = "") -> Path:
    fp = tmp_path / "instructions.md"
    fp.write_text(content or _BULLETS, encoding="utf-8")
    return fp


class TestClassifyRuleReference:
    def test_contradiction_keyword_in_neighbourhood(self) -> None:
        text = "The code violates [sr-001] by relaxing the lint checks."
        assert classify_rule_reference(text, "sr-001") is True

    def test_missing_keyword_returns_false(self) -> None:
        text = "[sr-001] was applied correctly in this change."
        assert classify_rule_reference(text, "sr-001") is False

    def test_different_rule_id_not_matched(self) -> None:
        text = "This breaks [sr-002] completely."
        assert classify_rule_reference(text, "sr-001") is False

    def test_keyword_outside_neighbourhood_not_matched(self) -> None:
        padding = "x" * 200
        text = f"This violates something.{padding}[sr-001] is mentioned here."
        assert classify_rule_reference(text, "sr-001") is False

    def test_multiple_contradiction_keywords(self) -> None:
        for kw in ("missing", "breaks", "fail", "bypass", "incorrect"):
            text = f"[sr-001] {kw} the policy"
            assert classify_rule_reference(text, "sr-001") is True

    def test_rg_prefix_matched(self) -> None:
        text = "This ignored [rg-013]."
        assert classify_rule_reference(text, "rg-013") is True

    def test_empty_text_returns_false(self) -> None:
        assert classify_rule_reference("", "sr-001") is False


class TestIncrementCounter:
    def test_increments_helpful_counter(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        result = increment_counter("sr-001", "helpful", fp, "F-1:sr-001:helpful")
        assert result is True
        assert parse_strategy_bullets(fp)["sr-001"]["helpful"] == 1

    def test_increments_harmful_counter(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        result = increment_counter("sr-001", "harmful", fp, "F-1:sr-001:harmful")
        assert result is True
        assert parse_strategy_bullets(fp)["sr-001"]["harmful"] == 1

    def test_idempotent_same_dedup_key(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        increment_counter("sr-001", "helpful", fp, "F-1:sr-001:helpful")
        result2 = increment_counter("sr-001", "helpful", fp, "F-1:sr-001:helpful")
        assert result2 is False
        assert parse_strategy_bullets(fp)["sr-001"]["helpful"] == 1

    def test_different_dedup_keys_allowed(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        increment_counter("sr-001", "helpful", fp, "F-1:sr-001:helpful")
        increment_counter("sr-001", "helpful", fp, "F-2:sr-001:helpful")
        assert parse_strategy_bullets(fp)["sr-001"]["helpful"] == 2

    def test_unknown_rule_id_returns_false(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        assert increment_counter("sr-999", "helpful", fp, "F-1:sr-999:helpful") is False

    def test_invalid_counter_name_raises(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        with pytest.raises(ValueError, match="counter must be"):
            increment_counter("sr-001", "positive", fp, "F-1:sr-001:positive")

    def test_dedup_sidecar_persists(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        increment_counter("sr-001", "helpful", fp, "F-1:sr-001:helpful")
        sidecar = fp.with_suffix(fp.suffix + ".ace_dedup.json")
        assert sidecar.exists()
        assert "F-1:sr-001:helpful" in json.loads(sidecar.read_text())


def _write_log(path: Path, records: list[dict]) -> Path:
    log = path / "ace_reflect_log.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return log


class TestAceApplyCounters:
    def test_empty_log_returns_zero_counts(self, tmp_path: Path) -> None:
        log = tmp_path / "ace_reflect_log.jsonl"
        log.write_text("", encoding="utf-8")
        fp = _make_instruction_file(tmp_path)
        assert ace_apply_counters(log, [fp]) == {"total_processed": 0, "incremented": 0, "skipped": 0}

    def test_missing_log_returns_zero_counts(self, tmp_path: Path) -> None:
        log = tmp_path / "ace_reflect_log.jsonl"
        fp = _make_instruction_file(tmp_path)
        assert ace_apply_counters(log, [fp]) == {"total_processed": 0, "incremented": 0, "skipped": 0}

    def test_valid_helpful_entry_increments_counter(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = _write_log(tmp_path, [{"finding_id": "F-1", "rule_id": "sr-001", "contradicts": False}])
        result = ace_apply_counters(log, [fp])
        assert result["incremented"] == 1
        assert parse_strategy_bullets(fp)["sr-001"]["helpful"] == 1

    def test_valid_harmful_entry_increments_harmful(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = _write_log(tmp_path, [{"finding_id": "F-2", "rule_id": "sr-001", "contradicts": True}])
        ace_apply_counters(log, [fp])
        assert parse_strategy_bullets(fp)["sr-001"]["harmful"] == 1

    def test_malformed_json_line_is_skipped(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = tmp_path / "ace_reflect_log.jsonl"
        log.write_text("not-valid-json\n", encoding="utf-8")
        assert ace_apply_counters(log, [fp])["skipped"] == 1

    def test_rerun_is_idempotent(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = _write_log(tmp_path, [{"finding_id": "F-1", "rule_id": "sr-001", "contradicts": False}])
        ace_apply_counters(log, [fp])
        result2 = ace_apply_counters(log, [fp])
        assert result2["incremented"] == 0
        assert parse_strategy_bullets(fp)["sr-001"]["helpful"] == 1

    def test_offset_file_written_after_apply(self, tmp_path: Path) -> None:
        fp = _make_instruction_file(tmp_path)
        log = _write_log(tmp_path, [
            {"finding_id": "F-1", "rule_id": "sr-001", "contradicts": False},
            {"finding_id": "F-2", "rule_id": "sr-002", "contradicts": False},
        ])
        ace_apply_counters(log, [fp])
        offset_file = log.with_name(log.name + ".offset")
        assert json.loads(offset_file.read_text())["processed_line_count"] == 2


class TestAceReflectOnFindings:
    _BULLETS_WITH_RULES = (
        "# Instructions\n\n"
        "- [sr-001] helpful=0 harmful=0 :: Do not relax compliance/lint scripts.\n"
        "- [sr-002] helpful=1 harmful=0 :: Use npm for Node.js.\n"
        "- [rg-001] helpful=2 harmful=0 :: No type-shim masking.\n"
    )

    def _instruction_file(self, tmp_path: Path) -> Path:
        fp = tmp_path / "instructions.md"
        fp.write_text(self._BULLETS_WITH_RULES, encoding="utf-8")
        return fp

    def test_no_findings_returns_empty(self, tmp_path: Path) -> None:
        inst = self._instruction_file(tmp_path)
        assert ace_reflect_on_findings([], [inst], state_dir=tmp_path / "state") == []

    def test_returns_records_without_state_dir(self, tmp_path: Path) -> None:
        inst = self._instruction_file(tmp_path)
        findings = [{"id": "F-1", "description": "Rule [sr-001] was violated here."}]
        records = ace_reflect_on_findings(findings, [inst])
        assert len(records) == 1
        assert records[0]["rule_id"] == "sr-001"

    def test_writes_log_with_state_dir(self, tmp_path: Path) -> None:
        inst = self._instruction_file(tmp_path)
        state_dir = tmp_path / "state"
        findings = [{"id": "F-2", "description": "[sr-002] is contradicted."}]
        ace_reflect_on_findings(findings, [inst], state_dir=state_dir)
        log = state_dir / "ace_reflect_log.jsonl"
        assert log.exists()
        rec = json.loads(log.read_text().splitlines()[0])
        assert rec["finding_id"] == "F-2"

    def test_unknown_rule_ids_filtered(self, tmp_path: Path) -> None:
        inst = self._instruction_file(tmp_path)
        findings = [{"id": "F-4", "description": "This mentions [xx-999] which does not exist."}]
        assert ace_reflect_on_findings(findings, [inst]) == []

    def test_multiple_rule_references(self, tmp_path: Path) -> None:
        inst = self._instruction_file(tmp_path)
        findings = [{"id": "F-5", "description": "Both [sr-001] and [sr-002] cited."}]
        records = ace_reflect_on_findings(findings, [inst])
        assert {r["rule_id"] for r in records} == {"sr-001", "sr-002"}
