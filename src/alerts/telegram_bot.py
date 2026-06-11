"""
Telegram bot for sending stock alerts and daily summaries.
"""

import logging
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)


def send_ops_alert(message):
    """Best-effort ops alert (pipeline failures, gate refusals, heartbeats).

    Builds its own Config + TelegramAlerter so call sites stay one line.
    Never raises — an unconfigured or unreachable Telegram must not break
    the pipeline or block a trading decision. Returns True if the send
    was attempted (config enabled + bot built), False otherwise.
    """
    try:
        from src.config_loader import Config

        alerter = TelegramAlerter(Config())
        if not alerter.enabled or alerter._get_bot() is None:
            return False
        alerter.send_text(message)
        return True
    except Exception as e:  # noqa: BLE001 — alerting is best-effort
        logger.info("telegram ops alert skipped (%s)", e)
        return False


class TelegramAlerter:
    def __init__(self, config):
        self.config = config
        self.token = config.telegram_token
        self.chat_id = config.telegram_chat_id
        self.enabled = config.get("alerts", "telegram", "enabled", default=True)
        self.min_score = config.get("alerts", "telegram", "min_score_to_notify", default=75)
        self._bot = None

    def _get_bot(self):
        """Lazy-initialize the Telegram bot."""
        if self._bot is None:
            if not self.token or not self.chat_id:
                logger.error(
                    "Telegram bot token or chat ID not configured. "
                    "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
                )
                return None
            try:
                from telegram import Bot
                self._bot = Bot(token=self.token)
            except ImportError:
                logger.error(
                    "python-telegram-bot not installed. "
                    "Install with: pip install python-telegram-bot"
                )
                return None
        return self._bot

    def send_alerts(self, recommendations):
        """
        Send Telegram alerts for stocks meeting the score threshold.

        Args:
            recommendations: list of recommendation dicts
        """
        if not self.enabled:
            logger.info("Telegram alerts disabled in config")
            return

        qualifying = [
            r for r in recommendations
            if r["composite_score"] >= self.min_score
            and r["action"] in ("STRONG BUY", "BUY")
        ]

        if not qualifying:
            logger.info("No stocks meet the alert threshold")
            return

        logger.info(f"Sending Telegram alerts for {len(qualifying)} stocks")

        # Build and send messages
        for rec in qualifying:
            message = self._format_alert(rec)
            self._send_message(message)

    def send_summary(self, recommendations, strategy_name=None):
        """Send a summary of the top stocks."""
        if not self.enabled:
            return

        message = self._format_summary(recommendations, strategy_name)
        self._send_message(message)

    def send_text(self, message):
        """Send a free-form text message (ops alerts, heartbeats).

        Public entry point for callers outside the recommendation flow
        (pipeline failure alerts, pre-trade gate refusals, daily-cron
        heartbeats). Honors the config enable flag; never raises.
        """
        if not self.enabled:
            logger.info("Telegram alerts disabled in config")
            return
        self._send_message(message)

    def _send_message(self, message):
        """Send a message via Telegram."""
        bot = self._get_bot()
        if bot is None:
            return

        try:
            asyncio.run(bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown",
            ))
            logger.info("Telegram message sent")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            # Try without markdown if formatting fails
            try:
                asyncio.run(bot.send_message(
                    chat_id=self.chat_id,
                    text=message.replace("*", "").replace("`", ""),
                ))
            except Exception as e2:
                logger.error(f"Telegram fallback also failed: {e2}")

    def _format_alert(self, rec):
        """Format a single stock alert message."""
        risk = rec.get("risk_management", {})
        sl = risk.get("stop_loss", {})
        tp = risk.get("take_profit", {})
        pos = risk.get("position", {})

        lines = [
            f"{'🟢' if rec['action'] == 'STRONG BUY' else '🔵'} *{rec['action']}*: {rec['ticker']}",
            f"*{rec.get('name', rec['ticker'])}*",
            f"Score: *{rec['composite_score']:.0f}/100* | Confidence: {rec.get('confidence', 'N/A')}",
            f"Sector: {rec.get('sector', 'N/A')} | Industry: {rec.get('industry', 'N/A')}",
            "",
            "*Score Breakdown:*",
        ]

        sub = rec.get("sub_scores", {})
        for cat, score in sub.items():
            emoji = "🟢" if score >= 65 else "🟡" if score >= 45 else "🔴"
            lines.append(f"  {emoji} {cat.capitalize()}: {score:.0f}")

        lines.append("")
        lines.append("*Key Signals:*")
        for reason in rec.get("reasoning", [])[:5]:
            lines.append(f"  {reason}")

        if risk:
            lines.extend([
                "",
                "*Risk Management:*",
                f"  Price: ${risk.get('current_price', 'N/A')}",
            ])
            if sl.get("price"):
                lines.append(f"  Stop Loss: ${sl['price']} ({sl.get('pct_from_current', 0):+.1f}%)")
            if tp.get("price"):
                lines.append(f"  Target: ${tp['price']} ({tp.get('pct_from_current', 0):+.1f}%)")
            lines.append(f"  R:R Ratio: {risk.get('risk_reward_ratio', 'N/A')}")
            if pos.get("recommended_shares"):
                lines.append(f"  Suggested: {pos['recommended_shares']} shares (${pos.get('dollar_amount', 0):,.0f})")

        lines.extend(["", f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}_"])

        return "\n".join(lines)

    def _format_summary(self, recommendations, strategy_name=None):
        """Format a summary of top recommendations."""
        lines = [
            "📊 *Stock Scanner Summary*",
            f"Strategy: {strategy_name or 'Default'}",
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"Stocks Analyzed: {len(recommendations)}",
            "",
        ]

        # Top BUY recommendations
        buys = [r for r in recommendations if r["action"] in ("STRONG BUY", "BUY")]
        if buys:
            lines.append(f"*Top {min(10, len(buys))} Buy Signals:*")
            for i, rec in enumerate(buys[:10], 1):
                risk = rec.get("risk_management", {})
                price = risk.get("current_price", "N/A")
                emoji = "🟢" if rec["action"] == "STRONG BUY" else "🔵"
                lines.append(
                    f"{i}. {emoji} `{rec['ticker']}` {rec['action']} "
                    f"({rec['composite_score']:.0f}) - ${price}"
                )
        else:
            lines.append("_No BUY signals found_")

        # Sell signals
        sells = [r for r in recommendations if r["action"] in ("SELL", "STRONG SELL")]
        if sells:
            lines.append("")
            lines.append(f"*Sell Signals ({len(sells)}):*")
            for rec in sells[:5]:
                lines.append(f"  🔴 `{rec['ticker']}` ({rec['composite_score']:.0f})")

        # Signal counts
        action_counts = {}
        for r in recommendations:
            action_counts[r["action"]] = action_counts.get(r["action"], 0) + 1

        lines.extend([
            "",
            "*Distribution:*",
        ])
        for action in ("STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"):
            count = action_counts.get(action, 0)
            if count > 0:
                lines.append(f"  {action}: {count}")

        return "\n".join(lines)
