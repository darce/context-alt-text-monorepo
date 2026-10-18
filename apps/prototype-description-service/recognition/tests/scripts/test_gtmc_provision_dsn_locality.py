"""Offline locality regressions for provisioning and expiry CLIs."""

import importlib

import pytest

from recognition.tests.scripts.test_gtmc_generic_dsn_locality import (
    test_numeric_loopback_forms_are_refused as _generic_numeric_contract,
)


_NUMERIC_LOCAL_HOSTS = next(
    mark.args[1]
    for mark in _generic_numeric_contract.pytestmark
    if mark.name == "parametrize" and mark.args[0] == "host"
)


@pytest.fixture(params=["provision_customer", "provision_demo", "sweep_expired_demos"])
def cli(request):
    return importlib.import_module(f"scripts.{request.param}")


def _dsn(host, query=""):
    return f"postgresql+asyncpg://fixture:fixture@{host}/fixture" + (f"?{query}" if query else "")


@pytest.mark.parametrize("host", _NUMERIC_LOCAL_HOSTS)
def test_numeric_loopback_forms_are_refused(cli, host):
    refusal = cli._validate_env_vs_dsn("prod", _dsn(host))
    assert refusal is not None, "numeric loopback must be refused"
    assert "looks local; refusing to run" in refusal


@pytest.mark.parametrize("host", [
    "localhost", "127.0.0.1", "127.0.0.2", "127.255.255.254", "[::1]",
    "0.0.0.0", "[::]", "[::ffff:127.0.0.1]", "[::ffff:0.0.0.0]",
    "[::FFFF:7f00:2]", "app.localhost", "APP.LOCALHOST.", "LoCaLhOsT.",
    "app.local", "APP.LOCAL.", "127.0.0.2.",
])
@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_local_targets(cli, host, env):
    refusal = cli._validate_env_vs_dsn(env, _dsn(host))
    if env == "prod":
        assert refusal is not None, "prod must refuse local effective targets"
        assert "looks local; refusing to run" in refusal
    else:
        assert refusal is None


@pytest.mark.parametrize("host", [
    "postgres", "POSTGRES.", "db.example.invalid", "192.0.2.1",
    "[2001:db8::1]", "[::ffff:192.0.2.1]", "localhost.example.invalid",
])
@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_remote_targets(cli, host, env):
    refusal = cli._validate_env_vs_dsn(env, _dsn(host))
    if env == "prod":
        assert refusal is None
    else:
        assert refusal is not None
        assert "is not a local host; refusing to run" in refusal


@pytest.mark.parametrize("key", [
    "host", "hostaddr", "port", "dsn", "service", "servicefile", "user",
    "username", "database", "dbname", "options",
])
@pytest.mark.parametrize("uppercase", [False, True])
@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_identity_query_overrides(cli, key, uppercase, env):
    host = "db.example.invalid" if env == "prod" else "localhost"
    query = f"{key.upper() if uppercase else key}=127.0.0.1"
    assert cli._validate_env_vs_dsn(env, _dsn(host, query)) == (
        f"env={env}: DSN query overrides the connection identity or endpoint; refusing to run"
    )


@pytest.mark.parametrize("query", [
    "host=db.example.invalid&host=127.0.0.1", "h%6fst=127.0.0.1", "host=",
])
@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_duplicate_encoded_empty_overrides(cli, query, env):
    host = "db.example.invalid" if env == "prod" else "localhost"
    assert cli._validate_env_vs_dsn(env, _dsn(host, query)) == (
        f"env={env}: DSN query overrides the connection identity or endpoint; refusing to run"
    )


@pytest.mark.parametrize("userinfo_suffix,path_suffix", [
    ("#marker", ""), ("?marker", ""), ("", "#marker"),
])
@pytest.mark.parametrize("query", ["host=127.0.0.1", "host=db.example.invalid&host=127.0.0.1"])
@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_parser_differential_overrides(cli, userinfo_suffix, path_suffix, query, env):
    host = "db.example.invalid" if env == "prod" else "localhost"
    dsn = f"postgresql+asyncpg://fixture:fixture{userinfo_suffix}@{host}/fixture{path_suffix}?{query}"
    assert cli._validate_env_vs_dsn(env, dsn) == (
        f"env={env}: DSN query overrides the connection identity or endpoint; refusing to run"
    )


@pytest.mark.parametrize("host", ["", "localhost,db.example.invalid", "db.example.invalid,localhost", "db example.invalid"])
@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_missing_ambiguous_host(cli, host, env):
    refusal = cli._validate_env_vs_dsn(env, _dsn(host))
    assert refusal is not None
    assert "refusing to run" in refusal


@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_malformed_dsn(cli, env):
    refusal = cli._validate_env_vs_dsn(env, "postgresql+asyncpg://fixture:fixture@[broken/fixture")
    assert refusal == f"env={env}: DSN is malformed; refusing to run"


@pytest.mark.parametrize("env", ["prod", "dev", "local"])
def test_nonidentity_query_control(cli, env):
    host = "db.example.invalid" if env == "prod" else "localhost"
    assert cli._validate_env_vs_dsn(env, _dsn(host, "application_name=locality-contract")) is None
