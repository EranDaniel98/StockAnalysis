"use client";

import { Badge } from "@/components/ui/badge";
import { fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

type RegimeStats = {
  n?: number;
  win_rate_pct?: number;
  avg_return_pct?: number;
  expectancy_pct?: number;
  total_pnl?: number;
};

type RegimePayload = {
  spy_bull?: RegimeStats;
  spy_bear?: RegimeStats;
  vix_low?: RegimeStats;
  vix_normal?: RegimeStats;
  vix_high?: RegimeStats;
};

/**
 * Compact regime grid: SPY bull/bear + VIX low/normal/high. Each tile
 * shows trade count, win-rate, average return. Per-tile color tone
 * follows the bullish/bearish/neutral semantics — bull → bullish badge,
 * bear → bearish badge, etc.
 */
export function RegimeBreakdown({ regimes }: { regimes: RegimePayload }) {
  const rows: Array<{
    label: string;
    badge: "bullish" | "bearish" | "neutral";
    stats?: RegimeStats;
  }> = [
    { label: "SPY BULL", badge: "bullish", stats: regimes.spy_bull },
    { label: "SPY BEAR", badge: "bearish", stats: regimes.spy_bear },
    { label: "VIX LOW", badge: "bullish", stats: regimes.vix_low },
    { label: "VIX NORMAL", badge: "neutral", stats: regimes.vix_normal },
    { label: "VIX HIGH", badge: "bearish", stats: regimes.vix_high },
  ];

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {rows.map((r) => {
        const s = r.stats ?? {};
        const n = s.n ?? 0;
        const winColor =
          (s.win_rate_pct ?? 0) >= 50 ? "text-bullish" : "text-bearish";
        const avgColor =
          (s.avg_return_pct ?? 0) > 0
            ? "text-bullish"
            : (s.avg_return_pct ?? 0) < 0
              ? "text-bearish"
              : "text-muted-foreground";
        return (
          <div
            key={r.label}
            className="border-border bg-card rounded-md border p-2"
          >
            <div className="flex items-center justify-between">
              <Badge variant={r.badge}>{r.label}</Badge>
              <span className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
                n={n}
              </span>
            </div>
            {n > 0 ? (
              <div className="mt-2 grid grid-cols-2 gap-1 font-mono text-[11px] tabular-nums">
                <div>
                  <div className="text-muted-foreground text-[9px] tracking-wider uppercase">
                    Win
                  </div>
                  <div className={cn(winColor)}>
                    {fmtPct(s.win_rate_pct, 1)}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-muted-foreground text-[9px] tracking-wider uppercase">
                    Avg
                  </div>
                  <div className={cn(avgColor)}>
                    {fmtPct(s.avg_return_pct, 2, true)}
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-muted-foreground mt-2 font-mono text-[10px] tracking-wider uppercase">
                no trades
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
