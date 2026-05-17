"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { use, useEffect } from "react";
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

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { MyPositionCard } from "@/components/stocks/my-position-card";
import {
  RecommendationWarnings,
  actionLabelForGate,
} from "@/components/stocks/recommendation-warnings";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, type OHLCBar, type ScanResultItem } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import {
  CHART_AXIS,
  CHART_GRID,
  CHART_TOKEN,
  CHART_TOOLTIP_BG,
  CHART_TOOLTIP_BORDER,
} from "@/lib/chart-tokens";
import { fmtDate, fmtNumber, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

const HISTORY_DAYS = 120;

type RiskMgmt = Record<string, unknown>;

type BadgeVariant = "bullish" | "bearish" | "neutral" | "default" | "outline";

function actionBadgeVariant(action: string): BadgeVariant {
  if (action === "STRONG BUY" || action === "BUY") return "bullish";
  if (action === "STRONG SELL" || action === "SELL") return "bearish";
  if (action === "REFUSED") return "bearish";
  if (action === "HOLD") return "neutral";
  return "outline";
}

function scoreTextClass(score: number): string {
  if (score >= 60) return "text-bullish";
  if (score <= 40) return "text-bearish";
  return "text-foreground";
}

function scoreBarClass(score: number): string {
  if (score >= 60) return "bg-bullish";
  if (score <= 40) return "bg-bearish";
  return "bg-primary";
}

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  return null;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/**
 * Risk values from the engine come in two shapes:
 *   1. flat number  (legacy + simple keys like current_price)
 *   2. nested dict  ({price, method, detail, pct_from_current}) — what
 *      stop_loss / take_profit actually emit today.
 * Extract the number if either shape resolves to one.
 */
function numFromRiskField(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (isPlainObject(v) && typeof v.price === "number" && Number.isFinite(v.price)) {
    return v.price;
  }
  return null;
}

function prettifyKey(k: string): string {
  return k
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatRiskValue(key: string, v: unknown): string {
  const n = num(v);
  const k = key.toLowerCase();
  if (n !== null) {
    if (k.includes("price") || k.includes("value") || k.includes("dollars")) {
      return fmtUSD(n);
    }
    if (
      k.includes("shares") ||
      k.includes("mult") ||
      k.includes("ratio") ||
      k.includes("pct")
    ) {
      return fmtNumber(n, 2);
    }
    return fmtNumber(n, 2);
  }
  if (typeof v === "string") return v;
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}

export default function StockDetailPage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker: tickerParam } = use(params);
  const ticker = decodeURIComponent(tickerParam).toUpperCase();

  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: qk.stocks.detail(ticker, HISTORY_DAYS),
    queryFn: () => api.stocks.get(ticker, { history_days: HISTORY_DAYS }),
    retry: false,
  });

  // Fallback path: the /api/stocks endpoint only returns a recommendation
  // if the ticker is present in a recent scan_run. For ad-hoc tickers from
  // the sidebar search bar we run the analyzer chain on-demand.
  const needsAnalyze =
    (data && !data.latest_recommendation) ||
    (error instanceof ApiError && error.status === 404);

  const {
    data: analyzeRec,
    isLoading: analyzeLoading,
    error: analyzeError,
  } = useQuery({
    queryKey: ["stocks", "analyze", ticker],
    queryFn: () => api.stocks.analyze(ticker),
    enabled: needsAnalyze,
    retry: false,
  });

  // /api/stocks/{ticker}/analyze writes the fetched OHLCV to Parquet as a
  // side effect. Once analyze lands, re-query /api/stocks so the chart
  // panel picks up the freshly-written bars (it reads from Parquet only).
  useEffect(() => {
    if (analyzeRec && (!data?.history || data.history.length === 0)) {
      queryClient.invalidateQueries({
        queryKey: qk.stocks.detail(ticker, HISTORY_DAYS),
      });
    }
  }, [analyzeRec, data?.history, ticker, queryClient]);

  if (isLoading || (needsAnalyze && analyzeLoading)) {
    return (
      <>
        <PageHeader
          title={ticker}
          description={analyzeLoading ? "Running on-demand analysis…" : "Loading…"}
        />
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
        <div className="grid lg:grid-cols-3 gap-4 mt-4">
          <Skeleton className="h-96 w-full lg:col-span-2" />
          <Skeleton className="h-96 w-full" />
        </div>
      </>
    );
  }

  // Both detail + analyze 404'd → ticker is unfetchable (e.g. typo).
  if (
    error instanceof ApiError &&
    error.status === 404 &&
    analyzeError instanceof ApiError &&
    analyzeError.status === 404
  ) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-3">
        <p className="font-mono text-xs tracking-wider uppercase text-muted-foreground">
          No price or fundamental data available
        </p>
        <p className="font-mono text-sm text-foreground">{ticker}</p>
        <Link
          href="/scan"
          className="font-mono text-xs tracking-wider uppercase text-primary hover:underline"
        >
          [ Back to scan ]
        </Link>
      </div>
    );
  }

  // Merge: prefer the scan-derived recommendation; fall back to the
  // on-demand analyze result. The /api/stocks payload still owns the
  // history / scan metadata even when the recommendation came from analyze.
  const merged = {
    ticker,
    latest_recommendation: data?.latest_recommendation ?? analyzeRec ?? null,
    scan_run_id: data?.scan_run_id ?? null,
    scan_strategy: data?.scan_strategy ?? null,
    scan_timestamp: data?.scan_timestamp ?? null,
    history: data?.history ?? [],
    onDemand: !data?.latest_recommendation && !!analyzeRec,
  };

  if (!merged.latest_recommendation) {
    return (
      <>
        <PageHeader title={ticker} description="No recommendation available" />
        {error ? <ErrorState error={error} /> : null}
        {analyzeError ? <ErrorState error={analyzeError} /> : null}
      </>
    );
  }

  // Suppress the original /api/stocks 404 once the analyze fallback has
  // produced a recommendation — that error is expected for ad-hoc tickers
  // not in any recent scan, and surfacing it next to a successful analysis
  // is just confusing noise.
  const surfaceError = merged.onDemand ? null : error;
  return <StockDetail ticker={ticker} data={merged} error={surfaceError} />;
}

function StockDetail({
  ticker,
  data,
  error,
}: {
  ticker: string;
  data: {
    ticker: string;
    latest_recommendation?: ScanResultItem | null;
    scan_run_id?: string | null;
    scan_strategy?: string | null;
    scan_timestamp?: string | null;
    history?: OHLCBar[];
    onDemand?: boolean;
  };
  error: unknown;
}) {
  const rec = data.latest_recommendation ?? null;
  const history = data.history ?? [];
  const risk: RiskMgmt = (rec?.risk_management ?? {}) as RiskMgmt;

  // Engine emits `current_price` (entry baseline) + nested stop_loss /
  // take_profit dicts with `.price`. Older callers may pass flat numbers.
  const entry = num(risk.entry_price) ?? num(risk.current_price);
  const stop = numFromRiskField(risk.stop_loss);
  const target = numFromRiskField(risk.take_profit);
  // Triple-barrier time stop. Calendar-day budget the engine applies to
  // new positions of this strategy. Shape: { method, days, exit_date,
  // detail }. Older recommendations won't have it — guard defensively.
  const timeStop =
    isPlainObject(risk.time_stop) && typeof risk.time_stop.exit_date === "string"
      ? {
          exitDate: risk.time_stop.exit_date as string,
          days:
            typeof risk.time_stop.days === "number"
              ? (risk.time_stop.days as number)
              : null,
        }
      : null;
  // Surface which method the engine actually used for the take-profit.
  // The basis affects how you should read the number: "resistance" =
  // chart-derived level (a real price the stock has struggled at);
  // "risk_reward" = mechanical 3:1 multiple of the stop distance, not
  // a price forecast.
  const takeProfitMethod =
    isPlainObject(risk.take_profit) && typeof risk.take_profit.method === "string"
      ? (risk.take_profit.method as string)
      : null;
  const lastClose = history.length > 0 ? history[history.length - 1].close : null;

  const headerTitle = rec?.name ? `${ticker} — ${rec.name}` : ticker;
  const headerDescription = rec
    ? [
        rec.sector,
        rec.industry,
        rec.market_cap != null
          ? `market cap ${fmtUSD(rec.market_cap, true)}`
          : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : history.length > 0
      ? `Last close ${fmtUSD(lastClose)}`
      : "No data yet";

  const rr =
    entry !== null && stop !== null && target !== null && entry !== stop
      ? (target - entry) / (entry - stop)
      : null;

  return (
    <>
      <PageHeader
        title={headerTitle}
        description={headerDescription}
        actions={
          rec ? (
            <div className="flex items-center gap-2 flex-wrap">
              <Badge variant={actionBadgeVariant(actionLabelForGate(rec))}>
                {actionLabelForGate(rec)}
              </Badge>
              {timeStop ? (
                <Badge
                  variant="neutral"
                  className="text-[10px]"
                  title={
                    timeStop.days != null
                      ? `Triple-barrier time stop: forced exit after ${timeStop.days} calendar days from entry. Calibrated to the strategy's alpha half-life.`
                      : "Triple-barrier time stop"
                  }
                >
                  Exit by {timeStop.exitDate}
                  {timeStop.days != null ? ` · ${timeStop.days}d` : ""}
                </Badge>
              ) : null}
              <a
                href={`https://www.tradingview.com/symbols/${encodeURIComponent(ticker)}/`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-2 py-1 text-[10px] font-mono uppercase tracking-wider border border-border rounded text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors"
                title={`Open ${ticker} chart on TradingView`}
                aria-label={`Open ${ticker} chart on TradingView (new tab)`}
              >
                <ExternalLink className="h-3 w-3" />
                TradingView
              </a>
              <span className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                {data.onDemand ? (
                  <>On-demand analysis · swing_trading</>
                ) : (
                  <>
                    Last scored {fmtDate(data.scan_timestamp)}
                    {data.scan_strategy ? ` · ${data.scan_strategy}` : ""}
                  </>
                )}
              </span>
            </div>
          ) : null
        }
      />

      {error ? <ErrorState error={error} /> : null}

      {rec ? <RecommendationWarnings rec={rec} /> : null}

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="Composite Score"
          tooltip="Strategy-weighted blend of all sub-scores, 0-100. ≥70 = STRONG BUY, 50-70 = HOLD, ≤30 = STRONG SELL. Each strategy weighs the sub-scores differently — see /help → Strategies."
          value={
            rec ? (
              <span
                className={cn(
                  rec.composite_score >= 60
                    ? "text-bullish"
                    : rec.composite_score <= 40
                      ? "text-bearish"
                      : "text-foreground",
                )}
              >
                {fmtNumber(rec.composite_score, 1)}
              </span>
            ) : (
              "—"
            )
          }
          sub={rec ? `${rec.confidence} confidence` : undefined}
          subTone="muted"
        />
        <ScoreboardTile
          label="Entry"
          tooltip="Suggested entry price for the trade plan — the engine's reference price at scan time (typically the latest close). Use the chart on the left to time the actual fill."
          value={fmtUSD(entry)}
          sub={lastClose !== null ? `last close ${fmtUSD(lastClose)}` : undefined}
          subTone="muted"
        />
        <ScoreboardTile
          label="Stop / Take profit"
          tooltip={
            takeProfitMethod === "resistance"
              ? "Stop (top, bearish) and take-profit (bottom, bullish). Stop is ATR-derived (default 2× ATR below entry). Take-profit is the nearest chart resistance level above entry that gives at least 1.5:1 reward-to-risk — a real price the stock has struggled at, not a forecast that it must reach."
              : "Stop (top, bearish) and take-profit (bottom, bullish). Stop is ATR-derived (default 2× ATR below entry). Take-profit is a mechanical 3:1 reward-to-risk multiple of the stop distance — NOT a forecast that the stock will reach this price. The system fell back to this when no chart resistance gave a usable level."
          }
          value={
            <span className="flex flex-col leading-none gap-1">
              <span className="text-bearish text-lg font-semibold tabular-nums">
                {fmtUSD(stop)}
              </span>
              <span className="text-bullish text-lg font-semibold tabular-nums">
                {fmtUSD(target)}
              </span>
            </span>
          }
          sub={
            <span>
              {rr !== null ? `${rr.toFixed(2)}:1 R/R` : null}
              {takeProfitMethod ? (
                <span className="ml-1 opacity-70">
                  {rr !== null ? "· " : ""}
                  {takeProfitMethod === "resistance"
                    ? "chart resistance"
                    : "R/R multiple"}
                </span>
              ) : null}
            </span>
          }
          subTone="muted"
        />
        <ScoreboardTile
          label="Signals"
          tooltip="Count of bullish (▲) vs bearish (▼) individual signals fired by all analyzers. Each is a reasoning bullet on the right (e.g. '+ SMA20: price above SMA20'). High bullish:bearish ratio = high-conviction setup."
          value={
            rec ? (
              <span className="font-mono">
                <span className="text-bullish">{rec.bullish_signals}</span>
                <span className="text-muted-foreground"> ▲ / </span>
                <span className="text-bearish">{rec.bearish_signals}</span>
                <span className="text-muted-foreground"> ▼</span>
              </span>
            ) : (
              "—"
            )
          }
          sub={
            rec && rec.breakdown && rec.breakdown.length > 0
              ? `${rec.breakdown.length} categories scored`
              : undefined
          }
          subTone="muted"
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-4 mt-4">
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                Price + plan
              </CardTitle>
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

          {rec && rec.sub_scores && Object.keys(rec.sub_scores).length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  Sub-score breakdown
                </CardTitle>
              </CardHeader>
              <CardContent>
                <SubScoreBars sub={rec.sub_scores} />
              </CardContent>
            </Card>
          ) : null}
        </div>

        <div className="lg:col-span-1 space-y-4">
          {rec ? (
            <>
              <MyPositionCard
                ticker={ticker}
                mark={lastClose ?? entry}
                entry={entry}
                stop={stop}
                target={target}
                action={rec.action}
                score={rec.composite_score}
                timeStop={timeStop}
              />
              <Card>
                <CardHeader>
                  <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                    Reasoning
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {rec.reasoning && rec.reasoning.length > 0 ? (
                    <ul className="space-y-1.5">
                      {rec.reasoning.map((r, i) => (
                        <li
                          key={i}
                          className="text-sm text-foreground font-mono leading-relaxed flex gap-2"
                        >
                          <span className="text-muted-foreground select-none">
                            {"→"}
                          </span>
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-muted-foreground text-sm font-mono">
                      No engine commentary.
                    </p>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                    Risk management
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <RiskTable risk={risk} />
                </CardContent>
              </Card>
            </>
          ) : (
            <Card>
              <CardContent>
                <p className="text-muted-foreground text-sm font-mono py-8 text-center">
                  No engine recommendation yet — run /scan to score this ticker.
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function PriceChart({
  history,
  entry,
  stop,
  target,
}: {
  history: OHLCBar[];
  entry: number | null;
  stop: number | null;
  target: number | null;
}) {
  const dateFmt = (d: string | number) => {
    const dt = new Date(d);
    return Number.isNaN(dt.getTime())
      ? String(d)
      : dt.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
  };

  const tooltipFormatter = (value: unknown) => {
    if (typeof value !== "number") return [String(value), "close"] as const;
    const tone =
      entry !== null
        ? value > entry
          ? "above entry"
          : value < entry
            ? "below entry"
            : "at entry"
        : "";
    return [`${fmtUSD(value)}${tone ? ` · ${tone}` : ""}`, "close"] as const;
  };

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart
        data={history}
        margin={{ top: 8, right: 64, bottom: 0, left: 8 }}
      >
        <defs>
          <linearGradient id="stock-price-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART_TOKEN.primary} stopOpacity={0.12} />
            <stop offset="100%" stopColor={CHART_TOKEN.primary} stopOpacity={0} />
          </linearGradient>
        </defs>

        <CartesianGrid
          stroke={CHART_GRID}
          strokeOpacity={0.4}
          strokeDasharray="2 4"
          vertical={false}
        />
        <XAxis
          dataKey="date"
          tickFormatter={dateFmt}
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
          width={56}
          domain={["auto", "auto"]}
        />
        <Tooltip
          contentStyle={{
            background: CHART_TOOLTIP_BG,
            border: `1px solid ${CHART_TOOLTIP_BORDER}`,
            borderRadius: 2,
            fontSize: 11,
            fontFamily: "var(--font-geist-mono)",
          }}
          labelFormatter={(d) => new Date(d as string).toLocaleDateString()}
          formatter={tooltipFormatter}
        />

        {entry !== null ? (
          <ReferenceLine
            y={entry}
            stroke={CHART_TOKEN.primary}
            strokeOpacity={0.9}
            strokeDasharray="3 3"
            label={{
              value: "ENTRY",
              position: "right",
              fill: CHART_TOKEN.primary,
              fontSize: 10,
              fontFamily: "var(--font-geist-mono)",
              letterSpacing: 1,
            }}
          />
        ) : null}
        {stop !== null ? (
          <ReferenceLine
            y={stop}
            stroke="var(--bearish)"
            strokeOpacity={0.9}
            strokeDasharray="3 3"
            label={{
              value: "STOP",
              position: "right",
              fill: "var(--bearish)",
              fontSize: 10,
              fontFamily: "var(--font-geist-mono)",
              letterSpacing: 1,
            }}
          />
        ) : null}
        {target !== null ? (
          <ReferenceLine
            y={target}
            stroke="var(--bullish)"
            strokeOpacity={0.9}
            strokeDasharray="3 3"
            label={{
              value: "TARGET",
              position: "right",
              fill: "var(--bullish)",
              fontSize: 10,
              fontFamily: "var(--font-geist-mono)",
              letterSpacing: 1,
            }}
          />
        ) : null}

        <Area
          type="monotone"
          dataKey="close"
          stroke={CHART_TOKEN.primary}
          strokeWidth={1.5}
          fill="url(#stock-price-fill)"
          fillOpacity={1}
          isAnimationActive={false}
          dot={false}
          activeDot={{ r: 3, fill: CHART_TOKEN.primary, stroke: "none" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function SubScoreBars({ sub }: { sub: Record<string, number | undefined> }) {
  const entries = Object.entries(sub)
    .filter(([, v]) => typeof v === "number" && Number.isFinite(v))
    .map(([k, v]) => [k, v as number] as const)
    .sort((a, b) => b[1] - a[1]);

  if (entries.length === 0) {
    return (
      <p className="text-muted-foreground text-sm font-mono">No sub-scores.</p>
    );
  }

  return (
    <div className="space-y-2">
      {entries.map(([k, score]) => {
        const pct = Math.max(0, Math.min(100, score));
        return (
          <div key={k} className="flex items-center gap-3">
            <span className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground w-28 truncate">
              {k}
            </span>
            <div className="h-1.5 bg-muted/30 rounded-full overflow-hidden flex-1">
              <div
                style={{ width: `${pct}%` }}
                className={cn("h-full", scoreBarClass(score))}
              />
            </div>
            <span
              className={cn(
                "font-mono tabular-nums text-xs w-12 text-right",
                scoreTextClass(score),
              )}
            >
              {score.toFixed(1)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function flattenRiskRows(risk: RiskMgmt): Array<{ label: string; value: string }> {
  const out: Array<{ label: string; value: string }> = [];
  for (const [k, v] of Object.entries(risk)) {
    if (v === null || v === undefined) continue;
    if (isPlainObject(v)) {
      // One level of nesting only — explode each primitive child as its
      // own row with the parent key prefixed (e.g. "Stop Loss · Price").
      for (const [childKey, childVal] of Object.entries(v)) {
        if (childVal === null || childVal === undefined) continue;
        if (isPlainObject(childVal) || Array.isArray(childVal)) continue;
        out.push({
          label: `${prettifyKey(k)} · ${prettifyKey(childKey)}`,
          value: formatRiskValue(childKey, childVal),
        });
      }
      continue;
    }
    if (Array.isArray(v)) continue;
    out.push({ label: prettifyKey(k), value: formatRiskValue(k, v) });
  }
  return out;
}

function RiskTable({ risk }: { risk: RiskMgmt }) {
  const rows = flattenRiskRows(risk);
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground text-sm font-mono">
        No risk fields.
      </p>
    );
  }
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
      {rows.map(({ label, value }) => (
        <div
          key={label}
          className="col-span-2 grid grid-cols-2 items-center border-b border-border last:border-b-0 pb-1.5"
        >
          <dt className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
            {label}
          </dt>
          <dd className="font-mono tabular-nums text-xs text-foreground text-right">
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
