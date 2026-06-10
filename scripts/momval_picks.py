"""Momentum-Value "biggest-risers" book — daily picks, enriched.

Momentum-tilted composite (weights from config/strategies.yaml::momval_book)
over the live PIT S&P 500, quality + PEAD dropped. For each pick this gathers
the EDGAR fundamentals + trailing return that justify it, and an AI "why to buy"
GROUNDED in those numbers — so the book is not a black box you act on blindly.

    uv run python -m scripts.momval_picks                 # today's picks + why
    uv run python -m scripts.momval_picks --no-ai         # skip the LLM rationale
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger("momval_picks")

OUTPUT = Path("reports") / "momval_picks_latest.json"

# EDGAR fundamental fields surfaced per pick (price-derived ratios like P/E are
# NOT in the EDGAR panel — they need a live price — so they're intentionally
# absent; we show what the filings actually carry).
_FUND_FIELDS = (
    "name", "sector", "revenue_growth_yoy", "earnings_growth_yoy",
    "profit_margin", "operating_margin", "debt_to_equity",
    "dividend_yield", "free_cash_flow",
)


def _cfg() -> dict:
    """momval_book config (weights, top_n, sector cap, model, risk note)."""
    from src.config_loader import Config  # loads .env + the yamls
    return Config().strategies.get("momval_book", {})


def _coerce(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _trailing_returns(tickers: list[str], as_of: pd.Timestamp) -> dict[str, float]:
    """12-1 momentum return (close[~21d ago]/close[~252d ago]-1) per ticker."""
    from scripts.research.trend_forward_paper import _close_at_offset, _polygon_daily
    start = (as_of - pd.Timedelta(days=420)).date().isoformat()
    prices = _polygon_daily(tickers, start, as_of.date().isoformat())
    out: dict[str, float] = {}
    for t in tickers:
        df = prices.get(t)
        if df is None or df.empty:
            continue
        num = _close_at_offset(df, as_of, 21)
        den = _close_at_offset(df, as_of, 252)
        if num and den and den > 0:
            out[t] = num / den - 1.0
    return out


def _fundamentals(tickers: list[str], as_of: pd.Timestamp) -> dict[str, dict]:
    from src.factors.pipeline import _load_fundamentals_sync
    loader = _load_fundamentals_sync(tickers)
    out: dict[str, dict] = {}
    for t in tickers:
        snap = loader.lookup(t, as_of)
        out[t] = {} if snap is None else {
            f: (getattr(snap, f) if f in ("name", "sector") else _coerce(getattr(snap, f, None)))
            for f in _FUND_FIELDS
        }
    return out


def _fmt_pct(v):
    return f"{v*100:+.0f}%" if isinstance(v, (int, float)) else "—"


def _analyst_recs(tickers: list[str]) -> dict[str, dict]:
    """yfinance analyst consensus per ticker — ADVISORY CONTEXT ONLY.

    Never a factor input: analyst recs have no point-in-time history (so the
    backtest can't grade them) and a documented herding problem. This is the
    same consensus data the TradingView widgets display, from a source we can
    actually read (TradingView's widgets are sealed iframes, no public API)."""
    from concurrent.futures import ThreadPoolExecutor

    import yfinance as yf

    def one(t: str) -> tuple[str, dict | None]:
        try:
            tk = yf.Ticker(t)
            out: dict = {}
            rs = tk.recommendations_summary
            if rs is not None and not rs.empty and "period" in rs.columns:
                cur = rs[rs["period"] == "0m"]
                if not cur.empty:
                    r = cur.iloc[0]
                    buy = int(r.get("strongBuy", 0)) + int(r.get("buy", 0))
                    hold = int(r.get("hold", 0))
                    sell = int(r.get("sell", 0)) + int(r.get("strongSell", 0))
                    if buy + hold + sell > 0:
                        out.update({"analyst_buy": buy, "analyst_hold": hold,
                                    "analyst_sell": sell})
            tgt = tk.analyst_price_targets or {}
            mean, cur_px = _coerce(tgt.get("mean")), _coerce(tgt.get("current"))
            if mean and cur_px and cur_px > 0:
                out["analyst_target_upside_pct"] = round(mean / cur_px - 1.0, 4)
            return t, (out or None)
        except Exception:  # noqa: BLE001 — yfinance is flaky; context is optional
            return t, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        return {t: d for t, d in ex.map(one, tickers) if d}


def _deploy_watch(guard: dict | None, n_picks: int, cfg: dict) -> dict | None:
    """Deploy-on-guard-clear plan: when the dispersion guard clears (regime
    where the selection edge was historically present), the plan is notional
    split equally across today's top-N. Fires a one-time alert on the
    caution->clear transition (previous state read from yesterday's JSON)."""
    dw = cfg.get("deploy_watch") or {}
    notional = float(dw.get("notional", 0) or 0)
    if guard is None or notional <= 0 or n_picks == 0:
        return None
    prev_caution = None
    if OUTPUT.exists():
        try:
            prev = json.loads(OUTPUT.read_text(encoding="utf-8"))
            prev_caution = (prev.get("dispersion_guard") or {}).get("caution")
        except Exception:  # noqa: BLE001
            pass
    clear = not guard["caution"]
    just_cleared = clear and prev_caution is True
    per_name = round(notional / n_picks, 2)
    plan = {
        "notional_usd": notional,
        "clear": clear,
        "just_cleared": just_cleared,
        "per_name_usd": per_name,
        "note": (
            f"DEPLOY WINDOW OPEN — dispersion guard clear (percentile "
            f"{guard['percentile_2018_2026']:.0%} < {guard['abstain_quantile']:.0%}): "
            f"plan = ${notional:,.0f} equal-weight across today's top-{n_picks} "
            f"(${per_name:,.2f}/name). Judge at 3-6 months."
            if clear else
            f"Deploy watch armed: waiting for momentum dispersion to drop below "
            f"the {guard['abstain_quantile']:.0%} reference percentile "
            f"(currently {guard['percentile_2018_2026']:.0%})."
        ),
    }
    if just_cleared:
        logger.warning("DEPLOY WATCH: %s", plan["note"])
        try:
            from src.alerts.telegram_bot import TelegramAlerter
            from src.config_loader import Config
            TelegramAlerter(Config())._send_message(
                f"MOMVAL deploy window OPEN: {plan['note']}")
        except Exception as e:  # noqa: BLE001 — alerting is best-effort
            logger.info("telegram alert skipped (%s)", e)
    return plan


def _dispersion_guard(composite: pd.DataFrame, cfg: dict) -> dict | None:
    """Momentum-dispersion abstention flag (calibration_abstention study).

    Live IQR of 12-1 momentum raw over the full cross-section, percentiled
    against the frozen 2018-2026 reference. Above ``abstain_quantile`` the
    selection edge was historically absent. Advisory, not a hard gate."""
    g = cfg.get("dispersion_guard") or {}
    ref_path = Path(g.get("reference_file", "reports/momval_dispersion_reference.json"))
    if "mom_raw" not in composite.columns or not ref_path.exists():
        return None
    raw = composite["mom_raw"].dropna()
    if len(raw) < 50:
        return None
    iqr = float(raw.quantile(0.75) - raw.quantile(0.25))
    ref = json.loads(ref_path.read_text(encoding="utf-8"))
    vals = sorted(r["mom_disp"] for r in ref["values"])
    pctile = sum(1 for v in vals if v <= iqr) / len(vals)
    abstain_q = float(g.get("abstain_quantile", 0.75))
    caution = pctile >= abstain_q
    return {
        "mom_dispersion_iqr": round(iqr, 4),
        "percentile_2018_2026": round(pctile, 3),
        "abstain_quantile": abstain_q,
        "caution": caution,
        "note": (
            "HIGH momentum dispersion — in the worst quartile of 2018-2026; the "
            "composite's biggest-risers edge was historically ABSENT in this regime "
            "(walk-forward: skipped dates sel -0.1%/3mo vs traded +3.4%). Treat "
            "today's ranking as low-confidence."
            if caution else
            "Momentum dispersion normal — regime in which the selection edge "
            "was historically present."
        ),
    }


def _ai_rationales(picks: list[dict], model: str) -> dict[str, str]:
    """One grounded Claude call -> {ticker: 'why to buy'}. Uses ONLY the supplied
    factor + fundamental numbers; instructed not to speculate."""
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY not set — skipping AI rationale.")
        return {}
    def _an(p: dict) -> str:
        if p.get("analyst_buy") is None:
            return ""
        s = (f" Analyst consensus (context only): {p['analyst_buy']}B/"
             f"{p['analyst_hold']}H/{p['analyst_sell']}S")
        if p.get("analyst_target_upside_pct") is not None:
            s += f", mean target {_fmt_pct(p['analyst_target_upside_pct'])} vs price"
        return s + "."

    lines = [
        f"{p['ticker']} ({p.get('name') or p['ticker']}, {p.get('sector') or '?'}): "
        f"composite z {p['composite_z']:+.2f}; momentum rank {p['mom_rank']}/{p['universe_size']} "
        f"(12-1 return {_fmt_pct(p.get('trailing_12_1'))}); value rank {p['val_rank']}; "
        f"rev growth {_fmt_pct(p.get('revenue_growth_yoy'))}, EPS growth {_fmt_pct(p.get('earnings_growth_yoy'))}, "
        f"profit margin {_fmt_pct(p.get('profit_margin'))}, debt/equity {p.get('debt_to_equity')}, "
        f"div yield {_fmt_pct(p.get('dividend_yield'))}." + _an(p)
        for p in picks
    ]
    system = (
        "You write a one-sentence, factual 'why this ranks' note for each stock in a "
        "MOMENTUM-VALUE quant book (it targets the biggest risers over 3-6 months and runs "
        "deeper drawdowns than a balanced book). Use ONLY the numbers provided — never invent "
        "fundamentals, news, or price targets, and never give buy/sell advice. State which leg "
        "drives the rank (momentum, value, or both) and flag any caveat visible IN THE NUMBERS "
        "(e.g. high debt, negative margin, weak value rank so it's momentum-only). Analyst "
        "consensus, when shown, is CONTEXT, not part of the quant rank — mention it only when "
        "it clearly disagrees with the factor view (e.g. sell-heavy consensus on a top rank). "
        "<=30 words each. Return ONLY a JSON object {ticker: sentence}."
    )

    async def _go():
        from src.research_agent.llm_client import AnthropicClient
        resp = await AnthropicClient().create(
            model=model, system=system, tools=[],
            messages=[{"role": "user", "content": "Stocks:\n" + "\n".join(lines)}],
            max_tokens=2048,
        )
        # content is a list of {type, text} blocks; join the text ones.
        return "".join(b.get("text", "") for b in resp.content if b.get("type") == "text")

    try:
        raw = asyncio.run(_go())
    except Exception as e:  # noqa: BLE001
        logger.warning("AI rationale call failed (%s) — continuing without it.", e)
        return {}
    blob = raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        return {k.upper(): v for k, v in json.loads(blob).items()}
    except Exception as e:  # noqa: BLE001
        logger.warning("AI rationale parse failed (%s); raw head: %r", e, raw[:200])
        return {}


def build(as_of: pd.Timestamp, use_ai: bool, model_override: str | None) -> dict:
    from src.factors.pipeline import run_factor_picks
    cfg = _cfg()
    weights = cfg.get("weights", {"momentum": 0.6, "value": 0.4})
    top_n = int(cfg.get("top_n", 24))
    max_sector_pct = cfg.get("max_sector_pct", 30.0)
    model = model_override or cfg.get("ai_model", "claude-sonnet-4-6")

    res = run_factor_picks(
        as_of=as_of, top_n=top_n,
        composite_factors="mv", factor_weights=weights,
        include_pead=False, sector_neutral_quality=False,
        min_overlap=1, max_sector_pct=max_sector_pct,
        min_history_days=int(cfg.get("min_history_days", 504)),
    )
    tickers = res.top_n["ticker"].tolist()
    funds = _fundamentals(tickers, as_of)
    rets = _trailing_returns(tickers, as_of)
    analysts = _analyst_recs(tickers) if cfg.get("analyst_context", True) else {}

    picks = []
    for _, r in res.top_n.iterrows():
        t = str(r.get("ticker"))
        f = funds.get(t, {})
        picks.append({
            "rank": int(r.get("rank")) if pd.notna(r.get("rank")) else None,
            "ticker": t, "name": f.get("name"),
            "composite_z": _coerce(r.get("z_score")),
            "mom_rank": int(r["mom_rank"]) if pd.notna(r.get("mom_rank")) else None,
            "val_rank": int(r["val_rank"]) if pd.notna(r.get("val_rank")) else None,
            "sector": f.get("sector") or (r.get("sector") if "sector" in res.top_n.columns else None),
            "trailing_12_1": _coerce(rets.get(t)),
            "universe_size": res.universe_size,
            **{k: f.get(k) for k in _FUND_FIELDS if k not in ("name", "sector")},
            **(analysts.get(t) or {}),
        })

    if use_ai:
        why = _ai_rationales(picks, model)
        for p in picks:
            p["why"] = why.get(p["ticker"].upper())

    guard = _dispersion_guard(res.composite, cfg)
    if guard and guard["caution"]:
        logger.warning("DISPERSION GUARD: %s", guard["note"])
    deploy = _deploy_watch(guard, len(picks), cfg)

    return {
        "strategy": "momval_6_4", "label": "Momentum-Value (biggest-risers)",
        "as_of": as_of.date().isoformat(), "weights": weights,
        "factors_used": res.factors_used, "universe_size": res.universe_size,
        "top_n": len(picks),
        "horizon_note": cfg.get("risk_note", "").strip(),
        "ai_model": model if use_ai else None,
        "dispersion_guard": guard,
        "deploy_watch": deploy,
        "picks": picks,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--no-ai", action="store_true", help="skip the LLM why-to-buy")
    ap.add_argument("--model", default=None, help="override momval_book.ai_model")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    as_of = pd.Timestamp(args.as_of) if args.as_of else \
        pd.Timestamp(datetime.now(timezone.utc).date())
    payload = build(as_of, not args.no_ai, args.model)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    logger.info("MOMVAL picks for %s (%d names):", payload["as_of"], payload["top_n"])
    for p in payload["picks"][:8]:
        logger.info("  #%-2s %-6s z=%+.2f  why: %s", p["rank"], p["ticker"],
                    p["composite_z"] or 0.0, (p.get("why") or "—")[:90])
    logger.info("wrote %s", OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
