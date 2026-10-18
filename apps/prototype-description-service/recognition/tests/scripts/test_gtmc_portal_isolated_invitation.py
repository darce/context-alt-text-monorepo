"""Offline RED contracts for isolated-target and bounded-operation gaps in the invitation CLI.

Tests only. Nothing here touches a database, SQLite, network, secret store, or live OCI/GPU resource:

* the real ``db.session`` module is replaced by a stub whose factory records calls, so a fallback to a
  real session shows up as a failed assertion instead of a connection. ``db/__init__.py`` (which imports
  the real session and reads settings) is never executed, and ``db.tenant_context`` is replaced by trusted
  no-op async bypass helpers with the producer's signatures;
* the CLI session is an in-memory spy. It records calls and returns only the rows a correct CLI must see
  (WHERE clauses are not evaluated, so fixtures list exactly those rows);
* settings reads are fakes. Their DSNs carry a fake credential that must never be echoed;
* the 10 s operation budget and the 2 s cleanup budget run on a virtual clock, so no wall time is spent.

Aura label admission and the strict nested-DSN guard belong to the existing K-lane tests. They are only
re-asserted here as preserved behavior.

Owner contract used by the operator ``--tenant`` tests (proposed configuration, not an observed resource):
the target tenant must exist in the injected target store. Zero portal identities on that tenant is a valid
first-owner bootstrap; any identity on that tenant occupies it and is refused. Identities bound to other tenants
are unrelated and ignored, except that an invitee email already bound to a different tenant in that store is
refused as a local conflict. No email-only or cross-store link is made, and issuance creates no portal identity.

The public-claim control reads the router's claim guard from its source text with ``ast`` and executes only those
definitions. It imports no application module.
"""

from __future__ import annotations

import __future__
import ast
import asyncio
import hashlib
import importlib
import importlib.util
import os
import pathlib
import secrets
import selectors
import sys
import uuid
from functools import lru_cache
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, BooleanClauseList

APP_ROOT = pathlib.Path(__file__).resolve().parents[3]
CLI_PATH = APP_ROOT / "scripts" / "manage_portal_invitations.py"
DB_PACKAGE_INIT = APP_ROOT / "db" / "__init__.py"

FAKE_TOKEN = "fake-isolated-invitation-token-0001"
FAKE_CREDENTIAL = "fake-test-credential"
TENANT_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")
OTHER_TENANT_ID = uuid.UUID("66666666-7777-4888-8999-aaaaaaaaaaaa")
INVITEE_EMAIL = "invitee@example.test"
OWNER_EMAIL = "owner@example.test"
LOCAL_DSN = "postgresql+asyncpg://localhost/testdb"

OPERATION_BUDGET_SECONDS = 10
CLEANUP_BUDGET_SECONDS = 2
AURA_LABELS = ("dev-auraface", "staging-auraface", "prod-auraface")
ISSUER = "https://issuer.example.test"
SUBJECT = "fake-claim-subject"
ALLOWED_ORIGIN = "https://app.example.test"
_ROUTER_PATH = APP_ROOT / "recognition" / "interface_adapters" / "http" / "routers" / "portal.py"
_CLAIM_ROUTE_NAMES = frozenset(
    {
        "NO_STORE_HEADERS",
        "_CLAIM_ERROR_STATUS",
        "_claim_http_error",
        "_allowed_claim_origins",
        "_require_claim_origin",
        "_reject_claim_tenant_selection",
        "_claim_payload",
        "_rollback_claim_session",
        "portal_onboarding_claim",
    }
)


def _bare_db_package() -> ModuleType:
    """Return the ``db`` package object without running ``db/__init__.py``.

    That initializer imports the real ``db.session``, which reads settings and the secret provider and builds engines
    at import time. ``db.models`` and ``db.settings`` only need the package search path, so the package is built from
    its spec and its initializer is never executed.
    """
    spec = importlib.util.spec_from_file_location(
        "db", DB_PACKAGE_INIT, submodule_search_locations=[str(DB_PACKAGE_INIT.parent)]
    )
    assert spec is not None
    return importlib.util.module_from_spec(spec)


def _load_orm_models() -> ModuleType:
    """Import ``db.models`` without running ``db/__init__.py`` or reading live settings.

    ``db.models.base_imports`` calls ``get_database_settings()`` at import time, which loads ``.env``, consults the
    secret provider, and may write ``POSTGRES_DSN`` into the process environment. The models use only the pgvector
    dimension from that object, so the producer's environment-only resolver stands in for the getter during the import.
    """
    if "db" in sys.modules:
        return importlib.import_module("db.models")
    sys.modules["db"] = _bare_db_package()
    try:
        settings = importlib.import_module("db.settings")
        real_getter = settings.get_database_settings
        settings.get_database_settings = lambda: SimpleNamespace(
            pgvector_dimension=settings._resolve_pgvector_dimension()
        )
        try:
            return importlib.import_module("db.models")
        finally:
            settings.get_database_settings = real_getter
    finally:
        del sys.modules["db"]


_ORM = _load_orm_models()
PortalIdentity = _ORM.PortalIdentity
PortalTenantInvitation = _ORM.PortalTenantInvitation
Tenant = _ORM.Tenant


def _dsn(role: str, database: str, *, host: str = "postgres", query: str = "") -> str:
    return f"postgresql+asyncpg://{role}:{FAKE_CREDENTIAL}@{host}:5432/{database}{query}"


# ---------------------------------------------------------------------------
# Harness: stub session factory, CLI loader, env/settings fakes, virtual clock.
# ---------------------------------------------------------------------------


class _SessionFactory:
    """Stands in for ``db.session.async_session_factory``. Records each open; never connects."""

    def __init__(self) -> None:
        self.calls = 0
        self.session: _SpySession | None = None

    def __call__(self):
        self.calls += 1
        if self.session is None:
            raise AssertionError("session factory opened without a configured fake session")
        return self.session


def _tenant_context_stub() -> ModuleType:
    """Stand-in for ``db.tenant_context`` with the producer's async bypass signatures.

    The real module imports ``engine`` from ``db.session`` at import time, so it cannot load against this stub. The CLI
    and the portal repository reach only ``enable_rls_bypass`` and ``disable_rls_bypass``. Both are trusted no-ops here
    and never touch the spy session, so the recorded session log is unchanged.
    """
    stub = ModuleType("db.tenant_context")

    async def enable_rls_bypass(session) -> None:
        return None

    async def disable_rls_bypass(session) -> None:
        return None

    stub.enable_rls_bypass = enable_rls_bypass
    stub.disable_rls_bypass = disable_rls_bypass
    return stub


@pytest.fixture(autouse=True)
def factory(monkeypatch) -> _SessionFactory:
    recorder = _SessionFactory()
    stub = ModuleType("db.session")
    stub.async_session_factory = recorder
    monkeypatch.setitem(sys.modules, "db.session", stub)
    monkeypatch.setitem(sys.modules, "db.tenant_context", _tenant_context_stub())
    if "db" not in sys.modules:
        # ``from db import settings`` needs a loaded parent; the bare package keeps db/__init__.py unexecuted.
        monkeypatch.setitem(sys.modules, "db", _bare_db_package())
    return recorder


def _import_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location("manage_portal_invitations_cli", CLI_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_cli(monkeypatch) -> ModuleType:
    cli = _import_cli()

    async def _no_rls(_session) -> None:
        return None

    monkeypatch.setattr(cli, "enable_rls_bypass", _no_rls)
    monkeypatch.setattr(cli, "disable_rls_bypass", _no_rls)
    return cli


def _configure_env(monkeypatch, *, acx_env: str | None, dsn: str | None, compose_project: str | None = None) -> list:
    """Set ACX_ENV and COMPOSE_PROJECT_NAME, and fake the settings read. Returns the list of reads."""
    if acx_env is None:
        monkeypatch.delenv("ACX_ENV", raising=False)
    else:
        monkeypatch.setenv("ACX_ENV", acx_env)
    if compose_project is None:
        monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    else:
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", compose_project)

    reads: list[int] = []

    def _read_settings():
        reads.append(1)
        if dsn is None:
            raise AssertionError("settings must not be read in this context")
        return SimpleNamespace(postgres_dsn=dsn)

    from db import settings as db_settings

    monkeypatch.setattr(db_settings, "get_database_settings", _read_settings)
    return reads


def _fake_token(monkeypatch) -> None:
    monkeypatch.setattr(secrets, "token_urlsafe", lambda _nbytes=32: FAKE_TOKEN)


class _VirtualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class _VirtualTimeSelector(selectors.SelectSelector):
    """Advances the virtual clock instead of sleeping, and refuses to block with no deadline."""

    def __init__(self, clock: _VirtualClock) -> None:
        super().__init__()
        self._clock = clock

    def select(self, timeout=None):
        if timeout is None:
            raise AssertionError("unbounded wait: an awaited CLI operation has no deadline")
        if timeout > 0:
            self._clock.now += timeout
        return super().select(0)


def _drive(clock: _VirtualClock, coro):
    loop = asyncio.SelectorEventLoop(_VirtualTimeSelector(clock))
    loop.time = clock.monotonic  # instance attribute shadows BaseEventLoop.time
    try:
        return loop.run_until_complete(coro)
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            try:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
        loop.close()


class _Result:
    def __init__(self, rows) -> None:
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self.first()

    def scalar_one_or_none(self):
        return self.first()


def _entity_of(statement):
    descriptions = getattr(statement, "column_descriptions", None) or []
    return descriptions[0].get("entity") if descriptions else None


class _SpySession:
    """In-memory AsyncSession stand-in. ``hang`` names the steps that never complete."""

    def __init__(self, clock: _VirtualClock, *, rows: dict | None = None, hang: tuple[str, ...] = ()) -> None:
        self._clock = clock
        self._rows = rows or {}
        self._hang = frozenset(hang)
        self.added: list = []
        self.log: list[str] = []
        self.events: list[tuple[str, str, float]] = []

    def add(self, obj) -> None:
        self.log.append("add")
        self.added.append(obj)

    async def flush(self) -> None:
        self.log.append("flush")

    async def get(self, model, key, *_args, **_kwargs):
        self.log.append("get")
        return next((row for row in self._rows.get(model, []) if row.id == key), None)

    async def execute(self, statement):
        self.log.append("execute")
        entity = _entity_of(statement)
        return _Result(self._rows.get(entity, []) if entity is not None else [])

    async def commit(self) -> None:
        await self._step("commit")
        self.log.append("commit")

    async def rollback(self) -> None:
        await self._step("rollback")
        self.log.append("rollback")

    async def close(self) -> None:
        await self._step("close")
        self.log.append("close")

    async def _step(self, name: str) -> None:
        if name not in self._hang:
            return
        self.events.append((name, "start", self._clock.now))
        try:
            await asyncio.get_running_loop().create_future()  # never resolves
        except asyncio.CancelledError:
            self.events.append((name, "cancelled", self._clock.now))
            raise


def _tenant_row(tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=tenant_id, site_url="https://tenant-fixture.example.test")


def _owner_row(tenant_id: uuid.UUID, email: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email=email,
        issuer="https://issuer.example.test",
        subject="fake-owner-subject",
    )


class _OwnerSpySession(_SpySession):
    """Spy whose reads honor the WHERE terms of each statement. Used by the owner matrix only.

    The base spy returns every row for an entity, so an unrelated foreign owner would look like a target owner. Here
    equality and inequality terms joined by AND are evaluated against the fixture rows. Any other predicate fails the
    test instead of being silently ignored. The base spy and the factory stub are unchanged.
    """

    async def execute(self, statement):
        self.log.append("execute")
        entity = _entity_of(statement)
        rows = self._rows.get(entity, []) if entity is not None else []
        return _Result(_where_filter(statement, rows))


def _where_filter(statement, rows) -> list:
    clause = getattr(statement, "whereclause", None)
    if clause is None:
        return list(rows)
    terms = _where_terms(clause)
    return [row for row in rows if all(_term_holds(term, row) for term in terms)]


def _where_terms(clause) -> list:
    if isinstance(clause, BooleanClauseList) and clause.operator is operators.and_:
        return [term for child in clause.clauses for term in _where_terms(child)]
    if isinstance(clause, BinaryExpression) and clause.operator in (operators.eq, operators.ne):
        return [clause]
    raise AssertionError(f"owner fake cannot evaluate WHERE term {clause!r}")


def _term_holds(term: BinaryExpression, row) -> bool:
    if not isinstance(term.right, BindParameter):
        raise AssertionError("owner fake supports only column-to-literal WHERE terms")
    actual = getattr(row, term.left.key)
    expected = term.right.value
    return actual == expected if term.operator is operators.eq else actual != expected


def _assert_sanitized_streams(captured) -> None:
    """The raw token appears exactly once, on stdout. Digest and DSN credential never appear on either stream."""
    combined = captured.out + captured.err
    assert combined.count(FAKE_TOKEN) == 1, "the raw token must be delivered exactly once"
    assert captured.err.count(FAKE_TOKEN) == 0, "the raw token must not reach stderr"
    assert hashlib.sha256(FAKE_TOKEN.encode("utf-8")).hexdigest() not in combined, "token digest must not be printed"
    assert FAKE_CREDENTIAL not in combined, "DSN credential must never be echoed"


def _assert_no_token_output(captured) -> None:
    combined = captured.out + captured.err
    assert "invitation_token=" not in captured.out, "no token line may be printed for a non-completed operation"
    assert FAKE_TOKEN not in combined, "raw token must not appear in any output"
    assert hashlib.sha256(FAKE_TOKEN.encode("utf-8")).hexdigest() not in combined, "token digest must not be printed"
    assert FAKE_CREDENTIAL not in combined, "DSN credential must never be echoed"


# ---------------------------------------------------------------------------
# 1. dev-fir exact isolated label (new) and preserved Aura labels.
# ---------------------------------------------------------------------------


def test_dev_fir_is_an_admitted_env_choice() -> None:
    cli = _import_cli()
    args = cli._build_parser().parse_args(["--env", "dev-fir", "list"])
    assert args.env == "dev-fir"


@pytest.mark.parametrize("label", AURA_LABELS)
def test_aura_selectors_remain_admitted(label: str) -> None:
    cli = _import_cli()
    assert cli._build_parser().parse_args(["--env", label, "list"]).env == label


def test_dev_fir_exact_label_with_dedicated_identity_is_admitted(monkeypatch, factory) -> None:
    cli = _load_cli(monkeypatch)
    reads = _configure_env(monkeypatch, acx_env="dev-fir", dsn=_dsn("acx_dev_fir", "alt_context_dev_fir"))
    clock = _VirtualClock()
    factory.session = _SpySession(clock)

    exit_code = _drive(clock, cli.run(argv=["--env", "dev-fir", "list"]))

    assert exit_code == 0, "matching ACX_ENV, dedicated role and dedicated database must pass"
    assert len(reads) == 1, "the DSN identity must be checked exactly once"
    assert factory.calls == 1


@pytest.mark.parametrize(
    ("acx_env", "dsn"),
    [
        pytest.param(None, _dsn("acx_dev_fir", "alt_context_dev_fir"), id="acx-env-unset"),
        pytest.param("dev", _dsn("acx_dev_fir", "alt_context_dev_fir"), id="dev-label-under-fir-context"),
        pytest.param("dev-auraface", _dsn("acx_dev_fir", "alt_context_dev_fir"), id="aura-label-under-fir-context"),
        pytest.param("dev-fir", _dsn("postgres", "testdb"), id="generic-role-and-database"),
        pytest.param("dev-fir", _dsn("acx_dev_fir", "testdb"), id="fir-role-generic-database"),
        pytest.param("dev-fir", _dsn("postgres", "alt_context_dev_fir"), id="generic-role-fir-database"),
        pytest.param("dev-fir", _dsn("acx_dev_auraface", "alt_context_dev_auraface"), id="aura-identity-under-fir"),
        pytest.param("dev-fir", _dsn("acx_dev_fir", "alt_context_dev_fir", host="db.example.test"), id="nonlocal-host"),
        pytest.param(
            "dev-fir",
            _dsn("acx_dev_fir", "alt_context_dev_fir", query="?options=-c%20role%3Dpostgres"),
            id="options-role-override",
        ),
        pytest.param(
            "dev-fir",
            _dsn("acx_dev_fir", "alt_context_dev_fir", query="?dsn=postgresql://other.example.test/x"),
            id="nested-dsn-override",
        ),
    ],
)
def test_dev_fir_mismatch_or_generic_identity_is_refused_before_factory(monkeypatch, capsys, factory, acx_env, dsn):
    cli = _load_cli(monkeypatch)
    reads = _configure_env(monkeypatch, acx_env=acx_env, dsn=dsn)
    clock = _VirtualClock()
    factory.session = _SpySession(clock)

    exit_code = _drive(clock, cli.run(argv=["--env", "dev-fir", "list"]))

    captured = capsys.readouterr()
    assert exit_code == 1, "a mismatched label or identity must be refused"
    assert factory.calls == 0, "refusal must happen before any session is opened"
    assert factory.session.log == [], "refusal must not touch the session"
    expected_reads = 1 if acx_env == "dev-fir" else 0
    assert len(reads) == expected_reads, "context refusals must not read settings"
    _assert_no_token_output(captured)


def test_dev_label_under_dev_fir_context_is_still_refused(monkeypatch, capsys, factory) -> None:
    """Preserved guard: a fabricated dev-fir context must not be admitted by the generic dev path."""
    cli = _load_cli(monkeypatch)
    _configure_env(monkeypatch, acx_env="dev-fir", dsn=_dsn("postgres", "testdb"))
    clock = _VirtualClock()
    factory.session = _SpySession(clock)

    exit_code = _drive(clock, cli.run(argv=["--env", "dev", "list"]))

    assert exit_code == 1
    assert factory.calls == 0
    _assert_no_token_output(capsys.readouterr())


# ---------------------------------------------------------------------------
# 2. Operator-only optional --tenant on create (new); unbound default unchanged.
# ---------------------------------------------------------------------------


def test_create_tenant_option_parses_uuid_for_operator() -> None:
    cli = _import_cli()
    args = cli._build_parser().parse_args(
        ["--env", "local", "create", "--email", INVITEE_EMAIL, "--tenant", str(TENANT_ID)]
    )
    assert TENANT_ID in vars(args).values(), "--tenant must parse to the target tenant UUID"


def test_create_tenant_option_rejects_a_non_uuid() -> None:
    cli = _import_cli()
    with pytest.raises(SystemExit) as exc_info:
        cli._build_parser().parse_args(["--env", "local", "create", "--email", INVITEE_EMAIL, "--tenant", "not-a-uuid"])
    assert exc_info.value.code == 2


def test_unbound_create_default_is_unchanged(monkeypatch, capsys, factory) -> None:
    _fake_token(monkeypatch)
    cli = _load_cli(monkeypatch)
    args_namespace = vars(cli._build_parser().parse_args(["--env", "local", "create", "--email", INVITEE_EMAIL]))
    assert not any(isinstance(value, uuid.UUID) for value in args_namespace.values()), "no tenant is selected by default"

    _configure_env(monkeypatch, acx_env=None, dsn=LOCAL_DSN)
    clock = _VirtualClock()
    session = _SpySession(clock)
    factory.session = session

    exit_code = _drive(clock, cli.run(argv=["--env", "local", "create", "--email", INVITEE_EMAIL]))

    assert exit_code == 0
    assert len(session.added) == 1
    assert session.added[0].tenant_id is None, "unbound invitation must keep tenant_id NULL"
    assert capsys.readouterr().out.count(f"invitation_token={FAKE_TOKEN}") == 1


_OWNER_BOOTSTRAP = [
    pytest.param({Tenant: [_tenant_row(TENANT_ID)]}, id="first-owner-no-portal-identity"),
    pytest.param(
        {Tenant: [_tenant_row(TENANT_ID)], PortalIdentity: [_owner_row(OTHER_TENANT_ID, OWNER_EMAIL)]},
        id="unrelated-foreign-owner-ignored",
    ),
]


@pytest.mark.parametrize("rows", _OWNER_BOOTSTRAP)
def test_bound_create_bootstraps_first_owner_on_existing_target_tenant(monkeypatch, capsys, factory, rows) -> None:
    _fake_token(monkeypatch)
    cli = _load_cli(monkeypatch)
    _configure_env(monkeypatch, acx_env=None, dsn=LOCAL_DSN)
    clock = _VirtualClock()
    session = _OwnerSpySession(clock, rows=rows)
    factory.session = session

    exit_code = _drive(
        clock,
        cli.run(argv=["--env", "local", "create", "--email", INVITEE_EMAIL, "--tenant", str(TENANT_ID)]),
    )

    captured = capsys.readouterr()
    assert exit_code == 0, "an existing target tenant with no portal owner must accept its first bound invitation"
    assert len(session.added) == 1, "exactly one invitation row is added"
    invitation = session.added[0]
    assert isinstance(invitation, PortalTenantInvitation)
    assert invitation.tenant_id == TENANT_ID, "invitation must bind to the operator-selected tenant"
    created_identities = [obj for obj in session.added if isinstance(obj, PortalIdentity)]
    assert created_identities == [], "issuance must not create a portal identity"
    assert session.log.count("commit") == 1, "the bootstrap invitation is committed once"
    assert "rollback" not in session.log, "a successful bootstrap does not roll back"
    assert captured.out.count(f"invitation_token={FAKE_TOKEN}") == 1


_OWNER_REFUSALS = [
    pytest.param({}, id="missing-target-tenant"),
    pytest.param(
        {Tenant: [_tenant_row(TENANT_ID)], PortalIdentity: [_owner_row(TENANT_ID, OWNER_EMAIL)]},
        id="target-tenant-occupied-by-owner",
    ),
    # The target has zero owners, so this refusal is attributable to the invitee conflict alone.
    pytest.param(
        {Tenant: [_tenant_row(TENANT_ID)], PortalIdentity: [_owner_row(OTHER_TENANT_ID, INVITEE_EMAIL)]},
        id="invitee-email-bound-to-foreign-tenant",
    ),
]


@pytest.mark.parametrize("rows", _OWNER_REFUSALS)
def test_bound_create_refuses_missing_occupied_or_conflicting_target(monkeypatch, capsys, factory, rows) -> None:
    _fake_token(monkeypatch)
    cli = _load_cli(monkeypatch)
    _configure_env(monkeypatch, acx_env=None, dsn=LOCAL_DSN)
    clock = _VirtualClock()
    session = _OwnerSpySession(clock, rows=rows)
    factory.session = session

    exit_code = _drive(
        clock,
        cli.run(argv=["--env", "local", "create", "--email", INVITEE_EMAIL, "--tenant", str(TENANT_ID)]),
    )

    captured = capsys.readouterr()
    assert exit_code == 1, "a missing, occupied or locally conflicting target must be refused"
    assert session.added == [], "refused bound invitation must not be added"
    assert "commit" not in session.log, "refused bound invitation must not commit"
    _assert_no_token_output(captured)


def test_owner_fake_evaluates_where_terms_before_returning_rows() -> None:
    """Control on the control: the owner fake must scope reads, or the foreign-owner cases prove nothing."""
    clock = _VirtualClock()
    own = _owner_row(TENANT_ID, OWNER_EMAIL)
    foreign = _owner_row(OTHER_TENANT_ID, OWNER_EMAIL)
    session = _OwnerSpySession(clock, rows={PortalIdentity: [own, foreign]})

    scoped = _drive(clock, session.execute(select(PortalIdentity).where(PortalIdentity.tenant_id == TENANT_ID)))
    assert scoped.all() == [own], "a tenant-scoped read must not return the foreign owner"
    unscoped = _drive(clock, session.execute(select(PortalIdentity)))
    assert len(unscoped.all()) == 2, "a read without WHERE keeps every fixture row"
    with pytest.raises(AssertionError, match="cannot evaluate"):
        _drive(clock, session.execute(select(PortalIdentity).where(PortalIdentity.subject.is_(None))))


# ---------------------------------------------------------------------------
# 3. Bounded CLI commit / rollback / close (new). Virtual clock: 10 s op, 2 s cleanup.
# ---------------------------------------------------------------------------


def test_virtual_clock_harness_refuses_an_unbounded_wait() -> None:
    clock = _VirtualClock()

    async def _never_resolves() -> None:
        await asyncio.get_running_loop().create_future()

    with pytest.raises(AssertionError, match="unbounded wait"):
        _drive(clock, _never_resolves())


def test_immediate_create_on_virtual_clock_prints_token_once(monkeypatch, capsys, factory) -> None:
    _fake_token(monkeypatch)
    cli = _load_cli(monkeypatch)
    _configure_env(monkeypatch, acx_env=None, dsn=LOCAL_DSN)
    clock = _VirtualClock()
    session = _SpySession(clock)
    factory.session = session

    exit_code = _drive(clock, cli.run(argv=["--env", "local", "create", "--email", INVITEE_EMAIL]))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert clock.now == 0.0, "immediate awaitables must consume no virtual time"
    assert captured.out.count(f"invitation_token={FAKE_TOKEN}") == 1
    assert "close" in session.log, "an opened session must be closed"


# Unacknowledged or ambiguous commit only. A hung close AFTER an acknowledged commit is a success case, tested below.
_HANG_CASES = [
    pytest.param(("commit",), 10, id="commit-hangs"),
    pytest.param(("commit", "rollback"), 12, id="commit-and-rollback-hang"),
    pytest.param(("commit", "close"), 12, id="commit-and-close-hang"),
]


@pytest.mark.parametrize(("hung", "expected_elapsed"), _HANG_CASES)
def test_hanging_cli_operations_are_bounded_and_emit_no_token(
    monkeypatch, capsys, factory, hung, expected_elapsed
) -> None:
    _fake_token(monkeypatch)
    cli = _load_cli(monkeypatch)
    _configure_env(monkeypatch, acx_env=None, dsn=LOCAL_DSN)
    clock = _VirtualClock()
    session = _SpySession(clock, hang=hung)
    factory.session = session

    exit_code = _drive(clock, cli.run(argv=["--env", "local", "create", "--email", INVITEE_EMAIL]))

    captured = capsys.readouterr()
    assert isinstance(exit_code, int) and exit_code != 0, "a hung operation must return a non-success code"
    assert clock.now == pytest.approx(expected_elapsed, abs=1e-6), "total time must follow the 10 s / 2 s budgets"
    for name in hung:
        starts = [at for step, kind, at in session.events if step == name and kind == "start"]
        cancels = [at for step, kind, at in session.events if step == name and kind == "cancelled"]
        assert len(starts) == 1 and len(cancels) == 1, f"{name} must be cancelled by its bound"
        budget = OPERATION_BUDGET_SECONDS if name == "commit" else CLEANUP_BUDGET_SECONDS
        assert cancels[0] - starts[0] == pytest.approx(budget), f"{name} budget must be {budget}s"
    _assert_no_token_output(captured)
    assert factory.calls == 1


def test_acknowledged_commit_with_hung_close_is_success_with_one_token_and_warning(
    monkeypatch, capsys, factory
) -> None:
    """Acknowledged commit + bounded close failure: status 0, token once, sanitized cleanup warning, no rollback."""
    _fake_token(monkeypatch)
    cli = _load_cli(monkeypatch)
    _configure_env(monkeypatch, acx_env=None, dsn=LOCAL_DSN)
    clock = _VirtualClock()
    session = _SpySession(clock, hang=("close",))
    factory.session = session

    exit_code = _drive(clock, cli.run(argv=["--env", "local", "create", "--email", INVITEE_EMAIL]))

    captured = capsys.readouterr()
    assert exit_code == 0, "an acknowledged commit is durable success even when the owned-session close hangs"
    assert "commit" in session.log, "the create must have been acknowledged before cleanup"
    assert "rollback" not in session.log, "no rollback may follow a known successful commit"
    assert captured.out.count(f"invitation_token={FAKE_TOKEN}") == 1, "the raw token is delivered exactly once"
    assert "invitation_id=" in captured.out, "safe invitation metadata accompanies the token"
    assert "warning" in (captured.out + captured.err).lower(), "a bounded close failure must emit a cleanup warning"
    _assert_sanitized_streams(captured)
    starts = [at for step, kind, at in session.events if step == "close" and kind == "start"]
    cancels = [at for step, kind, at in session.events if step == "close" and kind == "cancelled"]
    assert len(starts) == 1 and len(cancels) == 1, "the hung close must be cancelled once by its bound"
    assert cancels[0] - starts[0] == pytest.approx(CLEANUP_BUDGET_SECONDS), "close budget must be 2 s"
    assert clock.now == pytest.approx(CLEANUP_BUDGET_SECONDS, abs=1e-6), "the only added wait is the cleanup budget"
    assert factory.calls == 1


class _CommitFailureSession(_SpySession):
    """Commit raises before any acknowledgment. The fault is injected by the test; no driver is involved."""

    async def commit(self) -> None:
        self.log.append("commit-failed")
        raise RuntimeError("fake commit failure before acknowledgment")


def test_failed_commit_emits_no_token_and_is_not_success(monkeypatch, capsys, factory) -> None:
    """Preserved GREEN control: an unacknowledged commit failure never prints the raw token or reports success."""
    _fake_token(monkeypatch)
    cli = _load_cli(monkeypatch)
    _configure_env(monkeypatch, acx_env=None, dsn=LOCAL_DSN)
    clock = _VirtualClock()
    session = _CommitFailureSession(clock)
    factory.session = session

    try:
        outcome: object = _drive(clock, cli.run(argv=["--env", "local", "create", "--email", INVITEE_EMAIL]))
    except RuntimeError:
        outcome = "raised"

    captured = capsys.readouterr()
    assert outcome == "raised" or (isinstance(outcome, int) and outcome != 0), "a failed commit must not succeed"
    assert "commit-failed" in session.log
    _assert_no_token_output(captured)


# ---------------------------------------------------------------------------
# 4. Public claim body refusal (preserved GREEN control). Source-extracted; the router module is not imported.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _claim_route_namespace() -> dict:
    """Execute the claim route's own definitions taken from router source, without importing the router.

    Importing the router loads the real session, settings and billing graph. Instead its AST is parsed and only the
    claim guard and route definitions are compiled. Dependency defaults are placeholders, and classes that the route
    names only in an exception clause or on the success path are inert. A renamed or missing definition fails the set
    check below rather than passing silently.
    """
    import typing
    from collections.abc import Mapping

    from fastapi import status

    tree = ast.parse(_ROUTER_PATH.read_text(encoding="utf-8"), filename=str(_ROUTER_PATH))
    body: list[ast.stmt] = []
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _CLAIM_ROUTE_NAMES:
            node.decorator_list = []
            body.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)} & _CLAIM_ROUTE_NAMES
            if names:
                body.append(node)
                found |= names
    assert found == _CLAIM_ROUTE_NAMES, f"claim route definitions moved: {sorted(_CLAIM_ROUTE_NAMES - found)}"
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    code = compile(module, str(_ROUTER_PATH), "exec", flags=__future__.annotations.compiler_flag, dont_inherit=True)

    class _Inert:
        """Placeholder for a class the route names only in an exception clause or on the success path."""

    namespace: dict = {
        "__name__": "portal_claim_guard_source",
        "HTTPException": HTTPException,
        "status": status,
        "cast": typing.cast,
        "Mapping": Mapping,
        "os": os,
        "Depends": lambda dependency: dependency,
        "require_verified_portal_identity": object(),
        "get_portal_claim_service": object(),
        "get_claim_session": object(),
        "PortalClaimOutcome": _Inert,
        "PortalClaimResponse": _Inert,
        "PortalIdentityClaimError": _Inert,
        "PortalIdentityClaimRefused": _Inert,
    }
    exec(code, namespace)
    return namespace


class _ClaimRequest:
    """Minimal request: a valid origin, no query selectors, and a manually parsed JSON body."""

    def __init__(self, body: object) -> None:
        self.headers = {"origin": ALLOWED_ORIGIN}
        self.query_params: dict[str, str] = {}
        self.app = SimpleNamespace(state=SimpleNamespace(app_allowed_origins=frozenset({ALLOWED_ORIGIN})))
        self._body = body

    async def json(self) -> object:
        return self._body


class _ClaimService:
    """Records claim calls. Returns no outcome, so a route that reaches it ends on its own 503 path."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def claim_onboarding(self, *, issuer: str, subject: str, email: str, invitation_token: str) -> None:
        self.calls.append({"issuer": issuer, "subject": subject, "email": email, "invitation_token": invitation_token})
        return None


class _ClaimSession:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


def _claim(body: object, service: _ClaimService, session: _ClaimSession):
    route = _claim_route_namespace()["portal_onboarding_claim"]
    claims = SimpleNamespace(issuer=ISSUER, subject=SUBJECT, email=INVITEE_EMAIL, email_verified=True)
    return route(
        request=_ClaimRequest(body),
        response=SimpleNamespace(headers={}, status_code=None),
        claims=claims,
        service=service,
        session=session,
    )


@pytest.mark.parametrize("key", ["tenantId", "tenant_id"])
@pytest.mark.parametrize("value", [str(TENANT_ID), None, ""], ids=["uuid", "null", "empty"])
def test_public_claim_body_tenant_selector_is_refused_before_service_or_commit(key: str, value) -> None:
    service, session = _ClaimService(), _ClaimSession()

    with pytest.raises(HTTPException) as exc_info:
        _drive(_VirtualClock(), _claim({"invitation_token": FAKE_TOKEN, key: value}, service, session))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"code": "tenant_header_forbidden"}
    assert service.calls == [], "a body tenant selector must not reach the claim service"
    assert "commit" not in session.events, "a refused claim must not commit"


def test_public_claim_without_tenant_selector_reaches_the_service_once() -> None:
    """Reachability control for the refusal above: a valid body does reach the service exactly once."""
    service, session = _ClaimService(), _ClaimSession()

    with pytest.raises(HTTPException) as exc_info:
        _drive(_VirtualClock(), _claim({"invitation_token": FAKE_TOKEN}, service, session))

    assert exc_info.value.status_code == 503, "the stub returns no outcome, so the route's own 503 path ends the call"
    assert [call["invitation_token"] for call in service.calls] == [FAKE_TOKEN], "a valid body reaches the service once"
    assert "commit" not in session.events
