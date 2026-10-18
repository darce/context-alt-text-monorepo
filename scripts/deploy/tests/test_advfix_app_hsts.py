"""Contract test for HSTS on every response from the app vhost."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SNIPPET = REPO_ROOT / "infra" / "oci" / "app" / "Caddyfile.app"


def test_app_vhost_sets_hsts_for_spa_and_portal_api_responses() -> None:
    snippet = SNIPPET.read_text(encoding="utf-8")
    app_vhost = re.search(r"(?ms)^app\.altcontext\.com \{(?P<body>.*?)^\}", snippet)
    assert app_vhost is not None, "missing app HTTPS vhost"

    hsts_headers = re.findall(
        r'(?m)^\theader[ \t]+Strict-Transport-Security[ \t]+"([^"]*)"[ \t]*$',
        app_vhost["body"],
    )
    assert hsts_headers == ["max-age=31536000"], (
        "app vhost must set a one-year HSTS policy outside path handlers so it covers "
        "both the SPA and /portal API responses"
    )
