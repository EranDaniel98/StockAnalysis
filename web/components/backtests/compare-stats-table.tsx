"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { chartColor } from "@/lib/chart-tokens";
import { fmtNumber, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

export type CompareStatRun = {
  key: string;
  label: string;
  fullSharpe?: number | null;
  oosSharpe?: number | null;
  oosReturnPct?: number | null;
  maxDrawdownPct?: number | null;
  winRatePct?: number | null;
  nTrades?: number | null;
};

type StatKey =
  | "fullSharpe"
  | "oosSharpe"
  | "oosReturnPct"
  | "maxDrawdownPct"
  | "winRatePct"
  | "nTrades";

type StatRow = {
  key: StatKey;
  label: string;
  /** "higher" = larger is better; "lower" = smaller is better; "none" = skip highlight. */
  direction: "higher" | "lower" | "none";
  format: (v: number | null | undefined) => string;
};

const STAT_ROWS: StatRow[] = [
  {
    key: "fullSharpe",
    label: "Full Sharpe",
    direction: "higher",
    format: (v) => fmtNumber(v, 2),
  },
  {
    key: "oosSharpe",
    label: "OOS Sharpe",
    direction: "higher",
    format: (v) => fmtNumber(v, 2),
  },
  {
    key: "oosReturnPct",
    label: "OOS Return %",
    direction: "higher",
    format: (v) => fmtPct(v, 2, true),
  },
  {
    key: "maxDrawdownPct",
    label: "Max DD %",
    // max_drawdown_pct is stored as a negative number; "smaller magnitude" =
    // "closer to zero" = better. So the highest value is best.
    direction: "higher",
    format: (v) => fmtPct(v, 2),
  },
  {
    key: "winRatePct",
    label: "Win %",
    direction: "higher",
    format: (v) => fmtPct(v, 1),
  },
  {
    key: "nTrades",
    label: "# Trades",
    direction: "none",
    format: (v) => (v == null ? "—" : String(v)),
  },
];

/** Pick the best and worst index for a stat row, ignoring nulls / NaN. */
function rankIndices(
  runs: CompareStatRun[],
  key: StatKey,
  direction: "higher" | "lower" | "none",
): { best: Set<number>; worst: Set<number> } {
  if (direction === "none") {
    return { best: new Set(), worst: new Set() };
  }
  const values = runs.map((r) => r[key]);
  const valid = values
    .map((v, i) => ({ v, i }))
    .filter(
      (x): x is { v: number; i: number } =>
        x.v != null && !Number.isNaN(x.v as number),
    );
  if (valid.length < 2) return { best: new Set(), worst: new Set() };
  const sorted = [...valid].sort((a, b) =>
    direction === "higher" ? b.v - a.v : a.v - b.v,
  );
  const bestVal = sorted[0].v;
  const worstVal = sorted[sorted.length - 1].v;
  if (bestVal === worstVal) return { best: new Set(), worst: new Set() };
  return {
    best: new Set(valid.filter((x) => x.v === bestVal).map((x) => x.i)),
    worst: new Set(valid.filter((x) => x.v === worstVal).map((x) => x.i)),
  };
}

/**
 * Per-row best (text-bullish) + worst (text-bearish) highlighting. Stats with
 * no obvious direction (# trades) skip the highlight.
 *
 * Column headers carry the chartColor(i) accent that pairs each column with
 * the matching equity-curve line.
 */
export function CompareStatsTable({ runs }: { runs: CompareStatRun[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-44">Statistic</TableHead>
          {runs.map((r, i) => (
            <TableHead
              key={r.key}
              className="text-right"
              style={{ color: chartColor(i) }}
            >
              <span className="font-mono text-[10px] tracking-wider uppercase">
                [ {r.label} ]
              </span>
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {STAT_ROWS.map((row) => {
          const { best, worst } = rankIndices(runs, row.key, row.direction);
          return (
            <TableRow key={row.key} mono>
              <TableCell className="font-sans text-xs font-medium text-foreground">
                {row.label}
              </TableCell>
              {runs.map((r, i) => {
                const v = r[row.key];
                const tone = best.has(i)
                  ? "text-bullish"
                  : worst.has(i)
                    ? "text-bearish"
                    : "text-foreground";
                return (
                  <TableCell
                    key={r.key}
                    className={cn("text-right", tone)}
                  >
                    {row.format(v)}
                  </TableCell>
                );
              })}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
