"""Artifact lock for E15-28 Slice 2 WP bootstrap, tenant runbook, and hardening."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_DEMO = (
    REPO_ROOT / "apps/prototype-description-service/docker-compose.demo.yml"
)
CADDYFILE = REPO_ROOT / "apps/prototype-description-service/Caddyfile"
BOOTSTRAP = REPO_ROOT / "infra/oci/demo/bootstrap-wp.sh"
ENV_EXAMPLE = REPO_ROOT / "infra/oci/demo/.env.example"
TENANT_RUNBOOK = REPO_ROOT / "infra/oci/demo/tenant-mint-runbook.md"
RESET_RUNBOOK = REPO_ROOT / "infra/oci/demo/content-reset-runbook.md"
SYNC_DEMO = REPO_ROOT / "scripts/deploy/sync-demo.sh"


def test_compose_includes_wpcli_profile_and_config_extra() -> None:
    text = COMPOSE_DEMO.read_text()
    assert "wpcli:" in text
    assert 'profiles: ["tools"]' in text or "profiles:\n      - tools" in text
    assert "WORDPRESS_CONFIG_EXTRA" in text


def test_bootstrap_script_covers_install_plugin_sequence() -> None:
    text = BOOTSTRAP.read_text()
    assert "wp core is-installed" in text
    assert "wp core install" in text
    assert "wp plugin" in text
    assert "docker compose" in text


def test_caddy_demo_vhost_blocks_xmlrpc_and_rate_limits_login() -> None:
    text = CADDYFILE.read_text()
    demo_block = text.split("demo.altcontext.com {", 1)[1].split("\n}", 1)[0]
    assert "xmlrpc.php" in demo_block
    assert "403" in demo_block
    assert "wp-login.php" in demo_block
    assert "rate_limit" in demo_block


def test_env_example_documents_acx_constants_and_admin_creds() -> None:
    text = ENV_EXAMPLE.read_text()
    assert "WP_ADMIN_USER" in text
    assert "WP_ADMIN_PASSWORD" in text
    assert "WP_ADMIN_EMAIL" in text
    assert "ACX_RECOGNITION_URL" in text
    assert "ACX_RECOGNITION_SOURCE" in text
    assert "ACX_RECOGNITION_API_KEY" in text
    assert "ACX_RECOGNITION_TENANT_ID" in text
    assert "WP_AUTO_UPDATE_CORE" in text


def test_tenant_runbook_requires_explicit_uuid_not_url_derivation() -> None:
    text = TENANT_RUNBOOK.read_text()
    assert "tenant create --tenant" in text
    assert "https://demo.altcontext.com" in text
    assert "RECOGNITION_ALLOWED_ORIGINS" in text
    assert "derive" in text.lower() or "derived" in text.lower()


def test_deploy_demo_sync_invokes_bootstrap_and_plugin_zip() -> None:
    text = SYNC_DEMO.read_text()
    assert "bootstrap-wp.sh" in text
    assert "alt-context" in text


def test_content_reset_runbook_exists() -> None:
    text = RESET_RUNBOOK.read_text()
    assert "demo" in text.lower()
    assert "bootstrap-wp.sh" in text or "wp" in text
