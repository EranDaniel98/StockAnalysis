"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
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
import { fmtNumber, fmtPct, pnlColorClass } from "@/lib/format";

export default function CalibrationPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "calibration"],
    queryFn: () => api.analytics.calibration(),
  });

  return (
    <>
      <PageHeader
        title="Score calibration"
        description="Do higher composite scores actually produce higher realized returns? Buckets the closed paper trades and reports per-band stats."
      />

      {error ? <ErrorState error={error} /> : null}

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : data ? (
        <div className="space-y-6">
          {data.notes && data.notes.length > 0 ? (
            <Card>
              <CardContent className="space-y-1 py-3 text-xs">
                {data.notes.map((n, i) => (
                  <p key={i} className="text-muted-foreground">
                    {n}
                  </p>
                ))}
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>Avg realized return by score band</CardTitle>
              <CardDescription>
                Bars colored emerald (positive) / red (negative). Calibrated
                models climb monotonically left → right.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.buckets}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                    <XAxis dataKey="label" fontSize={11} />
                    <YAxis
                      fontSize={11}
                      tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "hsl(var(--popover))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                      formatter={(value, name) => {
                        if (name === "avg_pnl_pct" && typeof value === "number")
                          return [`${value.toFixed(2)}%`, "Avg return"];
                        return [value, name];
                      }}
                    />
                    <Bar dataKey="avg_pnl_pct" radius={[4, 4, 0, 0]}>
                      {(data.buckets ?? []).map((b, i) => (
                        <Cell
                          key={i}
                          fill={
                            (b.avg_pnl_pct ?? 0) >= 0 ? "#10b981" : "#ef4444"
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Per-bucket detail</CardTitle>
              <CardDescription>
                {data.n_total_trades} total closed trades.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Score band</TableHead>
                    <TableHead className="text-right">N trades</TableHead>
                    <TableHead className="text-right">Avg P&amp;L %</TableHead>
                    <TableHead className="text-right">Median P&amp;L %</TableHead>
                    <TableHead className="text-right">Win rate</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data.buckets ?? []).map((b) => (
                    <TableRow key={b.label}>
                      <TableCell>{b.label}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {b.n_trades}
                      </TableCell>
                      <TableCell
                        className={`text-right tabular-nums ${pnlColorClass(b.avg_pnl_pct)}`}
                      >
                        {fmtPct(b.avg_pnl_pct, 2, true)}
                      </TableCell>
                      <TableCell
                        className={`text-right tabular-nums ${pnlColorClass(b.median_pnl_pct)}`}
                      >
                        {fmtPct(b.median_pnl_pct, 2, true)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {b.win_rate == null
                          ? "—"
                          : `${fmtNumber((b.win_rate ?? 0) * 100, 0)}%`}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </>
  );
}
