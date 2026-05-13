"use client";

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
import { fmtUSD } from "@/lib/format";

type Point = { date: string; equity: number };

/**
 * Bloomberg-style equity curve. Mint portfolio line with a near-flat
 * mint area fill (fillOpacity 0.06), amber vertical marker at the IS->OOS
 * split, hairline axis ticks in monospace. No legend chrome — the marker
 * label and the page header carry meaning.
 */
export function EquityCurveChart({
  equity,
  splitDate,
}: {
  equity: Point[];
  splitDate?: string | null;
}) {
  const dateFmt = (d: string | number) => {
    const dt = new Date(d);
    return Number.isNaN(dt.getTime())
      ? String(d)
      : dt.toLocaleDateString(undefined, { year: "2-digit", month: "short" });
  };

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={equity} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
        <defs>
          <linearGradient id="bt-equity-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={CHART_TOKEN.bullish} stopOpacity={0.12} />
            <stop offset="100%" stopColor={CHART_TOKEN.bullish} stopOpacity={0} />
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
          tickFormatter={(v) => fmtUSD(v as number, true)}
          width={56}
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
            typeof value === "number" ? fmtUSD(value) : String(value),
            "equity",
          ]}
        />
        {splitDate ? (
          <ReferenceLine
            x={splitDate}
            stroke={CHART_TOKEN.primary}
            strokeOpacity={0.85}
            strokeDasharray="3 3"
            label={{
              value: "OOS START",
              position: "top",
              fill: CHART_TOKEN.primary,
              fontSize: 9,
              fontFamily: "var(--font-geist-mono)",
              letterSpacing: 1,
            }}
          />
        ) : null}
        <Area
          type="monotone"
          dataKey="equity"
          stroke={CHART_TOKEN.bullish}
          strokeWidth={1.5}
          fill="url(#bt-equity-fill)"
          fillOpacity={1}
          isAnimationActive={false}
          dot={false}
          activeDot={{ r: 3, fill: CHART_TOKEN.bullish, stroke: "none" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
