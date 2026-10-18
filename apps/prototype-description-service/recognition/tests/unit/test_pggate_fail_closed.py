"""Unit coverage for the PostgreSQL gate's fail-closed opt-in."""

import pytest
import sqlalchemy
from sqlalchemy.exc import OperationalError, ProgrammingError

import recognition.tests.conftest as recognition_conftest
from recognition.tests.conftest import _pg_create_scratch_db


class _FailingEngine:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.disposed = False

    def connect(self):
        raise self.error

    def dispose(self) -> None:
        self.disposed = True


@pytest.mark.parametrize(
    ("required", "expected_exception"),
    [
        (False, pytest.skip.Exception),
        (True, pytest.fail.Exception),
    ],
    ids=["skip-by-default", "fail-when-required"],
)
def test_operational_error_is_skip_or_failure(
    monkeypatch: pytest.MonkeyPatch,
    required: bool,
    expected_exception: type[BaseException],
) -> None:
    error = OperationalError("stmt", {}, Exception("refused"))
    engine = _FailingEngine(error)
    monkeypatch.setattr(recognition_conftest, "IDENTITY_PG_REQUIRED", required)
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: engine)

    with pytest.raises(expected_exception) as exc_info:
        _pg_create_scratch_db("postgresql+psycopg://x/postgres", "db", "context")

    assert engine.disposed
    if required:
        assert "IDENTITY_PG_REQUIRED=1" in str(exc_info.value)


@pytest.mark.parametrize(
    ("required", "expected_exception"),
    [
        (False, pytest.skip.Exception),
        (True, pytest.fail.Exception),
    ],
    ids=["skip-by-default", "fail-when-required"],
)
def test_programming_error_is_skip_or_failure(
    monkeypatch: pytest.MonkeyPatch,
    required: bool,
    expected_exception: type[BaseException],
) -> None:
    error = ProgrammingError("stmt", {}, Exception("no vector"))
    engine = _FailingEngine(error)
    monkeypatch.setattr(recognition_conftest, "IDENTITY_PG_REQUIRED", required)
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: engine)

    with pytest.raises(expected_exception) as exc_info:
        _pg_create_scratch_db("postgresql+psycopg://x/postgres", "db", "context")

    assert engine.disposed
    if required:
        assert "IDENTITY_PG_REQUIRED=1" in str(exc_info.value)
