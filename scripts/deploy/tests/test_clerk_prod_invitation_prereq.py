"""Pin the production invitation dependency without issuing real invitations."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = REPO_ROOT / "docs/runbooks/clerk-production-auth.md"
CLI_PATH = "apps/prototype-description-service/scripts/manage_portal_invitations.py"


def _runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _smoke() -> str:
    runbook = _runbook()
    heading = "### Post-launch signed-in smoke check"
    assert heading in runbook, "missing signed-in smoke instructions"
    return runbook.split(heading)[1].split("## 5.")[0]


def test_launch_stops_for_main_and_service_release_without_reversing_merge_order() -> None:
    runbook = _runbook()
    heading = "## Production LAUNCH prerequisite (before A3/deployment)"
    assert heading in runbook, "missing production LAUNCH prerequisite"
    prerequisite = runbook.split(heading)[1].split("Official references:")[0]
    assert "Current PROD-only tree does **not** include the invitation CLI" in prerequisite
    assert "STOP: do not begin A3/deployment or production LAUNCH" in prerequisite
    assert f"`main` contains `{CLI_PATH}`" in " ".join(prerequisite.split())
    assert "production service release to deploy includes that CLI" in " ".join(prerequisite.split())
    assert "PORTALDEV-1" in prerequisite
    assert prerequisite.index("PORTALPROD-1 config mainmerge") < prerequisite.index("PORTALDEV-1 union/mainmerge")
    assert "PROD config merge does not wait for the DEV branch" in " ".join(prerequisite.split())
    assert "not a circular branch merge dependency" in " ".join(prerequisite.split())
    materialize = runbook.split("## 4. Materialize and build")[1].split("```bash")[0]
    assert "Complete the production LAUNCH prerequisite above before A3/deployment" in materialize


def test_smoke_requires_deployed_cli_and_matching_unexpired_operator_invitation() -> None:
    smoke = " ".join(_smoke().split())
    assert "STOP this signed-in smoke check until PORTALDEV-1's invitation CLI has landed on `main`" in smoke
    assert "deployed production API includes it" in smoke
    assert "primary email verified in Clerk" in smoke
    assert "operator-issued, unexpired portal invitation" in smoke
    assert "invited email matches that verified primary email" in smoke
    assert "`POST /portal/onboarding/claim`" in smoke
    assert "through the portal's claim screen" in smoke
    assert "raw invitation token only once" in smoke
    assert "Copy it directly into the portal's invitation claim field" in smoke
    assert "Do not print an API key during the check" in smoke


def test_documented_issuance_command_runs_in_prod_api_with_supported_flags(tmp_path: Path) -> None:
    smoke = _smoke()
    blocks = [
        block
        for block in re.findall(r"```bash\n(.*?)```", smoke, re.DOTALL)
        if "manage_portal_invitations" in block
    ]
    assert len(blocks) == 1, "expected one supported invitation issuance command"
    lines = blocks[0].strip().splitlines()
    assert lines[0] == "cd /opt/acx-backend/prod"
    assert len(lines) == 2
    command = shlex.split(lines[1])
    assert command == [
        "docker",
        "compose",
        "-f",
        "docker-compose.env.yml",
        "exec",
        "-T",
        "api",
        "python",
        "-m",
        "scripts.manage_portal_invitations",
        "--env",
        "prod",
        "create",
        "--email",
        "you@example.com",
        "--ttl-hours",
        "72",
    ]
    # Execute only the parsed command, with docker replaced by a temporary fake.
    # The absolute operator directory is checked above, never accessed here.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" > "$INVITATION_ARGV_LOG"\nprintf "fake-one-time-token\\n"\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    fake_prod = tmp_path / "opt" / "acx-backend" / "prod"
    fake_prod.mkdir(parents=True)
    argv_log = tmp_path / "argv.log"
    result = subprocess.run(
        command,
        cwd=fake_prod,
        env={**os.environ, "PATH": str(fake_bin), "INVITATION_ARGV_LOG": str(argv_log)},
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "fake-one-time-token\n"
    assert argv_log.read_text(encoding="utf-8").splitlines() == [str(fake_prod), *command[1:]]
    assert (
        "Only after the dependency has landed and the production service has been deployed with it"
        in " ".join(smoke.split())
    )


def test_status_recovery_distinguishes_not_admitted_from_consumed_or_bound() -> None:
    smoke = " ".join(_smoke().split())
    forbidden = smoke.split("If it returns `403`")[1].split("If the onboarding claim returns `409`")[0]
    assert "`email` and boolean `email_verified: true`" in forbidden
    assert "`403` with `not_admitted`" in forbidden
    for cause in ("email mismatch", "unknown token", "expired invitation", "revoked invitation"):
        assert cause in forbidden
    assert "operator" in forbidden and "replacement invitation" in forbidden
    assert "consumed" not in forbidden
    conflict = smoke.split("If the onboarding claim returns `409`")[1].split("If it returns `503`")[0]
    assert "`invitation_consumed` or `identity_already_bound`" in conflict
    assert "operator" in conflict and "tenant binding" in conflict
    assert "reload" in conflict
    assert "`aud` is `altcontext-portal`" in smoke
    assert "`azp` is `https://app.altcontext.com`" in smoke
    assert "`503` with `portal identity unavailable`" in smoke
    assert "Check API logs and readiness" in smoke
