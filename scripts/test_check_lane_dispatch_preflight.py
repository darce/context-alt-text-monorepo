"""Task-scoped dispatch checks against real Git histories and failure paths."""

import builtins
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_lane_dispatch_preflight.py"


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True, timeout=10
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Preflight Test")
    (tmp_path / "file").write_text("base")
    git(tmp_path, "add", "file")
    git(tmp_path, "commit", "-m", "base")
    git(tmp_path, "branch", "lane/stale")
    (tmp_path / "file").write_text("integration advance")
    git(tmp_path, "commit", "-am", "advance")
    git(tmp_path, "checkout", "-b", "lane/fresh")
    (tmp_path / "lane-file").write_text("lane work")
    git(tmp_path, "add", "lane-file")
    git(tmp_path, "commit", "-m", "lane work")
    (tmp_path / "manifests").mkdir()
    write_manifest(tmp_path)
    return tmp_path


def lane(branch="lane/fresh", **overrides):
    return {
        "branch": branch,
        "owned_paths": ["scripts/a.py"],
        "test_commands": ["python3 -m pytest scripts/test_a.py"],
        "preferred_backend": "codex-remote",
        "preferred_model": "gpt-6.1-sol",
        "preferred_reasoning_effort": "high",
        **overrides,
    }


def write_manifest(repo, task="TASK", lanes=None):
    path = repo / "manifests" / f"{task}.json"
    path.write_text(json.dumps({"task_ref": task, "lanes": lanes or {"worker": lane()}}))
    return path


def run(repo, *args, task=True):
    assert SCRIPT.is_file(), f"missing production preflight: {SCRIPT}"
    command = [sys.executable, str(SCRIPT), "--manifest-dir", str(repo / "manifests"), "--json"]
    if task:
        command += ["--task-ref", "TASK"]
    return subprocess.run(command + list(args), cwd=repo, text=True, capture_output=True, timeout=20)


def report(result, code=0):
    assert result.returncode == code, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] == (code == 0)
    return payload


def error_codes(payload):
    return {finding["rule"] for finding in payload["findings"] if finding["level"] == "ERROR"}


def test_fresh_reports_exact_commits_and_never_mutates(repo):
    before = git(repo, "show-ref")
    row = report(run(repo))["lanes"][0]
    assert row == {
        "task": "TASK", "lane": "worker", "branch": "lane/fresh",
        "integration_sha": git(repo, "rev-parse", "main"),
        "lane_sha": git(repo, "rev-parse", "lane/fresh"),
        "freshness": "fresh",
    }
    assert git(repo, "show-ref") == before


def test_stale_is_actionable_and_retains_both_shas(repo):
    write_manifest(repo, lanes={"worker": lane("lane/stale")})
    payload = report(run(repo), 1)
    assert "branch-stale" in error_codes(payload)
    assert payload["lanes"][0]["freshness"] == "stale"
    assert payload["lanes"][0]["lane_sha"] == git(repo, "rev-parse", "lane/stale")
    assert payload["lanes"][0]["integration_sha"] == git(repo, "rev-parse", "main")
    assert "before dispatch" in payload["findings"][0]["message"]


def test_missing_branch_does_not_resolve_a_same_named_tag(repo):
    git(repo, "tag", "lane/missing")
    write_manifest(repo, lanes={"worker": lane("lane/missing")})
    payload = report(run(repo), 1)
    assert "branch-missing" in error_codes(payload)
    assert payload["lanes"][0]["lane_sha"] is None


@pytest.mark.parametrize("branch", [None, "", "--help", "main^{commit}", "../escape", 42])
def test_invalid_branches(repo, branch):
    write_manifest(repo, lanes={"worker": lane(branch)})
    assert "branch-invalid" in error_codes(report(run(repo), 1))


@pytest.mark.parametrize("ref,rule", [("missing", "integration-ref-missing"), ("--help", "integration-ref-invalid"), ("main~1", "integration-ref-invalid")])
def test_integration_errors(repo, ref, rule):
    assert rule in error_codes(report(run(repo, f"--integration-ref={ref}"), 1))


def test_explicit_integration_ref_and_full_lane_ref(repo):
    write_manifest(repo, lanes={"worker": lane("refs/heads/lane/stale")})
    payload = report(run(repo, "--integration-ref", "refs/heads/lane/stale"))
    assert payload["lanes"][0]["freshness"] == "fresh"


@pytest.mark.parametrize("document", ["{bad", "[]", '{"lanes": []}', '{"lanes": {"bad": null}}'])
def test_malformed_manifest(repo, document):
    (repo / "manifests/TASK.json").write_text(document)
    assert "manifest-malformed" in error_codes(report(run(repo), 1))


def test_missing_manifest(repo):
    assert "manifest-missing" in error_codes(report(run(repo, "--task-ref", "MISSING"), 2))


@pytest.mark.parametrize("task", ["../TASK", "--help", "TASK/other"])
def test_task_refs_cannot_escape_manifest_directory(repo, task):
    assert "task-ref-invalid" in error_codes(report(run(repo, f"--task-ref={task}", task=False), 2))


def test_requires_explicit_task_scope(repo):
    result = run(repo, task=False)
    assert result.returncode == 2
    assert "--task-ref" in result.stderr


def test_task_scoping_and_repeatable_task_refs(repo):
    (repo / "manifests/OLD.json").write_text("{bad")
    write_manifest(repo, "SECOND")
    payload = report(run(repo, "--task-ref", "SECOND"))
    assert {row["task"] for row in payload["lanes"]} == {"TASK", "SECOND"}


@pytest.mark.parametrize("terminal", [{"terminal": {"status": "merged"}}, *({"status": status} for status in ("merged", "closed", "closed_stale", "retired"))])
def test_terminal_skip_preserves_rule_checker_contract(repo, terminal):
    write_manifest(repo, lanes={"old": lane(None, test_commands=[], **terminal)})
    payload = report(run(repo, "--integration-ref", "missing"))
    assert payload["lanes"] == []
    assert payload["findings"] == []


def test_rule_failures_and_warnings_preserve_ids(repo):
    write_manifest(repo, lanes={"worker": lane(test_commands=[], owned_paths=["a", "b", "c", "d"])})
    payload = report(run(repo), 1)
    assert "test-commands-empty" in error_codes(payload)
    assert any(item["rule"] == "owned-paths-wide" and item["level"] == "WARNING" for item in payload["findings"])
    assert payload["lanes"][0]["freshness"] == "fresh"


def test_human_output(repo):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest-dir", str(repo / "manifests"), "--task-ref", "TASK"],
        cwd=repo, text=True, capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "TASK" in result.stdout and "worker" in result.stdout and "fresh" in result.stdout
    assert "unverified" in result.stdout.lower()


@pytest.fixture
def module(monkeypatch):
    assert SCRIPT.is_file(), f"missing production preflight: {SCRIPT}"
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("preflight_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("failure,rule", [(FileNotFoundError("git missing"), "git-unavailable"), (subprocess.TimeoutExpired(["git"], 10), "git-timeout")])
def test_git_io_failure_is_loud(module, repo, monkeypatch, capsys, failure, rule):
    def fail(*args, **kwargs):
        assert kwargs["timeout"] <= 15
        assert kwargs.get("shell", False) is False
        raise failure
    monkeypatch.setattr(module.subprocess, "run", fail)
    result = module.main(["--manifest-dir", str(repo / "manifests"), "--task-ref", "TASK", "--json"])
    assert result != 0
    assert rule in error_codes(json.loads(capsys.readouterr().out))


def test_checker_import_failure_is_loud(module, repo, monkeypatch, capsys):
    original = builtins.__import__
    def fail(name, *args, **kwargs):
        if name == "check_lane_manifest_rules":
            raise ImportError("checker unavailable")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fail)
    assert module.main(["--manifest-dir", str(repo / "manifests"), "--task-ref", "TASK", "--json"]) != 0
    assert "rule-checker-unavailable" in error_codes(json.loads(capsys.readouterr().out))


def test_manifest_read_failure_is_loud(module, repo, monkeypatch, capsys):
    original = Path.read_text
    def fail(path, *args, **kwargs):
        if path.name == "TASK.json":
            raise OSError("read denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", fail)
    assert module.main(["--manifest-dir", str(repo / "manifests"), "--task-ref", "TASK", "--json"]) == 1
    assert "manifest-malformed" in error_codes(json.loads(capsys.readouterr().out))


def test_make_forwarding_and_existing_target_compatibility(repo):
    scripts = repo / "scripts"
    scripts.mkdir()
    assert SCRIPT.is_file(), f"missing production preflight: {SCRIPT}"
    for name in (SCRIPT.name, "check_lane_manifest_rules.py"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    makefile = repo / "test.mk"
    makefile.write_text(f"ROOT_MAKEFILE_DIR := {repo}\ninclude {ROOT / 'mk/lane-overlaps.mk'}\n")
    def make(target, *extra):
        return subprocess.run(
            ["make", "--no-print-directory", "-f", str(makefile), target, "TASK=TASK",
             f"LANE_OVERLAPS_MANIFEST_DIR={repo / 'manifests'}", *extra],
            cwd=repo, capture_output=True, text=True, timeout=20,
        )
    payload = report(make("lane-dispatch-preflight", "LANE_DISPATCH_PREFLIGHT_JSON=1"))
    assert payload["lanes"][0]["task"] == "TASK"
    assert "integration-ref-missing" in error_codes(report(make(
        "lane-dispatch-preflight", "LANE_DISPATCH_PREFLIGHT_JSON=1",
        "LANE_DISPATCH_PREFLIGHT_INTEGRATION_REF=missing"), 2))
    assert make("lane-manifest-rules").returncode == 0
    assert make("lane-dispatch-preflight", "TASK=").returncode != 0
    injection = make("lane-dispatch-preflight", "TASK=TASK;touch injected")
    assert injection.returncode != 0
    assert not (repo / "injected").exists()
