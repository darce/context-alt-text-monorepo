from __future__ import annotations

import importlib
from pathlib import Path

import pytest


SECRET_OCID = "ocid1.vaultsecret.oc1.phx.aaaaaaaaaaaaaaaaaaaaaaaaaa"
FAKE_SECRET = "fake-oci-secret-value"


def _manifest_root(tmp_path: Path, *, hybrid: bool) -> Path:
    root = tmp_path / "envroot"
    manifest_dir = root / "manifest.d"
    manifest_dir.mkdir(parents=True)
    target_fields = [
        'audience = "backend"',
        'envs = ["dev"]',
        'path = "runtime.env"',
        'example = "example.env"',
        'sections = ["S"]',
    ]
    if hybrid:
        target_fields.extend([
            'remote_paths = { dev = "/opt/acx-backend/dev/.env" }',
            'lease_env = { dev = "dev" }',
        ])
    (manifest_dir / "targets.toml").write_text(
        "\n".join(["version = 1", "[targets.t]", *target_fields]) + "\n",
        encoding="utf-8",
    )
    (manifest_dir / "10-secrets.toml").write_text(
        "\n".join([
            "version = 1",
            "[[var]]",
            'name = "API_TOKEN"',
            'class = "secret"',
            'targets = ["t"]',
            'section = "S"',
            'example = "example-value"',
            f'secret = {{ dev = "oci:{SECRET_OCID}" }}',
        ]) + "\n",
        encoding="utf-8",
    )
    return root


def _resolver_spy(monkeypatch):
    render = importlib.import_module("env.render_env")
    original_render_target = render.render_target
    calls: list[tuple[str, str]] = []

    def render_with_spy(manifest, target_name, env, **kwargs):
        def resolve(var_name: str, reference: str) -> str:
            calls.append((var_name, reference))
            return FAKE_SECRET

        kwargs["resolve"] = resolve
        return original_render_target(manifest, target_name, env, **kwargs)

    monkeypatch.setattr(render, "render_target", render_with_spy)
    return render, calls


@pytest.mark.parametrize("hybrid", [False, True], ids=["local-only", "hybrid"])
@pytest.mark.parametrize("command", ["render", "check"])
def test_selected_oci_runtime_cli_fails_closed_without_resolution_or_write(
    tmp_path: Path, monkeypatch, capsys, hybrid: bool, command: str,
):
    render, calls = _resolver_spy(monkeypatch)
    root = _manifest_root(tmp_path, hybrid=hybrid)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    destination = repo_root / "runtime.env"
    original = b"existing runtime file must remain byte-for-byte unchanged\n"
    destination.write_bytes(original)

    result = render.main([
        command,
        "--root", str(root),
        "--repo-root", str(repo_root),
        "--target", "t",
        "--env", "dev",
    ])
    captured = capsys.readouterr()

    assert result == 2
    assert "oci" in captured.err.lower()
    assert "t" in captured.err
    assert SECRET_OCID not in captured.out + captured.err
    assert FAKE_SECRET not in captured.out + captured.err
    assert calls == []
    assert destination.read_bytes() == original


def test_unselected_oci_env_and_target_do_not_block_local_keychain_cli(
    tmp_path: Path, monkeypatch,
):
    render, calls = _resolver_spy(monkeypatch)
    root = tmp_path / "envroot"
    manifest_dir = root / "manifest.d"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "targets.toml").write_text(
        "\n".join([
            "version = 1",
            "[targets.t]",
            'audience = "backend"',
            'envs = ["dev", "local"]',
            'path = "runtime.env"',
            'example = "example.env"',
            'sections = ["S"]',
            'remote_paths = { dev = "/opt/acx-backend/dev/.env" }',
            'lease_env = { dev = "dev" }',
            "",
            "[targets.other]",
            'audience = "backend"',
            'envs = ["dev"]',
            'path = "other.env"',
            'sections = ["S"]',
            'remote_paths = { dev = "/opt/acx-backend/other/.env" }',
            'lease_env = { dev = "dev" }',
        ]) + "\n",
        encoding="utf-8",
    )
    (manifest_dir / "10-secrets.toml").write_text(
        "\n".join([
            "version = 1",
            "[[var]]",
            'name = "API_TOKEN"',
            'class = "secret"',
            'targets = ["t"]',
            'section = "S"',
            'example = "example-value"',
            f'secret = {{ dev = "oci:{SECRET_OCID}", local = "keychain:acx-test/API_TOKEN" }}',
            "",
            "[[var]]",
            'name = "OTHER_TOKEN"',
            'class = "secret"',
            'targets = ["other"]',
            'section = "S"',
            'example = "other-example"',
            f'secret = {{ dev = "oci:{SECRET_OCID}" }}',
        ]) + "\n",
        encoding="utf-8",
    )
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = render.main([
        "render",
        "--root", str(root),
        "--repo-root", str(repo_root),
        "--target", "t",
        "--env", "local",
    ])

    assert result == 0
    assert (repo_root / "runtime.env").read_text(encoding="utf-8").find(
        f"API_TOKEN={FAKE_SECRET}"
    ) >= 0
    assert calls == [("API_TOKEN", "keychain:acx-test/API_TOKEN")]


def test_ordinary_host_env_and_keychain_runtime_controls_remain_available(
    tmp_path: Path, monkeypatch,
):
    render, calls = _resolver_spy(monkeypatch)
    root = tmp_path / "envroot"
    manifest_dir = root / "manifest.d"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "targets.toml").write_text(
        "\n".join([
            "version = 1",
            "[targets.local]",
            'audience = "backend"',
            'envs = ["dev"]',
            'path = "local.env"',
            'sections = ["S"]',
            "",
            "[targets.remote]",
            'audience = "backend"',
            'envs = ["dev"]',
            'path = "remote.env"',
            'sections = ["S"]',
            'remote_paths = { dev = "/opt/acx-backend/dev/.env" }',
            'lease_env = { dev = "dev" }',
        ]) + "\n",
        encoding="utf-8",
    )
    (manifest_dir / "10-secrets.toml").write_text(
        "\n".join([
            "version = 1",
            "[[var]]",
            'name = "ENV_TOKEN"',
            'class = "secret"',
            'targets = ["local"]',
            'section = "S"',
            'example = "env-example"',
            'secret = { dev = "env:ACX_ENV_TOKEN" }',
            "",
            "[[var]]",
            'name = "KEYCHAIN_TOKEN"',
            'class = "secret"',
            'targets = ["local"]',
            'section = "S"',
            'example = "keychain-example"',
            'secret = { dev = "keychain:acx-test/KEYCHAIN_TOKEN" }',
            "",
            "[[var]]",
            'name = "HOST_TOKEN"',
            'class = "secret"',
            'targets = ["remote"]',
            'section = "S"',
            'example = "host-example"',
            "required = false",
            'secret = { dev = "host:" }',
        ]) + "\n",
        encoding="utf-8",
    )
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    for target in ("local", "remote"):
        args = [
            "--root", str(root), "--repo-root", str(repo_root),
            "--target", target, "--env", "dev",
        ]
        assert render.main(["render", *args]) == 0
        assert render.main(["check", *args]) == 0

    assert (repo_root / "local.env").read_text(encoding="utf-8").count(FAKE_SECRET) == 2
    assert calls == [
        ("ENV_TOKEN", "env:ACX_ENV_TOKEN"),
        ("KEYCHAIN_TOKEN", "keychain:acx-test/KEYCHAIN_TOKEN"),
        ("ENV_TOKEN", "env:ACX_ENV_TOKEN"),
        ("KEYCHAIN_TOKEN", "keychain:acx-test/KEYCHAIN_TOKEN"),
    ]


def test_example_and_all_examples_skip_runtime_oci_boundary(tmp_path: Path, monkeypatch):
    render, calls = _resolver_spy(monkeypatch)
    root = _manifest_root(tmp_path, hybrid=True)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    assert render.main([
        "render", "--root", str(root), "--repo-root", str(repo_root), "--target", "t",
    ]) == 0
    assert render.main([
        "check", "--root", str(root), "--repo-root", str(repo_root), "--target", "t",
    ]) == 0
    assert render.main([
        "render", "--root", str(root), "--repo-root", str(repo_root), "--all-examples",
    ]) == 0
    assert render.main([
        "check", "--root", str(root), "--repo-root", str(repo_root), "--all-examples",
    ]) == 0
    assert calls == []
