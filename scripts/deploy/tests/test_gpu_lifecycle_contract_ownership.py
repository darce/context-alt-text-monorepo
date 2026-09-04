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


# --- WBUX6-MRG-01: the image's runtime gid is half of the ownership contract ---
#
# The installer grants the api container write access to the describe-load
# directory through the *group* (`root:10001 0775`). That only works if the
# container's runtime gid really is 10001. The image creates the runtime user
# with an explicit uid but the group gid is a separate, easily-dropped flag:
# `groupadd -r acx` (no `-g`) yields `uid=10001(acx) gid=999(acx)` on
# python:3.12-slim, which matches neither owner nor group and falls through to
# `other` (r-x). Nothing compared the two files, so the split shipped.

DOCKERFILE = REPO_ROOT / "apps/prototype-description-service/Dockerfile"

# `groupadd [-r] -g <gid> <name>` — the pinned runtime group.
_GROUPADD_PINNED_GID = re.compile(r"groupadd[^&|\n]*?\s-g\s+(?P<gid>\d+)")
_USERADD_UID = re.compile(r"useradd[^&|\n]*?\s-u\s+(?P<uid>\d+)")


def _api_runtime_ids() -> tuple[str, str]:
    """The uid and gid the api image pins for its runtime user."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    gids = {m["gid"] for m in _GROUPADD_PINNED_GID.finditer(text)}
    uids = {m["uid"] for m in _USERADD_UID.finditer(text)}
    assert len(uids) == 1, (
        f"{DOCKERFILE.name} must create exactly one runtime user with an "
        f"explicit uid; found {sorted(uids)}"
    )
    assert len(gids) == 1, (
        f"{DOCKERFILE.name} must pin exactly one runtime gid via `groupadd -g`; "
        f"found {sorted(gids)}. Without an explicit -g the base image assigns "
        "the gid (observed 999), so the group-write grant on "
        "/run/acx-write/<env> silently stops applying."
    )
    return uids.pop(), gids.pop()


def test_api_image_pins_its_runtime_gid_explicitly() -> None:
    """An implicit gid is not a contract; it is whatever the base image had."""
    uid, gid = _api_runtime_ids()
    assert uid == gid, (
        f"the api image pins uid {uid} but gid {gid}; the deployment contract "
        "treats them as one identity"
    )


def test_load_dir_group_matches_the_gid_the_api_image_pins() -> None:
    """The group the host grants must be the group the container actually has.

    This is the assertion whose absence let WBUX6-MRG-01 ship: the installer
    and the Dockerfile each looked self-consistent, and no test read both.
    """
    _, image_gid = _api_runtime_ids()
    provisioned = _provisioned()

    write_dirs = {
        path: ownership
        for path, ownership in provisioned.items()
        if path == "/run/acx-write" or path.startswith("/run/acx-write/")
    }
    assert write_dirs, "installer must provision the describe-load write root"

    for path, ownership in write_dirs.items():
        owner, mode = ownership.split()
        group = owner.split(":")[1]
        assert group == image_gid, (
            f"installer provisions {path} with group {group}, but the api image "
            f"runs as gid {image_gid}; the container would fall through to "
            "`other` and could not publish describe-load.json"
        )
        # Group-write is the mechanism that grant depends on.
        assert mode[2] in "2367", (
            f"{path} is provisioned {mode}; group {group} must have write "
            "permission or the group grant is inert"
        )


def test_installer_template_group_is_not_hardcoded_away_from_the_image() -> None:
    """The per-environment tmpfiles template carries the same group."""
    _, image_gid = _api_runtime_ids()
    installer = INSTALL_SCRIPT.read_text(encoding="utf-8")
    assert f"d /run/acx-write/${{environment}} 0775 root {image_gid} -" in installer, (
        "the per-environment tmpfiles template must grant the gid the api "
        f"image pins ({image_gid})"
    )
