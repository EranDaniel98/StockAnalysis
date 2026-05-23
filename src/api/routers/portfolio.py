"""Portfolio endpoints.

Read-only views on top of the Alpaca paper account. The Alpaca SDK is sync;
wrap each call in `asyncio.to_thread` so we don't block the event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.execution.alpaca import AlpacaClient, AlpacaClientError

logger = logging.getLogger(__name__)
router = APIRouter()


class EquityPoint(BaseModel):
    timestamp: int
    """Epoch seconds. Frontend converts to a Date for display."""
    equity: float
    profit_loss: float
    profit_loss_pct: float | None = None
    spy_equity: float | None = Field(
        default=None,
        description=(
            "Synthetic SPY equity at this timestamp, normalized so that "
            "the first point of the window equals ``base_value``. Lets the "
            "FE plot a same-axis alpha line. Null when "
            "``include_spy=false`` or SPY data couldn't be fetched."
        ),
    )


class PortfolioHistory(BaseModel):
    period: str
    timeframe: str
    base_value: float | None = None
    points: list[EquityPoint] = Field(default_factory=list)
    spy_status: Literal["ok", "skipped", "unavailable"] = Field(
        default="skipped",
        description=(
            "'ok' = SPY normalized line included on every point; "
            "'skipped' = include_spy=false; "
            "'unavailable' = SPY fetch failed (yfinance down / DNS). "
            "FE should hide the SPY series when not 'ok'."
        ),
    )


class AccountSummary(BaseModel):
    account_number: str
    status: str
    equity: float
    cash: float
    buying_power: float
    portfolio_value: float
    long_market_value: float
    pattern_day_trader: bool


class Position(BaseModel):
    ticker: str
    shares: float
    avg_price: float
    current_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0


class PortfolioStatus(BaseModel):
    account: AccountSummary
    positions: list[Position]
    n_positions: int = Field(ge=0)


PositionStatus = Literal[
    "HOLDING",
    "STOP_HIT",
    "NEAR_STOP",
    "TARGET_HIT",
    "NEAR_TARGET",
]


class PositionRecommendation(BaseModel):
    """Per-position recommended levels + basket-membership verdict.

    Sourced from the most-recent ``portfolio_analysis_*.json``. When the
    ticker is held but not in the analysis (legacy position from before
    the current strategy), the response uses ``source='fallback_8pct'``
    bands at ±8% / +10%.
    """
    ticker: str
    stop_loss: float
    target: float
    time_exit_date: Optional[date] = Field(
        default=None,
        description=(
            "Quarter-end forced exit from the analysis JSON. Null when "
            "the ticker isn't in the current basket."
        ),
    )
    expected_return_pct: Optional[float] = Field(default=None)
    source: Literal["strategy", "fallback_8pct"]
    in_todays_basket: bool = Field(
        description=(
            "True when the ticker is in today's factor picks — i.e. the "
            "system would KEEP this position on rebalance. False = EXIT."
        ),
    )
    status: PositionStatus = Field(
        description=(
            "Live classification vs the recommended levels. Mirrors "
            "scripts/position_monitor.py and "
            "src.api.routers.briefing._classify_position."
        ),
    )


class PortfolioRecommendations(BaseModel):
    as_of: Optional[date] = Field(
        default=None,
        description="picks_date underlying these recommendations.",
    )
    analysis_path: Optional[str] = Field(
        default=None,
        description="Filename of the portfolio_analysis JSON consulted.",
    )
    recommendations: list[PositionRecommendation] = Field(default_factory=list)
    n_at_risk: int = Field(
        default=0, ge=0,
        description="Count of positions with status != HOLDING.",
    )


def _build_client() -> AlpacaClient:
    try:
        return AlpacaClient()
    except AlpacaClientError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("", response_model=PortfolioStatus)
async def get_portfolio() -> PortfolioStatus:
    """Live snapshot: account fields + current positions."""
    client = _build_client()
    account = await asyncio.to_thread(client.get_account)
    positions = await asyncio.to_thread(client.get_positions)
    return PortfolioStatus(
        account=AccountSummary(**account),
        positions=[Position(**p) for p in positions],
        n_positions=len(positions),
    )


@router.get("/positions", response_model=list[Position])
async def get_positions() -> list[Position]:
    client = _build_client()
    positions = await asyncio.to_thread(client.get_positions)
    return [Position(**p) for p in positions]


@router.get("/account", response_model=AccountSummary)
async def get_account() -> AccountSummary:
    client = _build_client()
    account = await asyncio.to_thread(client.get_account)
    return AccountSummary(**account)


_PERIOD_VALUES = ("1D", "1W", "1M", "3M", "6M", "1A")
_TIMEFRAME_VALUES = ("1Min", "5Min", "15Min", "1H", "1D")


# ----------------------------- helpers ------------------------------

# Recommendation defaults for held positions that aren't in today's basket.
# Matches src.api.routers.briefing constants so /portfolio and /api/dashboard/briefing
# classify the same way.
_FALLBACK_STOP_PCT = 0.08
_FALLBACK_TARGET_PCT = 0.10
_NEAR_STOP_MULT = 1.02
_NEAR_TARGET_MULT = 0.98

PICKS_DIR = Path("data/daily_picks")
REPORTS_DIR = Path("reports")
PAPER_VS_SPY_FILE = REPORTS_DIR / "paper_vs_spy.json"


class PaperVsSpyPaperLeg(BaseModel):
    starting_equity_usd: float
    current_equity_usd: float
    pnl_usd: float
    return_pct: float


class PaperVsSpySpyLeg(BaseModel):
    starting_price: float
    current_price: float
    return_pct: float


class PaperVsSpySnapshot(BaseModel):
    """Mirror of ``reports/paper_vs_spy.json``. The Python snapshot
    script writes this file on every daily-pipeline run; the FE reads
    it via this endpoint so it doesn't have to share the filesystem."""
    status: Literal["ok", "not_configured", "no_history", "error"]
    message: Optional[str] = None
    generated_at_utc: str
    window_days: int
    paper: Optional[PaperVsSpyPaperLeg] = None
    spy: Optional[PaperVsSpySpyLeg] = None
    alpha_pct: Optional[float] = None


def _latest_portfolio_analysis() -> Optional[Path]:
    if not REPORTS_DIR.exists():
        return None
    candidates = sorted(REPORTS_DIR.glob("portfolio_analysis_*.json"))
    return candidates[-1] if candidates else None


def _latest_picks_path() -> Optional[Path]:
    if not PICKS_DIR.exists():
        return None
    candidates = sorted(PICKS_DIR.glob("*.json"))
    return candidates[-1] if candidates else None


def _classify_position(
    current: float, stop: float, target: float,
) -> PositionStatus:
    if current <= stop:
        return "STOP_HIT"
    if current >= target:
        return "TARGET_HIT"
    if current <= stop * _NEAR_STOP_MULT:
        return "NEAR_STOP"
    if current >= target * _NEAR_TARGET_MULT:
        return "NEAR_TARGET"
    return "HOLDING"


def _fetch_spy_history_sync(
    period: str, timeframe: str,
) -> Optional["list[tuple[int, float]]"]:
    """yfinance lookup for SPY over the same window. Returns a list of
    (epoch_seconds, close_price) tuples or None when the fetch fails.

    Period mapping: Alpaca uses 1D/1W/1M/3M/6M/1A; yfinance uses
    1d/5d/1mo/3mo/6mo/1y. ``timeframe`` is Alpaca-style; we map to
    yfinance intervals only for the intraday cases where 1m bars exist.
    """
    yf_period_map = {
        "1D": "1d", "1W": "5d", "1M": "1mo",
        "3M": "3mo", "6M": "6mo", "1A": "1y",
    }
    yf_interval_map = {
        "1Min": "1m", "5Min": "5m", "15Min": "15m",
        "1H": "60m", "1D": "1d",
    }
    yf_period = yf_period_map.get(period, "1mo")
    yf_interval = yf_interval_map.get(timeframe, "1d")
    try:
        import yfinance as yf

        df = yf.Ticker("SPY").history(
            period=yf_period, interval=yf_interval, auto_adjust=True,
        )
        if df is None or df.empty:
            return None
        out: list[tuple[int, float]] = []
        for ts, row in df["Close"].items():
            # pandas Timestamp -> epoch seconds; tz-aware -> UTC.
            try:
                epoch = int(ts.timestamp())
            except Exception:  # noqa: BLE001
                continue
            try:
                px = float(row)
            except (TypeError, ValueError):
                continue
            out.append((epoch, px))
        return out or None
    except Exception as e:  # noqa: BLE001
        logger.warning("SPY history fetch failed (%s, %s): %s", period, timeframe, e)
        return None


def _align_spy_to_equity(
    portfolio_ts: list[int],
    spy_series: list[tuple[int, float]],
    base_value: float,
) -> list[Optional[float]]:
    """For each portfolio timestamp, find the closest-prior SPY close and
    rebase so the first portfolio point and the first SPY point have the
    SAME value of ``base_value``. Anchor SPY price is the SPY tick closest
    to (and not later than) the first portfolio timestamp — using SPY's
    earliest tick instead would shift the first SPY value above/below the
    portfolio's starting equity whenever the portfolio window starts later
    than SPY's first available bar.

    Returns None at any portfolio timestamp that has no preceding SPY
    tick, so the FE can ``connectNulls`` over the gap.
    """
    if not portfolio_ts or not spy_series or base_value <= 0:
        return [None] * len(portfolio_ts)
    spy_sorted = sorted(spy_series, key=lambda x: x[0])
    spy_ts = [t for t, _ in spy_sorted]
    spy_px = [p for _, p in spy_sorted]

    # Find SPY anchor: latest SPY tick at-or-before portfolio's first ts.
    first_pt = portfolio_ts[0]
    anchor_idx: Optional[int] = None
    for i, t in enumerate(spy_ts):
        if t <= first_pt:
            anchor_idx = i
        else:
            break
    if anchor_idx is None:
        # SPY hasn't traded yet at portfolio start — fall back to SPY's
        # earliest tick so we still emit a usable line, but flag the
        # caller can detect the mismatch (returned spy_equity[0] != base).
        anchor_idx = 0
    anchor_px = spy_px[anchor_idx]
    if anchor_px <= 0:
        return [None] * len(portfolio_ts)

    out: list[Optional[float]] = []
    j = 0  # walking-pointer; O(n + m) overall
    last_px: Optional[float] = spy_px[anchor_idx]
    # Advance j past the anchor so subsequent walks pick up forward ticks.
    j = anchor_idx
    for pt in portfolio_ts:
        while j < len(spy_ts) and spy_ts[j] <= pt:
            last_px = spy_px[j]
            j += 1
        if last_px is None:
            out.append(None)
        else:
            out.append(base_value * (last_px / anchor_px))
    return out


# ----------------------------- endpoints ------------------------------


@router.get("/history", response_model=PortfolioHistory)
async def get_history(
    period: Literal["1D", "1W", "1M", "3M", "6M", "1A"] = Query(default="1M"),
    timeframe: Literal["1Min", "5Min", "15Min", "1H", "1D"] = Query(default="1D"),
    include_spy: bool = Query(
        default=False,
        description="When true, overlay a same-axis SPY equity line.",
    ),
) -> PortfolioHistory:
    """Equity curve from Alpaca's portfolio history.

    ``period`` is Alpaca's window shorthand (1D / 1W / 1M / 3M / 6M / 1A).
    ``timeframe`` is the bar size; intraday timeframes are silently
    downgraded to 1D for windows > 1W (Alpaca rejects them otherwise).

    When ``include_spy=true``, each point also carries a synthetic
    ``spy_equity`` value derived from yfinance SPY closes, normalized so
    the window's first point matches ``base_value`` — both lines share
    the same y-axis and the visual gap is alpha.
    """
    client = _build_client()
    raw = await asyncio.to_thread(client.get_portfolio_history, period, timeframe)

    timestamps: list[int] = raw["timestamps"]
    equities: list[float] = raw["equity"]
    pls: list[float] = raw["profit_loss"]
    plps: list[Optional[float]] = raw["profit_loss_pct"]

    # Alpaca returns equity=0 for bars that predate account funding. Leaving
    # those in makes the chart draw a $0 -> $41k spike on day 1, dwarfing
    # any actual movement, and anchors the SPY overlay to a pre-funding
    # date so the two lines never share a starting value. Strip leading
    # zero-equity points; re-anchor base_value to the first funded bar.
    first_funded = next(
        (i for i, e in enumerate(equities) if e and e > 0), None,
    )
    if first_funded is not None and first_funded > 0:
        timestamps = timestamps[first_funded:]
        equities = equities[first_funded:]
        pls = pls[first_funded:]
        plps = plps[first_funded:]

    if equities:
        anchor_value = float(equities[0])
    else:
        anchor_value = float(raw.get("base_value") or 0.0)

    spy_status: Literal["ok", "skipped", "unavailable"] = "skipped"
    spy_equity: list[Optional[float]] = [None] * len(timestamps)
    if include_spy and timestamps and anchor_value > 0:
        spy_series = await asyncio.to_thread(
            _fetch_spy_history_sync, period, timeframe,
        )
        if spy_series:
            spy_equity = _align_spy_to_equity(
                timestamps, spy_series, anchor_value,
            )
            spy_status = "ok" if any(v is not None for v in spy_equity) else "unavailable"
        else:
            spy_status = "unavailable"

    points = [
        EquityPoint(
            timestamp=ts,
            equity=eq,
            profit_loss=pl,
            profit_loss_pct=plp,
            spy_equity=sp,
        )
        for ts, eq, pl, plp, sp in zip(
            timestamps, equities, pls, plps, spy_equity,
        )
    ]
    return PortfolioHistory(
        period=raw["period"],
        timeframe=raw["timeframe"],
        # base_value is the first funded equity now, NOT Alpaca's raw base.
        # The latter sits at a pre-funding date and would mis-position the
        # alpha-since-start indicator on the FE.
        base_value=anchor_value if equities else raw.get("base_value"),
        points=points,
        spy_status=spy_status,
    )


@router.get("/spy-snapshot", response_model=PaperVsSpySnapshot)
async def get_spy_snapshot() -> PaperVsSpySnapshot:
    """Returns the latest ``reports/paper_vs_spy.json`` snapshot. Refreshed
    by ``scripts/paper_vs_spy_snapshot.py`` (last step of the daily
    pipeline). 404 when the file doesn't exist yet."""
    if not PAPER_VS_SPY_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No paper_vs_spy.json — run "
                "`uv run python -m scripts.paper_vs_spy_snapshot` to create it."
            ),
        )
    try:
        data = json.loads(PAPER_VS_SPY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read {PAPER_VS_SPY_FILE.name}: {e}",
        )
    return PaperVsSpySnapshot(**data)


@router.get("/recommendations", response_model=PortfolioRecommendations)
async def get_recommendations() -> PortfolioRecommendations:
    """Per-position stop/target/status overlay sourced from the latest
    portfolio_analysis JSON + today's picks file. Lets the FE render the
    action/strategy columns on /portfolio without re-reading reports.

    Held positions outside the current basket get fallback ±8% / +10%
    bands so the table never has empty cells; ``source`` flags which.
    """
    client = _build_client()
    positions = await asyncio.to_thread(client.get_positions)

    analysis_path = _latest_portfolio_analysis()
    analysis_plans: dict[str, dict] = {}
    as_of: Optional[date] = None
    if analysis_path is not None:
        try:
            data = json.loads(analysis_path.read_text(encoding="utf-8"))
            analysis_plans = {p["ticker"]: p for p in data.get("picks", [])}
            if data.get("as_of"):
                try:
                    as_of = date.fromisoformat(data["as_of"])
                except ValueError:
                    as_of = None
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Bad analysis JSON %s: %s", analysis_path, e)

    # Pick basket membership comes from today's picks file. Use the freshest
    # file we have rather than today's UTC date so we never falsely flag
    # everything EXIT on a missed-pipeline day.
    picks_path = _latest_picks_path()
    basket: set[str] = set()
    if picks_path is not None:
        try:
            payload = json.loads(picks_path.read_text(encoding="utf-8"))
            basket = {
                (p.get("ticker") or "").upper()
                for p in payload.get("picks", [])
                if isinstance(p, dict)
            }
            basket.discard("")
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Bad picks JSON %s: %s", picks_path, e)

    recs: list[PositionRecommendation] = []
    n_at_risk = 0
    for pos in positions:
        ticker = (pos.get("ticker") or "").upper()
        if not ticker:
            continue
        current = float(pos.get("current_price") or 0.0)
        avg_entry = float(pos.get("avg_price") or 0.0)
        if current <= 0 or avg_entry <= 0:
            continue
        plan = analysis_plans.get(ticker)
        if plan and plan.get("stop_loss") and plan.get("target"):
            stop = float(plan["stop_loss"])
            target = float(plan["target"])
            source = "strategy"
            time_exit: Optional[date] = None
            if plan.get("time_exit_date"):
                try:
                    time_exit = date.fromisoformat(str(plan["time_exit_date"]))
                except ValueError:
                    time_exit = None
            expected = plan.get("expected_return_pct")
            try:
                expected_pct: Optional[float] = float(expected) if expected is not None else None
            except (TypeError, ValueError):
                expected_pct = None
        else:
            stop = avg_entry * (1 - _FALLBACK_STOP_PCT)
            target = avg_entry * (1 + _FALLBACK_TARGET_PCT)
            source = "fallback_8pct"
            time_exit = None
            expected_pct = None
        status = _classify_position(current, stop, target)
        if status != "HOLDING":
            n_at_risk += 1
        recs.append(PositionRecommendation(
            ticker=ticker,
            stop_loss=round(stop, 4),
            target=round(target, 4),
            time_exit_date=time_exit,
            expected_return_pct=expected_pct,
            source=source,
            in_todays_basket=ticker in basket,
            status=status,
        ))

    # Sort: at-risk first (worst-first), then by ticker.
    rank = {"STOP_HIT": 0, "NEAR_STOP": 1, "TARGET_HIT": 2, "NEAR_TARGET": 3, "HOLDING": 4}
    recs.sort(key=lambda r: (rank.get(r.status, 9), r.ticker))

    return PortfolioRecommendations(
        as_of=as_of,
        analysis_path=analysis_path.name if analysis_path else None,
        recommendations=recs,
        n_at_risk=n_at_risk,
    )
