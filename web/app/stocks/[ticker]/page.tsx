"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Calendar,
  ChevronLeft,
  ExternalLink,
  Loader2,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { FactorChips } from "@/components/factor-chips";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  api,
  type OHLCBar,
  type Position,
  type TickerFactors,
  type TodayActionItem,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import {
  CHART_AXIS,
  CHART_GRID,
  CHART_TOKEN,
  CHART_TOOLTIP_BG,
  CHART_TOOLTIP_BORDER,
} from "@/lib/chart-tokens";
import { fmtNumber, fmtPct, fmtUSD, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

const HISTORY_DAYS = 180;

type Params = { params: Promise<{ ticker: string }> };

// ─── Page entry ─────────────────────────────────────────────────────────────

export default function StockDetailPage({ params }: Params) {
  const { ticker: tickerParam } = use(params);
  const ticker = decodeURIComponent(tickerParam).toUpperCase();

  // Three independent queries; the page renders best-effort using
  // whichever subset succeeded. Price history is the only "required"
  // surface — without it, there's nothing to draw.
  const historyQ = useQuery({
    queryKey: qk.stocks.detail(ticker, HISTORY_DAYS),
    queryFn: () => api.stocks.get(ticker, { history_days: HISTORY_DAYS }),
    retry: false,
  });
  const actionsQ = useQuery({
    queryKey: qk.pipeline.todayActions(),
    queryFn: () => api.pipeline.todayActions(),
    refetchInterval: 60_000,
    retry: false,
  });
  const portfolioQ = useQuery({
    queryKey: qk.portfolio.status(),
    queryFn: () => api.portfolio.status(),
    refetchInterval: 60_000,
    retry: false,
  });

  // Lookup helpers — find the basket entry and the held position (if any).
  const basketItem: TodayActionItem | null =
    [
      ...(actionsQ.data?.new_buys ?? []),
      ...(actionsQ.data?.keeps ?? []),
      ...(actionsQ.data?.exits ?? []),
    ].find((it) => it.ticker === ticker) ?? null;

  const heldPosition: Position | null =
    portfolioQ.data?.positions?.find((p) => p.ticker === ticker) ?? null;

  const isLoading = historyQ.isLoading;
  const history = historyQ.data?.history ?? [];

  if (isLoading) {
    return (
      <>
        <PageHeader title={ticker} description="Loading…" />
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
        <Skeleton className="h-80 w-full mt-4" />
      </>
    );
  }

  // /api/stocks 404 means we have no Parquet history for this ticker.
  if (
    historyQ.error instanceof ApiError &&
    historyQ.error.status === 404 &&
    history.length === 0
  ) {
    return <NoData ticker={ticker} />;
  }

  return (
    <StockDetail
      ticker={ticker}
      history={history}
      basketItem={basketItem}
      heldPosition={heldPosition}
      picksDate={actionsQ.data?.picks_date ?? null}
    />
  );
}

// ─── Detail body ───────────────────────────────────────────────────────────

function StockDetail({
  ticker, history, basketItem, heldPosition, picksDate,
}: {
  ticker: string;
  history: OHLCBar[];
  basketItem: TodayActionItem | null;
  heldPosition: Position | null;
  picksDate: string | null;
}) {
  const lastBar = history[history.length - 1] ?? null;
  const lastClose = lastBar?.close ?? null;

  // Prefer strategy stop/target from basket; fall back to none for
  // tickers outside the basket (the chart still draws, just no overlay).
  const entry = basketItem?.entry_price ?? heldPosition?.avg_price ?? null;
  const stop = basketItem?.stop_loss ?? null;
  const target = basketItem?.target ?? null;
  const rr =
    entry != null && stop != null && target != null && entry !== stop
      ? (target - entry) / (entry - stop)
      : null;

  const action = basketItem?.action ?? null;  // NEW_BUY / KEEP / EXIT / null
  const status = basketItem?.position_status ?? null;
  const sanity = basketItem?.sanity_verdict ?? null;

  // On-demand factor ranks for tickers outside today's basket. Lifted to the
  // component root so the top scoreboard tiles populate from the same data as
  // the bottom panel once the user clicks "Analyze factors".
  const [analyze, setAnalyze] = useState(false);
  const factorsQ = useQuery({
    queryKey: ["stockFactors", ticker],
    queryFn: () => api.stocks.factors(ticker),
    enabled: analyze && !basketItem,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const fz = !basketItem && factorsQ.data?.in_universe ? factorsQ.data : null;

  return (
    <>
      <PageHeader
        title={ticker}
        description={describeTicker(basketItem, heldPosition, lastClose)}
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            {action ? <ActionBadge action={action} /> : (
              <Badge variant="outline" className="text-[10px] font-mono uppercase tracking-wider">
                not in basket
              </Badge>
            )}
            {status && status !== "HOLDING" ? (
              <Badge variant="outline" className={cn("text-[10px] font-mono uppercase tracking-wider", statusClass(status))}>
                {status}
              </Badge>
            ) : null}
            <a
              href={`https://www.tradingview.com/symbols/${encodeURIComponent(ticker)}/`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-2 py-1 text-[10px] font-mono uppercase tracking-wider border border-border rounded text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors"
              title={`Open ${ticker} chart on TradingView`}
            >
              <ExternalLink className="h-3 w-3" />
              TradingView
            </a>
            <Link
              href="/buy-signals"
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              <ChevronLeft className="h-3 w-3" />
              actions
            </Link>
          </div>
        }
      />

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="Composite z"
          tooltip="Strategy z-score for today's basket — ranks this ticker against the rest of the S&P 500 universe. Only present when the ticker is in today's basket."
          value={
            basketItem?.composite_z != null ? (
              <span className={cn("font-mono", basketItem.composite_z >= 2.0 ? "text-bullish" : "text-foreground")}>
                +{basketItem.composite_z.toFixed(2)}
              </span>
            ) : fz?.composite_z != null ? (
              <span className={cn("font-mono", fz.composite_z >= 2.0 ? "text-bullish" : "text-foreground")}>
                {fz.composite_z >= 0 ? "+" : ""}{fz.composite_z.toFixed(2)}
              </span>
            ) : (
              <span className="text-muted-foreground text-base">—</span>
            )
          }
          sub={
            basketItem?.composite_z != null
              ? picksDate ? `picks for ${picksDate}` : "no picks data"
              : fz?.composite_rank != null
                ? `on-demand · #${fz.composite_rank}/${fz.universe_size}`
                : picksDate ? `picks for ${picksDate}` : "no picks data"
          }
          subTone="muted"
        />
        <ScoreboardTile
          label="Factor stack"
          tooltip="Per-factor rank within today's universe (smaller = stronger). Chips render when the rank lands in top decile (≤ 50)."
          value={
            basketItem ? (
              <FactorChips
                mom={basketItem.mom_rank}
                qual={basketItem.qual_rank}
                val={basketItem.val_rank}
                pead={basketItem.pead_rank}
              />
            ) : fz ? (
              <FactorChips
                mom={fz.momentum_rank}
                qual={fz.quality_rank}
                val={fz.value_rank}
                pead={fz.pead_rank}
              />
            ) : (
              <span className="text-muted-foreground text-base">—</span>
            )
          }
          sub={basketItem ? "top-decile factors" : fz ? "on-demand · top-decile" : "not ranked"}
          subTone="muted"
        />
        <ScoreboardTile
          label="Position"
          tooltip="Currently-held paper position state for this ticker."
          value={
            heldPosition ? (
              <span className="font-mono text-base">
                {fmtNumber(heldPosition.shares, 0)} sh
              </span>
            ) : (
              <span className="text-muted-foreground text-base">none</span>
            )
          }
          sub={
            heldPosition
              ? `${fmtUSD(heldPosition.avg_price)} avg · ${fmtUSD(heldPosition.market_value)}`
              : "not held"
          }
          subTone={heldPosition ? "muted" : "muted"}
        />
        <ScoreboardTile
          label="Unrealized P&L"
          value={
            heldPosition ? (
              <span className={cn("font-mono", pnlColorClass(heldPosition.unrealized_pnl))}>
                {fmtUSD(heldPosition.unrealized_pnl)}
              </span>
            ) : (
              <span className="text-muted-foreground text-base">—</span>
            )
          }
          sub={
            heldPosition
              ? `${fmtPct(heldPosition.unrealized_pnl_pct, 2, true)} vs cost`
              : undefined
          }
          subTone={
            heldPosition && heldPosition.unrealized_pnl > 0 ? "bullish"
            : heldPosition && heldPosition.unrealized_pnl < 0 ? "bearish"
            : "muted"
          }
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-4 mt-4">
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                Price + plan
              </CardTitle>
              <CardDescription className="text-[11px]">
                {history.length}d of OHLC.
                {entry != null ? <> Entry {fmtUSD(entry)}.</> : null}
                {stop != null ? <> Stop {fmtUSD(stop)}.</> : null}
                {target != null ? <> Target {fmtUSD(target)}.</> : null}
                {rr != null ? <> R/R {rr.toFixed(2)}:1.</> : null}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {history.length === 0 ? (
                <p className="text-muted-foreground text-sm py-12 text-center font-mono">
                  No price history yet — Parquet store doesn&apos;t have {ticker}.
                </p>
              ) : (
                <div className="h-80">
                  <PriceChart
                    history={history}
                    entry={entry}
                    stop={stop}
                    target={target}
                  />
                </div>
              )}
            </CardContent>
          </Card>

          {basketItem?.rationale ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  Why this trade
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-relaxed">{basketItem.rationale}</p>
                {basketItem.expected_return_pct != null
                  || basketItem.position_size_usd != null
                  || basketItem.time_exit_date != null
                  ? (
                  <dl className="mt-4 grid grid-cols-2 gap-x-3 gap-y-1.5 font-mono text-xs">
                    {basketItem.position_size_usd != null ? (
                      <>
                        <dt className="text-muted-foreground">position size</dt>
                        <dd>{fmtUSD(basketItem.position_size_usd, true)}</dd>
                      </>
                    ) : null}
                    {basketItem.target_shares != null ? (
                      <>
                        <dt className="text-muted-foreground">target shares</dt>
                        <dd>{basketItem.target_shares}</dd>
                      </>
                    ) : null}
                    {basketItem.expected_return_pct != null ? (
                      <>
                        <dt className="text-muted-foreground">expected return</dt>
                        <dd className={pnlColorClass(basketItem.expected_return_pct)}>
                          {fmtPct(basketItem.expected_return_pct, 1, true)}
                        </dd>
                      </>
                    ) : null}
                    {basketItem.time_exit_date != null ? (
                      <>
                        <dt className="text-muted-foreground">time-exit</dt>
                        <dd>{basketItem.time_exit_date}</dd>
                      </>
                    ) : null}
                    {basketItem.days_to_earnings != null ? (
                      <>
                        <dt className="text-muted-foreground">earnings in</dt>
                        <dd className={basketItem.days_to_earnings <= 14 ? "text-bearish" : ""}>
                          {basketItem.days_to_earnings}d
                        </dd>
                      </>
                    ) : null}
                  </dl>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </div>

        <div className="lg:col-span-1 space-y-4">
          {sanity ? (
            <SanityCard item={basketItem!} />
          ) : null}

          {heldPosition ? (
            <PositionCard
              ticker={ticker}
              position={heldPosition}
              stop={stop}
              target={target}
              entry={entry}
              lastClose={lastClose}
            />
          ) : null}

          {action != null && !heldPosition && action === "NEW_BUY" ? (
            <NewBuyHintCard item={basketItem!} />
          ) : null}

          {!basketItem && !heldPosition ? (
            <FactorAnalysisCard
              run={analyze}
              onRun={() => setAnalyze(true)}
              data={factorsQ.data}
              isLoading={factorsQ.isLoading || factorsQ.isFetching}
              error={factorsQ.error}
            />
          ) : null}
        </div>
      </div>
    </>
  );
}

function FactorAnalysisCard({
  run,
  onRun,
  data,
  isLoading,
  error,
}: {
  run: boolean;
  onRun: () => void;
  data: TickerFactors | undefined;
  isLoading: boolean;
  error: unknown;
}) {
  return (
    <Card>
      <CardContent className="py-5 space-y-3">
        <p className="text-sm text-muted-foreground">
          Not in today&apos;s basket or your paper positions.
        </p>
        {!run ? (
          <div className="space-y-1.5">
            <Button
              size="sm"
              onClick={onRun}
              className="font-mono text-[11px] tracking-wider uppercase"
            >
              Analyze factors
            </Button>
            <p className="text-[10px] text-muted-foreground">
              ranks this ticker across the universe · first run ~1–2&nbsp;min
            </p>
          </div>
        ) : isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Scoring the universe… (~1–2&nbsp;min)
          </div>
        ) : error ? (
          <p className="text-sm text-bearish">
            Couldn&apos;t compute factors:{" "}
            {error instanceof Error ? error.message : "unknown error"}
          </p>
        ) : data ? (
          <FactorAnalysisResult data={data} />
        ) : null}
      </CardContent>
    </Card>
  );
}

function FactorAnalysisResult({ data }: { data: TickerFactors }) {
  if (!data.in_universe) {
    return (
      <p className="text-sm text-muted-foreground">
        {data.note ?? "Not in the scored S&P 500 universe for this date."}
      </p>
    );
  }
  const fmt = (n: number | null) => (n != null ? `#${n}` : "—");
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between border-b border-border pb-2">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          Composite
        </span>
        <span className="font-mono text-sm">
          {fmt(data.composite_rank)}
          <span className="text-muted-foreground">/{data.universe_size}</span>
          {data.composite_z != null ? (
            <span className="ml-2 text-muted-foreground">
              z {data.composite_z >= 0 ? "+" : ""}
              {data.composite_z.toFixed(2)}
            </span>
          ) : null}
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 font-mono text-xs">
        <dt className="text-muted-foreground">momentum</dt>
        <dd>{fmt(data.momentum_rank)}</dd>
        <dt className="text-muted-foreground">quality</dt>
        <dd>{fmt(data.quality_rank)}</dd>
        <dt className="text-muted-foreground">value</dt>
        <dd>{fmt(data.value_rank)}</dd>
        <dt className="text-muted-foreground">PEAD</dt>
        <dd>{fmt(data.pead_rank)}</dd>
      </dl>
      <p
        className={
          data.picked_today
            ? "text-[11px] text-bullish"
            : "text-[11px] text-muted-foreground"
        }
      >
        {data.picked_today ? "In today's basket." : "Not in today's basket."}
      </p>
      {data.note ? (
        <p className="text-[11px] leading-snug text-amber-500/90">{data.note}</p>
      ) : null}
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function describeTicker(
  basket: TodayActionItem | null,
  position: Position | null,
  lastClose: number | null,
): string {
  const parts: string[] = [];
  if (basket?.sector) parts.push(basket.sector);
  if (position) parts.push(`held ${position.shares} sh @ ${fmtUSD(position.avg_price)}`);
  if (lastClose != null) parts.push(`last close ${fmtUSD(lastClose)}`);
  return parts.length > 0 ? parts.join(" · ") : "Per-ticker detail";
}

function ActionBadge({ action }: { action: "NEW_BUY" | "KEEP" | "EXIT" }) {
  const cfg: Record<
    "NEW_BUY" | "KEEP" | "EXIT",
    { label: string; cls: string; icon: typeof ArrowUpRight }
  > = {
    NEW_BUY: { label: "NEW BUY", cls: "border-bullish/40 bg-bullish/10 text-bullish", icon: ArrowUpRight },
    KEEP: { label: "KEEP", cls: "border-primary/40 bg-primary/10 text-primary", icon: Wallet },
    EXIT: { label: "EXIT", cls: "border-bearish/40 bg-bearish/10 text-bearish", icon: ArrowDownRight },
  };
  const c = cfg[action];
  const Icon = c.icon;
  return (
    <Badge variant="outline" className={cn("gap-1 text-[10px] font-mono uppercase tracking-wider", c.cls)}>
      <Icon className="h-3 w-3" />
      {c.label}
    </Badge>
  );
}

function statusClass(s: NonNullable<TodayActionItem["position_status"]>): string {
  if (s === "STOP_HIT") return "border-bearish/40 bg-bearish/10 text-bearish";
  if (s === "NEAR_STOP") return "border-amber-500/40 bg-amber-500/10 text-amber-500";
  if (s === "TARGET_HIT") return "border-bullish/40 bg-bullish/10 text-bullish";
  if (s === "NEAR_TARGET") return "border-emerald-500/40 bg-emerald-500/10 text-emerald-500";
  return "border-border text-muted-foreground";
}

// ─── Side cards ─────────────────────────────────────────────────────────────

function SanityCard({ item }: { item: TodayActionItem }) {
  const v = item.sanity_verdict;
  const cls =
    v === "VETO" ? "border-bearish/40 bg-bearish/5"
    : v === "FLAG" ? "border-amber-500/40 bg-amber-500/5"
    : "border-bullish/40 bg-bullish/5";
  return (
    <Card className={cls}>
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
          AI sanity check
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2 mb-2">
          <Badge
            variant="outline"
            className={cn(
              "text-[10px] font-mono uppercase tracking-wider",
              v === "VETO" && "border-bearish/40 bg-bearish/10 text-bearish",
              v === "FLAG" && "border-amber-500/40 bg-amber-500/10 text-amber-500",
              (v === "KEEP") && "border-bullish/40 bg-bullish/10 text-bullish",
            )}
          >
            {v}
          </Badge>
          {item.sanity_reason ? (
            <span className="text-[10px] font-mono text-muted-foreground">
              {item.sanity_reason}
            </span>
          ) : null}
        </div>
        {item.sanity_evidence ? (
          <p className="text-xs leading-relaxed text-muted-foreground">
            {item.sanity_evidence}
          </p>
        ) : null}
        <p className="mt-3 text-[10px] text-muted-foreground/60">
          Advisory only — does not block paper-trade execution.
        </p>
      </CardContent>
    </Card>
  );
}

function PositionCard({
  ticker, position, stop, target, entry, lastClose,
}: {
  ticker: string;
  position: Position;
  stop: number | null;
  target: number | null;
  entry: number | null;
  lastClose: number | null;
}) {
  const mark = position.current_price ?? lastClose;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
          My position
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 font-mono text-xs">
          <dt className="text-muted-foreground">ticker</dt>
          <dd>{ticker}</dd>
          <dt className="text-muted-foreground">shares</dt>
          <dd>{fmtNumber(position.shares, 0)}</dd>
          <dt className="text-muted-foreground">avg cost</dt>
          <dd>{fmtUSD(position.avg_price)}</dd>
          <dt className="text-muted-foreground">mark</dt>
          <dd>{mark != null ? fmtUSD(mark) : "—"}</dd>
          <dt className="text-muted-foreground">market value</dt>
          <dd>{fmtUSD(position.market_value)}</dd>
          <dt className="text-muted-foreground">unrl P&amp;L</dt>
          <dd className={pnlColorClass(position.unrealized_pnl)}>
            {fmtUSD(position.unrealized_pnl)} ({fmtPct(position.unrealized_pnl_pct, 2, true)})
          </dd>
          {entry != null ? (
            <>
              <dt className="text-muted-foreground">entry plan</dt>
              <dd>{fmtUSD(entry)}</dd>
            </>
          ) : null}
          {stop != null ? (
            <>
              <dt className="text-muted-foreground">stop</dt>
              <dd className="text-bearish">{fmtUSD(stop)}</dd>
            </>
          ) : null}
          {target != null ? (
            <>
              <dt className="text-muted-foreground">target</dt>
              <dd className="text-bullish">{fmtUSD(target)}</dd>
            </>
          ) : null}
        </dl>
      </CardContent>
    </Card>
  );
}

function NewBuyHintCard({ item }: { item: TodayActionItem }) {
  return (
    <Card className="border-bullish/40 bg-bullish/5">
      <CardHeader>
        <CardTitle className="text-xs font-medium tracking-wider uppercase text-bullish">
          New buy — order ready
        </CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 font-mono text-xs">
          {item.target_shares != null ? (
            <>
              <dt className="text-muted-foreground">qty</dt>
              <dd>{item.target_shares}</dd>
            </>
          ) : null}
          {item.entry_price != null ? (
            <>
              <dt className="text-muted-foreground">entry</dt>
              <dd>{fmtUSD(item.entry_price)}</dd>
            </>
          ) : null}
          {item.stop_loss != null ? (
            <>
              <dt className="text-muted-foreground">stop</dt>
              <dd className="text-bearish">{fmtUSD(item.stop_loss)}</dd>
            </>
          ) : null}
          {item.target != null ? (
            <>
              <dt className="text-muted-foreground">target</dt>
              <dd className="text-bullish">{fmtUSD(item.target)}</dd>
            </>
          ) : null}
        </dl>
        <Link
          href="/buy-signals"
          className="mt-3 inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          Full action list <ChevronLeft className="h-3 w-3 rotate-180" />
        </Link>
      </CardContent>
    </Card>
  );
}

function NoData({ ticker }: { ticker: string }) {
  return (
    <>
      <PageHeader title={ticker} description="No data available" />
      <Card>
        <CardContent className="py-12 text-center space-y-3">
          <AlertTriangle className="h-8 w-8 text-muted-foreground mx-auto" />
          <p className="font-mono text-xs tracking-wider uppercase text-muted-foreground">
            No price history in Parquet store
          </p>
          <p className="text-sm text-muted-foreground">
            This ticker has no cached OHLC bars and isn&apos;t in today&apos;s basket.
            Add it to the universe (config/portfolio.yaml) and re-run the
            pipeline, or check the ticker spelling.
          </p>
          <Link
            href="/buy-signals"
            className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          >
            <ChevronLeft className="h-3 w-3" />
            Today&apos;s actions
          </Link>
        </CardContent>
      </Card>
    </>
  );
}

// ─── Price chart ────────────────────────────────────────────────────────────

function PriceChart({
  history, entry, stop, target,
}: {
  history: OHLCBar[];
  entry: number | null;
  stop: number | null;
  target: number | null;
}) {
  const data = history.map((b) => ({
    date: b.date,
    close: b.close,
    timestamp: new Date(b.date).getTime() / 1000,
  }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
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
              month: "short",
              day: "2-digit",
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
          tickFormatter={(v) => fmtUSD(v as number)}
          width={64}
          domain={["auto", "auto"]}
        />
        <Tooltip
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const row = payload[0]?.payload as { date: string; close: number };
            return (
              <div
                className="border border-border px-2.5 py-1.5 font-mono text-[11px] leading-tight"
                style={{
                  background: CHART_TOOLTIP_BG,
                  borderColor: CHART_TOOLTIP_BORDER,
                }}
              >
                <div className="text-muted-foreground text-[10px] uppercase tracking-wider">
                  {row.date}
                </div>
                <div className="text-foreground tabular-nums">{fmtUSD(row.close)}</div>
              </div>
            );
          }}
          cursor={{ stroke: CHART_GRID }}
        />
        {stop != null ? (
          <ReferenceLine
            y={stop}
            stroke="var(--bearish)"
            strokeDasharray="3 3"
            label={{
              value: `STOP ${fmtUSD(stop)}`,
              position: "insideTopRight",
              fill: "var(--bearish)",
              fontSize: 10,
              fontFamily: "var(--font-geist-mono)",
            }}
          />
        ) : null}
        {target != null ? (
          <ReferenceLine
            y={target}
            stroke="var(--bullish)"
            strokeDasharray="3 3"
            label={{
              value: `TARGET ${fmtUSD(target)}`,
              position: "insideTopRight",
              fill: "var(--bullish)",
              fontSize: 10,
              fontFamily: "var(--font-geist-mono)",
            }}
          />
        ) : null}
        {entry != null ? (
          <ReferenceLine
            y={entry}
            stroke={CHART_AXIS}
            strokeOpacity={0.6}
            label={{
              value: `ENTRY ${fmtUSD(entry)}`,
              position: "insideBottomRight",
              fill: CHART_AXIS,
              fontSize: 10,
              fontFamily: "var(--font-geist-mono)",
            }}
          />
        ) : null}
        <Area
          type="monotone"
          dataKey="close"
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
