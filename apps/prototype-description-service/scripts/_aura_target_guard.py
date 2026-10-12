"""Shared operator-target guard for the dedicated Aura labels of the tenant CLIs (GTMR K lane).

scripts/manage_api_keys.py and scripts/manage_portal_invitations.py call validate_aura_target() before any settings
read, session creation, injected-session use or operation dispatch. Apart from the single DSN read the caller injects,
the guard performs no I/O: no database, network or secret is touched.

Contract (target names are proposed configuration, not observed resources):

* --env dev-auraface, staging-auraface or prod-auraface is admitted only when ACX_ENV equals that label, the
  COMPOSE_PROJECT_NAME execution context equals acx-<label>, and the effective DSN names the dedicated role
  acx_<label with underscores> and the dedicated database alt_context_<label with underscores>.
* A DSN query key that asyncpg merges into connect arguments, or resolves through a service file, can replace the
  effective user, database, host or port. A nested `dsn` key can set startup settings such as the role while the outer
  identity stays dedicated. Any such key is refused regardless of its value, so the netloc is the only identity source
  for an Aura label.
* Missing or malformed role, database, host or port is refused. Refusal text never includes the DSN or its credential.
* Host policy: dev-auraface and staging-auraface accept a local host or the Compose postgres service, as their generic
  stacks do. prod-auraface refuses loopback, unspecified and *.local hosts, and accepts any other host, including
  postgres. A public API hostname is not required of the database host.

Scope limit: ACX_ENV and COMPOSE_PROJECT_NAME are environment-consistency signals. They do not prove which container,
image or runtime the process ran in. Collector and runtime provenance are verified separately.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

# label -> (dedicated role, dedicated database). Proposed configuration; not an observed resource.
_TARGETS: dict[str, tuple[str, str]] = {
    "dev-auraface": ("acx_dev_auraface", "alt_context_dev_auraface"),
    "staging-auraface": ("acx_staging_auraface", "alt_context_staging_auraface"),
    "prod-auraface": ("acx_prod_auraface", "alt_context_prod_auraface"),
}
AURA_LABELS: tuple[str, ...] = tuple(_TARGETS)
_PROD_LABEL = "prod-auraface"

# Query keys that can replace the effective endpoint, identity or startup settings. asyncpg merges query keys into
# connect kwargs, and resolves `service` and `servicefile` against a pg_service.conf file. `dsn` is a nested DSN:
# asyncpg parses its query into server_settings, so `dsn=...?role=...` sets the startup role while the outer identity
# stays dedicated. `options` carries libpq startup settings such as `-c role=...`; asyncpg.connect has no such argument
# and rejects it with TypeError. Refusing it here keeps the refusal ahead of any connection attempt. Keys are matched
# case-insensitively.
_ENDPOINT_QUERY_KEYS = frozenset(
    {"user", "username", "database", "dbname", "host", "hostaddr", "port", "service", "servicefile", "options", "dsn"}
)


def validate_aura_target(
    label: str,
    *,
    configured_env: str | None,
    compose_project: str | None,
    read_dsn: Callable[[], object],
) -> str | None:
    """Return a refusal message, or None when the Aura label and its effective DSN identity agree.

    ``read_dsn`` is called only after the environment context has passed, so a refused context reads no settings.
    """
    if label not in _TARGETS:
        raise ValueError(f"not an Aura label: {label!r}")
    refusal = _context_refusal(label, configured_env=configured_env, compose_project=compose_project)
    if refusal is not None:
        return refusal
    return _dsn_refusal(label, read_dsn())


def _context_refusal(label: str, *, configured_env: str | None, compose_project: str | None) -> str | None:
    if configured_env is None:
        return f"ACX_ENV must be set to {label!r} to match --env; refusing to run"
    if configured_env != label:
        return f"ACX_ENV={configured_env!r} does not match --env={label!r}; refusing to run"
    if compose_project != f"acx-{label}":
        return f"COMPOSE_PROJECT_NAME must be 'acx-{label}' for --env={label!r}; refusing to run"
    return None


def _dsn_refusal(label: str, dsn: object) -> str | None:
    role, database = _TARGETS[label]
    if not isinstance(dsn, str) or not dsn:
        return f"env={label}: DSN is missing; refusing to run"
    try:
        url = make_url(dsn)
    except (ArgumentError, ValueError):
        # No exception text: parser messages can echo fragments of the DSN, including its credential.
        return f"env={label}: DSN is malformed; refusing to run"
    if any(key.lower() in _ENDPOINT_QUERY_KEYS for key in url.query):
        return f"env={label}: DSN query overrides the connection identity or endpoint; refusing to run"
    if url.port is not None and not 1 <= url.port <= 65535:
        return f"env={label}: DSN port is malformed; refusing to run"
    host = (url.host or "").lower()
    if not host or "," in host or any(character.isspace() for character in host):
        return f"env={label}: DSN host is missing or malformed; refusing to run"
    if not url.username:
        return f"env={label}: DSN role is missing; refusing to run"
    if not url.database:
        return f"env={label}: DSN database is missing; refusing to run"
    if url.username != role or url.database != database:
        return f"env={label}: DSN role or database does not match the dedicated target; refusing to run"
    return _host_refusal(label, host)


def _host_refusal(label: str, host: str) -> str | None:
    local = _is_local_host(host)
    if label == _PROD_LABEL:
        return f"env={label} but DSN host '{host}' looks local; refusing to run" if local else None
    if local or host == "postgres":
        return None
    return f"env={label} but DSN host '{host}' is not a local or Compose postgres host; refusing to run"


def _is_local_host(host: str) -> bool:
    if host == "localhost" or host.endswith((".localhost", ".local")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    # Loopback covers 127.0.0.0/8 and ::1; unspecified covers 0.0.0.0 and ::, which connect to the local host on Linux.
    return address.is_loopback or address.is_unspecified
