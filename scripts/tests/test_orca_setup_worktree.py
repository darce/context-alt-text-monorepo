from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP = REPO_ROOT / "scripts/orca/setup_worktree.py"
ORCA_YAML = REPO_ROOT / "orca.yaml"

CANONICAL_ORCA_YAML = (
    "# WorkBay owns worktree creation and provisioning: docs/runbooks/orca-worktrees.md\n"
    "scripts:\n"
    '  setup: \'"$ORCA_ROOT_PATH/.venv/bin/python" "$ORCA_ROOT_PATH/scripts/orca/setup_worktree.py"\'\n'
    '  archive: \'"$ORCA_ROOT_PATH/.venv/bin/python" "$ORCA_ROOT_PATH/scripts/orca/archive_worktree.py"\'\n'
    "setupAgentStartupPolicy: wait-for-setup\n"
)

# Copied verbatim from contract C4; the stub stands in for the installed WorkBay package.
STUB_BRANCH_NAMING = (
    "import re\n"
    "\n"
    'TASK_REF_RE = re.compile(r"^feature/(?=[a-z])(?=[a-z0-9-]*\\d)(?P<task_ref>[a-z0-9]+(?:-[a-z0-9]+)+)$")\n'
)

STUB_MAKE = """\
import json
import os
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
record = {"argv": sys.argv[1:], "cwd": os.getcwd(), "env": dict(os.environ)}
(here / "make-record.json").write_text(json.dumps(record), encoding="utf-8")
sys.stdout.write((here / "make-stdout.txt").read_text(encoding="utf-8"))
sys.stdout.flush()
sys.stderr.write("stub make stderr line\\n")
raise SystemExit(int((here / "make-exit.txt").read_text(encoding="utf-8")))
"""

GOOD_RECEIPT = {
    "ok": True,
    "task_ref": "ORCA-77",
    "worktree_bootstrap": {"ran": True, "ok": True, "skipped": False, "exit": 0},
}


@dataclass(frozen=True)
class Fixture:
    root: Path
    feature_wt: Path
    darce_wt: Path
    detached_wt: Path
    foreign_wt: Path
    stubs: Path
    make_dir: Path

    @property
    def make(self) -> Path:
        return self.make_dir / "make"

    @property
    def record(self) -> Path:
        return self.make_dir / "make-record.json"

    def program_make(self, stdout: str, exit_code: int = 0) -> None:
        (self.make_dir / "make-stdout.txt").write_text(stdout, encoding="utf-8")
        (self.make_dir / "make-exit.txt").write_text(str(exit_code), encoding="utf-8")

    def recorded(self) -> dict:
        return json.loads(self.record.read_text(encoding="utf-8"))


def _hermetic_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("GIT_", "ORCA_"))}
    env.pop("PYTHONPATH", None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["LC_ALL"] = "C"
    return env


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], check=True, capture_output=True, text=True, env=_hermetic_env())
    return completed.stdout


def _init_repo(path: Path) -> None:
    _git("-c", "init.defaultBranch=main", "init", "-q", str(path))
    _git("-C", str(path), "config", "user.name", "Orca Setup Test")
    _git("-C", str(path), "config", "user.email", "orca-setup@example.invalid")
    _git("-C", str(path), "config", "commit.gpgsign", "false")
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    _git("-C", str(path), "add", "README.md")
    _git("-C", str(path), "commit", "-q", "-m", "init")


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    base = tmp_path.resolve()
    root = base / "primary"
    _init_repo(root)
    feature_wt = base / "wt-orca-77"
    darce_wt = base / "wt-darce-foo"
    detached_wt = base / "wt-detached"
    _git("-C", str(root), "worktree", "add", "-q", "-b", "feature/orca-77", str(feature_wt))
    _git("-C", str(root), "worktree", "add", "-q", "-b", "darce/foo", str(darce_wt))
    _git("-C", str(root), "worktree", "add", "-q", "--detach", str(detached_wt))

    other = base / "other"
    _init_repo(other)
    foreign_wt = base / "wt-foreign"
    _git("-C", str(other), "worktree", "add", "-q", "-b", "feature/orca-88", str(foreign_wt))

    stubs = base / "stubs"
    (stubs / "workbay_protocol").mkdir(parents=True)
    (stubs / "workbay_protocol/__init__.py").write_text("", encoding="utf-8")
    (stubs / "workbay_protocol/branch_naming.py").write_text(STUB_BRANCH_NAMING, encoding="utf-8")

    make_dir = base / "bin"
    make_dir.mkdir()
    (make_dir / "stub_make.py").write_text(STUB_MAKE, encoding="utf-8")
    make = make_dir / "make"
    make.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(make_dir / "stub_make.py"))} "$@"\n',
        encoding="utf-8",
    )
    make.chmod(0o755)
    fixture = Fixture(root, feature_wt, darce_wt, detached_wt, foreign_wt, stubs, make_dir)
    fixture.program_make(json.dumps(GOOD_RECEIPT) + "\n")
    return fixture


def _run(
    fx: Fixture,
    *extra: str,
    root: str | Path | None = None,
    worktree: str | Path | None = None,
    stub_protocol: bool = True,
    env_overrides: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = _hermetic_env()
    env["ORCA_ROOT_PATH"] = str(fx.root if root is None else root)
    env["ORCA_WORKTREE_PATH"] = str(fx.feature_wt if worktree is None else worktree)
    env["ORCA_WORKSPACE_NAME"] = "orca-77"
    if stub_protocol:
        env["PYTHONPATH"] = str(fx.stubs)
    for key, value in (env_overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    # -S keeps an installed workbay_protocol from leaking past the stub (or into the absent case).
    return subprocess.run(
        [sys.executable, "-S", str(SETUP), "--make", str(fx.make), *extra],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=fx.feature_wt,
        timeout=60,
    )


def _expected_argv(fx: Fixture) -> list[str]:
    return [
        "--no-print-directory",
        "-C",
        str(fx.root),
        "task-start",
        "TASK=ORCA-77",
        "MODE=claim",
        "LIFECYCLE_ARGS=--json",
    ]


def test_orca_yaml_is_the_canonical_text() -> None:
    assert ORCA_YAML.read_bytes() == CANONICAL_ORCA_YAML.encode("utf-8")


def test_orca_yaml_setup_command_names_this_script() -> None:
    line = next(raw for raw in ORCA_YAML.read_text(encoding="utf-8").splitlines() if raw.startswith("  setup: "))
    scalar = line.removeprefix("  setup: ")
    assert scalar.startswith("'") and scalar.endswith("'")
    words = shlex.split(scalar[1:-1].replace("$ORCA_ROOT_PATH", str(REPO_ROOT)))
    assert words == [str(REPO_ROOT / ".venv/bin/python"), str(SETUP)]


def test_success_runs_task_start_claim_with_exact_argv(fx: Fixture) -> None:
    completed = _run(
        fx,
        env_overrides={"MAKEFLAGS": "-j8 --jobserver-auth=3,4", "MAKELEVEL": "2", "MFLAGS": "-j8"},
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    record = fx.recorded()
    assert record["argv"] == _expected_argv(fx)
    assert not any(arg.startswith("OBJECTIVE=") for arg in record["argv"])
    assert Path(record["cwd"]).resolve() == fx.root
    for scrubbed in ("MAKEFLAGS", "MAKELEVEL", "MFLAGS"):
        assert scrubbed not in record["env"]
    assert record["env"]["ORCA_WORKTREE_PATH"] == str(fx.feature_wt)
    assert "stub make stderr line" in completed.stderr
    summary = [line for line in completed.stderr.splitlines() if line.startswith("setup_worktree:")]
    assert len(summary) == 1
    assert "orca-77" in summary[0]
    assert "feature/orca-77" in summary[0]
    assert str(fx.feature_wt) in summary[0]


def test_objective_is_appended_only_when_given(fx: Fixture) -> None:
    completed = _run(fx, "--objective", "Ship the Orca adapter (C4) & docs")

    assert completed.returncode == 0, completed.stderr
    assert fx.recorded()["argv"] == [*_expected_argv(fx), "OBJECTIVE=Ship the Orca adapter (C4) & docs"]


@pytest.mark.parametrize(
    "objective",
    ["it's broken", "line one\nline two", "tab\tseparated", "ansi \x1b[31mred", "del\x7f", ""],
)
def test_objective_unsafe_for_make_quoting_is_refused(fx: Fixture, objective: str) -> None:
    completed = _run(fx, "--objective", objective)

    assert completed.returncode == 2, completed.stderr
    assert "--objective" in completed.stderr
    assert not fx.record.exists()


@pytest.mark.parametrize("missing", ["ORCA_ROOT_PATH", "ORCA_WORKTREE_PATH"])
@pytest.mark.parametrize("value", [None, ""])
def test_missing_env_is_refused(fx: Fixture, missing: str, value: str | None) -> None:
    completed = _run(fx, env_overrides={missing: value})

    assert completed.returncode == 2, completed.stderr
    assert missing in completed.stderr
    assert not fx.record.exists()


@pytest.mark.parametrize("var", ["ORCA_ROOT_PATH", "ORCA_WORKTREE_PATH"])
def test_relative_env_is_refused(fx: Fixture, var: str) -> None:
    target = fx.root if var == "ORCA_ROOT_PATH" else fx.feature_wt
    relative = os.path.relpath(target, fx.feature_wt)
    completed = _run(fx, env_overrides={var: relative})

    assert completed.returncode == 2, completed.stderr
    assert var in completed.stderr
    assert "absolute" in completed.stderr
    assert not fx.record.exists()


@pytest.mark.parametrize("var", ["ORCA_ROOT_PATH", "ORCA_WORKTREE_PATH"])
def test_env_that_is_not_a_directory_is_refused(fx: Fixture, var: str) -> None:
    completed = _run(fx, env_overrides={var: str(fx.root / "README.md")})

    assert completed.returncode == 2, completed.stderr
    assert var in completed.stderr
    assert "directory" in completed.stderr
    assert not fx.record.exists()


def test_worktree_equal_to_root_is_refused(fx: Fixture) -> None:
    completed = _run(fx, worktree=fx.root)

    assert completed.returncode == 2, completed.stderr
    assert "primary checkout" in completed.stderr
    assert not fx.record.exists()


def test_worktree_symlink_resolving_to_root_is_refused(fx: Fixture, tmp_path: Path) -> None:
    alias = tmp_path / "alias-of-primary"
    alias.symlink_to(fx.root, target_is_directory=True)
    completed = _run(fx, worktree=alias)

    assert completed.returncode == 2, completed.stderr
    assert "primary checkout" in completed.stderr
    assert not fx.record.exists()


def test_worktree_of_another_repository_is_refused(fx: Fixture) -> None:
    completed = _run(fx, worktree=fx.foreign_wt)

    assert completed.returncode == 2, completed.stderr
    assert str(fx.root) in completed.stderr
    assert str((fx.root.parent / "other").resolve()) in completed.stderr
    assert not fx.record.exists()


def test_worktree_outside_git_is_refused(fx: Fixture, tmp_path: Path) -> None:
    plain = tmp_path / "plain-dir"
    plain.mkdir()
    completed = _run(fx, worktree=plain)

    assert completed.returncode == 2, completed.stderr
    assert "git" in completed.stderr
    assert not fx.record.exists()


def test_missing_workbay_protocol_is_refused(fx: Fixture) -> None:
    completed = _run(fx, stub_protocol=False)

    assert completed.returncode == 2, completed.stderr
    assert "workbay_protocol" in completed.stderr
    assert not fx.record.exists()


def test_detached_head_is_refused(fx: Fixture) -> None:
    completed = _run(fx, worktree=fx.detached_wt)

    assert completed.returncode == 1, completed.stderr
    assert "detached" in completed.stderr
    assert "feature/<task-ref>" in completed.stderr
    assert 'Custom "feature"' in completed.stderr
    assert not fx.record.exists()


def test_branch_outside_task_grammar_is_refused(fx: Fixture) -> None:
    completed = _run(fx, worktree=fx.darce_wt)

    assert completed.returncode == 1, completed.stderr
    assert "darce/foo" in completed.stderr
    assert "feature/<task-ref>" in completed.stderr
    assert "(?P<task_ref>" in completed.stderr
    assert 'branch prefix to Custom "feature"' in completed.stderr
    assert "auto-rename" in completed.stderr
    assert not fx.record.exists()


def test_receipt_is_the_last_json_object_line(fx: Fixture) -> None:
    noisy = "\n".join(
        [
            "make[1]: recipe chatter",
            json.dumps({"ok": False, "worktree_bootstrap": {"ok": False}}),
            "{not json",
            json.dumps(GOOD_RECEIPT),
            "trailing chatter",
            "[1, 2, 3]",
            "42",
            "",
        ]
    )
    fx.program_make(noisy)

    completed = _run(fx)

    assert completed.returncode == 0, completed.stderr


def test_earlier_good_receipt_does_not_mask_a_later_failure(fx: Fixture) -> None:
    later = {"ok": True, "worktree_bootstrap": {"ran": True, "ok": False, "skipped": False, "exit": 4}}
    fx.program_make(json.dumps(GOOD_RECEIPT) + "\nchatter\n" + json.dumps(later) + "\n")

    completed = _run(fx)

    assert completed.returncode == 3, completed.stderr


@pytest.mark.parametrize(
    ("stdout", "exit_code", "expect"),
    [
        (json.dumps(GOOD_RECEIPT) + "\n", 2, "exited 2"),
        ("make: *** [task-start] chatter only\n", 0, "no JSON receipt"),
        (json.dumps({**GOOD_RECEIPT, "ok": False}) + "\n", 0, '"ok"'),
        (json.dumps({**GOOD_RECEIPT, "ok": "true"}) + "\n", 0, '"ok"'),
        (json.dumps({"ok": True}) + "\n", 0, "worktree_bootstrap"),
        (json.dumps({"ok": True, "worktree_bootstrap": None}) + "\n", 0, "worktree_bootstrap"),
        (
            json.dumps({"ok": True, "worktree_bootstrap": {"ran": False, "ok": False, "skipped": True, "exit": None}})
            + "\n",
            0,
            "worktree_bootstrap",
        ),
        (
            json.dumps({"ok": True, "worktree_bootstrap": {"ran": True, "ok": False, "skipped": False, "exit": 4}})
            + "\n",
            0,
            "worktree_bootstrap",
        ),
    ],
    ids=[
        "make-nonzero",
        "no-json",
        "ok-false",
        "ok-not-bool",
        "bootstrap-missing",
        "bootstrap-null",
        "bootstrap-skipped",
        "bootstrap-failed",
    ],
)
def test_task_start_failure_is_exit_3(fx: Fixture, stdout: str, exit_code: int, expect: str) -> None:
    fx.program_make(stdout, exit_code)

    completed = _run(fx)

    assert completed.returncode == 3, completed.stderr
    assert expect in completed.stderr
    assert "TASK=ORCA-77" in completed.stderr
    assert completed.stdout == ""
    assert fx.recorded()["argv"] == _expected_argv(fx)


def test_unrunnable_make_is_exit_3(fx: Fixture, tmp_path: Path) -> None:
    env = _hermetic_env()
    env.update(
        ORCA_ROOT_PATH=str(fx.root),
        ORCA_WORKTREE_PATH=str(fx.feature_wt),
        PYTHONPATH=str(fx.stubs),
    )
    completed = subprocess.run(
        [sys.executable, "-S", str(SETUP), "--make", str(tmp_path / "no-such-make")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )

    assert completed.returncode == 3, completed.stderr
    assert "no-such-make" in completed.stderr
