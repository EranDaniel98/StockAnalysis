"use client";

import { useEffect, useRef, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip } from "recharts";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { fmtPct, fmtUSD } from "@/lib/format";

const MAX_POINTS = 360; // ~60 min @ 1 sample / 10s
const SAMPLE_MS = 10_000;

type Point = { t: number; equity: number };

function toneClass(n: number): string {
  if (Number.isNaN(n)) return "text-foreground";
  if (n > 0) return "text-bullish";
  if (n < 0) return "text-bearish";
  return "text-muted-foreground";
}

/**
 * Tiny in-memory equity recorder. Samples the supplied `equity` value at
 * SAMPLE_MS intervals so a live-tick override doesn't flood the chart with
 * thousands of points. Persists in module-level memory across re-renders
 * but resets on hard reload — we don't have a server-side equity log yet.
 *
 * `variant="inline"` strips the card chrome so the chart can be slotted
 * next to a scoreboard tile without nesting panels.
 */
export function EquitySparkline({
  equity,
  variant = "card",
  className,
}: {
  equity: number | null;
  variant?: "card" | "inline";
  className?: string;
}) {
  const [points, setPoints] = useState<Point[]>([]);
  const lastSampleRef = useRef<number>(0);

  useEffect(() => {
    if (equity == null || Number.isNaN(equity)) return;
    const now = Date.now();
    if (now - lastSampleRef.current < SAMPLE_MS && points.length > 0) return;
    lastSampleRef.current = now;
    setPoints((prev) => {
      const next = [...prev, { t: now, equity }];
      return next.length > MAX_POINTS ? next.slice(next.length - MAX_POINTS) : next;
    });
  }, [equity, points.length]);

  const ready = points.length >= 2;
  const first = ready ? points[0].equity : 0;
  const last = ready ? points[points.length - 1].equity : (equity ?? 0);
  const delta = ready ? last - first : 0;
  const deltaPct = ready && first !== 0 ? (delta / first) * 100 : 0;
  const positive = delta >= 0;
  // Profit mint vs loss coral via chart tokens — survives both themes.
  const stroke = positive ? "var(--chart-2)" : "var(--chart-4)";

  if (variant === "inline") {
    return (
      <div
        className={cn(
          "flex h-10 w-[120px] items-center justify-end",
          className,
        )}
        aria-label="Equity sparkline (last hour)"
      >
        {ready ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={points}
              margin={{ top: 2, right: 0, bottom: 2, left: 0 }}
            >
              <defs>
                <linearGradient id="eq-spark-inline" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={stroke} stopOpacity={0.18} />
                  <stop offset="100%" stopColor={stroke} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="equity"
                stroke={stroke}
                strokeWidth={1.5}
                fill="url(#eq-spark-inline)"
                fillOpacity={1}
                isAnimationActive={false}
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <span className="text-muted-foreground text-[10px] tracking-wider uppercase">
            collecting
          </span>
        )}
      </div>
    );
  }

  // Default card variant (kept for any consumer that still wants a panel).
  if (!ready) {
    return (
      <Card className={className}>
        <CardHeader className="pb-2">
          <CardDescription>Equity (last hour)</CardDescription>
          <CardTitle className="text-2xl font-mono font-semibold tabular-nums">
            {equity != null ? fmtUSD(equity) : "—"}
          </CardTitle>
        </CardHeader>
        <CardContent className="h-16">
          <p className="text-muted-foreground text-xs">
            Collecting samples… reload-persistent history is on the Phase 4
            roadmap.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={className}>
      <CardHeader className="pb-2">
        <CardDescription>
          Equity (last {Math.round((Date.now() - points[0].t) / 60_000) || 1}m)
        </CardDescription>
        <CardTitle className="flex items-baseline gap-2 text-2xl font-mono font-semibold tabular-nums">
          {fmtUSD(last)}
          <span
            className={cn("font-mono text-xs font-normal", toneClass(delta))}
          >
            {fmtUSD(delta)} ({fmtPct(deltaPct, 2, true)})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="h-16">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points}>
            <defs>
              <linearGradient id="eq-spark-card" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity={0.25} />
                <stop offset="100%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Tooltip
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 2,
                fontSize: 11,
              }}
              labelFormatter={(t) =>
                new Date(t as number).toLocaleTimeString()
              }
              formatter={(value) => [
                typeof value === "number" ? fmtUSD(value) : String(value),
                "equity",
              ]}
            />
            <Area
              type="monotone"
              dataKey="equity"
              stroke={stroke}
              strokeWidth={1.5}
              fillOpacity={1}
              fill="url(#eq-spark-card)"
              isAnimationActive={false}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
