from __future__ import annotations

import hashlib
import json
import posixpath
import re
import sys
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, NoReturn
from urllib.parse import parse_qsl


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    name: str
    audience: str
    envs: tuple[str, ...]
    path: str | None
    example: str | None
    sections: tuple[str, ...]
    doc: str | None = None
    remote_paths: Mapping[str, str] = field(default_factory=dict)
    preserve: tuple[str, ...] = ()
    lease_env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Var:
    name: str
    cls: str
    targets: tuple[str, ...]
    section: str
    doc: str
    example: str
    required: bool
    values: Mapping[str, str]
    secret: Mapping[str, str]
    derive: str | None
    source: str
    derive_vault_map: bool = False
    required_when: Mapping[str, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class Override:
    name: str
    target: str
    example: str | None
    required: bool | None
    doc: str | None
    section: str | None
    source: str


@dataclass(frozen=True)
class Manifest:
    targets: Mapping[str, Target]
    vars: tuple[Var, ...]
    overrides: Mapping[tuple[str, str], Override] = field(default_factory=dict)


_TOP_LEVEL_TARGET_KEYS = frozenset({"version", "targets"})
_TARGET_REQUIRED_KEYS = frozenset({"audience", "envs", "sections"})
_TARGET_KEYS = _TARGET_REQUIRED_KEYS | frozenset({"path", "example", "doc", "remote_paths", "preserve", "lease_env"})
_FRAGMENT_KEYS = frozenset({"version", "var", "override"})
_VAR_REQUIRED_KEYS = frozenset({"name", "class", "targets", "section", "example"})
_VAR_KEYS = _VAR_REQUIRED_KEYS | frozenset(
    {"doc", "required", "required_when", "values", "secret", "derive", "derive_vault_map"}
)
_DERIVE_REF = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
_LITERAL_SECRET = re.compile(
    r"sk_(?:test|live)_|\brk_(?:test|live)_|whsec_|-----BEGIN"
    r"|gh[pos]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}"
    r"|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]+"
)
_PUBLIC_SENSITIVE_TOKENS = frozenset({
    "SECRET", "PASSWORD", "PASSWD", "PWD", "TOKEN", "PRIVATE", "KEY",
    "CREDENTIAL", "SIGNING", "SECRETS", "CREDENTIALS",
})
_URL_USERINFO_PASSWORD = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/?#\s@:]+:[^/?#\s@]*@")
# Each input is one env value: retain all base-check flags and add embedded URLs.
# Extra flags are acceptable, missed credentials are not.
_URL_CREDENTIAL_TOKENS = (
    "password", "passwd", "pwd", "pass", "secret", "token", "access_token",
    "api_key", "apikey", "key", "sig", "signature", "auth", "credential", "credentials",
)


def _url_query_credential(value: str) -> bool:
    first_scheme_delimiter = -1
    delimiter = value.find("://")
    while delimiter >= 0:
        position = delimiter
        has_ascii_letter = False
        while position:
            character = value[position - 1]
            if (character.isascii() and character.isalnum()) or character in "+.-":
                has_ascii_letter |= character.isascii() and character.isalpha()
                position -= 1
            else:
                break
        if has_ascii_letter and first_scheme_delimiter < 0:
            first_scheme_delimiter = delimiter
        delimiter = value.find("://", delimiter + 3)

    if first_scheme_delimiter < 0:
        return False

    query_marker = value.find("?", first_scheme_delimiter + 3)
    fragment_marker = value.find("#", first_scheme_delimiter + 3)
    markers = [marker for marker in (query_marker, fragment_marker) if marker >= 0]
    if not markers:
        return False

    # Every later URL suffix is covered by this one component suffix. Treating
    # later query/fragment markers as separators is a superset of parsing each
    # overlapping suffix and keeps the parse work bounded by the input length.
    components = value[min(markers) + 1 :].replace("?", "&").replace("#", "&")
    return any(
        key.lower().replace("-", "_").endswith(_URL_CREDENTIAL_TOKENS)
        for key, _ in parse_qsl(components, keep_blank_values=True)
    )


def _fail(source: str, key: str, detail: str) -> NoReturn:
    raise ManifestError(f"{source}: {key}: {detail}")


def _read_toml(path: Path) -> dict[str, object]:
    try:
        content = path.read_bytes().decode("utf-8")
    except OSError:
        _fail(path.name, "file", "cannot read manifest file")
    except UnicodeDecodeError:
        _fail(path.name, "TOML", "manifest file is not UTF-8")
    try:
        parsed = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        _fail(path.name, "TOML", "invalid TOML")
    return parsed


def _check_keys(
    table: Mapping[str, object],
    required: frozenset[str],
    allowed: frozenset[str],
    source: str,
    prefix: str = "",
) -> None:
    for key in sorted(required - table.keys()):
        _fail(source, f"{prefix}{key}", "missing key")
    for key in sorted(table.keys() - allowed):
        _fail(source, f"{prefix}{key}", "unknown key")


def _mapping(value: object, source: str, key: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        _fail(source, key, "must be a table")
    return value


def _string(value: object, source: str, key: str) -> str:
    if not isinstance(value, str):
        _fail(source, key, "must be a string")
    return value


def _string_list(value: object, source: str, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _fail(source, key, "must be a list of strings")
    return tuple(value)


def _string_map(value: object, source: str, key: str) -> dict[str, str]:
    if not isinstance(value, dict):
        _fail(source, key, "must be a table")
    if any(not isinstance(item_key, str) or not isinstance(item, str) for item_key, item in value.items()):
        _fail(source, key, "must map strings to strings")
    return dict(value)


def _validate_lease_env_label(value: str) -> None:
    scripts_root = str(Path(__file__).resolve().parent.parent)
    if scripts_root not in sys.path:
        sys.path.insert(0, scripts_root)
    from env.materialize import _lease_path

    _lease_path(Path("/"), value)


def _target_path(value: object, path: Path, key: str) -> str | None:
    if value is None:
        return None
    value = _string(value, path.name, key)
    normalized = posixpath.normpath(value)
    if Path(value).is_absolute() or normalized == ".." or normalized.startswith("../"):
        _fail(path.name, key, "must be relative and remain inside repo root")
    return value


def _load_targets(path: Path) -> dict[str, Target]:
    if not path.exists():
        _fail(path.name, "targets", "targets file is missing")
    raw = _read_toml(path)
    _check_keys(raw, _TOP_LEVEL_TARGET_KEYS, _TOP_LEVEL_TARGET_KEYS, path.name)
    version = raw["version"]
    if type(version) is not int or version != 1:
        _fail(path.name, "version", "unsupported manifest version")
    raw_targets = _mapping(raw["targets"], path.name, "targets")
    targets: dict[str, Target] = {}
    for name, raw_target in raw_targets.items():
        prefix = f"{name}."
        target_data = _mapping(raw_target, path.name, prefix.rstrip("."))
        _check_keys(
            target_data,
            _TARGET_REQUIRED_KEYS,
            _TARGET_KEYS,
            path.name,
            prefix,
        )
        audience = _string(target_data["audience"], path.name, f"{prefix}audience")
        if audience not in {"backend", "public_build", "test"}:
            _fail(path.name, f"{prefix}audience", "unsupported audience")
        envs = _string_list(target_data["envs"], path.name, f"{prefix}envs")
        sections = _string_list(target_data["sections"], path.name, f"{prefix}sections")
        target_path = _target_path(target_data.get("path"), path, f"{prefix}path")
        example_path = _target_path(target_data.get("example"), path, f"{prefix}example")
        doc = target_data.get("doc")
        if doc is not None:
            doc = _string(doc, path.name, f"{prefix}doc")
        remote_paths = _string_map(target_data.get("remote_paths", {}), path.name, f"{prefix}remote_paths")
        preserve = _string_list(target_data.get("preserve", []), path.name, f"{prefix}preserve")
        lease_env = _string_map(target_data.get("lease_env", {}), path.name, f"{prefix}lease_env")
        targets[name] = Target(name, audience, envs, target_path, example_path, sections, doc,
                               MappingProxyType(remote_paths), preserve, MappingProxyType(lease_env))
    _validate_targets(targets, path.name)
    return targets


def _validate_targets(targets: Mapping[str, Target], source: str) -> None:
    for target in targets.values():
        for env, remote_path in target.remote_paths.items():
            if (env not in target.envs or not remote_path.startswith("/opt/acx-backend/")
                    or posixpath.normpath(remote_path) != remote_path):
                _fail(source, f"{target.name}.remote_paths", "requires configured envs and normalized paths under /opt/acx-backend/")
        if not target.lease_env.keys() <= target.remote_paths.keys():
            _fail(source, f"{target.name}.lease_env", "envs must have remote_paths")
        for lease_env in target.lease_env.values():
            _validate_lease_env_label(lease_env)
        for section in target.sections:
            _validate_section(section, source, f"{target.name}.sections")
        _validate_doc(target.doc, source, f"{target.name}.doc")
        _validate_literal_guard(source, target.name, [("doc", target.doc)])
    for key in ("path", "example"):
        owners: dict[str, str] = {}
        for target in targets.values():
            value = getattr(target, key)
            if value is None:
                continue
            value = posixpath.normpath(value)
            if value in owners:
                _fail(source, key, f"targets {owners[value]} and {target.name} share {key}")
            owners[value] = target.name


def _load_value_source(
    table: Mapping[str, object], source: str, name: str, cls: str
) -> tuple[dict[str, str], dict[str, str], str | None]:
    source_fields = ("values", "secret", "derive")
    present_sources = [key for key in source_fields if key in table]
    derive_vault_map = table.get("derive_vault_map", False)
    if not isinstance(derive_vault_map, bool):
        _fail(source, name, "derive_vault_map must be a boolean")
    if derive_vault_map:
        if cls != "config" or present_sources:
            _fail(source, name, "derive_vault_map requires config class and no other value source")
        return {}, {}, None
    if len(present_sources) != 1:
        _fail(source, name, "requires exactly one of values, secret, or derive")
    values: dict[str, str] = {}
    secret: dict[str, str] = {}
    derive: str | None = None
    if "values" in table:
        values = _string_map(table["values"], source, f"{name}.values")
    elif "secret" in table:
        secret = _string_map(table["secret"], source, f"{name}.secret")
    else:
        derive = _string(table["derive"], source, f"{name}.derive")
    if cls == "secret" and "values" in table:
        _fail(source, f"{name}.values", "secret vars cannot define values")
    if cls != "secret" and "secret" in table:
        _fail(source, f"{name}.secret", "only secret vars can define secret refs")
    for reference in secret.values():
        scheme, separator, remainder = reference.partition(":")
        if not separator or scheme not in {"keychain", "env", "vault", "oci", "host"}:
            shown_scheme = scheme if separator else "missing"
            _fail(source, f"{name}.{shown_scheme}", "unsupported secret scheme")
        if scheme == "host" and remainder:
            _fail(source, name, "host ref must have an empty remainder")
        if scheme == "vault" and re.fullmatch(r"ocid1\.vaultsecret\.oc1\.[a-z0-9-]*\.[a-z0-9]{20,}", remainder) is None:
            _fail(source, name, "vault ref requires a valid vault secret OCID")
        if scheme == "oci" and re.fullmatch(r"ocid1\.vaultsecret\.oc1\.[a-z0-9-]+\.[a-z0-9]{20,}", remainder) is None:
            _fail(source, name, "oci ref requires a valid vault secret OCID")
    return values, secret, derive


def _validate_literal_guard(
    source: str, name: str, candidates: list[tuple[str, str | None]]
) -> None:
    for key, value in candidates:
        if value is not None and _LITERAL_SECRET.search(value):
            _fail(source, f"{name}.{key}", "literal secret material is not allowed")


def _validate_name(name: str, source: str) -> None:
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is None:
        _fail(source, name, "invalid variable name")


def _validate_section(section: str, source: str, key: str) -> None:
    if re.search(r"[\x00-\x1f\x7f]", section):
        _fail(source, key, "section contains a control character")


def _validate_doc(doc: str | None, source: str, key: str) -> None:
    if doc is not None and "\r" in doc:
        _fail(source, key, "doc contains a carriage return")


def _validate_var_fields(var: Var) -> None:
    _validate_name(var.name, var.source)
    _validate_section(var.section, var.source, f"{var.name}.section")
    _validate_doc(var.doc, var.source, f"{var.name}.doc")
    _validate_vite_secret(var)
    candidates = [(key, getattr(var, key)) for key in ("example", "derive", "doc", "section")]
    candidates.extend(("values", value) for value in var.values.values())
    _validate_literal_guard(var.source, var.name, candidates)


def _validate_vite_secret(var: Var) -> None:
    if var.cls == "secret" and var.name.startswith("VITE_"):
        _fail(var.source, var.name, "secret vars cannot use the VITE_ prefix")


def _load_var(raw: object, source: str) -> Var:
    table = _mapping(raw, source, "var")
    name_hint = table.get("name")
    name_hint = name_hint if isinstance(name_hint, str) else "var"
    _check_keys(table, _VAR_REQUIRED_KEYS, _VAR_KEYS, source, f"{name_hint}.")
    name = _string(table["name"], source, "name")
    cls = _string(table["class"], source, f"{name}.class")
    if cls not in {"public", "config", "secret"}:
        _fail(source, f"{name}.class", "unsupported class")
    targets = _string_list(table["targets"], source, f"{name}.targets")
    section = _string(table["section"], source, f"{name}.section")
    example = _string(table["example"], source, f"{name}.example")
    doc = _string(table.get("doc", ""), source, f"{name}.doc")
    required = table.get("required", True)
    if not isinstance(required, bool):
        _fail(source, f"{name}.required", "must be a boolean")
    required_when = _load_required_when(table, source, name)
    values, secret, derive = _load_value_source(table, source, name, cls)
    var = Var(
        name=name,
        cls=cls,
        targets=targets,
        section=section,
        doc=doc,
        example=example,
        required=required,
        values=MappingProxyType(values),
        secret=MappingProxyType(secret),
        derive=derive,
        source=source,
        derive_vault_map=table.get("derive_vault_map", False),
        required_when=required_when,
    )
    _validate_var_fields(var)
    return var


def _load_required_when(
    table: Mapping[str, object], source: str, name: str
) -> Mapping[str, tuple[str, ...]] | None:
    if "required_when" not in table:
        return None
    raw = _mapping(table["required_when"], source, f"{name}.required_when")
    conditions: dict[str, tuple[str, ...]] = {}
    for referenced_name, raw_values in raw.items():
        key = f"{name}.required_when.{referenced_name}"
        if not isinstance(referenced_name, str):
            _fail(source, f"{name}.required_when", "variable names must be strings")
        if not isinstance(raw_values, list):
            _fail(source, key, "must be a non-empty list of strings")
        if not raw_values:
            _fail(source, key, "list must not be empty")
        if any(not isinstance(value, str) for value in raw_values):
            _fail(source, key, "list items must be strings")
        conditions[referenced_name] = tuple(raw_values)
    return MappingProxyType(conditions)


def _load_fragments(manifest_dir: Path) -> tuple[dict[str, Var], list[Var]]:
    vars_by_name: dict[str, Var] = {}
    ordered_vars: list[Var] = []
    try:
        fragment_paths = sorted(
            path for path in manifest_dir.glob("*.toml") if path.name != "targets.toml"
        )
    except OSError:
        _fail("manifest.d", "fragments", "cannot list manifest fragments")

    for fragment_path in fragment_paths:
        source = fragment_path.name
        raw = _read_toml(fragment_path)
        _check_keys(raw, frozenset({"version"}), _FRAGMENT_KEYS, source)
        version = raw["version"]
        if type(version) is not int or version != 1:
            _fail(source, "version", "unsupported manifest version")
        raw_vars = raw.get("var", [])
        if not isinstance(raw_vars, list):
            _fail(source, "var", "must be an array of tables")
        for raw_var in raw_vars:
            var = _load_var(raw_var, source)
            if var.name in vars_by_name:
                _fail(source, var.name, "duplicate variable name")
            vars_by_name[var.name] = var
            ordered_vars.append(var)
    _validate_required_when_references(vars_by_name)
    return vars_by_name, ordered_vars


def _validate_required_when_references(vars_by_name: Mapping[str, Var]) -> None:
    for var in vars_by_name.values():
        for referenced_name in var.required_when or {}:
            referenced = vars_by_name.get(referenced_name)
            if referenced is None:
                _fail(var.source, var.name, f"required_when references unknown var {referenced_name}")
            if referenced.cls != "config":
                _fail(var.source, var.name, f"required_when var {referenced_name} must have config class")
            missing_targets = set(var.targets) - set(referenced.targets)
            if missing_targets:
                target_name = sorted(missing_targets)[0]
                _fail(
                    var.source,
                    var.name,
                    f"required_when var {referenced_name} does not target {target_name}",
                )


def effective_var(manifest: Manifest, var: Var, target_name: str) -> Var:
    override = manifest.overrides.get((var.name, target_name))
    if override is None:
        return var
    return replace(var, **{key: getattr(override, key) for key in
                           ("example", "required", "doc", "section")
                           if getattr(override, key) is not None})


def _validate_override(raw: object, source: str, targets, vars_by_name) -> Override:
    table = _mapping(raw, source, "override")
    name, target = table.get("name"), table.get("target")
    if (isinstance(name, str) and isinstance(target, str)
            and name in vars_by_name and target in vars_by_name[name].targets
            and target in targets and targets[target].audience == "public_build"):
        values = table.get("values", {})
        _validate_public_literals(source, name, (
            table.get("example"),
            *(values.values() if isinstance(values, dict) else ()),
        ))
    fields = frozenset({"example", "required", "doc", "section"})
    _check_keys(table, frozenset({"name", "target"}), fields | {"name", "target"}, source)
    name = _string(table["name"], source, "name")
    target = _string(table["target"], source, "target")
    _validate_name(name, source)
    if not fields.intersection(table):
        _fail(source, name, "override requires a field")
    if name not in vars_by_name:
        _fail(source, name, "unknown var")
    if target not in vars_by_name[name].targets:
        _fail(source, target, "override target is not a var target")
    for key in fields.intersection(table):
        if key == "required":
            if type(table[key]) is not bool:
                _fail(source, key, "must be a boolean")
        else:
            _string(table[key], source, key)
    if "section" in table and (target not in targets or table["section"] not in targets[target].sections):
        _fail(source, "section", "override section is not configured")
    _validate_override_fields(table, source, name)
    return Override(name, target, *(table.get(key) for key in
                                   ("example", "required", "doc", "section")), source)


def _validate_override_fields(table: Mapping[str, object], source: str, name: str) -> None:
    candidates = [(key, table[key]) for key in ("example", "doc", "section") if key in table]
    _validate_literal_guard(source, name, candidates)
    if "section" in table:
        _validate_section(table["section"], source, f"{name}.section")
    _validate_doc(table.get("doc"), source, f"{name}.doc")


def _load_overrides(manifest_dir, targets, vars_by_name):
    overrides = {}
    for path in sorted(manifest_dir.glob("*.toml")):
        if path.name == "targets.toml":
            continue
        rows = _read_toml(path).get("override", [])
        if not isinstance(rows, list):
            _fail(path.name, "override", "must be an array of tables")
        for row in rows:
            override = _validate_override(row, path.name, targets, vars_by_name)
            key = (override.name, override.target)
            if key in overrides:
                _fail(path.name, f"{override.name}.{override.target}", "duplicate override")
            overrides[key] = override
    return MappingProxyType(overrides)


def _validate_target_envs(manifest: Manifest) -> None:
    for var in manifest.vars:
        envs = set()
        for target_name in var.targets:
            target = manifest.targets.get(target_name)
            if target is None:
                _fail(var.source, var.name, f"unknown target {target_name}")
            if effective_var(manifest, var, target_name).section not in target.sections:
                _fail(var.source, var.name, f"section is not configured on target {target_name}")
            envs.update(target.envs)
        for source_name, env_map in (("values", var.values), ("secret", var.secret)):
            for env_name in env_map:
                if env_name not in envs:
                    _fail(var.source, var.name, f"{source_name} env {env_name} is not configured")


def _parse_derive_references(var: Var) -> tuple[str, ...]:
    if var.derive is None:
        return ()
    references = []
    position = 0
    while True:
        start = var.derive.find("$", position)
        if start == -1:
            return tuple(references)
        match = _DERIVE_REF.match(var.derive, start)
        if match is None:
            _fail(var.source, f"{var.name}.derive", "malformed derive interpolation")
        references.append(match.group(1))
        position = match.end()


def _validate_derive_references(
    vars_by_name: Mapping[str, Var],
) -> dict[str, tuple[str, ...]]:
    references: dict[str, tuple[str, ...]] = {}
    for var in vars_by_name.values():
        names = _parse_derive_references(var)
        references[var.name] = names
        for referenced_name in names:
            referenced = vars_by_name.get(referenced_name)
            if referenced is None:
                _fail(var.source, referenced_name, f"unknown var referenced by {var.name}")
            for target_name in var.targets:
                if target_name not in referenced.targets:
                    _fail(
                        var.source,
                        f"{var.name}.{referenced_name}",
                        f"referenced var does not target {target_name}",
                    )
    return references


def _validate_derive_cycles(
    vars_by_name: Mapping[str, Var], references: Mapping[str, tuple[str, ...]]
) -> None:
    visit_state: dict[str, int] = {}

    def visit(name: str) -> None:
        state = visit_state.get(name, 0)
        if state == 1:
            var = vars_by_name[name]
            _fail(var.source, name, "derive cycle")
        if state == 2:
            return
        visit_state[name] = 1
        for referenced_name in references[name]:
            visit(referenced_name)
        visit_state[name] = 2

    for name in vars_by_name:
        visit(name)


def _derive_secret_reachability(
    vars_by_name: Mapping[str, Var], references: Mapping[str, tuple[str, ...]]
) -> dict[str, bool]:
    secret_reachability: dict[str, bool] = {}

    def reaches_secret(name: str) -> bool:
        if name not in secret_reachability:
            var = vars_by_name[name]
            secret_reachability[name] = var.cls == "secret" or any(
                reaches_secret(referenced_name) for referenced_name in references[name]
            )
        return secret_reachability[name]

    for name in vars_by_name:
        reaches_secret(name)
    return secret_reachability


def _validate_derive_graph(vars_by_name: Mapping[str, Var]) -> dict[str, bool]:
    references = _validate_derive_references(vars_by_name)
    _validate_derive_cycles(vars_by_name, references)
    return _derive_secret_reachability(vars_by_name, references)


def _validate_value_sources(
    vars: tuple[Var, ...] | list[Var], reaches_secret: Mapping[str, bool]
) -> None:
    for var in vars:
        if var.derive is not None and var.cls != "secret" and reaches_secret[var.name]:
            _fail(var.source, var.name, "non-secret derive references secret material")


def _validate_public_build(
    manifest: Manifest,
    reaches_secret: Mapping[str, bool],
) -> None:
    for var in manifest.vars:
        public_targets = [name for name in var.targets
                          if manifest.targets[name].audience == "public_build"]
        if not public_targets:
            continue
        if var.cls == "secret":
            _fail(var.source, var.name, "secret vars cannot target public builds")
        if var.derive is not None and reaches_secret[var.name]:
            _fail(var.source, var.name, "public build derive reaches secret material")
        if not var.name.startswith("VITE_"):
            _fail(var.source, var.name, "public build vars must use the VITE_ prefix")
        _validate_public_name(var)
        _validate_public_literals(var.source, var.name, (var.example, *var.values.values()))
        _validate_public_urls(var)
        for target_name in public_targets:
            override = manifest.overrides.get((var.name, target_name))
            if override is not None and override.example is not None:
                _validate_public_literals(override.source, var.name, (override.example,))
                effective = effective_var(manifest, var, target_name)
                _validate_public_urls(replace(effective, source=override.source))


def _validate_public_literals(source: str, name: str, values: tuple[object, ...]) -> None:
    if any(isinstance(value, str) and "$" in value for value in values):
        _fail(source, name, "public build values cannot contain $ references")


def _validate_public_urls(var: Var) -> None:
    for value in (var.example, *var.values.values()):
        if _URL_USERINFO_PASSWORD.search(value) or _url_query_credential(value):
            _fail(var.source, var.name, "public build values cannot embed URL credentials")


def _validate_public_name(var: Var) -> None:
    tokens = var.name.split("_")
    remaining = []
    index = 0
    while index < len(tokens):
        if tokens[index:index + 2] == ["PUBLISHABLE", "KEY"]:
            index += 2
            continue
        remaining.append(tokens[index])
        index += 1
    if set(remaining) & _PUBLIC_SENSITIVE_TOKENS:
        _fail(var.source, var.name, "sensitive var name cannot target public builds")


def vault_secret_map(manifest: Manifest, target: str, env: str) -> dict[str, str]:
    return {
        var.name: var.secret[env].partition(":")[2]
        for var in sorted(manifest.vars, key=lambda item: item.name)
        if target in var.targets and var.secret.get(env, "").startswith("vault:")
    }


def _validate_remote_sources(manifest: Manifest) -> None:
    for target in manifest.targets.values():
        variables = {var.name: var for var in manifest.vars if target.name in var.targets}
        for name in target.preserve:
            if name in variables:
                _fail("targets.toml", f"{target.name}.preserve.{name}", "preserved key overlaps a target var")
        for env in target.envs:
            for var in variables.values():
                scheme = var.secret.get(env, "").partition(":")[0]
                if scheme == "host" and env not in target.remote_paths:
                    _fail(var.source, var.name, f"host secret refs require a remote path on target {target.name}")
                if scheme == "oci" and env not in target.remote_paths:
                    _fail(var.source, var.name, f"oci secret refs require a remote path on target {target.name}")
                if scheme in {"vault", "oci", "host"} and target.audience in {"public_build", "test"}:
                    _fail(var.source, var.name, f"remote secret refs are forbidden on target {target.name}")
                if scheme in {"keychain", "env"} and env in target.remote_paths:
                    _fail(var.source, var.name, f"local secret refs are forbidden on remote target {target.name}")
                for name in _parse_derive_references(var):
                    if variables[name].secret.get(env, "").partition(":")[0] in {"vault", "oci", "host"}:
                        _fail(var.source, var.name, f"derive references remote secret var {name}")
            mapping = vault_secret_map(manifest, target.name, env)
            backend = variables.get("RECOGNITION_SECRET_BACKEND")
            uses_vault = backend is not None and backend.values.get(env) == "oci_vault"
            map_var = variables.get("RECOGNITION_VAULT_SECRET_MAP")
            host_map = map_var is not None and map_var.secret.get(env) == "host:"
            # oci_vault has exactly one map source: derived Vault refs (static boot-key
            # checks) or a required host line (boot keys checked by the app at startup).
            if host_map and mapping:
                _fail(map_var.source, map_var.name, "host-preserved map cannot be mixed with vault refs")
            if mapping and (not uses_vault or not any(var.derive_vault_map for var in variables.values())):
                var = variables[next(iter(mapping))]
                _fail(var.source, var.name, "vault refs require derive_vault_map and RECOGNITION_SECRET_BACKEND = oci_vault")
            if uses_vault:
                if host_map:
                    continue
                if not mapping:
                    _fail(backend.source, backend.name, "oci_vault requires vault refs")
                for name in ("PGPASSWORD", "RECOGNITION_ADMIN_TOKEN"):
                    if name not in mapping:
                        var = variables.get(name, backend)
                        _fail(var.source, name, f"oci_vault requires a vault ref on target {target.name}")


def load_manifest(root: Path) -> Manifest:
    manifest_dir = Path(root) / "manifest.d"
    targets = _load_targets(manifest_dir / "targets.toml")
    vars_by_name, ordered_vars = _load_fragments(manifest_dir)
    overrides = _load_overrides(manifest_dir, targets, vars_by_name)
    manifest = Manifest(MappingProxyType(targets), tuple(ordered_vars), overrides)
    _validate_target_envs(manifest)
    reaches_secret = _validate_derive_graph(vars_by_name)
    _validate_remote_sources(manifest)
    _validate_value_sources(ordered_vars, reaches_secret)
    _validate_public_build(manifest, reaches_secret)

    return manifest


def target_digest(manifest: Manifest, target_name: str) -> str:
    target = manifest.targets[target_name]
    target_data = {
        "name": target.name,
        "audience": target.audience,
        "envs": target.envs,
        "path": target.path,
        "example": target.example,
        "sections": target.sections,
        "doc": target.doc,
    }
    # Keep existing example digests stable when no remote metadata is configured.
    for key in ("remote_paths", "preserve", "lease_env"):
        value = getattr(target, key)
        if value:
            target_data[key] = list(value) if key == "preserve" else dict(value)
    var_data = []
    for var in sorted(
        (item for item in manifest.vars if target_name in item.targets),
        key=lambda item: item.name,
    ):
        var = effective_var(manifest, var, target_name)
        var_data.append(
            {
                "name": var.name,
                "cls": var.cls,
                "targets": var.targets,
                "section": var.section,
                "doc": var.doc,
                "example": var.example,
                "required": var.required,
                "values": dict(var.values),
                "secret": dict(var.secret),
                "derive": var.derive,
            }
        )
        if var.derive_vault_map:
            var_data[-1]["derive_vault_map"] = True
        if var.required_when is not None:
            var_data[-1]["required_when"] = {
                name: list(values) for name, values in var.required_when.items()
            }
    encoded = json.dumps(
        {"target": target_data, "vars": var_data, "overrides": [
            {key: value for key, value in vars(override).items() if key != "source"}
            for (name, target), override in sorted(manifest.overrides.items())
            if target == target_name]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
