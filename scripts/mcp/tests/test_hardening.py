"""Tests for orchestration-hardening features across mcp scripts."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = REPO_ROOT / "scripts" / "mcp"


def _load(name: str):
    path = SCRIPT_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    # Ensure sub-deps can be found
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# _env.py: EFFORT_LADDER and _escalate_effort
# ---------------------------------------------------------------------------


class TestEscalateEffort:
    def _env(self):
        return _load("_env")

    def test_ladder_constant_is_tuple(self) -> None:
        env = self._env()
        assert env.EFFORT_LADDER == ("low", "medium", "high", "xhigh")

    def test_escalate_low_to_medium(self) -> None:
        env = self._env()
        assert env._escalate_effort("low") == "medium"

    def test_escalate_medium_to_high(self) -> None:
        env = self._env()
        assert env._escalate_effort("medium") == "high"

    def test_escalate_high_to_xhigh(self) -> None:
        env = self._env()
        assert env._escalate_effort("high") == "xhigh"

    def test_escalate_xhigh_returns_none(self) -> None:
        env = self._env()
        assert env._escalate_effort("xhigh") is None

    def test_escalate_unknown_returns_none(self) -> None:
        env = self._env()
        assert env._escalate_effort("turbo") is None

    def test_escalate_empty_returns_none(self) -> None:
        env = self._env()
        assert env._escalate_effort("") is None

    def test_resolve_auto_escalates_when_previous_exhausted(self, tmp_path: Path) -> None:
        """With previous_run_exhausted=True an auto score of 0 should produce
        one level higher than the baseline selection."""
        env = self._env()
        # docs-only lane should auto-select "low"; with exhaustion it escalates to "medium"
        effort, reasons = env.resolve_auto_reasoning_effort(
            orchestrator_root=tmp_path,
            task_ref="test-task",
            lane_id="docs-lane",
            requested="auto",
            cycle=0,
            prompt_override=None,
            previous_run_exhausted=True,
        )
        # The manifest won't exist in tmp_path so we fall through to scoring
        assert effort in ("medium", "high", "xhigh"), effort
        assert any("escalated" in r for r in reasons)

    def test_resolve_auto_no_escalation_without_flag(self, tmp_path: Path) -> None:
        env = self._env()
        effort, reasons = env.resolve_auto_reasoning_effort(
            orchestrator_root=tmp_path,
            task_ref="test-task",
            lane_id="docs-lane",
            requested="auto",
            cycle=0,
            prompt_override=None,
            previous_run_exhausted=False,
        )
        assert not any("escalated" in r for r in reasons)


# ---------------------------------------------------------------------------
# lane_exec.py: _matches_any_owned_path
# ---------------------------------------------------------------------------


class TestMatchesAnyOwnedPath:
    def _mod(self):
        return _load("lane_exec")

    def test_direct_prefix_match(self) -> None:
        mod = self._mod()
        assert mod._matches_any_owned_path("apps/foo/bar.py", ["apps/foo/**"]) is True

    def test_no_match_outside_paths(self) -> None:
        mod = self._mod()
        assert mod._matches_any_owned_path("apps/bar/baz.py", ["apps/foo/**"]) is False

    def test_exact_prefix_match(self) -> None:
        mod = self._mod()
        assert mod._matches_any_owned_path("src/components/Button.tsx", ["src/components/**"]) is True

    def test_empty_owned_paths_returns_false(self) -> None:
        mod = self._mod()
        assert mod._matches_any_owned_path("anywhere.py", []) is False

    def test_fnmatch_glob(self) -> None:
        mod = self._mod()
        assert mod._matches_any_owned_path("scripts/mcp/foo.py", ["scripts/mcp/*.py"]) is True

    def test_no_leading_slash(self) -> None:
        mod = self._mod()
        assert mod._matches_any_owned_path("/apps/foo/f.py", ["apps/foo/**"]) is True

    def test_sibling_prefix_not_matched(self) -> None:
        """apps/foobar/baz.py must NOT match pattern apps/foo/** (M-PREFIX-01)."""
        mod = self._mod()
        assert mod._matches_any_owned_path("apps/foobar/baz.py", ["apps/foo/**"]) is False


# ---------------------------------------------------------------------------
# lane_exec.py: _check_scope_violations (with a fake git repo)
# ---------------------------------------------------------------------------


class TestCheckScopeViolations:
    def _mod(self):
        return _load("lane_exec")

    def test_no_owned_paths_returns_empty(self, tmp_path: Path) -> None:
        mod = self._mod()
        result = mod._check_scope_violations(tmp_path, owned_paths=[])
        assert result == []

    def test_scope_violation_detected(self, tmp_path: Path) -> None:
        """Untracked file outside owned_paths should appear in violations."""
        import subprocess
        # Init a bare git repo
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        # Create an initial commit
        readme = tmp_path / "README.md"
        readme.write_text("init")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        # Leave a file outside owned_paths as untracked (not committed)
        outside = tmp_path / "outside" / "file.py"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("# outside")

        mod = self._mod()
        violations = mod._check_scope_violations(
            tmp_path, owned_paths=["apps/**"]
        )
        assert any("outside" in v for v in violations), f"expected violation, got {violations}"

    def test_no_violation_within_owned_paths(self, tmp_path: Path) -> None:
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        readme = tmp_path / "README.md"
        readme.write_text("init")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        # Leave a file within owned_paths as untracked
        inside = tmp_path / "apps" / "foo" / "bar.py"
        inside.parent.mkdir(parents=True, exist_ok=True)
        inside.write_text("# inside")
        mod = self._mod()
        violations = mod._check_scope_violations(
            tmp_path, owned_paths=["apps/**"]
        )
        assert violations == [], f"unexpected violations: {violations}"

    def test_mixed_scope_violations(self, tmp_path: Path) -> None:
        """Files both inside and outside owned_paths: only outside ones returned."""
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        readme = tmp_path / "README.md"
        readme.write_text("init")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path), check=True, capture_output=True,
        )
        # Inside owned path
        inside = tmp_path / "apps" / "service" / "main.py"
        inside.parent.mkdir(parents=True, exist_ok=True)
        inside.write_text("# inside")
        # Outside owned path
        outside = tmp_path / "scripts" / "deploy.sh"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("#!/bin/sh")

        mod = self._mod()
        violations = mod._check_scope_violations(
            tmp_path, owned_paths=["apps/**"]
        )
        assert any("deploy.sh" in v for v in violations), f"expected deploy.sh in violations, got {violations}"
        assert not any("main.py" in v for v in violations), f"main.py should not be a violation, got {violations}"





class TestExhaustionStreak:
    def _mod(self):
        return _load("worker_daemon")

    def test_first_call_returns_one(self, tmp_path: Path) -> None:
        mod = self._mod()
        count = mod._update_exhaustion_streak(tmp_path, "test-lane", "run-1")
        assert count == 1

    def test_increments_within_same_run(self, tmp_path: Path) -> None:
        mod = self._mod()
        mod._update_exhaustion_streak(tmp_path, "test-lane", "run-1")
        count = mod._update_exhaustion_streak(tmp_path, "test-lane", "run-1")
        assert count == 2

    def test_resets_on_new_run_id(self, tmp_path: Path) -> None:
        mod = self._mod()
        mod._update_exhaustion_streak(tmp_path, "test-lane", "run-1")
        mod._update_exhaustion_streak(tmp_path, "test-lane", "run-1")
        # New run ID: streak should restart from 1
        count = mod._update_exhaustion_streak(tmp_path, "test-lane", "run-2")
        assert count == 1

    def test_reset_writes_zero(self, tmp_path: Path) -> None:
        mod = self._mod()
        mod._update_exhaustion_streak(tmp_path, "test-lane", "run-1")
        mod._reset_exhaustion_streak(tmp_path, "test-lane", "run-1")
        # After reset, update should return 1 (fresh start)
        count = mod._update_exhaustion_streak(tmp_path, "test-lane", "run-1")
        # Reset sets count=0; update increments to 1
        assert count == 1


# ---------------------------------------------------------------------------
# worker_daemon.py: _check_token_burn
# ---------------------------------------------------------------------------


class TestCheckTokenBurn:
    def _mod(self):
        return _load("worker_daemon")

    def _write_status(self, state_dir: Path, lane_id: str, total_tokens: int) -> None:
        path = state_dir / f"worker-{lane_id}.status.json"
        state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "observability": {
                "history": [
                    {"token_usage_totals": {"total_tokens": total_tokens}},
                ],
            },
        }
        path.write_text(json.dumps(payload))

    def test_below_threshold_returns_false(self, tmp_path: Path) -> None:
        mod = self._mod()
        self._write_status(tmp_path, "test-lane", 100_000)
        result = mod._check_token_burn(
            state_dir=tmp_path,
            lane_id="test-lane",
            run_id="run-1",
            threshold=2_000_000,
            log_dir=tmp_path / "logs",
        )
        assert result is False

    def test_exceeds_threshold_returns_true_and_writes_log(self, tmp_path: Path) -> None:
        mod = self._mod()
        self._write_status(tmp_path, "test-lane", 3_000_000)
        log_dir = tmp_path / "logs"
        result = mod._check_token_burn(
            state_dir=tmp_path,
            lane_id="test-lane",
            run_id="run-1",
            threshold=2_000_000,
            log_dir=log_dir,
        )
        assert result is True
        log_path = log_dir / "worker-test-lane.jsonl"
        assert log_path.exists()
        events = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        assert any(e.get("event") == "token_burn_warning" for e in events)

    def test_no_observability_returns_false(self, tmp_path: Path) -> None:
        mod = self._mod()
        result = mod._check_token_burn(
            state_dir=tmp_path,
            lane_id="empty-lane",
            run_id="run-1",
            threshold=2_000_000,
            log_dir=tmp_path / "logs",
        )
        assert result is False


# ---------------------------------------------------------------------------
# worker_daemon_ctl.py: _cleanup_lock and _emit_stopped_event
# ---------------------------------------------------------------------------


class TestCleanupLock:
    def _mod(self):
        return _load("worker_daemon_ctl")

    def test_deletes_existing_lock(self, tmp_path: Path) -> None:
        mod = self._mod()
        lock = mod._lock_path(tmp_path, "test-lane")
        lock.touch()
        assert lock.exists()
        mod._cleanup_lock(tmp_path, "test-lane")
        assert not lock.exists()

    def test_no_error_if_lock_missing(self, tmp_path: Path) -> None:
        mod = self._mod()
        # Should not raise
        mod._cleanup_lock(tmp_path, "missing-lane")

    def test_emit_stopped_event_appends_jsonl(self, tmp_path: Path) -> None:
        mod = self._mod()
        log_dir = tmp_path / "logs"
        mod._emit_stopped_event(log_dir, "test-lane")
        log_path = log_dir / "worker-test-lane.jsonl"
        assert log_path.exists()
        events = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        assert any(e.get("event") == "worker_stopped" for e in events)

    def test_daemon_stop_cleans_lock(self, tmp_path: Path) -> None:
        """daemon_stop should delete the lock file and emit a stopped event."""
        mod = self._mod()
        state_dir = tmp_path / "state"
        log_dir = tmp_path / "logs"
        state_dir.mkdir()
        log_dir.mkdir()

        lock = mod._lock_path(state_dir, "test-lane")
        lock.write_text(json.dumps({"pid": 99999}))

        # Patch daemon_status to return a fake running process
        from unittest import mock

        fake_status = {
            "lane_id": "test-lane",
            "process": {"pid": 99999, "stopped": False},
            "status_record": {"state": "executing", "task_ref": "test"},
            "stale_lock": False,
            "worker_state": "executing",
            "state_summary": "running",
            "attention_required": False,
            "last_event": None,
        }
        with mock.patch.object(mod, "daemon_status", return_value=fake_status), \
             mock.patch.object(mod, "_signal_tree", return_value=[99999]):
            result = mod.daemon_stop(
                state_dir=state_dir,
                log_dir=log_dir,
                lane_id="test-lane",
            )

        assert result["ok"] is True
        assert not lock.exists(), "Lock file should be deleted by daemon_stop"
        log_path = log_dir / "worker-test-lane.jsonl"
        assert log_path.exists()


# ---------------------------------------------------------------------------
# lane_prompt.py: _measure_context_utilization
# ---------------------------------------------------------------------------


class TestMeasureContextUtilization:
    def _mod(self):
        return _load("lane_prompt")

    def test_basic_metrics_computed(self) -> None:
        mod = self._mod()
        prompt = "x" * 4000  # 4000 chars = ~1000 tokens
        section_sizes = {
            "header": 200,
            "assignment": 1500,
            "runtime_guidance": 800,
            "dependency_briefs": 500,
        }
        result = mod._measure_context_utilization(prompt, 8_000, section_sizes)
        assert result["prompt_chars"] == 4000
        assert result["prompt_tokens_approx"] == 1000
        assert 0 < result["utilization_ratio"] < 1.0
        assert 0 < result["domain_signal_ratio"] <= 1.0
        assert result["pressure"] in ("normal", "elevated", "high")

    def test_high_pressure_when_utilization_above_threshold(self) -> None:
        mod = self._mod()
        prompt = "x" * 3200  # 3200 chars = 800 tokens at 4 chars/token
        # model_context_window = 1000 -> utilization = 0.8 > 0.4
        # section_sizes give domain_ratio = 0/3200 = 0.0 < 0.5 -> "high"
        section_sizes = {"header": 3100, "boilerplate": 100}
        result = mod._measure_context_utilization(prompt, 1_000, section_sizes)
        assert result["pressure"] == "high"

    def test_low_pressure_baseline(self) -> None:
        mod = self._mod()
        prompt = "x" * 400  # 100 tokens
        # context window 10,000 -> utilization 0.01 -> "low"
        section_sizes = {
            "assignment": 200,
            "runtime_guidance": 100,
            "dependency_briefs": 50,
            "header": 50,
        }
        result = mod._measure_context_utilization(prompt, 10_000, section_sizes)
        assert result["pressure"] == "normal"

    def test_zero_context_window_handled(self) -> None:
        mod = self._mod()
        result = mod._measure_context_utilization("hello", 0, {"header": 5})
        assert result["utilization_ratio"] == 0.0

    def test_domain_signal_ratio_correct(self) -> None:
        mod = self._mod()
        section_sizes = {
            "header": 100,
            "assignment": 300,
            "runtime_guidance": 200,
            "dependency_briefs": 100,
        }
        result = mod._measure_context_utilization("x" * 2800, 128_000, section_sizes)
        # domain = 300+200+100 = 600, total = 700
        expected_ratio = round(600 / 700, 4)
        assert result["domain_signal_ratio"] == expected_ratio


# ---------------------------------------------------------------------------
# lane_manifest.py: token_burn_threshold and model_context_window defaults
# ---------------------------------------------------------------------------


class TestLaneManifestDefaults:
    def test_defaults_present_when_manifest_missing(self, tmp_path: Path) -> None:
        """Verify token_burn_threshold and model_context_window defaults are wired
        into a manifest lane config via get_lane_config."""
        from unittest import mock
        mod = _load("lane_manifest")
        # Build a minimal manifest dict that would pass validation if loaded
        manifest = {
            "task_ref": "test-task",
            "lanes": {
                "frontend": {
                    "branch": "codex/test-frontend",
                    "worktree_path": str(tmp_path / "lane"),
                    "owned_paths": ["apps/foo/**"],
                    "test_commands": [],
                },
            },
        }
        # Patch load_manifest to return our in-memory manifest
        with mock.patch.object(mod, "load_manifest", return_value=manifest):
            result = mod.get_lane_config(
                "test-task", "frontend", orchestrator_root=str(tmp_path)
            )
        assert result is not None
        assert result.get("token_burn_threshold") == 2_000_000
        assert result.get("model_context_window") == 128_000


# ---------------------------------------------------------------------------
# H-ORCH-HARD-01: _get_effective_owned_paths parses JSON-string artifacts
# ---------------------------------------------------------------------------


class TestGetEffectiveOwnedPathsStringArtifacts:
    def _mod(self):
        return _load("lane_exec")

    def test_string_artifact_override_applied(self, tmp_path: Path) -> None:
        """A JSON-encoded string artifact with type=owned_paths_override is parsed."""
        mod = self._mod()
        from unittest import mock

        override_artifact = json.dumps({
            "type": "owned_paths_override",
            "paths": ["apps/foo/**", "apps/bar/**"],
        })
        activity = {
            "messages": [
                {
                    "direction": "orchestrator_to_worker",
                    "payload": {},
                    "artifacts": [override_artifact],
                }
            ]
        }
        with mock.patch.object(mod, "sys") as mock_sys, \
             mock.patch("subprocess.run") as mock_run:
            mock_sys.executable = "python3"
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout=json.dumps(activity),
            )
            result = mod._get_effective_owned_paths(
                "task", "lane-a",
                owned_paths=["apps/default/**"],
                orchestrator_root=tmp_path,
            )
        assert "apps/foo/**" in result
        assert "apps/bar/**" in result

    def test_invalid_json_string_artifact_skipped(self, tmp_path: Path) -> None:
        """A non-JSON string artifact is skipped without error."""
        mod = self._mod()
        from unittest import mock

        activity = {
            "messages": [
                {
                    "direction": "orchestrator_to_worker",
                    "payload": {},
                    "artifacts": ["not-json-at-all"],
                }
            ]
        }
        with mock.patch.object(mod, "sys") as mock_sys, \
             mock.patch("subprocess.run") as mock_run:
            mock_sys.executable = "python3"
            mock_run.return_value = mock.Mock(
                returncode=0,
                stdout=json.dumps(activity),
            )
            result = mod._get_effective_owned_paths(
                "task", "lane-a",
                owned_paths=["apps/default/**"],
                orchestrator_root=tmp_path,
            )
        # Falls back to manifest paths when no valid override found
        assert result == ["apps/default/**"]


# ---------------------------------------------------------------------------
# H-ORCH-HARD-02: _ensure_lane_workers exhaustion gate
# ---------------------------------------------------------------------------


class TestEnsureLaneWorkersExhaustionGate:
    def _mod(self):
        return _load("orchestrator_daemon")

    def test_exhausted_lane_not_started(self, tmp_path: Path) -> None:
        """Lane with exhaustion_streak >= 2 should not be auto-started."""
        mod = self._mod()
        from unittest import mock

        exhausted_status = {
            "ok": True,
            "running": False,
            "attention_required": False,
            "status_record": {"exhaustion_streak": {"count": 2}},
        }
        logged: list[tuple] = []

        def _fake_log(level, event, **kw):
            logged.append((level, event, kw))

        with mock.patch(
            "agent_handoff_mcp.worker_status",
            return_value=json.dumps(exhausted_status),
        ), mock.patch(
            "agent_handoff_mcp.worker_start",
        ) as mock_start:
            rows = mod._ensure_lane_workers(
                tmp_path,
                "test-task",
                ["exhausted-lane"],
                worker_start_mode="mcp",
                log=_fake_log,
            )

        mock_start.assert_not_called()
        assert any(r.get("worker_state") == "unhealthy" for r in rows)
        assert any(e[1] == "lane_unhealthy" for e in logged)

    def test_attention_required_lane_not_started(self, tmp_path: Path) -> None:
        """Lane with attention_required=True should not be auto-started."""
        mod = self._mod()
        from unittest import mock

        attn_status = {
            "ok": True,
            "running": False,
            "attention_required": True,
            "status_record": {},
        }

        with mock.patch(
            "agent_handoff_mcp.worker_status",
            return_value=json.dumps(attn_status),
        ), mock.patch(
            "agent_handoff_mcp.worker_start",
        ) as mock_start:
            rows = mod._ensure_lane_workers(
                tmp_path,
                "test-task",
                ["attn-lane"],
                worker_start_mode="mcp",
            )

        mock_start.assert_not_called()
        assert any(r.get("reason") == "attention_required" for r in rows)


# ---------------------------------------------------------------------------
# M-ORCH-HARD-03: pressure labels match task contract
# ---------------------------------------------------------------------------


class TestPressureLabels:
    def _mod(self):
        return _load("lane_prompt")

    def test_high_pressure_label(self) -> None:
        mod = self._mod()
        # utilization > 0.4 AND domain_signal_ratio < 0.5 => "high"
        result = mod._measure_context_utilization(
            "x" * 4400,  # 1100 tokens
            2_000,         # window -> util = 1100/2000 = 0.55 > 0.4
            {"header": 4000, "noise": 400},  # domain_ratio = 0/4400 = 0.0 < 0.5
        )
        assert result["pressure"] == "high"

    def test_elevated_pressure_label(self) -> None:
        mod = self._mod()
        # utilization > 0.3 but NOT (>0.4 AND domain<0.5) => "elevated"
        result = mod._measure_context_utilization(
            "x" * 1600,   # 400 tokens
            1_000,          # util = 0.4, not > 0.4 -> fails high; util > 0.3 -> elevated
            {
                "assignment": 800,
                "runtime_guidance": 400,
                "dependency_briefs": 200,
                "header": 200,
            },  # domain_ratio high, so NOT high pressure
        )
        assert result["pressure"] == "elevated"

    def test_normal_pressure_label(self) -> None:
        mod = self._mod()
        # utilization <= 0.3 => "normal"
        result = mod._measure_context_utilization(
            "x" * 400,    # 100 tokens
            10_000,         # util = 0.01
            {"assignment": 200, "header": 200},
        )
        assert result["pressure"] == "normal"

    def test_no_medium_or_low_labels_exist(self) -> None:
        """Ensure the legacy low/medium labels are gone from all outputs."""
        mod = self._mod()
        for chars, window, sections in [
            (100, 1_000_000, {"header": 100}),
            (400, 1_000, {"header": 400}),
            (40000, 10_000, {"header": 40000}),
        ]:
            result = mod._measure_context_utilization("x" * chars, window, sections)
            assert result["pressure"] not in ("low", "medium"), \
                f"Unexpected legacy label {result['pressure']} for chars={chars}"


# ---------------------------------------------------------------------------
# M-ORCH-HARD-04: dashboard _summarize surfaces hardening signals
# ---------------------------------------------------------------------------


class TestDashboardSummarize:
    def _mod(self):
        return _load("dashboard_live")

    def _make_status(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "worker_state": "executing",
            "attention_required": False,
            "state_summary": "running",
            "process": {"pid": 1234},
            "observability": {
                "latest": {
                    "model": "gpt-5.4-mini",
                    "effective_reasoning_effort": "low",
                },
                "history": [],
            },
            "context_utilization_latest": {
                "pressure": "elevated",
                "utilization_ratio": 0.35,
                "domain_signal_ratio": 0.7,
                "prompt_tokens_approx": 4500,
                "prompt_chars": 18000,
            },
            "status_record": {"exhaustion_streak": {"count": 0}},
            "last_event": None,
            "lock_path": None,
            "running": True,
        }
        base.update(overrides)
        return base

    def test_model_and_effort_extracted(self) -> None:
        mod = self._mod()
        info = mod._summarize(self._make_status())
        assert info["model"] == "gpt-5.4-mini"
        assert info["effort"] == "low"

    def test_pressure_extracted_from_context_utilization_latest(self) -> None:
        mod = self._mod()
        info = mod._summarize(self._make_status())
        assert info["pressure"] == "elevated"

    def test_stale_lock_true_when_lock_exists_but_not_running(self, tmp_path: Path) -> None:
        mod = self._mod()
        lock = tmp_path / "worker-test.lock"
        lock.touch()
        info = mod._summarize(self._make_status(lock_path=str(lock), running=False))
        assert info["stale_lock"] is True

    def test_health_is_ok_for_healthy_lane(self) -> None:
        mod = self._mod()
        status = self._make_status(
            context_utilization_latest={"pressure": "normal"},
        )
        info = mod._summarize(status)
        assert info["health"] == "ok"

    def test_health_is_attention_when_streak_ge_2(self) -> None:
        mod = self._mod()
        status = self._make_status(
            status_record={"exhaustion_streak": {"count": 2}},
        )
        info = mod._summarize(status)
        assert info["health"] == "ATTENTION"

    def test_format_table_includes_pressure_and_effort_columns(self) -> None:
        mod = self._mod()
        info = mod._summarize(self._make_status())
        table = mod._format_table("test-task", [("my-lane", info)], "2026-01-01 00:00:00")
        assert "PRES" in table
        assert "EFFORT" in table
        assert "HEALTH" in table
        assert "elevated" in table
        assert "low" in table  # effort value


# ---------------------------------------------------------------------------
# M-ORCH-HARD-05: scope_violation event name (not scope_violation_detected)
# ---------------------------------------------------------------------------


class TestScopeViolationEventName:
    def test_event_name_is_scope_violation_not_detected(self) -> None:
        """The emitted event must be 'scope_violation', not 'scope_violation_detected'."""
        content = (SCRIPT_DIR / "worker_daemon.py").read_text()
        assert "scope_violation_detected" not in content, (
            "Found legacy event name 'scope_violation_detected' in worker_daemon.py; "
            "it must be renamed to 'scope_violation' per M-ORCH-HARD-05."
        )

    def test_scope_violation_string_present(self) -> None:
        """Sanity check: 'scope_violation' event string appears in worker_daemon.py."""
        content = (SCRIPT_DIR / "worker_daemon.py").read_text()
        assert '"scope_violation"' in content or "'scope_violation'" in content


# ---------------------------------------------------------------------------
# M-ORCH-HARD-06: exhaustion_streak JSONL event emitted after streak update
# ---------------------------------------------------------------------------


class TestExhaustionStreakEvent:
    def _mod(self):
        return _load("worker_daemon")

    def test_log_writes_exhaustion_streak_event(self, tmp_path: Path) -> None:
        """_log called with exhaustion_streak event writes expected fields to JSONL."""
        mod = self._mod()
        log_dir = tmp_path / "logs"
        mod._log("test-lane", log_dir, "WARNING", "exhaustion_streak",
                  streak=2, run_id="run-abc", lane="test-lane")
        log_path = log_dir / "worker-test-lane.jsonl"
        assert log_path.exists()
        entry = json.loads(log_path.read_text().strip())
        assert entry["event"] == "exhaustion_streak"
        assert entry["streak"] == 2
        assert entry["run_id"] == "run-abc"
        assert entry["lane"] == "test-lane"
        assert entry["level"] == "WARNING"

    def test_exhaustion_streak_event_name_in_source(self) -> None:
        """Verify the exhaustion_streak event emission is present in worker_daemon.py."""
        content = (SCRIPT_DIR / "worker_daemon.py").read_text()
        assert '"exhaustion_streak"' in content or "'exhaustion_streak'" in content


# ---------------------------------------------------------------------------
# M-ORCH-HARD-07: context_utilization threaded through observability
# ---------------------------------------------------------------------------


class TestObservabilityContextUtilization:
    def _mod(self):
        return _load("worker_daemon")

    def test_observability_entry_includes_context_utilization(self) -> None:
        """_observability_entry returns context_utilization when provided."""
        mod = self._mod()
        ctx = {"utilization_ratio": 0.35, "domain_signal_ratio": 0.6, "pressure": "elevated"}
        entry = mod._observability_entry(
            task_ref="test-task",
            lane_id="test-lane",
            cycle=0,
            phase="execution",
            backend="codex",
            model="gpt-4",
            requested_reasoning_effort="auto",
            effective_reasoning_effort="medium",
            telemetry={},
            context_utilization=ctx,
        )
        assert entry["context_utilization"] == ctx

    def test_observability_entry_omits_key_when_none(self) -> None:
        """_observability_entry should not include context_utilization key when not passed."""
        mod = self._mod()
        entry = mod._observability_entry(
            task_ref="test-task",
            lane_id="test-lane",
            cycle=0,
            phase="execution",
            backend="codex",
            model=None,
            requested_reasoning_effort="auto",
            effective_reasoning_effort="auto",
            telemetry={},
        )
        assert "context_utilization" not in entry

    def test_record_observability_stores_context_utilization_in_latest(self, tmp_path: Path) -> None:
        """_record_observability stores context_utilization inside observability.latest."""
        mod = self._mod()
        state_dir = tmp_path / ".task-state"
        state_dir.mkdir()
        log_dir = tmp_path / "logs" / "worker-daemon"
        log_dir.mkdir(parents=True)
        ctx = {"utilization_ratio": 0.25, "domain_signal_ratio": 0.8, "pressure": "normal"}
        mod._record_observability(
            orchestrator_root=tmp_path,
            task_ref="test-task",
            lane_id="test-lane",
            session="sess-1",
            cycle=0,
            phase="context_freshness",
            backend="codex",
            model="gpt-4",
            requested_reasoning_effort="auto",
            effective_reasoning_effort="medium",
            telemetry={},
            state="executing",
            summary="Context freshness recorded.",
            context_utilization=ctx,
        )
        status = mod._read_worker_status(state_dir, "test-lane")
        assert status is not None
        assert status["observability"]["latest"]["context_utilization"] == ctx


# ---------------------------------------------------------------------------
# M-GAP-REVIEW-02: _check_lane_health() covers health/degraded/unhealthy paths
# ---------------------------------------------------------------------------


class TestCheckLaneHealth:
    def _mod(self):
        return _load("orchestrator_daemon")

    def _healthy_status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "running": False,
            "attention_required": False,
            "worker_state": "idle",
            "status_record": {"exhaustion_streak": {"count": 0}, "cycle": 1},
            "observability": {"history": [], "latest": {}},
            "context_utilization_latest": {"pressure": "normal"},
        }

    def test_healthy_lane_returns_healthy(self) -> None:
        """Lane with no issues returns ('healthy', None)."""
        mod = self._mod()
        health, action = mod._check_lane_health(self._healthy_status())
        assert health == "healthy"
        assert action is None

    def test_exhaustion_streak_returns_unhealthy_promote_model(self) -> None:
        """Streak >= 2 returns ('unhealthy', 'promote_model')."""
        mod = self._mod()
        status = self._healthy_status()
        status["status_record"]["exhaustion_streak"] = {"count": 2}
        health, action = mod._check_lane_health(status)
        assert health == "unhealthy"
        assert action == "promote_model"

    def test_attention_required_returns_unhealthy_close_lane(self) -> None:
        """attention_required=True (no streak) returns ('unhealthy', 'close_lane')."""
        mod = self._mod()
        status = self._healthy_status()
        status["attention_required"] = True
        health, action = mod._check_lane_health(status)
        assert health == "unhealthy"
        assert action == "close_lane"

    def test_worker_state_unhealthy_returns_unhealthy(self) -> None:
        """worker_state == 'unhealthy' returns ('unhealthy', 'close_lane')."""
        mod = self._mod()
        status = self._healthy_status()
        status["worker_state"] = "unhealthy"
        health, action = mod._check_lane_health(status)
        assert health == "unhealthy"
        assert action == "close_lane"

    def test_scope_violation_in_history_returns_degraded_fresh_worktree(self) -> None:
        """A scope_check phase entry in observability history returns 'degraded'+'fresh_worktree'."""
        mod = self._mod()
        status = self._healthy_status()
        status["observability"]["history"] = [
            {"phase": "scope_check", "state": "scope_violation"},
        ]
        health, action = mod._check_lane_health(status)
        assert health == "degraded"
        assert action == "fresh_worktree"

    def test_high_pressure_returns_degraded_split_lane(self) -> None:
        """context pressure 'high' returns ('degraded', 'split_lane')."""
        mod = self._mod()
        status = self._healthy_status()
        status["context_utilization_latest"] = {"pressure": "high"}
        health, action = mod._check_lane_health(status)
        assert health == "degraded"
        assert action == "split_lane"

    def test_elevated_pressure_returns_degraded_no_action(self) -> None:
        """context pressure 'elevated' returns ('degraded', None)."""
        mod = self._mod()
        status = self._healthy_status()
        status["context_utilization_latest"] = {"pressure": "elevated"}
        health, action = mod._check_lane_health(status)
        assert health == "degraded"
        assert action is None

    def test_streak_takes_priority_over_scope_violation(self) -> None:
        """Streak >= 2 takes priority over scope violation."""
        mod = self._mod()
        status = self._healthy_status()
        status["status_record"]["exhaustion_streak"] = {"count": 3}
        status["observability"]["history"] = [{"phase": "scope_check"}]
        health, action = mod._check_lane_health(status)
        assert health == "unhealthy"
        assert action == "promote_model"

    def test_empty_status_returns_healthy(self) -> None:
        """Gracefully handle an almost-empty status dict."""
        mod = self._mod()
        health, action = mod._check_lane_health({"ok": True})
        assert health == "healthy"
        assert action is None


# ---------------------------------------------------------------------------
# orchestrator_daemon.py: lane_health_changed event emission
# ---------------------------------------------------------------------------


class TestLaneHealthChangedEvent:
    def _mod(self):
        return _load("orchestrator_daemon")

    def _status(self, *, streak: int = 0, attention: bool = False) -> str:
        return json.dumps({
            "ok": True,
            "running": False,
            "attention_required": attention,
            "worker_state": "idle",
            "status_record": {"exhaustion_streak": {"count": streak}},
            "observability": {"history": [], "latest": {}},
            "context_utilization_latest": {"pressure": "normal"},
        })

    def test_no_event_on_first_cycle(self, tmp_path: Path) -> None:
        """No lane_health_changed event on the first cycle (no previous state)."""
        mod = self._mod()
        from unittest import mock

        logged: list[tuple] = []

        def _fake_log(level, event, **kw):
            logged.append((level, event, kw))

        prev_health: dict = {}
        with mock.patch("agent_handoff_mcp.worker_status", return_value=self._status()), \
             mock.patch("agent_handoff_mcp.worker_start"):
            mod._ensure_lane_workers(
                tmp_path, "task", ["lane-a"],
                worker_start_mode="dry_run",
                dry_run=True,
                log=_fake_log,
                prev_health=prev_health,
            )

        assert not any(e[1] == "lane_health_changed" for e in logged)
        assert prev_health.get("lane-a") == "healthy"

    def test_event_emitted_on_health_transition(self, tmp_path: Path) -> None:
        """lane_health_changed emitted when health changes from healthy to unhealthy."""
        mod = self._mod()
        from unittest import mock

        logged: list[tuple] = []

        def _fake_log(level, event, **kw):
            logged.append((level, event, kw))

        prev_health: dict = {"lane-a": "healthy"}
        with mock.patch(
            "agent_handoff_mcp.worker_status",
            return_value=self._status(streak=2),
        ), mock.patch("agent_handoff_mcp.worker_start"):
            mod._ensure_lane_workers(
                tmp_path, "task", ["lane-a"],
                worker_start_mode="dry_run",
                dry_run=True,
                log=_fake_log,
                prev_health=prev_health,
            )

        changed = [e for e in logged if e[1] == "lane_health_changed"]
        assert changed, "expected lane_health_changed event"
        assert changed[0][2]["previous"] == "healthy"
        assert changed[0][2]["current"] == "unhealthy"
        assert prev_health.get("lane-a") == "unhealthy"

    def test_no_event_when_health_unchanged(self, tmp_path: Path) -> None:
        """No lane_health_changed when health stays the same."""
        mod = self._mod()
        from unittest import mock

        logged: list[tuple] = []

        def _fake_log(level, event, **kw):
            logged.append((level, event, kw))

        prev_health: dict = {"lane-a": "healthy"}
        with mock.patch("agent_handoff_mcp.worker_status", return_value=self._status()), \
             mock.patch("agent_handoff_mcp.worker_start"):
            mod._ensure_lane_workers(
                tmp_path, "task", ["lane-a"],
                worker_start_mode="dry_run",
                dry_run=True,
                log=_fake_log,
                prev_health=prev_health,
            )

        assert not any(e[1] == "lane_health_changed" for e in logged)


# ---------------------------------------------------------------------------
# SG3: owned_paths_override native support in _normalize_lane_message_payload
# ---------------------------------------------------------------------------


class TestOwnedPathsOverrideNormalizer:
    """Verify that _normalize_lane_message_payload passes owned_paths_override through."""

    def _core(self):
        import importlib.util as _iu
        mcp_root = REPO_ROOT / "packages" / "agent-handoff-mcp" / "src"
        path = mcp_root / "agent_handoff_mcp" / "core.py"
        spec = _iu.spec_from_file_location("agent_handoff_mcp.core", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load core.py from {path}")
        mod = _iu.module_from_spec(spec)
        if str(mcp_root) not in sys.path:
            sys.path.insert(0, str(mcp_root))
        spec.loader.exec_module(mod)
        return mod

    def test_owned_paths_override_normalized(self) -> None:
        """owned_paths_override list is preserved in normalized payload."""
        core = self._core()
        payload = {
            "summary": "narrow dispatch",
            "owned_paths_override": ["apps/service/**", "packages/shared/**"],
        }
        normalized, err = core._normalize_lane_message_payload(payload)
        assert err is None
        assert normalized is not None
        assert normalized["owned_paths_override"] == ["apps/service/**", "packages/shared/**"]

    def test_owned_paths_override_absent_excluded(self) -> None:
        """Absent owned_paths_override is not included in normalized payload."""
        core = self._core()
        payload = {"summary": "regular dispatch"}
        normalized, err = core._normalize_lane_message_payload(payload)
        assert err is None
        assert normalized is not None
        assert "owned_paths_override" not in normalized

    def test_owned_paths_override_empty_list_excluded(self) -> None:
        """An empty owned_paths_override is treated as absent."""
        core = self._core()
        payload = {"summary": "dispatch", "owned_paths_override": []}
        normalized, err = core._normalize_lane_message_payload(payload)
        assert err is None
        assert normalized is not None
        assert "owned_paths_override" not in normalized

    def test_owned_paths_override_string_coerced(self) -> None:
        """A single string is coerced to a list."""
        core = self._core()
        payload = {"owned_paths_override": "apps/foo/**"}
        normalized, err = core._normalize_lane_message_payload(payload)
        assert err is None
        assert normalized is not None
        assert normalized["owned_paths_override"] == ["apps/foo/**"]


# ---------------------------------------------------------------------------
# SG4: _compute_finding_diff + _finding_stable_id
# ---------------------------------------------------------------------------


class TestComputeFindingDiff:
    def _mod(self):
        return _load("worker_daemon")

    def _finding(
        self,
        severity: str = "HIGH",
        category: str = "GAP",
        file_path: str = "src/main.py",
        line_start: int = 10,
    ) -> dict[str, Any]:
        return {
            "severity": severity,
            "category": category,
            "file_path": file_path,
            "line_start": line_start,
        }

    def test_all_new_when_prev_empty(self) -> None:
        mod = self._mod()
        findings = [self._finding(), self._finding(file_path="src/b.py")]
        diff = mod._compute_finding_diff(set(), findings)
        assert len(diff["new"]) == 2
        assert diff["recurring"] == []
        assert diff["resolved_count"] == 0

    def test_recurring_finds_match(self) -> None:
        mod = self._mod()
        f1 = self._finding(file_path="src/a.py", line_start=5)
        f2 = self._finding(file_path="src/b.py", line_start=20)
        prev_ids = {mod._finding_stable_id(f1)}
        diff = mod._compute_finding_diff(prev_ids, [f1, f2])
        assert len(diff["recurring"]) == 1
        assert diff["recurring"][0]["file_path"] == "src/a.py"
        assert len(diff["new"]) == 1
        assert diff["new"][0]["file_path"] == "src/b.py"
        assert diff["resolved_count"] == 0

    def test_resolved_count_correct(self) -> None:
        mod = self._mod()
        f_old = self._finding(file_path="src/old.py", line_start=1)
        prev_ids = {mod._finding_stable_id(f_old)}
        diff = mod._compute_finding_diff(prev_ids, [])
        assert diff["resolved_count"] == 1
        assert diff["new"] == []
        assert diff["recurring"] == []

    def test_finding_stable_id_deterministic(self) -> None:
        mod = self._mod()
        f = self._finding()
        id1 = mod._finding_stable_id(f)
        id2 = mod._finding_stable_id(f)
        assert id1 == id2
        assert id1 == "HIGH:GAP:src/main.py:10"

    def test_partial_match_not_recurring(self) -> None:
        """A finding with same file but different line is treated as new."""
        mod = self._mod()
        f1 = self._finding(line_start=10)
        f2 = self._finding(line_start=20)
        prev_ids = {mod._finding_stable_id(f1)}
        diff = mod._compute_finding_diff(prev_ids, [f2])
        assert len(diff["new"]) == 1
        assert diff["recurring"] == []


# ---------------------------------------------------------------------------
# SG1: salvage_and_close_lane
# ---------------------------------------------------------------------------


class TestSalvageAndCloseLane:
    def _mod(self):
        return _load("orchestrator_daemon")

    def test_dry_run_classifies_files(self, tmp_path: Path) -> None:
        """dry_run=True returns classification without calling MCP."""
        mod = self._mod()
        from unittest import mock

        manifest = {
            "task_ref": "test-task",
            "lanes": {
                "frontend": {
                    "branch": "codex/test-frontend",
                    "worktree_path": str(tmp_path),
                    "owned_paths": ["apps/wp/**"],
                    "test_commands": [],
                },
                "backend": {
                    "branch": "codex/test-backend",
                    "worktree_path": str(tmp_path),
                    "owned_paths": ["apps/service/**"],
                    "test_commands": [],
                },
            },
        }

        def fake_git(args, **kw):
            class R:
                returncode = 0
                stdout = "apps/wp/Button.tsx\napps/service/main.py\nsome/other.py\n"
                stderr = ""
            return R()

        with mock.patch("subprocess.run", side_effect=fake_git), \
             mock.patch(
                 "orchestrator_lanes._resolve_lane_worktree",
                 return_value=tmp_path,
             ), \
             mock.patch("lane_manifest.load_manifest", return_value=manifest):
            result = mod.salvage_and_close_lane(
                tmp_path, "test-task", "frontend", dry_run=True
            )

        assert result["dry_run"] is True
        assert "apps/wp/Button.tsx" in result["this_lane"]
        assert "apps/service/main.py" in result["other_lanes"].get("backend", [])
        assert "some/other.py" in result["unclassified"]

    def test_returns_worktree_preserved(self, tmp_path: Path) -> None:
        mod = self._mod()
        from unittest import mock

        manifest = {
            "task_ref": "test-task",
            "lanes": {
                "frontend": {
                    "branch": "codex/test-frontend",
                    "worktree_path": str(tmp_path),
                    "owned_paths": ["apps/wp/**"],
                    "test_commands": [],
                },
            },
        }

        def fake_git(args, **kw):
            class R:
                returncode = 0
                stdout = ""
                stderr = ""
            return R()

        with mock.patch("subprocess.run", side_effect=fake_git), \
             mock.patch(
                 "orchestrator_lanes._resolve_lane_worktree",
                 return_value=tmp_path,
             ), \
             mock.patch("lane_manifest.load_manifest", return_value=manifest):
            result = mod.salvage_and_close_lane(
                tmp_path, "test-task", "frontend", dry_run=True
            )

        assert result["worktree_preserved"] == str(tmp_path)

    def test_no_worktree_returns_empty_lists(self, tmp_path: Path) -> None:
        mod = self._mod()
        from unittest import mock

        manifest = {
            "task_ref": "test-task",
            "lanes": {"frontend": {"owned_paths": ["apps/wp/**"]}},
        }

        with mock.patch(
            "orchestrator_lanes._resolve_lane_worktree",
            return_value=None,
        ), mock.patch("lane_manifest.load_manifest", return_value=manifest):
            result = mod.salvage_and_close_lane(
                tmp_path, "test-task", "frontend", dry_run=True
            )

        assert result["this_lane"] == []
        assert result["other_lanes"] == {}
        assert result["unclassified"] == []


# ---------------------------------------------------------------------------
# SG2: _provision_fresh_worktree
# ---------------------------------------------------------------------------


class TestProvisionFreshWorktree:
    def _mod(self):
        return _load("orchestrator_lanes")

    def test_dry_run_returns_path_without_creating_worktree(self, tmp_path: Path) -> None:
        mod = self._mod()
        from unittest import mock

        config = {
            "branch": "codex/test-frontend",
            "worktree_path": str(tmp_path),
            "owned_paths": ["apps/wp/**"],
        }

        head_result = mock.MagicMock()
        head_result.stdout = "feature/main\n"
        head_result.returncode = 0

        with mock.patch("lane_manifest.get_lane_config", return_value=config), \
             mock.patch("subprocess.run", return_value=head_result):
            path = mod._provision_fresh_worktree(
                tmp_path, "test-task", "frontend", dry_run=True
            )

        assert path is not None
        assert "frontend-fresh" in str(path)

    def test_returns_none_when_git_worktree_add_fails(self, tmp_path: Path) -> None:
        mod = self._mod()
        from unittest import mock

        config = {
            "branch": "codex/test-frontend",
            "worktree_path": str(tmp_path),
            "owned_paths": ["apps/wp/**"],
        }

        def side_effect(args, **kw):
            result = mock.MagicMock()
            if "rev-parse" in args:
                result.returncode = 0
                result.stdout = "main\n"
            else:
                result.returncode = 1
                result.stdout = ""
                result.stderr = "worktree already exists"
            return result

        with mock.patch("lane_manifest.get_lane_config", return_value=config), \
             mock.patch("subprocess.run", side_effect=side_effect):
            path = mod._provision_fresh_worktree(
                tmp_path, "test-task", "frontend", dry_run=False
            )

        assert path is None

    def test_returns_none_when_no_lane_config(self, tmp_path: Path) -> None:
        mod = self._mod()
        from unittest import mock

        with mock.patch("lane_manifest.get_lane_config", return_value=None):
            path = mod._provision_fresh_worktree(
                tmp_path, "test-task", "frontend", dry_run=True
            )

        assert path is None


# ---------------------------------------------------------------------------
# SG5: dashboard_tui.py importability and callable surface
# ---------------------------------------------------------------------------


class TestDashboardTui:
    """Verify dashboard_tui.py is importable and exposes key symbols."""

    def _mod(self):
        return _load("dashboard_tui")

    def test_module_has_main(self) -> None:
        mod = self._mod()
        assert callable(getattr(mod, "main", None))

    def test_run_rich_live_callable(self) -> None:
        mod = self._mod()
        assert callable(getattr(mod, "_run_rich_live", None))

    def test_run_plain_text_callable(self) -> None:
        mod = self._mod()
        assert callable(getattr(mod, "_run_plain_text", None))

    def test_textual_available_flag_is_bool(self) -> None:
        mod = self._mod()
        flag = getattr(mod, "_TEXTUAL_AVAILABLE", None)
        assert isinstance(flag, bool)

    def test_rich_live_renders_once(self, tmp_path: Path) -> None:
        """_run_rich_live renders one frame without error in once=True mode."""
        mod = self._mod()
        from unittest import mock

        def fake_status(*args, **kw) -> dict[str, Any]:
            return {"lane_id": "frontend", "worker_state": "idle", "state_summary": "idle"}

        with mock.patch.object(mod, "_mcp_worker_status", side_effect=fake_status):
            mod._run_rich_live(
                orchestrator_root=tmp_path,
                task_ref="test-task",
                lane_ids=["frontend"],
                interval=1,
                once=True,
            )

