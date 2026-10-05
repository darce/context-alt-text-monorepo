#!/usr/bin/env python3
"""Persist a minted GPU Vault secret OCID into its manifest refs."""

from __future__ import annotations

import argparse
import os
import re
import stat
import tempfile
import tomllib
from pathlib import Path


_SECRET_OCID = re.compile(r"^ocid1\.vaultsecret\.oc[0-9]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9._-]+$")
_TABLE_HEADER = re.compile(r"(?m)^\[\[[^\]]+\]\][ \t]*$")
_VAR_HEADER = re.compile(r"(?m)^\[\[var\]\][ \t]*$")
_SECRET_LINE = re.compile(r"(?m)^secret\s*=\s*\{[^\n]*\}$")


def _replace_env_ref(secret_line: str, env: str, value: str) -> str:
    pattern = re.compile(rf"(?<![A-Za-z0-9_])({re.escape(env)}\s*=\s*)\"[^\"]*\"")
    updated, count = pattern.subn(rf'\g<1>"{value}"', secret_line)
    if count != 1:
        raise ValueError(f"GPU key manifest must contain exactly one {env} secret ref")
    return updated


def validate_manifest_ready(document: dict[str, object]) -> None:
    """Require the derived four-secret prod map before any GPU key mutation."""
    maps = [row for row in document.get("var", []) if row.get("name") == "RECOGNITION_VAULT_SECRET_MAP"]
    if len(maps) != 1:
        raise ValueError("GPU mint requires one RECOGNITION_VAULT_SECRET_MAP var")
    map_var = maps[0]
    if (
        map_var.get("class") != "config"
        or map_var.get("derive_vault_map") is not True
        or "svc-vm" not in map_var.get("targets", [])
    ):
        raise ValueError("GPU mint requires the svc-vm derived Vault secret map")

    required_names = ("PGPASSWORD", "POSTGRES_DSN", "POSTGRES_SYNC_DSN", "RECOGNITION_ADMIN_TOKEN")
    for name in required_names:
        refs = [row for row in document.get("var", []) if row.get("name") == name]
        if len(refs) != 1 or "svc-vm" not in refs[0].get("targets", []):
            raise ValueError(f"GPU mint requires a svc-vm {name} Vault ref")
        secret_refs = refs[0].get("secret")
        if not isinstance(secret_refs, dict):
            raise ValueError(f"GPU mint requires a prod Vault ref for {name}")
        reference = secret_refs.get("prod", "")
        scheme, separator, ocid = reference.partition(":")
        if scheme != "vault" or not separator or not _SECRET_OCID.fullmatch(ocid):
            raise ValueError(f"GPU mint requires a real prod vault ref for {name}")


def update_manifest_text(text: str, secret_ocid: str) -> str:
    """Return updated TOML, changing only the GPU key's dev/prod references."""
    if not _SECRET_OCID.fullmatch(secret_ocid):
        raise ValueError("refusing invalid Vault secret OCID")
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("GPU key manifest is not valid TOML") from exc
    validate_manifest_ready(document)

    variables = [row for row in document.get("var", []) if row.get("name") == "ACX_GPU_ENDPOINT_API_KEY"]
    if len(variables) != 1:
        raise ValueError("GPU key manifest must contain exactly one ACX_GPU_ENDPOINT_API_KEY var")
    variable = variables[0]
    if variable.get("class") != "secret" or "svc-vm" not in variable.get("targets", []):
        raise ValueError("GPU key manifest var must remain a svc-vm secret")

    refs = variable.get("secret")
    if not isinstance(refs, dict) or not {"dev", "staging", "prod"} <= refs.keys():
        raise ValueError("GPU key manifest must define dev, staging, and prod refs")
    expected_refs = {"dev": f"oci:{secret_ocid}", "prod": f"vault:{secret_ocid}"}
    for env, expected in expected_refs.items():
        if refs[env] not in {"host:", expected}:
            raise ValueError(f"refusing to replace existing {env} GPU key ref")

    matches = list(_VAR_HEADER.finditer(text))
    blocks = []
    for match in matches:
        end = _TABLE_HEADER.search(text, match.end())
        block_end = end.start() if end is not None else len(text)
        block = text[match.start():block_end]
        try:
            parsed = tomllib.loads(block)
        except tomllib.TOMLDecodeError:
            continue
        row = parsed.get("var", [{}])[0]
        if row.get("name") == "ACX_GPU_ENDPOINT_API_KEY":
            blocks.append((match.start(), block_end, block))
    if len(blocks) != 1:
        raise ValueError("could not isolate GPU key manifest var")

    start, end, block = blocks[0]
    secret_lines = list(_SECRET_LINE.finditer(block))
    if len(secret_lines) != 1:
        raise ValueError("GPU key manifest var must contain one inline secret map")
    secret_line = secret_lines[0].group(0)
    for env, expected in expected_refs.items():
        scheme, _, existing_ocid = refs[env].partition(":")
        if scheme == "host":
            secret_line = _replace_env_ref(secret_line, env, expected)
        elif existing_ocid != secret_ocid:
            raise ValueError(f"refusing to replace existing {env} GPU key OCID")
    updated_block = block[:secret_lines[0].start()] + secret_line + block[secret_lines[0].end():]
    return text[:start] + updated_block + text[end:]


def check_manifest_ready(path: Path) -> None:
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError("cannot read GPU key manifest") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("GPU key manifest is not valid TOML") from exc
    validate_manifest_ready(document)


def persist_manifest(path: Path, updated_text: str) -> None:
    """Durably atomically replace the regular manifest file."""
    try:
        source_stat = path.lstat()
    except OSError as exc:
        raise ValueError("cannot inspect GPU key manifest") from exc
    if not stat.S_ISREG(source_stat.st_mode):
        raise ValueError("GPU key manifest must be a regular file")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{path.name}.envman-tmp-",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IMODE(source_stat.st_mode))
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            descriptor = -1
            stream.write(updated_text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def set_gpu_key_ocid(path: Path, secret_ocid: str) -> None:
    """Update the manifest with the real OCID returned by the Vault writer."""
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError("cannot read GPU key manifest") from exc
    updated = update_manifest_text(original, secret_ocid)
    if updated != original:
        persist_manifest(path, updated)


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config/env/manifest.d/10-service-shared.toml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("secret_ocid", nargs="?")
    parser.add_argument("--manifest", type=Path, default=default_manifest_path())
    parser.add_argument("--check-ready", action="store_true")
    args = parser.parse_args()
    if args.check_ready:
        if args.secret_ocid is not None:
            parser.error("--check-ready does not accept a secret OCID")
        check_manifest_ready(args.manifest)
        return 0
    if args.secret_ocid is None:
        parser.error("secret_ocid is required")
    set_gpu_key_ocid(args.manifest, args.secret_ocid)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
