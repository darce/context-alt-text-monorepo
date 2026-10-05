from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from collections.abc import Mapping
from typing import Callable


class SecretUnavailable(RuntimeError):
    pass


class SecretNotFound(SecretUnavailable):
    pass


_OCI_SECRET_OCID = re.compile(r"ocid1\.vaultsecret\.oc1\.[a-z0-9-]+\.[a-z0-9]{20,}")
_OCI_TIMEOUT_SECONDS = 30


def _json_object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


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

    if scheme == "oci":
        if _OCI_SECRET_OCID.fullmatch(location) is None:
            raise _unavailable(var_name, scheme)
        try:
            result = runner(
                [
                    "oci", "secrets", "secret-bundle", "get", "--auth", "instance_principal",
                    "--secret-id", location,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=_OCI_TIMEOUT_SECONDS,
            )
            if result.returncode != 0 or not isinstance(result.stdout, str):
                raise ValueError("OCI secret retrieval failed")
            payload = json.loads(result.stdout, object_pairs_hook=_json_object_without_duplicate_keys)
            content = payload["data"]["secret-bundle-content"]
            if not isinstance(content, dict) or content.get("content-type") != "BASE64":
                raise ValueError("unsupported OCI secret content")
            encoded = content.get("content")
            if not isinstance(encoded, str) or not encoded:
                raise ValueError("empty OCI secret content")
            raw_value = base64.b64decode(encoded, validate=True)
            if not raw_value:
                raise ValueError("empty OCI secret content")
            value = raw_value.decode("utf-8", errors="strict")
        except Exception:
            raise _unavailable(var_name, scheme) from None
        return value

    raise SecretUnavailable(f"secret {var_name!r} has unsupported scheme {scheme!r}")
