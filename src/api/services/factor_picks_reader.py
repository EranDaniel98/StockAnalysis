"""Read factor picks from disk and translate to BuySignal shape.

The factor strategy (``composite_d05_r63``) writes to
``data/daily_picks/YYYY-MM-DD.json`` (not the ``scan_runs`` DB table the
CLI scan command uses). The /api/scans/latest-buys endpoint reads from
scan_runs only, so the web UI was showing the OLD composite path while
the paper trader executed the NEW factor path — two separate
recommendation sources.

This reader closes that gap. It loads the most recent picks JSON, maps
the per-factor ranks to a BuySignal-shaped envelope, and lets the API
expose factor picks under the same response_model as the composite path.

Two design choices worth knowing:

1. ``z_score`` → ``composite_score`` mapping uses a clamp + linear
   rescale. Z usually lives in [-2.5, +3.0]; mapping to [40, 95]
   keeps the FE's existing color thresholds readable without
   misrepresenting the underlying signal.
2. Per-factor ranks → sub_scores divides by universe_size so the
   FE's existing percentile filters (``fundamental >= 60`` etc.)
   still make sense — a rank-1 momentum name becomes sub_scores
   {"momentum": 99.7} on a 500-ticker universe.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.api.schemas.scan import BuySignal
from src.factors.strategy_id import strategy_name

logger = logging.getLogger(__name__)


def _z_to_composite(z: float) -> float:
    """Clamp z to [-2.5, 3.0] and linearly rescale to [40, 95].

    The factor strategy uses raw z-scores; the FE was built around
    0-100 composite_score with color thresholds at 65 / 80. Mapping
    keeps the existing UI legible without changing it. Out-of-range
    z values clip rather than extrapolate so a single outlier doesn't
    blow past the 95-point cap.
    """
    z = max(-2.5, min(3.0, z))
    return 40.0 + (z + 2.5) / 5.5 * 55.0


def _rank_to_sub_score(rank: Optional[float], universe_size: int) -> Optional[float]:
    """Convert a 1-based rank to a 0-100 percentile sub-score.

    Rank 1 in a universe of N becomes percentile ~ 100 * (N-1)/(N-1) = 100.
    Rank N becomes 0. NaN/missing ranks return None so the FE can
    distinguish "factor didn't cover this ticker" from "factor said zero".
    """
    if rank is None or universe_size <= 1:
        return None
    try:
        r = float(rank)
    except (TypeError, ValueError):
        return None
    if r != r:  # NaN
        return None
    pct = (universe_size - r) / max(1.0, universe_size - 1) * 100.0
    return round(max(0.0, min(100.0, pct)), 1)


def _action_for(z: float, top_quartile_z: float) -> str:
    """Top quartile of the picks gets STRONG BUY, the rest BUY.

    Anchored on z rather than fixed thresholds so the action labels
    track the relative ordering of TODAY'S picks, not historical norms.
    """
    return "STRONG BUY" if z >= top_quartile_z else "BUY"


def find_latest_picks_file(picks_dir: Path | str) -> Optional[Path]:
    """Return the lexicographically-greatest YYYY-MM-DD.json file, or None.

    Lex order = date order for ISO dates. Skips JSONs that don't match
    the date stem pattern (e.g. an execution_log/ subdirectory)."""
    path = Path(picks_dir)
    if not path.is_dir():
        return None
    candidates = []
    for p in path.glob("*.json"):
        stem = p.stem
        if len(stem) != 10 or stem[4] != "-" or stem[7] != "-":
            continue
        candidates.append(p)
    if not candidates:
        return None
    return sorted(candidates)[-1]


def load_latest_factor_picks(
    picks_dir: Path | str = "data/daily_picks",
) -> list[BuySignal]:
    """Read the most-recent picks JSON and return BuySignal rows.

    Returns an empty list when no picks file exists (system not yet
    bootstrapped) or when the file is malformed (loud log; doesn't
    raise — the API endpoint falls back to the DB path then). Callers
    that need to know whether picks were present vs empty should check
    the return list length AND the log.
    """
    latest = find_latest_picks_file(picks_dir)
    if latest is None:
        logger.info("No factor picks JSON found under %s", picks_dir)
        return []
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to parse factor picks at %s: %s", latest, exc)
        return []

    picks = payload.get("picks") or []
    if not picks:
        return []

    strategy = payload.get("strategy") or strategy_name()
    as_of_str = payload.get("as_of", "")
    universe_size = int(payload.get("universe_size") or len(picks))
    run_id = f"factor:{strategy}:{as_of_str}"
    try:
        scan_ts = datetime.fromisoformat(
            payload.get("generated_at_utc")
            or datetime.now(timezone.utc).isoformat()
        )
    except (TypeError, ValueError):
        scan_ts = datetime.now(timezone.utc)
    if scan_ts.tzinfo is None:
        scan_ts = scan_ts.replace(tzinfo=timezone.utc)

    z_scores = [float(p.get("z_score") or 0.0) for p in picks]
    if z_scores:
        z_sorted = sorted(z_scores, reverse=True)
        top_quartile_z = z_sorted[max(0, len(z_sorted) // 4 - 1)]
    else:
        top_quartile_z = float("inf")

    out: list[BuySignal] = []
    for p in picks:
        ticker = p.get("ticker")
        if not ticker:
            continue
        z = float(p.get("z_score") or 0.0)
        composite = _z_to_composite(z)
        action = _action_for(z, top_quartile_z)

        sub_scores: dict[str, float] = {}
        for key, src in (
            ("momentum", "mom_rank"),
            ("quality", "qual_rank"),
            ("value", "val_rank"),
            ("pead", "pead_rank"),
        ):
            score = _rank_to_sub_score(p.get(src), universe_size)
            if score is not None:
                sub_scores[key] = score

        out.append(BuySignal(
            ticker=ticker,
            name=p.get("name") or "",
            sector=p.get("sector") or "Unknown",
            industry=p.get("industry") or "Unknown",
            market_cap=p.get("market_cap"),
            action=action,
            composite_score=round(composite, 1),
            confidence=f"z={z:+.2f} rank={int(p.get('rank') or 0)}",
            strategy=strategy,
            scan_timestamp=scan_ts,
            run_id=run_id,
            consensus_count=1,
            consensus_strategies=[strategy],
            sub_scores=sub_scores,
            earnings_announcement_ts=p.get("earnings_announcement_ts"),
            earnings_call_ts=p.get("earnings_call_ts"),
            sanity_check=None,
        ))
    out.sort(key=lambda b: (-b.composite_score, b.ticker))
    return out


__all__ = ["load_latest_factor_picks", "find_latest_picks_file"]
