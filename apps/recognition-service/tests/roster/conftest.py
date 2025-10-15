import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from roster.config import reload_config
from roster.ports.api_router import router
from roster.ports.dependencies import reset_roster_service


@pytest.fixture()
def roster_data_dir(tmp_path) -> Iterator[str]:
    """Provide an isolated roster data directory for each test."""
    previous_data_dir = os.environ.get("ROSTER_DATA_DIR")
    data_dir = tmp_path / "roster-data"
    data_dir.mkdir()

    os.environ["ROSTER_DATA_DIR"] = str(data_dir)
    reload_config()
    reset_roster_service()

    try:
        yield str(data_dir)
    finally:
        reset_roster_service()
        if previous_data_dir is not None:
            os.environ["ROSTER_DATA_DIR"] = previous_data_dir
        else:
            os.environ.pop("ROSTER_DATA_DIR", None)
        reload_config()


@pytest.fixture()
def api_client(roster_data_dir: str) -> Iterator[TestClient]:
    """Create a FastAPI test client wired to the roster router."""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    try:
        yield client
    finally:
        client.close()
