"""F1: gpu-lifecycle-install.sh must own /run/acx as container uid 10001.

The api container writes describe-load.json as uid 10001 gid 999, so a
root:10001 directory is not writable and GPU start/reap timers stall.
"""

from __future__ import annotations

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
    return token.split()


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


def test_gpu_lifecycle_install_owns_run_acx_as_container_uid() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    commands = _non_comment_command_lines(text)

    assert any("chown 10001:10001 /run/acx" in line for line in commands), (
        "non-comment installer command must include 'chown 10001:10001 /run/acx'"
    )
    assert any("chmod 0775 /run/acx" in line for line in commands), (
        "non-comment installer command must include 'chmod 0775 /run/acx'"
    )
    assert any("d /run/acx 0775 10001 10001 -" in line for line in commands), (
        "non-comment tmpfiles.d line must be 'd /run/acx 0775 10001 10001 -'"
    )
    assert any("echo" in line and "0775 10001:10001" in line for line in commands), (
        "dry-run echo must contain '0775 10001:10001'"
    )
    root_owned = [line for line in commands if "root:10001" in line]
    assert root_owned == [], (
        "non-comment installer lines must not contain 'root:10001'; "
        f"found {root_owned!r}"
    )


def test_cloud_init_owns_run_acx_as_container_uid() -> None:
    """HARM-F2: cloud-init must match installer ownership of /run/acx."""
    parsed = yaml.safe_load(CLOUD_INIT.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), "cloud-init.yaml must parse to a mapping"

    write_files = parsed.get("write_files")
    assert isinstance(write_files, list), "cloud-init.yaml must define write_files"
    tmpfiles_entries = [
        item
        for item in write_files
        if isinstance(item, dict) and item.get("path") == "/etc/tmpfiles.d/acx-gpu.conf"
    ]
    assert len(tmpfiles_entries) == 1, (
        "exactly one write_files entry must have path '/etc/tmpfiles.d/acx-gpu.conf'; "
        f"found {len(tmpfiles_entries)}"
    )
    tmpfiles_content = tmpfiles_entries[0].get("content")
    assert isinstance(tmpfiles_content, str), (
        "write_files entry /etc/tmpfiles.d/acx-gpu.conf must have string content"
    )
    expected_tmpfiles_line = "d /run/acx 0775 10001 10001 -"
    tmpfiles_lines = [line.strip() for line in tmpfiles_content.splitlines() if line.strip()]
    assert expected_tmpfiles_line in tmpfiles_lines, (
        "tmpfiles.d content must contain the full line 'd /run/acx 0775 10001 10001 -'"
    )
    tmpfiles_dropins = [
        item
        for item in write_files
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and str(item["path"]).startswith("/etc/tmpfiles.d/")
    ]
    assert tmpfiles_dropins, (
        "cloud-init.yaml must write at least one /etc/tmpfiles.d/ drop-in"
    )
    for item in tmpfiles_dropins:
        dropin_path = item.get("path")
        dropin_content = item.get("content")
        assert isinstance(dropin_content, str), (
            f"write_files entry {dropin_path!r} must have string content"
        )
        for raw_line in dropin_content.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            line_tokens = stripped.split()
            if len(line_tokens) >= 2 and line_tokens[1] == "/run/acx":
                assert stripped == expected_tmpfiles_line, (
                    "every /etc/tmpfiles.d/ line whose second token is /run/acx "
                    f"must be {expected_tmpfiles_line!r}; got {stripped!r} in {dropin_path!r}"
                )

    tokens = _flatten_runcmd(parsed.get("runcmd"))
    mkdir_cmd = "mkdir -p /run/acx /etc/acx"
    chown_cmd = "chown 10001:10001 /run/acx"
    chmod_cmd = "chmod 0775 /run/acx"
    assert mkdir_cmd in tokens, (
        "runcmd must include the full command token 'mkdir -p /run/acx /etc/acx'"
    )
    mkdir_idx = tokens.index(mkdir_cmd)
    assert chown_cmd in tokens, (
        "runcmd must include the full command token 'chown 10001:10001 /run/acx'"
    )
    assert chmod_cmd in tokens, (
        "runcmd must include the full command token 'chmod 0775 /run/acx'"
    )
    chown_idx = tokens.index(chown_cmd)
    chmod_idx = tokens.index(chmod_cmd)
    assert chown_idx > mkdir_idx, (
        f"{chown_cmd!r} must appear after {mkdir_cmd!r} "
        f"(indices {chown_idx} <= {mkdir_idx})"
    )
    assert chmod_idx > mkdir_idx, (
        f"{chmod_cmd!r} must appear after {mkdir_cmd!r} "
        f"(indices {chmod_idx} <= {mkdir_idx})"
    )

    root_owned = [tok for tok in tokens if "chown root:10001" in tok]
    assert root_owned == [], (
        "runcmd must not contain 'chown root:10001'; "
        f"found {root_owned!r}"
    )
    run_acx_chowns = [
        (idx, tok) for idx, tok in enumerate(tokens) if _is_chown_of_run_acx(tok)
    ]
    assert run_acx_chowns, "runcmd must include a chown touching /run/acx"
    for idx, tok in run_acx_chowns:
        owner = _chown_owner(tok)
        assert owner == "10001:10001", (
            "chown on /run/acx must use owner 10001:10001, not "
            f"{owner!r} in {tok!r} (index {idx})"
        )
    last_chown_idx, last_chown = run_acx_chowns[-1]
    assert last_chown == chown_cmd, (
        "the last chown touching /run/acx must be "
        f"{chown_cmd!r}; got {last_chown!r} at index {last_chown_idx}"
    )

    later_destroy = [
        tok for tok in tokens[chown_idx + 1 :] if _removes_or_recreates_run_acx(tok)
    ]
    assert later_destroy == [], (
        "runcmd must not remove or recreate /run/acx after "
        f"{chown_cmd!r}; found {later_destroy!r}"
    )
