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
  chartColor,
} from "@/lib/chart-tokens";

export type IcBarRow = {
  /** Display label: "1d" | "5d" | "21d" | ... */
  period: string;
  /** IC mean (Spearman) on this horizon. */
  ic: number;
  /** IC information ratio (mean / std). Optional, shown in tooltip. */
  ir?: number;
};

/**
 * Bloomberg-style IC-by-horizon bar chart. Each forward-window gets its
 * own colorblind-stable hue via chartColor(i) in the documented
 * chart-tokens order (cyan -> mint -> amber -> coral -> graphite). Bars
 * whose |IC| falls below the configured gate are dimmed via fillOpacity
 * so the eye picks up the "passes gate" horizons immediately.
 *
 * Amber dashed reference lines mark +/-gate; a second amber dashed line
 * at y=0 separates positive / negative IC.
 */
export function IcBarChart({
  rows,
  gate,
}: {
  rows: IcBarRow[];
  gate: number;
}) {
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
          tickFormatter={(v) => (v as number).toFixed(3)}
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
          formatter={(value, name, item) => {
            if (value == null) return ["-", String(name).toUpperCase()];
            if (name === "ic") {
              const ir = (item?.payload as { ir?: number } | undefined)?.ir;
              const irStr =
                ir != null && !Number.isNaN(ir)
                  ? ` (IR ${ir.toFixed(2)})`
                  : "";
              return [`${(value as number).toFixed(4)}${irStr}`, "IC MEAN"];
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
        <ReferenceLine
          y={gate}
          stroke={CHART_TOKEN.primary}
          strokeOpacity={0.35}
          strokeDasharray="2 4"
          label={{
            value: `GATE +${gate.toFixed(2)}`,
            position: "right",
            fill: CHART_TOKEN.primary,
            fontSize: 9,
            fontFamily: "var(--font-geist-mono)",
            letterSpacing: 1,
          }}
        />
        <ReferenceLine
          y={-gate}
          stroke={CHART_TOKEN.primary}
          strokeOpacity={0.35}
          strokeDasharray="2 4"
        />
        <Bar dataKey="ic" isAnimationActive={false} radius={[2, 2, 0, 0]}>
          {rows.map((r, i) => (
            <Cell
              key={i}
              fill={chartColor(i)}
              fillOpacity={Math.abs(r.ic) >= gate ? 0.9 : 0.3}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
