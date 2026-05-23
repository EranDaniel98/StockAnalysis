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

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.main import create_app
from src.db.models import ScanRun
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


def test_get_unknown_backtest_returns_404(client: TestClient) -> None:
    r = client.get("/api/backtests/999999999")
    assert r.status_code == 404


def test_get_unknown_diagnostic_returns_404(client: TestClient) -> None:
    r = client.get("/api/diagnostics/999999999")
    assert r.status_code == 404


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


# ─── SSE streams ─────────────────────────────────────────────────────────────


def test_dashboard_round_trip(client: TestClient) -> None:
    """Seed a ScanRun with one BUY row, GET /api/dashboard, verify the
    strategy card surfaces it and the cross-strategy pool picks it up.

    Like `test_scan_db_round_trip`, this avoids the live screener path —
    we want to assert the aggregation + sweep-fallback wiring, not
    finviz/yfinance behavior.
    """
    import asyncio
    import uuid
    from datetime import datetime, timezone

    run_id = f"test-dash-{uuid.uuid4()}"
    ticker = "DASHTEST"
    seed_rec = {
        "ticker": ticker,
        "action": "BUY",
        "composite_score": 88.4,
        "confidence": "High",
        "sub_scores": {"technical": 85, "fundamental": 90},
        "reasoning": ["dashboard integration seed"],
        "bullish_signals": 4,
        "bearish_signals": 0,
        "breakdown": [],
        "risk_management": {"entry_price": 123.45, "stop_loss": 110.0},
        "sector": "Technology",
        "industry": "Software",
        "name": "Dashboard Test Co.",
        "market_cap": 5_000_000_000,
    }

    async def _seed() -> int:
        engine = create_async_engine(get_dsn())
        try:
            Session = async_sessionmaker(engine, expire_on_commit=False)
            async with Session() as s:
                row = ScanRun(
                    strategy="swing_trading",
                    # Pin a future-ish timestamp so this row beats any
                    # real swing_trading scan that's already in the DB.
                    # The dashboard query orders by scan_timestamp desc.
                    scan_timestamp=datetime(2099, 1, 1, tzinfo=timezone.utc),
                    run_id=run_id,
                    budget=None,
                    n_candidates=1,
                    recommendations=[seed_rec],
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
        r = client.get("/api/dashboard")
        assert r.status_code == 200, r.text
        body = r.json()

        assert "generated_at" in body
        assert "strategies" in body
        assert "top_picks" in body

        # Strategy card surfaces our seed row.
        swing = next(
            (c for c in body["strategies"] if c["strategy"] == "swing_trading"),
            None,
        )
        assert swing is not None, "swing_trading card missing from dashboard"
        assert swing["last_scan_run_id"] == run_id, (
            "seeded ScanRun should win 'most recent' on the 2099 timestamp"
        )
        assert swing["n_buys"] >= 1
        seeded_pick = next(
            (p for p in swing["top_picks"] if p["ticker"] == ticker), None
        )
        assert seeded_pick is not None, "seeded ticker missing from top_picks"
        assert seeded_pick["composite_score"] == 88.4
        assert seeded_pick["entry_price"] == 123.45

        # Cross-strategy pool should also pick it up.
        in_cross = any(p["ticker"] == ticker for p in body["top_picks"])
        assert in_cross, "seeded BUY missing from cross-strategy top_picks"
    finally:
        asyncio.run(_cleanup(seeded_id))

