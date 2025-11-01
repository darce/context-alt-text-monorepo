import os
from collections.abc import Iterator

import pytest
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.testclient import TestClient

from roster.config import reload_config
from roster.ports.api_router import router
from roster.ports.dependencies import reset_roster_service


@pytest.fixture()
def roster_database_url() -> Iterator[str]:
    """Provide PostgreSQL database URL for roster tests."""
    load_dotenv()
    
    database_url = os.getenv('DATABASE_URL')
    if not database_url or not database_url.startswith('postgresql'):
        pytest.skip("PostgreSQL DATABASE_URL not set or not PostgreSQL")
    
    previous_url = os.environ.get("DATABASE_URL")
    
    os.environ["DATABASE_URL"] = database_url
    reload_config()
    reset_roster_service()

    try:
        yield database_url
    finally:
        reset_roster_service()
        if previous_url is not None:
            os.environ["DATABASE_URL"] = previous_url
        else:
            os.environ.pop("DATABASE_URL", None)
        reload_config()


@pytest.fixture()
def api_client(roster_database_url: str) -> Iterator[TestClient]:
    """Create a FastAPI test client wired to the roster router."""
    from roster.ports.dependencies import get_roster_service
    
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    try:
        yield client
    finally:
        # Clean up test data after each test
        try:
            service = get_roster_service()
            # Clear all test data for common models
            for model in ["adaface_ir101", "insightface_w600k"]:
                try:
                    service.clear_roster(model)
                except:
                    pass
        except:
            pass
        client.close()
