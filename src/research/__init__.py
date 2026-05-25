"""Research bounded context.

Live consumers after the 5-engine → factor-pipeline migration:
  - per_stock_analyzer: builds the per-ticker trading plan that feeds
    comprehensive_analysis.md and the morning briefing
  - per_stock_markdown: render the analyzer's typed output

``diagnostic_service`` / ``quantstats_service`` / ``sweep_runner`` were
deleted 2026-05-23 along with the rest of the legacy stack.
"""
