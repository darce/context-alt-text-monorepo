from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# plan-accept lives on the tracked mk/ surface, never inside Makefile.d/: that
# directory is a gitignored, bootstrap-materialized plugin overlay and Git
# silently overwrites ignored untracked files on merge.
LIFECYCLE_MK = REPO_ROOT / "mk" / "lane-lifecycle.mk"
TRACKED_HANDLER = "scripts/workstate/lifecycle/handlers/plan_baseline.py"


def _overlay_ignore_probe(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-v", "Makefile.d"],
        capture_output=True,
        text=True,
        check=False,
    )


def _recipe_for(path: Path, target: str) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith(f"{target}:")), None)
    assert start is not None, f"missing target {target} in {path}"
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("\t"):
            body.append(line[1:])
            continue
        if not line.strip():
            continue
        break
    recipe = "\n".join(body)
    assert recipe, f"target {target} in {path} has no recipe"
    return recipe


def test_plan_accept_recipe_names_tracked_handler() -> None:
    contents = LIFECYCLE_MK.read_text(encoding="utf-8")
    body = _recipe_for(LIFECYCLE_MK, "plan-accept")
    assert "ACX_LIFECYCLE_HANDLERS ?= scripts/workstate/lifecycle/handlers" in contents
    assert ".PHONY: plan-accept" in contents
    assert TRACKED_HANDLER in body.replace("$(ACX_LIFECYCLE_HANDLERS)", "scripts/workstate/lifecycle/handlers")
    assert '--task "$(TASK)"' in body
    assert '$(if $(PLAN),--plan "$(PLAN)",)' in body
    assert "workbay_lifecycle" not in body


def test_plan_accept_dry_run_names_tracked_handler() -> None:
    completed = subprocess.run(
        ["make", "-n", "-f", str(LIFECYCLE_MK), "plan-accept", "TASK=ISSUEDAG-1"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert TRACKED_HANDLER in combined
    assert "workbay_lifecycle" not in combined


def test_plugin_managed_overlay_dir_stays_untracked_and_ignored() -> None:
    """Regression guard: a tracked file under Makefile.d/ lets `git merge`
    silently clobber the operator's untracked, gitignored plugin overlay, which
    is the only definition of context/task-start/task-finish/wb and friends."""
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "Makefile.d/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert "Makefile.d/lifecycle.mk" not in tracked, (
        "Makefile.d/lifecycle.mk must not be tracked; define plan-accept in mk/lane-lifecycle.mk"
    )

    ignore_rules = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/Makefile.d" in ignore_rules
    assert not [line for line in ignore_rules if line.startswith("!/Makefile.d")], (
        "no Makefile.d/ path may be un-ignored; the whole directory is plugin-managed"
    )

    check_ignore = _overlay_ignore_probe(REPO_ROOT)
    assert check_ignore.returncode == 0, check_ignore.stdout or check_ignore.stderr
    assert "/Makefile.d" in check_ignore.stdout


def test_overlay_ignore_probe_holds_when_overlay_is_a_symlink(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, text=True, check=True)

    ignore_rule = next(
        line for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line == "/Makefile.d"
    )
    (repo / ".gitignore").write_text(f"{ignore_rule}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], capture_output=True, text=True, check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "add overlay ignore rule",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "lifecycle.mk").write_text("# plugin overlay\n", encoding="utf-8")
    (repo / "Makefile.d").symlink_to(overlay, target_is_directory=True)

    check_ignore = _overlay_ignore_probe(repo)
    assert check_ignore.returncode == 0, check_ignore.stdout or check_ignore.stderr
    assert "/Makefile.d" in check_ignore.stdout

    old_probe = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "-v", "Makefile.d/lifecycle.mk"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert old_probe.returncode != 0


def test_no_tracked_overlay_fragment_defines_plan_accept() -> None:
    """Untracked overlay content belongs to the operator's plugin install; what
    the branch must never do is ship a plan-accept definition from inside the
    plugin-managed directory."""
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "Makefile.d/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    for rel in tracked:
        contents = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        assert "\nplan-accept:" not in f"\n{contents}", (
            f"{rel} defines plan-accept; it belongs in mk/lane-lifecycle.mk"
        )
