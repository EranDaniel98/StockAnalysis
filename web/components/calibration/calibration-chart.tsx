"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
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

export type CalibrationBucketRow = {
  label: string;
  lower: number;
  upper: number;
  n_trades: number;
  avg_pnl_pct?: number | null;
  median_pnl_pct?: number | null;
  win_rate?: number | null;
};

/**
 * Bloomberg-style score-vs-return calibration bar chart.
 *
 * Each bin is a cyan info-tone bar for the *realized* average pnl%. A coral
 * tint is used when the bar value goes negative so the eye picks up
 * miscalibration at a glance. An amber dashed line overlays the *ideal
 * monotone trend* — a synthetic series that climbs linearly across the
 * non-empty bins (slope chosen so its endpoints match the bar series'
 * min/max). The reference line at y=0 is amber as well, keeping the
 * primary highlight color reserved for "the calibration target".
 */
export function CalibrationChart({
  buckets,
}: {
  buckets: CalibrationBucketRow[];
}) {
  const populated = buckets.filter((b) => b.n_trades > 0);
  // Ideal-trend line: linear interpolation between min(avg_pnl) and
  // max(avg_pnl) across populated bins. Empty bins get a null so Recharts
  // skips them on the line series.
  const values = populated
    .map((b) => b.avg_pnl_pct)
    .filter((v): v is number => v != null);
  const lo = values.length > 0 ? Math.min(...values) : 0;
  const hi = values.length > 0 ? Math.max(...values) : 0;

  let popIdx = -1;
  const data = buckets.map((b) => {
    const hasValue = b.n_trades > 0 && b.avg_pnl_pct != null;
    if (hasValue) popIdx += 1;
    const ideal =
      hasValue && populated.length > 1
        ? lo + ((hi - lo) * popIdx) / (populated.length - 1)
        : hasValue
          ? lo
          : null;
    return {
      label: b.label,
      avg_pnl_pct: b.avg_pnl_pct,
      ideal,
      n_trades: b.n_trades,
    };
  });

  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart
        data={data}
        margin={{ top: 12, right: 8, bottom: 0, left: 8 }}
      >
        <CartesianGrid
          stroke={CHART_GRID}
          strokeOpacity={0.4}
          strokeDasharray="2 4"
          vertical={false}
        />
        <XAxis
          dataKey="label"
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
          formatter={(value, name) => {
            if (value == null) return ["-", String(name)];
            if (name === "avg_pnl_pct") {
              return [
                `${(value as number).toFixed(2)}%`,
                "AVG REALIZED",
              ];
            }
            if (name === "ideal") {
              return [`${(value as number).toFixed(2)}%`, "IDEAL TREND"];
            }
            return [String(value), String(name)];
          }}
          labelFormatter={(label, payload) => {
            const n =
              payload && payload.length > 0
                ? (payload[0].payload as { n_trades?: number }).n_trades
                : undefined;
            return n != null ? `BIN ${label} | n=${n}` : `BIN ${label}`;
          }}
        />
        <ReferenceLine
          y={0}
          stroke={CHART_TOKEN.primary}
          strokeOpacity={0.5}
          strokeDasharray="3 3"
        />
        <Bar
          dataKey="avg_pnl_pct"
          isAnimationActive={false}
          barSize={32}
          radius={[2, 2, 0, 0]}
        >
          {data.map((d, i) => (
            <Cell
              key={i}
              fill={
                d.avg_pnl_pct == null
                  ? CHART_TOKEN.neutral
                  : (d.avg_pnl_pct as number) >= 0
                    ? CHART_TOKEN.info
                    : CHART_TOKEN.bearish
              }
              fillOpacity={d.avg_pnl_pct == null ? 0.25 : 0.85}
            />
          ))}
        </Bar>
        <Line
          type="linear"
          dataKey="ideal"
          stroke={CHART_TOKEN.primary}
          strokeWidth={1.25}
          strokeDasharray="4 4"
          dot={{ r: 2, fill: CHART_TOKEN.primary, stroke: "none" }}
          activeDot={{ r: 3, fill: CHART_TOKEN.primary, stroke: "none" }}
          isAnimationActive={false}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
