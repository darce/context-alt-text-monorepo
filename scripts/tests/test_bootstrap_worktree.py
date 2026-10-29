from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "scripts/workstate/bootstrap_worktree.py"
PROVISIONER = REPO_ROOT / "scripts/workstate/provision_lane_worktree.py"
CONTRACT_REL = "docs/workbay/contracts/harness-protocol.yaml"
KEY_PATH = "bootstrap_overlay.tracked_vs_overlay_boundary.overlay_managed_prefixes"
PREFIXES = [
    "scripts/hooks/",
    "docs/workbay/contracts/",
    "docs/workbay/rules/",
    "Makefile.d/",
    "scripts/workbay/",
    ".github/hooks/",
    ".github/prompts/",
    ".workbay/generated/plugins/workbay-system/",
    ".mcp.json",
    ".vscode/mcp.json",
    ".codex/config.toml",
]
SCRUBBED_MAKE_ENV = ("MAKEFLAGS", "MAKELEVEL", "MFLAGS")
SENTINEL_ENV = "BOOTSTRAP_TEST_SENTINEL"

# The lane test env has no pyyaml and the bootstrap runs under -S, so this
# stub is the only yaml it can import. JSON fixtures are valid YAML.
YAML_STUB = """\
import json


class YAMLError(Exception):
    pass


def safe_load(stream):
    text = stream if isinstance(stream, str) else stream.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise YAMLError(str(exc)) from exc
"""

STUB_PROVISIONER_BODY = """
import json
import os
import sys
from pathlib import Path

argv = sys.argv[1:]
worktree = Path(argv[argv.index("--worktree") + 1])
venv = worktree / ".venv"
record = {
    "argv": argv,
    "venv_is_symlink": venv.is_symlink(),
    "venv_target": os.readlink(venv) if venv.is_symlink() else None,
    "literature_present": (worktree / "literature").exists(),
}
with open(LOG, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\\n")
print("provisioner stdout noise")
print("provisioner stderr marker", file=sys.stderr)
raise SystemExit(EXIT)
"""

STUB_MAKE_BODY = """
import json
import os
import sys
import time

argv = sys.argv[1:]
record = {
    "argv": argv,
    "cwd": os.getcwd(),
    "env": {name: os.environ.get(name) for name in ENV_NAMES},
}
with open(LOG, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\\n")
target = argv[-1]
print(f"echo dry-run {target}")
if SLEEP:
    time.sleep(SLEEP)
if target == FAIL_TARGET:
    print("make: earlier noise", file=sys.stderr)
    print(f"make: *** No rule to make target '{target}'.  Stop.", file=sys.stderr)
    raise SystemExit(2)
"""


@dataclass
class Fixture:
    root: Path
    primary: Path
    worktree: Path
    env: dict[str, str]
    yaml_stub_dir: Path
    no_yaml_dir: Path
    provisioner: Path
    provisioner_log: Path
    make: Path
    make_log: Path

    def seams(self) -> list[str]:
        return ["--provisioner", str(self.provisioner), "--make", str(self.make)]

    def provisioner_calls(self) -> list[dict[str, object]]:
        return _read_log(self.provisioner_log)

    def make_calls(self) -> list[dict[str, object]]:
        return _read_log(self.make_log)


def _read_log(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _git(cwd: Path, env: dict[str, str], *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout


def _write_contract(primary: Path, payload: object) -> None:
    contract = primary / CONTRACT_REL
    contract.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    contract.write_text(text, encoding="utf-8")


def _contract(prefixes: object) -> dict[str, object]:
    return {
        "version": 1,
        "bootstrap_overlay": {"tracked_vs_overlay_boundary": {"overlay_managed_prefixes": prefixes}},
    }


def write_stub_provisioner(fx: Fixture, *, exit_code: int = 0) -> None:
    header = f"LOG = {str(fx.provisioner_log)!r}\nEXIT = {exit_code}\n"
    fx.provisioner.write_text(header + STUB_PROVISIONER_BODY, encoding="utf-8")


def write_stub_make(fx: Fixture, *, fail_target: str | None = None, sleep: float = 0) -> None:
    recorder = fx.make.with_name("make_recorder.py")
    header = (
        f"LOG = {str(fx.make_log)!r}\n"
        f"FAIL_TARGET = {fail_target!r}\n"
        f"SLEEP = {sleep!r}\n"
        f"ENV_NAMES = {(*SCRUBBED_MAKE_ENV, SENTINEL_ENV)!r}\n"
    )
    recorder.write_text(header + STUB_MAKE_BODY, encoding="utf-8")
    # A /bin/sh wrapper keeps the shebang short; exec so a timeout kill
    # reaches the recorder itself.
    fx.make.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(recorder))} "$@"\n',
        encoding="utf-8",
    )
    fx.make.chmod(0o755)


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    root = tmp_path.resolve()
    home = root / "home"
    home.mkdir()
    gitconfig = home / ".gitconfig"
    gitconfig.write_text("", encoding="utf-8")
    yaml_stub_dir = root / "yaml-stub"
    yaml_stub_dir.mkdir()
    (yaml_stub_dir / "yaml.py").write_text(YAML_STUB, encoding="utf-8")
    no_yaml_dir = root / "no-yaml"
    no_yaml_dir.mkdir()

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_") and key not in SCRUBBED_MAKE_ENV and key != "PYTHONPATH"
    }
    env.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": str(gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONPATH": str(yaml_stub_dir),
        }
    )

    primary = root / "primary"
    worktree = root / "wt"
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "-q", str(primary)],
        check=True,
        capture_output=True,
        env=env,
    )
    _git(primary, env, "config", "user.name", "Bootstrap Test")
    _git(primary, env, "config", "user.email", "bootstrap-test@example.invalid")
    _git(primary, env, "config", "init.defaultBranch", "main")
    (primary / ".gitignore").write_text(".venv\n", encoding="utf-8")
    (primary / "literature").mkdir()
    (primary / "literature/README.md").write_text("literature\n", encoding="utf-8")
    (primary / "src").mkdir()
    (primary / "src/app.txt").write_text("app\n", encoding="utf-8")
    _git(primary, env, "add", "-A")
    _git(primary, env, "commit", "-q", "-m", "fixture")
    _git(primary, env, "worktree", "add", "-q", str(worktree), "-b", "feature/orca-9")
    (primary / ".venv/bin").mkdir(parents=True)
    (primary / ".venv/pyvenv.cfg").write_text("home = fixture\n", encoding="utf-8")
    _write_contract(primary, _contract(PREFIXES))

    stubs = root / "stubs"
    stubs.mkdir()
    fixture = Fixture(
        root=root,
        primary=primary,
        worktree=worktree,
        env=env,
        yaml_stub_dir=yaml_stub_dir,
        no_yaml_dir=no_yaml_dir,
        provisioner=stubs / "provisioner.py",
        provisioner_log=root / "provisioner.log",
        make=stubs / "make",
        make_log=root / "make.log",
    )
    write_stub_provisioner(fixture)
    write_stub_make(fixture)
    return fixture


def run_bootstrap(
    fx: Fixture,
    *args: str,
    cwd: Path | None = None,
    yaml_stub: bool = True,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(fx.env)
    if not yaml_stub:
        env["PYTHONPATH"] = str(fx.no_yaml_dir)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-S", str(BOOTSTRAP), *args],
        cwd=cwd or fx.worktree,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _receipt(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert len(lines) == 1, completed.stdout
    payload = json.loads(lines[0])
    assert isinstance(payload, dict)
    return payload


def _load_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("bootstrap_worktree_under_test", BOOTSTRAP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sparse_enabled(worktree: Path, env: dict[str, str]) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(worktree), "config", "--bool", "core.sparseCheckout"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return completed.stdout.strip() == "true"


def test_success_prints_exactly_one_json_receipt_using_default_worktree_and_primary(fx: Fixture) -> None:
    completed = run_bootstrap(fx, *fx.seams(), cwd=fx.worktree)

    assert _receipt(completed) == {
        "ok": True,
        "worktree": str(fx.worktree),
        "primary": str(fx.primary),
        "overlay_paths": PREFIXES,
        "venv": "linked",
        "sparse": "applied",
        "postconditions": ["context", "slice-commit"],
    }
    assert "provisioner stdout noise" in completed.stderr
    assert "provisioner stderr marker" in completed.stderr
    assert "dry-run" not in completed.stdout


@pytest.mark.parametrize("explicit_primary", [False, True], ids=["default-primary", "explicit-primary"])
def test_refuses_to_bootstrap_the_primary_checkout(fx: Fixture, explicit_primary: bool) -> None:
    args = ["--worktree", str(fx.primary)]
    if explicit_primary:
        args += ["--primary", str(fx.primary)]
    completed = run_bootstrap(fx, *args, *fx.seams(), cwd=fx.primary)

    assert completed.returncode == 2, completed.stderr
    assert "refusing to bootstrap the primary checkout" in completed.stderr
    assert completed.stdout == ""
    assert fx.provisioner_calls() == []
    assert fx.make_calls() == []
    assert not _sparse_enabled(fx.primary, fx.env)


def test_refuses_when_explicit_primary_is_the_worktree(fx: Fixture) -> None:
    completed = run_bootstrap(fx, "--worktree", str(fx.worktree), "--primary", str(fx.worktree), *fx.seams())

    assert completed.returncode == 2, completed.stderr
    assert "refusing to bootstrap the primary checkout" in completed.stderr
    assert not (fx.worktree / ".venv").is_symlink()
    assert fx.provisioner_calls() == []


def test_refuses_a_path_below_the_worktree_top(fx: Fixture) -> None:
    completed = run_bootstrap(fx, "--worktree", str(fx.worktree / "src"), *fx.seams())

    assert completed.returncode == 2, completed.stderr
    assert "top" in completed.stderr
    assert not (fx.worktree / "src/.venv").exists()
    assert fx.provisioner_calls() == []


def test_refuses_a_missing_worktree(fx: Fixture) -> None:
    completed = run_bootstrap(fx, "--worktree", str(fx.root / "absent"), *fx.seams(), cwd=fx.root)

    assert completed.returncode == 2, completed.stderr
    assert str(fx.root / "absent") in completed.stderr
    assert fx.provisioner_calls() == []


def test_links_venv_before_the_provisioner_runs(fx: Fixture) -> None:
    completed = run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams())

    receipt = _receipt(completed)
    assert receipt["venv"] == "linked"
    venv = fx.worktree / ".venv"
    assert venv.is_symlink()
    assert venv.resolve() == (fx.primary / ".venv").resolve()
    [call] = fx.provisioner_calls()
    assert call["venv_is_symlink"] is True
    assert call["venv_target"] == str(fx.primary / ".venv")


@pytest.mark.parametrize("kind", ["directory", "dangling-symlink"])
def test_existing_worktree_venv_is_left_untouched(fx: Fixture, kind: str) -> None:
    venv = fx.worktree / ".venv"
    if kind == "directory":
        venv.mkdir()
        (venv / "marker").write_text("lane venv\n", encoding="utf-8")
    else:
        venv.symlink_to(fx.root / "gone-venv")

    receipt = _receipt(run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams()))

    assert receipt["venv"] == "present"
    if kind == "directory":
        assert not venv.is_symlink()
        assert (venv / "marker").read_text(encoding="utf-8") == "lane venv\n"
    else:
        assert os.readlink(venv) == str(fx.root / "gone-venv")


def test_venv_absent_when_primary_has_none(fx: Fixture) -> None:
    (fx.primary / ".venv/pyvenv.cfg").unlink()
    (fx.primary / ".venv/bin").rmdir()
    (fx.primary / ".venv").rmdir()

    receipt = _receipt(run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams()))

    assert receipt["venv"] == "absent"
    venv = fx.worktree / ".venv"
    assert not venv.exists() and not venv.is_symlink()


def test_missing_contract_refuses_with_key_path(fx: Fixture) -> None:
    (fx.primary / CONTRACT_REL).unlink()

    completed = run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams())

    assert completed.returncode == 2, completed.stderr
    assert KEY_PATH in completed.stderr
    assert str(fx.primary / CONTRACT_REL) in completed.stderr
    assert completed.stdout == ""
    assert fx.provisioner_calls() == []
    assert fx.make_calls() == []


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("{not json", id="unparseable"),
        pytest.param(["not", "a", "mapping"], id="top-level-list"),
        pytest.param({"version": 1}, id="missing-bootstrap_overlay"),
        pytest.param({"bootstrap_overlay": {}}, id="missing-boundary"),
        pytest.param({"bootstrap_overlay": {"tracked_vs_overlay_boundary": {}}}, id="missing-prefixes"),
        pytest.param({"bootstrap_overlay": ["not-a-mapping"]}, id="bootstrap_overlay-not-mapping"),
        pytest.param(_contract([]), id="empty-list"),
        pytest.param(_contract("Makefile.d/"), id="string-not-list"),
        pytest.param(_contract(["Makefile.d/", 7]), id="non-string-item"),
        pytest.param(_contract(["Makefile.d/", ""]), id="empty-string-item"),
        pytest.param(_contract(["Makefile.d/", "   "]), id="blank-string-item"),
        pytest.param(_contract(None), id="null"),
    ],
)
def test_malformed_contract_refuses_with_key_path(fx: Fixture, payload: object) -> None:
    _write_contract(fx.primary, payload)

    completed = run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams())

    assert completed.returncode == 2, completed.stderr
    assert KEY_PATH in completed.stderr
    assert completed.stdout == ""
    assert fx.provisioner_calls() == []
    assert fx.make_calls() == []


def test_missing_pyyaml_refuses_with_key_path(fx: Fixture) -> None:
    completed = run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams(), yaml_stub=False)

    assert completed.returncode == 2, completed.stderr
    assert "pyyaml" in completed.stderr.lower()
    assert KEY_PATH in completed.stderr
    assert completed.stdout == ""
    assert fx.provisioner_calls() == []


def test_provisioner_receives_one_overlay_path_per_prefix_in_order(fx: Fixture) -> None:
    prefixes = ["Makefile.d/", ".mcp.json", "scripts/hooks/"]
    _write_contract(fx.primary, _contract(prefixes))

    receipt = _receipt(run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams()))

    [call] = fx.provisioner_calls()
    expected = ["--worktree", str(fx.worktree), "--primary", str(fx.primary)]
    for prefix in prefixes:
        expected += ["--overlay-path", prefix]
    assert call["argv"] == expected
    assert receipt["overlay_paths"] == prefixes


def test_provisioner_receives_the_full_contract_prefix_list(fx: Fixture) -> None:
    _receipt(run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams()))

    [call] = fx.provisioner_calls()
    argv = call["argv"]
    assert isinstance(argv, list)
    overlay_values = [argv[index + 1] for index, token in enumerate(argv) if token == "--overlay-path"]
    assert overlay_values == PREFIXES


def test_provisioner_failure_maps_to_exit_3_with_stderr_passthrough(fx: Fixture) -> None:
    write_stub_provisioner(fx, exit_code=1)

    completed = run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams())

    assert completed.returncode == 3, completed.stderr
    assert "provisioner stderr marker" in completed.stderr
    assert completed.stdout == ""
    assert fx.make_calls() == []
    assert not _sparse_enabled(fx.worktree, fx.env)


def test_sparse_applied_when_not_sparse_and_literature_clean(fx: Fixture) -> None:
    receipt = _receipt(run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams()))

    assert receipt["sparse"] == "applied"
    assert _sparse_enabled(fx.worktree, fx.env)
    assert not (fx.worktree / "literature").exists()
    assert (fx.worktree / "src/app.txt").exists()
    patterns = _git(fx.worktree, fx.env, "sparse-checkout", "list").splitlines()
    assert patterns == ["/*", "!/literature/"]
    [call] = fx.provisioner_calls()
    assert call["literature_present"] is True, "sparse must run after the provisioner"
    assert (fx.primary / "literature/README.md").exists()
    assert not _sparse_enabled(fx.primary, fx.env)


def test_no_sparse_disables_the_sparse_step(fx: Fixture) -> None:
    receipt = _receipt(run_bootstrap(fx, "--worktree", str(fx.worktree), "--no-sparse", *fx.seams()))

    assert receipt["sparse"] == "disabled"
    assert not _sparse_enabled(fx.worktree, fx.env)
    assert (fx.worktree / "literature/README.md").exists()


@pytest.mark.parametrize("change", ["modified", "untracked"])
def test_dirty_literature_skips_sparse_with_note(fx: Fixture, change: str) -> None:
    if change == "modified":
        (fx.worktree / "literature/README.md").write_text("edited\n", encoding="utf-8")
    else:
        (fx.worktree / "literature/notes.md").write_text("new\n", encoding="utf-8")

    completed = run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams())

    receipt = _receipt(completed)
    assert receipt["sparse"] == "skipped:literature-dirty"
    assert "literature" in completed.stderr
    assert not _sparse_enabled(fx.worktree, fx.env)
    assert (fx.worktree / "literature/README.md").exists()


def test_already_sparse_worktree_is_left_alone(fx: Fixture) -> None:
    _git(fx.worktree, fx.env, "sparse-checkout", "set", "--no-cone", "/*")

    completed = run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams())

    assert _receipt(completed)["sparse"] == "already"
    assert _git(fx.worktree, fx.env, "sparse-checkout", "list").splitlines() == ["/*"]
    assert (fx.worktree / "literature/README.md").exists()


def test_missing_literature_skips_sparse_with_note(fx: Fixture) -> None:
    (fx.worktree / "literature/README.md").unlink()
    (fx.worktree / "literature").rmdir()

    completed = run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams())

    assert _receipt(completed)["sparse"] == "skipped:literature-absent"
    assert "literature" in completed.stderr
    assert not _sparse_enabled(fx.worktree, fx.env)


def test_failing_sparse_command_maps_to_exit_3(fx: Fixture) -> None:
    git_dir = Path(_git(fx.worktree, fx.env, "rev-parse", "--absolute-git-dir").strip())
    # A held index lock leaves `git status` working but makes the sparse
    # checkout's index rewrite fail.
    (git_dir / "index.lock").write_text("", encoding="utf-8")

    completed = run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams())

    assert completed.returncode == 3, completed.stderr
    assert "sparse-checkout" in completed.stderr
    assert "index.lock" in completed.stderr
    assert completed.stdout == ""
    assert fx.make_calls() == []


def test_make_postconditions_run_in_order_with_make_env_scrubbed(fx: Fixture) -> None:
    completed = run_bootstrap(
        fx,
        "--worktree",
        str(fx.worktree),
        *fx.seams(),
        extra_env={
            "MAKEFLAGS": "n --no-print-directory -- TASK=PARENT",
            "MAKELEVEL": "1",
            "MFLAGS": "-n",
            SENTINEL_ENV: "kept",
        },
    )

    _receipt(completed)
    calls = fx.make_calls()
    assert [call["argv"] for call in calls] == [
        ["--no-print-directory", "-C", str(fx.worktree), "-n", "context"],
        ["--no-print-directory", "-C", str(fx.worktree), "-n", "slice-commit"],
    ]
    for call in calls:
        assert call["env"] == {"MAKEFLAGS": None, "MAKELEVEL": None, "MFLAGS": None, SENTINEL_ENV: "kept"}


@pytest.mark.parametrize(
    ("fail_target", "expected_calls"),
    [("context", ["context"]), ("slice-commit", ["context", "slice-commit"])],
)
def test_make_postcondition_failure_maps_to_exit_4(fx: Fixture, fail_target: str, expected_calls: list[str]) -> None:
    write_stub_make(fx, fail_target=fail_target)

    completed = run_bootstrap(fx, "--worktree", str(fx.worktree), *fx.seams())

    assert completed.returncode == 4, completed.stderr
    assert f"-n {fail_target}" in completed.stderr
    assert f"No rule to make target '{fail_target}'" in completed.stderr
    assert completed.stdout == ""
    assert [call["argv"][-1] for call in fx.make_calls()] == expected_calls


def test_missing_make_maps_to_exit_4(fx: Fixture) -> None:
    completed = run_bootstrap(
        fx,
        "--worktree",
        str(fx.worktree),
        "--provisioner",
        str(fx.provisioner),
        "--make",
        str(fx.root / "no-make"),
    )

    assert completed.returncode == 4, completed.stderr
    assert "-n context" in completed.stderr
    assert completed.stdout == ""
    assert len(fx.provisioner_calls()) == 1


def test_make_postcondition_timeout_maps_to_exit_4(
    fx: Fixture, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    write_stub_make(fx, sleep=30)
    module = _load_module()
    monkeypatch.setattr(module, "POSTCONDITION_TIMEOUT_S", 1)
    yaml_stub = types.ModuleType("yaml")
    exec(YAML_STUB, yaml_stub.__dict__)
    monkeypatch.setitem(sys.modules, "yaml", yaml_stub)
    for key in list(os.environ):
        if key not in fx.env:
            monkeypatch.delenv(key)
    for key, value in fx.env.items():
        monkeypatch.setenv(key, value)

    code = module.main(["--worktree", str(fx.worktree), "--no-sparse", *fx.seams()])

    captured = capfd.readouterr()
    assert code == 4, captured.err
    assert "timed out" in captured.err
    assert "-n context" in captured.err
    assert captured.out == ""
    assert [call["argv"][-1] for call in fx.make_calls()] == ["context"]


def test_default_seams_point_at_the_sibling_provisioner_and_make() -> None:
    module = _load_module()

    args = module.build_parser().parse_args([])

    assert Path(args.provisioner).resolve() == PROVISIONER.resolve()
    assert args.make == "make"
    assert args.primary is None
    assert args.no_sparse is False


def test_help_hides_the_test_seams(fx: Fixture) -> None:
    completed = run_bootstrap(fx, "--help")

    assert completed.returncode == 0, completed.stderr
    assert "--no-sparse" in completed.stdout
    assert "--provisioner" not in completed.stdout
    assert "--make" not in completed.stdout
