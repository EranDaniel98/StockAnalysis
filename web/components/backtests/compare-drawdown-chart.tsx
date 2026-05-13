"use client";

import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
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
import { cn } from "@/lib/utils";

export type CompareDrawdownSeries = {
  key: string;
  name: string;
  points: { date: string; equity: number }[];
  splitDate?: string | null;
};

type Row = {
  date: string;
  [key: string]: number | string | null | undefined;
};

/** O(N) running-max drawdown path. */
function deriveDrawdown(
  points: { date: string; equity: number }[],
): { date: string; drawdown: number }[] {
  let peak = -Infinity;
  return points.map((p) => {
    if (p.equity > peak) peak = p.equity;
    const dd = peak > 0 ? (p.equity / peak - 1) * 100 : 0;
    return { date: p.date, drawdown: Number(dd.toFixed(2)) };
  });
}

/**
 * Drawdown overlay paired with `CompareEquityChart`. N coral-tinted areas,
 * one per run via `chartColor(i)`. Fill opacity is intentionally low
 * (~0.08) so multiple curves coexist without drowning each other.
 *
 * Mirrors the equity-overlay legend pattern (click-to-toggle, mono chips).
 */
export function CompareDrawdownChart({
  series,
}: {
  series: CompareDrawdownSeries[];
}) {
  const { rows, sharedSplit } = useMemo(() => {
    const index = new Map<string, Row>();
    for (const s of series) {
      const dd = deriveDrawdown(s.points);
      for (const p of dd) {
        const row = index.get(p.date) ?? { date: p.date };
        row[s.key] = p.drawdown;
        index.set(p.date, row);
      }
    }
    const out: Row[] = [...index.values()].sort((a, b) =>
      String(a.date).localeCompare(String(b.date)),
    );
    const splits = new Set(
      series
        .map((s) => s.splitDate ?? null)
        .filter((d): d is string => !!d),
    );
    const sharedSplit = splits.size === 1 ? [...splits][0] : null;
    return { rows: out, sharedSplit };
  }, [series]);

  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const onLegendClick = (entry: unknown) => {
    const raw = (entry as { dataKey?: unknown }).dataKey;
    if (typeof raw !== "string" && typeof raw !== "number") return;
    const k = String(raw);
    if (!k) return;
    setHidden((prev) => ({ ...prev, [k]: !prev[k] }));
  };

  if (rows.length === 0) {
    return (
      <div className="flex h-full items-center justify-center font-mono text-xs tracking-wider text-muted-foreground uppercase">
        No drawdown samples.
      </div>
    );
  }

  const dateFmt = (d: string | number) => {
    const dt = new Date(d);
    return Number.isNaN(dt.getTime())
      ? String(d)
      : dt.toLocaleDateString(undefined, { year: "2-digit", month: "short" });
  };

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
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
          tick={{
            fill: CHART_AXIS,
            fontFamily: "var(--font-geist-mono)",
            fontSize: 10,
          }}
          tickLine={false}
          axisLine={{ stroke: CHART_GRID, strokeOpacity: 0.6 }}
          minTickGap={32}
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
          tickFormatter={(v) => `${(v as number).toFixed(0)}%`}
          width={56}
          domain={["dataMin", 0]}
        />
        <Tooltip
          cursor={{
            stroke: CHART_GRID,
            strokeOpacity: 0.6,
            strokeDasharray: "2 4",
          }}
          contentStyle={{
            background: CHART_TOOLTIP_BG,
            border: `1px solid ${CHART_TOOLTIP_BORDER}`,
            borderRadius: 2,
            fontSize: 11,
            fontFamily: "var(--font-geist-mono)",
          }}
          labelFormatter={(d) => new Date(d as string).toLocaleDateString()}
          formatter={(value, name) => {
            if (value == null) return ["-", String(name).toUpperCase()];
            return [
              typeof value === "number" ? `${value.toFixed(2)}%` : String(value),
              String(name).toUpperCase(),
            ];
          }}
        />
        {sharedSplit ? (
          <ReferenceLine
            x={sharedSplit}
            stroke={CHART_TOKEN.primary}
            strokeOpacity={0.6}
            strokeDasharray="3 3"
          />
        ) : null}
        {series.map((s, i) => (
          <Area
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.name}
            stroke={chartColor(i)}
            strokeWidth={1.25}
            fill={chartColor(i)}
            fillOpacity={0.08}
            isAnimationActive={false}
            connectNulls
            hide={hidden[s.key]}
            dot={false}
            activeDot={{ r: 3, fill: chartColor(i), stroke: "none" }}
          />
        ))}
        <Legend
          verticalAlign="bottom"
          height={28}
          iconType="plainline"
          onClick={onLegendClick}
          formatter={(value, entry) => {
            const dk = (entry as { dataKey?: unknown }).dataKey;
            const key = typeof dk === "string" ? dk : String(value);
            return (
              <span
                className={cn(
                  "font-mono text-[10px] tracking-wider uppercase cursor-pointer select-none",
                  hidden[key]
                    ? "text-muted-foreground/40 line-through"
                    : "text-foreground",
                )}
              >
                [ {String(value)} ]
              </span>
            );
          }}
          wrapperStyle={{ paddingTop: 4 }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
