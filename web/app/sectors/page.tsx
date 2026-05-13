"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type SectorMetric } from "@/lib/api/client";
import { fmtPct, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

// ±5% caps the heatmap saturation so a single melt-up day doesn't wash the grid.
function intensity(pct: number | null | undefined): number {
  if (pct == null) return 0;
  const clamped = Math.max(-5, Math.min(5, pct));
  return Math.abs(clamped) / 5;
}

function tileBg(pct: number | null | undefined): string {
  if (pct == null) return "transparent";
  const token = pct >= 0 ? "var(--bullish)" : "var(--bearish)";
  const alpha = Math.round(intensity(pct) * 40);
  return `color-mix(in oklch, ${token} ${alpha}%, transparent)`;
}

function ReturnRow({
  label,
  pct,
  emphasis = false,
}: {
  label: string;
  pct: number | null | undefined;
  emphasis?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          "font-mono tabular-nums",
          emphasis ? "text-base font-semibold" : "text-sm",
          pnlColorClass(pct),
        )}
      >
        {fmtPct(pct, 2, true)}
      </span>
    </div>
  );
}

function SectorTile({ s }: { s: SectorMetric }) {
  return (
    <Card
      className="border border-border overflow-hidden"
      style={{ backgroundColor: tileBg(s.return_5d_pct) }}
    >
      <CardContent className="space-y-2 p-4">
        <div className="flex items-baseline justify-between">
          <span className="font-mono text-sm font-semibold tracking-wider">
            {s.ticker}
          </span>
          {s.above_sma50 == null ? null : (
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              SMA50{" "}
              <span
                className={cn(
                  "font-mono",
                  s.above_sma50 ? "text-bullish" : "text-bearish",
                )}
              >
                {s.above_sma50 ? "+" : "−"}
              </span>
            </span>
          )}
        </div>
        <h3 className="text-xs uppercase tracking-wider text-muted-foreground">
          {s.name}
        </h3>
        <div className="space-y-1">
          <ReturnRow label="1d" pct={s.return_1d_pct} />
          <ReturnRow label="5d" pct={s.return_5d_pct} emphasis />
          <ReturnRow label="21d" pct={s.return_21d_pct} />
        </div>
      </CardContent>
    </Card>
  );
}

type Summary = {
  total: number;
  nPositive: number;
  positivePct: number;
  avg5d: number | null;
  leader: SectorMetric | null;
  laggard: SectorMetric | null;
};

function summarise(sectors: SectorMetric[]): Summary {
  let nPositive = 0;
  let sum = 0;
  let count = 0;
  let leader: SectorMetric | null = null;
  let laggard: SectorMetric | null = null;
  for (const s of sectors) {
    const r = s.return_5d_pct;
    if (r === null || r === undefined || Number.isNaN(r)) continue;
    if (r > 0) nPositive += 1;
    sum += r;
    count += 1;
    if (leader === null || r > (leader.return_5d_pct ?? -Infinity)) leader = s;
    if (laggard === null || r < (laggard.return_5d_pct ?? Infinity)) laggard = s;
  }
  const total = sectors.length;
  return {
    total,
    nPositive,
    positivePct: total > 0 ? (nPositive / total) * 100 : 0,
    avg5d: count > 0 ? sum / count : null,
    leader,
    laggard,
  };
}

export default function SectorsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["market", "sectors"],
    queryFn: () => api.market.sectors(),
    refetchInterval: 5 * 60_000,
  });

  const sectors = data?.sectors ?? [];
  const summary = useMemo(() => summarise(sectors), [sectors]);

  const breadthTone: "bullish" | "bearish" | "neutral" =
    summary.total === 0
      ? "neutral"
      : summary.positivePct >= 60
        ? "bullish"
        : summary.positivePct <= 40
          ? "bearish"
          : "neutral";

  const avgTone =
    summary.avg5d === null
      ? "muted"
      : summary.avg5d > 0
        ? "bullish"
        : summary.avg5d < 0
          ? "bearish"
          : "neutral";

  return (
    <>
      <PageHeader
        title="Sector rotation"
        description="SPDR Select Sector ETFs. Tile color tracks the 5-day return (bullish ↔ bearish, clamped at ±5%)."
      />

      {error ? <ErrorState error={error} /> : null}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <ScoreboardTile
          label="Breadth (5d)"
          value={
            isLoading || summary.total === 0
              ? "—"
              : `${summary.nPositive}/${summary.total}`
          }
          sub={
            isLoading || summary.total === 0
              ? undefined
              : `${summary.positivePct.toFixed(0)}% positive`
          }
          subTone={breadthTone === "neutral" ? "muted" : breadthTone}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Avg 5d"
          value={
            isLoading || summary.avg5d === null ? (
              "—"
            ) : (
              <span className={pnlColorClass(summary.avg5d)}>
                {fmtPct(summary.avg5d, 2, true)}
              </span>
            )
          }
          sub={
            isLoading || summary.total === 0
              ? undefined
              : `across ${summary.total} sectors`
          }
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Leader"
          value={isLoading || !summary.leader ? "—" : summary.leader.ticker}
          sub={
            isLoading || !summary.leader
              ? undefined
              : fmtPct(summary.leader.return_5d_pct, 2, true)
          }
          subTone={avgTone === "muted" ? "muted" : "bullish"}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Laggard"
          value={isLoading || !summary.laggard ? "—" : summary.laggard.ticker}
          sub={
            isLoading || !summary.laggard
              ? undefined
              : fmtPct(summary.laggard.return_5d_pct, 2, true)
          }
          subTone={avgTone === "muted" ? "muted" : "bearish"}
          isLoading={isLoading}
        />
      </div>

      {isLoading ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 11 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : data ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
          {sectors.map((s) => (
            <SectorTile key={s.ticker} s={s} />
          ))}
        </div>
      ) : null}
    </>
  );
}
