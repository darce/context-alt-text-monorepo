"""Contract tests for the secrets inventory and Phase 4 auth-pipeline plan."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = (
    REPO_ROOT
    / "apps"
    / "prototype-description-service"
    / "docs"
    / "secrets-inventory.md"
)
SCOPE = REPO_ROOT / "docs" / "scopes" / "secrets-consolidation.md"
DOCS = (INVENTORY, SCOPE)

MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
STALE = re.compile(
    r"/opt/acx-backend/(?:(?:prod|staging|dev|dev-fir|<env>)/)?secrets/\.env"
)
SKIP_LINK_PREFIXES = ("http:", "https:", "mailto:")
STALE_CLAIMS = (
    "No OCI Vault backend",
    "Until Slice 3 lands",
    "OCI Vault (prod, Phase 3)",
    "OCI Vault (Phase 3)",
    "through the env's `/admin` console",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_relative_markdown_links_resolve() -> None:
    missing: list[str] = []
    for doc in DOCS:
        text = _read(doc)
        for match in MD_LINK.finditer(text):
            target = match.group(1)
            if target.startswith(SKIP_LINK_PREFIXES):
                continue
            if target.startswith("#"):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            resolved = (doc.parent / path_part).resolve()
            if not resolved.is_file():
                missing.append(f"{doc.relative_to(REPO_ROOT)} -> {target} ({resolved})")
    assert not missing, "broken relative markdown links:\n" + "\n".join(missing)


def test_inventory_drops_stale_vm_secrets_paths() -> None:
    text = _read(INVENTORY)
    hits = STALE.findall(text)
    assert hits == [], f"stale VM secrets/.env paths remain: {hits}"
    assert "/opt/acx-backend/demo/secrets/.env" in text


def test_inventory_drops_stale_phase1_claims() -> None:
    text = _read(INVENTORY)
    found = [claim for claim in STALE_CLAIMS if claim in text]
    assert found == [], f"stale Phase-1 claims remain: {found}"


def test_current_state_claims_present() -> None:
    inventory = _read(INVENTORY)
    for snippet in (
        "oci_vault",
        "## Public vhosts require auth",
        "RECOGNITION_AUTH_ENABLED=true",
        "RECOGNITION_PORTAL_ENABLED",
        "POLAR_WEBHOOK_SECRET",
    ):
        assert snippet in inventory, f"inventory missing current-state claim: {snippet}"

    scope = _read(SCOPE)
    assert any(
        line.startswith("### Phase 4") for line in scope.splitlines()
    ), "scope doc missing ### Phase 4 heading"
    for snippet in ("app.altcontext.com", "api_keys", "169.254.169.254"):
        assert snippet in scope, f"scope doc missing current-state claim: {snippet}"


def test_stale_path_pattern_self_check() -> None:
    assert STALE.search("/opt/acx-backend/prod/secrets/.env")
    assert STALE.search("/opt/acx-backend/<env>/secrets/.env")
    assert STALE.search("/opt/acx-backend/demo/secrets/.env") is None
