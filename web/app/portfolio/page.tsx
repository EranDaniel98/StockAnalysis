"use client";

import { useQuery } from "@tanstack/react-query";
import { Radio, RefreshCw } from "lucide-react";
import { useState } from "react";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import {
  api,
  type EquityPoint,
  type PortfolioHistory,
  type Position,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { useLivePrices, type LivePriceMap } from "@/lib/api/use-live-prices";
import {
  CHART_AXIS,
  CHART_GRID,
  CHART_TOKEN,
} from "@/lib/chart-tokens";
import { fmtNumber, fmtPct, fmtUSD, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Local tone helper bound to the new bullish/bearish tokens. */
function toneClass(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "text-foreground";
  if (n > 0) return "text-bullish";
  if (n < 0) return "text-bearish";
  return "text-muted-foreground";
}

function toneFor(
  n: number | null | undefined,
): "bullish" | "bearish" | "neutral" | "muted" {
  if (n === null || n === undefined || Number.isNaN(n)) return "muted";
  if (n > 0) return "bullish";
  if (n < 0) return "bearish";
  return "neutral";
}

function applyLivePrice(p: Position, live: LivePriceMap): Position {
  const tick = live[p.ticker];
  if (!tick || !p.shares) return p;
  const market_value = tick.price * p.shares;
  const cost_basis = p.avg_price * p.shares;
  const unrealized_pnl = market_value - cost_basis;
  const unrealized_pnl_pct = cost_basis > 0 ? (unrealized_pnl / cost_basis) * 100 : 0;
  return {
    ...p,
    current_price: tick.price,
    market_value,
    unrealized_pnl,
    unrealized_pnl_pct,
  };
}

// ─── Equity curve config ──────────────────────────────────────────────────────

type Period = "1D" | "1W" | "1M" | "3M" | "6M" | "1A";
type Timeframe = "1Min" | "5Min" | "15Min" | "1H" | "1D";

const PERIODS: ReadonlyArray<Period> = ["1D", "1W", "1M", "3M", "6M", "1A"];

// Alpaca rejects mismatched (period, timeframe) combos. Lock the bar size
// per window so the user never has to think about it.
const PERIOD_TIMEFRAME: Record<Period, Timeframe> = {
  "1D": "5Min",
  "1W": "1H",
  "1M": "1H",
  "3M": "1D",
  "6M": "1D",
  "1A": "1D",
};

const INTRADAY_TIME_FMT = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const DAILY_DATE_FMT = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "2-digit",
});

const TOOLTIP_FULL_FMT = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

function isIntraday(tf: Timeframe): boolean {
  return tf === "1Min" || tf === "5Min" || tf === "15Min" || tf === "1H";
}

export default function PortfolioPage() {
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: qk.portfolio.status(),
    queryFn: () => api.portfolio.status(),
    refetchInterval: 60_000,
  });

  const symbols = data?.positions.map((p) => p.ticker) ?? [];
  const { prices, connected, error: liveError } = useLivePrices(symbols);

  const livePositions = (data?.positions ?? []).map((p) => applyLivePrice(p, prices));
  const liveLongMarketValue = livePositions.reduce(
    (sum, p) => sum + (p.market_value ?? 0),
    0,
  );
  const liveCostBasis = livePositions.reduce(
    (sum, p) => sum + p.avg_price * p.shares,
    0,
  );
  const liveUnrealizedPnl = liveLongMarketValue - liveCostBasis;
  const liveUnrealizedPnlPct =
    liveCostBasis > 0 ? (liveUnrealizedPnl / liveCostBasis) * 100 : 0;
  // Total Equity must mirror Alpaca's dashboard exactly — `equity` is the
  // authoritative server-side value (cash + market value − short value +
  // any margin/accruals). Recomputing it client-side from cash +
  // long_market_value drops shorts, margin, and pending settlements and
  // drifts visibly from Alpaca.
  const reportedEquity = data?.account.equity ?? null;

  const [period, setPeriod] = useState<Period>("1M");
  const timeframe = PERIOD_TIMEFRAME[period];

  return (
    <>
      <PageHeader
        title="Portfolio"
        description="Live Alpaca paper account. Position prices stream from Alpaca's IEX feed."
        actions={
          <div className="flex items-center gap-2">
            <Badge
              variant={connected ? "bullish" : "neutral"}
              className="gap-1.5"
              title={liveError ?? (connected ? "Streaming" : "Connecting…")}
            >
              <Radio
                className={`h-3 w-3 ${connected ? "animate-pulse" : "opacity-50"}`}
              />
              {connected ? "LIVE" : "OFFLINE"}
            </Badge>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              disabled={isFetching}
            >
              <RefreshCw
                className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`}
              />
              Refresh
            </Button>
          </div>
        }
      />

      {error ? <ErrorState error={error} /> : null}

      {/* Bloomberg scoreboard strip: 4 tiles. */}
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="Total Equity"
          value={fmtUSD(reportedEquity)}
          sub={
            data
              ? `${fmtUSD(data.account.portfolio_value, true)} portfolio value`
              : undefined
          }
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Unrealized P&L"
          value={
            <span className={cn(toneClass(liveUnrealizedPnl))}>
              {fmtUSD(liveUnrealizedPnl)}
            </span>
          }
          sub={
            data
              ? `${liveUnrealizedPnlPct >= 0 ? "+" : ""}${liveUnrealizedPnlPct.toFixed(2)}% on ${fmtUSD(liveCostBasis)} cost`
              : undefined
          }
          subTone={toneFor(liveUnrealizedPnl)}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Open Positions"
          value={data ? String(data.n_positions) : "—"}
          sub={
            data
              ? `${fmtUSD(liveLongMarketValue, true)} long market value`
              : undefined
          }
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Cash / Buying Power"
          tooltip="Cash = settled dollars available for new positions. Buying power can exceed cash on a margin account (typically 2x cash for day-trading paper accounts). Use cash, not buying power, for sizing if you want to stay unleveraged."
          value={fmtUSD(data?.account.cash)}
          sub={
            data ? `${fmtUSD(data.account.buying_power)} buying power` : undefined
          }
          subTone="muted"
          isLoading={isLoading}
        />
      </div>

      <EquityCurveCard period={period} setPeriod={setPeriod} timeframe={timeframe} />

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Positions</CardTitle>
          <CardDescription>
            {data
              ? `${data.n_positions} open ${data.n_positions === 1 ? "position" : "positions"} ${connected ? "· streaming" : "· last poll"}`
              : "Loading positions…"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2 py-1">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-7 w-full" />
              ))}
            </div>
          ) : !data || livePositions.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-xs">
              No open positions.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead className="text-right">Shares</TableHead>
                  <TableHead className="text-right">Avg Cost</TableHead>
                  <TableHead className="text-right">Mark</TableHead>
                  <TableHead className="text-right">Mkt Value</TableHead>
                  <TableHead className="text-right">Unrl P&amp;L $</TableHead>
                  <TableHead className="text-right">Unrl P&amp;L %</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {livePositions.map((p) => {
                  const isLive = prices[p.ticker] !== undefined;
                  return (
                    <TableRow key={p.ticker} mono>
                      <TableCell>
                        <span className="font-mono text-foreground">
                          {p.ticker}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        {fmtNumber(p.shares, 0)}
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground">
                        {fmtUSD(p.avg_price)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right",
                          isLive ? "text-bullish" : "text-foreground",
                        )}
                        title={isLive ? "Live tick" : "Last poll"}
                      >
                        {fmtUSD(p.current_price)}
                      </TableCell>
                      <TableCell className="text-right">
                        {fmtUSD(p.market_value)}
                      </TableCell>
                      <TableCell
                        className={cn("text-right", toneClass(p.unrealized_pnl))}
                      >
                        {fmtUSD(p.unrealized_pnl)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right",
                          toneClass(p.unrealized_pnl_pct),
                        )}
                      >
                        {fmtPct(p.unrealized_pnl_pct, 2, true)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}

// ─── Equity curve card ────────────────────────────────────────────────────────

function EquityCurveCard({
  period,
  setPeriod,
  timeframe,
}: {
  period: Period;
  setPeriod: (p: Period) => void;
  timeframe: Timeframe;
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.portfolio.history({ period, timeframe }),
    queryFn: () => api.portfolio.history({ period, timeframe }),
  });

  const points = data?.points ?? [];
  const base = data?.base_value ?? null;
  const latestEquity = points.length > 0 ? points[points.length - 1].equity : null;
  const sinceStart =
    latestEquity != null && base != null ? latestEquity - base : null;

  const descriptionText = data
    ? `${period} window · ${timeframe} bars · `
    : "Loading…";

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
          Equity curve
        </CardTitle>
        <CardDescription className="text-muted-foreground font-mono text-xs">
          {data ? (
            <>
              {descriptionText}
              <span className={cn(pnlColorClass(sinceStart))}>
                {fmtUSD(sinceStart)}
              </span>
              {" since start"}
            </>
          ) : (
            "Loading…"
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-3 flex items-center gap-1">
          {PERIODS.map((p) => {
            const active = p === period;
            return (
              <button
                key={p}
                type="button"
                onClick={() => setPeriod(p)}
                className={cn(
                  "font-mono text-[10px] uppercase tracking-wider px-2 py-1 border rounded transition-colors",
                  active
                    ? "text-foreground bg-muted/40 border-border"
                    : "text-muted-foreground hover:text-foreground border-transparent",
                )}
              >
                {p}
              </button>
            );
          })}
        </div>
        {error ? (
          <ErrorState error={error} />
        ) : isLoading || !data ? (
          <Skeleton className="h-[320px] w-full" />
        ) : points.length === 0 ? (
          <p className="text-muted-foreground py-12 text-center text-xs font-mono">
            No equity history in this window.
          </p>
        ) : (
          <div className="h-[320px]">
            <EquityCurveChart history={data} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function EquityCurveChart({ history }: { history: PortfolioHistory }) {
  const timeframe = history.timeframe as Timeframe;
  const intraday = isIntraday(timeframe);
  const fmt = intraday ? INTRADAY_TIME_FMT : DAILY_DATE_FMT;

  const tickFormatter = (v: number | string) => {
    // API gives epoch seconds — Date wants ms.
    const dt = new Date(Number(v) * 1000);
    return Number.isNaN(dt.getTime()) ? String(v) : fmt.format(dt);
  };

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart
        data={history.points as EquityPoint[]}
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
        <Tooltip content={<EquityTooltip />} cursor={{ stroke: CHART_GRID }} />
        <Area
          type="monotone"
          dataKey="equity"
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

// Recharts hands the tooltip raw payload — format the date, tone the P&L
// against the bullish/bearish tokens, render the structured panel here.
function EquityTooltip(props: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: EquityPoint }>;
}) {
  const { active, payload } = props;
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const dt = new Date(row.timestamp * 1000);
  const dateLabel = Number.isNaN(dt.getTime())
    ? String(row.timestamp)
    : TOOLTIP_FULL_FMT.format(dt);
  return (
    <div className="bg-card border border-border px-2.5 py-1.5 font-mono text-[11px] leading-tight">
      <div className="text-muted-foreground tracking-wider uppercase text-[10px]">
        {dateLabel}
      </div>
      <div className="tabular-nums text-foreground">
        Equity {fmtUSD(row.equity)}
      </div>
      <div className={cn("tabular-nums", pnlColorClass(row.profit_loss))}>
        P&amp;L {fmtUSD(row.profit_loss)} ({fmtPct(row.profit_loss_pct, 2, true)})
      </div>
    </div>
  );
}
