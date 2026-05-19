"""Real cost-basis override for reporting.

The Alpaca paper account records its avg_entry_price as whatever it
actually paid at fill time. When the user has synced paper to mirror
real-life brokerage holdings (scripts/sync_real_holdings.py), the
paper's recorded cost basis is the market-open price on sync day, NOT
the user's real entry cost basis.

This module replaces avg_price with the user's real cost basis (from
``config/real_holdings.yaml``) and recomputes the derived P&L fields
when ``STOCKNEW_USE_REAL_COST_BASIS=1`` is set. Tickers not in the
holdings file pass through unchanged.

Design notes
------------
The override is applied at the broker boundary (``AlpacaClient.
get_positions``), so every downstream consumer (briefing endpoint,
portfolio API, CLI tables, position monitor) gets the corrected P&L
without explicit opt-in. The env-var gate keeps the previous behavior
the default — turn the override on deliberately by setting
STOCKNEW_USE_REAL_COST_BASIS=1 in .env.

The override CHANGES the apparent unrealized P&L. It does NOT touch
realized P&L, fills, or order history. If you're reading paper-broker
account equity straight from Alpaca, that number still reflects the
broker's view; the override is reporting-layer only.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import yaml

logger = logging.getLogger(__name__)


_ENV_FLAG = "STOCKNEW_USE_REAL_COST_BASIS"
_DEFAULT_PATH = Path("config/real_holdings.yaml")


def is_enabled() -> bool:
    """True iff the override should be applied."""
    return os.environ.get(_ENV_FLAG, "").strip() in ("1", "true", "TRUE", "yes")


@lru_cache(maxsize=4)
def load_real_cost_basis(path: str | None = None) -> dict[str, float]:
    """Return ``{ticker: real_avg_price}`` from the holdings YAML.

    Cached per-path. Returns an empty dict if the file is missing or
    malformed — callers can treat "no real basis available" the same as
    "override disabled" and pass through.

    ``path`` defaults to ``_DEFAULT_PATH``, looked up at CALL time
    (not capture time) so tests can monkey-patch the module-level
    constant.
    """
    p = Path(path) if path is not None else _DEFAULT_PATH
    if not p.exists():
        logger.debug("real_holdings file not found at %s; override no-op", p)
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as e:
        logger.warning("Failed to load %s for cost-basis override: %s", p, e)
        return {}
    out: dict[str, float] = {}
    for row in data.get("holdings", []) or []:
        ticker = row.get("ticker")
        avg = row.get("avg_price")
        if ticker and avg is not None:
            try:
                out[str(ticker).upper()] = float(avg)
            except (TypeError, ValueError):
                logger.warning(
                    "Skipping bad avg_price for %s in %s: %r",
                    ticker, p, avg,
                )
    return out


def apply_real_cost_basis(
    positions: Iterable[dict],
    *,
    real_basis: dict[str, float] | None = None,
) -> list[dict]:
    """Return positions with avg_price + unrealized_pnl(_pct) overridden.

    Only positions whose ticker has an entry in ``real_basis`` are
    modified; others are passed through unchanged (avg_price as Alpaca
    reported it).

    Each modified row gains a ``cost_basis_source`` field set to
    ``"real_holdings"``; rows passed through don't get this key, so
    downstream code can detect which positions had real-basis applied.

    Recomputed fields:
        avg_price            = real cost basis
        unrealized_pnl       = (current_price - real_avg) * shares
        unrealized_pnl_pct   = (current_price / real_avg - 1) * 100
                               (set to 0 if real_avg is 0 or current
                               price missing)
    """
    if real_basis is None:
        real_basis = load_real_cost_basis()
    if not real_basis:
        return list(positions)

    out: list[dict] = []
    for pos in positions:
        ticker = str(pos.get("ticker", "")).upper()
        real_avg = real_basis.get(ticker)
        if real_avg is None:
            out.append(pos)
            continue
        shares = float(pos.get("shares") or 0)
        current = pos.get("current_price")
        new = dict(pos)
        new["avg_price"] = real_avg
        new["cost_basis_source"] = "real_holdings"
        if current is not None and real_avg > 0:
            cur = float(current)
            new["unrealized_pnl"] = (cur - real_avg) * shares
            new["unrealized_pnl_pct"] = (cur / real_avg - 1.0) * 100.0
        else:
            new["unrealized_pnl"] = 0.0
            new["unrealized_pnl_pct"] = 0.0
        out.append(new)
    return out


def apply_if_enabled(positions: Iterable[dict]) -> list[dict]:
    """Apply the override when ``STOCKNEW_USE_REAL_COST_BASIS=1``,
    otherwise pass through unchanged. The thin wrapper used at the
    broker boundary so the default behavior is unchanged."""
    pos_list = list(positions)
    if not is_enabled():
        return pos_list
    return apply_real_cost_basis(pos_list)
