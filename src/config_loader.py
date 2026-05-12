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
