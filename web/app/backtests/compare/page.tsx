"use client";

import { useQueries } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";

import {
  CompareDrawdownChart,
  type CompareDrawdownSeries,
} from "@/components/backtests/compare-drawdown-chart";
import {
  CompareEquityChart,
  type CompareEquitySeries,
} from "@/components/backtests/compare-equity-chart";
import {
  CompareStatsTable,
  type CompareStatRun,
} from "@/components/backtests/compare-stats-table";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { chartColor } from "@/lib/chart-tokens";
import { fmtNumber, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

type EquityPoint = { date: string; equity: number };
type SectionSummary = {
  n_trades?: number;
  total_return_pct?: number;
  win_rate_pct?: number;
  alpha_vs_spy_pct?: number | null;
};
type SectionEquity = {
  max_drawdown_pct?: number;
  ann_sharpe?: number;
};
type Section = { summary?: SectionSummary; equity_stats?: SectionEquity };

const COMPARE_MIN = 2;
const COMPARE_MAX = 5;

function toneClass(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "text-foreground";
  if (n > 0) return "text-bullish";
  if (n < 0) return "text-bearish";
  return "text-muted-foreground";
}

type BacktestDetail = Awaited<ReturnType<typeof api.backtests.get>>;

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
    .filter((n) => Number.isFinite(n) && n > 0)
    .slice(0, COMPARE_MAX);

  if (ids.length < COMPARE_MIN) {
    return (
      <>
        <PageHeader
          title="Compare backtests"
          description="Multi-run overlay of equity curves, drawdowns, and OOS statistics."
        />
        <EmptyCompareState reason="few" selected={ids.length} />
      </>
    );
  }

  const queries = useQueries({
    queries: ids.map((id) => ({
      queryKey: qk.backtests.detail(id),
      queryFn: () => api.backtests.get(id),
    })),
  });

  const loading = queries.some((q) => q.isLoading);
  const failed = queries.find((q) => q.error);

  if (failed) {
    return (
      <>
        <PageHeader
          title="Compare backtests"
          description={`Comparing ${ids.length} runs`}
        />
        <ErrorState error={failed.error} />
      </>
    );
  }

  if (loading) {
    return (
      <>
        <PageHeader
          title="Compare backtests"
          description={`Loading ${ids.length} runs...`}
        />
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-5">
            {Array.from({ length: ids.length }).map((_, i) => (
              <Skeleton key={i} className="h-24 w-full" />
            ))}
          </div>
          <Skeleton className="h-80 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      </>
    );
  }

  const runs = queries
    .map((q, i) => ({ id: ids[i], data: q.data }))
    .filter(
      (r): r is { id: number; data: NonNullable<typeof r.data> } => !!r.data,
    );

  if (runs.length < COMPARE_MIN) {
    return (
      <>
        <PageHeader title="Compare backtests" />
        <EmptyCompareState reason="missing" selected={runs.length} />
      </>
    );
  }

  return <CompareView runs={runs} />;
}

function CompareView({
  runs,
}: {
  runs: Array<{ id: number; data: BacktestDetail }>;
}) {
  const enriched = useMemo(() => {
    return runs.map((r, i) => {
      const result = (r.data.result ?? {}) as Record<string, unknown>;
      const full = (result.full ?? {}) as Section;
      const oos = (result.out_of_sample ?? {}) as Section;
      const equity = (result.equity_curve ?? []) as EquityPoint[];
      const splitDate = (result.split_date ?? null) as string | null;
      return {
        id: r.id,
        index: i,
        strategy: r.data.strategy,
        windowStart: r.data.window_start,
        windowEnd: r.data.window_end,
        equity,
        splitDate,
        full,
        oos,
        color: chartColor(i),
      };
    });
  }, [runs]);

  const cohortStart = useMemo(() => {
    const ts = enriched
      .map((r) => new Date(r.windowStart).getTime())
      .filter((t) => !Number.isNaN(t));
    return ts.length ? new Date(Math.min(...ts)) : null;
  }, [enriched]);
  const cohortEnd = useMemo(() => {
    const ts = enriched
      .map((r) => new Date(r.windowEnd).getTime())
      .filter((t) => !Number.isNaN(t));
    return ts.length ? new Date(Math.max(...ts)) : null;
  }, [enriched]);

  const yearFmt = (d: Date) => d.getFullYear().toString();
  const cohortLabel =
    cohortStart && cohortEnd
      ? `${yearFmt(cohortStart)}-${yearFmt(cohortEnd)}`
      : "—";

  const splitDates = new Set(
    enriched
      .map((r) => r.splitDate ?? null)
      .filter((d): d is string => !!d),
  );
  const splitRangeLabel = (() => {
    if (splitDates.size === 0) return null;
    if (splitDates.size === 1) return `OOS SPLIT ${[...splitDates][0]}`;
    const ts = [...splitDates]
      .map((d) => new Date(d).getTime())
      .filter((t) => !Number.isNaN(t))
      .sort((a, b) => a - b);
    if (ts.length === 0) return null;
    const fmt = (t: number) =>
      new Date(t).toLocaleDateString(undefined, {
        year: "2-digit",
        month: "short",
        day: "2-digit",
      });
    return `OOS SPLIT [ ${fmt(ts[0])} -> ${fmt(ts[ts.length - 1])} ]`;
  })();

  // Verdict: based on OOS Sharpe delta. Mirrors the calibration verdict.
  const oosSharpes = enriched
    .map((r) => ({ id: r.id, strategy: r.strategy, v: r.oos.equity_stats?.ann_sharpe }))
    .filter(
      (x): x is { id: number; strategy: string; v: number } =>
        x.v != null && !Number.isNaN(x.v),
    );
  let verdict: string;
  let verdictTone: "bullish" | "bearish" | "neutral" | "muted";
  if (oosSharpes.length < 2) {
    verdict = "INSUFFICIENT DATA";
    verdictTone = "muted";
  } else {
    const sorted = [...oosSharpes].sort((a, b) => b.v - a.v);
    const top = sorted[0];
    const second = sorted[1];
    const delta = top.v - second.v;
    if (delta < 0.1) {
      verdict = "TIE";
      verdictTone = "neutral";
    } else {
      verdict = `${top.strategy.toUpperCase()} (#${top.id}) WINS`;
      verdictTone = "bullish";
    }
  }

  const equitySeries: CompareEquitySeries[] = enriched.map((r) => ({
    key: `run_${r.id}`,
    name: `${r.strategy} #${r.id}`,
    points: r.equity,
    splitDate: r.splitDate,
  }));
  const drawdownSeries: CompareDrawdownSeries[] = enriched.map((r) => ({
    key: `run_${r.id}`,
    name: `${r.strategy} #${r.id}`,
    points: r.equity,
    splitDate: r.splitDate,
  }));

  const statRuns: CompareStatRun[] = enriched.map((r) => ({
    key: `run_${r.id}`,
    label: `${r.strategy} #${r.id}`,
    fullSharpe: r.full.equity_stats?.ann_sharpe ?? null,
    oosSharpe: r.oos.equity_stats?.ann_sharpe ?? null,
    oosReturnPct: r.oos.summary?.total_return_pct ?? null,
    maxDrawdownPct: r.full.equity_stats?.max_drawdown_pct ?? null,
    winRatePct: r.full.summary?.win_rate_pct ?? null,
    nTrades: r.full.summary?.n_trades ?? null,
  }));

  const hasEquity = enriched.some((r) => r.equity.length > 0);

  return (
    <>
      <PageHeader
        title="Compare backtests"
        description={`Comparing ${enriched.length} runs over ${cohortLabel}.`}
      />

      {/* ── Per-run scoreboard, color-coded ─────────────────────────────── */}
      <div
        className={cn(
          "grid gap-3",
          enriched.length === 2
            ? "md:grid-cols-2"
            : enriched.length === 3
              ? "md:grid-cols-3"
              : enriched.length === 4
                ? "md:grid-cols-2 lg:grid-cols-4"
                : "md:grid-cols-3 lg:grid-cols-5",
        )}
      >
        {enriched.map((r) => {
          const sharpe = r.oos.equity_stats?.ann_sharpe;
          const trades = r.full.summary?.n_trades;
          const win = r.full.summary?.win_rate_pct;
          return (
            <Card
              key={r.id}
              size="sm"
              className="gap-1.5 border-l-2"
              style={{ borderLeftColor: r.color }}
            >
              <div className="flex items-center justify-between gap-2 px-2 pt-1">
                <span
                  className="font-mono text-[10px] font-medium tracking-wider uppercase truncate"
                  style={{ color: r.color }}
                >
                  {r.strategy}
                </span>
                <Link
                  href={`/backtests/${r.id}`}
                  className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground hover:text-foreground"
                >
                  #{r.id}
                </Link>
              </div>
              <div className="flex items-end justify-between gap-2 px-2 pb-1">
                <div className="flex flex-col gap-0.5 min-w-0">
                  <output
                    className={cn(
                      "font-mono text-2xl leading-none font-semibold tabular-nums truncate",
                      toneClass(sharpe),
                    )}
                  >
                    {fmtNumber(sharpe, 2)}
                  </output>
                  <span className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                    OOS Sharpe
                  </span>
                </div>
                <div className="flex flex-col items-end gap-0.5 text-right">
                  <span className="font-mono text-[11px] tabular-nums text-foreground">
                    {trades == null ? "—" : trades}
                  </span>
                  <span
                    className={cn(
                      "font-mono text-[11px] tabular-nums",
                      win == null
                        ? "text-muted-foreground"
                        : win >= 55
                          ? "text-bullish"
                          : win < 45
                            ? "text-bearish"
                            : "text-foreground",
                    )}
                  >
                    {fmtPct(win, 1)}
                  </span>
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      {/* ── Verdict strip ───────────────────────────────────────────────── */}
      <div className="mt-4 border-border text-muted-foreground flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 font-mono text-[11px] tracking-wider uppercase">
        <span>Comparison Verdict</span>
        <span
          className={cn(
            verdictTone === "bullish"
              ? "text-bullish"
              : verdictTone === "muted"
                ? "text-muted-foreground"
                : "text-foreground",
          )}
        >
          [ {verdict} ]
        </span>
        {splitRangeLabel ? (
          <span className="ml-auto">{splitRangeLabel}</span>
        ) : null}
      </div>

      {/* ── Equity-curve overlay ────────────────────────────────────────── */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Equity curves overlay</span>
            <span className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
              {enriched.length} runs | click legend to toggle
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {hasEquity ? (
            <div className="h-80">
              <CompareEquityChart series={equitySeries} />
            </div>
          ) : (
            <div className="flex h-40 items-center justify-center font-mono text-[11px] tracking-wider uppercase text-muted-foreground">
              No equity samples available across these runs.
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Drawdown overlay ────────────────────────────────────────────── */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Drawdown overlay</span>
            <span className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
              % from running peak
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {hasEquity ? (
            <div className="h-64">
              <CompareDrawdownChart series={drawdownSeries} />
            </div>
          ) : (
            <div className="flex h-40 items-center justify-center font-mono text-[11px] tracking-wider uppercase text-muted-foreground">
              No drawdown samples available.
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Stat comparison table ───────────────────────────────────────── */}
      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>Stat comparison</span>
            <span className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
              best | worst per row
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <CompareStatsTable runs={statRuns} />
        </CardContent>
      </Card>
    </>
  );
}

function EmptyCompareState({
  reason,
  selected,
}: {
  reason: "few" | "missing";
  selected: number;
}) {
  const msg =
    reason === "missing"
      ? `Only ${selected} of the selected runs returned data. Pick ${COMPARE_MIN}-${COMPARE_MAX} valid runs from the index.`
      : `Select ${COMPARE_MIN}-${COMPARE_MAX} runs from the index to compare.`;
  return (
    <div className="border-border rounded-md border bg-card px-3 py-12 text-center">
      <p className="font-mono text-xs tracking-wider text-muted-foreground uppercase">
        {msg}
      </p>
      <Link
        href="/backtests"
        className="mt-3 inline-block font-mono text-[11px] tracking-wider uppercase text-foreground hover:text-bullish"
      >
        [ Back to runs index -&gt; ]
      </Link>
    </div>
  );
}
