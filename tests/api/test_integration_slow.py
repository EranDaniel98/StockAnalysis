"""Slow live-infra integration tests — opt-in via `pytest -m slow`.

These drive the API through code paths that hit external services
(Finviz screener, yfinance prices, fundamentals). They're tagged
``slow`` so they're skipped by default and only run when the human
deliberately asks (``uv run pytest -m slow``). The fast suite in
``test_integration.py`` seeds Postgres directly to keep CI green even
when the scrapers are down.

Use case: catching regressions where the scan pipeline imports cleanly
and seeds the DB correctly, but the *real* scan path is broken (e.g.
a screener filter that returns 0 tickers, or analyzer code that only
trips on live data shapes).

Requirements (same as test_integration.py):
  - Postgres on :5432
  - Redis on :6379
  - `alembic upgrade head` applied
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.main import create_app
from src.db.models import ScanRun
from src.db.session import get_dsn

from .test_integration import _postgres_reachable, _redis_reachable

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not (_postgres_reachable() and _redis_reachable()),
        reason="Postgres or Redis not reachable — `docker compose up` first",
    ),
]


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_live_scan_round_trip(client: TestClient) -> None:
    """POST /api/scans with a tiny theme, then GET it back.

    ``robotics_automation`` is the smallest curated theme in
    ``config/sectors.yaml`` (5 known_tickers) so the scan finishes in
    seconds instead of minutes. The point is exercising the full
    discover → fundamentals → prices → analyze → score path end-to-end,
    not stress-testing it.

    The TestClient call blocks until the scan completes — that's the
    point. Finviz + yfinance round-trips dominate the wall-clock here.
    """
    resp = client.post(
        "/api/scans",
        json={
            "strategy": "swing_trading",
            "theme": "robotics_automation",
            "top": 3,
            "fresh": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    run_id = body["run_id"]
    assert body["strategy"] == "swing_trading"
    # n_results may be 0 if every ticker fails stage-2 filters (e.g. all
    # got dropped for missing fundamentals on a bad fetch day). That's
    # still a meaningful "the pipeline ran without exploding" assertion.
    assert isinstance(body["results"], list)
    assert body["n_candidates"] == len(body["results"])

    try:
        # Round-trip: fetch via GET and verify the persisted row matches.
        got = client.get(f"/api/scans/{run_id}")
        assert got.status_code == 200, got.text
        got_body = got.json()
        assert got_body["run_id"] == run_id
        assert got_body["n_results"] == body["n_results"]

        # List view must surface it.
        listing = client.get("/api/scans?strategy=swing_trading&limit=20")
        assert listing.status_code == 200
        assert any(s["run_id"] == run_id for s in listing.json())

        # Spot-check a result's typed shape if anything came back.
        if body["results"]:
            top = body["results"][0]
            assert isinstance(top["ticker"], str) and top["ticker"]
            assert 0 <= top["composite_score"] <= 100
            assert top["action"] in {
                "STRONG BUY",
                "BUY",
                "HOLD",
                "SELL",
                "STRONG SELL",
            }
    finally:
        asyncio.run(_delete_scan_run(run_id))


async def _delete_scan_run(run_id: str) -> None:
    """Cleanup helper — scopes engine creation so the Windows proactor
    transport gets torn down on the same loop that created it."""
    engine = create_async_engine(get_dsn())
    try:
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as s:
            await s.execute(delete(ScanRun).where(ScanRun.universe_label == run_id))
            await s.commit()
    finally:
        await engine.dispose()


# NOTE — there is intentionally no slow happy-path test for
# `/api/stream/scan`. SSE coverage on the unhappy path lives in the fast
# suite (`test_scan_stream_unknown_strategy_emits_error`); a real-scan
# happy path is covered by the POST-based `test_live_scan_round_trip`
# above. Combining "real scan" + "async stream consumer" was attempted
# and consistently failed with "Future attached to a different loop" —
# the module-scoped TestClient drives lifespan + asyncpg pool on its
# own loop, and `httpx.AsyncClient(ASGITransport(app=client.app))`
# routes the request through a different loop, which asyncpg connections
# refuse to cross. Wiring this up correctly needs `asgi-lifespan` (extra
# dep) or running uvicorn in a subprocess (extra complexity) — neither
# justified for one test whose two halves are already each covered.
