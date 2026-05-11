"""
Portfolio tracker.
Loads holdings from config, calculates P&L, and generates
position-level recommendations integrated with the analysis engine.
"""

import yaml
import logging
from pathlib import Path
from datetime import datetime, date

logger = logging.getLogger(__name__)


class Portfolio:
    def __init__(self, config):
        self.config = config
        self.portfolio_config = self._load_portfolio()
        self.holdings = self.portfolio_config.get("holdings", [])
        self.cash_available = self.portfolio_config.get("total_cash_available", 0)
        self.thresholds = self.portfolio_config.get("action_thresholds", {})

    def _load_portfolio(self):
        path = self.config.config_dir / "portfolio.yaml"
        if not path.exists():
            logger.warning(f"Portfolio file not found: {path}")
            return {"holdings": [], "total_cash_available": 0}
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data or {"holdings": [], "total_cash_available": 0}

    def get_tickers(self):
        """Get list of tickers in the portfolio."""
        return [h["ticker"] for h in self.holdings if h.get("ticker")]

    def get_holding(self, ticker):
        """Get holding details for a specific ticker."""
        for h in self.holdings:
            if h.get("ticker", "").upper() == ticker.upper():
                return h
        return None

    def calculate_positions(self, current_prices):
        """
        Calculate full P&L for all holdings.

        Args:
            current_prices: dict of {ticker: current_price}

        Returns:
            dict with positions list, totals, and sector breakdown
        """
        positions = []
        total_cost = 0
        total_market_value = 0

        for holding in self.holdings:
            ticker = holding.get("ticker", "").upper()
            shares = holding.get("shares", 0)
            avg_price = holding.get("avg_price", 0)
            date_acquired = holding.get("date_acquired")
            notes = holding.get("notes", "")

            if not ticker or shares <= 0 or avg_price <= 0:
                continue

            current_price = current_prices.get(ticker)
            if current_price is None:
                logger.warning(f"No current price for {ticker}, skipping")
                continue

            cost_basis = shares * avg_price
            market_value = shares * current_price
            unrealized_pnl = market_value - cost_basis
            pnl_pct = (current_price / avg_price - 1) * 100

            # Calculate hold duration
            hold_days = None
            if date_acquired:
                try:
                    acquired = datetime.strptime(str(date_acquired), "%Y-%m-%d").date()
                    hold_days = (date.today() - acquired).days
                except (ValueError, TypeError):
                    pass

            total_cost += cost_basis
            total_market_value += market_value

            positions.append({
                "ticker": ticker,
                "shares": shares,
                "avg_price": avg_price,
                "current_price": round(current_price, 2),
                "cost_basis": round(cost_basis, 2),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "hold_days": hold_days,
                "notes": notes,
                "date_acquired": str(date_acquired) if date_acquired else None,
            })

        # Calculate weights
        total_portfolio = total_market_value + self.cash_available
        for pos in positions:
            pos["weight_pct"] = round(
                pos["market_value"] / total_portfolio * 100, 2
            ) if total_portfolio > 0 else 0

        total_pnl = total_market_value - total_cost
        total_pnl_pct = (total_market_value / total_cost - 1) * 100 if total_cost > 0 else 0

        return {
            "positions": positions,
            "total_cost": round(total_cost, 2),
            "total_market_value": round(total_market_value, 2),
            "total_unrealized_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "cash_available": self.cash_available,
            "total_portfolio_value": round(total_portfolio, 2),
            "cash_pct": round(
                self.cash_available / total_portfolio * 100, 2
            ) if total_portfolio > 0 else 100,
            "num_positions": len(positions),
        }

    def recommend_actions(self, positions_data, recommendations_map):
        """
        Generate action recommendations for each existing holding.

        Args:
            positions_data: output from calculate_positions()
            recommendations_map: dict of {ticker: recommendation_dict} from the analysis

        Returns:
            list of position dicts enriched with action, reasoning
        """
        add_score = self.thresholds.get("add_score", 65)
        hold_min = self.thresholds.get("hold_min_score", 40)
        trim_score = self.thresholds.get("trim_score", 35)
        overweight = self.thresholds.get("overweight_pct", 15)
        underweight = self.thresholds.get("underweight_pct", 3)

        enriched = []

        for pos in positions_data["positions"]:
            ticker = pos["ticker"]
            rec = recommendations_map.get(ticker, {})
            score = rec.get("composite_score", 50)
            scan_action = rec.get("action", "N/A")
            weight = pos["weight_pct"]
            pnl_pct = pos["pnl_pct"]
            signals = rec.get("all_signals", [])

            # Determine position action
            action, reasons = self._decide_position_action(
                score, scan_action, weight, pnl_pct, pos,
                add_score, hold_min, trim_score, overweight, underweight
            )

            # Get risk levels from recommendation
            risk = rec.get("risk_management", {})
            sl = risk.get("stop_loss", {})
            tp = risk.get("take_profit", {})

            # Build concrete action details
            action_details = self._build_action_details(
                action, pos, rec, risk,
                positions_data["total_portfolio_value"],
                overweight,
            )

            enriched.append({
                **pos,
                "analysis_score": round(score, 1),
                "scan_action": scan_action,
                "position_action": action,
                "reasons": reasons,
                "sub_scores": rec.get("sub_scores", {}),
                "stop_loss": sl.get("price"),
                "take_profit": tp.get("price"),
                "key_signals": [
                    s for s in signals[:6]
                ],
                **action_details,
            })

        return enriched

    def _decide_position_action(
        self, score, scan_action, weight, pnl_pct, pos,
        add_score, hold_min, trim_score, overweight, underweight
    ):
        """Decide what to do with an existing position."""
        reasons = []

        # SELL: very low score or STRONG SELL from scanner
        if score < trim_score or scan_action == "STRONG SELL":
            reasons.append(f"Low score ({score:.0f}) — fundamentals/technicals deteriorating")
            if pnl_pct > 0:
                reasons.append(f"Lock in +{pnl_pct:.1f}% gains before further decline")
            elif pnl_pct < -15:
                reasons.append(f"Cut losses at {pnl_pct:.1f}% — avoid deeper drawdown")
            return "SELL", reasons

        # TRIM: low-ish score AND overweight
        if score < hold_min and weight > overweight:
            reasons.append(f"Score below hold threshold ({score:.0f} < {hold_min})")
            reasons.append(f"Overweight at {weight:.1f}% of portfolio (max {overweight}%)")
            if pnl_pct > 20:
                reasons.append(f"Take partial profits (+{pnl_pct:.1f}%)")
            return "TRIM", reasons

        # TRIM: decent score but significantly overweight
        if weight > overweight * 1.5:
            reasons.append(f"Significantly overweight: {weight:.1f}% (target max {overweight}%)")
            reasons.append("Reduce to improve diversification, regardless of score")
            return "TRIM", reasons

        # ADD: high score AND underweight or small position
        if score >= add_score and (weight < underweight or scan_action in ("BUY", "STRONG BUY")):
            reasons.append(f"Strong score ({score:.0f}) — analysis supports adding")
            if weight < underweight:
                reasons.append(f"Underweight at {weight:.1f}% (min {underweight}%)")
            if scan_action == "STRONG BUY":
                reasons.append("Scanner rates STRONG BUY")
            return "ADD", reasons

        # ADD: high score, moderate weight, good momentum
        if score >= add_score and weight <= overweight * 0.7:
            reasons.append(f"Score {score:.0f} supports adding — room under weight cap")
            return "ADD", reasons

        # HOLD: default for decent scores
        if score >= hold_min:
            reasons.append(f"Score {score:.0f} is acceptable — maintain position")
            if pnl_pct > 0:
                reasons.append(f"In profit (+{pnl_pct:.1f}%) — no reason to exit")
            elif pnl_pct < -10:
                reasons.append(f"Down {pnl_pct:.1f}% — hold for recovery, monitor closely")
            return "HOLD", reasons

        # Edge case: score between trim and hold, not overweight
        reasons.append(f"Score {score:.0f} is borderline — hold but monitor closely")
        if pnl_pct < -20:
            reasons.append(f"Significant loss ({pnl_pct:.1f}%) — set tight stop-loss")
        return "HOLD", reasons

    def _build_action_details(self, action, pos, rec, risk, total_portfolio_value, overweight_pct):
        """Build step-by-step action details with concrete share counts and prices."""
        details = {
            "action_steps": [],
            "action_order": "",
            "action_summary": "",
        }

        ticker = pos["ticker"]
        shares = pos["shares"]
        current_price = pos["current_price"]
        avg_price = pos["avg_price"]
        market_value = pos["market_value"]
        weight = pos["weight_pct"]
        sl_price = risk.get("stop_loss", {}).get("price")
        tp_price = risk.get("take_profit", {}).get("price")
        score = rec.get("composite_score", 50)

        if action == "ADD":
            # Calculate how many shares to add
            max_add_value = (total_portfolio_value * overweight_pct / 100) - market_value
            max_add_value = max(0, min(max_add_value, self.cash_available))
            shares_to_add = int(max_add_value / current_price) if current_price > 0 else 0
            shares_to_add = max(1, shares_to_add)

            add_cost = shares_to_add * current_price
            new_total_shares = shares + shares_to_add
            new_avg = (shares * avg_price + shares_to_add * current_price) / new_total_shares
            new_value = new_total_shares * current_price
            limit_price = round(current_price * 0.97, 2)

            details["shares_to_add"] = shares_to_add
            details["new_avg_price"] = round(new_avg, 2)
            details["add_cost"] = round(add_cost, 2)

            s_label = "share" if shares_to_add == 1 else "shares"
            details["action_steps"] = [
                f"Buy {shares_to_add} more {s_label} of {ticker}",
                f"Order: Limit @ ${limit_price:.2f} (3% below current ${current_price:.2f})",
            ]
            if sl_price:
                details["action_steps"].append(
                    f"After fill, set stop-loss at ${sl_price:.2f} for ALL {new_total_shares:.4g} shares"
                )
            details["action_steps"].append(
                f"New avg price: ~${new_avg:.2f} | New total value: ~${new_value:,.0f}"
            )
            if tp_price:
                risk_line = ""
                if sl_price:
                    risk_dollars = round(abs(current_price - sl_price) * new_total_shares, 0)
                    risk_line = f"Risk: ${risk_dollars:,.0f} | "
                target_pct = round((tp_price / current_price - 1) * 100, 1)
                details["action_steps"].append(
                    f"{risk_line}Target: ${tp_price:.2f} (+{target_pct}%)"
                )

            details["action_order"] = f"Limit @ ${limit_price:.2f}"
            details["action_summary"] = (
                f"Add {shares_to_add} {s_label} (~${add_cost:,.0f}), new avg ${new_avg:.2f}"
            )

        elif action == "TRIM":
            target_value = total_portfolio_value * overweight_pct / 100
            excess_value = market_value - target_value
            shares_to_sell = max(1, int(excess_value / current_price)) if current_price > 0 else 1
            # Don't sell more than we own minus 1
            shares_to_sell = min(shares_to_sell, max(1, int(shares) - 1))

            remaining = shares - shares_to_sell
            new_weight = (remaining * current_price) / total_portfolio_value * 100 if total_portfolio_value > 0 else 0
            proceeds = shares_to_sell * current_price

            details["shares_to_sell"] = shares_to_sell
            details["remaining_shares"] = round(remaining, 4)
            details["proceeds"] = round(proceeds, 2)

            score_note = "acceptable" if score >= 40 else "weak — monitor closely"
            s_label = "share" if shares_to_sell == 1 else "shares"
            details["action_steps"] = [
                f"Sell {shares_to_sell} of your {shares:.4g} {s_label} of {ticker}",
                f"Order: Market Order — reduce position now",
                f"Keep {remaining:.4g} shares — score {score:.0f} is {score_note}",
                f"New weight after trim: ~{new_weight:.1f}% (was {weight:.1f}%)",
                f"Proceeds: ~${proceeds:,.0f} returned to cash",
            ]
            details["action_order"] = "Market Order"
            details["action_summary"] = (
                f"Sell {shares_to_sell} {s_label} (~${proceeds:,.0f}), "
                f"keep {remaining:.4g}, weight {weight:.1f}% -> {new_weight:.1f}%"
            )

        elif action == "SELL":
            proceeds = shares * current_price
            pnl = pos["unrealized_pnl"]
            pnl_note = f"locking in ${pnl:+,.0f} profit" if pnl >= 0 else f"cutting loss at ${pnl:+,.0f}"

            details["proceeds"] = round(proceeds, 2)

            details["action_steps"] = [
                f"Sell ALL {shares:.4g} shares of {ticker}",
                f"Order: Market Order — exit entire position",
                f"Proceeds: ~${proceeds:,.0f} ({pnl_note})",
                f"Frees up {weight:.1f}% of portfolio for better opportunities",
            ]
            details["action_order"] = "Market Order"
            details["action_summary"] = f"Exit all {shares:.4g} shares (~${proceeds:,.0f})"

        elif action == "HOLD":
            details["action_steps"] = [
                f"No action needed for {ticker}",
            ]
            if sl_price:
                details["action_steps"].append(
                    f"Ensure stop-loss is set at ${sl_price:.2f} to protect your position"
                )
            if tp_price:
                details["action_steps"].append(
                    f"Take-profit target: ${tp_price:.2f}"
                )
            details["action_steps"].append("Review again on next scan")
            details["action_order"] = "None"
            details["action_summary"] = "Maintain position, monitor"

        return details

    def get_sector_exposure(self, positions_data, fundamentals_map):
        """Calculate sector exposure from existing holdings."""
        sector_totals = {}
        total = positions_data["total_portfolio_value"]

        for pos in positions_data["positions"]:
            ticker = pos["ticker"]
            fund = fundamentals_map.get(ticker, {})
            sector = fund.get("sector", "Unknown")
            sector_totals[sector] = sector_totals.get(sector, 0) + pos["market_value"]

        return {
            sector: {
                "amount": round(amount, 2),
                "pct": round(amount / total * 100, 2) if total > 0 else 0,
            }
            for sector, amount in sorted(
                sector_totals.items(), key=lambda x: x[1], reverse=True
            )
        }

    def get_portfolio_aware_budget(self, positions_data):
        """Return the effective budget for new investments."""
        return self.cash_available
