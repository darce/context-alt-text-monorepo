"""Smoke tests for scripts/remote_gate.sh local validation guards.

Every guard rejects BEFORE any ssh/push happens, so these run hermetically:
each case must exit 2 with its specific refusal on stderr. A bogus host is
exported so an accidental guard bypass fails on DNS instead of touching a
real host.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "remote_gate.sh"


def _run(args: list[str], extra_env: dict[str, str] | None = None, cwd: Path | None = None):
    env = os.environ.copy()
    env["WORKBAY_REMOTE_GATE_HOST"] = "gate@remote-gate-guard-test.invalid"
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=str(cwd or REPO_ROOT),
    )


def test_script_is_executable_and_parses() -> None:
    assert os.access(SCRIPT, os.X_OK)
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr


def _remote_command_string() -> str:
    # The `run)` case builds one long double-quoted string that is handed to
    # ssh. Everything between the preflight comment and the trailing `exit
    # \$overall` is expanded by the LOCAL shell before it is ever sent.
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("# Fail-closed repo preflight (GATE-BR-01)")
    end = text.index("exit \\$overall", start)
    return text[start:end]


def test_remote_command_string_has_no_backticks() -> None:
    # Backticks inside that double-quoted string are command substitution: they
    # run on the OPERATOR's machine at expansion time, not on the gate host.
    # A comment containing `gate-preflight` did exactly that (GATE1-BR-01) —
    # harmless only because no such local command existed. This is the same
    # hazard test_gate_env_metachars_refused rejects for operator-supplied env.
    assert "`" not in _remote_command_string()


def test_preflight_runs_before_any_gate_target() -> None:
    # A preflight that runs after the targets certifies nothing: the point is
    # that a workdir whose fixtures/weights are missing never reaches a suite
    # that would SKIP over them and report EXIT=0 (GATE-BR-01). Pin the order
    # and the abort, not just the presence.
    block = _remote_command_string()
    probe = block.index("make -n gate-preflight")
    # Anchor on the statement, not the prose: the rationale comment above the
    # probe also says "exit 73".
    abort_stmt = re.search(r"(?m)^\s+exit 73$", block)
    assert abort_stmt is not None, "no bare `exit 73` abort statement in the preflight block"
    loop = block.index("for t in ")
    assert probe < abort_stmt.start() < loop, (
        "gate-preflight must probe and abort before the target loop"
    )
    # Undeclared is logged, never silent — otherwise a workdir that simply
    # forgot the target looks identical to one that passed preflight.
    assert "no gate-preflight target" in block


def test_no_private_host_baked_in() -> None:
    # Assessment NG-5: the script must carry no concrete tailnet host — a
    # private address must never be a distributable default (fail-open leak).
    text = SCRIPT.read_text(encoding="utf-8")
    # Generic detectors, deliberately NOT naming any real host: no tailnet
    # domain, no IPv4 literal, no user@host-looking default may ship in the
    # script — the host must come only from operator-local config.
    assert ".ts.net" not in text
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text), "IPv4 literal baked into the script"
    assert not re.search(r"HOST:-[\x22\x27]?\w+@", text), "baked-in default ssh destination"


def test_unset_host_is_hard_error_no_fallback() -> None:
    # No baked default: an unconfigured caller must fail closed (exit 78),
    # never silently push HEAD to some fallback address. Guard against the
    # operator config file in the main checkout satisfying the host by
    # pointing HOME/config resolution at an isolated cwd-less repo.
    env = os.environ.copy()
    env.pop("WORKBAY_REMOTE_GATE_HOST", None)
    proc = subprocess.run(
        ["bash", str(SCRIPT), "doctor"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=str(REPO_ROOT),
    )
    config_file = _main_checkout_root() / ".workbay" / "remote-gate.env"
    if config_file.is_file() and "REMOTE_GATE_HOST" in config_file.read_text(encoding="utf-8"):
        pytest.skip("operator-local .workbay/remote-gate.env sets a host; unset-host path not testable here")
    assert proc.returncode == 78
    assert "host not configured" in proc.stderr


def _main_checkout_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
        check=True,
    ).stdout.strip()
    return Path(out).parent


@pytest.mark.parametrize(
    "target",
    ["check;evil", "a b", "$(id)", "x&&y", "../up"],
)
def test_unsafe_target_names_refused(target: str) -> None:
    proc = _run(["run", target])
    assert proc.returncode == 2
    assert "refusing target with unsafe characters" in proc.stderr


@pytest.mark.parametrize(
    "remote_dir,message",
    # NOTE: empty values are not testable via env — the script's `${VAR:-default}`
    # resolution swallows empty into the default before validation runs; the
    # empty/"." arms of the guard are unreachable defense-in-depth.
    [
        (".", "invalid REMOTE_DIR"),
        ("/abs/context-alt-text-monorepo", "invalid REMOTE_DIR"),
        ("src/../context-alt-text-monorepo", "invalid REMOTE_DIR"),
        ("src/other-repo", "must end with the repo slug"),
    ],
)
def test_remote_dir_validation(remote_dir: str, message: str) -> None:
    proc = _run(["run"], extra_env={"WORKBAY_REMOTE_GATE_DIR": remote_dir})
    assert proc.returncode == 2
    assert message in proc.stderr


@pytest.mark.parametrize("workdir", ["/abs", "up/../.."])
def test_workdir_validation(workdir: str) -> None:
    proc = _run(["run"], extra_env={"WORKBAY_REMOTE_GATE_WORKDIR": workdir})
    assert proc.returncode == 2
    assert "invalid REMOTE_GATE_WORKDIR" in proc.stderr


def test_remote_dir_charset_validation() -> None:
    proc = _run(["run"], extra_env={"WORKBAY_REMOTE_GATE_DIR": "src/$x/context-alt-text-monorepo"})
    assert proc.returncode == 2
    assert "characters outside" in proc.stderr


@pytest.mark.parametrize(
    "env_key,env_value,message",
    [
        ("WORKBAY_REMOTE_GATE_NICE", "abc", "must be an integer"),
        ("WORKBAY_REMOTE_GATE_NICE", "1x", "must be an integer"),
        ("PYTEST_WORKERS", "two", "must be an integer"),
        ("WORKBAY_REMOTE_GATE_MEMORY_MAX", "6Gigs", "must look like 6G/512M"),
        ("WORKBAY_REMOTE_GATE_CPU_QUOTA", "fast", "must look like 200%"),
    ],
)
def test_numeric_shape_validation(env_key: str, env_value: str, message: str) -> None:
    proc = _run(["run"], extra_env={env_key: env_value})
    assert proc.returncode == 2
    assert message in proc.stderr


@pytest.mark.parametrize(
    "entry",
    [
        "KEY=$(id)",
        "KEY=a;b",
        "KEY=a|b",
        "KEY=a&b",
        "KEY=a`b`",
        "KEY=a>b",
        "KEY=a<b",
        "KEY=a\\b",
    ],
)
def test_gate_env_metachars_refused(entry: str) -> None:
    proc = _run(["run"], extra_env={"WORKBAY_REMOTE_GATE_ENV": entry})
    assert proc.returncode == 2
    assert "shell metacharacters" in proc.stderr


def test_gate_env_requires_key_value_shape() -> None:
    proc = _run(["run"], extra_env={"WORKBAY_REMOTE_GATE_ENV": "not-an-assignment"})
    assert proc.returncode == 2
    assert "must be KEY=VALUE" in proc.stderr


def test_env_overrides_config_file(tmp_path: Path) -> None:
    # Layer precedence: caller env is captured before the config file is
    # sourced, so a file host must never beat an explicit env host. Proven
    # via a guard that only fires on the env value: an invalid env REMOTE_DIR
    # must be rejected even when the file sets a valid one.
    repo = tmp_path / "context-alt-text-monorepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, timeout=30)
    workbay = repo / ".workbay"
    workbay.mkdir()
    (workbay / "remote-gate.env").write_text(
        'REMOTE_GATE_DIR="src/context-alt-text-monorepo"\n', encoding="utf-8"
    )
    script_copy = repo / "remote_gate.sh"
    script_copy.write_bytes(SCRIPT.read_bytes())
    env = os.environ.copy()
    env["WORKBAY_REMOTE_GATE_HOST"] = "gate@remote-gate-guard-test.invalid"
    env["WORKBAY_REMOTE_GATE_DIR"] = "src/other-repo"
    proc = subprocess.run(
        ["bash", str(script_copy), "run"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=str(repo),
    )
    assert proc.returncode == 2
    assert "must end with the repo slug" in proc.stderr
