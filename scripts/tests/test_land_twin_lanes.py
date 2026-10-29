"""Behavioral contract for exact-base synthetic-twin landing (real Git producers)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "workstate/land_twin_lanes.py"


def git(root, *args, ok=True, env=None):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", **(env or {})}, timeout=15,
    )
    if ok:
        assert result.returncode == 0, result.stderr
    return result.stdout.strip() if ok else result


def commit(root, message):
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def twin(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-qb", "integration")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    (root / ".gitignore").write_text(".task-state/\n")
    (root / "owned.txt").write_text("base\n")
    (root / "delete.txt").write_text("remove me\n")
    (root / "exec.sh").write_text("#!/bin/sh\nexit 0\n")
    (root / "unrelated.txt").write_text("integration\n")
    initial = commit(root, "initial")
    git(root, "checkout", "-qb", "lane-a")
    # Synthetic twin carries copied history that MUST NOT be landed.
    (root / "unrelated.txt").write_text("copied unrelated history\n")
    base = commit(root, "synthetic main twin")
    (root / "owned.txt").write_text("desired\n")
    (root / "delete.txt").unlink()
    (root / "exec.sh").chmod(0o755)
    tip = commit(root, "reviewed lane a")
    git(root, "checkout", "-q", "integration")
    spec = {
        "task": "FIXTURE-1",
        "integration": {"checkout": str(root), "branch": "integration", "base": initial},
        "receipt": ".task-state/FIXTURE-1/receipt.json",
        "lanes": [{"id": "a", "branch": "lane-a", "base": base, "tip": tip,
                   "owned_paths": ["owned.txt", "delete.txt", "exec.sh"]}],
    }
    spec_path = tmp_path / "spec.json"
    return root, spec, spec_path


def run(twin, mode="--check", task="FIXTURE-1", success=True):
    root, spec, path = twin
    path.write_text(json.dumps(spec))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--spec", str(path), "--task", task, mode],
        capture_output=True, text=True, timeout=20,
    )
    if success:
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert result.returncode != 0
    assert "land_twin_lanes:" in result.stderr
    return result


def receipt(twin):
    root, spec, _ = twin
    return json.loads((root / spec["receipt"]).read_text())


def test_check_composes_only_base_tip_and_does_not_mutate_index(twin):
    root, spec, _ = twin
    index = (root / ".git/index").read_bytes()
    before = git(root, "rev-parse", "HEAD")
    result = run(twin)
    tree = result["composed_tree"]
    assert git(root, "show", f"{tree}:owned.txt") == "desired"
    assert git(root, "show", f"{tree}:unrelated.txt") == "integration"
    assert git(root, "ls-tree", tree, "delete.txt") == ""
    assert git(root, "ls-tree", tree, "exec.sh").startswith("100755 blob")
    assert (root / ".git/index").read_bytes() == index
    assert git(root, "rev-parse", "HEAD") == before
    assert (root / "owned.txt").read_text() == "base\n"
    assert receipt(twin)["spec_sha256"]
    spec["expected_tree"] = tree
    # Changing a reviewed contract requires a fresh receipt; no production overwrite.
    (root / spec["receipt"]).unlink()
    assert run(twin)["composed_tree"] == tree


def test_apply_preserves_lane_ancestry_deletion_modes_and_is_idempotent(twin):
    root, spec, _ = twin
    expected = run(twin)["composed_tree"]
    result = run(twin, "--apply")
    landed = git(root, "rev-parse", "HEAD")
    assert git(root, "rev-parse", "HEAD^{tree}") == expected
    assert git(root, "merge-base", "--is-ancestor", spec["lanes"][0]["tip"], "HEAD") == ""
    assert git(root, "show", "HEAD:unrelated.txt") == "integration"
    assert not (root / "delete.txt").exists()
    assert (root / "exec.sh").stat().st_mode & 0o111
    assert result["status"] == "applied"
    assert run(twin, "--apply")["status"] == "applied"
    assert git(root, "rev-parse", "HEAD") == landed
    assert git(root, "status", "--porcelain") == ""


def test_two_lanes_resume_after_second_commit_hook_failure(twin):
    root, spec, _ = twin
    git(root, "checkout", "-qb", "lane-b", spec["integration"]["base"])
    (root / "second.txt").write_text("second\n")
    tip = commit(root, "reviewed lane b")
    spec["lanes"].append({"id": "b", "branch": "lane-b", "base": spec["integration"]["base"],
                          "tip": tip, "owned_paths": ["second.txt"]})
    git(root, "checkout", "-q", "integration")
    hook = root / ".git/hooks/pre-commit"
    hook.write_text('#!/bin/sh\nif git diff --cached --name-only | grep -q second.txt; then exit 1; fi\n')
    hook.chmod(0o755)
    run(twin, "--apply", success=False)
    saved = receipt(twin)
    assert len(saved["landings"]) == 1
    assert saved["pending"]["lane"] == "b"
    first = saved["landings"][0]["commit"]
    hook.unlink()
    assert run(twin, "--apply")["status"] == "applied"
    assert receipt(twin)["landings"][0]["commit"] == first
    assert git(root, "rev-list", "--first-parent", "--count", f'{spec["integration"]["base"]}..HEAD') == "2"
    assert git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("defect", ["unowned", "clobber", "mode_clobber", "dirty", "staged", "moved_tip",
                                  "wrong_base", "wrong_tree", "wrong_task", "traversal", "symlink_receipt",
                                  "untracked_collision", "symlink_parent", "unknown_field"])
def test_refuses_unsafe_specs_without_changing_head_or_index(twin, defect, tmp_path):
    root, spec, _ = twin
    task = "FIXTURE-1"
    if defect == "unowned":
        spec["lanes"][0]["owned_paths"] = ["owned.txt"]
    elif defect in {"clobber", "mode_clobber"}:
        if defect == "clobber":
            (root / "owned.txt").write_text("other integrated change\n")
        else:
            (root / "owned.txt").chmod(0o755)
        spec["integration"]["base"] = commit(root, "concurrent integration")
    elif defect == "dirty":
        (root / "owned.txt").write_text("operator work\n")
    elif defect == "staged":
        (root / "owned.txt").write_text("operator staged work\n")
        git(root, "add", "owned.txt")
    elif defect == "moved_tip":
        git(root, "update-ref", "refs/heads/lane-a", spec["lanes"][0]["base"])
    elif defect == "wrong_base":
        spec["integration"]["base"] = spec["lanes"][0]["base"]
    elif defect == "wrong_tree":
        spec["expected_tree"] = git(root, "rev-parse", "HEAD^{tree}")
    elif defect == "wrong_task":
        task = "ANOTHER-1"
    elif defect == "traversal":
        spec["receipt"] = "../escape.json"
    elif defect == "symlink_receipt":
        (root / ".task-state").symlink_to(tmp_path)
    elif defect == "untracked_collision":
        git(root, "checkout", "-q", "lane-a")
        (root / "new.txt").write_text("lane\n")
        spec["lanes"][0]["tip"] = commit(root, "add new")
        spec["lanes"][0]["owned_paths"].append("new.txt")
        git(root, "checkout", "-q", "integration")
        (root / "new.txt").write_text("operator untracked\n")
    elif defect == "symlink_parent":
        spec["lanes"][0]["owned_paths"].append("../outside")
    elif defect == "unknown_field":
        spec["shell_command"] = "true"
    before = git(root, "rev-parse", "HEAD")
    index = (root / ".git/index").read_bytes()
    run(twin, "--apply", task=task, success=False)
    assert git(root, "rev-parse", "HEAD") == before
    assert (root / ".git/index").read_bytes() == index


def test_already_desired_is_allowed_but_history_is_still_preserved(twin):
    root, spec, _ = twin
    (root / "owned.txt").write_text("desired\n")
    spec["integration"]["base"] = commit(root, "copied desired bytes")
    run(twin, "--apply")
    assert git(root, "merge-base", "--is-ancestor", spec["lanes"][0]["tip"], "HEAD") == ""


def test_cleanup_requires_positive_evidence_and_uses_safe_branch_deletion(twin):
    root, spec, _ = twin
    spec["cleanup"] = {"branches": ["lane-a"]}
    run(twin, "--cleanup", success=False)
    assert git(root, "rev-parse", "lane-a") == spec["lanes"][0]["tip"]
    run(twin, "--apply")
    assert run(twin, "--cleanup")["status"] == "cleaned"
    assert git(root, "show-ref", "--verify", "refs/heads/lane-a", ok=False).returncode != 0
    assert run(twin, "--cleanup")["status"] == "cleaned"


def test_cleanup_retains_checked_out_lane_and_unknown_resources(twin, tmp_path):
    root, spec, _ = twin
    worktree = tmp_path / "lane-worktree"
    git(root, "worktree", "add", "-q", str(worktree), "lane-a")
    spec["cleanup"] = {"branches": ["lane-a"]}
    run(twin, "--apply")
    result = run(twin, "--cleanup")
    assert result["cleanup_results"][0]["reason"]
    assert worktree.exists()
    assert git(root, "rev-parse", "lane-a") == spec["lanes"][0]["tip"]


def test_cleanup_never_deletes_sandbox_or_attempt_evidence(twin, tmp_path):
    root, spec, _ = twin
    unknown = tmp_path / "attempt-evidence-keep"
    unknown.mkdir()
    (unknown / "operator.txt").write_text("keep\n")
    spec["cleanup"] = {"sandboxes": [{"path": str(unknown), "marker": "fake"}]}
    run(twin, "--cleanup", success=False)
    assert (unknown / "operator.txt").read_text() == "keep\n"


def test_import_has_no_optional_dependencies_and_no_side_effects(tmp_path):
    result = subprocess.run([sys.executable, "-I", "-c",
        "import importlib.util; "
        f"s=importlib.util.spec_from_file_location('land_twin', {str(SCRIPT)!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)"],
        cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert not list(tmp_path.iterdir())


def test_missing_spec_reports_io_failure_without_traceback(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--spec", str(tmp_path / "missing.json"),
                             "--task", "FIXTURE-1", "--check"], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "land_twin_lanes:" in result.stderr
    assert "Traceback" not in result.stderr


def test_git_failure_and_receipt_io_failure_are_loud(twin, monkeypatch, capsys):
    # Read subprocess.run's actual CompletedProcess return shape before replacing Git.
    root, spec, path = twin
    path.write_text(json.dumps(spec))
    module_spec = importlib.util.spec_from_file_location("land_twin", SCRIPT)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    real_run = module.subprocess.run
    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git unavailable")
    monkeypatch.setattr(module.subprocess, "run", missing_git)
    assert module.main(["--spec", str(path), "--task", "FIXTURE-1", "--check"]) == 1
    assert "git unavailable" in capsys.readouterr().err
    monkeypatch.setattr(module.subprocess, "run", real_run)
    (root / ".task-state").mkdir()
    (root / ".task-state/FIXTURE-1").write_text("not a directory")
    assert module.main(["--spec", str(path), "--task", "FIXTURE-1", "--check"]) == 1
    assert capsys.readouterr().err
    assert git(root, "rev-parse", "HEAD") == spec["integration"]["base"]


def import_helper():
    module_spec = importlib.util.spec_from_file_location("land_twin", SCRIPT)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_hidden_tracked_work_cannot_be_overwritten(twin, flag):
    root, spec, _ = twin
    git(root, "update-index", flag, "owned.txt")
    (root / "owned.txt").write_text("hidden operator work\n")
    before = (root / ".git/index").read_bytes()
    failure = run(twin, "--apply", success=False)
    assert "hidden index flags" in failure.stderr
    assert (root / "owned.txt").read_text() == "hidden operator work\n"
    assert (root / ".git/index").read_bytes() == before
    assert git(root, "rev-parse", "HEAD") == spec["integration"]["base"]


def test_optional_lock_import_failure_is_reported(twin, monkeypatch, capsys):
    root, spec, path = twin
    path.write_text(json.dumps(spec))
    module = import_helper()
    import builtins
    original = builtins.__import__
    def without_lock(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError("fcntl unavailable")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", without_lock)
    assert module.main(["--spec", str(path), "--task", "FIXTURE-1", "--check"]) == 1
    assert "fcntl unavailable" in capsys.readouterr().err
    assert git(root, "rev-parse", "HEAD") == spec["integration"]["base"]


def test_git_timeout_is_bounded_and_reported(twin, monkeypatch, capsys):
    root, spec, path = twin
    path.write_text(json.dumps(spec))
    module = import_helper()
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired(args[0], 30)
    monkeypatch.setattr(module.subprocess, "run", timeout)
    assert module.main(["--spec", str(path), "--task", "FIXTURE-1", "--check"]) == 1
    assert "timed out" in capsys.readouterr().err


def test_resume_adopts_commit_after_crash_before_receipt_save(twin, monkeypatch):
    root, spec, path = twin
    path.write_text(json.dumps(spec))
    module = import_helper()
    real_save = module.save
    def crash_after_commit(path, state):
        if state["landings"]:
            raise SystemExit("simulate crash after commit")
        return real_save(path, state)
    monkeypatch.setattr(module, "save", crash_after_commit)
    with pytest.raises(SystemExit, match="simulate crash"):
        module.main(["--spec", str(path), "--task", "FIXTURE-1", "--apply"])
    landed = git(root, "rev-parse", "HEAD")
    assert receipt(twin)["pending"]
    assert run(twin, "--apply")["status"] == "applied"
    assert git(root, "rev-parse", "HEAD") == landed
    assert len(receipt(twin)["landings"]) == 1


def test_cleanup_recovers_crash_after_branch_deletion(twin, monkeypatch):
    root, spec, path = twin
    spec["cleanup"] = {"branches": ["lane-a"]}
    run(twin, "--apply")
    module = import_helper()
    real_run = module.Git.run
    def crash_after_delete(self, *args, **kwargs):
        result = real_run(self, *args, **kwargs)
        if args[:2] == ("branch", "-d") and result.returncode == 0:
            raise SystemExit("crash after delete")
        return result
    monkeypatch.setattr(module.Git, "run", crash_after_delete)
    with pytest.raises(SystemExit, match="crash after delete"):
        module.main(["--spec", str(path), "--task", "FIXTURE-1", "--cleanup"])
    assert git(root, "show-ref", "--verify", "refs/heads/lane-a", ok=False).returncode != 0
    assert run(twin, "--cleanup")["cleanup_results"][0]["result"] == "deleted"


def test_cleanup_dirty_lane_keeps_history_and_operator_data(twin, tmp_path):
    root, spec, _ = twin
    other = tmp_path / "lane"
    git(root, "worktree", "add", "-q", str(other), "lane-a")
    spec["cleanup"] = {"branches": ["lane-a"]}
    run(twin, "--apply")
    (other / "owned.txt").write_text("operator work\n")
    failure = run(twin, "--cleanup", success=False)
    assert "dirty worktree" in failure.stderr
    assert (other / "owned.txt").read_text() == "operator work\n"
    assert git(root, "rev-parse", "lane-a") == spec["lanes"][0]["tip"]


def test_real_symlink_parent_is_refused(twin, tmp_path):
    root, spec, _ = twin
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked").symlink_to(outside)
    spec["lanes"][0]["owned_paths"].append("linked/leaf")
    failure = run(twin, "--apply", success=False)
    assert "symlink" in failure.stderr
    assert not list(outside.iterdir())


def test_changed_spec_cannot_replace_receipted_history(twin):
    root, spec, _ = twin
    run(twin)
    original = (root / spec["receipt"]).read_bytes()
    spec["lanes"][0]["owned_paths"].append("extra")
    assert "receipt/spec mismatch" in run(twin, "--apply", success=False).stderr
    assert (root / spec["receipt"]).read_bytes() == original


def test_untracked_ignored_collision_is_preserved(twin):
    root, spec, _ = twin
    git(root, "checkout", "-q", "lane-a")
    (root / "payload").write_text("reviewed\n")
    spec["lanes"][0]["tip"] = commit(root, "new file")
    spec["lanes"][0]["owned_paths"].append("payload")
    git(root, "checkout", "-q", "integration")
    with (root / ".git/info/exclude").open("a") as handle:
        handle.write("payload\n")
    (root / "payload").write_text("ignored operator payload\n")
    assert "untracked write collision" in run(twin, "--apply", success=False).stderr
    assert (root / "payload").read_text() == "ignored operator payload\n"


def test_mode_only_clobber_and_delete_clobber_are_not_ignored(twin):
    root, spec, _ = twin
    # Lane deletes delete.txt. A concurrent edit to it must refuse, even if content
    # on the other lane's executable-only change is otherwise identical.
    (root / "delete.txt").write_text("new integrated bytes\n")
    spec["integration"]["base"] = commit(root, "concurrent deletion target edit")
    assert "clobber" in run(twin, "--apply", success=False).stderr


def test_invalid_json_is_loud_without_mutation(twin):
    root, spec, path = twin
    path.write_text("{invalid")
    result = subprocess.run([sys.executable, str(SCRIPT), "--spec", str(path), "--task", "FIXTURE-1", "--check"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "land_twin_lanes:" in result.stderr
    assert "Traceback" not in result.stderr
    assert git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("value", [[None], {"bad": "shape"}])
def test_malformed_receipt_attempts_are_rejected_without_traceback(twin, value):
    root, spec, _ = twin
    run(twin)
    saved = receipt(twin)
    saved["attempts"] = value
    path = root / spec["receipt"]
    path.write_text(json.dumps(saved))
    before = path.read_bytes()
    result = run(twin, "--apply", success=False)
    assert "Traceback" not in result.stderr
    assert path.read_bytes() == before
    assert git(root, "rev-parse", "HEAD") == spec["integration"]["base"]


def test_overlapping_lanes_cannot_silently_clobber_each_other(twin):
    root, spec, _ = twin
    git(root, "checkout", "-qb", "lane-b", spec["integration"]["base"])
    (root / "owned.txt").write_text("other desired bytes\n")
    tip = commit(root, "overlapping lane")
    spec["lanes"].append({"id": "b", "branch": "lane-b", "base": spec["integration"]["base"],
                          "tip": tip, "owned_paths": ["owned.txt"]})
    git(root, "checkout", "-q", "integration")
    assert "clobber" in run(twin, "--check", success=False).stderr
    assert git(root, "rev-parse", "HEAD") == spec["integration"]["base"]


def test_check_rejects_merge_in_progress_without_mutation(twin):
    root, spec, _ = twin
    git(root, "merge", "-s", "ours", "--no-commit", "--no-ff", "lane-a")
    index = (root / ".git/index").read_bytes()
    assert "in-progress Git operation" in run(twin, "--check", success=False).stderr
    assert (root / ".git/index").read_bytes() == index
    assert (root / ".git/MERGE_HEAD").read_text().strip() == spec["lanes"][0]["tip"]
