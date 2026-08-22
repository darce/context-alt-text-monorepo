"""Pin the `make eval-*` surface to the real eval_harness CLIs (EVALSURF-1).

rg-006: a documented command that does not run as written is a bug. These
targets are the discoverable entry point `/scope` is meant to hand a feature
author, so a renamed module or a renamed flag must turn this file red rather
than surface at the operator's shell as `No module named ...`.

TEST-15 discrimination guards, deliberately shipped:

  * ``test_every_target_module_exists`` goes red if a harness module is
    renamed or moved.
  * ``test_every_emitted_flag_is_a_real_argparse_flag`` goes red if a flag is
    renamed upstream (e.g. ``--run-record`` -> ``--record``).
  * ``test_eval_list_advertises_every_eval_target`` goes red if someone adds
    an ``eval-*`` target without listing it, which is the exact failure mode
    this slice exists to fix.

Static, offline, no network, no inference: the assertions read `make -n`
output and module source, never the service.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALS_MK = REPO_ROOT / "mk" / "evals.mk"
SERVICE = REPO_ROOT / "apps" / "prototype-description-service"

# Placeholder values that satisfy each target's required-argument guard so
# `make -n` reaches the recipe body. Values are never dereferenced: -n prints.
TARGET_ARGS: dict[str, list[str]] = {
    "eval-score": ["RUN_RECORD=run.json"],
    "eval-face-calibrate": ["REPORT=report.json", "MANIFEST=golden.json", "OUT=cal.json"],
    "eval-fusion": [],
    "eval-report": ["RUN=baseline=run.json", "MANIFEST=golden.json", "OUT=report.html"],
    "eval-corpus-inventory": ["IMAGES=/tmp/images", "OUT=inv.jsonl"],
    "eval-strata": ["INVENTORY=celebs01=inv.jsonl", "OUT=shortlists.json"],
}

# Subcommand-carrying entry points: flags are declared in cli.py, not in a
# module of their own.
MODULE_FLAG_SOURCE: dict[str, str] = {
    "scripts.eval_harness.cli": "cli.py",
}


def _make_n(target: str, args: list[str]) -> str:
    env = {**os.environ}
    env.pop("EVAL_ARGS", None)
    result = subprocess.run(
        ["make", "-n", "-C", str(REPO_ROOT), target, *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, f"make -n {target} failed:\n{result.stderr}"
    return result.stdout


def _recipe_line(target: str) -> str:
    """The single `uv run python -m ...` line the target would execute."""
    logical_output = _make_n(target, TARGET_ARGS[target]).replace("\\\n", " ")
    for line in logical_output.splitlines():
        if "python -m scripts.eval_harness." in line:
            return line
    raise AssertionError(f"{target} emits no eval_harness invocation")


def _module_of(recipe: str) -> str:
    match = re.search(r"python -m (scripts\.eval_harness\.[\w.]+)", recipe)
    assert match, f"no module in recipe: {recipe}"
    return match.group(1)


def _module_source(module: str) -> Path:
    relative = MODULE_FLAG_SOURCE.get(module)
    if relative is None:
        relative = module.split(".")[-1] + ".py"
    return SERVICE / "scripts" / "eval_harness" / relative


@pytest.mark.parametrize("target", sorted(TARGET_ARGS))
def test_every_target_module_exists(target: str) -> None:
    module = _module_of(_recipe_line(target))
    source = _module_source(module)
    assert source.is_file(), f"{target} invokes {module}, but {source} does not exist"


@pytest.mark.parametrize("target", sorted(TARGET_ARGS))
def test_every_emitted_flag_is_a_real_argparse_flag(target: str) -> None:
    recipe = _recipe_line(target)
    module = _module_of(recipe)
    source_text = _module_source(module).read_text(encoding="utf-8")

    flags = sorted(set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", recipe)))
    assert flags or target == "eval-fusion", f"{target} emits no flags to pin"

    for flag in flags:
        declared = f'"{flag}"' in source_text or f"'{flag}'" in source_text
        assert declared, f"{target} passes {flag}, which {module} does not declare"


@pytest.mark.parametrize("target", sorted(TARGET_ARGS))
def test_required_arguments_are_guarded(target: str) -> None:
    """Omitting a required variable must fail with exit 2, not a broken run."""
    if not TARGET_ARGS[target]:
        pytest.skip(f"{target} has no required arguments")
    result = subprocess.run(
        ["make", "-C", str(REPO_ROOT), target],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, f"{target} ran with no required arguments"
    assert "is required" in result.stdout + result.stderr


def test_eval_list_advertises_every_eval_target() -> None:
    defined = set(re.findall(r"^(eval-[a-z-]+):", EVALS_MK.read_text(encoding="utf-8"), re.M))
    assert defined, "no eval-* targets found in mk/evals.mk"

    result = subprocess.run(
        ["make", "-C", str(REPO_ROOT), "eval-list"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    undiscoverable = {t for t in defined - {"eval-list"} if t not in result.stdout}
    assert not undiscoverable, f"eval-list does not advertise: {sorted(undiscoverable)}"


def test_eval_list_advertises_the_preexisting_root_targets() -> None:
    """eval-captions / bakeoff-face predate this file and live in the root
    Makefile; the discovery target is only useful if it names them too."""
    result = subprocess.run(
        ["make", "-C", str(REPO_ROOT), "eval-list"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for target in ("eval-captions", "bakeoff-face", "bakeoff-face-score"):
        assert target in result.stdout, f"eval-list omits pre-existing target {target}"


def test_test_scripts_collects_eval_target_contract() -> None:
    result = subprocess.run(
        ["make", "-n", "-C", str(REPO_ROOT), "test-scripts"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "scripts/test_make_eval_targets.py" in result.stdout, (
        "test-scripts does not collect scripts/test_make_eval_targets.py"
    )


def test_eval_report_requires_and_forwards_run() -> None:
    missing_run = subprocess.run(
        [
            "make",
            "-C",
            str(REPO_ROOT),
            "eval-report",
            "MANIFEST=golden.json",
            "OUT=report.html",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_run.returncode != 0, "eval-report ran without required RUN"
    assert "RUN is required" in missing_run.stdout + missing_run.stderr

    recipe = _recipe_line("eval-report")
    assert '--run "baseline=run.json"' in recipe, "eval-report does not forward RUN as --run"
