"""Pre-trade gates: drift, sanity, kill switch.

Three independent checks that must pass before any order reaches Alpaca.
Each gate either:
- proceeds silently (logged at INFO),
- proceeds with a warning (logged at WARNING; the caller continues),
- raises SystemExit with a human-readable explanation,

unless a corresponding ``--override-*`` flag is set on the caller args.

Extracted from ``scripts/paper_trade_factor_picks.py`` so the script's
orchestrator is decoupled from the gate plumbing. The argument is a duck-typed
``argparse.Namespace`` — anything with the right attribute names works.

Gates expected fields on ``args``:
- drift gate:        picks_date, picks_dir, override_drift
- sanity gate:       skip_sanity, sanity_mode, override_sanity_errors
- kill switch gate:  override_kill_switch
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run_drift_gate(args: Any) -> None:
    """Refuse to trade if today's picks composition has drifted from the
    trailing baseline (universe shrink, factor coverage collapse, sector
    cap break, top-z outlier, hysteresis carry rate anomaly).

    See ``reports/decision_logic_uplift_2026_05_18.md`` — the detector
    caught a real value-coverage drop on its first run.
    """
    from src.factors.drift_detector import (
        compute_drift_report, format_markdown,
    )
    today_str = (
        args.picks_date or datetime.now(timezone.utc).date().isoformat()
    )
    report = compute_drift_report(
        today_path=Path(args.picks_dir) / f"{today_str}.json",
        history_dir=Path(args.picks_dir),
        days=30,
    )
    if report.overall_status == "fail":
        logger.error(
            "Drift detector returned FAIL. Picks composition has shifted "
            "vs trailing baseline. Refusing to trade.",
        )
        for c in report.checks:
            if c.status == "fail":
                logger.error("  FAIL %s: %s", c.name, c.message)
        if not args.override_drift:
            print(format_markdown(report))
            raise SystemExit(
                "\nRefusing to trade -- drift detector failed. "
                "Investigate the FAILs above. To override (NOT "
                "recommended without manual verification), rerun with "
                "--override-drift."
            )
        logger.warning(
            "Proceeding despite drift FAIL because --override-drift was set."
        )
    elif report.overall_status == "warn":
        logger.warning("Drift detector returned WARN (proceeding):")
        for c in report.checks:
            if c.status == "warn":
                logger.warning("  WARN %s: %s", c.name, c.message)
    else:
        logger.info("Drift gate OK (%d checks)", len(report.checks))


def run_kill_switch_gate(args: Any, strategy_label: str) -> dict:
    """Refuse new entries when live α has dropped below the threshold.

    Always runs (also under --no-execute) so the report file stays fresh
    and the warm-up counter advances. Rolls over the strategy state file
    when ``strategy_label`` no longer matches what's recorded — a config
    change is detected the moment the new strategy first tries to trade
    and the rolling window restarts cleanly.

    Status semantics:

    - ``warming_up``: <60 trading days since strategy started; no gate yet
    - ``unavailable``: Alpaca or yfinance unreachable; gate inactive, log only
    - ``ok``: window full, α >= threshold
    - ``triggered``: window full, α < threshold; refuse unless overridden
    """
    from src.execution.kill_switch import evaluate, write_report

    payload = evaluate(strategy_label)
    write_report(payload)
    status = payload["status"]
    if status == "triggered":
        logger.error("KILL SWITCH TRIGGERED: %s", payload["message"])
        if not args.override_kill_switch:
            raise SystemExit(
                "\nRefusing to trade -- live α kill switch triggered. "
                "Inspect reports/kill_switch.json and decide whether the "
                "drawdown is recoverable. To override (e.g., the threshold "
                "fires on an isolated bad week), rerun with "
                "--override-kill-switch."
            )
        logger.warning(
            "Proceeding despite kill-switch trigger because "
            "--override-kill-switch was set."
        )
    elif status == "warming_up":
        logger.info("Kill switch: %s", payload["message"])
    elif status == "unavailable":
        logger.warning("Kill switch unavailable: %s", payload["message"])
    else:
        logger.info("Kill switch OK: %s", payload["message"])
    return payload


def _sanity_outcomes_to_dict(res) -> dict:
    """Flatten sanity-gate ``outcomes`` into the JSON shape we log."""
    return {t: {
        "verdict": o.verdict,
        "reason": o.reason,
        "confidence": o.check.confidence if o.check else None,
        "model": o.check.model_used if o.check else None,
        "mocked": o.check.mocked if o.check else None,
    } for t, o in res.outcomes.items()}


def _sanity_gate_errors(res) -> list[str]:
    """Tickers whose gate call FAILED (transport / API), distinct from
    LLM-verdict REJECTs. ``_gate_one`` tags those reasons with
    ``gate_error:``. Any such ticker is a hard stop unless overridden —
    masking call failures with mock fallback is what hid the 5-day
    silent gate failure after commit 411d288."""
    if res is None:
        return []
    return [
        t for t, o in res.outcomes.items()
        if (o.reason or "").startswith("gate_error:")
    ]


def run_sanity_gate(
    args: Any,
    longs: list[dict],
    shorts: list[dict],
    long_short_mode: bool,
) -> tuple[list[dict], list[dict], dict]:
    """Apply the asymmetric LLM sanity check. REJECT removes; CAUTION warns.
    SKIP (gate error) is treated as REJECT — 'when in doubt, don't trade'.

    Returns ``(filtered_longs, filtered_shorts, summary)``. Raises
    ``SystemExit`` on transport errors (without ``--override-sanity-errors``)
    or if every pick gets rejected.
    """
    if args.skip_sanity:
        logger.warning(
            "Sanity gate BYPASSED via --skip-sanity. Picks reach the "
            "broker unfiltered. NOT recommended for live trading."
        )
        return longs, shorts, {
            "applied": False, "kept": [], "rejected": [],
            "cautioned": [], "outcomes": {},
        }

    from src.research_agent.sanity_gate import gate_picks_sync, is_available

    if args.sanity_mode == "live" and not is_available():
        raise SystemExit(
            "--sanity-mode=live requires ANTHROPIC_API_KEY. "
            "Either set the key or rerun with --sanity-mode=mock."
        )
    logger.info(
        "Running sanity gate (mode=%s) on %d longs%s...",
        args.sanity_mode, len(longs),
        f" + {len(shorts)} shorts" if long_short_mode else "",
    )
    long_result = gate_picks_sync(picks=longs, mode=args.sanity_mode, action="BUY")
    short_result = (
        gate_picks_sync(picks=shorts, mode=args.sanity_mode, action="SHORT")
        if long_short_mode and shorts
        else None
    )

    summary: dict = {
        "applied": True,
        "mode": args.sanity_mode,
        "long_kept": long_result.kept,
        "long_rejected": long_result.rejected,
        "long_cautioned": long_result.cautioned,
        "long_outcomes": _sanity_outcomes_to_dict(long_result),
        "short_kept": short_result.kept if short_result else [],
        "short_rejected": short_result.rejected if short_result else [],
        "short_cautioned": short_result.cautioned if short_result else [],
        "short_outcomes": (
            _sanity_outcomes_to_dict(short_result) if short_result else {}
        ),
    }
    if long_result.rejected:
        logger.warning(
            "Sanity gate REJECTED %d longs: %s",
            len(long_result.rejected), ", ".join(long_result.rejected),
        )
    if short_result and short_result.rejected:
        logger.warning(
            "Sanity gate REJECTED %d shorts: %s",
            len(short_result.rejected), ", ".join(short_result.rejected),
        )

    gate_errors = (
        _sanity_gate_errors(long_result) + _sanity_gate_errors(short_result)
    )
    if gate_errors:
        logger.error(
            "Sanity gate had %d API/transport ERRORS (not LLM verdicts): %s",
            len(gate_errors), ", ".join(sorted(set(gate_errors))),
        )
        outcomes_long = long_result.outcomes if long_result else {}
        outcomes_short = short_result.outcomes if short_result else {}
        for t in sorted(set(gate_errors)):
            o = outcomes_long.get(t) or outcomes_short.get(t)
            if o:
                logger.error("  %s: %s", t, o.reason)
        if not args.override_sanity_errors:
            raise SystemExit(
                "\nRefusing to trade -- sanity gate had transport errors "
                "on the calls above. The previous behaviour (silently "
                "fall back to mock) hid a five-day broken gate. Diagnose "
                "the underlying call failure, or rerun with "
                "--override-sanity-errors (NOT recommended)."
            )
        logger.warning(
            "Proceeding despite %d sanity-gate errors because "
            "--override-sanity-errors was set.",
            len(gate_errors),
        )

    kept_longs = set(long_result.kept)
    kept_shorts = set(short_result.kept) if short_result else set()
    longs = [p for p in longs if p["ticker"] in kept_longs]
    shorts = [p for p in shorts if p["ticker"] in kept_shorts]

    if not longs and not shorts:
        raise SystemExit(
            "Sanity gate rejected every pick. Nothing to trade. "
            "Investigate the verdicts above; rerun with --skip-sanity "
            "only if you have a reason to override (you should not)."
        )
    return longs, shorts, summary
