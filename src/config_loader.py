"""
Configuration loader - reads all YAML configs and environment variables.
Provides unified access to all settings with nested key support.
"""

import yaml
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class Config:
    def __init__(self, config_dir=None, env_file=None):
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        self.config_dir = Path(config_dir)

        # Load .env file
        env_path = env_file or Path(__file__).parent.parent / ".env"
        load_dotenv(dotenv_path=env_path)

        # Load all config files
        self.settings = self._load_yaml("settings.yaml")
        self.sectors = self._load_yaml("sectors.yaml")
        self.strategies = self._load_yaml("strategies.yaml")

        # Secrets from environment
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        # Setup logging from config
        self._setup_logging()

    def _load_yaml(self, filename, required=True):
        path = self.config_dir / filename
        if not path.exists():
            if required:
                raise FileNotFoundError(f"Config file not found: {path}")
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        logger.debug(f"Loaded config: {filename}")
        return data or {}

    def _setup_logging(self):
        # If something else (e.g. src.observability.logging.configure_logging
        # called by the FastAPI factory) already set up the root logger, don't
        # clobber it with basicConfig — that would tear down structured JSON
        # output for every CLI helper that happens to construct a Config.
        if logging.getLogger().handlers:
            return

        level_str = self.get("logging", "level", default="INFO")
        level = getattr(logging, level_str.upper(), logging.INFO)
        log_file = self.get("logging", "file")

        handlers = [logging.StreamHandler()]
        if log_file:
            handlers.append(logging.FileHandler(log_file))

        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            handlers=handlers,
        )

    def get(self, *keys, default=None):
        """
        Get a nested config value from settings.

        Usage:
            config.get('technical_indicators', 'rsi', 'period')  -> 14
            config.get('markets', 'exchanges')                   -> ['NYSE', 'NASDAQ']
            config.get('nonexistent', 'key', default=42)         -> 42
        """
        result = self.settings
        for key in keys:
            if isinstance(result, dict) and key in result:
                result = result[key]
            else:
                return default
        return result

    def get_strategy(self, name=None):
        """Get a strategy config by name, or the default strategy."""
        if name is None:
            name = self.strategies.get("default_strategy", "long_term_growth")
        strategies = self.strategies.get("strategies", {})
        if name not in strategies:
            available = list(strategies.keys())
            raise ValueError(
                f"Strategy '{name}' not found. Available: {available}"
            )
        return strategies[name]

    def get_strategy_names(self):
        """Get list of all available strategy names."""
        return list(self.strategies.get("strategies", {}).keys())

    def get_sector(self, name):
        """Get a sector definition by key."""
        return self.sectors.get("sectors", {}).get(name, {})

    def get_all_sectors(self):
        """Get all sector definitions."""
        return self.sectors.get("sectors", {})

    def get_theme(self, name):
        """Get a theme definition by key."""
        return self.sectors.get("themes", {}).get(name, {})

    def get_all_themes(self):
        """Get all theme definitions."""
        return self.sectors.get("themes", {})

    def get_watchlist(self):
        """Get the custom watchlist tickers."""
        return self.sectors.get("watchlist", [])

    def get_value_cohort_tickers(self):
        """Mid/small-cap value-tilted universe used by the insider /
        catalyst A/B sweeps. Defined in ``config/sectors.yaml`` under
        the ``value_cohort:`` key. Empty list if the key is missing
        (back-compat for older configs)."""
        return list(self.sectors.get("value_cohort", []))

    def get_russell_1000_tickers(self):
        """The current Russell 1000 constituents — top-1000 US listed
        companies by market cap. Sourced from iShares IWB holdings via
        ``scripts/fetch_russell_1000.py`` which writes
        ``config/russell_1000_tickers.txt``. Returns [] when the file
        doesn't exist yet — run the fetcher to populate.

        Refresh schedule: iShares updates IWB daily; we typically re-run
        the fetcher quarterly or after a Russell reconstitution (last
        Friday of June each year)."""
        path = self.config_dir / "russell_1000_tickers.txt"
        if not path.exists():
            return []
        return sorted(
            t.strip() for t in path.read_text(encoding="utf-8").splitlines()
            if t.strip() and not t.startswith("#")
        )

    def get_sp500_pit_tickers(self, as_of_date) -> list[str]:
        """Reconstructed S&P 500 constituents as of ``as_of_date``.

        Backed by ``src.universe.sp500_pit.SP500Membership``. Returns a
        sorted list so caller order is deterministic. Raises
        ``FileNotFoundError`` if the membership CSVs haven't been
        scraped — run ``scripts/fetch_sp500_membership.py`` first.
        """
        from src.universe import load_default_sp500

        membership = load_default_sp500()
        return sorted(membership.as_of(as_of_date))

    def get_universe_captured_date(self, universe_label: str):
        """Return the ``# captured: YYYY-MM-DD`` date in a universe file.

        Review item #4: a historical backtest whose end_date is AFTER
        the universe was captured is structurally survivor-biased — the
        ticker list only contains names that survived to the capture
        date. The backtest engine reads this to refuse such runs unless
        the operator passes an explicit override.

        Returns ``date`` on success; raises ``ValueError`` when the file
        exists but has no header (so we don't silently treat a missing
        header as "no bias risk"); returns ``None`` when the file
        doesn't exist (universe is empty)."""
        from datetime import date

        # sp500_pit is a reconstructed universe — there is no "captured
        # date" because membership is computed per-target-date from the
        # Wikipedia changes log. Return None so the survivorship guard
        # in the backtest engine permits any historical window.
        if universe_label == "sp500_pit":
            return None

        path_map = {
            "russell_1000": self.config_dir / "russell_1000_tickers.txt",
        }
        path = path_map.get(universe_label)
        if path is None or not path.exists():
            return None
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("#"):
                # First non-comment line — header block ended without a
                # match. Header MUST come before tickers.
                break
            # Form: "# captured: 2026-05-13" — case-insensitive label.
            body = line.lstrip("#").strip()
            if body.lower().startswith("captured:"):
                stamp = body.split(":", 1)[1].strip()
                try:
                    return date.fromisoformat(stamp)
                except ValueError as exc:
                    raise ValueError(
                        f"{path.name}: malformed captured-date "
                        f"{stamp!r}; expected YYYY-MM-DD"
                    ) from exc
        raise ValueError(
            f"{path.name}: missing '# captured: YYYY-MM-DD' header. "
            f"Add the date the ticker list was snapshotted so the "
            f"backtest engine can refuse survivor-biased windows."
        )

    def get_theme_tickers(self):
        """Get all known tickers from all themes (deduplicated)."""
        tickers = set()
        for theme in self.get_all_themes().values():
            tickers.update(theme.get("known_tickers", []))
        return sorted(tickers)

    def get_focused_sectors(self):
        """Get the list of sectors the user wants to focus on."""
        return self.get("sectors_focus", default=[])

    def get_scoring_thresholds(self):
        """Get scoring thresholds for recommendation labels."""
        return self.get("scoring", "thresholds", default={
            "strong_buy": 80,
            "buy": 65,
            "hold_upper": 50,
            "hold_lower": 35,
            "sell": 20,
        })

    def get_regime_filter(self):
        """Get the market-regime entry-gate config.

        Returns a dict with: enabled, mode, sma_period, vix_low, vix_high.
        Defaults disable the gate so old YAMLs without this block keep
        their pre-regime behavior.
        """
        return self.get("risk_management", "regime_filter", default={
            "enabled": False,
            "mode": "off",
            "sma_period": 200,
            "vix_low": 20.0,
            "vix_high": 25.0,
        })

    def get_sector_relative_scoring(self):
        """Get the sector-relative scoring config.

        Returns ``{enabled, min_cohort}``. Defaults disabled — old
        YAMLs without the block reproduce legacy absolute-threshold
        behavior. Enable via settings.yaml or programmatically in
        sweep scripts.
        """
        return self.get("risk_management", "sector_relative_scoring", default={
            "enabled": False,
            "min_cohort": 5,
        })

    def get_analyst_scoring(self):
        """Get the analyst-score toggle config.

        Returns ``{enabled: bool}``. Default enabled — preserves legacy
        behavior so old YAMLs without the block keep producing the same
        composite scores.
        """
        return self.get("risk_management", "analyst_score", default={
            "enabled": True,
        })

    def get_catalyst(self):
        """Insider catalyst-narrative scoring config.

        Returns ``{enabled, max_age_days, min_sim}``. Defaults disabled —
        the day-5 ML A/B (2026-05-13) showed only +0.0053 Pearson IC
        lift on 74/7644 rows. The analyzer's main value is
        explainability (one-line catalyst label in the rationale), not
        raw alpha. Enable when a future A/B sweep on a broader universe
        + denser 8-K corpus shows decisive lift.

        - ``enabled``: include catalyst.analyze in the scan path
        - ``max_age_days``: how stale a snapshot can be (default 60)
        - ``min_sim``: cosine floor below which an anchor doesn't fire
          (default 0.30 — calibrated by the day-1 eyeball test)
        """
        return self.get("risk_management", "catalyst", default={
            "enabled": False,
            "max_age_days": 60,
            "min_sim": 0.30,
        })

    def get_insider_flow(self):
        """Insider Form 4 cluster-buy scoring config.

        Returns ``{enabled, enrich_narrative, lookback_days, window_days}``.
        Defaults disabled — the 2026-05-13 A/B sweep on the themes
        universe showed the signal is too sparse on large-cap tech to
        move OOS Sharpe. Enable when the universe expands to mid/small-
        cap value where insider buying actually clusters.

        - ``enabled``: include insider_flow.analyze in the scan path
        - ``enrich_narrative``: when a cluster fires, look up the
          nearest 8-K in filings_corpus and attach an excerpt
        - ``lookback_days``: how far back we look for insider rows to
          feed the analyzer
        - ``window_days`` / ``min_cluster_insiders``: forwarded to the
          analyzer's InsiderFlowParams
        """
        return self.get("risk_management", "insider_flow", default={
            "enabled": False,
            "enrich_narrative": False,
            "lookback_days": 60,
            "window_days": 30,
            "min_cluster_insiders": 2,
        })
