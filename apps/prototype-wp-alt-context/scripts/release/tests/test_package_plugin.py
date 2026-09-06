import subprocess
import sys
from pathlib import Path


def test_package_plugin_shell_regression():
    test_script = Path(__file__).with_name("test-package-plugin.sh")
    result = subprocess.run(
        ["bash", str(test_script)],
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)

    assert result.returncode == 0
