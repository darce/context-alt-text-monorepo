"""Collect the real public-guide cases using app-local Playwright, without a browser."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = APP_ROOT.parents[1]


def test_public_guide_collects_desktop_and_phone_cases() -> None:
    playwright = APP_ROOT / "node_modules/.bin/playwright"
    assert playwright.is_file(), (
        f"Missing app-local Playwright; provision dependencies with npm ci --ignore-scripts in {APP_ROOT}"
    )
    try:
        result = subprocess.run(
            [str(playwright), "test", "--project=public-guide", "--list"],
            cwd=APP_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.fail(f"App-local Playwright collection could not complete within 60 seconds: {exc}")
    output = result.stdout + result.stderr
    assert result.returncode == 0, output

    # Three acceptance cases in the real spec, each repeated for desktop and Pixel 7.
    titles = (
        "signed-out /guide/ is 200 with canonical, scope copy, keyboard apply/undo, and no REST",
        "direct reload of /guide/ keeps the page working",
        "route-blocked guide bundle shows the fallback paragraph",
    )
    collected = [line.strip() for line in result.stdout.splitlines() if "[public-guide]" in line]
    assert len(collected) == 2 * len(titles), output
    for viewport in ("desktop 1440x900", "mobile Pixel 7"):
        for title in titles:
            suffix = f"public guide signed-out › {viewport} › {title}"
            assert sum(line.endswith(suffix) for line in collected) == 1, output
    assert all("public-guide.spec.ts:" in line for line in collected), output
    assert re.search(r"Total: 6 tests in 1 file\b", result.stdout), output

