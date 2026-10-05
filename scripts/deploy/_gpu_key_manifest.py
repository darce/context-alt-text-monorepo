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

    variable = _unique_gpu_key_var(document)
    if variable.get("class") != "secret" or "svc-vm" not in variable.get("targets", []):
        raise ValueError("GPU key manifest var must remain a svc-vm secret")
    refs = variable.get("secret")
    if not isinstance(refs, dict) or not {"dev", "staging", "prod"} <= refs.keys():
        raise ValueError("GPU key manifest must define dev, staging, and prod refs")


def _unique_gpu_key_var(document: dict[str, object]) -> dict[str, object]:
    variables = [
        row for row in document.get("var", [])
        if row.get("name") == "ACX_GPU_ENDPOINT_API_KEY"
    ]
    if len(variables) != 1:
        raise ValueError("GPU key manifest must contain exactly one ACX_GPU_ENDPOINT_API_KEY var")
    return variables[0]


def update_manifest_text(text: str, secret_ocid: str) -> str:
    """Return updated TOML, changing only the GPU key's dev/prod references."""
    if not _SECRET_OCID.fullmatch(secret_ocid):
        raise ValueError("refusing invalid Vault secret OCID")
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("GPU key manifest is not valid TOML") from exc
    validate_manifest_ready(document)

    return _update_gpu_key_text(text, secret_ocid)


def _update_gpu_key_text(text: str, secret_ocid: str) -> str:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("GPU key manifest is not valid TOML") from exc

    variable = _unique_gpu_key_var(document)
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


def _manifest_fragment_paths(path: Path) -> list[Path]:
    if path.is_dir():
        directory = path
        requested_fragment = None
    else:
        try:
            source_stat = path.lstat()
        except OSError as exc:
            raise ValueError("cannot read GPU key manifest") from exc
        if not stat.S_ISREG(source_stat.st_mode):
            raise ValueError("GPU key manifest must be a regular file or fragment directory")
        directory = path.parent
        requested_fragment = path

    try:
        fragments = sorted(
            fragment
            for fragment in directory.glob("*.toml")
            if fragment.name != "targets.toml"
        )
    except OSError as exc:
        raise ValueError("cannot list GPU key manifest fragments") from exc
    if not fragments or (requested_fragment is not None and requested_fragment not in fragments):
        raise ValueError("cannot read GPU key manifest")
    return fragments


def _load_manifest_fragments(
    path: Path,
) -> tuple[dict[str, object], dict[Path, tuple[str, dict[str, object]]]]:
    all_variables: list[dict[str, object]] = []
    fragments: dict[Path, tuple[str, dict[str, object]]] = {}
    for fragment_path in _manifest_fragment_paths(path):
        try:
            text = fragment_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError("cannot read GPU key manifest") from exc
        try:
            fragment = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError("GPU key manifest is not valid TOML") from exc
        fragment_variables = fragment.get("var", [])
        if not isinstance(fragment_variables, list) or any(
            not isinstance(row, dict) for row in fragment_variables
        ):
            raise ValueError("GPU key manifest var entries must be tables")
        all_variables.extend(fragment_variables)
        fragments[fragment_path] = (text, fragment)
    return {"var": all_variables}, fragments


def check_manifest_ready(path: Path) -> None:
    document, _ = _load_manifest_fragments(path)
    validate_manifest_ready(document)


def _durable_replace(path: Path, updated_text: str, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{path.name}.envman-tmp-",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
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


def persist_manifest(path: Path, updated_text: str) -> None:
    """Durably atomically replace the regular manifest file."""
    try:
        source_stat = path.lstat()
    except OSError as exc:
        raise ValueError("cannot inspect GPU key manifest") from exc
    if not stat.S_ISREG(source_stat.st_mode):
        raise ValueError("GPU key manifest must be a regular file")
    _durable_replace(path, updated_text, stat.S_IMODE(source_stat.st_mode))


def write_terraform_input(path: Path, secret_ocid: str) -> None:
    """Create a durable Terraform input file containing only the secret OCID."""
    if not _SECRET_OCID.fullmatch(secret_ocid):
        raise ValueError("refusing invalid Vault secret OCID")
    updated_text = (
        "# Generated by scripts/deploy/gpu-key-mint.sh; identifier only.\n"
        f'gpu_api_key_secret_ocid = "{secret_ocid}"\n'
    )
    try:
        source_stat = path.lstat()
    except FileNotFoundError:
        _durable_replace(path, updated_text, 0o600)
        return
    except OSError as exc:
        raise ValueError("cannot inspect Terraform GPU key input") from exc
    if not stat.S_ISREG(source_stat.st_mode):
        raise ValueError("Terraform GPU key input must be a regular file")
    try:
        existing_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError("cannot read Terraform GPU key input") from exc
    if existing_text == updated_text and stat.S_IMODE(source_stat.st_mode) == 0o600:
        return
    if existing_text != updated_text:
        raise ValueError("refusing to replace existing Terraform GPU key input")
    _durable_replace(path, updated_text, 0o600)


def set_gpu_key_ocid(path: Path, secret_ocid: str) -> None:
    """Update the manifest with the real OCID returned by the Vault writer."""
    if not _SECRET_OCID.fullmatch(secret_ocid):
        raise ValueError("refusing invalid Vault secret OCID")
    document, fragments = _load_manifest_fragments(path)
    validate_manifest_ready(document)
    owners = [
        (fragment_path, text)
        for fragment_path, (text, fragment) in fragments.items()
        if any(row.get("name") == "ACX_GPU_ENDPOINT_API_KEY" for row in fragment.get("var", []))
    ]
    if len(owners) != 1:
        raise ValueError("GPU key manifest must contain exactly one ACX_GPU_ENDPOINT_API_KEY var")
    owner_path, original = owners[0]
    updated = _update_gpu_key_text(original, secret_ocid)
    if updated != original:
        persist_manifest(owner_path, updated)


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config/env/manifest.d/10-service-shared.toml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("secret_ocid", nargs="?")
    parser.add_argument("--manifest", type=Path, default=default_manifest_path())
    parser.add_argument("--terraform-input", type=Path)
    parser.add_argument("--check-ready", action="store_true")
    args = parser.parse_args()
    if args.check_ready:
        if args.secret_ocid is not None:
            parser.error("--check-ready does not accept a secret OCID")
        if args.terraform_input is not None:
            parser.error("--check-ready does not accept a Terraform input path")
        check_manifest_ready(args.manifest)
        return 0
    if args.secret_ocid is None:
        parser.error("secret_ocid is required")
    set_gpu_key_ocid(args.manifest, args.secret_ocid)
    if args.terraform_input is not None:
        write_terraform_input(args.terraform_input, args.secret_ocid)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
