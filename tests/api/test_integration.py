"""Phase 1 integration tests — exercise the API against live infra.

Requirements:
  - `docker compose up` (Postgres on 5432, Redis on 6379)
  - `alembic upgrade head` applied
  - ALPACA_API_KEY / ALPACA_API_SECRET in .env (only for portfolio tests)

These tests write real rows to Postgres tables (`scan_runs`, `backtest_runs`,
`ic_diagnostics`). Each test cleans up the rows it creates by ID, so the
suite is safe to re-run against a dev DB. Skip cleanly when infra isn't up
or credentials are missing — they're real assertions, not smoke fillers.
"""

from __future__ import annotations

import os

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.main import create_app
from src.db.models import BacktestRun, ICDiagnostic, ScanRun
from src.db.session import get_dsn


def _postgres_reachable() -> bool:
    """Sync TCP probe — cheaper than spinning up an asyncpg connection."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", 5432))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _redis_reachable() -> bool:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", 6379))
        return True
    except OSError:
        return False
    finally:
        s.close()


pytestmark = pytest.mark.skipif(
    not (_postgres_reachable() and _redis_reachable()),
    reason="Postgres or Redis not reachable — `docker compose up` first",
)


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health_ready_against_live_infra(client: TestClient) -> None:
    """/health/ready hits Postgres + Redis end-to-end."""
    r = client.get("/health/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"status": "ready", "db": "ok", "redis": "ok"}


def test_scan_list_round_trip(client: TestClient) -> None:
    """List endpoint should return 200 with a JSON array even when empty."""
    r = client.get("/api/scans?limit=5")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_backtest_list_round_trip(client: TestClient) -> None:
    r = client.get("/api/backtests?limit=5")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_diagnostic_list_round_trip(client: TestClient) -> None:
    r = client.get("/api/diagnostics?limit=5")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_recommendation_list_round_trip(client: TestClient) -> None:
    r = client.get("/api/recommendations?limit=5")
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_get_unknown_scan_returns_404(client: TestClient) -> None:
    r = client.get("/api/scans/this-run-id-does-not-exist")
    assert r.status_code == 404


def test_get_unknown_backtest_returns_404(client: TestClient) -> None:
    r = client.get("/api/backtests/999999999")
    assert r.status_code == 404


def test_get_unknown_diagnostic_returns_404(client: TestClient) -> None:
    r = client.get("/api/diagnostics/999999999")
    assert r.status_code == 404


def test_scan_db_round_trip(client: TestClient) -> None:
    """Write a ScanRun directly to Postgres, fetch via the API, delete.

    Faster + more reliable than triggering a live scan (which hits Finviz +
    yfinance + the analyzer pipeline). Proves the API ↔ DB wiring: the
    Postgres-side schema accepts what the API model produces, and the
    response model parses what comes back.

    Seed + cleanup share a single event loop so the Windows proactor
    transport doesn't get torn down twice.
    """
    import asyncio
    import uuid
    from datetime import datetime, timezone

    run_id = f"test-{uuid.uuid4()}"
    seed_row = {
        "ticker": "AAPL",
        "action": "BUY",
        "composite_score": 72.5,
        "confidence": "Medium",
        "sub_scores": {"technical": 70, "fundamental": 75},
        "reasoning": ["test seed row"],
        "bullish_signals": 2,
        "bearish_signals": 0,
        "breakdown": [],
        "risk_management": {},
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "name": "Apple Inc.",
        "market_cap": 3_000_000_000_000,
    }

    async def _seed() -> int:
        engine = create_async_engine(get_dsn())
        try:
            Session = async_sessionmaker(engine, expire_on_commit=False)
            async with Session() as s:
                row = ScanRun(
                    strategy="swing_trading",
                    scan_timestamp=datetime.now(timezone.utc),
                    universe_label=run_id,
                    budget=10_000.0,
                    n_candidates=1,
                    recommendations=[seed_row],
                )
                s.add(row)
                await s.commit()
                await s.refresh(row)
                return row.id
        finally:
            await engine.dispose()

    async def _cleanup(row_id: int) -> None:
        engine = create_async_engine(get_dsn())
        try:
            Session = async_sessionmaker(engine, expire_on_commit=False)
            async with Session() as s:
                await s.execute(delete(ScanRun).where(ScanRun.id == row_id))
                await s.commit()
        finally:
            await engine.dispose()

    seeded_id = asyncio.run(_seed())
    try:
        r = client.get(f"/api/scans/{run_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["run_id"] == run_id
        assert body["strategy"] == "swing_trading"
        assert body["n_results"] == 1
        assert body["results"][0]["ticker"] == "AAPL"
        assert body["results"][0]["composite_score"] == 72.5

        r_list = client.get("/api/scans?strategy=swing_trading&limit=20")
        assert r_list.status_code == 200
        seeded = [s for s in r_list.json() if s["run_id"] == run_id]
        assert len(seeded) == 1
        assert seeded[0]["top_ticker"] == "AAPL"
    finally:
        asyncio.run(_cleanup(seeded_id))


@pytest.mark.skipif(
    not (os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET")),
    reason="Alpaca paper credentials not set",
)
def test_portfolio_account_against_live_alpaca(client: TestClient) -> None:
    """Hits Alpaca paper API. Skips when keys aren't present."""
    r = client.get("/api/portfolio/account")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "equity" in body
    assert "buying_power" in body
    assert body["status"]
