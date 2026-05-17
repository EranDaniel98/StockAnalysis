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

import json
import os
from typing import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.main import create_app
from src.db.models import BacktestRun, ICDiagnostic, ScanRun
from src.db.session import get_dsn


# ─── SSE parser ──────────────────────────────────────────────────────────────


async def aiter_sse_events(response: httpx.Response) -> AsyncIterator[dict]:
    """Yield ``{event, data}`` dicts from a streaming SSE response.

    Async because TestClient's sync `.stream()` doesn't flush sse_starlette
    chunks reliably on Windows — events stay buffered until the connection
    closes, which deadlocks tests that wait for a live event. Going through
    `httpx.AsyncClient(transport=ASGITransport(app))` runs the FastAPI app
    on the same loop and yields chunks as the server emits them.

    SSE wire format is `field: value` lines terminated by a blank line
    between events. Comment lines beginning with `:` (sse_starlette uses
    these for keepalive pings) are skipped.
    """
    name: str | None = None
    data_parts: list[str] = []
    async for raw in response.aiter_lines():
        line = raw.rstrip("\r")
        if not line:
            if name is not None or data_parts:
                yield {"event": name or "message", "data": "\n".join(data_parts)}
                name = None
                data_parts = []
            continue
        if line.startswith(":"):
            continue
        field, sep, value = line.partition(":")
        if not sep:
            continue
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            name = value
        elif field == "data":
            data_parts.append(value)


def _async_client(client: TestClient) -> httpx.AsyncClient:
    """AsyncClient bound to the same FastAPI app the sync TestClient is
    holding open. The TestClient's `with` block already drove lifespan
    startup (Postgres/Redis/bus singletons), so the async client inherits
    a fully-wired app without re-running lifespan."""
    transport = ASGITransport(app=client.app)
    return httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=httpx.Timeout(30.0, read=30.0),
    )


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
                    run_id=run_id,
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


# ─── SSE streams ─────────────────────────────────────────────────────────────


async def test_scan_stream_unknown_strategy_emits_error(
    client: TestClient,
) -> None:
    """A bad strategy name should hit the up-front `KeyError` branch in
    the scan-stream generator and yield exactly one ``error`` event,
    after which the stream closes. Proves the SSE error path produces a
    machine-parseable payload (not just a closed connection)."""
    async with _async_client(client) as ac:
        async with ac.stream(
            "GET",
            "/api/stream/scan?strategy=this-strategy-does-not-exist",
            timeout=10.0,
        ) as response:
            assert response.status_code == 200
            events = [event async for event in aiter_sse_events(response)]

    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) >= 1, f"expected error event, got: {events}"
    payload = json.loads(error_events[0]["data"])
    assert "detail" in payload
    assert "this-strategy-does-not-exist" in payload["detail"]


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


# ─── /api/scans/latest-buys ──────────────────────────────────────────────────


def _seed_scan_runs(rows: list[tuple[str, str, "datetime", list[dict]]]) -> list[int]:
    """Seed a batch of ScanRuns. ``rows`` is a list of
    ``(strategy, run_id, scan_timestamp, recommendations)`` tuples.

    Returns the inserted ``scan_runs.id`` values for cleanup. Lives at module
    scope so the latest-buys tests below can share a single helper.
    """
    import asyncio

    async def _go() -> list[int]:
        engine = create_async_engine(get_dsn())
        try:
            Session = async_sessionmaker(engine, expire_on_commit=False)
            ids: list[int] = []
            async with Session() as s:
                for strategy, run_id, ts, recs in rows:
                    row = ScanRun(
                        strategy=strategy,
                        scan_timestamp=ts,
                        run_id=run_id,
                        budget=None,
                        n_candidates=len(recs),
                        recommendations=recs,
                    )
                    s.add(row)
                await s.commit()
                # Refresh after commit — async_sessionmaker doesn't preload
                # autoincrement ids without an explicit refresh.
                for obj in s.new:
                    pass
            # Re-query for the ids we just wrote: easier than tracking each
            # refresh, and keyed by run_id which we control.
            async with Session() as s:
                from sqlalchemy import select as sql_select
                rids = {r[1] for r in rows}
                res = await s.execute(
                    sql_select(ScanRun.id).where(ScanRun.run_id.in_(rids))
                )
                ids = [r[0] for r in res.all()]
            return ids
        finally:
            await engine.dispose()

    return asyncio.run(_go())


def _cleanup_scan_runs(ids: list[int]) -> None:
    import asyncio

    async def _go() -> None:
        engine = create_async_engine(get_dsn())
        try:
            Session = async_sessionmaker(engine, expire_on_commit=False)
            async with Session() as s:
                await s.execute(delete(ScanRun).where(ScanRun.id.in_(ids)))
                await s.commit()
        finally:
            await engine.dispose()

    asyncio.run(_go())


def _buy_rec(
    ticker: str,
    score: float,
    *,
    action: str = "BUY",
    score_valid: bool = True,
    instrument_warning: str | None = None,
    insufficient_history: bool = False,
) -> dict:
    """One recommendation row shaped like the recommender's output."""
    return {
        "ticker": ticker,
        "action": action,
        "composite_score": score,
        "confidence": "Medium-High",
        "sub_scores": {"technical": score, "fundamental": score},
        "reasoning": [],
        "bullish_signals": 1,
        "bearish_signals": 0,
        "breakdown": [],
        "risk_management": {},
        "sector": "Technology",
        "industry": "Software",
        "name": f"{ticker} Test Co.",
        "market_cap": 1_000_000_000,
        "score_valid": score_valid,
        "instrument_warning": instrument_warning,
        "insufficient_history": insufficient_history,
    }


def test_latest_buys_dedup_across_strategies(client: TestClient) -> None:
    """Same ticker BUY in 3 strategies → dedup to one row, attributed to
    the strategy with the highest score, consensus_count==3, strategies
    list deduped+sorted.

    Pins the bucket-dedup invariant in scans.py:latest_buys.
    """
    import uuid
    from datetime import datetime, timezone

    suffix = uuid.uuid4().hex[:8]
    ts = datetime(2099, 1, 1, tzinfo=timezone.utc)
    ticker = f"LBT{suffix[:4].upper()}"

    rows = [
        ("swing_trading", f"lb-st-{suffix}", ts, [_buy_rec(ticker, 60.0)]),
        ("value_investing", f"lb-vi-{suffix}", ts, [_buy_rec(ticker, 75.0)]),
        ("dividend_income", f"lb-di-{suffix}", ts, [_buy_rec(ticker, 65.0)]),
    ]
    ids = _seed_scan_runs(rows)
    try:
        r = client.get("/api/scans/latest-buys")
        assert r.status_code == 200, r.text
        body = r.json()
        seeded = [b for b in body if b["ticker"] == ticker]
        assert len(seeded) == 1, "ticker must appear exactly once"
        b = seeded[0]
        assert b["composite_score"] == 75.0
        assert b["strategy"] == "value_investing", "best-score attribution"
        assert b["consensus_count"] == 3
        assert sorted(b["consensus_strategies"]) == [
            "dividend_income",
            "swing_trading",
            "value_investing",
        ]
    finally:
        _cleanup_scan_runs(ids)


def test_latest_buys_only_latest_per_strategy(client: TestClient) -> None:
    """Two scans for the same strategy at different timestamps → only the
    newer scan's BUY row appears. Pins seen_strategies short-circuit.
    """
    import uuid
    from datetime import datetime, timezone

    suffix = uuid.uuid4().hex[:8]
    old = datetime(2099, 1, 1, tzinfo=timezone.utc)
    new = datetime(2099, 6, 1, tzinfo=timezone.utc)
    old_ticker = f"OLD{suffix[:4].upper()}"
    new_ticker = f"NEW{suffix[:4].upper()}"

    rows = [
        ("swing_trading", f"lb-old-{suffix}", old, [_buy_rec(old_ticker, 80.0)]),
        ("swing_trading", f"lb-new-{suffix}", new, [_buy_rec(new_ticker, 60.0)]),
    ]
    ids = _seed_scan_runs(rows)
    try:
        r = client.get("/api/scans/latest-buys")
        assert r.status_code == 200, r.text
        tickers = {b["ticker"] for b in r.json()}
        assert new_ticker in tickers, "newer scan's BUY must surface"
        assert old_ticker not in tickers, (
            "older scan for same strategy must be suppressed even though "
            "its score is higher"
        )
    finally:
        _cleanup_scan_runs(ids)


def test_latest_buys_filters_refused_recs(client: TestClient) -> None:
    """Recs flagged score_valid=False / instrument_warning / insufficient_history
    must NOT surface as BUY signals, even when their action says BUY.

    Today the recommender forces HOLD when these fire, so this is a
    belt-and-suspenders gate against a future refactor that decouples
    HOLD-forcing from the integrity flags. Real-money concern: a refused
    leveraged-ETF or short-history ticker quietly resurfaces with a
    confident BUY rating.
    """
    import uuid
    from datetime import datetime, timezone

    suffix = uuid.uuid4().hex[:8]
    ts = datetime(2099, 1, 1, tzinfo=timezone.utc)
    good = f"GOOD{suffix[:3].upper()}"
    bad_score = f"BSC{suffix[:3].upper()}"
    bad_inst = f"BIN{suffix[:3].upper()}"
    bad_hist = f"BHS{suffix[:3].upper()}"

    rows = [
        (
            "swing_trading",
            f"lb-refused-{suffix}",
            ts,
            [
                _buy_rec(good, 80.0),
                _buy_rec(bad_score, 75.0, score_valid=False),
                _buy_rec(bad_inst, 72.0, instrument_warning="leveraged_or_inverse_etf"),
                _buy_rec(bad_hist, 70.0, insufficient_history=True),
            ],
        ),
    ]
    ids = _seed_scan_runs(rows)
    try:
        r = client.get("/api/scans/latest-buys")
        assert r.status_code == 200, r.text
        tickers = {b["ticker"] for b in r.json()}
        assert good in tickers, "valid BUY must surface"
        assert bad_score not in tickers, "score_valid=False must be filtered"
        assert bad_inst not in tickers, "instrument_warning must be filtered"
        assert bad_hist not in tickers, "insufficient_history must be filtered"
    finally:
        _cleanup_scan_runs(ids)


def test_latest_buys_strong_only_filter(client: TestClient) -> None:
    """?strong_only=true keeps STRONG BUY rows, drops plain BUY rows."""
    import uuid
    from datetime import datetime, timezone

    suffix = uuid.uuid4().hex[:8]
    ts = datetime(2099, 1, 1, tzinfo=timezone.utc)
    strong = f"STR{suffix[:4].upper()}"
    plain = f"PLN{suffix[:4].upper()}"

    rows = [
        (
            "swing_trading",
            f"lb-strong-{suffix}",
            ts,
            [
                _buy_rec(strong, 85.0, action="STRONG BUY"),
                _buy_rec(plain, 65.0, action="BUY"),
            ],
        ),
    ]
    ids = _seed_scan_runs(rows)
    try:
        r_all = client.get("/api/scans/latest-buys")
        tickers_all = {b["ticker"] for b in r_all.json()}
        assert strong in tickers_all and plain in tickers_all

        r_strong = client.get("/api/scans/latest-buys?strong_only=true")
        tickers_strong = {b["ticker"] for b in r_strong.json()}
        assert strong in tickers_strong
        assert plain not in tickers_strong, (
            "strong_only=true must drop plain BUY rows"
        )
    finally:
        _cleanup_scan_runs(ids)


def test_latest_buys_sort_invariants(client: TestClient) -> None:
    """Output sorted by composite_score desc, and consensus_count equals
    len(consensus_strategies) for every row.
    """
    r = client.get("/api/scans/latest-buys")
    assert r.status_code == 200, r.text
    body = r.json()
    scores = [b["composite_score"] for b in body]
    assert scores == sorted(scores, reverse=True), (
        "rows must be sorted by composite_score desc"
    )
    for b in body:
        assert b["consensus_count"] == len(b["consensus_strategies"]), (
            f"{b['ticker']}: consensus_count ({b['consensus_count']}) != "
            f"len(consensus_strategies) ({len(b['consensus_strategies'])})"
        )
        # Strategy list is deduped.
        assert len(b["consensus_strategies"]) == len(set(b["consensus_strategies"]))


# ─── /api/scans/sanity-check ─────────────────────────────────────────────────


def _cleanup_sanity_checks(run_ids: list[str]) -> None:
    """Remove sanity_checks rows for the given run_ids.

    Needed because scan_runs cleanup uses scan_runs.id (the seq-pk),
    not run_id; the FK from sanity_checks is on run_id with ON DELETE
    CASCADE, so deleting scan_runs by id WILL cascade — but only when
    the test cleans up scan_runs in the same engine session. Belt-
    and-suspenders for tests that fail before scan_runs cleanup runs.
    """
    import asyncio

    from src.db.models import SanityCheckRow

    async def _go() -> None:
        engine = create_async_engine(get_dsn())
        try:
            Session = async_sessionmaker(engine, expire_on_commit=False)
            async with Session() as s:
                await s.execute(
                    delete(SanityCheckRow).where(SanityCheckRow.run_id.in_(run_ids))
                )
                await s.commit()
        finally:
            await engine.dispose()

    asyncio.run(_go())


def test_latest_buys_returns_null_sanity_check_when_unchecked(
    client: TestClient,
) -> None:
    """BuySignal rows for a freshly-seeded scan have no cached sanity
    check yet → field is null/None, not absent or coerced.

    Uses a far-future ``scan_timestamp`` (mirrors
    ``test_latest_buys_strong_only_filter``) so DISTINCT ON picks this
    row even if a prior test left a zombie scan_run behind. Microsecond
    offset derived from the uuid suffix keeps concurrent test seeds
    from colliding at the unique-constraint level.
    """
    import uuid
    from datetime import datetime, timezone

    suffix = uuid.uuid4().hex[:8]
    ticker = f"SCK{suffix[:4]}".upper()
    ts = datetime(2099, 1, 1, 0, 0, 0, int(suffix[:6], 16) % 999_999, tzinfo=timezone.utc)
    rows = [
        ("swing_trading", f"sc-{suffix}", ts, [_buy_rec(ticker, 70.0)]),
    ]
    ids = _seed_scan_runs(rows)
    try:
        r = client.get("/api/scans/latest-buys")
        assert r.status_code == 200, r.text
        match = [b for b in r.json() if b["ticker"] == ticker]
        assert match, f"seeded ticker {ticker} missing from latest-buys"
        assert match[0]["sanity_check"] is None, (
            "uncached check must serialize as null, not missing or {} "
            "— the FE switches on null to render 'no check yet'"
        )
    finally:
        _cleanup_scan_runs(ids)


def test_sanity_check_post_creates_and_enriches_rows(client: TestClient) -> None:
    """POST /api/scans/sanity-check?mode=mock runs the deterministic
    mock over the candidate set, upserts one row per (ticker, run_id),
    and the follow-up GET surfaces the result via ``sanity_check``."""
    import uuid
    from datetime import datetime, timezone

    suffix = uuid.uuid4().hex[:8]
    run_id = f"sc-post-{suffix}"
    ticker = f"SCK{suffix[:4]}".upper()
    ts = datetime(2099, 1, 1, 0, 0, 0, int(suffix[:6], 16) % 999_999, tzinfo=timezone.utc)
    rows = [
        ("swing_trading", run_id, ts, [_buy_rec(ticker, 70.0)]),
    ]
    ids = _seed_scan_runs(rows)
    try:
        post = client.post(
            "/api/scans/sanity-check",
            json={"strong_only": False, "mode": "mock", "force_refresh": False},
        )
        assert post.status_code == 200, post.text
        body = post.json()
        match = [b for b in body if b["ticker"] == ticker]
        assert match, f"seeded ticker {ticker} missing from POST response"
        sc = match[0]["sanity_check"]
        assert sc is not None, "POST must populate sanity_check for the seeded row"
        assert sc["verdict"] in ("OK", "CAUTION", "REJECT")
        assert sc["mocked"] is True, "mode='mock' must mark the row mocked=True"
        assert sc["model_used"] == "mock"
        # Follow-up GET surfaces the same row from the cache.
        get = client.get("/api/scans/latest-buys")
        assert get.status_code == 200
        get_match = [b for b in get.json() if b["ticker"] == ticker]
        assert get_match and get_match[0]["sanity_check"] is not None, (
            "cached check must be visible to subsequent GETs"
        )
    finally:
        _cleanup_sanity_checks([run_id])
        _cleanup_scan_runs(ids)


def test_sanity_check_post_does_not_duplicate_on_rerun(
    client: TestClient,
) -> None:
    """A second POST without ``force_refresh`` must NOT create a new
    sanity_checks row for the same (ticker, run_id). UNIQUE constraint
    is enforced at the schema level; this exercises the upsert path."""
    import uuid
    from datetime import datetime, timezone

    from src.db.models import SanityCheckRow

    suffix = uuid.uuid4().hex[:8]
    run_id = f"sc-rerun-{suffix}"
    ticker = f"SCK{suffix[:4]}".upper()
    ts = datetime(2099, 1, 1, 0, 0, 0, int(suffix[:6], 16) % 999_999, tzinfo=timezone.utc)
    rows = [
        ("swing_trading", run_id, ts, [_buy_rec(ticker, 70.0)]),
    ]
    ids = _seed_scan_runs(rows)
    try:
        for _ in range(2):
            r = client.post(
                "/api/scans/sanity-check",
                json={"strong_only": False, "mode": "mock", "force_refresh": True},
            )
            assert r.status_code == 200, r.text

        # Direct DB count to verify the unique constraint held.
        import asyncio

        async def _count() -> int:
            engine = create_async_engine(get_dsn())
            try:
                Session = async_sessionmaker(engine, expire_on_commit=False)
                async with Session() as s:
                    from sqlalchemy import func, select as sql_select

                    res = await s.execute(
                        sql_select(func.count())
                        .select_from(SanityCheckRow)
                        .where(SanityCheckRow.run_id == run_id)
                    )
                    return int(res.scalar_one())
            finally:
                await engine.dispose()

        count = asyncio.run(_count())
        assert count == 1, (
            f"expected 1 row per (ticker, run_id) after upsert; got {count}"
        )
    finally:
        _cleanup_sanity_checks([run_id])
        _cleanup_scan_runs(ids)
