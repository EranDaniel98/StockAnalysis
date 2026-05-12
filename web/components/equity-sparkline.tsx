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
import { fmtPct, fmtUSD, pnlColorClass } from "@/lib/format";

const MAX_POINTS = 360; // ~60 min @ 1 sample / 10s
const SAMPLE_MS = 10_000;

type Point = { t: number; equity: number };

/**
 * Tiny in-memory equity recorder. Samples the supplied `equity` value at
 * SAMPLE_MS intervals so a live-tick override doesn't flood the chart with
 * thousands of points. Persists in module-level memory across re-renders
 * but resets on hard reload — we don't have a server-side equity log yet.
 */
export function EquitySparkline({ equity }: { equity: number | null }) {
  const [points, setPoints] = useState<Point[]>([]);
  const lastSampleRef = useRef<number>(0);

  useEffect(() => {
    if (equity == null || Number.isNaN(equity)) return;
    const now = Date.now();
    if (now - lastSampleRef.current < SAMPLE_MS && points.length > 0) return;
    lastSampleRef.current = now;
    setPoints((prev) => {
      const next = [...prev, { t: now, equity }];
      // Drop the oldest entries once we exceed the window.
      return next.length > MAX_POINTS ? next.slice(next.length - MAX_POINTS) : next;
    });
  }, [equity, points.length]);

  if (points.length < 2) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardDescription>Equity (last hour)</CardDescription>
          <CardTitle className="text-2xl font-semibold tabular-nums">
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

  const first = points[0].equity;
  const last = points[points.length - 1].equity;
  const delta = last - first;
  const deltaPct = first !== 0 ? (delta / first) * 100 : 0;
  const positive = delta >= 0;
  const stroke = positive ? "#10b981" : "#ef4444";

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>
          Equity (last {Math.round((Date.now() - points[0].t) / 60_000) || 1}m)
        </CardDescription>
        <CardTitle className="flex items-baseline gap-2 text-2xl font-semibold tabular-nums">
          {fmtUSD(last)}
          <span className={`text-xs font-normal ${pnlColorClass(delta)}`}>
            {fmtUSD(delta)} ({fmtPct(deltaPct, 2, true)})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="h-16">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points}>
            <defs>
              <linearGradient id="eq-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={stroke} stopOpacity={0.5} />
                <stop offset="95%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Tooltip
              contentStyle={{
                background: "hsl(var(--popover))",
                border: "1px solid hsl(var(--border))",
                borderRadius: 8,
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
              fill="url(#eq-grad)"
              isAnimationActive={false}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
