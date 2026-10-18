"""Offline portal-label and legacy identity regressions (fixture data only)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import Label
from sqlalchemy.sql.functions import Function

_STRIP_CHARACTERS = "".join(chr(codepoint) for codepoint in range(sys.maxunicode + 1) if chr(codepoint).isspace())

_SPEC = importlib.util.spec_from_file_location(
    "_target_label_harness", Path(__file__).with_name("test_gtmc_portal_isolated_invitation.py")
)
assert _SPEC is not None and _SPEC.loader is not None
h = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(h)
factory = h.factory


@pytest.mark.parametrize("label", ["staging-auraface", "prod-auraface"])
def test_aura_portal_labels_admitted_in_dedicated_store(monkeypatch, capsys, factory, label):
    cli = h._load_cli(monkeypatch)
    reads = h._configure_env(
        monkeypatch, acx_env=label,
        dsn=h._dsn("acx_" + label.replace("-", "_"), "alt_context_" + label.replace("-", "_")),
        compose_project="acx-" + label,
    )
    clock = h._VirtualClock()
    factory.session = h._SpySession(clock)
    assert h._drive(clock, cli.run(["--env", label, "list"])) == 0
    assert len(reads) == 1
    assert factory.calls == 1
    assert factory.session.log == ["execute", "commit", "close"]
    h._assert_no_token_output(capsys.readouterr())


def _value(expression, row):
    if isinstance(expression, Label):
        return _value(expression.element, row)
    if isinstance(expression, Function):
        assert expression.name in {"lower", "trim", "btrim"}
        argument, *parameters = expression.clauses
        value = _value(argument, row)
        if value is None:
            return None
        if expression.name == "lower":
            assert not parameters
            return value.lower()
        if expression.name == "trim":
            assert not parameters
            return value.strip(" ")
        characters, = parameters
        return value.strip(characters.value)
    return getattr(row, expression.key)


class _NormalizedOwnerSession(h._OwnerSpySession):
    async def execute(self, statement):
        self.log.append("execute")
        rows = self._rows.get(h._entity_of(statement), [])
        terms = h._where_terms(statement.whereclause)
        def matches(row):
            for term in terms:
                actual, expected = _value(term.left, row), term.right.value
                if not (actual == expected if term.operator is h.operators.eq else actual != expected):
                    return False
            return True
        return h._Result([row for row in rows if matches(row)])


@pytest.mark.parametrize("variant", ["upper", "padded", "both", "normalized", "unrelated"])
def test_foreign_legacy_email_binding_refused(monkeypatch, capsys, factory, variant):
    cli = h._load_cli(monkeypatch)
    h._configure_env(monkeypatch, acx_env=None, dsn=h.LOCAL_DSN)
    h._fake_token(monkeypatch)
    stored = h.INVITEE_EMAIL
    if variant in {"upper", "both"}:
        stored = stored.upper()
    if variant in {"padded", "both"}:
        stored = "  " + stored + "  "
    if variant == "unrelated":
        stored = h.OWNER_EMAIL
    clock = h._VirtualClock()
    session = _NormalizedOwnerSession(clock, rows={
        h.Tenant: [h._tenant_row(h.TENANT_ID)],
        h.PortalIdentity: [h._owner_row(h.OTHER_TENANT_ID, stored)],
    })
    factory.session = session
    status = h._drive(clock, cli.run([
        "--env", "local", "create", "--email", h.INVITEE_EMAIL, "--tenant", str(h.TENANT_ID)
    ]))
    assert status == (0 if variant == "unrelated" else 1)
    captured = capsys.readouterr()
    if variant != "unrelated":
        assert session.added == []
        assert "commit" not in session.log
        h._assert_no_token_output(captured)


@pytest.mark.parametrize("padding", _STRIP_CHARACTERS, ids=lambda char: f"U+{ord(char):04X}")
@pytest.mark.parametrize("placement", ["leading", "trailing", "both"])
def test_whitespace_foreign_binding_refused(monkeypatch, capsys, factory, padding, placement):
    cli = h._load_cli(monkeypatch)
    h._configure_env(monkeypatch, acx_env=None, dsn=h.LOCAL_DSN)
    token_calls = []

    def unexpected_token(*args, **kwargs):
        token_calls.append(True)
        return h.FAKE_TOKEN

    monkeypatch.setattr(cli.secrets, "token_urlsafe", unexpected_token)
    stored = h.INVITEE_EMAIL
    if placement in {"leading", "both"}:
        stored = padding + stored
    if placement in {"trailing", "both"}:
        stored += padding
    assert cli._normalize_email(stored) == h.INVITEE_EMAIL
    clock = h._VirtualClock()
    session = _NormalizedOwnerSession(clock, rows={
        h.Tenant: [h._tenant_row(h.TENANT_ID)],
        h.PortalIdentity: [h._owner_row(h.OTHER_TENANT_ID, stored)],
    })
    factory.session = session
    status = h._drive(clock, cli.run([
        "--env", "local", "create", "--email", h.INVITEE_EMAIL, "--tenant", str(h.TENANT_ID)
    ]))
    captured = capsys.readouterr()
    assert status == 1
    assert session.added == []
    assert "commit" not in session.log
    assert "flush" not in session.log
    assert token_calls == []
    assert session.log == ["execute", "execute", "execute", "rollback", "close"]
    h._assert_no_token_output(captured)


def test_mixed_whitespace_foreign_binding_refused(monkeypatch, capsys, factory):
    test_whitespace_foreign_binding_refused(
        monkeypatch, capsys, factory, _STRIP_CHARACTERS, "both"
    )


def test_compiled_conflict_predicate_matches_canonicalizer(monkeypatch, factory):
    cli = h._load_cli(monkeypatch)
    h._fake_token(monkeypatch)
    statements = []

    class CaptureSession(_NormalizedOwnerSession):
        async def execute(self, statement):
            statements.append(statement)
            return await super().execute(statement)

    clock = h._VirtualClock()
    session = CaptureSession(clock, rows={h.Tenant: [h._tenant_row(h.TENANT_ID)]})
    args = cli._build_parser().parse_args([
        "--env", "local", "create", "--email", h.INVITEE_EMAIL, "--tenant", str(h.TENANT_ID)
    ])
    h._drive(clock, cli._create(args, session))
    compiled = statements[2].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "lower(btrim(portal_identity.email," in sql
    assert "lower(trim(" not in sql
    assert _STRIP_CHARACTERS in compiled.params.values()
    assert cli._EMAIL_STRIP_CHARACTERS == _STRIP_CHARACTERS
