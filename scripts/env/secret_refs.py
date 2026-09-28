from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from typing import Callable


class SecretUnavailable(RuntimeError):
    pass


class SecretNotFound(SecretUnavailable):
    pass


def _unavailable(var_name: str, scheme: str) -> SecretUnavailable:
    return SecretUnavailable(f"secret {var_name!r} unavailable for scheme {scheme!r}")


def _not_found(var_name: str, scheme: str) -> SecretNotFound:
    return SecretNotFound(f"secret {var_name!r} unavailable for scheme {scheme!r}")


def resolve_secret(
    var_name: str,
    ref: str,
    *,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str:
    scheme, separator, location = ref.partition(":")
    if not separator:
        raise SecretUnavailable(f"secret {var_name!r} reference has no scheme")

    if scheme == "keychain":
        if "/" not in location:
            raise _unavailable(var_name, scheme)
        service, account = location.split("/", 1)
        if not service or not account:
            raise _unavailable(var_name, scheme)
        try:
            result = runner(
                ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            raise _unavailable(var_name, scheme) from None
        if result.returncode == 44:
            raise _not_found(var_name, scheme)
        if result.returncode != 0 or not isinstance(result.stdout, str):
            raise _unavailable(var_name, scheme)
        value = result.stdout[:-1] if result.stdout.endswith("\n") else result.stdout
        if not value:
            raise _unavailable(var_name, scheme)
        return value

    if scheme == "env":
        if not location:
            raise _unavailable(var_name, scheme)
        environment = os.environ if environ is None else environ
        value = environment.get(location)
        if not value:
            raise _not_found(var_name, scheme)
        return value

    if scheme == "vault":
        raise SecretUnavailable(f"secret {var_name!r} for scheme 'vault' is deferred to ENVMAN-2")

    raise SecretUnavailable(f"secret {var_name!r} has unsupported scheme {scheme!r}")
