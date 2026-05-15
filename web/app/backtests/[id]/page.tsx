"use client";

import { useQuery } from "@tanstack/react-query";
import { use } from "react";

import { DrawdownChart } from "@/components/backtests/drawdown-chart";
import { EquityCurveChart } from "@/components/backtests/equity-curve-chart";
import { RegimeBreakdown } from "@/components/backtests/regime-breakdown";
import { SectionStatsTable } from "@/components/backtests/section-stats-table";
import { TradeTable, type Trade } from "@/components/backtests/trade-table";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtNumber, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

type EquityPoint = { date: string; equity: number; [k: string]: unknown };

type SectionSummary = {
  n_trades?: number;
  total_return_pct?: number;
  cagr_pct?: number;
  win_rate_pct?: number;
  expectancy_pct?: number;
  avg_hold_days?: number;
  sharpe_per_trade?: number;
  spy_return_pct?: number | null;
  alpha_vs_spy_pct?: number | null;
};
type SectionEquity = {
  max_drawdown_pct?: number;
  time_in_dd_pct?: number;
  ann_sharpe?: number;
  ann_sortino?: number;
  calmar?: number;
  ann_volatility_pct?: number;
};
type Section = { summary?: SectionSummary; equity_stats?: SectionEquity };

type Regimes = {
  spy_bull?: Record<string, number>;
  spy_bear?: Record<string, number>;
  vix_low?: Record<string, number>;
  vix_normal?: Record<string, number>;
  vix_high?: Record<string, number>;
};

type AdjustedSection = {
  total_return_pct?: number | null;
  cagr_pct?: number | null;
  ann_sharpe?: number | null;
  haircut_applied?: {
    annual_return_haircut_pct?: number;
    sharpe_haircut?: number;
    rationale?: string;
  };
};
type SurvivorshipBias = {
  applies?: boolean;
  severity?: string;
  magnitude_hint_annual_pct?: string;
  source?: string;
  details?: string;
  remediation?: string;
  universe_label?: string;
  adjusted?: {
    full?: AdjustedSection | null;
    out_of_sample?: AdjustedSection | null;
    method?: string;
  };
};
type DataQuality = {
  pipeline_version?: string;
  survivorship_bias?: SurvivorshipBias;
  n_tickers_traded?: number;
};

function toneClass(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "text-foreground";
  if (n > 0) return "text-bullish";
  if (n < 0) return "text-bearish";
  return "text-muted-foreground";
}

function toneFor(
  n: number | null | undefined,
): "bullish" | "bearish" | "neutral" | "muted" {
  if (n == null || Number.isNaN(n)) return "muted";
  if (n > 0) return "bullish";
  if (n < 0) return "bearish";
  return "neutral";
}

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

  const windowLabel = data
    ? `${new Date(data.window_start).toLocaleDateString()} -> ${new Date(data.window_end).toLocaleDateString()}`
    : "Loading...";

  return (
    <>
      <PageHeader
        title={data ? `Backtest #${data.id}` : "Backtest"}
        description={
          data
            ? `${data.strategy} | ${windowLabel}`
            : "Loading run metadata..."
        }
        actions={
          data ? (
            <Badge variant="outline" className="font-mono">
              {data.strategy}
            </Badge>
          ) : null
        }
      />

      {error ? <ErrorState error={error} /> : null}

      {isLoading || !data ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
          <Skeleton className="h-72 w-full" />
        </div>
      ) : (
        <BacktestDetail result={data.result} />
      )}
    </>
  );
}

function BacktestDetail({ result }: { result: Record<string, unknown> }) {
  const full = (result.full ?? {}) as Section;
  const inSample = (result.in_sample ?? {}) as Section;
  const outOfSample = (result.out_of_sample ?? {}) as Section;
  const equity = (result.equity_curve ?? []) as EquityPoint[];
  const trades = (result.trades ?? []) as Trade[];
  const regimes = (result.regimes ?? {}) as Regimes;
  const splitDate = (result.split_date ?? null) as string | null;
  const verdict = (result.verdict_oos ?? null) as string | null;
  const dataQuality = (result.data_quality ?? null) as DataQuality | null;

  const fullSummary = full.summary ?? {};
  const fullEq = full.equity_stats ?? {};
  const oosSummary = outOfSample.summary ?? {};
  const oosEq = outOfSample.equity_stats ?? {};

  const oosTradeShare =
    fullSummary.n_trades && oosSummary.n_trades != null
      ? `${oosSummary.n_trades}/${fullSummary.n_trades} OOS`
      : undefined;

  return (
    <div className="space-y-4">
      <DataQualityBanner quality={dataQuality} />
      {/* ── Scoreboard strip: 6 dense tiles ─────────────────────────────── */}
      <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
        <ScoreboardTile
          label="Total Return"
          value={
            <span className={cn(toneClass(fullSummary.total_return_pct))}>
              {fmtPct(fullSummary.total_return_pct, 2, true)}
            </span>
          }
          sub={
            fullSummary.cagr_pct != null
              ? `${fmtPct(fullSummary.cagr_pct, 2, true)} CAGR`
              : undefined
          }
          subTone={toneFor(fullSummary.cagr_pct)}
        />
        <ScoreboardTile
          label="OOS Return"
          value={
            <span className={cn(toneClass(oosSummary.total_return_pct))}>
              {fmtPct(oosSummary.total_return_pct, 2, true)}
            </span>
          }
          sub={
            oosSummary.alpha_vs_spy_pct != null
              ? `alpha ${fmtPct(oosSummary.alpha_vs_spy_pct, 2, true)}`
              : "vs SPY n/a"
          }
          subTone={toneFor(oosSummary.alpha_vs_spy_pct)}
        />
        <ScoreboardTile
          label="Full Sharpe"
          value={fmtNumber(fullEq.ann_sharpe, 2)}
          sub={
            fullEq.ann_sortino != null
              ? `Sortino ${fmtNumber(fullEq.ann_sortino, 2)}`
              : undefined
          }
          subTone="muted"
        />
        <ScoreboardTile
          label="OOS Sharpe"
          value={
            <span className={cn(toneClass(oosEq.ann_sharpe))}>
              {fmtNumber(oosEq.ann_sharpe, 2)}
            </span>
          }
          sub={
            oosEq.calmar != null
              ? `Calmar ${fmtNumber(oosEq.calmar, 2)}`
              : undefined
          }
          subTone={toneFor(oosEq.ann_sharpe)}
        />
        <ScoreboardTile
          label="Max DD"
          value={
            <span className={cn(toneClass(-(fullEq.max_drawdown_pct ?? 0)))}>
              {fmtPct(fullEq.max_drawdown_pct, 2)}
            </span>
          }
          sub={
            fullEq.time_in_dd_pct != null
              ? `${fmtPct(fullEq.time_in_dd_pct, 1)} time in DD`
              : undefined
          }
          subTone="muted"
        />
        <ScoreboardTile
          label="Win % / Trades"
          value={fmtPct(fullSummary.win_rate_pct, 1)}
          sub={
            oosTradeShare ??
            (fullSummary.n_trades != null
              ? `${fullSummary.n_trades} trades`
              : undefined)
          }
          subTone="muted"
        />
      </div>

      {verdict ? (
        <div className="border-border text-muted-foreground flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 font-mono text-[11px] tracking-wider uppercase">
          <span>OOS VERDICT</span>
          <span className="text-foreground">[ {verdict} ]</span>
          {splitDate ? (
            <span className="ml-auto">SPLIT {splitDate}</span>
          ) : null}
        </div>
      ) : null}

      {/* ── Equity curve + drawdown ─────────────────────────────────────── */}
      {equity.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Equity curve</span>
              <span className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
                {equity.length} weekly marks
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-64">
              <EquityCurveChart equity={equity} splitDate={splitDate} />
            </div>
            <div className="border-border mt-3 border-t pt-3">
              <div className="text-muted-foreground mb-1 font-mono text-[10px] tracking-wider uppercase">
                Drawdown (% from running peak)
              </div>
              <div className="h-32">
                <DrawdownChart equity={equity} splitDate={splitDate} />
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* ── IS / OOS / Full comparison ─────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Section stats</span>
            <span className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
              IS | OOS | Full
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <SectionStatsTable
            full={full}
            inSample={inSample}
            outOfSample={outOfSample}
            splitDate={splitDate}
          />
        </CardContent>
      </Card>

      {/* ── Regime breakdown (optional) ─────────────────────────────────── */}
      {regimes && Object.keys(regimes).length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Regime breakdown</span>
              <span className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
                trade entry context
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <RegimeBreakdown regimes={regimes} />
          </CardContent>
        </Card>
      ) : null}

      {/* ── Trades ─────────────────────────────────────────────────────── */}
      {trades.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Trades</span>
              <span className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
                {trades.length} closed
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="px-0">
            <TradeTable trades={trades} />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function DataQualityBanner({ quality }: { quality: DataQuality | null }) {
  if (!quality || !quality.survivorship_bias?.applies) return null;
  const sb = quality.survivorship_bias;
  const adjOos = sb.adjusted?.out_of_sample ?? null;
  const adjFull = sb.adjusted?.full ?? null;
  return (
    <div
      role="note"
      aria-label="Data quality warning"
      className="border-l-4 border-amber-500 bg-amber-500/10 px-4 py-3 text-sm"
    >
      <div className="flex items-baseline justify-between gap-3">
        <div className="font-semibold text-amber-700 dark:text-amber-300">
          Survivorship bias: {sb.severity ?? "uncorrected"}
          {sb.universe_label ? (
            <span className="text-muted-foreground ml-2 font-normal">
              · universe: <span className="font-mono">{sb.universe_label}</span>
            </span>
          ) : null}
        </div>
        {quality.pipeline_version ? (
          <div className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
            {quality.pipeline_version}
          </div>
        ) : null}
      </div>
      <p className="text-muted-foreground mt-1 leading-snug">
        {sb.details ?? "Universe excludes delisted tickers; headline numbers biased upward."}
      </p>
      {(adjOos || adjFull) ? (
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          {adjOos ? <AdjustedTile label="OOS (haircut-adjusted)" section={adjOos} /> : null}
          {adjFull ? <AdjustedTile label="Full (haircut-adjusted)" section={adjFull} /> : null}
        </div>
      ) : sb.magnitude_hint_annual_pct ? (
        <p className="text-muted-foreground mt-1 text-xs leading-snug">
          Magnitude hint: <span className="font-mono">{sb.magnitude_hint_annual_pct}%/yr</span>
        </p>
      ) : null}
      {sb.remediation ? (
        <p className="text-muted-foreground mt-2 text-xs italic leading-snug">
          {sb.remediation}
        </p>
      ) : null}
    </div>
  );
}

function AdjustedTile({ label, section }: { label: string; section: AdjustedSection }) {
  const h = section.haircut_applied;
  return (
    <div className="bg-background/40 rounded border border-amber-500/30 px-2 py-1.5 text-xs">
      <div className="font-mono text-[10px] tracking-wider text-amber-700 uppercase dark:text-amber-300">
        {label}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono">
        {section.ann_sharpe != null ? (
          <span>
            Sharpe <span className="font-semibold">{section.ann_sharpe.toFixed(2)}</span>
          </span>
        ) : null}
        {section.cagr_pct != null ? (
          <span>
            CAGR <span className="font-semibold">{section.cagr_pct.toFixed(2)}%</span>
          </span>
        ) : null}
        {section.total_return_pct != null ? (
          <span>
            Total <span className="font-semibold">{section.total_return_pct.toFixed(2)}%</span>
          </span>
        ) : null}
      </div>
      {h ? (
        <div className="text-muted-foreground mt-1 text-[10px]">
          haircut: -{h.annual_return_haircut_pct}%/yr, -{h.sharpe_haircut} Sharpe
          {h.rationale ? <span className="ml-1 italic">({h.rationale})</span> : null}
        </div>
      ) : null}
    </div>
  );
}
