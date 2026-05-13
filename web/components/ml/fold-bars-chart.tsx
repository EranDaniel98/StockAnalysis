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

type Fold = { test_start: string; ic_pearson: number };

/**
 * Per-fold Pearson IC mini chart. Mint bars above zero, coral below zero,
 * amber zero-reference line. Identical token / style language as the
 * calibration chart so the two pages read as the same product.
 */
export function FoldBarsChart({ folds }: { folds: Fold[] }) {
  const bars = folds.map((f) => ({
    label: f.test_start.slice(5, 10),
    ic: f.ic_pearson,
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={bars} margin={{ top: 8, right: 4, bottom: 0, left: 4 }}>
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
            fontSize: 9,
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
            fontSize: 9,
          }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v) => (v as number).toFixed(2)}
          width={40}
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
          formatter={(value) =>
            typeof value === "number"
              ? [value.toFixed(4), "IC"]
              : [String(value ?? ""), "IC"]
          }
        />
        <ReferenceLine
          y={0}
          stroke={CHART_TOKEN.primary}
          strokeOpacity={0.5}
          strokeDasharray="3 3"
        />
        <Bar
          dataKey="ic"
          isAnimationActive={false}
          radius={[2, 2, 0, 0]}
          barSize={18}
        >
          {bars.map((b, i) => (
            <Cell
              key={i}
              fill={b.ic >= 0 ? CHART_TOKEN.bullish : CHART_TOKEN.bearish}
              fillOpacity={0.85}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
