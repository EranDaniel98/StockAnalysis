# Archived scripts

One-shot experiments and superseded utilities. Kept on-disk for git
history and as references for past methodology, but not part of the
active CLI / pipeline surface.

## Inventory

- `eyeball_catalyst_anchors.py` — hand-inspection helper for the
  catalyst analyzer's filing anchors. Used during the 2026-05-13
  catalyst rollout; the catalyst feature was disabled after the null
  A/B (see `MEMORY.md` → `project_catalyst_ab_null.md`).
- `wait_then_battery.py`, `wait_then_sweep.py` — scaffolding to run a
  sweep after another long-running job finished. Replaced by the
  automatic notifications in the new task runner.
- `produce_mvtp_report.py` — one-shot "minimum viable trading platform"
  report writer. Pre-dates `scripts/comprehensive_analysis.py` which
  covers the same surface with cleaner abstractions.
- `run_minimal_baseline.py` — first credible OOS validation harness
  (see `MEMORY.md` → `project_minimal_baseline_2022_2024.md`). Its
  result is now baked into the live factor strategy; this script is
  kept for reproducibility, not active use.
