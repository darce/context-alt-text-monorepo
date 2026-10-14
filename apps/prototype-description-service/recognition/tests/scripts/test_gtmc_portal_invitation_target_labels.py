"""Offline portal-label and legacy identity regressions (fixture data only)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.sql.elements import Label
from sqlalchemy.sql.functions import Function

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
        argument, = expression.clauses
        value = _value(argument, row)
        assert expression.name in {"lower", "trim"}
        return None if value is None else (value.lower() if expression.name == "lower" else value.strip(" "))
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
