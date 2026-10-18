from __future__ import annotations

import importlib
import subprocess

import pytest


def _secret_refs():
    return importlib.import_module("env.secret_refs")


def _assert_unavailable(exc_info, secret_refs):
    assert type(exc_info.value) is secret_refs.SecretUnavailable


def test_keychain_resolution_uses_exact_argv_and_options():
    secret_refs = _secret_refs()
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="v\n", stderr="")

    assert secret_refs.resolve_secret("PGPASSWORD", "keychain:acx-local/PGPASSWORD", runner=runner) == "v"
    assert calls == [
        (
            ["security", "find-generic-password", "-s", "acx-local", "-a", "PGPASSWORD", "-w"],
            {"capture_output": True, "text": True, "check": False},
        )
    ]


@pytest.mark.parametrize(("stdout", "expected"), [("v\n", "v"), ("v\n\n", "v\n")])
def test_keychain_resolution_strips_exactly_one_trailing_newline(stdout, expected):
    secret_refs = _secret_refs()

    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    assert secret_refs.resolve_secret("PGPASSWORD", "keychain:acx-local/PGPASSWORD", runner=runner) == expected


def test_keychain_ref_splits_at_the_first_slash():
    secret_refs = _secret_refs()
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="v", stderr="")

    assert secret_refs.resolve_secret("TOKEN", "keychain:svc/acct/x", runner=runner) == "v"
    assert calls == [
        (
            ["security", "find-generic-password", "-s", "svc", "-a", "acct/x", "-w"],
            {"capture_output": True, "text": True, "check": False},
        )
    ]


def test_keychain_nonzero_exit_does_not_expose_stdout_secret():
    secret_refs = _secret_refs()
    fake_secret = "s3cr3t-value"
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 1, stdout=fake_secret, stderr="failure")

    with pytest.raises(secret_refs.SecretUnavailable) as exc_info:
        secret_refs.resolve_secret("PGPASSWORD", "keychain:acx-local/PGPASSWORD", runner=runner)

    _assert_unavailable(exc_info, secret_refs)
    message = str(exc_info.value)
    assert "PGPASSWORD" in message
    assert "keychain" in message
    assert fake_secret not in message
    assert fake_secret not in repr(exc_info.value)
    assert len(calls) == 1


def test_keychain_empty_stdout_is_unavailable():
    secret_refs = _secret_refs()

    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with pytest.raises(secret_refs.SecretUnavailable) as exc_info:
        secret_refs.resolve_secret("PGPASSWORD", "keychain:acx-local/PGPASSWORD", runner=runner)

    _assert_unavailable(exc_info, secret_refs)
    assert "PGPASSWORD" in str(exc_info.value)
    assert "keychain" in str(exc_info.value)


@pytest.mark.parametrize(
    "ref",
    ["keychain:acx-local", "keychain:/PGPASSWORD", "keychain:acx-local/"],
    ids=["missing-account-separator", "empty-service", "empty-account"],
)
def test_malformed_keychain_ref_is_unavailable_without_runner(ref):
    secret_refs = _secret_refs()
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with pytest.raises(secret_refs.SecretUnavailable) as exc_info:
        secret_refs.resolve_secret("PGPASSWORD", ref, runner=runner)

    _assert_unavailable(exc_info, secret_refs)
    assert "PGPASSWORD" in str(exc_info.value)
    assert "keychain" in str(exc_info.value)
    assert calls == []


def test_env_ref_returns_value_from_injected_mapping():
    secret_refs = _secret_refs()
    assert secret_refs.resolve_secret("DATABASE_URL", "env:DATABASE_URL", environ={"DATABASE_URL": "db-value"}) == "db-value"


@pytest.mark.parametrize("environ", [{}, {"DATABASE_URL": ""}], ids=["missing", "empty"])
def test_env_ref_missing_or_empty_value_is_not_found(environ):
    secret_refs = _secret_refs()

    with pytest.raises(secret_refs.SecretUnavailable) as exc_info:
        secret_refs.resolve_secret("DATABASE_URL", "env:DATABASE_URL", environ=environ)

    assert type(exc_info.value) is secret_refs.SecretNotFound
    assert "DATABASE_URL" in str(exc_info.value)
    assert "env" in str(exc_info.value)


def test_env_ref_defaults_to_os_environ(monkeypatch):
    secret_refs = _secret_refs()
    monkeypatch.setenv("ENVMAN_TEST_SECRET", "from-os-environ")

    assert secret_refs.resolve_secret("TOKEN", "env:ENVMAN_TEST_SECRET") == "from-os-environ"


def test_vault_ref_is_deferred_to_envman_2_without_runner_call():
    secret_refs = _secret_refs()
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with pytest.raises(secret_refs.SecretUnavailable) as exc_info:
        secret_refs.resolve_secret("API_TOKEN", "vault:team/api-token", runner=runner)

    _assert_unavailable(exc_info, secret_refs)
    assert "API_TOKEN" in str(exc_info.value)
    assert "ENVMAN-2" in str(exc_info.value)
    assert calls == []


@pytest.mark.parametrize(
    ("ref", "message_part"),
    [("file:/x", "file"), ("bare-ref", "scheme")],
    ids=["unknown-scheme", "missing-scheme"],
)
def test_unknown_or_missing_scheme_is_unavailable_without_runner(ref, message_part):
    secret_refs = _secret_refs()
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with pytest.raises(secret_refs.SecretUnavailable) as exc_info:
        secret_refs.resolve_secret("TOKEN", ref, runner=runner)

    _assert_unavailable(exc_info, secret_refs)
    message = str(exc_info.value)
    assert "TOKEN" in message
    assert message_part in message
    assert calls == []


def test_secret_unavailable_is_a_runtime_error_subclass():
    secret_refs = _secret_refs()
    assert issubclass(secret_refs.SecretUnavailable, RuntimeError)


def test_keychain_newline_only_stdout_is_unavailable():
    secret_refs = _secret_refs()

    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="\n", stderr="")

    with pytest.raises(secret_refs.SecretUnavailable) as exc_info:
        secret_refs.resolve_secret("PGPASSWORD", "keychain:acx-local/PGPASSWORD", runner=runner)

    _assert_unavailable(exc_info, secret_refs)
    assert "PGPASSWORD" in str(exc_info.value)
    assert "keychain" in str(exc_info.value)
