"""Research bounded context.

Houses the analysis pipelines that aren't single-ticker scoring:
  - diagnostic_service: alphalens IC diagnostic (moved from src/diagnostic/)
  - quantstats_service: tearsheet renderer (moved from src/diagnostic/)

Stream B's final slice (deferred) will extract the backtest orchestration
from src/backtest/engine.py into src/research/backtest_service.py. For
now the engine stays in place and src/main.py:cmd_backtest still calls
it directly.
"""

from src.research import diagnostic_service, quantstats_service

__all__ = ["diagnostic_service", "quantstats_service"]
