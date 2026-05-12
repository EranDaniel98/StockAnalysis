"use client";

import { useQueries } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Suspense } from "react";

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
import { fmtNumber, fmtPct, pnlColorClass } from "@/lib/format";

const PALETTE = [
  "#10b981", // emerald
  "#3b82f6", // blue
  "#f59e0b", // amber
  "#ef4444", // red
  "#a78bfa", // violet
  "#06b6d4", // cyan
];

type EquityPoint = { date?: string; equity?: number };

export default function CompareBacktestsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <Compare />
    </Suspense>
  );
}

function Compare() {
  const search = useSearchParams();
  const idsParam = search.get("ids") ?? "";
  const ids = idsParam
    .split(",")
    .map((s) => Number.parseInt(s, 10))
    .filter((n) => Number.isFinite(n) && n > 0);

  const queries = useQueries({
    queries: ids.map((id) => ({
      queryKey: qk.backtests.detail(id),
      queryFn: () => api.backtests.get(id),
    })),
  });

  if (ids.length === 0) {
    return (
      <>
        <PageHeader title="Compare backtests" />
        <ErrorState
          title="No backtests selected"
          error={
            new Error(
              "Append ?ids=1,2,3 to the URL to compare specific backtest runs.",
            )
          }
        />
      </>
    );
  }

  const loading = queries.some((q) => q.isLoading);
  const failed = queries.find((q) => q.error);

  if (loading) {
    return (
      <>
        <PageHeader title="Compare backtests" description={`Loading ${ids.length} runs…`} />
        <Skeleton className="h-96 w-full" />
      </>
    );
  }

  if (failed) {
    return (
      <>
        <PageHeader title="Compare backtests" />
        <ErrorState error={failed.error} />
      </>
    );
  }

  const runs = queries
    .map((q, i) => ({ id: ids[i], data: q.data, color: PALETTE[i % PALETTE.length] }))
    .filter((r) => !!r.data);

  // Merge equity curves by date for the overlay chart.
  const dateIndex = new Map<string, Record<string, number | string>>();
  for (const r of runs) {
    const equity = (r.data?.result?.equity_curve ?? []) as EquityPoint[];
    for (const p of equity) {
      if (!p.date || p.equity == null) continue;
      const row = dateIndex.get(p.date) ?? { date: p.date };
      row[`run_${r.id}`] = p.equity;
      dateIndex.set(p.date, row);
    }
  }
  const chartData = [...dateIndex.values()].sort((a, b) =>
    String(a.date).localeCompare(String(b.date)),
  );

  return (
    <>
      <PageHeader
        title="Compare backtests"
        description={`${runs.length} runs · overlay equity curves & side-by-side OOS metrics.`}
      />

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Equity curves (overlay)</CardTitle>
          <CardDescription>
            All runs share the X axis. Normalize manually by setting equal
            starting cash in each backtest.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis
                  dataKey="date"
                  tickFormatter={(d) => new Date(d).toLocaleDateString()}
                  fontSize={11}
                />
                <YAxis fontSize={11} />
                <Tooltip
                  contentStyle={{
                    background: "hsl(var(--popover))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  labelFormatter={(d) =>
                    new Date(d as string).toLocaleDateString()
                  }
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {runs.map((r) => (
                  <Line
                    key={r.id}
                    type="monotone"
                    dataKey={`run_${r.id}`}
                    name={`#${r.id} ${r.data?.strategy}`}
                    stroke={r.color}
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Side-by-side metrics</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run</TableHead>
                <TableHead>Strategy</TableHead>
                <TableHead>Window</TableHead>
                <TableHead className="text-right">Trades</TableHead>
                <TableHead className="text-right">OOS Sharpe</TableHead>
                <TableHead className="text-right">OOS Return</TableHead>
                <TableHead className="text-right">OOS Max DD</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((r) => {
                const result = r.data!.result as Record<string, unknown>;
                const oos = (result.out_of_sample ?? {}) as Record<
                  string,
                  number | undefined
                >;
                const trades = (result.trades ?? []) as unknown[];
                return (
                  <TableRow key={r.id}>
                    <TableCell>
                      <Badge variant="outline" style={{ borderColor: r.color }}>
                        #{r.id}
                      </Badge>
                    </TableCell>
                    <TableCell>{r.data!.strategy}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {new Date(r.data!.window_start).toLocaleDateString()} →{" "}
                      {new Date(r.data!.window_end).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {trades.length}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${pnlColorClass(oos.sharpe)}`}
                    >
                      {fmtNumber(oos.sharpe, 2)}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${pnlColorClass(oos.total_return_pct)}`}
                    >
                      {fmtPct(oos.total_return_pct, 1, true)}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${pnlColorClass(-(oos.max_drawdown_pct ?? 0))}`}
                    >
                      {fmtPct(oos.max_drawdown_pct, 1)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}
