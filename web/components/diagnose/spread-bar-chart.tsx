"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
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

export type SpreadBarRow = {
  /** Display label: "1d" | "5d" | "21d" | ... */
  period: string;
  /** Top-quantile mean return minus bottom-quantile mean return, in pct. */
  spread: number;
};

/**
 * Bloomberg-style quantile-spread bar chart. Renders the top-minus-bottom
 * cumulative return per horizon. Mint above zero (bullish edge), coral
 * below (inverted edge). Amber dashed reference line at y=0.
 */
export function SpreadBarChart({ rows }: { rows: SpreadBarRow[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} margin={{ top: 12, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid
          stroke={CHART_GRID}
          strokeOpacity={0.4}
          strokeDasharray="2 4"
          vertical={false}
        />
        <XAxis
          dataKey="period"
          stroke={CHART_AXIS}
          tick={{
            fill: CHART_AXIS,
            fontFamily: "var(--font-geist-mono)",
            fontSize: 10,
          }}
          tickLine={false}
          axisLine={{ stroke: CHART_GRID, strokeOpacity: 0.6 }}
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
          tickFormatter={(v) => `${(v as number).toFixed(1)}%`}
          width={56}
        />
        <Tooltip
          cursor={{ fill: CHART_GRID, fillOpacity: 0.25 }}
          contentStyle={{
            background: CHART_TOOLTIP_BG,
            border: `1px solid ${CHART_TOOLTIP_BORDER}`,
            borderRadius: 2,
            fontSize: 11,
            fontFamily: "var(--font-geist-mono)",
          }}
          labelFormatter={(label) => `HORIZON ${label}`}
          formatter={(value, name) => {
            if (value == null) return ["-", String(name).toUpperCase()];
            if (name === "spread") {
              return [`${(value as number).toFixed(2)}%`, "TOP - BOTTOM"];
            }
            return [String(value), String(name).toUpperCase()];
          }}
        />
        <ReferenceLine
          y={0}
          stroke={CHART_TOKEN.primary}
          strokeOpacity={0.6}
          strokeDasharray="3 3"
        />
        <Bar dataKey="spread" isAnimationActive={false} radius={[2, 2, 0, 0]}>
          {rows.map((r, i) => (
            <Cell
              key={i}
              fill={r.spread >= 0 ? CHART_TOKEN.bullish : CHART_TOKEN.bearish}
              fillOpacity={0.85}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
