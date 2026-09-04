"""Every tracked shell script must parse under the *system* bash (OCIRV-1).

macOS ships bash 3.2 (the last GPLv2 release) and will not move off it. Deploy
hosts run bash 5. That split hides a real class of breakage: bash 3.2's
command-substitution parser miscounts the `)` that closes a `case` pattern
nested inside `$( )` and aborts with

    syntax error near unexpected token `;;'

Two gate libraries carried exactly that shape. Both parsed on the VM, so review
and remote CI saw nothing, while `make test-deploy-contract` and `make check-all`
were hard-red on every macOS laptop -- the one place those gates are actually
exercised before a deploy. The fix is a leading `(` on the pattern.

[rg-006] a documented command must run as written. A gate that cannot be parsed
locally is not a gate.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_BASH = "/bin/bash"
BASH_32_ENV = "BASH_3_2"


def _bash_version(bash: str) -> str:
    return subprocess.run(
        [bash, "-c", 'printf "%s" "$BASH_VERSION"'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _tracked_shell_scripts():
    out = subprocess.run(
        ["git", "ls-files", "*.sh"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(out)


@pytest.mark.skipif(not Path(SYSTEM_BASH).exists(), reason="no /bin/bash on this platform")
@pytest.mark.parametrize("rel_path", _tracked_shell_scripts())
def test_script_parses_under_system_bash(rel_path):
    result = subprocess.run(
        [SYSTEM_BASH, "-n", rel_path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    version = _bash_version(SYSTEM_BASH)
    assert result.returncode == 0, (
        f"{rel_path} does not parse under {SYSTEM_BASH} {version}:\n"
        f"{result.stderr}\n"
        "If this is a `case` inside $( ), prefix the pattern with `(`."
    )


def test_the_guard_would_catch_the_shape_that_broke(tmp_path):
    # [TEST-15] Prove the assertion can fail: the exact construct that shipped.
    requested_bash = os.environ.get(BASH_32_ENV, SYSTEM_BASH)
    bash_32 = shutil.which(requested_bash)
    if bash_32 is None:
        pytest.skip(f"bash interpreter not found: {requested_bash}")
    version = _bash_version(bash_32)
    if version.split(".")[:2] != ["3", "2"]:
        pytest.skip(
            f"TEST-15 requires bash 3.2; found {bash_32} {version}. Set {BASH_32_ENV} to a bash 3.2 binary to opt in."
        )
    broken = tmp_path / "broken.sh"
    broken.write_text(
        "out=$(\n"
        "    for a in x; do\n"
        '        case "$a" in\n'
        "            *'['*)\n"
        "                echo FAIL\n"
        "                ;;\n"
        "        esac\n"
        "    done\n"
        ")\n"
    )
    assert subprocess.run([bash_32, "-n", str(broken)], capture_output=True).returncode != 0

    fixed = tmp_path / "fixed.sh"
    fixed.write_text(broken.read_text().replace("            *'['*)", "            (*'['*)"))
    assert subprocess.run([bash_32, "-n", str(fixed)], capture_output=True).returncode == 0
