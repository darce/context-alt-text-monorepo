"""Pin the production invitation dependency without issuing real invitations."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = REPO_ROOT / "docs/runbooks/clerk-production-auth.md"
DEPLOY_RUNBOOK = REPO_ROOT / "docs/runbooks/app-portal-deploy.md"
CLI_PATH = "apps/prototype-description-service/scripts/manage_portal_invitations.py"
LAUNCH_LINK = "clerk-production-auth.md#production-launch-prerequisite-before-a3deployment"
CLI_HELP_COMMAND = (
    "cd /opt/acx-backend/prod && docker compose -f docker-compose.env.yml "
    "exec -T api python -m scripts.manage_portal_invitations --help"
)


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
        block for block in re.findall(r"```bash\n(.*?)```", smoke, re.DOTALL) if "manage_portal_invitations" in block
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
    assert "Only after the dependency has landed and the production service has been deployed with it" in " ".join(
        smoke.split()
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


def _assert_deploy_launch_contract(runbook: str) -> None:
    checklist = runbook.split("## Before production launch")[1].split("## Default dry-run")[0]
    activation = runbook.split("### Activate the production API before frontend apply")[1].split(
        "### Install the checker and apply the frontend"
    )[0]
    first_materialize = runbook.index("make env-materialize")
    for section in (checklist, activation.split("The portal router enablement")[0]):
        normalized = " ".join(section.split())
        for required in (
            "**STOP:**",
            f"`main` must contain `{CLI_PATH}`",
            "PORTALDEV-1",
            "combined-main production service release to deploy",
            LAUNCH_LINK,
        ):
            assert required in normalized, f"missing deploy-runbook gate: {required}"
        assert runbook.index(section) < first_materialize, "launch gate must precede materialization"
    checklist = " ".join(checklist.split())
    assert "service release must be deployed and its invitation CLI verified" in checklist
    assert "A restart alone does not install code" in checklist
    assert "Materialization and restart are the remaining operator steps" not in " ".join(runbook.split())

    blocks = re.findall(r"```bash\n(.*?)```", activation, re.DOTALL)
    steps = (
        "make env-materialize ENV=prod TARGET=svc-vm\n",
        "make env-materialize ENV=prod TARGET=svc-vm APPLY=1 CONFIRM=prod\n",
        "make deploy-prod CONFIRM=PROMOTE\n",
        "sudo systemctl restart acx-prod\n",
        CLI_HELP_COMMAND,
        "https://api.altcontext.com/portal/me",
    )
    positions = []
    for step in steps:
        matches = [index for index, block in enumerate(blocks) if step in block]
        assert len(matches) == 1, f"missing or ambiguous activation step: {step}"
        positions.append(matches[0])
    assert positions == sorted(set(positions)), "materialize/deploy/CLI/API order is unsafe"
    assert runbook.index(CLI_HELP_COMMAND) < runbook.index("scripts/deploy/app-portal.sh --apply")
    normalized = " ".join(activation.split())
    for required in (
        "preflight_env_manifest",
        "materialize_remote.sh prod svc-vm --check",
        "refuses runtime drift or missing host-only secrets",
        "Do not bypass the manifest preflight or any other deployment safety gate",
        "container CLI check below succeeds",
        "matching, unexpired operator-issued portal invitation",
        "verified primary email",
        "clerk-production-auth.md#post-launch-signed-in-smoke-check",
    ):
        assert required in normalized, f"missing deployment ordering explanation: {required}"


def test_deploy_runbook_gates_materialization_and_public_launch_in_supported_order() -> None:
    _assert_deploy_launch_contract(DEPLOY_RUNBOOK.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "start,end",
    [
        ("- **STOP:**", "- The production value"),
        ("**STOP:** before the first materialization", "The portal router enablement"),
    ],
)
def test_deploy_runbook_pins_reject_either_removed_stop_gate(start: str, end: str) -> None:
    runbook = DEPLOY_RUNBOOK.read_text(encoding="utf-8")
    gate_start = runbook.index(start)
    gate_end = runbook.index(end, gate_start)
    mutant = runbook[:gate_start] + runbook[gate_end:]
    with pytest.raises(AssertionError, match="missing deploy-runbook gate"):
        _assert_deploy_launch_contract(mutant)


@pytest.mark.parametrize(
    "removed",
    [
        "**STOP:**",
        CLI_PATH,
        "PORTALDEV-1",
        LAUNCH_LINK,
        "CLI verified",
        "A restart alone does not install code",
        "make deploy-prod CONFIRM=PROMOTE",
        CLI_HELP_COMMAND,
        "preflight_env_manifest",
        "Do not bypass",
        "matching, unexpired operator-issued portal invitation",
    ],
)
def test_deploy_runbook_pins_reject_removal_mutants(removed: str) -> None:
    runbook = DEPLOY_RUNBOOK.read_text(encoding="utf-8")
    assert removed in runbook, "mutation must remove existing instructions"
    with pytest.raises(AssertionError):
        _assert_deploy_launch_contract(runbook.replace(removed, ""))


def test_deploy_runbook_pins_reject_deploy_before_materialization() -> None:
    runbook = DEPLOY_RUNBOOK.read_text(encoding="utf-8")
    deploy_block = "```bash\nmake deploy-prod CONFIRM=PROMOTE\n```"
    materialize_block = "```bash\nmake env-materialize ENV=prod TARGET=svc-vm\n```"
    assert deploy_block in runbook and materialize_block in runbook
    mutant = runbook.replace(deploy_block, "").replace(materialize_block, deploy_block + "\n" + materialize_block)
    with pytest.raises(AssertionError, match="materialize/deploy/CLI/API order is unsafe"):
        _assert_deploy_launch_contract(mutant)


@pytest.mark.parametrize("cli_status,missing_directory", [(0, False), (1, False), (127, False), (0, True)])
def test_deployed_cli_help_check_fails_closed_with_only_fake_docker(
    tmp_path: Path, cli_status: int, missing_directory: bool
) -> None:
    runbook = DEPLOY_RUNBOOK.read_text(encoding="utf-8")
    blocks = [block for block in re.findall(r"```bash\n(.*?)```", runbook, re.DOTALL) if "--help" in block]
    assert len(blocks) == 1, "expected one deployed invitation CLI check"
    block = blocks[0]
    assert CLI_HELP_COMMAND in block
    fake_prod = tmp_path / "prod"
    if not missing_directory:
        fake_prod.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    argv_log = tmp_path / "argv.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" > "$INVITATION_ARGV_LOG"\nexit "$CLI_STATUS"\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    # Substitute only the operator cwd; no real VM paths or commands are touched.
    script = block.replace("/opt/acx-backend/prod", shlex.quote(str(fake_prod)))
    # A stand-in for subsequent frontend apply must be unreachable on failure.
    assert script.endswith(")\n")
    script = script[:-2] + "  printf 'frontend-apply\\n'\n)\n"
    result = subprocess.run(
        ["/bin/bash", "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(fake_bin),
            "INVITATION_ARGV_LOG": str(argv_log),
            "CLI_STATUS": str(cli_status),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if missing_directory:
        assert not argv_log.exists(), "docker must not run after failed cd"
    else:
        assert argv_log.read_text(encoding="utf-8").splitlines() == [
            str(fake_prod),
            *shlex.split(CLI_HELP_COMMAND.split(" && ")[1])[1:],
        ]
    if cli_status or missing_directory:
        assert result.returncode != 0
        assert "STOP: deployed production invitation CLI unavailable" in result.stderr
        assert "frontend-apply" not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout == "frontend-apply\n"


def test_rollback_prose_preserves_successful_prestate_and_failed_restore_inputs() -> None:
    runbook = DEPLOY_RUNBOOK.read_text(encoding="utf-8")
    apply_steps = " ".join(runbook.split("`--apply` then:")[1].split("Interrupted recovery also")[0].split())
    step5 = apply_steps.split("5. On success:")[1].split("6. Promotes")[0]
    assert "reclaimed only after a successful apply" in step5
    assert "failed apply must not displace the last successful apply's prestate set" in step5
    for section in (apply_steps.split("10. Any failure")[1], runbook.split("### Frontend back-out")[1]):
        normalized = " ".join(section.split())
        assert "removes only its duplicate timestamp set" in normalized
        assert "preserving the last successful apply's prestate set" in normalized
        assert "Failed restore retains the journal and all snapshot/absence-marker inputs for retry" in normalized
