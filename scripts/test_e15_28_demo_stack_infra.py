"""Doc/artifact lock for E15-28 Slice 1 demo stack infrastructure.

The repo-tracked compose, Caddy, deploy, and systemd surfaces are the contract
for reproducible demo provisioning on the OCI VM. If Slice 1 deliverables drift
without updating this test, CI fails before prod Caddy routing regresses silently.
"""

from __future__ import annotations

import re
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
    # acx-demo-net must stay external: a compose-owned network gets deleted by
    # `down`, and the edge Caddy declares it as a required external join.
    assert "external: true" in text
    # No blanket env_file — each service maps only the secrets it needs.
    assert "env_file:" not in text


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
    # The network name is hardcoded in compose (external acx-demo-net); an env
    # knob would be illusory because docker-compose.caddy.yml and sync-demo.sh
    # both hardcode the name.
    assert "ACX_NETWORK_NAME" not in env_text


def test_sync_demo_ensures_fir_network_before_caddy_up() -> None:
    """FL30-C-13: demo deploy must create acx-dev-fir-net before caddy up -d.

    docker-compose.caddy.yml declares acx-dev-fir-net as external:true. The
    recognition-service.sh path creates it idempotently, but sync-demo.sh is what
    deploy-demo.yml drives. Without an ensure here, compose aborts when the fir
    stack has never stood the network up.

    Labels must match docker-compose.env.yml's declaring key (`backend`) and
    COMPOSE_PROJECT_NAME=acx-dev-fir so a later fir stack bring-up can adopt the
    network rather than refusing an unlabelled one.
    """
    text = SYNC_DEMO.read_text()
    caddy_up = "docker compose -f docker-compose.caddy.yml up -d"
    up_idx = text.find(caddy_up)
    assert up_idx != -1, f"sync-demo.sh must invoke `{caddy_up}`"

    # Locate an idempotent ensure of acx-dev-fir-net: inspect-guarded create
    # with both compose adoption labels. A bare name mention (comment, compose
    # scp path) must not satisfy this.
    ensure_re = re.compile(
        r"docker\s+network\s+inspect\s+acx-dev-fir-net\b"
        r".*?"
        r"\|\|"
        r".*?"
        r"docker\s+network\s+create\b"
        r".*?"
        r"--label\s+com\.docker\.compose\.network=backend\b"
        r".*?"
        r"--label\s+com\.docker\.compose\.project=acx-dev-fir\b"
        r".*?"
        r"acx-dev-fir-net\b",
        re.DOTALL,
    )
    # Allow either label order; re-check with swapped labels if needed.
    ensure_re_alt = re.compile(
        r"docker\s+network\s+inspect\s+acx-dev-fir-net\b"
        r".*?"
        r"\|\|"
        r".*?"
        r"docker\s+network\s+create\b"
        r".*?"
        r"--label\s+com\.docker\.compose\.project=acx-dev-fir\b"
        r".*?"
        r"--label\s+com\.docker\.compose\.network=backend\b"
        r".*?"
        r"acx-dev-fir-net\b",
        re.DOTALL,
    )
    match = ensure_re.search(text) or ensure_re_alt.search(text)
    assert match is not None, (
        "sync-demo.sh must idempotently ensure acx-dev-fir-net "
        "(docker network inspect … || docker network create with "
        "com.docker.compose.network=backend and "
        "com.docker.compose.project=acx-dev-fir labels) before caddy up"
    )
    ensure_idx = match.start()
    assert ensure_idx < up_idx, (
        f"acx-dev-fir-net ensure must appear before `{caddy_up}` "
        f"(ensure@{ensure_idx} vs up@{up_idx}); reordering leaves external "
        "network missing when compose runs"
    )
