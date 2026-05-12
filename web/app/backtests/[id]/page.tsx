"use client";

import { useQuery } from "@tanstack/react-query";
import { use } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
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

type EquityPoint = { date?: string; equity?: number; [k: string]: unknown };
type Trade = {
  ticker?: string;
  entry_date?: string;
  exit_date?: string;
  pnl_pct?: number;
  hold_days?: number;
  exit_reason?: string;
  [k: string]: unknown;
};

export default function BacktestDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: idParam } = use(params);
  const id = Number(idParam);

  const { data, isLoading, error } = useQuery({
    queryKey: qk.backtests.detail(id),
    queryFn: () => api.backtests.get(id),
    enabled: !Number.isNaN(id),
  });

  if (Number.isNaN(id)) {
    return <ErrorState error={new Error(`Invalid backtest id: ${idParam}`)} />;
  }

  return (
    <>
      <PageHeader
        title={data ? `Backtest #${data.id}` : "Backtest"}
        description={
          data
            ? `${data.strategy} · ${new Date(data.window_start).toLocaleDateString()} → ${new Date(data.window_end).toLocaleDateString()}`
            : "Loading…"
        }
      />

      {error ? <ErrorState error={error} /> : null}

      {isLoading || !data ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        <BacktestDetail result={data.result} />
      )}
    </>
  );
}

function BacktestDetail({ result }: { result: Record<string, unknown> }) {
  const oos = (result.out_of_sample ?? {}) as Record<string, number | undefined>;
  const inSample = (result.in_sample ?? {}) as Record<
    string,
    number | undefined
  >;
  const equity = (result.equity_curve ?? []) as EquityPoint[];
  const trades = (result.trades ?? []) as Trade[];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        <MetricCard
          label="OOS Sharpe"
          value={fmtNumber(oos.sharpe, 2)}
          accent={pnlColorClass(oos.sharpe)}
        />
        <MetricCard
          label="OOS total return"
          value={fmtPct(oos.total_return_pct, 1, true)}
          accent={pnlColorClass(oos.total_return_pct)}
        />
        <MetricCard
          label="OOS max DD"
          value={fmtPct(oos.max_drawdown_pct, 1)}
          accent={pnlColorClass(-(oos.max_drawdown_pct ?? 0))}
        />
        <MetricCard
          label="IS Sharpe"
          value={fmtNumber(inSample.sharpe, 2)}
          accent={pnlColorClass(inSample.sharpe)}
        />
      </div>

      {equity.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Equity curve</CardTitle>
            <CardDescription>
              {equity.length.toLocaleString()} weekly mark-to-market points.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={equity}>
                  <defs>
                    <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                      <stop
                        offset="5%"
                        stopColor="hsl(var(--primary))"
                        stopOpacity={0.5}
                      />
                      <stop
                        offset="95%"
                        stopColor="hsl(var(--primary))"
                        stopOpacity={0}
                      />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={(d) => new Date(d).toLocaleDateString()}
                    fontSize={11}
                    tick={{ fill: "currentColor", opacity: 0.6 }}
                  />
                  <YAxis
                    fontSize={11}
                    tick={{ fill: "currentColor", opacity: 0.6 }}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: 8,
                    }}
                    labelFormatter={(d) => new Date(d as string).toLocaleDateString()}
                  />
                  <Area
                    type="monotone"
                    dataKey="equity"
                    stroke="hsl(var(--primary))"
                    fillOpacity={1}
                    fill="url(#eq)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {trades.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Trades ({trades.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="max-h-[480px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Ticker</TableHead>
                    <TableHead>Entry</TableHead>
                    <TableHead>Exit</TableHead>
                    <TableHead className="text-right">P&amp;L %</TableHead>
                    <TableHead className="text-right">Hold (d)</TableHead>
                    <TableHead>Exit reason</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {trades.slice(0, 200).map((t, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-mono">{t.ticker}</TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {t.entry_date}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {t.exit_date}
                      </TableCell>
                      <TableCell
                        className={`text-right tabular-nums ${pnlColorClass(t.pnl_pct)}`}
                      >
                        {fmtPct(t.pnl_pct, 1, true)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {t.hold_days ?? "—"}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {t.exit_reason ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function MetricCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-semibold tabular-nums ${accent ?? ""}`}>
          {value}
        </div>
      </CardContent>
    </Card>
  );
}
