from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from env.manifest import ManifestError, load_manifest

from conftest import load_module


TARGETS = """
version = 1

[targets.vm]
audience = "backend"
envs = ["dev", "prod"]
sections = ["Runtime"]

[targets.other]
audience = "backend"
envs = ["staging"]
sections = ["Runtime"]
"""

VARS = '''
version = 1

[[var]]
name = "LOG_LEVEL"
class = "config"
targets = ["vm"]
section = "Runtime"
example = "info"
values = { dev = "info" }

[[var]]
name = "EXTRA_MODE"
class = "config"
targets = ["vm"]
section = "Runtime"
example = "safe"
values = {}

[[var]]
name = "SECRET_VALUE"
class = "secret"
targets = ["vm"]
section = "Runtime"
example = "secret"
secret = {}

[[var]]
name = "OTHER_TARGET_VALUE"
class = "config"
targets = ["other"]
section = "Runtime"
example = "other"
values = {}

[[var]]
name = "DERIVED_VALUE"
class = "config"
targets = ["vm"]
section = "Runtime"
example = "info"
derive = "${LOG_LEVEL}"

[[var]]
name = "VAULT_MAPPED"
class = "config"
targets = ["vm"]
section = "Runtime"
example = "mapped"
derive_vault_map = true
'''

WITHHELD = {
    "secret": [],
    "derived": [],
    "unmanaged": [],
    "missing": [],
    "secret_looking": [],
    "unparsed": [],
}


def _harvest(values: dict[str, str], **changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "version": 1,
        "target": "vm",
        "env": "prod",
        "values": values,
        "withheld": WITHHELD,
    }
    result.update(changes)
    return result


def _input(tmp_path: Path, content: object) -> Path:
    path = tmp_path / "harvest.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def _run(root: Path, input_path: Path, capsys, *, prefer: bool = False) -> tuple[int, str, str]:
    module = load_module("harvest_apply")
    args = ["--root", str(root)]
    if prefer:
        args.append("--prefer-harvest")
    args.append(str(input_path))
    code = module.main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def manifest_root(write_manifest) -> Path:
    return write_manifest(TARGETS, vars=VARS)


def test_apply_appends_env_in_order_and_emits_one_set_line(manifest_root, tmp_path, capsys):
    fragment = manifest_root / "manifest.d" / "vars.toml"
    original = fragment.read_bytes()
    source = _input(tmp_path, _harvest({"LOG_LEVEL": "warning"}))

    code, stdout, stderr = _run(manifest_root, source, capsys)

    assert code == 0
    assert stdout == "set\tLOG_LEVEL\tprod\n"
    assert stderr == ""
    parsed = tomllib.loads(fragment.read_text(encoding="utf-8"))
    assert parsed["var"][0]["values"] == {"dev": "info", "prod": "warning"}
    assert fragment.read_bytes() != original
    before_lines = original.decode("utf-8").splitlines()
    after_lines = fragment.read_text(encoding="utf-8").splitlines()
    changed_lines = [index for index, pair in enumerate(zip(before_lines, after_lines)) if pair[0] != pair[1]]
    assert len(changed_lines) == 1
    assert before_lines[changed_lines[0]].lstrip().startswith("values =")
    assert load_manifest(manifest_root).vars[0].values["prod"] == "warning"


@pytest.mark.parametrize(
    ("changes", "values", "expected_name"),
    [
        ({"version": 2}, {"LOG_LEVEL": "private-fake-value"}, "version"),
        ({"target": "unknown"}, {"LOG_LEVEL": "private-fake-value"}, "target"),
        ({"env": "night"}, {"LOG_LEVEL": "private-fake-value"}, "env"),
        ({"env": "staging"}, {"LOG_LEVEL": "private-fake-value"}, "env"),
        ({}, {"UNDECLARED_NAME": "private-fake-value"}, "UNDECLARED_NAME"),
        ({}, {"SECRET_VALUE": "private-fake-value"}, "SECRET_VALUE"),
        ({}, {"OTHER_TARGET_VALUE": "private-fake-value"}, "OTHER_TARGET_VALUE"),
        ({}, {"DERIVED_VALUE": "private-fake-value"}, "DERIVED_VALUE"),
        ({}, {"VAULT_MAPPED": "private-fake-value"}, "VAULT_MAPPED"),
        ({"withheld": {**WITHHELD, "secret": ["LOG_LEVEL"]}}, {"LOG_LEVEL": "private-fake-value"}, "LOG_LEVEL"),
        ({}, {"LOG_LEVEL": 7}, "LOG_LEVEL"),
        ({"withheld": {**WITHHELD, "secret": ["ZED", "ALPHA"]}}, {"LOG_LEVEL": "private-fake-value"}, "withheld"),
        ({"extra": "unexpected"}, {"LOG_LEVEL": "private-fake-value"}, "object"),
    ],
)
def test_invalid_harvest_is_refused_without_writing(
    manifest_root, tmp_path, capsys, changes, values, expected_name
):
    fragment = manifest_root / "manifest.d" / "vars.toml"
    original = fragment.read_bytes()
    source = _input(tmp_path, _harvest(values, **changes))

    code, stdout, stderr = _run(manifest_root, source, capsys)

    assert code == 2
    assert stdout == ""
    assert expected_name in stderr
    assert "private-fake-value" not in stdout + stderr
    assert fragment.read_bytes() == original


def test_conflict_refuses_without_writing_and_reports_name_only(manifest_root, tmp_path, capsys):
    fragment = manifest_root / "manifest.d" / "vars.toml"
    original = fragment.read_bytes()
    source = _input(tmp_path, _harvest({"LOG_LEVEL": "different-fake-value"}, env="dev"))

    code, stdout, stderr = _run(manifest_root, source, capsys)

    assert code == 3
    assert stdout == ""
    assert "conflict\tLOG_LEVEL\tdev" in stderr
    assert "different-fake-value" not in stderr
    assert fragment.read_bytes() == original


def test_equal_manifest_value_is_a_noop(manifest_root, tmp_path, capsys):
    fragment = manifest_root / "manifest.d" / "vars.toml"
    original = fragment.read_bytes()
    source = _input(tmp_path, _harvest({"LOG_LEVEL": "info"}, env="dev"))

    code, stdout, stderr = _run(manifest_root, source, capsys)

    assert code == 0
    assert stdout == ""
    assert stderr == ""
    assert fragment.read_bytes() == original


def test_empty_manifest_value_is_replaced_without_prefer_flag(manifest_root, tmp_path, capsys):
    fragment = manifest_root / "manifest.d" / "vars.toml"
    original = fragment.read_text(encoding="utf-8")
    fragment.write_text(original.replace('values = { dev = "info" }', 'values = { dev = "" }'), encoding="utf-8")
    source = _input(tmp_path, _harvest({"LOG_LEVEL": "info"}, env="dev"))

    code, stdout, stderr = _run(manifest_root, source, capsys)

    assert code == 0
    assert stdout == "set\tLOG_LEVEL\tdev\n"
    assert stderr == ""
    assert load_manifest(manifest_root).vars[0].values["dev"] == "info"


def test_prefer_harvest_replaces_manifest_conflict(manifest_root, tmp_path, capsys):
    fragment = manifest_root / "manifest.d" / "vars.toml"
    source = _input(tmp_path, _harvest({"LOG_LEVEL": "warning"}, env="dev"))

    code, stdout, stderr = _run(manifest_root, source, capsys, prefer=True)

    assert code == 0
    assert stdout == "set\tLOG_LEVEL\tdev\n"
    assert stderr == ""
    assert load_manifest(manifest_root).vars[0].values["dev"] == "warning"


@pytest.fixture
def shared_manifest_root(write_manifest) -> Path:
    targets = TARGETS.replace('envs = ["staging"]', 'envs = ["dev", "prod"]')
    variables = VARS.replace('targets = ["vm"]', 'targets = ["vm", "other"]')
    return write_manifest(targets, vars=variables, extra="version = 1\n")


@pytest.mark.parametrize("prefer", [False, True])
@pytest.mark.parametrize("env", ["dev", "prod"])
@pytest.mark.parametrize("reverse", [False, True])
def test_cross_input_disagreement_refuses_all_writes(
    shared_manifest_root, tmp_path, capsys, prefer, env, reverse
):
    originals = {
        path: path.read_bytes() for path in (shared_manifest_root / "manifest.d").glob("*.toml")
    }
    documents = [
        _harvest({"LOG_LEVEL": "warning", "EXTRA_MODE": "safe-new"}, env=env),
        _harvest({"LOG_LEVEL": "debug"}, target="other", env=env),
    ]
    source = _input(tmp_path, documents[::-1] if reverse else documents)

    code, stdout, stderr = _run(shared_manifest_root, source, capsys, prefer=prefer)

    assert code == 3
    assert stdout == ""
    assert stderr == f"conflict\tLOG_LEVEL\t{env}\tinputs\n"
    assert all(path.read_bytes() == original for path, original in originals.items())


@pytest.mark.parametrize("prefer, env, value, expected_code", [
    (False, "prod", "warning", 0),
    (False, "dev", "info", 0),
    (False, "dev", "warning", 3),
    (True, "dev", "warning", 0),
])
def test_identical_cross_input_values_keep_manifest_conflict_policy(
    shared_manifest_root, tmp_path, capsys, prefer, env, value, expected_code
):
    source = _input(tmp_path, [
        _harvest({"LOG_LEVEL": value}, env=env),
        _harvest({"LOG_LEVEL": value}, target="other", env=env),
    ])

    code, stdout, stderr = _run(shared_manifest_root, source, capsys, prefer=prefer)

    assert code == expected_code
    if expected_code == 3:
        assert stdout == ""
        assert stderr == f"conflict\tLOG_LEVEL\t{env}\n"
    else:
        assert stderr == ""
        assert stdout == ("" if value == "info" else f"set\tLOG_LEVEL\t{env}\n")
        assert load_manifest(shared_manifest_root).vars[0].values[env] == value


def test_toml_escaping_round_trips_backslashes_quotes_and_controls(manifest_root, tmp_path, capsys):
    value = 'a\\b"c\tline\nnext\r\x01'
    source = _input(tmp_path, _harvest({"EXTRA_MODE": value}))

    code, stdout, stderr = _run(manifest_root, source, capsys)

    assert code == 0
    assert stdout == "set\tEXTRA_MODE\tprod\n"
    assert stderr == ""
    parsed = tomllib.loads((manifest_root / "manifest.d" / "vars.toml").read_text(encoding="utf-8"))
    assert parsed["var"][1]["values"]["prod"] == value


def test_invalid_later_object_prevents_all_writes(manifest_root, tmp_path, capsys):
    fragment = manifest_root / "manifest.d" / "vars.toml"
    original = fragment.read_bytes()
    valid = _harvest({"EXTRA_MODE": "safe-new"})
    invalid = _harvest({"UNDECLARED_NAME": "private-fake-value"}, env="dev")
    source = _input(tmp_path, [valid, invalid])

    code, stdout, stderr = _run(manifest_root, source, capsys)

    assert code == 2
    assert stdout == ""
    assert "UNDECLARED_NAME" in stderr
    assert "private-fake-value" not in stderr
    assert fragment.read_bytes() == original


def test_secret_looking_value_is_refused_without_printing_value(manifest_root, tmp_path, capsys):
    fragment = manifest_root / "manifest.d" / "vars.toml"
    original = fragment.read_bytes()
    fake_secret = "sk_test_FAKE_VALUE"
    source = _input(tmp_path, _harvest({"LOG_LEVEL": fake_secret}))

    code, stdout, stderr = _run(manifest_root, source, capsys)

    assert code == 2
    assert stdout == ""
    assert "LOG_LEVEL" in stderr
    assert fake_secret not in stderr
    assert fragment.read_bytes() == original


@pytest.mark.parametrize("value", [
    "https://example.test/x?token=fake",
    "https://example.test/x#access_token=fake",
])
def test_query_credentials_are_refused_without_any_writes(manifest_root, tmp_path, capsys, value):
    originals = {path: path.read_bytes() for path in (manifest_root / "manifest.d").glob("*.toml")}
    source = _input(tmp_path, _harvest({"LOG_LEVEL": value, "EXTRA_MODE": "safe-new"}))

    code, stdout, stderr = _run(manifest_root, source, capsys)

    assert code == 2
    assert stdout == ""
    assert "LOG_LEVEL" in stderr
    assert value not in stdout + stderr
    assert {path: path.read_bytes() for path in originals} == originals


def test_extract_to_apply_preserves_empty_and_inline_comment_values(manifest_root, tmp_path, capsys):
    module = load_module("harvest_extract")
    targets = manifest_root / "manifest.d" / "targets.toml"
    targets.write_text(
        targets.read_text(encoding="utf-8").replace(
            '[targets.vm]\n',
            '[targets.vm]\nremote_paths = { prod = "/opt/acx-backend/prod/.env" }\n',
        ),
        encoding="utf-8",
    )
    env_path = tmp_path / "opt/acx-backend/prod/.env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(
        "EXTRA_MODE=\nLOG_LEVEL=https://example.test # endpoint\n", encoding="utf-8",
    )
    assert module.main([
        "--root", str(manifest_root), "--target", "vm", "--env", "prod",
        "--fs-root", str(tmp_path),
    ]) == 0
    extracted = capsys.readouterr()
    assert extracted.err == ""
    assert "endpoint" not in extracted.out
    source = _input(tmp_path, json.loads(extracted.out))

    code, stdout, stderr = _run(manifest_root, source, capsys)

    assert code == 0
    assert stderr == ""
    variables = {var.name: var for var in load_manifest(manifest_root).vars}
    assert variables["EXTRA_MODE"].values["prod"] == ""
    assert variables["LOG_LEVEL"].values["prod"] == "https://example.test"
    assert "endpoint" not in stdout + stderr


def test_multiline_values_table_is_refused_without_writing(manifest_root, tmp_path, capsys):
    fragment = manifest_root / "manifest.d" / "vars.toml"
    original = fragment.read_text(encoding="utf-8")
    fragment.write_text(original.replace('values = { dev = "info" }', '[var.values]\ndev = "info"'), encoding="utf-8")
    before = fragment.read_bytes()
    source = _input(tmp_path, _harvest({"LOG_LEVEL": "warning"}, env="dev"))

    code, stdout, stderr = _run(manifest_root, source, capsys)

    assert code == 2
    assert stdout == ""
    assert "LOG_LEVEL" in stderr
    assert "single-line" in stderr
    assert fragment.read_bytes() == before


def test_post_write_load_failure_restores_every_fragment_byte_for_byte(
    manifest_root, tmp_path, capsys, monkeypatch
):
    vars_fragment = manifest_root / "manifest.d" / "vars.toml"
    other_fragment = manifest_root / "manifest.d" / "extra.toml"
    other_fragment.write_text(
        '''version = 1
[[var]]
name = "SECOND_VALUE"
class = "config"
targets = ["vm"]
section = "Runtime"
example = "safe"
values = {}
''',
        encoding="utf-8",
    )
    original = {vars_fragment: vars_fragment.read_bytes(), other_fragment: other_fragment.read_bytes()}
    source = _input(tmp_path, _harvest({"LOG_LEVEL": "warning", "SECOND_VALUE": "safe-new"}))
    module = load_module("harvest_apply")
    real_load_manifest = load_manifest
    calls = 0

    def fail_after_write(root: Path):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_load_manifest(root)
        raise ManifestError("forced validation failure")

    monkeypatch.setattr(module, "load_manifest", fail_after_write)
    code = module.main(["--root", str(manifest_root), str(source)])
    captured = capsys.readouterr()

    assert calls == 2
    assert code == 2
    assert captured.out == ""
    assert "reload failed" in captured.err
    assert "warning" not in captured.err
    assert {path: path.read_bytes() for path in original} == original
