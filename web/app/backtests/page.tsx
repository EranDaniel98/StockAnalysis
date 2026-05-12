"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtDate, fmtNumber, fmtPct, pnlColorClass } from "@/lib/format";

export default function BacktestsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.backtests.list({ limit: 30 }),
    queryFn: () => api.backtests.list({ limit: 30 }),
  });

  return (
    <>
      <PageHeader
        title="Backtests"
        description="Walk-forward simulations. Triggering a new run is a long-running operation — best done from the CLI today."
      />

      <Card>
        <CardHeader>
          <CardTitle>Recent runs</CardTitle>
          <CardDescription>
            {data ? `${data.length} runs` : "Loading…"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error ? <ErrorState error={error} /> : null}

          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !data || data.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              No backtests yet. Run one from the CLI:{" "}
              <code className="bg-muted rounded px-1.5 py-0.5 text-xs">
                python -m src.main backtest --strategy swing_trading --years 3
              </code>
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Strategy</TableHead>
                  <TableHead>Universe</TableHead>
                  <TableHead>Window</TableHead>
                  <TableHead className="text-right">Trades</TableHead>
                  <TableHead className="text-right">OOS Sharpe</TableHead>
                  <TableHead className="text-right">OOS Return</TableHead>
                  <TableHead className="text-right">OOS Max DD</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((bt) => (
                  <TableRow key={bt.id}>
                    <TableCell className="text-muted-foreground text-xs">
                      {fmtDate(bt.created_at)}
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/backtests/${bt.id}`}
                        className="hover:underline"
                      >
                        <Badge variant="secondary">{bt.strategy}</Badge>
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {bt.universe_label}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {new Date(bt.window_start).toLocaleDateString()} →{" "}
                      {new Date(bt.window_end).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {bt.n_trades ?? "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtNumber(bt.oos_sharpe, 2)}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${pnlColorClass(bt.oos_total_return_pct)}`}
                    >
                      {fmtPct(bt.oos_total_return_pct, 1, true)}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${pnlColorClass(-(bt.oos_max_drawdown_pct ?? 0))}`}
                    >
                      {fmtPct(bt.oos_max_drawdown_pct, 1)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}
