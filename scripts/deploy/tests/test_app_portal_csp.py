"""Contract test for the production CSP on the app portal SPA response."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SNIPPET = REPO_ROOT / "infra" / "oci" / "app" / "Caddyfile.app"
PRODUCTION_CSP = REPO_ROOT / "apps" / "app-portal" / "csp" / "production.csp"


def _directives(policy: str) -> set[str]:
    return {directive.strip() for directive in policy.split(";") if directive.strip()}


def test_production_csp_is_applied_to_the_spa_handle() -> None:
    snippet = SNIPPET.read_text(encoding="utf-8")
    spa_handle = re.search(r"(?ms)^[ \t]*handle[ \t]*\{(?P<body>.*?)^[ \t]*\}", snippet)
    assert spa_handle is not None, "missing SPA handle"

    csp_headers = re.findall(
        r'(?m)^[ \t]*header[ \t]+Content-Security-Policy[ \t]+"([^"]*)"[ \t]*$',
        spa_handle["body"],
    )
    assert len(csp_headers) == 1, "SPA handle must set exactly one Content-Security-Policy header"

    actual = _directives(csp_headers[0])
    expected = _directives(PRODUCTION_CSP.read_text(encoding="utf-8"))
    assert actual == expected
