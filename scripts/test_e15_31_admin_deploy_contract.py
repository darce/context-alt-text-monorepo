"""Static deployment-contract checks for the persistent E15-31 admin overlay.

The /admin surface ships as a compose overlay (docker-compose.admin.yml) that
binds the admin port to loopback. These tests pin the contract that ordinary
prod deploys and systemd restarts install and retain that overlay — without
them, a manual `docker compose -f env -f admin up` (runbook step) is silently
dropped by the next deploy-env.sh run or unit restart.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "apps/prototype-description-service"


def test_prod_deploy_installs_and_persists_admin_compose_overlay() -> None:
    deploy = (SERVICE / "scripts/deploy-env.sh").read_text()
    unit = (SERVICE / "systemd/acx-env.service.template").read_text()

    assert 'docker-compose.admin.yml" "$SSH_TARGET:/opt/acx-backend/$ENV/' in deploy
    assert 'COMPOSE_FILES="-f docker-compose.env.yml -f docker-compose.admin.yml"' in deploy
    assert "{{COMPOSE_FILES}} up --remove-orphans" in unit
    assert "{{COMPOSE_FILES}} stop" in unit


def test_prod_compose_sync_promotes_and_applies_admin_overlay() -> None:
    sync = (ROOT / "scripts/deploy/sync-compose.sh").read_text()

    assert 'ADMIN_SOURCE="${ADMIN_SOURCE:-apps/prototype-description-service/docker-compose.admin.yml}"' in sync
    assert "docker-compose.admin.yml.new" in sync
    assert 'COMPOSE_ARGS="-f docker-compose.env.yml -f docker-compose.admin.yml"' in sync
    assert "docker compose $COMPOSE_ARGS up -d" in sync
    assert r"\$(date +%s)" not in sync
