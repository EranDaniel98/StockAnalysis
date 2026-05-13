"use client";

import { Badge } from "@/components/ui/badge";
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

export type Trade = {
  ticker?: string;
  entry_date?: string;
  exit_date?: string;
  entry_price?: number;
  exit_price?: number;
  pnl_pct?: number;
  pnl?: number;
  hold_days?: number;
  r_multiple?: number;
  exit_reason?: string;
  sector?: string;
  [k: string]: unknown;
};

/**
 * Dense trade log, scrollable. Hairline rows in monospace, right-aligned
 * numerics, win/loss tag as a bullish/bearish Badge. R-multiple and P&L
 * cells tone via pnlColorClass.
 */
export function TradeTable({
  trades,
  limit = 200,
}: {
  trades: Trade[];
  limit?: number;
}) {
  const shown = trades.slice(0, limit);

  return (
    <div className="max-h-[520px] overflow-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Ticker</TableHead>
            <TableHead>Entry</TableHead>
            <TableHead className="text-right">Entry Px</TableHead>
            <TableHead>Exit</TableHead>
            <TableHead className="text-right">Exit Px</TableHead>
            <TableHead className="text-right">Hold d</TableHead>
            <TableHead className="text-right">R</TableHead>
            <TableHead className="text-right">P&amp;L %</TableHead>
            <TableHead>Outcome</TableHead>
            <TableHead>Exit Reason</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((t, i) => {
            const win = (t.pnl_pct ?? 0) > 0;
            return (
              <TableRow key={`${t.ticker ?? i}-${t.entry_date ?? i}`} mono>
                <TableCell className="text-foreground">
                  {t.ticker ?? "—"}
                </TableCell>
                <TableCell className="text-muted-foreground text-[11px]">
                  {t.entry_date ?? "—"}
                </TableCell>
                <TableCell className="text-right">
                  {t.entry_price != null ? fmtNumber(t.entry_price, 2) : "—"}
                </TableCell>
                <TableCell className="text-muted-foreground text-[11px]">
                  {t.exit_date ?? "—"}
                </TableCell>
                <TableCell className="text-right">
                  {t.exit_price != null ? fmtNumber(t.exit_price, 2) : "—"}
                </TableCell>
                <TableCell className="text-right text-muted-foreground">
                  {t.hold_days ?? "—"}
                </TableCell>
                <TableCell
                  className={cn("text-right", pnlColorClass(t.r_multiple))}
                >
                  {t.r_multiple != null ? fmtNumber(t.r_multiple, 2) : "—"}
                </TableCell>
                <TableCell
                  className={cn("text-right", pnlColorClass(t.pnl_pct))}
                >
                  {fmtPct(t.pnl_pct, 2, true)}
                </TableCell>
                <TableCell>
                  <Badge variant={win ? "bullish" : "bearish"}>
                    {win ? "WIN" : "LOSS"}
                  </Badge>
                </TableCell>
                <TableCell className="font-sans text-muted-foreground text-[11px]">
                  {t.exit_reason ?? "—"}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {trades.length > limit ? (
        <div className="text-muted-foreground border-border border-t px-2 py-1.5 font-mono text-[10px] tracking-wider uppercase">
          {trades.length - limit} more trades not shown
        </div>
      ) : null}
    </div>
  );
}
