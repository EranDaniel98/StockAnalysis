"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ExternalLink, Radio, RefreshCw } from "lucide-react";
import { useState } from "react";
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

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { PaperVsSpyCard } from "@/components/paper-vs-spy-card";
import {
  BasketActionBadge,
  PositionStatusBadge,
} from "@/components/position-status-badge";
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
  type PositionRecommendation,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { useLivePrices, type LivePriceMap } from "@/lib/api/use-live-prices";
import {
  CHART_AXIS,
  CHART_GRID,
  CHART_TOKEN,
} from "@/lib/chart-tokens";
import type { PaperVsSpyFile } from "@/lib/factors/data";
import { fmtNumber, fmtPct, fmtUSD, pnlColorClass } from "@/lib/format";
import { useMounted } from "@/lib/use-mounted";
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

// Approximate calendar-day length of each Alpaca shorthand window. Used
// only for the "truncated" hint — exact match isn't required.
const PERIOD_TO_DAYS: Record<Period, number> = {
  "1D": 1, "1W": 7, "1M": 30, "3M": 90, "6M": 180, "1A": 365,
};
function periodToDays(p: Period): number {
  return PERIOD_TO_DAYS[p];
}

export default function PortfolioPage() {
  const mounted = useMounted();
  const portfolioQ = useQuery({
    queryKey: qk.portfolio.status(),
    queryFn: () => api.portfolio.status(),
    refetchInterval: 60_000,
  });
  const recsQ = useQuery({
    queryKey: qk.portfolio.recommendations(),
    queryFn: () => api.portfolio.recommendations(),
    refetchInterval: 60_000,
  });
  const spyQ = useQuery({
    queryKey: qk.portfolio.spySnapshot(),
    queryFn: () => api.portfolio.spySnapshot(),
    // Snapshot only changes when the daily pipeline runs; no need to
    // hammer the file every minute.
    refetchInterval: 5 * 60_000,
    // The endpoint 404s when no snapshot exists yet; suppress retry-storms.
    retry: false,
  });

  const data = portfolioQ.data;
  const { isLoading, error, refetch, isFetching } = portfolioQ;
  const fetching = mounted && (isFetching || recsQ.isFetching);

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

  // See the original comment in the prior version of this file: the
  // tile shows Alpaca's authoritative snapshot P&L plus a live-tick
  // delta so the displayed number doesn't drift permanently from the
  // broker's own number.
  const snapshotUnrealizedPnl = (data?.positions ?? []).reduce(
    (sum, p) => sum + p.unrealized_pnl,
    0,
  );
  const liveTickDelta = (data?.positions ?? []).reduce((sum, p) => {
    const tick = prices[p.ticker];
    if (!tick || !p.shares || p.current_price == null) return sum;
    return sum + (tick.price - p.current_price) * p.shares;
  }, 0);
  const liveUnrealizedPnl = snapshotUnrealizedPnl + liveTickDelta;
  const liveUnrealizedPnlPct =
    liveCostBasis > 0 ? (liveUnrealizedPnl / liveCostBasis) * 100 : 0;
  const reportedEquity = data?.account.equity ?? null;

  // Recommendation lookup keyed by ticker for O(1) per-row joins.
  const recByTicker = new Map<string, PositionRecommendation>();
  for (const r of recsQ.data?.recommendations ?? []) {
    recByTicker.set(r.ticker, r);
  }
  const nAtRisk = recsQ.data?.n_at_risk ?? 0;
  const atRiskRecs = (recsQ.data?.recommendations ?? []).filter(
    (r) => r.status !== "HOLDING",
  );

  const [period, setPeriod] = useState<Period>("1M");
  const timeframe = PERIOD_TIMEFRAME[period];

  return (
    <>
      <PageHeader
        title="Portfolio"
        description="Live Alpaca paper account, joined with today's strategy stops/targets. IEX prices stream when the market is open."
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
              onClick={() => {
                refetch();
                recsQ.refetch();
                spyQ.refetch();
              }}
              disabled={fetching}
            >
              <RefreshCw
                className={`mr-2 h-4 w-4 ${fetching ? "animate-spin" : ""}`}
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
          tooltip={
            "Sum of Alpaca's authoritative per-position unrealized P&L from the last snapshot. " +
            "Live ticks modulate the displayed number as an estimate; re-anchors to Alpaca's number on the next 60s snapshot."
          }
          value={
            <span className={cn(toneClass(liveUnrealizedPnl))}>
              {fmtUSD(liveUnrealizedPnl)}
            </span>
          }
          sub={
            data
              ? `${liveUnrealizedPnlPct >= 0 ? "+" : ""}${liveUnrealizedPnlPct.toFixed(2)}% on ${fmtUSD(liveCostBasis)} cost${liveTickDelta !== 0 ? " · live tick est." : ""}`
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

      {/* Positions-at-risk callout — only renders when the broker
          recommendations report a stop/target situation. */}
      {nAtRisk > 0 ? (
        <PositionsAtRiskCallout positions={atRiskRecs} />
      ) : null}

      {/* Paper vs SPY card — the alpha story. */}
      <div className="mt-4">
        {spyQ.data ? (
          // PaperVsSpyCard was written for the file-loaded shape; the
          // API response is structurally identical so we cast through.
          <PaperVsSpyCard data={spyQ.data as unknown as PaperVsSpyFile} />
        ) : spyQ.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <PaperVsSpyCard data={null} />
        )}
      </div>

      <EquityCurveCard
        period={period}
        setPeriod={setPeriod}
        timeframe={timeframe}
      />

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Positions</CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-3 text-[11px]">
            <span>
              {data
                ? `${data.n_positions} open ${data.n_positions === 1 ? "position" : "positions"} ${connected ? "· streaming" : "· last poll"}`
                : "Loading positions…"}
            </span>
            {recsQ.data ? (
              <span className="text-muted-foreground">
                stops/targets from{" "}
                <code className="bg-muted px-1 py-0.5 rounded text-[10px]">
                  {recsQ.data.analysis_path ?? "fallback bands"}
                </code>
              </span>
            ) : null}
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
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Shares</TableHead>
                  <TableHead className="text-right">Avg Cost</TableHead>
                  <TableHead className="text-right">Mark</TableHead>
                  <TableHead className="text-right">Stop</TableHead>
                  <TableHead className="text-right">Target</TableHead>
                  <TableHead className="text-right">Mkt Value</TableHead>
                  <TableHead className="text-right">Unrl P&amp;L $</TableHead>
                  <TableHead className="text-right">Unrl P&amp;L %</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {livePositions.map((p) => {
                  const rec = recByTicker.get(p.ticker);
                  const isLive = prices[p.ticker] !== undefined;
                  const fallback = rec?.source === "fallback_8pct";
                  return (
                    <TableRow key={p.ticker} mono>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono text-foreground">
                            {p.ticker}
                          </span>
                          {rec ? (
                            <BasketActionBadge inBasket={rec.in_todays_basket} />
                          ) : null}
                          <a
                            href={`https://www.tradingview.com/symbols/${encodeURIComponent(p.ticker)}/`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-muted-foreground/60 hover:text-primary transition-colors"
                            title={`Open ${p.ticker} chart on TradingView`}
                            aria-label={`Open ${p.ticker} chart on TradingView (new tab)`}
                          >
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        </div>
                      </TableCell>
                      <TableCell>
                        {rec ? (
                          <PositionStatusBadge status={rec.status} />
                        ) : (
                          <span className="text-muted-foreground/60 text-[10px]">—</span>
                        )}
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
                      <TableCell
                        className={cn(
                          "text-right text-bearish",
                          fallback && "italic opacity-70",
                        )}
                        title={
                          fallback
                            ? "Fallback −8% band (ticker not in current strategy)"
                            : "Strategy stop"
                        }
                      >
                        {rec ? fmtUSD(rec.stop_loss) : "—"}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right text-bullish",
                          fallback && "italic opacity-70",
                        )}
                        title={
                          fallback
                            ? "Fallback +10% band (ticker not in current strategy)"
                            : "Strategy target"
                        }
                      >
                        {rec ? fmtUSD(rec.target) : "—"}
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

// ─── Positions-at-risk callout ───────────────────────────────────────────────

function PositionsAtRiskCallout({
  positions,
}: {
  positions: PositionRecommendation[];
}) {
  if (positions.length === 0) return null;
  return (
    <div className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="h-4 w-4 text-amber-500" />
        <p className="text-sm font-medium text-amber-500">
          {positions.length} {positions.length === 1 ? "position" : "positions"} at risk
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {positions.map((p) => (
          <div
            key={p.ticker}
            className="flex items-center gap-1.5 rounded border border-border bg-background/60 px-2 py-1"
          >
            <span className="font-mono text-sm font-semibold">{p.ticker}</span>
            <PositionStatusBadge status={p.status} />
          </div>
        ))}
      </div>
    </div>
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
    queryKey: qk.portfolio.history({ period, timeframe, includeSpy: true }),
    queryFn: () => api.portfolio.history({ period, timeframe, includeSpy: true }),
  });

  const points = data?.points ?? [];
  const base = data?.base_value ?? null;
  const latestEquity = points.length > 0 ? points[points.length - 1].equity : null;
  const sinceStart =
    latestEquity != null && base != null ? latestEquity - base : null;

  // Alpha-since-start: latest portfolio equity minus latest SPY equity,
  // both normalized to base_value. Equivalent to portfolio_return − spy_return
  // scaled by base, so positive = outperforming.
  const lastSpy = points.length > 0 ? points[points.length - 1].spy_equity : null;
  const alphaSinceStart =
    latestEquity != null && lastSpy != null ? latestEquity - lastSpy : null;

  const showSpy = data?.spy_status === "ok";

  // Window-actually-shown vs window-requested: the backend strips leading
  // zero-equity bars (pre-funding). When that fires, longer-window buttons
  // can produce the same number of bars as shorter ones — surface that
  // so the user doesn't conclude the buttons are broken.
  const firstShown = points.length > 0 ? points[0].timestamp : null;
  const lastShown =
    points.length > 0 ? points[points.length - 1].timestamp : null;
  const windowDaysShown =
    firstShown != null && lastShown != null
      ? Math.max(1, Math.round((lastShown - firstShown) / 86400))
      : null;

  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
          Equity curve
        </CardTitle>
        <CardDescription className="text-muted-foreground font-mono text-xs flex flex-wrap gap-3">
          {data ? (
            <>
              <span>
                {period} requested · {windowDaysShown ?? "—"}d shown
                {windowDaysShown != null && windowDaysShown < periodToDays(period) - 2 ? (
                  <span
                    className="ml-1 text-amber-500"
                    title="Account funded after the requested window — chart truncated to actual history"
                  >
                    (truncated)
                  </span>
                ) : null}
                {" · "}{timeframe} bars
              </span>
              <span>
                <span className={cn(pnlColorClass(sinceStart))}>
                  {fmtUSD(sinceStart)}
                </span>
                {" since start"}
              </span>
              {showSpy && alphaSinceStart != null ? (
                <span>
                  α{" "}
                  <span className={cn(pnlColorClass(alphaSinceStart))}>
                    {fmtUSD(alphaSinceStart)}
                  </span>
                  {" vs SPY"}
                </span>
              ) : data?.spy_status === "unavailable" ? (
                <span className="text-muted-foreground/60">
                  (SPY overlay unavailable)
                </span>
              ) : null}
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
  const showSpy = history.spy_status === "ok";

  const tickFormatter = (v: number | string) => {
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
            dataKey="spy_equity"
            name="SPY (normalized)"
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
          name="Paper account"
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
  const alpha = row.spy_equity != null ? row.equity - row.spy_equity : null;
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
      {row.spy_equity != null ? (
        <>
          <div className="tabular-nums text-muted-foreground mt-1">
            SPY {fmtUSD(row.spy_equity)}
          </div>
          <div className={cn("tabular-nums", pnlColorClass(alpha))}>
            α {fmtUSD(alpha)}
          </div>
        </>
      ) : null}
    </div>
  );
}
