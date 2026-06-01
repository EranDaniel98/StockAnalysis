"""Single source of truth for the live strategy label.

``strategy_name()`` (e.g. ``composite_d05_r63``) tags picks, reports and the
API. ``execution_label()`` is ``factor_<name>`` — the kill-switch rollover key
and the Alpaca client-order-id namespace. Live paper state on disk is keyed to
that value, so it must stay byte-stable across edits; the label lives in
``config/settings.yaml`` (``strategy.name``) and everything derives from it.
"""

from __future__ import annotations

from src.config_loader import Config

# Fallback used only if config is unreadable. Must equal the shipped
# settings.yaml value so behavior is identical with or without config.
_DEFAULT_NAME = "composite_d05_r63"


def strategy_name(config: Config | None = None) -> str:
    return (config or Config()).get("strategy", "name", default=_DEFAULT_NAME)


def execution_label(config: Config | None = None) -> str:
    return "factor_" + strategy_name(config)
