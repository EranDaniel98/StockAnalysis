"""Rich-based CLI rendering. The single legacy module lives here for now;
a follow-up Stream B slice will split it into tables/panels/formatters."""

from src.presentation.cli import cli_output

__all__ = ["cli_output"]
