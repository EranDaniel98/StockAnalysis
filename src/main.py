"""Legacy entry point. Real implementation lives in ``src.cli.main``.

Kept so ``python -m src.main`` and ``from src.main import main`` keep working
for cron jobs, README snippets, and the documentation. New code should use
``python -m src.cli.main`` directly.
"""

from src.cli.main import main

if __name__ == "__main__":
    main()
