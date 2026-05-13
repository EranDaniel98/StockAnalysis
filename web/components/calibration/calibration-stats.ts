/**
 * Calibration summary stats computed from per-bin aggregates.
 *
 * The /api/analytics/calibration endpoint only returns bucket-level stats
 * (avg / median / win_rate), not per-trade rows, so the correlations here
 * are computed against bin midpoints weighted by trade count. They answer
 * the same monotonicity question (do higher scores -> higher realized
 * returns?) without needing the raw trade table.
 */

import type { CalibrationBucketRow } from "./calibration-chart";

export type CalibrationStats = {
  pearson: number | null;
  spearman: number | null;
  monotonicityPct: number | null;
  totalScored: number;
  populatedBins: number;
};

/** Per-bin midpoint + observed avg_pnl, weighted by n_trades. */
type Row = { x: number; y: number; w: number };

function rowsFromBuckets(buckets: CalibrationBucketRow[]): Row[] {
  const rows: Row[] = [];
  for (const b of buckets) {
    if (b.n_trades > 0 && b.avg_pnl_pct != null) {
      rows.push({
        x: (b.lower + b.upper) / 2,
        y: b.avg_pnl_pct,
        w: b.n_trades,
      });
    }
  }
  return rows;
}

function weightedPearson(rows: Row[]): number | null {
  if (rows.length < 2) return null;
  const W = rows.reduce((acc, r) => acc + r.w, 0);
  if (W <= 0) return null;
  const mx = rows.reduce((a, r) => a + r.w * r.x, 0) / W;
  const my = rows.reduce((a, r) => a + r.w * r.y, 0) / W;
  let cov = 0;
  let vx = 0;
  let vy = 0;
  for (const r of rows) {
    const dx = r.x - mx;
    const dy = r.y - my;
    cov += r.w * dx * dy;
    vx += r.w * dx * dx;
    vy += r.w * dy * dy;
  }
  const denom = Math.sqrt(vx * vy);
  return denom > 0 ? cov / denom : null;
}

/** Spearman = Pearson on tied-rank averages. Bin midpoints are already
 *  ordered, so x-ranks come for free; y-ranks need a sort. */
function spearmanRank(rows: Row[]): number | null {
  if (rows.length < 2) return null;
  const ranked = rankWithTies(rows.map((r) => r.y));
  const xRanks = rows.map((_, i) => i + 1);
  const weighted: Row[] = rows.map((r, i) => ({
    x: xRanks[i],
    y: ranked[i],
    w: r.w,
  }));
  return weightedPearson(weighted);
}

function rankWithTies(values: number[]): number[] {
  const indexed = values.map((v, i) => ({ v, i }));
  indexed.sort((a, b) => a.v - b.v);
  const ranks = new Array<number>(values.length);
  let i = 0;
  while (i < indexed.length) {
    let j = i;
    while (j + 1 < indexed.length && indexed[j + 1].v === indexed[i].v) j += 1;
    const avgRank = (i + j) / 2 + 1; // 1-based midrank
    for (let k = i; k <= j; k += 1) ranks[indexed[k].i] = avgRank;
    i = j + 1;
  }
  return ranks;
}

/** Fraction of adjacent populated-bin pairs where avg_pnl is non-decreasing. */
function monotonicityPct(rows: Row[]): number | null {
  if (rows.length < 2) return null;
  let ok = 0;
  for (let i = 1; i < rows.length; i += 1) {
    if (rows[i].y >= rows[i - 1].y) ok += 1;
  }
  return (ok / (rows.length - 1)) * 100;
}

export function computeCalibrationStats(
  buckets: CalibrationBucketRow[],
): CalibrationStats {
  const rows = rowsFromBuckets(buckets);
  const totalScored = buckets.reduce((acc, b) => acc + b.n_trades, 0);
  return {
    pearson: weightedPearson(rows),
    spearman: spearmanRank(rows),
    monotonicityPct: monotonicityPct(rows),
    totalScored,
    populatedBins: rows.length,
  };
}
