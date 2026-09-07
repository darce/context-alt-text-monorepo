"""F1: gpu-lifecycle-install.sh must own /run/acx as container uid 10001.

The api container writes describe-load.json as uid 10001 gid 999, so a
root:10001 directory is not writable and GPU start/reap timers stall.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_INSTALLER_REL = Path("scripts/deploy/gpu-lifecycle-install.sh")
_CLOUD_INIT_REL = Path("infra/oci/cloud-init.yaml")


def _repo_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        marker = candidate / _INSTALLER_REL
        if marker.is_file():
            return candidate
    raise FileNotFoundError(
        "could not locate repo root containing "
        f"{_INSTALLER_REL} (walked up from {start})"
    )


def _non_comment_command_lines(text: str) -> list[str]:
    commands: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        commands.append(stripped)
    return commands


def _flatten_runcmd(runcmd: object) -> list[str]:
    """Flatten cloud-init runcmd into command tokens, splitting compound `&&`."""
    if not isinstance(runcmd, list):
        return []
    tokens: list[str] = []
    for item in runcmd:
        parts: list[str]
        if isinstance(item, str):
            parts = item.split("&&")
        elif isinstance(item, list):
            parts = [" ".join(str(x) for x in item)]
        else:
            continue
        for part in parts:
            token = " ".join(part.split())
            if token:
                tokens.append(token)
    return tokens


def _argv(token: str) -> list[str]:
    """Split a command token, dropping a leading privilege-escalation wrapper.

    The installer issues its chowns as `sudo chown ...` inside the remote
    command block, so matching on argv[0] alone would silently classify every
    installer chown as "not a chown" and make the comparisons below vacuous.
    """
    argv = token.split()
    while argv and Path(argv[0]).name in {"sudo", "doas"}:
        argv = argv[1:]
        # Skip sudo's own options, but stop at the first VAR=value / command.
        while argv and argv[0].startswith("-"):
            argv = argv[1:]
    return argv


def _is_chown_command(argv0: str) -> bool:
    return Path(argv0).name == "chown"


def _is_chown_of_run_acx(token: str) -> bool:
    argv = _argv(token)
    if not argv or not _is_chown_command(argv[0]):
        return False
    return any(arg.rstrip("/") == "/run/acx" for arg in argv[1:])


def _chown_owner(token: str) -> str | None:
    argv = _argv(token)
    if not argv or not _is_chown_command(argv[0]):
        return None
    rest = [arg for arg in argv[1:] if not arg.startswith("-")]
    return rest[0] if rest else None


def _removes_or_recreates_run_acx(token: str) -> bool:
    argv = _argv(token)
    if not argv or argv[0] not in {"rm", "rmdir", "mkdir"}:
        return False
    return any(
        arg == "/run/acx" or arg.startswith("/run/acx/") or arg.rstrip("/") == "/run/acx"
        for arg in argv[1:]
    )


_ROOT = _repo_root()
SCRIPT = _ROOT / _INSTALLER_REL
CLOUD_INIT = _ROOT / _CLOUD_INIT_REL


def test_gpu_lifecycle_install_keeps_the_api_load_dir_group_writable() -> None:
    """WBUX-6 F1's invariant, retargeted onto GPUUX-1's split-directory layout.

    F1 asserted `chown 10001:10001 /run/acx` because the API published
    describe-load.json straight into the single shared `/run/acx`. GPUUX-1
    (M-08) split that: `/run/acx` became host-owned lifecycle state mounted
    read-only into the API, and the API's load dump moved to a separate
    per-environment `/run/acx-write/<env>`. The old assertion's subject no
    longer exists, but the invariant behind it does — the directory the API
    writes into must be writable by the container's writer, and the lifecycle
    state directory must not be API-owned.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    commands = _non_comment_command_lines(text)

    # The load dir the API writes into must carry group 10001 and group-write.
    assert any("chown root:10001 ${LOAD_ENVIRONMENT_DIRS}" in line for line in commands), (
        "installer must give every registered load directory group 10001"
    )
    assert any("chmod 0775 ${LOAD_ENVIRONMENT_DIRS}" in line for line in commands), (
        "installer must keep every registered load directory group-writable"
    )
    assert "d /run/acx-write/${environment} 0775 root 10001 -" in text, (
        "the per-environment tmpfiles template must re-create the load dir "
        "group-writable by 10001 after a tmpfs reboot"
    )

    # The lifecycle state dir is host-owned; the API only gets it read-only.
    assert any("chown ubuntu:ubuntu /run/acx" in line for line in commands), (
        "installer must keep /run/acx owned by the host lifecycle units"
    )
    api_owned_state = [
        line
        for line in commands
        if "10001:10001 /run/acx" in line or "d /run/acx 0775 10001 10001 -" in line
    ]
    assert api_owned_state == [], (
        "/run/acx is the host-owned lifecycle state directory and is mounted "
        f"read-only into the API; it must not be API-owned. found {api_owned_state!r}"
    )


# --- WBUX6-MRG-02: cloud-init and the installer must not both own the contract ---
#
# The replaced test (`test_cloud_init_owns_run_acx_as_container_uid`) asserted
# that cloud-init writes `d /run/acx 0775 10001 10001 -` and chowns /run/acx to
# 10001:10001. It only ever compared cloud-init against itself, so it passed
# happily while gpu-lifecycle-install.sh wrote the *same filename*
# (/etc/tmpfiles.d/acx-gpu.conf) with `d /run/acx 0755 ubuntu ubuntu -`. Two
# writers, one file, last one wins, and the assertion that should have caught it
# was structurally incapable of doing so. The installer is the authority
# (rg-005); these tests compare the two files.

_TMPFILES_FRAGMENT = "/etc/tmpfiles.d/acx-gpu.conf"
# `d <path> <mode> <user> <group> <age>`
_TMPFILES_DIR_LINE = re.compile(
    r"^d\s+(?P<path>/run/\S+)\s+(?P<mode>0[0-7]{3})\s+(?P<user>\S+)\s+(?P<group>\S+)\s"
)


def _tmpfiles_dir_lines(text: str) -> dict[str, str]:
    """Map each `d /run/...` tmpfiles path to its ``user:group mode``."""
    found: dict[str, str] = {}
    for raw in text.splitlines():
        match = _TMPFILES_DIR_LINE.match(raw.strip())
        if not match or "$" in match["path"]:
            continue
        found[match["path"]] = f"{match['user']}:{match['group']} {match['mode']}"
    return found


def _cloud_init() -> dict:
    parsed = yaml.safe_load(CLOUD_INIT.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), "cloud-init.yaml must parse to a mapping"
    return parsed


def _cloud_init_write_files() -> list[dict]:
    write_files = _cloud_init().get("write_files")
    assert isinstance(write_files, list), "cloud-init.yaml must define write_files"
    return [item for item in write_files if isinstance(item, dict)]


def test_only_the_installer_writes_the_tmpfiles_fragment() -> None:
    """One filename, one writer. Two writers is a coin flip, not a contract."""
    installer = SCRIPT.read_text(encoding="utf-8")
    assert _TMPFILES_FRAGMENT in installer, (
        "gpu-lifecycle-install.sh is the authority for the tmpfiles fragment "
        f"and must still write {_TMPFILES_FRAGMENT}"
    )

    conflicting = [
        item["path"]
        for item in _cloud_init_write_files()
        if item.get("path") == _TMPFILES_FRAGMENT
    ]
    assert conflicting == [], (
        f"cloud-init.yaml also writes {_TMPFILES_FRAGMENT}, which "
        "gpu-lifecycle-install.sh owns; whichever runs last silently wins. "
        "Remove it from cloud-init.yaml."
    )


def test_no_cloud_init_tmpfiles_dropin_contradicts_the_installer() -> None:
    """A different filename does not make a contradicting rule safe.

    systemd-tmpfiles merges every drop-in, so a second fragment naming the same
    path under another filename reintroduces the same ambiguity.
    """
    installer_dirs = _tmpfiles_dir_lines(SCRIPT.read_text(encoding="utf-8"))
    assert installer_dirs, "installer tmpfiles parse found nothing; the lines moved"

    for item in _cloud_init_write_files():
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith("/etc/tmpfiles.d/"):
            continue
        content = item.get("content")
        assert isinstance(content, str), f"write_files {path!r} must have string content"
        for run_path, ownership in _tmpfiles_dir_lines(content).items():
            installer_ownership = installer_dirs.get(run_path)
            assert installer_ownership is None or installer_ownership == ownership, (
                f"cloud-init drop-in {path} declares {run_path} as {ownership} "
                f"while gpu-lifecycle-install.sh declares it {installer_ownership}"
            )


def test_cloud_init_does_not_contradict_installer_ownership_of_run_acx() -> None:
    """/run/acx is host lifecycle state; cloud-init must not re-own it.

    The installer chowns it `ubuntu:ubuntu`. A cloud-init `chown 10001:10001`
    on the same path is the API-owned state directory that
    `test_gpu_lifecycle_install_keeps_the_api_load_dir_group_writable` forbids
    the installer from doing -- forbidding it in one file only relocates it.
    """
    tokens = _flatten_runcmd(_cloud_init().get("runcmd"))

    api_owned = [
        tok
        for tok in tokens
        if _is_chown_of_run_acx(tok) and _chown_owner(tok) == "10001:10001"
    ]
    assert api_owned == [], (
        "/run/acx is host-owned lifecycle state mounted read-only into the api "
        f"container; cloud-init must not chown it to the container. found {api_owned!r}"
    )

    installer_commands = _non_comment_command_lines(SCRIPT.read_text(encoding="utf-8"))
    installer_owner = next(
        (
            _chown_owner(line)
            for line in installer_commands
            if _is_chown_of_run_acx(line)
        ),
        None,
    )
    assert installer_owner is not None, "installer must chown /run/acx"
    for tok in tokens:
        if not _is_chown_of_run_acx(tok):
            continue
        assert _chown_owner(tok) == installer_owner, (
            f"cloud-init chowns /run/acx to {_chown_owner(tok)!r} while the "
            f"installer uses {installer_owner!r}: {tok!r}"
        )


def test_installer_reaper_units_read_the_directory_compose_publishes_to() -> None:
    """The reaper must read a path something actually writes.

    cloud-init used to point the reaper at `--load-json /run/acx/describe-load.json`.
    GPUUX-1 moved publication to `/run/acx-write/<env>/describe-load.json` and
    replaced the flag with `--load-dir`. GPUOPS-1 then made the installer the
    single declarative owner of the reaper (cloud-init no longer writes the unit
    at all -- that ownership split is guarded by
    scripts/deploy/tests/test_gpu_lifecycle_single_reaper_owner.py), so the
    flag-correctness guard has to follow the units into the installer.
    """
    cloud_init_gpu_units = [
        item
        for item in _cloud_init_write_files()
        if isinstance(item.get("path"), str)
        and "gpu" in str(item["path"])
        and str(item["path"]).endswith(".service")
    ]
    assert not cloud_init_gpu_units, (
        "the installer is the single reaper owner; cloud-init must not define a "
        f"GPU unit, but it defines {[u['path'] for u in cloud_init_gpu_units]!r}"
    )

    installer = SCRIPT.read_text(encoding="utf-8")
    installer_load_dirs = set(re.findall(r"--load-dir\s+(\S+)", installer))
    assert len(installer_load_dirs) == 1, (
        f"installer units must agree on one --load-dir; found {installer_load_dirs}"
    )
    expected_load_dir = installer_load_dirs.pop()

    exec_starts = [
        line
        for line in re.findall(r"^ExecStart=.*$", installer, re.MULTILINE)
        if "gpu_lifecycle" in line and "--mode" in line
    ]
    assert exec_starts, "installer must define gpu_lifecycle ExecStart units"
    for exec_start in exec_starts:
        assert "--load-json" not in exec_start, (
            f"--load-json is not a gpu_lifecycle flag any more: {exec_start!r}"
        )
        load_dirs = re.findall(r"--load-dir\s+(\S+)", exec_start)
        assert load_dirs == [expected_load_dir], (
            f"every installer reaper unit must read {expected_load_dir!r}; "
            f"got {load_dirs!r} in {exec_start!r}"
        )
