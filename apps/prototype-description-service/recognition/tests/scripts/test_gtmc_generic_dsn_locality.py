"""Generic tenant CLI locality contracts; settings are stubbed and no connection is opened."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_APP_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_HOSTS = [
    pytest.param("127.0.0.2", id="loopback-v4"),
    pytest.param("127.255.255.254", id="loopback-v4-range"),
    pytest.param("[::1]", id="loopback-v6"),
    pytest.param("0.0.0.0", id="unspecified-v4"),
    pytest.param("[::]", id="unspecified-v6"),
    pytest.param("[::ffff:127.0.0.1]", id="mapped-loopback"),
    pytest.param("[::ffff:0.0.0.0]", id="mapped-unspecified"),
    pytest.param("[::FFFF:7f00:2]", id="mapped-loopback-hex"),
    pytest.param("app.localhost", id="localhost-subdomain"),
    pytest.param("APP.LOCALHOST.", id="localhost-subdomain-case-dot"),
    pytest.param("LoCaLhOsT.", id="localhost-case-dot"),
    pytest.param("app.local", id="local-suffix"),
    pytest.param("APP.LOCAL.", id="local-suffix-case-dot"),
    pytest.param("127.0.0.2.", id="loopback-trailing-dot"),
]
_REMOTE_HOSTS = [
    pytest.param("postgres", id="compose-postgres"),
    pytest.param("db.example.invalid", id="remote-name"),
    pytest.param("POSTGRES.", id="compose-case-dot"),
    pytest.param("192.0.2.1", id="remote-v4"),
    pytest.param("[2001:db8::1]", id="remote-v6"),
    pytest.param("[::ffff:192.0.2.1]", id="mapped-remote"),
    pytest.param("localhost.example.invalid", id="localhost-prefix-only"),
]


@pytest.fixture(params=["manage_api_keys", "manage_portal_invitations"], ids=["api", "portal"])
def cli(request):
    path = _APP_ROOT / "scripts" / f"{request.param}.py"
    spec = importlib.util.spec_from_file_location(f"gtmc_generic_{request.param}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dsn(host: str, query: str = "") -> str:
    return f"postgresql+asyncpg://fixture:fixture@{host}/fixture" + (f"?{query}" if query else "")


def _settings(monkeypatch, dsn: str, configured_env: str | None = None) -> list[str]:
    from db import settings

    if configured_env is None:
        monkeypatch.delenv("ACX_ENV", raising=False)
    else:
        monkeypatch.setenv("ACX_ENV", configured_env)
    reads = []

    def read_settings():
        reads.append("settings")
        return SimpleNamespace(postgres_dsn=dsn)

    monkeypatch.setattr(settings, "get_database_settings", read_settings)
    return reads


@pytest.mark.parametrize("host", _LOCAL_HOSTS)
@pytest.mark.parametrize("configured_env", [None, "prod"], ids=["unset", "matched"])
def test_prod_refuses_every_local_host(cli, monkeypatch, host, configured_env) -> None:
    reads = _settings(monkeypatch, _dsn(host), configured_env)
    refusal = cli._validate_runtime_env("prod")
    assert refusal is not None, "prod must refuse local effective targets"
    assert "looks local; refusing to run" in refusal
    assert reads == ["settings"]


@pytest.mark.parametrize("host", _LOCAL_HOSTS)
@pytest.mark.parametrize("env", ["dev", "local"])
def test_dev_local_accept_every_local_host(cli, monkeypatch, host, env) -> None:
    reads = _settings(monkeypatch, _dsn(host))
    assert cli._validate_runtime_env(env) is None
    assert reads == ["settings"]


@pytest.mark.parametrize("host", _REMOTE_HOSTS)
@pytest.mark.parametrize("configured_env", [None, "prod"], ids=["unset", "matched"])
def test_prod_accepts_nonlocal_service_and_remote_hosts(cli, monkeypatch, host, configured_env) -> None:
    reads = _settings(monkeypatch, _dsn(host), configured_env)
    assert cli._validate_runtime_env("prod") is None
    assert reads == ["settings"]


@pytest.mark.parametrize("host", _REMOTE_HOSTS)
@pytest.mark.parametrize("env", ["dev", "local"])
def test_dsn_only_dev_local_refuse_nonlocal_hosts(cli, monkeypatch, host, env) -> None:
    _settings(monkeypatch, _dsn(host))
    refusal = cli._validate_runtime_env(env)
    assert refusal is not None
    assert "refusing to run" in refusal


@pytest.mark.parametrize("key", ["host", "hostaddr", "port", "dsn", "service", "servicefile", "user", "username", "database", "dbname", "options"])
@pytest.mark.parametrize("uppercase", [False, True], ids=["lowercase", "uppercase"])
@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_identity_query_keys_are_refused(cli, monkeypatch, key, uppercase, env) -> None:
    host = "db.example.invalid" if env == "prod" else "localhost"
    query = f"{key.upper() if uppercase else key}=127.0.0.1"
    reads = _settings(monkeypatch, _dsn(host, query), "prod" if env == "prod" else None)
    refusal = cli._validate_runtime_env(env)
    assert refusal is not None, "connection query overrides must be refused before choosing a host"
    assert "DSN query overrides the connection identity or endpoint; refusing to run" in refusal
    assert "127.0.0.1" not in refusal
    assert reads == ["settings"]


@pytest.mark.parametrize("query", [
    pytest.param("host=db.example.invalid&host=127.0.0.1", id="duplicate-host"),
    pytest.param("h%6fst=127.0.0.1", id="encoded-host-key"),
    pytest.param("host=", id="empty-host-value"),
])
@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_duplicate_encoded_and_empty_query_overrides_are_refused(cli, monkeypatch, query, env) -> None:
    host = "db.example.invalid" if env == "prod" else "localhost"
    _settings(monkeypatch, _dsn(host, query), "prod" if env == "prod" else None)
    refusal = cli._validate_runtime_env(env)
    assert refusal is not None
    assert "DSN query overrides" in refusal


@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_nonidentity_query_preserves_locality_admission(cli, monkeypatch, env) -> None:
    host = "postgres" if env == "prod" else "app.localhost"
    _settings(monkeypatch, _dsn(host, "application_name=locality-contract"))
    assert cli._validate_runtime_env(env) is None


@pytest.mark.parametrize("env", ["prod", "dev", "local"])
@pytest.mark.parametrize("host", ["", "localhost,db.example.invalid", "db.example.invalid,localhost", "db example.invalid"])
def test_missing_or_ambiguous_host_is_refused(cli, monkeypatch, env, host) -> None:
    _settings(monkeypatch, _dsn(host), "prod" if env == "prod" else None)
    refusal = cli._validate_runtime_env(env)
    assert refusal is not None
    assert "refusing to run" in refusal


@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_malformed_dsn_refusal_is_credential_free(cli, monkeypatch, env) -> None:
    _settings(monkeypatch, "postgresql+asyncpg://fixture:fixture@[broken/fixture")
    refusal = cli._validate_runtime_env(env)
    assert refusal is not None
    assert "DSN is malformed; refusing to run" in refusal
    assert "fixture" not in refusal


@pytest.mark.parametrize("env", ["dev", "local"])
@pytest.mark.parametrize("host", ["127.0.0.2", "app.localhost"])
def test_matched_dev_local_preserve_settings_policy(cli, monkeypatch, env, host) -> None:
    reads = _settings(monkeypatch, _dsn(host), env)
    assert cli._validate_runtime_env(env) is None
    assert reads == (["settings"] if cli.__name__.endswith("manage_api_keys") else [])


@pytest.mark.parametrize("userinfo_suffix,path_suffix", [
    pytest.param("#marker", "", id="userinfo-fragment"),
    pytest.param("?marker", "", id="userinfo-query"),
    pytest.param("", "#marker", id="path-fragment"),
])
@pytest.mark.parametrize("query", [
    pytest.param("host=127.0.0.1", id="single-host"),
    pytest.param("host=db.example.invalid&host=127.0.0.1", id="repeated-host"),
])
@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_parser_differential_query_overrides_are_refused(
    cli, monkeypatch, userinfo_suffix, path_suffix, query, env,
) -> None:
    host = "db.example.invalid" if env == "prod" else "localhost"
    dsn = f"postgresql+asyncpg://fixture:fixture{userinfo_suffix}@{host}/fixture{path_suffix}?{query}"
    reads = _settings(monkeypatch, dsn, "prod" if env == "prod" else None)
    refusal = cli._validate_runtime_env(env)
    assert refusal == f"env={env}: DSN query overrides the connection identity or endpoint; refusing to run"
    assert reads == ["settings"]


@pytest.mark.parametrize("env", ["dev", "local"])
def test_clean_local_dsn_control_is_admitted(cli, monkeypatch, env) -> None:
    reads = _settings(monkeypatch, _dsn("localhost"))
    assert cli._validate_runtime_env(env) is None
    assert reads == ["settings"]


# GTMC-C80A-I77-N2: numeric-only resolution must cover libc's legacy and IDNA forms.
@pytest.mark.parametrize("host", ["2130706433", "0177.0.0.1", "0x7f.0.0.1", "127.1", "0", "１２７.0.0.1"])
def test_numeric_loopback_forms_are_refused(cli, monkeypatch, host) -> None:
    _settings(monkeypatch, _dsn(host), "prod")
    refusal = cli._validate_runtime_env("prod")
    assert refusal is not None, "numeric loopback must be refused"
    assert "looks local; refusing to run" in refusal


@pytest.mark.parametrize("host", ["2130706433", "0177.0.0.1", "0x7f.0.0.1", "127.1", "0", "１２７.0.0.1"])
def test_aura_numeric_loopback_forms_are_refused(host) -> None:
    from scripts._aura_target_guard import validate_aura_target

    refusal = validate_aura_target(
        "prod-auraface", configured_env="prod-auraface", compose_project="acx-prod-auraface",
        read_dsn=lambda: f"postgresql+asyncpg://acx_prod_auraface@{host}/alt_context_prod_auraface",
    )
    assert refusal is not None, "Aura must also refuse numeric loopback"
    assert "looks local; refusing to run" in refusal


# N4 pins the normalization used by the matched Compose exception.
@pytest.mark.parametrize("env", ["dev", "staging", "dev-fir"])
@pytest.mark.parametrize("host", ["POSTGRES", "postgres.", "PoStGrEs."])
def test_api_matched_compose_host_normalization(monkeypatch, env, host) -> None:
    from scripts import manage_api_keys

    _settings(monkeypatch, _dsn(host), env)
    assert manage_api_keys._validate_runtime_env(env) is None


def test_numeric_resolution_never_uses_dns(monkeypatch) -> None:
    import socket
    from scripts._aura_target_guard import is_local_host

    real_getaddrinfo = socket.getaddrinfo
    calls = []

    def numeric_only(host, port, *args, **kwargs):
        assert kwargs.get("flags") == socket.AI_NUMERICHOST
        calls.append(host)
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", numeric_only)
    assert is_local_host("2130706433")
    assert not is_local_host("192.0.2.1")
    assert not is_local_host("db.example.invalid")
    assert calls == ["2130706433", "db.example.invalid"]


def test_guard_documents_explicit_port() -> None:
    from scripts import _aura_target_guard

    assert "omitted port" in _aura_target_guard.__doc__
    assert "explicit settings" in _aura_target_guard.__doc__


def test_guard_documents_name_resolution_limit() -> None:
    from scripts import _aura_target_guard

    assert "DNS-to-loopback" in _aura_target_guard.__doc__
