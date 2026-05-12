"""Phase 4 ML platform.

Components:
  - feature_store      : compute + persist daily factor snapshots
  - dataset            : assemble (date, ticker) → factors + forward-return
                         training matrix
  - models             : individual trainers (lightgbm, ridge, ffn)
  - drift              : rolling IC vs training IC monitor (P4.5)

The current hand-tuned weighted-sum composite stays available as the
``legacy_v1`` strategy alias so the ML output can be benchmarked against
what the project shipped pre-ML.
"""
