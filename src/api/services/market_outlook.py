"""Market-outlook computation -- a conditions read, not a forecast.

Tallies four objective signals (SPY trend vs 200-SMA, VIX level, news
sentiment tilt, SPY after-hours drift) into a crude risk-on/neutral/risk-off
lean, and surfaces the pre/post-market moves behind it. The lean is a
transparent +1/0/-1 sum -- no model, no prediction. Deliberately blunt so
the user makes the call.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from src.api.schemas.market import (
    MarketOutlook,
    MarketRegime,
    OutlookSignal,
    PrePostMove,
)
from src.market_data.polygon import PolygonClient, bars_to_frame

logger = logging.getLogger(__name__)

# Index/sector ETFs whose extended-hours moves stand in for "the market".
INDEX_PROXIES = ["SPY", "QQQ", "DIA", "IWM"]

_CAVEAT = (
    "Conditions read, not a forecast. This is a blunt tally of objective "
    "signals (trend, VIX, news tilt, after-hours drift) — markets are not "
    "predictable from these. Use it as context, not a trade trigger."
)


def _latest_session(client: PolygonClient) -> tuple[str, dict[str, float]]:
    """(latest_session_date, {ticker: prior_regular_close}) from daily bars.
    SPY's last bar dates the session; prior close is the second-to-last bar."""
    end = pd.Timestamp.utcnow().tz_localize(None).normalize()
    start = (end - pd.Timedelta(days=14)).date().isoformat()
    spy = bars_to_frame(client.aggregates("SPY", start, end.date().isoformat(),
                                          timespan="day", multiplier=1, adjusted=True),
                        daily=True)
    if spy is None or spy.empty:
        return "", {}
    return spy.index[-1].date().isoformat(), {}


def fetch_prepost(tickers: list[str]) -> tuple[str, list[PrePostMove]]:
    """Latest-session pre/after-hours moves for ``tickers``. premarket_pct is
    vs the prior regular close; afterhours_pct is vs that session's close."""
    client = PolygonClient()
    session_date, _ = _latest_session(client)
    if not session_date:
        return "", []

    end = pd.Timestamp(session_date)
    start = (end - pd.Timedelta(days=14)).date().isoformat()

    def _one(t: str) -> PrePostMove | None:
        df = bars_to_frame(client.aggregates(t, start, session_date, timespan="day",
                                             multiplier=1, adjusted=True), daily=True)
        if df is None or df.empty:
            return None
        last_close = float(df["Close"].iloc[-1])
        prev_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else None
        oc = client.open_close(t, session_date)
        pre = oc.get("preMarket")
        after = oc.get("afterHours")
        pre_pct = ((float(pre) / prev_close - 1.0) * 100.0
                   if pre and prev_close else None)
        after_pct = ((float(after) / last_close - 1.0) * 100.0
                     if after and last_close else None)
        return PrePostMove(
            ticker=t, session_date=session_date,
            last_close=round(last_close, 2),
            premarket_pct=round(pre_pct, 2) if pre_pct is not None else None,
            afterhours_pct=round(after_pct, 2) if after_pct is not None else None,
        )

    out: list[PrePostMove] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for mv in ex.map(_one, tickers):
            if mv is not None:
                out.append(mv)
    return session_date, out


def _trend_signal(regime: MarketRegime) -> OutlookSignal:
    if regime.spy_above_sma200 is None:
        return OutlookSignal(name="Trend", detail="SPY vs 200-SMA unavailable", tilt="neutral")
    pct = regime.spy_pct_from_sma200
    detail = f"SPY {pct:+.1f}% vs 200-SMA" if pct is not None else "SPY vs 200-SMA"
    return OutlookSignal(
        name="Trend", detail=detail,
        tilt="bullish" if regime.spy_above_sma200 else "bearish",
    )


def _vix_signal(regime: MarketRegime) -> OutlookSignal:
    vix = regime.vix_level
    if vix is None:
        return OutlookSignal(name="VIX", detail="VIX unavailable", tilt="neutral")
    tilt = "bullish" if vix < 20 else "bearish" if vix > 25 else "neutral"
    return OutlookSignal(name="VIX", detail=f"VIX {vix:.1f}", tilt=tilt)


def _news_signal(counts: dict[str, int]) -> OutlookSignal:
    pos, neg = counts.get("positive", 0), counts.get("negative", 0)
    net = pos - neg
    tilt = "bullish" if net >= 5 else "bearish" if net <= -5 else "neutral"
    return OutlookSignal(
        name="News sentiment", detail=f"{pos}↑ / {neg}↓ across feed (net {net:+d})",
        tilt=tilt,
    )


def _afterhours_signal(prepost: list[PrePostMove]) -> OutlookSignal:
    spy = next((m for m in prepost if m.ticker == "SPY"), None)
    if not spy or spy.afterhours_pct is None:
        return OutlookSignal(name="After-hours", detail="SPY after-hours unavailable", tilt="neutral")
    ah = spy.afterhours_pct
    tilt = "bullish" if ah > 0.2 else "bearish" if ah < -0.2 else "neutral"
    return OutlookSignal(name="After-hours", detail=f"SPY after-hours {ah:+.2f}%", tilt=tilt)


_TILT_SCORE = {"bullish": 1, "neutral": 0, "bearish": -1}


def build_outlook(
    regime: MarketRegime,
    news_counts: dict[str, int],
    session_date: str,
    prepost: list[PrePostMove],
) -> MarketOutlook:
    signals = [
        _trend_signal(regime),
        _vix_signal(regime),
        _news_signal(news_counts),
        _afterhours_signal(prepost),
    ]
    score = sum(_TILT_SCORE[s.tilt] for s in signals)
    n_bull = sum(1 for s in signals if s.tilt == "bullish")
    n_bear = sum(1 for s in signals if s.tilt == "bearish")
    # Require a clear ±2 majority to call a side; otherwise neutral.
    lean = "risk_on" if score >= 2 else "risk_off" if score <= -2 else "neutral"
    return MarketOutlook(
        as_of=regime.as_of,
        session_date=session_date or regime.as_of.date().isoformat(),
        lean=lean,
        lean_score=score,
        n_bullish=n_bull,
        n_bearish=n_bear,
        signals=signals,
        prepost=prepost,
        news_sentiment=news_counts,
        caveat=_CAVEAT,
    )
