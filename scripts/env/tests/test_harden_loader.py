from __future__ import annotations

import json
from pathlib import Path

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
) -> str:
    lines = [
        "[[var]]",
        f"name = {json.dumps(name)}",
        f"class = {json.dumps(cls)}",
        'targets = ["t"]',
        f"section = {json.dumps(section)}",
    ]
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
    return message


@pytest.mark.parametrize("name", ["lower", "1ABC", "A-B", "A B"])
def test_harden_invalid_var_name(write_manifest, name):
    root = write_manifest(_targets(), config="version = 1\n" + _var(name, values={"local": "ok"}))
    _refused(root, "config.toml", name)


def test_harden_control_character_section(write_manifest):
    section = "Data\x07base"
    root = write_manifest(
        _targets(sections=(section,)),
        config="version = 1\n" + _var("NAME", section=section, values={"local": "ok"}),
    )
    manifest = load_module("manifest")
    with pytest.raises(manifest.ManifestError) as caught:
        manifest.load_manifest(root)
    message = str(caught.value)
    assert ("targets.toml" in message and "sections" in message) or (
        "config.toml" in message and "NAME" in message
    )


@pytest.mark.parametrize("doc", ["first\rsecond", "sk_" + "live_" + "x" * 8], ids=["carriage-return", "literal"])
def test_harden_var_doc(write_manifest, doc):
    root = write_manifest(_targets(), config="version = 1\n" + _var("NAME", doc=doc, values={"local": "ok"}))
    _refused(root, "config.toml", "NAME")


def test_harden_target_doc_literal(write_manifest):
    doc = "sk_" + "live_" + "x" * 8
    root = write_manifest(
        _targets() + "\ndoc = " + json.dumps(doc),
        config="version = 1\n" + _var("NAME", values={"local": "ok"}),
    )
    message = _refused(root, "targets.toml", "doc")
    assert "unknown" not in message.lower(), "target doc must be checked for literal material"


@pytest.mark.parametrize("example", [
    "gh" + "p_" + "a" * 36,
    "gh" + "o_" + "a" * 36,
    "gh" + "s_" + "a" * 36,
    "github_" + "pat_" + "a" * 22,
    "AK" + "IA" + "A1" * 8,
    "xox" + "b-" + "123456789",
], ids=["github-personal", "github-oauth", "github-server", "github-fine-grained", "aws", "slack"])
def test_harden_literal_patterns(write_manifest, example):
    root = write_manifest(_targets(), config="version = 1\n" + _var("NAME", example=example, values={"local": "ok"}))
    _refused(root, "config.toml", "NAME")


def test_harden_backend_vite_secret(write_manifest):
    root = write_manifest(_targets(), config="version = 1\n" + _var("VITE_SESSION", cls="secret", secret={"local": "env:SESSION"}))
    _refused(root, "config.toml", "VITE_SESSION")


@pytest.mark.parametrize("key", ["path", "example"])
def test_harden_duplicate_target_paths(write_manifest, key):
    targets = _targets(**{key: "shared.env"})
    second = targets.split("[targets.t]", 1)[1]
    root = write_manifest(targets.replace("[targets.t]", "[targets.primary]") + "\n[targets.other]\n" + second)
    message = _refused(root, "targets.toml", key)
    assert "primary" in message and "other" in message


@pytest.mark.parametrize("name", ["VITE_PASSWD", "VITE_DB_PWD", "VITE_CREDENTIAL", "VITE_KEY_ID", "VITE_SIGNING_KEY_B64"])
def test_harden_public_build_denylist(write_manifest, name):
    root = write_manifest(_targets(audience="public_build"), config="version = 1\n" + _var(name, cls="public", values={"local": "ok"}))
    _refused(root, "config.toml", name)


def test_harden_public_build_whole_token(write_manifest):
    root = write_manifest(_targets(audience="public_build"), config="version = 1\n" + _var("VITE_TOKENIZER_URL", cls="public", values={"local": "ok"}))
    manifest = load_module("manifest")
    try:
        loaded = manifest.load_manifest(root)
    except manifest.ManifestError as error:
        pytest.fail(f"whole-token guard rejected TOKENIZER: {error}")
    assert loaded.vars[0].name == "VITE_TOKENIZER_URL"


@pytest.mark.parametrize("name,audience,cls,example", [
    ("VITE_CLERK_PUBLISHABLE_KEY", "public_build", "public", "example"),
    ("VITE_MONKEY_MODE", "public_build", "public", "example"),
    ("NAME", "backend", "config", "AK" + "IA" + "SHORT"),
    ("ACX_SECRET_ROTATION_DAYS", "backend", "config", "30"),
], ids=["publishable-key", "monkey", "short-aws", "backend-config"])
def test_harden_regression_guards_still_load(write_manifest, name, audience, cls, example):
    root = write_manifest(_targets(audience=audience), config="version = 1\n" + _var(name, cls=cls, example=example, values={"local": "ok"}))
    assert load_module("manifest").load_manifest(root).vars[0].name == name


@pytest.mark.parametrize("name,allowed", [
    ("VITE_CLERK_PUBLISHABLE_KEY", True),
    ("VITE_PUBLISHABLE_SECRET_TOKEN", False),
    ("VITE_PUBLISHABLE_KEY_PASSWORD", False),
    ("VITE_PUBLISHABLE_OTHER_KEY", False),
    ("VITE_KEY_PUBLISHABLE_KEY", False),
])
def test_harden_publishable_key_exemption_is_exact(write_manifest, name, allowed):
    root = write_manifest(
        _targets(audience="public_build"),
        config="version = 1\n" + _var(name, cls="public", values={"local": "ok"}),
    )
    if allowed:
        assert load_module("manifest").load_manifest(root).vars[0].name == name
    else:
        _refused(root, "config.toml", name)


@pytest.mark.parametrize("key", ["path", "example"])
@pytest.mark.parametrize("alias", ["apps/x/./.env", "apps/x/../x/.env"])
def test_harden_normalized_duplicate_target_paths(write_manifest, key, alias):
    targets = _targets(**{key: "apps/x/.env"}).replace("[targets.t]", "[targets.primary]")
    second = _targets(**{key: alias}).split("[targets.t]", 1)[1]
    root = write_manifest(targets + "\n[targets.other]\n" + second)
    message = _refused(root, "targets.toml", key)
    assert "primary" in message and "other" in message


@pytest.mark.parametrize("key", ["path", "example"])
def test_harden_target_path_escape_in_repo_layout(tmp_path, key):
    root = tmp_path / "repo" / "config" / "env"
    mdir = root / "manifest.d"
    mdir.mkdir(parents=True)
    (mdir / "targets.toml").write_text(_targets(**{key: "../config/runtime.env"}), encoding="utf-8")
    (mdir / "config.toml").write_text("version = 1\n" + _var("NAME", values={"local": "ok"}), encoding="utf-8")
    _refused(root, "targets.toml", key)


def test_harden_target_path_inside_repo_layout_loads(tmp_path):
    root = tmp_path / "repo" / "config" / "env"
    mdir = root / "manifest.d"
    mdir.mkdir(parents=True)
    (mdir / "targets.toml").write_text(_targets(path="apps/x/.env"), encoding="utf-8")
    (mdir / "config.toml").write_text("version = 1\n" + _var("NAME", values={"local": "ok"}), encoding="utf-8")
    assert "t" in load_module("manifest").load_manifest(root).targets


@pytest.mark.parametrize("name", ["VITE_SECRETS", "VITE_CREDENTIALS", "VITE_APP_CREDENTIALS"])
def test_harden_public_build_plural_tokens(write_manifest, name):
    root = write_manifest(_targets(audience="public_build"), config="version = 1\n" + _var(name, cls="public", values={"local": "ok"}))
    _refused(root, "config.toml", name)


@pytest.mark.parametrize("field", ["values", "example"])
def test_harden_public_build_url_userinfo_refused(write_manifest, field):
    v = "https://alice:pw@api.example.com/v1"
    kwargs = {"values": {"local": v}} if field == "values" else {"example": v, "values": {"local": "ok"}}
    root = write_manifest(
        _targets(audience="public_build"),
        config="version = 1\n" + _var("VITE_API_URL", cls="public", **kwargs),
    )
    message = _refused(root, "config.toml", "VITE_API_URL")
    assert "pw@" not in message


@pytest.mark.parametrize("audience,value", [
    ("public_build", "https://api.example.com/v1"),
    ("public_build", "https://alice@api.example.com"),
    ("backend", "postgresql://acx:acx@localhost/db"),
])
def test_harden_url_userinfo_guard_scope(write_manifest, audience, value):
    name = "VITE_API_URL" if audience == "public_build" else "APP_DSN"
    cls = "public" if audience == "public_build" else "config"
    root = write_manifest(
        _targets(audience=audience),
        config="version = 1\n" + _var(name, cls=cls, example=value, values={"local": value}),
    )
    assert load_module("manifest").load_manifest(root).vars[0].name == name


@pytest.mark.parametrize("field,value", [
    ("values", "${CI_SECRET}"),
    ("values", "https://$HOST/api"),
    ("example", "${CI_SECRET}"),
])
def test_harden_public_build_value_reference_refused(write_manifest, field, value):
    kwargs = {"values": {"local": value}} if field == "values" else {
        "example": value, "values": {"local": "ok"},
    }
    root = write_manifest(
        _targets(audience="public_build"),
        config="version = 1\n" + _var("VITE_API_ORIGIN", cls="public", **kwargs),
    )
    message = _refused(root, "config.toml", "VITE_API_ORIGIN")
    assert "CI_SECRET" not in message and "HOST" not in message


def test_harden_public_build_override_reference_refused(write_manifest):
    root = write_manifest(
        _targets(audience="public_build"),
        config="version = 1\n" + _var("VITE_API_ORIGIN", cls="public", values={"local": "ok"}),
        overrides='''version = 1
var = []
[[override]]
name = "VITE_API_ORIGIN"
target = "t"
values = { local = "${CI_SECRET}" }
''',
    )
    message = _refused(root, "overrides.toml", "VITE_API_ORIGIN")
    assert "CI_SECRET" not in message


def test_harden_backend_reference_still_loads(write_manifest):
    root = write_manifest(
        _targets(audience="backend"),
        config="version = 1\n" + _var("APP_URL", values={"local": "${APP_HOST}/x"}),
    )
    manifest = load_module("manifest").load_manifest(root)
    assert manifest.vars[0].values["local"] == "${APP_HOST}/x"
