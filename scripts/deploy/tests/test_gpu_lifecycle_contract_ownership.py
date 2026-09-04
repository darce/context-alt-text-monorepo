"""The GPU lifecycle contract must state the ownership the installer provisions.

GPUUX1-M-08: the contract claimed `/run/acx` was `10001:10001 0775` while
`gpu-lifecycle-install.sh` provisions it `ubuntu:ubuntu 0755`, and it never
mentioned `/run/acx-write` at all. Nothing tested the claim, so the drift
shipped. The systemd-tmpfiles lines in the installer are the authority
(rg-005 contract parity).
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SCRIPT = REPO_ROOT / "scripts/deploy/gpu-lifecycle-install.sh"
DEPLOYMENTS = REPO_ROOT / "scripts/deploy/gpu-snapshot-deployments.conf"
CONTRACT = REPO_ROOT / "docs/workbay/contracts/gpu-lifecycle.md"

# `d <path> <mode> <user> <group> <age>` — the systemd-tmpfiles directory lines.
_TMPFILES_DIR = re.compile(
    r"^d\s+(?P<path>/run/\S+)\s+(?P<mode>0[0-7]{3})\s+(?P<user>\S+)\s+(?P<group>\S+)\s",
    re.MULTILINE,
)
_BRACE = re.compile(r"\{([^{}]+)\}")


def _provisioned() -> dict[str, str]:
    """Map each provisioned /run directory to its ``user:group mode`` string."""
    text = INSTALL_SCRIPT.read_text(encoding="utf-8")
    found = {}
    for match in _TMPFILES_DIR.finditer(text):
        path = match["path"]
        ownership = f"{match['user']}:{match['group']} {match['mode']}"
        if "$" not in path:
            found[path] = ownership
    # A silently-empty parse would make every assertion below vacuous.
    assert {"/run/acx", "/run/acx-write"} <= set(found), (
        f"installer tmpfiles parse found only {sorted(found)}; "
        "the directory lines moved or changed shape"
    )
    return found


def _contract_text() -> str:
    """Contract prose with grouped deployment brace forms expanded.

    The contract legitimately writes one line for a group of sibling
    directories that share ownership. Expanding the braces lets the path
    check stay literal without forcing triplicated boilerplate into the doc.
    """
    text = CONTRACT.read_text(encoding="utf-8")
    expansions = []
    for line in text.splitlines():
        match = _BRACE.search(line)
        if not match:
            continue
        alternatives = [a.strip() for a in match.group(1).split(",")]
        expansions.extend(line.replace(match.group(0), alt) for alt in alternatives)
    return "\n".join(itertools.chain([text], expansions))


def test_every_provisioned_directory_is_named_in_the_contract() -> None:
    contract = _contract_text()

    for path in _provisioned():
        assert f"`{path}`" in contract, (
            f"{INSTALL_SCRIPT.name} provisions {path} but the contract never names it"
        )


def test_contract_states_each_distinct_ownership_tuple() -> None:
    contract = _contract_text()

    for ownership in sorted(set(_provisioned().values())):
        assert f"`{ownership}`" in contract, (
            f"{INSTALL_SCRIPT.name} provisions a directory as {ownership}, "
            "which the contract never states"
        )


def test_a_subdirectory_that_breaks_from_its_parent_must_be_stated_explicitly() -> None:
    """Shared ownership may be described as a group; a divergence may not.

    A subdirectory provisioned differently from its parent is exactly the
    case a grouped sentence would hide, so it must carry its own line.
    """
    provisioned = _provisioned()
    contract = _contract_text()

    for path, ownership in provisioned.items():
        parent = str(Path(path).parent)
        if provisioned.get(parent) in (None, ownership):
            continue
        assert f"`{path}` is `{ownership}`" in contract, (
            f"{path} is provisioned {ownership}, differing from its parent "
            f"{parent} ({provisioned[parent]}); the contract must say so explicitly"
        )


def test_contract_does_not_claim_the_state_dir_is_api_owned() -> None:
    """`/run/acx` is read-only to the api container; uid 10001 must not own it."""
    assert "`/run/acx` is `10001:10001" not in CONTRACT.read_text(encoding="utf-8")


def test_each_registered_deployment_uses_api_writable_tmpfiles_template() -> None:
    """The validated registry must drive one root:10001 0775 tmpfiles rule."""
    deployments = DEPLOYMENTS.read_text(encoding="utf-8").splitlines()
    required_deployments = {"dev", "dev-fir", "staging", "prod"}
    assert deployments, "GPU snapshot deployment registry must not be empty"
    assert len(deployments) == len(set(deployments)), "deployments must be unique"
    assert all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", item) for item in deployments)
    assert required_deployments <= set(deployments), (
        "GPU snapshot deployment registry is missing required environments: "
        f"{sorted(required_deployments - set(deployments))}"
    )

    installer = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert "d /run/acx-write/${environment} 0775 root 10001 -" in installer
    assert 'done < "$DEPLOYMENTS_FILE"' in installer
