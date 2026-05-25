"""API smoke tests.

Run without Docker — verify the FastAPI app constructs cleanly, serves
``/health``, and the generated OpenAPI schema exposes every endpoint the
FE consumes. Live-infra tests live in ``test_integration.py`` and skip
unless ``docker compose up`` is running.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app


@pytest.fixture(scope="module")
def client():
    """TestClient as a context manager drives lifespan startup/shutdown.
    Postgres/Redis singletons are wired in lifespan but no request hits
    them in this smoke suite, so docker compose is NOT required."""
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_openapi_paths_present(client: TestClient) -> None:
    """Every endpoint the FE consumes must be in the OpenAPI schema."""
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"].keys())
    expected = {
        "/health",
        "/health/ready",
        "/api/portfolio",
        "/api/portfolio/positions",
        "/api/portfolio/account",
        "/api/scans/factor-picks",
        "/api/recommendations",
        "/api/recommendations/{rec_id}",
        "/api/stream/portfolio",
        "/api/stream/heartbeat",
        "/api/stream/prices",
        "/api/stream/trade-updates",
        "/api/market/regime",
        "/api/market/sectors",
        "/api/dashboard",
        "/api/dashboard/briefing",
        "/api/factor-backtests",
        "/api/ic-reports",
        "/api/executions",
        "/api/pipeline/recent",
        "/api/pipeline/today-actions",
    }
    missing = expected - paths
    assert not missing, f"OpenAPI missing paths: {missing}"
