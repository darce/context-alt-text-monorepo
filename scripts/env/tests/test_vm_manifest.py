from __future__ import annotations

import json

import pytest

from conftest import load_module


def _toml_table(values: dict[str, str]) -> str:
    return "{ " + ", ".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + " }"


def _targets(
    *,
    sections: tuple[str, ...] = ("Database",),
    envs: tuple[str, ...] = ("local",),
    audience: str = "backend",
    path: str | None = None,
    example: str | None = None,
    version: int = 1,
    remote_paths: dict[str, str] | None = None,
    preserve: tuple[str, ...] | None = None,
    lease_env: dict[str, str] | None = None,
) -> str:
    lines = [
        f"version = {version}",
        "",
        "[targets.t]",
        f"audience = {json.dumps(audience)}",
        f"envs = {json.dumps(list(envs))}",
    ]
    if path is not None:
        lines.append(f"path = {json.dumps(path)}")
    if example is not None:
        lines.append(f"example = {json.dumps(example)}")
    for key, value in (("remote_paths", remote_paths), ("lease_env", lease_env)):
        if value is not None:
            lines.append(f"{key} = {_toml_table(value)}")
    if preserve is not None:
        lines.append(f"preserve = {json.dumps(list(preserve))}")
    lines.append(f"sections = {json.dumps(list(sections))}")
    return "\n".join(lines)


def _var(
    name: str,
    *,
    cls: str = "config",
    section: str = "Database",
    example: str = "example-value",
    values: dict[str, str] | None = None,
    secret: dict[str, str] | None = None,
    derive: str | None = None,
    doc: str | None = None,
    required: bool = True,
    derive_vault_map: bool = False,
) -> str:
    lines = [
        "[[var]]",
        f"name = {json.dumps(name)}",
        f"class = {json.dumps(cls)}",
        'targets = ["t"]',
        f"section = {json.dumps(section)}",
    ]
    if derive_vault_map:
        lines.append("derive_vault_map = true")
    if doc is not None:
        lines.append(f"doc = {json.dumps(doc)}")
    lines.append(f"example = {json.dumps(example)}")
    if not required:
        lines.append("required = false")
    if values is not None:
        lines.append(f"values = {_toml_table(values)}")
    if secret is not None:
        lines.append(f"secret = {_toml_table(secret)}")
    if derive is not None:
        lines.append(f"derive = {json.dumps(derive)}")
    return "\n".join(lines)


def _refused(root, fragment, key):
    manifest = load_module("manifest")
    with pytest.raises(manifest.ManifestError) as caught:
        manifest.load_manifest(root)
    message = str(caught.value)
    assert fragment in message
    assert key in message
    assert "s3cr3t-value" not in message
    assert "unknown key" not in message
    return message


OCID = "ocid1.vaultsecret.oc1.iad." + "a" * 60
OTHER_OCID = "ocid1.vaultsecret.oc1.iad." + "b" * 60
REMOTE = {env: f"/opt/acx-backend/{env}/.env" for env in ("dev", "prod")}
FRAGMENT = "10-vm.toml"


def _vm_targets(**kwargs):
    return _targets(envs=("dev", "prod"), remote_paths=REMOTE, **kwargs)


def _backend():
    return _var("RECOGNITION_SECRET_BACKEND", values={"dev": "env", "prod": "oci_vault"})


def _map_var(**kwargs):
    return _var("RECOGNITION_VAULT_SECRET_MAP", derive_vault_map=True, **kwargs)


def _boot_vars(**refs):
    return "\n".join(
        _var(name, cls="secret", secret={"dev": "host:", "prod": refs.get(name, "vault:" + ocid)})
        for name, ocid in (("RECOGNITION_ADMIN_TOKEN", OTHER_OCID), ("PGPASSWORD", OCID))
    )


def _root(write_manifest, targets, *variables):
    return write_manifest(targets, **{"10-vm": "version = 1\n" + "\n".join(variables)})


def test_target_remote_paths_loaded(write_manifest):
    mod = load_module("manifest")
    root = _root(write_manifest, _targets(envs=("dev", "prod"), remote_paths={"dev": REMOTE["dev"]},
                 preserve=("ACX_IMAGE_REPO",), lease_env={"dev": "dev"}))
    target = mod.load_manifest(root).targets["t"]
    assert target.remote_paths == {"dev": REMOTE["dev"]}
    assert target.preserve == ("ACX_IMAGE_REPO",)
    assert target.lease_env == {"dev": "dev"}


def test_target_defaults_empty(write_manifest):
    mod = load_module("manifest")
    target = mod.load_manifest(_root(write_manifest, _targets(envs=("dev", "prod")))).targets["t"]
    assert target.remote_paths == {}
    assert target.preserve == ()
    assert target.lease_env == {}


@pytest.mark.parametrize("remote_paths", [
    {"dev": "relative/.env"}, {"dev": "/etc/acx/.env"},
    {"dev": "/opt/acx-backend/../etc/.env"}, {"dev": "/opt/acx-backend//dev/.env"},
    {"staging": "/opt/acx-backend/staging/.env"},
])
def test_remote_path_refused(write_manifest, remote_paths):
    root = _root(write_manifest, _targets(envs=("dev", "prod"), remote_paths=remote_paths))
    _refused(root, "targets.toml", "t")


def test_lease_env_key_outside_remote_paths_refused(write_manifest):
    root = _root(write_manifest, _targets(envs=("dev", "prod"),
                 remote_paths={"dev": REMOTE["dev"]}, lease_env={"prod": "prod"}))
    _refused(root, "targets.toml", "t")


def test_preserve_overlapping_var_refused(write_manifest):
    root = _root(write_manifest, _vm_targets(preserve=("ACX_IMAGE_REPO",)),
                 _var("ACX_IMAGE_REPO", values={"dev": "repo", "prod": "repo"}))
    _refused(root, "targets.toml", "ACX_IMAGE_REPO")


def test_vault_and_host_refs_load(write_manifest):
    mod = load_module("manifest")
    root = _root(write_manifest, _vm_targets(), _boot_vars(), _backend(), _map_var())
    manifest = mod.load_manifest(root)
    var = next(var for var in manifest.vars if var.name == "PGPASSWORD")
    assert var.secret == {"prod": "vault:" + OCID, "dev": "host:"}
    assert next(var for var in manifest.vars if var.name == "RECOGNITION_VAULT_SECRET_MAP").derive_vault_map is True


@pytest.mark.parametrize("ref", ["vault:", "vault:ocid1.vault.oc1.iad." + "a" * 60,
                                "vault:ocid1.vaultsecret.oc1.iad.short"])
def test_bad_vault_ocid_refused(write_manifest, ref):
    root = _root(write_manifest, _vm_targets(), _boot_vars(PGPASSWORD=ref), _backend(), _map_var())
    message = _refused(root, FRAGMENT, "PGPASSWORD")
    remainder = ref.partition(":")[2]
    if remainder:
        assert remainder not in message


def test_host_ref_with_remainder_refused(write_manifest):
    root = _root(write_manifest, _vm_targets(),
                 _var("PGPASSWORD", cls="secret", secret={"dev": "host:x", "prod": "host:"}))
    _refused(root, FRAGMENT, "PGPASSWORD")


@pytest.mark.parametrize("missing", ["backend", "map"])
def test_vault_ref_requires_backend_and_map(write_manifest, missing):
    variables = [
        _var("PGPASSWORD", cls="secret", secret={"dev": "host:", "prod": "vault:" + OCID}),
        _var("RECOGNITION_ADMIN_TOKEN", cls="secret",
             secret={"dev": "host:", "prod": "vault:" + OTHER_OCID}),
    ]
    if missing != "backend":
        variables.append(_backend())
    if missing != "map":
        variables.append(_map_var())
    root = _root(write_manifest, _vm_targets(), *variables)
    _refused(root, FRAGMENT, "PGPASSWORD")


def test_oci_vault_without_vault_refs_refused(write_manifest):
    root = _root(write_manifest, _vm_targets(), _backend(), _map_var(),
                 _boot_vars(PGPASSWORD="host:", RECOGNITION_ADMIN_TOKEN="host:"))
    _refused(root, FRAGMENT, "RECOGNITION_SECRET_BACKEND")


@pytest.mark.parametrize("key", ["PGPASSWORD", "RECOGNITION_ADMIN_TOKEN"])
def test_oci_vault_requires_boot_keys(write_manifest, key):
    root = _root(write_manifest, _vm_targets(), _boot_vars(**{key: "host:"}), _backend(), _map_var())
    _refused(root, FRAGMENT, key)


@pytest.mark.parametrize("audience", ["public_build", "test"])
@pytest.mark.parametrize("ref", ["vault:" + OCID, "host:"])
def test_vault_or_host_on_public_or_test_audience_refused(write_manifest, audience, ref):
    root = _root(write_manifest, _targets(envs=("dev", "prod"), audience=audience),
                 _var("PGPASSWORD", cls="secret", secret={"dev": ref, "prod": ref}))
    _refused(root, FRAGMENT, "PGPASSWORD")


@pytest.mark.parametrize("ref", ["keychain:acx/PGPASSWORD", "env:PGPASSWORD"])
def test_keychain_or_env_on_remote_env_refused(write_manifest, ref):
    root = _root(write_manifest, _vm_targets(),
                 _var("PGPASSWORD", cls="secret", secret={"dev": ref, "prod": "host:"}))
    _refused(root, FRAGMENT, "PGPASSWORD")


def test_keychain_on_local_env_still_loads(write_manifest):
    mod = load_module("manifest")
    root = _root(write_manifest, _targets(),
                 _var("PGPASSWORD", cls="secret", secret={"local": "keychain:acx/PGPASSWORD"}))
    assert mod.load_manifest(root).vars[0].secret["local"] == "keychain:acx/PGPASSWORD"


@pytest.mark.parametrize("ref", ["host:", "vault"])
def test_derive_from_vault_or_host_refused(write_manifest, ref):
    variables = ([_boot_vars(), _backend(), _map_var()] if ref == "vault" else [
        _var("PGPASSWORD", cls="secret", secret={"dev": "host:", "prod": "host:"}),
    ])
    root = _root(write_manifest, _vm_targets(), *variables,
                 _var("POSTGRES_DSN", cls="secret", derive="postgresql://u:${PGPASSWORD}@h/db"))
    _refused(root, FRAGMENT, "POSTGRES_DSN")


@pytest.mark.parametrize("shape", [{"cls": "secret"}, {"values": {"prod": "{}"}}, {"derive": "x"}])
def test_derive_vault_map_var_shape_refused(write_manifest, shape):
    root = _root(write_manifest, _vm_targets(), _boot_vars(), _backend(), _map_var(**shape))
    _refused(root, FRAGMENT, "RECOGNITION_VAULT_SECRET_MAP")


def test_vault_secret_map_sorted_per_env(write_manifest):
    mod = load_module("manifest")
    root = _root(write_manifest, _vm_targets(), _boot_vars(), _backend(), _map_var())
    manifest = mod.load_manifest(root)
    mapping = mod.vault_secret_map(manifest, "t", "prod")
    assert mapping == {"PGPASSWORD": OCID, "RECOGNITION_ADMIN_TOKEN": OTHER_OCID}
    assert list(mapping) == ["PGPASSWORD", "RECOGNITION_ADMIN_TOKEN"]
    assert mod.vault_secret_map(manifest, "t", "dev") == {}
