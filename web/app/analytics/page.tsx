"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
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
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type TradeAnalytics } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import {
  CHART_AXIS,
  CHART_GRID,
  CHART_TOKEN,
} from "@/lib/chart-tokens";
import { fmtPct, fmtUSD, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

const AXIS_DATE_FMT = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "2-digit",
});

const TOOLTIP_DATE_FMT = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
});

function fmtDateOnly(d: string): string {
  const dt = new Date(d);
  return Number.isNaN(dt.getTime()) ? d : TOOLTIP_DATE_FMT.format(dt);
}

function tileToneFromExpectancy(
  v: number | null | undefined,
): "bullish" | "bearish" | "muted" {
  if (v == null || Number.isNaN(v)) return "muted";
  if (v > 0) return "bullish";
  if (v < 0) return "bearish";
  return "muted";
}

function winRateValueClass(rate: number): string {
  if (rate >= 0.5) return "text-bullish";
  if (rate < 0.4) return "text-bearish";
  return "text-foreground";
}

function profitFactorValueClass(pf: number | null | undefined): string {
  if (pf == null) return "text-foreground";
  if (pf >= 1.5) return "text-bullish";
  if (pf < 1.0) return "text-bearish";
  return "text-foreground";
}

export default function AnalyticsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.analytics.tradesSummary(),
    queryFn: () => api.analytics.tradesSummary(),
  });

  if (isLoading || !data) {
    return (
      <>
        <PageHeader
          title="Trade analytics"
          description="Aggregate stats over every closed paper trade. Sourced from the paper trade journal."
        />
        {error ? <ErrorState error={error} /> : null}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
        <Skeleton className="h-72 w-full mt-4" />
      </>
    );
  }

  return <AnalyticsBody data={data} error={error} />;
}

function AnalyticsBody({
  data,
  error,
}: {
  data: TradeAnalytics;
  error: unknown;
}) {
  const headline = data.headline;
  const notes = data.notes ?? [];
  const cumulative = data.cumulative_pnl ?? [];
  const byStrategy = data.by_strategy ?? [];
  const byExitReason = data.by_exit_reason ?? [];
  const holdBuckets = data.hold_time_distribution ?? [];
  const winners = data.top_winners ?? [];
  const losers = data.top_losers ?? [];

  if (headline.n_trades === 0) {
    return (
      <>
        <PageHeader
          title="Trade analytics"
          description="Aggregate stats over every closed paper trade. Sourced from the paper trade journal."
        />
        {error ? <ErrorState error={error} /> : null}
        <p className="text-muted-foreground py-12 text-center text-sm font-mono">
          No closed paper trades yet — run paper trade + evaluate first.
        </p>
      </>
    );
  }

  const winRatePct = headline.win_rate * 100;

  const maxBucketCount = holdBuckets.reduce(
    (acc, b) => (b.n_trades > acc ? b.n_trades : acc),
    0,
  );

  return (
    <>
      <PageHeader
        title="Trade analytics"
        description="Aggregate stats over every closed paper trade. Sourced from the paper trade journal."
      />

      {error ? <ErrorState error={error} /> : null}

      {notes.length > 0 ? (
        <div className="mb-4 text-xs font-mono text-muted-foreground tracking-wider uppercase">
          {notes.join(" · ")}
        </div>
      ) : null}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <ScoreboardTile
          label="Closed trades"
          tooltip="Every paper trade that's exited (target hit, stop hit, or manually closed). Sub: W/L/BE breakdown — winners, losers, breakeven."
          value={String(headline.n_trades)}
          sub={`${headline.n_winners}W / ${headline.n_losers}L / ${headline.n_breakeven}BE`}
          subTone="muted"
        />
        <ScoreboardTile
          label="Win rate"
          tooltip="Fraction of closed trades with positive P&L. Above 50% is good, but on its own it's misleading — a 90% win rate with tiny wins and one huge loss is a losing strategy. Read alongside Profit Factor + Expectancy."
          value={
            <span className={cn(winRateValueClass(headline.win_rate))}>
              {winRatePct.toFixed(1)}%
            </span>
          }
          sub={`expectancy: ${fmtPct(headline.expectancy_pct, 2, true)}`}
          subTone={tileToneFromExpectancy(headline.expectancy_pct)}
        />
        <ScoreboardTile
          label="Total P&L"
          tooltip="Sum of realized P&L across every closed trade. Sub-value is the mean pnl_pct per trade — i.e. average return on each individual position, not the portfolio."
          value={
            <span className={cn(pnlColorClass(headline.total_pnl))}>
              {fmtUSD(headline.total_pnl)}
            </span>
          }
          sub={`${fmtPct(headline.avg_pnl_pct, 2, true)} avg`}
          subTone={tileToneFromExpectancy(headline.avg_pnl_pct)}
        />
        <ScoreboardTile
          label="Profit factor"
          tooltip="Sum of winning P&L divided by absolute sum of losing P&L. >1.0 = profitable. >2.0 = strong system. <1.0 = losing money. Sub-value: avg win % / avg loss %."
          value={
            <span className={cn(profitFactorValueClass(headline.profit_factor))}>
              {headline.profit_factor != null
                ? headline.profit_factor.toFixed(2)
                : "—"}
            </span>
          }
          sub={
            headline.avg_win_pct != null && headline.avg_loss_pct != null
              ? `${fmtPct(headline.avg_win_pct, 1, true)} / ${fmtPct(headline.avg_loss_pct, 1, true)}`
              : undefined
          }
          subTone="muted"
        />
      </div>

      <div className="mt-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
              Cumulative P&L
            </CardTitle>
            <CardDescription className="text-muted-foreground font-mono text-xs">
              {`${cumulative.length} day(s) with closures, ${fmtUSD(headline.total_pnl)} total`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {cumulative.length < 2 ? (
              <p className="text-muted-foreground py-12 text-center text-xs font-mono">
                Need at least 2 closing dates to draw the curve.
              </p>
            ) : (
              <div className="h-[280px]">
                <CumulativePnlChart points={cumulative} />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mt-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
              By strategy
            </CardTitle>
          </CardHeader>
          <CardContent className="px-0">
            {byStrategy.length === 0 ? (
              <p className="text-muted-foreground px-3 py-6 text-center text-xs font-mono">
                No strategy attribution yet.
              </p>
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                      Strategy
                    </th>
                    <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                      Trades
                    </th>
                    <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                      Avg %
                    </th>
                    <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                      Win %
                    </th>
                    <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                      Total P&L
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {byStrategy.map((s) => (
                    <tr
                      key={s.strategy}
                      className="font-mono tabular-nums text-xs border-b border-border last:border-b-0 hover:bg-muted/40"
                    >
                      <td className="text-left px-3 py-1.5 text-foreground">
                        {s.strategy}
                      </td>
                      <td className="text-right px-3 py-1.5 text-muted-foreground">
                        {s.n_trades}
                      </td>
                      <td className={cn("text-right px-3 py-1.5", pnlColorClass(s.avg_pnl_pct))}>
                        {fmtPct(s.avg_pnl_pct, 2, true)}
                      </td>
                      <td className="text-right px-3 py-1.5 text-muted-foreground">
                        {(s.win_rate * 100).toFixed(0)}%
                      </td>
                      <td className={cn("text-right px-3 py-1.5", pnlColorClass(s.total_pnl))}>
                        {fmtUSD(s.total_pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
              By exit reason
            </CardTitle>
          </CardHeader>
          <CardContent className="px-0">
            {byExitReason.length === 0 ? (
              <p className="text-muted-foreground px-3 py-6 text-center text-xs font-mono">
                No exits recorded yet.
              </p>
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                      Reason
                    </th>
                    <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                      Trades
                    </th>
                    <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                      Avg %
                    </th>
                    <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                      Win %
                    </th>
                    <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                      Total P&L
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {byExitReason.map((r) => (
                    <tr
                      key={r.reason}
                      className="font-mono tabular-nums text-xs border-b border-border last:border-b-0 hover:bg-muted/40"
                    >
                      <td className="text-left px-3 py-1.5 text-[10px] tracking-wider uppercase text-muted-foreground">
                        {r.reason}
                      </td>
                      <td className="text-right px-3 py-1.5 text-muted-foreground">
                        {r.n_trades}
                      </td>
                      <td className={cn("text-right px-3 py-1.5", pnlColorClass(r.avg_pnl_pct))}>
                        {fmtPct(r.avg_pnl_pct, 2, true)}
                      </td>
                      <td className="text-right px-3 py-1.5 text-muted-foreground">
                        {(r.win_rate * 100).toFixed(0)}%
                      </td>
                      <td className={cn("text-right px-3 py-1.5", pnlColorClass(r.total_pnl))}>
                        {fmtUSD(r.total_pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
              Hold-time distribution
            </CardTitle>
          </CardHeader>
          <CardContent>
            {holdBuckets.length === 0 ? (
              <p className="text-muted-foreground py-6 text-center text-xs font-mono">
                No hold-time data.
              </p>
            ) : (
              <div className="space-y-2">
                {holdBuckets.map((b) => {
                  const widthPct =
                    maxBucketCount > 0 ? (b.n_trades / maxBucketCount) * 100 : 0;
                  const barTone =
                    b.avg_pnl_pct != null && b.avg_pnl_pct > 0
                      ? "bg-bullish"
                      : b.avg_pnl_pct != null && b.avg_pnl_pct < 0
                        ? "bg-bearish"
                        : "bg-primary";
                  return (
                    <div key={b.label} className="flex items-center gap-3">
                      <span className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground w-16 shrink-0">
                        {b.label}
                      </span>
                      <div className="h-1.5 bg-muted/30 rounded-full overflow-hidden flex-1">
                        <div
                          style={{ width: `${widthPct}%` }}
                          className={cn("h-full", barTone)}
                        />
                      </div>
                      <span className="font-mono tabular-nums text-[11px] text-muted-foreground w-44 text-right shrink-0">
                        <span className="text-foreground">{b.n_trades}</span> trades ·{" "}
                        <span className={cn(pnlColorClass(b.avg_pnl_pct))}>
                          {fmtPct(b.avg_pnl_pct, 2, true)}
                        </span>{" "}
                        avg
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mt-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
              Top winners
            </CardTitle>
          </CardHeader>
          <CardContent className="px-0">
            <TickerTable rows={winners} tone="bullish" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
              Top losers
            </CardTitle>
          </CardHeader>
          <CardContent className="px-0">
            <TickerTable rows={losers} tone="bearish" />
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function TickerTable({
  rows,
  tone,
}: {
  rows: ReadonlyArray<{
    ticker: string;
    n_trades: number;
    total_pnl: number;
    avg_pnl_pct: number;
  }>;
  tone: "bullish" | "bearish";
}) {
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground px-3 py-6 text-center text-xs font-mono">
        No closed trades yet.
      </p>
    );
  }
  const pnlClass = tone === "bullish" ? "text-bullish" : "text-bearish";
  return (
    <table className="w-full">
      <thead>
        <tr className="border-b border-border">
          <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
            Ticker
          </th>
          <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
            Trades
          </th>
          <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
            Avg %
          </th>
          <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
            Total P&L
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr
            key={r.ticker}
            className="font-mono tabular-nums text-xs border-b border-border last:border-b-0 hover:bg-muted/40"
          >
            <td className="text-left px-3 py-1.5">
              <Link
                href={`/stocks/${encodeURIComponent(r.ticker)}`}
                className="text-primary hover:underline underline-offset-2"
                title="View trade plan"
              >
                {r.ticker}
              </Link>
            </td>
            <td className="text-right px-3 py-1.5 text-muted-foreground">
              {r.n_trades}
            </td>
            <td className={cn("text-right px-3 py-1.5", pnlColorClass(r.avg_pnl_pct))}>
              {fmtPct(r.avg_pnl_pct, 2, true)}
            </td>
            <td className={cn("text-right px-3 py-1.5", pnlClass)}>
              {fmtUSD(r.total_pnl)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

type CumPoint = { date: string; cumulative_pnl: number; n_trades: number };

function CumulativePnlChart({ points }: { points: ReadonlyArray<CumPoint> }) {
  const tickFormatter = (d: string | number) => {
    const dt = new Date(d as string);
    return Number.isNaN(dt.getTime()) ? String(d) : AXIS_DATE_FMT.format(dt);
  };
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={points as CumPoint[]} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
        <CartesianGrid
          stroke={CHART_GRID}
          strokeOpacity={0.4}
          strokeDasharray="2 4"
          vertical={false}
        />
        <XAxis
          dataKey="date"
          tickFormatter={tickFormatter}
          interval="preserveStartEnd"
          stroke={CHART_AXIS}
          tick={{
            fill: CHART_AXIS,
            fontFamily: "var(--font-geist-mono)",
            fontSize: 10,
          }}
          tickLine={false}
          axisLine={{ stroke: CHART_GRID, strokeOpacity: 0.6 }}
          minTickGap={32}
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
        <Tooltip content={<CumTooltip />} cursor={{ stroke: CHART_GRID }} />
        <Area
          type="monotone"
          dataKey="cumulative_pnl"
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
  );
}

// Custom Recharts tooltip — Recharts only passes raw payload, so the formatted
// surface (token-coloured P&L, date-only label, closure count) lives here.
function CumTooltip(props: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: CumPoint }>;
}) {
  const { active, payload } = props;
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  return (
    <div className="bg-card border border-border px-2.5 py-1.5 font-mono text-[11px] leading-tight">
      <div className="text-muted-foreground tracking-wider uppercase text-[10px]">
        {fmtDateOnly(row.date)}
      </div>
      <div className={cn("tabular-nums", pnlColorClass(row.cumulative_pnl))}>
        Cumulative {fmtUSD(row.cumulative_pnl)}
      </div>
      <div className="tabular-nums text-muted-foreground">
        {row.n_trades} closures
      </div>
    </div>
  );
}
