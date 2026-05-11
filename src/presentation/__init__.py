"""Presentation bounded context.

CLI rendering lives in src/presentation/cli/ (Rich tables, panels). When
the web layer arrives in Phase 1+, it imports the shared formatters from
this package and uses its own React components for actual rendering.

Phase 0 keeps the legacy 607-line src/display/cli_output.py intact at its
new home (src/presentation/cli/cli_output.py). A follow-up slice will
split it into tables.py / panels.py / formatters.py per the plan.
"""
