"""Doc/artifact lock for E15-28 Slice 1 demo stack infrastructure.

The repo-tracked compose, Caddy, deploy, and systemd surfaces are the contract
for reproducible demo provisioning on the OCI VM. If Slice 1 deliverables drift
without updating this test, CI fails before prod Caddy routing regresses silently.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_DEMO = (
    REPO_ROOT / "apps/prototype-description-service/docker-compose.demo.yml"
)
CADDYFILE = REPO_ROOT / "apps/prototype-description-service/Caddyfile"
CADDY_COMPOSE = (
    REPO_ROOT / "apps/prototype-description-service/docker-compose.caddy.yml"
)
DEPLOY_MK = REPO_ROOT / "mk/deploy.mk"
SYNC_DEMO = REPO_ROOT / "scripts/deploy/sync-demo.sh"
SYSTEMD_UNIT = (
    REPO_ROOT / "apps/prototype-description-service/systemd/acx-demo.service"
)
ENV_EXAMPLE = REPO_ROOT / "infra/oci/demo/.env.example"


def test_demo_compose_file_exists_with_bulkhead_and_network_alias() -> None:
    text = COMPOSE_DEMO.read_text()
    assert "wordpress:" in text
    assert "mariadb:" in text
    assert "acx-demo-net" in text
    assert "demo-wp" in text
    assert "cpus:" in text
    assert "mem_limit:" in text
    assert "ACX_DEMO_WPDATA_PATH" in text
    assert "ACX_DEMO_DBDATA_PATH" in text


def test_caddyfile_routes_demo_subdomain_to_demo_wp_upstream() -> None:
    text = CADDYFILE.read_text()
    assert "demo.altcontext.com" in text
    assert "reverse_proxy demo-wp:80" in text


def test_caddy_compose_joins_demo_network() -> None:
    text = CADDY_COMPOSE.read_text()
    assert "acx-demo-net" in text
    assert "external: true" in text


def test_deploy_demo_target_and_sync_script_exist() -> None:
    deploy_text = DEPLOY_MK.read_text()
    assert "deploy-demo" in deploy_text
    sync_text = SYNC_DEMO.read_text()
    assert "docker-compose.demo.yml" in sync_text
    assert "Caddyfile" in sync_text
    assert "docker-compose.caddy.yml" in sync_text
    assert "caddy validate" in sync_text


def test_systemd_unit_and_secrets_template_exist() -> None:
    unit_text = SYSTEMD_UNIT.read_text()
    assert "acx-demo.service" in unit_text or "Description=ACX Demo" in unit_text
    assert "docker-compose.demo.yml" in unit_text
    env_text = ENV_EXAMPLE.read_text()
    assert "COMPOSE_PROJECT_NAME=acx-demo" in env_text
    assert "ACX_NETWORK_NAME=acx-demo-net" in env_text
