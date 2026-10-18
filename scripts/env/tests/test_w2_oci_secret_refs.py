from __future__ import annotations

import base64
import importlib
import io
import json
import stat
import subprocess
from pathlib import Path

import pytest

from conftest import load_module


SECRET_OCID = "ocid1.vaultsecret.oc1.phx.FAKE_TEST_SECRET_00000000000000000001"
FAKE_SECRET = "fake-oci-secret-value"
INTO = "/opt/acx-backend/dev/.env"


def _secret_refs():
    return importlib.import_module("env.secret_refs")


def _oci_result(value: str = FAKE_SECRET):
    content = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return json.dumps({
        "data": {
            "secret-bundle-content": {
                "content-type": "BASE64",
                "content": content,
            }
        }
    })


def test_oci_resolution_fetches_secret_bundle_with_instance_principal():
    secret_refs = _secret_refs()
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=_oci_result(), stderr="")

    assert secret_refs.resolve_secret("API_TOKEN", f"oci:{SECRET_OCID}", environ={}, runner=runner) == FAKE_SECRET
    assert calls == [(
        ["/home/ubuntu/.oci-venv/bin/oci", "secrets", "secret-bundle", "get", "--auth", "instance_principal", "--secret-id", SECRET_OCID],
        {"capture_output": True, "text": True, "check": False, "timeout": 30},
    )]


def test_oci_resolution_uses_validated_cli_override_as_argv_zero(tmp_path):
    secret_refs = _secret_refs()
    calls = []
    cli = str(tmp_path / "fake-oci-venv" / "bin" / "oci")

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=_oci_result(), stderr="")

    assert secret_refs.resolve_secret(
        "API_TOKEN", f"oci:{SECRET_OCID}", environ={"ACX_OCI_BIN": cli}, runner=runner,
    ) == FAKE_SECRET
    assert calls[0][0][0] == cli


def test_empty_oci_cli_override_uses_default_path():
    secret_refs = _secret_refs()
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=_oci_result(), stderr="")

    secret_refs.resolve_secret(
        "API_TOKEN", f"oci:{SECRET_OCID}", environ={"ACX_OCI_BIN": ""}, runner=runner,
    )
    assert calls[0][0][0] == "/home/ubuntu/.oci-venv/bin/oci"


@pytest.mark.parametrize(
    "kind",
    [
        "relative",
        "dotdot",
        "whitespace",
        "semicolon",
        "shell-metacharacter",
    ],
)
def test_invalid_oci_cli_override_is_rejected_before_runner(tmp_path, kind):
    secret_refs = _secret_refs()
    calls = []
    cli = {
        "relative": "oci",
        "dotdot": str(tmp_path / ".." / "fake-oci" / "bin" / "oci"),
        "whitespace": str(tmp_path / "fake oci" / "bin" / "oci"),
        "semicolon": str(tmp_path / "fake;oci" / "bin" / "oci"),
        "shell-metacharacter": str(tmp_path / "fake$oci" / "bin" / "oci"),
    }[kind]

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=_oci_result(), stderr="")

    with pytest.raises(secret_refs.OciCliUnavailable) as exc_info:
        secret_refs.resolve_secret(
            "API_TOKEN", f"oci:{SECRET_OCID}", environ={"ACX_OCI_BIN": cli}, runner=runner,
        )

    assert "ACX_OCI_BIN" in str(exc_info.value)
    assert "OCI CLI" in str(exc_info.value)
    assert calls == []


@pytest.mark.parametrize(
    "ref",
    [
        "oci:",
        "oci:ocid1.vaultsecret.oc1.phx.too-short",
        "oci:ocid1.vaultsecret.oc.phx.FAKE_IDENTIFIER_000000000001",
        "oci:ocid1.vaultsecret.oc1.phx.aaaaaaaaaaaaaaaaaaaaaaaaaa/extra",
    ],
)
def test_malformed_oci_identifier_is_rejected_before_cli(ref):
    secret_refs = _secret_refs()
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=_oci_result(), stderr="")

    with pytest.raises(secret_refs.SecretUnavailable) as exc_info:
        secret_refs.resolve_secret("API_TOKEN", ref, runner=runner)

    assert type(exc_info.value) is secret_refs.SecretUnavailable
    assert "API_TOKEN" in str(exc_info.value)
    assert "oci" in str(exc_info.value)
    assert calls == []


@pytest.mark.parametrize(
    "outcome",
    [
        "nonzero",
        "timeout",
        "missing-cli",
        "permission-denied",
        "not-a-directory",
        "invalid-json",
        "duplicate-json-key",
        "wrong-shape",
        "unsupported-encoding",
        "empty-content",
        "invalid-base64",
        "invalid-utf8",
    ],
)
def test_unavailable_oci_responses_are_sanitized(tmp_path, outcome):
    secret_refs = _secret_refs()
    marker = "fake-output-must-not-leak"
    cli = str(tmp_path / "missing-oci-venv" / "bin" / "oci")

    def runner(argv, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=marker, stderr=marker)
        if outcome == "missing-cli":
            raise FileNotFoundError(marker)
        if outcome == "permission-denied":
            raise PermissionError(marker)
        if outcome == "not-a-directory":
            raise NotADirectoryError(marker)
        if outcome == "nonzero":
            return subprocess.CompletedProcess(argv, 1, stdout=marker, stderr=marker)
        if outcome == "invalid-json":
            return subprocess.CompletedProcess(argv, 0, stdout=marker, stderr="")
        content_type, content = "BASE64", base64.b64encode(FAKE_SECRET.encode()).decode()
        if outcome == "duplicate-json-key":
            duplicate = (
                '{"data":{"secret-bundle-content":{"content-type":"BASE64","content":"'
                + content + '","content":"' + content + '"}}}'
            )
            return subprocess.CompletedProcess(argv, 0, stdout=duplicate, stderr="")
        if outcome == "wrong-shape":
            payload = {"data": {"content": content}}
        elif outcome == "unsupported-encoding":
            payload = {"data": {"secret-bundle-content": {"content-type": "BINARY", "content": content}}}
        elif outcome == "empty-content":
            payload = {"data": {"secret-bundle-content": {"content-type": content_type, "content": ""}}}
        elif outcome == "invalid-base64":
            payload = {"data": {"secret-bundle-content": {"content-type": content_type, "content": "%%%"}}}
        else:
            invalid_utf8 = base64.b64encode(b"\xff").decode()
            payload = {"data": {"secret-bundle-content": {"content-type": content_type, "content": invalid_utf8}}}
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")

    expected_exception = (
        secret_refs.OciCliUnavailable
        if outcome in {"missing-cli", "permission-denied", "not-a-directory"}
        else secret_refs.OciResolutionFailed
    )
    with pytest.raises(expected_exception) as exc_info:
        secret_refs.resolve_secret(
            "API_TOKEN", f"oci:{SECRET_OCID}", environ={"ACX_OCI_BIN": cli}, runner=runner,
        )

    assert "API_TOKEN" in str(exc_info.value)
    if expected_exception is secret_refs.OciCliUnavailable:
        assert "OCI CLI unavailable" in str(exc_info.value)
        assert "ACX_OCI_BIN" in str(exc_info.value)
    else:
        assert "oci" in str(exc_info.value)
    assert marker not in str(exc_info.value)
    assert marker not in repr(exc_info.value)


def _toml_table(values: dict[str, str]) -> str:
    return "{ " + ", ".join(f'{key} = {json.dumps(value)}' for key, value in values.items()) + " }"


def _oci_manifest(
    tmp_path: Path, secret_ref: str = f"oci:{SECRET_OCID}", *,
    audience: str = "backend", derive_from_secret: bool = False,
) -> Path:
    root = tmp_path / "envroot"
    manifest_dir = root / "manifest.d"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "targets.toml").write_text(
        "\n".join([
            "version = 1",
            "[targets.t]",
            f'audience = "{audience}"',
            'envs = ["dev"]',
            'sections = ["S"]',
            f"remote_paths = {_toml_table({'dev': INTO})}",
            "lease_env = { dev = \"dev\" }",
        ]) + "\n",
        encoding="utf-8",
    )
    fragment = [
        "version = 1",
        "[[var]]",
        'name = "API_TOKEN"',
        'class = "secret"',
        'targets = ["t"]',
        'section = "S"',
        'example = "example-value"',
        f"secret = {_toml_table({'dev': secret_ref})}",
    ]
    if derive_from_secret:
        fragment.extend(
            [
                "[[var]]",
                'name = "DATABASE_URL"',
                'class = "secret"',
                'targets = ["t"]',
                'section = "S"',
                'example = "example-value"',
                'derive = "postgresql://u:${API_TOKEN}@db/app"',
            ]
        )
    (manifest_dir / "10-secrets.toml").write_text(
        "\n".join(fragment) + "\n",
        encoding="utf-8",
    )
    return root


def _run_materialize(
    tmp_path, monkeypatch, *, runner, secret_ref: str = f"oci:{SECRET_OCID}",
    audience: str = "backend", derive_from_secret: bool = False, oci_bin: str | None = None,
):
    mat = load_module("materialize")
    render = load_module("render_env")
    original_render_target = render.render_target
    environment = {} if oci_bin is None else {"ACX_OCI_BIN": oci_bin}

    def render_with_fake_oci(manifest, target, env, **kwargs):
        resolve = lambda var_name, ref: _secret_refs().resolve_secret(
            var_name, ref, environ=environment, runner=runner,
        )
        return original_render_target(manifest, target, env, resolve=resolve, **kwargs)

    monkeypatch.setattr(render, "render_target", render_with_fake_oci)

    manifest_root = _oci_manifest(
        tmp_path, secret_ref, audience=audience, derive_from_secret=derive_from_secret,
    )
    fs_root = tmp_path / "fs"
    output_path = fs_root / INTO.lstrip("/")
    output_path.parent.mkdir(parents=True)
    output_path.write_text(
        render.HEADER_LINE + "\n# materialized target=t env=dev digest=x\n",
        encoding="utf-8",
    )
    output_path.chmod(0o600)
    before = output_path.read_bytes()
    out, err = io.StringIO(), io.StringIO()
    result = mat.run(
        manifest_root,
        env="dev",
        target="t",
        into=INTO,
        fs_root=fs_root,
        backup_root=tmp_path / "backups",
        lock_timeout=0.2,
        now=lambda: 1_000_000.0,
        out=out,
        err=err,
    )
    return result, output_path, before, out.getvalue(), err.getvalue()


def test_oci_secret_materializes_to_private_backend_env(tmp_path, monkeypatch):
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=_oci_result(), stderr="")

    result, output_path, _, out, err = _run_materialize(tmp_path, monkeypatch, runner=runner)

    assert result == 0
    assert "API_TOKEN=fake-oci-secret-value" in output_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert out == ""
    assert err == ""
    assert len(calls) == 1


@pytest.mark.parametrize(
    "identifier",
    [
        "ocid1.vaultsecret.oc1.phx.ABCDEFGHIJKLMNOPQRST",
        "ocid1.vaultsecret.oc1.phx.FAKE_UPPERCASE_SUFFIX_000000000001",
        "ocid1.vaultsecret.oc10.eu-fr_1.FAKE_Mixed_Underscore-Hyphen.Dot_000001",
        "ocid1.vaultsecret.oc42..FAKE_Global_Identifier.With-Dots_000001",
    ],
)
def test_accepted_grammar_materializes_through_real_loader_and_resolver(
    tmp_path, monkeypatch, identifier,
):
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=_oci_result(), stderr="")

    result, output_path, _, out, err = _run_materialize(
        tmp_path, monkeypatch, runner=runner, secret_ref=f"oci:{identifier}",
    )

    assert result == 0
    assert "API_TOKEN=fake-oci-secret-value" in output_path.read_text(encoding="utf-8")
    assert out == ""
    assert err == ""
    assert len(calls) == 1
    assert calls[0][0][-1] == identifier


@pytest.mark.parametrize("outcome", ["nonzero", "timeout", "invalid-json", "invalid-base64", "invalid-utf8"])
def test_oci_resolution_failure_materialization_exits_6_without_disclosure(tmp_path, monkeypatch, outcome):
    marker = "fake-cli-output-must-not-leak"

    def runner(argv, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=marker, stderr=marker)
        if outcome == "invalid-json":
            return subprocess.CompletedProcess(argv, 0, stdout=marker, stderr="")
        if outcome == "invalid-base64":
            payload = {"data": {"secret-bundle-content": {"content-type": "BASE64", "content": "%%%"}}}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")
        if outcome == "invalid-utf8":
            encoded = base64.b64encode(b"\xff").decode()
            payload = {"data": {"secret-bundle-content": {"content-type": "BASE64", "content": encoded}}}
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload), stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout=marker, stderr=marker)

    result, output_path, before, out, err = _run_materialize(tmp_path, monkeypatch, runner=runner)

    assert result == 6
    assert "API_TOKEN" in err
    assert "oci" in err
    assert marker not in out + err
    assert output_path.read_bytes() == before
    assert "API_TOKEN=" not in output_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600


@pytest.mark.parametrize("failure", [FileNotFoundError, PermissionError])
def test_oci_cli_unavailable_materialization_exits_5_without_disclosure(
    tmp_path, monkeypatch, failure,
):
    marker = "fake-cli-path-must-not-leak"

    def runner(argv, **kwargs):
        raise failure(marker)

    cli = str(tmp_path / "missing-oci-venv" / "bin" / "oci")
    result, output_path, before, out, err = _run_materialize(
        tmp_path, monkeypatch, runner=runner, oci_bin=cli,
    )

    assert result == 5
    assert "ACX_OCI_BIN" in err
    assert "OCI CLI" in err
    assert marker not in out + err
    assert output_path.read_bytes() == before


def test_non_oci_missing_secret_still_exits_4(tmp_path, monkeypatch):
    result, output_path, before, out, err = _run_materialize(
        tmp_path, monkeypatch, runner=lambda argv, **kwargs: pytest.fail("runner must not be called"),
        secret_ref="host:",
    )

    assert result == 4
    assert "missing host key API_TOKEN" in err
    assert output_path.read_bytes() == before
    assert out == ""


@pytest.mark.parametrize(
    ("audience", "derive_from_secret"),
    [("test", False), ("backend", True)],
)
def test_remote_oci_policy_rejection_precedes_resolver(
    tmp_path, monkeypatch, audience, derive_from_secret,
):
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=_oci_result(), stderr="")

    result, output_path, before, out, err = _run_materialize(
        tmp_path,
        monkeypatch,
        runner=runner,
        audience=audience,
        derive_from_secret=derive_from_secret,
    )

    assert result == 2
    assert calls == []
    assert output_path.read_bytes() == before
    assert out == ""
    assert "fake-oci-secret-value" not in err


def test_malformed_oci_materialization_is_refused_before_cli(tmp_path, monkeypatch):
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=_oci_result(), stderr="")

    result, output_path, before, out, err = _run_materialize(
        tmp_path, monkeypatch, runner=runner,
        secret_ref="oci:ocid1.vaultsecret.oc1..too-short",
    )

    assert result == 2
    assert "oci" in err
    assert calls == []
    assert output_path.read_bytes() == before
    assert out == ""
