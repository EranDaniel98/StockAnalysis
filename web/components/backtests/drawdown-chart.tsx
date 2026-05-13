"use client";

import { useMemo } from "react";
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

import {
  CHART_AXIS,
  CHART_GRID,
  CHART_TOKEN,
  CHART_TOOLTIP_BG,
  CHART_TOOLTIP_BORDER,
} from "@/lib/chart-tokens";

type EquityPoint = { date: string; equity: number };
type DDPoint = { date: string; drawdown: number };

/**
 * Derive a running-max drawdown series from the equity curve. The engine
 * exposes max_drawdown_pct in equity_stats but not the full path, so we
 * compute it client-side; it's a cheap O(N) pass on weekly samples.
 */
function deriveDrawdown(equity: EquityPoint[]): DDPoint[] {
  let peak = -Infinity;
  return equity.map((p) => {
    if (p.equity > peak) peak = p.equity;
    const dd = peak > 0 ? (p.equity / peak - 1) * 100 : 0;
    return { date: p.date, drawdown: Number(dd.toFixed(2)) };
  });
}

export function DrawdownChart({
  equity,
  splitDate,
}: {
  equity: EquityPoint[];
  splitDate?: string | null;
}) {
  const data = useMemo(() => deriveDrawdown(equity), [equity]);
  const dateFmt = (d: string | number) => {
    const dt = new Date(d);
    return Number.isNaN(dt.getTime())
      ? String(d)
      : dt.toLocaleDateString(undefined, { year: "2-digit", month: "short" });
  };

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
        <defs>
          <linearGradient id="bt-dd-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART_TOKEN.bearish} stopOpacity={0} />
            <stop offset="100%" stopColor={CHART_TOKEN.bearish} stopOpacity={0.18} />
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
          tick={{ fill: CHART_AXIS, fontFamily: "var(--font-geist-mono)", fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: CHART_GRID, strokeOpacity: 0.6 }}
          minTickGap={32}
        />
        <YAxis
          orientation="right"
          stroke={CHART_AXIS}
          tick={{ fill: CHART_AXIS, fontFamily: "var(--font-geist-mono)", fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v) => `${(v as number).toFixed(0)}%`}
          width={56}
          domain={["dataMin", 0]}
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
          formatter={(value) => [
            typeof value === "number" ? `${value.toFixed(2)}%` : String(value),
            "drawdown",
          ]}
        />
        {splitDate ? (
          <ReferenceLine
            x={splitDate}
            stroke={CHART_TOKEN.primary}
            strokeOpacity={0.6}
            strokeDasharray="3 3"
          />
        ) : null}
        <Area
          type="monotone"
          dataKey="drawdown"
          stroke={CHART_TOKEN.bearish}
          strokeWidth={1.25}
          fill="url(#bt-dd-fill)"
          fillOpacity={1}
          isAnimationActive={false}
          dot={false}
          activeDot={{ r: 3, fill: CHART_TOKEN.bearish, stroke: "none" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
