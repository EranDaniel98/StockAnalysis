"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChevronLeft, CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { use, useMemo } from "react";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
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
import { api, type FactorBacktestDetail } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { CHART_AXIS, CHART_GRID, CHART_TOKEN } from "@/lib/chart-tokens";
import { fmtNumber, fmtPct, fmtUSD, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

type Params = { params: Promise<{ id: string }> };

export default function FactorBacktestDetailPage({ params }: Params) {
  const { id } = use(params);
  const { data, isLoading, error } = useQuery({
    queryKey: qk.factorBacktests.detail(id),
    queryFn: () => api.factorBacktests.get(id),
  });

  return (
    <>
      <PageHeader
        title={data ? data.slug : isLoading ? "Loading…" : "Backtest"}
        description={
          data
            ? `${data.strategy} · ${data.universe_label ?? "—"} · ${data.window_start ?? "?"} → ${data.window_end ?? "?"}`
            : "Factor backtest detail"
        }
        actions={
          <Link
            href="/backtests"
            className="text-sm text-primary hover:underline inline-flex items-center gap-1"
          >
            <ChevronLeft className="h-3 w-3" />
            Back to runs
          </Link>
        }
      />

      {error ? <ErrorState error={error} /> : null}
      {isLoading || !data ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
          <Skeleton className="h-80 w-full" />
        </div>
      ) : (
        <DetailBody data={data} />
      )}
    </>
  );
}

function DetailBody({ data }: { data: FactorBacktestDetail }) {
  return (
    <>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="α vs SPY"
          tooltip="alpha_vs_spy_pct from the run JSON. Strategy total return minus SPY total return over the same window."
          value={
            data.alpha_vs_spy_pct == null ? (
              "—"
            ) : (
              <span
                className={cn(
                  "font-mono",
                  pnlColorClass(data.alpha_vs_spy_pct),
                )}
              >
                {fmtPct(data.alpha_vs_spy_pct, 2, true)}
              </span>
            )
          }
          sub={
            data.spy_total_return_pct != null && data.total_return_pct != null
              ? `${fmtPct(data.total_return_pct, 1, true)} vs ${fmtPct(data.spy_total_return_pct, 1, true)}`
              : undefined
          }
          subTone="muted"
        />
        <ScoreboardTile
          label="OOS Sharpe"
          value={
            data.ann_sharpe == null ? "—" : (
              <span className={cn("font-mono", pnlColorClass(data.ann_sharpe))}>
                {fmtNumber(data.ann_sharpe, 2)}
              </span>
            )
          }
          sub={
            data.spy_ann_sharpe != null
              ? `SPY ${fmtNumber(data.spy_ann_sharpe, 2)}`
              : undefined
          }
          subTone="muted"
        />
        <ScoreboardTile
          label="Max DD"
          value={
            data.max_drawdown_pct == null ? "—" : (
              <span className="font-mono text-bearish">
                {fmtPct(data.max_drawdown_pct, 1)}
              </span>
            )
          }
          sub={
            data.cagr_pct != null
              ? `CAGR ${fmtPct(data.cagr_pct, 1, true)}`
              : undefined
          }
          subTone="muted"
        />
        <ScoreboardTile
          label="Walk-forward"
          tooltip="walk_forward.passed gate from the run JSON. Pass = every fold cleared the script's Sharpe threshold."
          value={<WfBadgeBig passed={data.wf_passed} />}
          sub={
            data.wf_mean_sharpe != null && data.wf_min_sharpe != null
              ? `mean ${fmtNumber(data.wf_mean_sharpe, 2)} · min ${fmtNumber(data.wf_min_sharpe, 2)} · ${data.n_folds ?? 0} folds`
              : undefined
          }
          subTone="muted"
        />
      </div>

      {/* Parameters + walk-forward folds, side-by-side */}
      <div className="grid gap-4 mt-4 lg:grid-cols-2">
        <ParametersCard data={data} />
        <WalkForwardCard data={data} />
      </div>

      <EquityCurveCard data={data} />

      <RebalanceLogCard data={data} />

      <TradesSampleCard data={data} />
    </>
  );
}

// ─── Parameters ────────────────────────────────────────────────────────────

function ParametersCard({ data }: { data: FactorBacktestDetail }) {
  const entries = useMemo(
    () => Object.entries(data.parameters ?? {}),
    [data.parameters],
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Parameters</CardTitle>
        <CardDescription className="text-[11px]">
          From the run JSON&apos;s <code>parameters</code> object.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-xs text-muted-foreground">No parameters recorded.</p>
        ) : (
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 font-mono text-xs">
            {entries.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground truncate">{k}</dt>
                <dd className="tabular-nums truncate">{formatParam(v)}</dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function formatParam(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4);
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

// ─── Walk-forward folds ────────────────────────────────────────────────────

function WalkForwardCard({ data }: { data: FactorBacktestDetail }) {
  const folds = data.walk_forward_folds ?? [];
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-sm">Walk-forward folds</CardTitle>
          <WfBadgeBig passed={data.wf_passed} />
        </div>
        <CardDescription className="text-[11px]">
          Per-fold OOS Sharpe + return. The gate is a min-Sharpe threshold
          enforced by run_factor_backtest.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {folds.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No fold data recorded.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">#</TableHead>
                <TableHead className="text-right">Days</TableHead>
                <TableHead className="text-right">Return</TableHead>
                <TableHead className="text-right">Sharpe</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {folds.map((f) => (
                <TableRow key={f.fold} mono>
                  <TableCell className="text-muted-foreground">{f.fold}</TableCell>
                  <TableCell className="text-right">{f.n_days ?? "—"}</TableCell>
                  <TableCell
                    className={cn("text-right", pnlColorClass(f.return_pct))}
                  >
                    {fmtPct(f.return_pct, 2, true)}
                  </TableCell>
                  <TableCell
                    className={cn("text-right", pnlColorClass(f.sharpe))}
                  >
                    {fmtNumber(f.sharpe, 2)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function WfBadgeBig({ passed }: { passed: boolean | null | undefined }) {
  if (passed == null) {
    return (
      <Badge variant="outline" className="font-mono text-[10px] tracking-wider uppercase opacity-50">
        —
      </Badge>
    );
  }
  return passed ? (
    <Badge variant="bullish" className="font-mono text-[10px] tracking-wider uppercase gap-1">
      <CheckCircle2 className="h-3 w-3" />
      Passed
    </Badge>
  ) : (
    <Badge variant="bearish" className="font-mono text-[10px] tracking-wider uppercase gap-1">
      <XCircle className="h-3 w-3" />
      Failed
    </Badge>
  );
}

// ─── Equity curve ──────────────────────────────────────────────────────────

function EquityCurveCard({ data }: { data: FactorBacktestDetail }) {
  // Merge strategy + interpolated SPY into one chart series keyed by date.
  const merged = useMemo(() => {
    const eqByDate = new Map<string, number>();
    for (const [d, v] of data.equity_curve ?? []) {
      eqByDate.set(d, v);
    }
    const spyByDate = new Map<string, number>();
    for (const [d, v] of data.spy_equity_curve ?? []) {
      spyByDate.set(d, v);
    }
    const dates = Array.from(new Set([...eqByDate.keys(), ...spyByDate.keys()]))
      .sort();
    return dates.map((d) => ({
      date: d,
      timestamp: new Date(d).getTime() / 1000,
      equity: eqByDate.get(d) ?? null,
      spy: spyByDate.get(d) ?? null,
    }));
  }, [data]);

  const start = merged[0];
  const end = merged[merged.length - 1];
  const showSpy = (data.spy_equity_curve ?? []).length > 0;

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle className="text-sm">Equity curve</CardTitle>
        <CardDescription className="text-[11px] flex flex-wrap gap-3">
          {start && end ? (
            <>
              <span>{start.date} → {end.date}</span>
              <span>
                strategy{" "}
                <span className={cn(pnlColorClass(
                  end.equity != null && start.equity ? end.equity - start.equity : 0,
                ))}>
                  {fmtUSD((end.equity ?? 0) - (start.equity ?? 0))}
                </span>
              </span>
              {showSpy && start.spy != null && end.spy != null ? (
                <span className="text-muted-foreground">
                  SPY synthetic line is linear-interpolated from total return
                </span>
              ) : null}
            </>
          ) : "—"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={merged}
              margin={{ top: 8, right: 16, bottom: 0, left: 8 }}
            >
              <CartesianGrid
                stroke={CHART_GRID}
                strokeOpacity={0.4}
                strokeDasharray="2 4"
                vertical={false}
              />
              <XAxis
                dataKey="timestamp"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(v) =>
                  new Date(Number(v) * 1000).toLocaleDateString(undefined, {
                    year: "2-digit",
                    month: "short",
                  })
                }
                stroke={CHART_AXIS}
                tick={{
                  fill: CHART_AXIS,
                  fontFamily: "var(--font-geist-mono)",
                  fontSize: 10,
                }}
                tickLine={false}
                axisLine={{ stroke: CHART_GRID, strokeOpacity: 0.6 }}
                minTickGap={48}
              />
              <YAxis
                orientation="right"
                stroke={CHART_AXIS}
                tick={{
                  fill: CHART_AXIS,
                  fontFamily: "var(--font-geist-mono)",
                  fontSize: 10,
                }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) => fmtUSD(v as number, true)}
                width={64}
                domain={["auto", "auto"]}
              />
              <Tooltip content={<EquityTooltip showSpy={showSpy} />} cursor={{ stroke: CHART_GRID }} />
              {showSpy ? (
                <Legend
                  verticalAlign="top"
                  height={20}
                  wrapperStyle={{
                    fontFamily: "var(--font-geist-mono)",
                    fontSize: 10,
                    color: CHART_AXIS,
                  }}
                  iconType="line"
                />
              ) : null}
              {showSpy ? (
                <Area
                  type="monotone"
                  dataKey="spy"
                  name="SPY (synthetic)"
                  stroke={CHART_AXIS}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  fill="transparent"
                  isAnimationActive={false}
                  dot={false}
                  activeDot={false}
                  connectNulls
                />
              ) : null}
              <Area
                type="monotone"
                dataKey="equity"
                name="Strategy"
                stroke={CHART_TOKEN.primary}
                strokeWidth={1.5}
                fill={CHART_TOKEN.primary}
                fillOpacity={0.15}
                isAnimationActive={false}
                dot={false}
                activeDot={{ r: 3, fill: CHART_TOKEN.primary, stroke: "none" }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

function EquityTooltip({
  active, payload, showSpy,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: { date: string; equity: number | null; spy: number | null } }>;
  showSpy: boolean;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const alpha =
    row.equity != null && row.spy != null ? row.equity - row.spy : null;
  return (
    <div className="bg-card border border-border px-2.5 py-1.5 font-mono text-[11px] leading-tight">
      <div className="text-muted-foreground tracking-wider uppercase text-[10px]">
        {row.date}
      </div>
      <div className="tabular-nums text-foreground">
        Strategy {row.equity != null ? fmtUSD(row.equity) : "—"}
      </div>
      {showSpy ? (
        <>
          <div className="tabular-nums text-muted-foreground">
            SPY {row.spy != null ? fmtUSD(row.spy) : "—"}
          </div>
          {alpha != null ? (
            <div className={cn("tabular-nums", pnlColorClass(alpha))}>
              α {fmtUSD(alpha)}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

// ─── Rebalance log ─────────────────────────────────────────────────────────

function RebalanceLogCard({ data }: { data: FactorBacktestDetail }) {
  // Hooks must run before any conditional return. Memoize both the
  // safe list and its derived key set; bail on empty after.
  const log = useMemo(() => data.rebalance_log ?? [], [data.rebalance_log]);
  const allKeys = useMemo(() => {
    const seen = new Set<string>();
    for (const row of log) {
      if (row && typeof row === "object") {
        for (const k of Object.keys(row)) seen.add(k);
      }
    }
    return Array.from(seen);
  }, [log]);
  if (log.length === 0) return null;
  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle className="text-sm">Rebalance log</CardTitle>
        <CardDescription className="text-[11px]">
          {log.length} rebalance{log.length === 1 ? "" : "s"} over the window.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              {allKeys.map((k) => (
                <TableHead key={k} className="text-[10px] font-mono uppercase tracking-wider">
                  {k}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {log.map((row, i) => (
              <TableRow key={i} mono>
                {allKeys.map((k) => (
                  <TableCell key={k} className="text-[11px]">
                    {formatParam((row as Record<string, unknown>)[k])}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

// ─── Trades sample ─────────────────────────────────────────────────────────

function TradesSampleCard({ data }: { data: FactorBacktestDetail }) {
  // Hooks-before-return order, same pattern as RebalanceLogCard.
  const trades = useMemo(
    () => data.trades_sample ?? [],
    [data.trades_sample],
  );
  const allKeys = useMemo(() => {
    const seen = new Set<string>();
    for (const row of trades) {
      if (row && typeof row === "object") {
        for (const k of Object.keys(row)) seen.add(k);
      }
    }
    return Array.from(seen);
  }, [trades]);
  if (trades.length === 0) return null;
  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle className="text-sm">Trades sample</CardTitle>
        <CardDescription className="text-[11px]">
          First {trades.length} trades from the run. Full trade list is in the
          raw JSON.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="max-h-96 overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                {allKeys.map((k) => (
                  <TableHead key={k} className="text-[10px] font-mono uppercase tracking-wider">
                    {k}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {trades.slice(0, 50).map((row, i) => (
                <TableRow key={i} mono>
                  {allKeys.map((k) => (
                    <TableCell key={k} className="text-[11px] tabular-nums">
                      {formatParam((row as Record<string, unknown>)[k])}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}
