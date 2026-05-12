"use client";

import { useQuery } from "@tanstack/react-query";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type SectorMetric } from "@/lib/api/client";
import { fmtPct } from "@/lib/format";

// Map a percentage return to a 0..1 intensity, clamped at ±5%.
function intensity(pct: number | null | undefined): number {
  if (pct == null) return 0;
  const clamped = Math.max(-5, Math.min(5, pct));
  return Math.abs(clamped) / 5;
}

function bgColor(pct: number | null | undefined): string {
  if (pct == null) return "hsl(var(--muted) / 0.4)";
  const i = intensity(pct);
  if (pct >= 0) return `hsl(152, 60%, ${20 + i * 25}%)`;
  return `hsl(0, 65%, ${22 + i * 25}%)`;
}

function SectorTile({ s }: { s: SectorMetric }) {
  return (
    <Card
      className="border-border/60 overflow-hidden"
      style={{ backgroundColor: bgColor(s.return_5d_pct) }}
    >
      <CardContent className="space-y-2 p-4">
        <div className="flex items-baseline justify-between">
          <span className="font-mono text-xs opacity-70">{s.ticker}</span>
          {s.above_sma50 == null ? null : (
            <span className="text-[10px] opacity-70">
              {s.above_sma50 ? "▲ trend" : "▼ trend"}
            </span>
          )}
        </div>
        <h3 className="text-sm font-medium">{s.name}</h3>
        <div className="space-y-1 text-xs">
          <div className="flex justify-between">
            <span className="opacity-70">1d</span>
            <span className="tabular-nums">
              {fmtPct(s.return_1d_pct, 2, true)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="opacity-70">5d</span>
            <span className="font-semibold tabular-nums">
              {fmtPct(s.return_5d_pct, 2, true)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="opacity-70">21d</span>
            <span className="tabular-nums">
              {fmtPct(s.return_21d_pct, 2, true)}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function SectorsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["market", "sectors"],
    queryFn: () => api.market.sectors(),
    refetchInterval: 5 * 60_000,
  });

  return (
    <>
      <PageHeader
        title="Sector rotation"
        description="SPDR Select Sector ETFs. Tile color tracks the 5-day return (red ↔ green, clamped at ±5%)."
      />

      {error ? <ErrorState error={error} /> : null}

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 11 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : data ? (
        <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
          {(data.sectors ?? []).map((s) => (
            <SectorTile key={s.ticker} s={s} />
          ))}
        </div>
      ) : null}
    </>
  );
}
