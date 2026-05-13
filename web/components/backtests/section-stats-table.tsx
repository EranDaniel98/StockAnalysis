"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { fmtNumber, fmtPct, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

type SectionSummary = {
  n_trades?: number;
  total_return_pct?: number;
  cagr_pct?: number;
  win_rate_pct?: number;
  expectancy_pct?: number;
  avg_hold_days?: number;
  sharpe_per_trade?: number;
  spy_return_pct?: number | null;
  alpha_vs_spy_pct?: number | null;
};

type SectionEquity = {
  max_drawdown_pct?: number;
  time_in_dd_pct?: number;
  ann_sharpe?: number;
  ann_sortino?: number;
  calmar?: number;
  ann_volatility_pct?: number;
};

type Section = {
  summary?: SectionSummary;
  equity_stats?: SectionEquity;
};

/**
 * IS / OOS / Full comparison grid — the equivalent of a walk-forward fold
 * matrix for the single-split engine. Hairline rows, mono numerics, P&L
 * cells toned via the bullish/bearish tokens. OOS is the trustworthy
 * column per the engine notes; we emphasise it with a tinted background.
 */
export function SectionStatsTable({
  full,
  inSample,
  outOfSample,
  splitDate,
}: {
  full: Section;
  inSample: Section;
  outOfSample: Section;
  splitDate?: string | null;
}) {
  const sections: Array<{
    key: "is" | "oos" | "full";
    label: string;
    section: Section;
    emphasise?: boolean;
  }> = [
    { key: "is", label: "In Sample", section: inSample },
    { key: "oos", label: "Out of Sample", section: outOfSample, emphasise: true },
    { key: "full", label: "Full Window", section: full },
  ];

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Window</TableHead>
          <TableHead className="text-right">Trades</TableHead>
          <TableHead className="text-right">Return %</TableHead>
          <TableHead className="text-right">CAGR %</TableHead>
          <TableHead className="text-right">Win %</TableHead>
          <TableHead className="text-right">Expect %</TableHead>
          <TableHead className="text-right">Hold d</TableHead>
          <TableHead className="text-right">Ann Sharpe</TableHead>
          <TableHead className="text-right">Sortino</TableHead>
          <TableHead className="text-right">Max DD %</TableHead>
          <TableHead className="text-right">Alpha vs SPY</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sections.map(({ key, label, section, emphasise }) => {
          const s = section.summary ?? {};
          const eq = section.equity_stats ?? {};
          return (
            <TableRow
              key={key}
              mono
              className={cn(emphasise && "bg-muted/30")}
            >
              <TableCell className="font-sans">
                <span className="text-foreground text-xs font-medium">
                  {label}
                </span>
                {key === "oos" && splitDate ? (
                  <span className="text-muted-foreground ml-2 text-[10px] tracking-wider uppercase">
                    from {splitDate}
                  </span>
                ) : null}
              </TableCell>
              <TableCell className="text-right">
                {s.n_trades ?? "—"}
              </TableCell>
              <TableCell
                className={cn("text-right", pnlColorClass(s.total_return_pct))}
              >
                {fmtPct(s.total_return_pct, 2, true)}
              </TableCell>
              <TableCell
                className={cn("text-right", pnlColorClass(s.cagr_pct))}
              >
                {fmtPct(s.cagr_pct, 2, true)}
              </TableCell>
              <TableCell className="text-right">
                {fmtPct(s.win_rate_pct, 1)}
              </TableCell>
              <TableCell
                className={cn("text-right", pnlColorClass(s.expectancy_pct))}
              >
                {fmtPct(s.expectancy_pct, 2, true)}
              </TableCell>
              <TableCell className="text-right text-muted-foreground">
                {fmtNumber(s.avg_hold_days, 0)}
              </TableCell>
              <TableCell
                className={cn("text-right", pnlColorClass(eq.ann_sharpe))}
              >
                {fmtNumber(eq.ann_sharpe, 2)}
              </TableCell>
              <TableCell
                className={cn("text-right", pnlColorClass(eq.ann_sortino))}
              >
                {fmtNumber(eq.ann_sortino, 2)}
              </TableCell>
              <TableCell
                className={cn(
                  "text-right",
                  pnlColorClass(-(eq.max_drawdown_pct ?? 0)),
                )}
              >
                {fmtPct(eq.max_drawdown_pct, 2)}
              </TableCell>
              <TableCell
                className={cn("text-right", pnlColorClass(s.alpha_vs_spy_pct))}
              >
                {s.alpha_vs_spy_pct == null
                  ? "—"
                  : fmtPct(s.alpha_vs_spy_pct, 2, true)}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
