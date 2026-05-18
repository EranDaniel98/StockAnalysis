"""Phase 1 API smoke tests.

These run without Docker — they verify the FastAPI app constructs cleanly,
serves /health, and the generated OpenAPI schema exposes every endpoint
that Phase 2's Next.js client needs. Tests that hit Postgres / Redis /
Alpaca live in tests/api/test_integration.py and require docker compose up.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app


@pytest.fixture(scope="module")
def client():
    """TestClient as a context manager drives lifespan startup/shutdown.
    Postgres/Redis singletons are wired in lifespan but no request hits them
    in this smoke suite, so docker compose is NOT required to run these."""
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_openapi_paths_present(client: TestClient) -> None:
    """Every endpoint Phase 2 will consume must be in the OpenAPI schema."""
    schema = client.get("/openapi.json").json()
    paths = set(schema["paths"].keys())
    expected = {
        "/health",
        "/health/ready",
        "/api/portfolio",
        "/api/portfolio/positions",
        "/api/portfolio/account",
        "/api/scans",
        "/api/scans/{run_id}",
        "/api/backtests",
        "/api/backtests/{run_id}",
        "/api/diagnostics",
        "/api/diagnostics/{run_id}",
        "/api/recommendations",
        "/api/recommendations/{rec_id}",
        "/api/stream/portfolio",
        "/api/stream/heartbeat",
        "/api/stream/scan",
        "/api/stream/prices",
        "/api/stream/trade-updates",
        "/api/market/regime",
        "/api/market/sectors",
        "/api/dashboard",
        "/api/dashboard/briefing",
    }
    missing = expected - paths
    assert not missing, f"OpenAPI missing paths: {missing}"


def test_request_validation_rejects_bad_strategy_body(client: TestClient) -> None:
    """Pydantic should 422 on a malformed scan request — confirms model binding
    is wired correctly without needing to touch the DB."""
    r = client.post("/api/scans", json={"top": -1})
    assert r.status_code == 422


def test_backtest_request_validation(client: TestClient) -> None:
    r = client.post(
        "/api/backtests",
        json={"strategy": "swing_trading", "years": 100},  # exceeds le=20
    )
    assert r.status_code == 422


def test_diagnostic_request_validation(client: TestClient) -> None:
    r = client.post(
        "/api/diagnostics",
        json={"strategy": "swing_trading", "quantiles": 1},  # ge=2
    )
    assert r.status_code == 422
