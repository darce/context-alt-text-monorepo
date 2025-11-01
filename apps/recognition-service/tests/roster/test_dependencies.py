"""Tests covering dependency helpers for the roster service."""

from __future__ import annotations

import os
import pytest
from dotenv import load_dotenv

from roster.config import reload_config
from roster.ports.dependencies import get_roster_service, reset_roster_service


@pytest.fixture
def db_url():
    """Database URL for testing."""
    load_dotenv()
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url or not database_url.startswith('postgresql'):
        pytest.skip("PostgreSQL DATABASE_URL not set or not PostgreSQL")
    
    return database_url


def test_get_roster_service_returns_singleton(db_url) -> None:
    os.environ["DATABASE_URL"] = db_url
    reload_config()
    reset_roster_service()
    reload_config()

    first = get_roster_service()
    second = get_roster_service()

    assert first is second

    reset_roster_service()
    third = get_roster_service()
    assert third is not first

    reset_roster_service()
    reload_config()
