"use client";

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
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

export type ModelFoldSeries = {
  /** Display name shown in legend + tooltip. */
  name: string;
  /** Folds sorted oldest -> newest. */
  folds: { test_start: string; ic_pearson: number }[];
};

type Row = {
  date: string;
  // Indexed by series name. Recharts handles null gaps natively.
  [seriesName: string]: number | string | null | undefined;
};

/**
 * Bloomberg-style rolling-IC overlay. One line per active model + an
 * `ENSEMBLE` line (simple per-bucket average across the models that have
 * a value on that date — the registered ensemble is just averaged here
 * because the API does not yet surface per-model weights).
 *
 * Visual rules:
 *  - Ensemble: solid 2px, amber `CHART_TOKEN.primary`. Always rendered
 *    first so per-model strokes sit on top of it but the legend keeps
 *    the ensemble at the front.
 *  - Per-model series: 1.5px, cyclic colors via `chartColor(i)` in the
 *    documented chart-tokens order.
 *  - Zero-line reference at IC=0 using `CHART_TOKEN.primary` (amber,
 *    opacity 0.5) — IC=0 is the "no edge" boundary.
 *
 * Click a legend chip to toggle the corresponding series.
 */
export function RollingICChart({
  series,
  ensembleName = "ENSEMBLE",
}: {
  series: ModelFoldSeries[];
  ensembleName?: string;
}) {
  // Union all timestamps across models, then for each timestamp pull each
  // model's ic_pearson (or null when the model didn't have a fold on that
  // date) plus the ensemble = mean of available values.
  const { rows, names } = useMemo(() => {
    const ts = new Set<string>();
    for (const s of series) {
      for (const f of s.folds) ts.add(f.test_start);
    }
    const sortedTs = Array.from(ts).sort();
    const indexed = new Map<string, Map<string, number>>();
    for (const s of series) {
      for (const f of s.folds) {
        if (!indexed.has(f.test_start)) indexed.set(f.test_start, new Map());
        indexed.get(f.test_start)!.set(s.name, f.ic_pearson);
      }
    }
    const out: Row[] = sortedTs.map((date) => {
      const slice = indexed.get(date)!;
      const row: Row = { date };
      const values: number[] = [];
      for (const s of series) {
        const v = slice.get(s.name);
        if (v == null || Number.isNaN(v)) {
          row[s.name] = null;
        } else {
          row[s.name] = v;
          values.push(v);
        }
      }
      row[ensembleName] =
        values.length > 0
          ? values.reduce((a, b) => a + b, 0) / values.length
          : null;
      return row;
    });
    return { rows: out, names: series.map((s) => s.name) };
  }, [series, ensembleName]);

  // Track which series are hidden via legend toggles.
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  // Recharts' Legend onClick payload type is loose (dataKey can be a
  // function for derived series), so we narrow at runtime instead of
  // fighting the upstream type.
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
        No fold metrics yet.
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
      <LineChart data={rows} margin={{ top: 12, right: 8, bottom: 0, left: 8 }}>
        <CartesianGrid
          stroke={CHART_GRID}
          strokeOpacity={0.4}
          strokeDasharray="2 4"
          vertical={false}
        />
        <XAxis
          dataKey="date"
          stroke={CHART_AXIS}
          tick={{
            fill: CHART_AXIS,
            fontFamily: "var(--font-geist-mono)",
            fontSize: 10,
          }}
          tickFormatter={dateFmt}
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
          tickFormatter={(v) => (v as number).toFixed(3)}
          width={56}
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
            return [(value as number).toFixed(4), String(name).toUpperCase()];
          }}
        />
        <ReferenceLine
          y={0}
          stroke={CHART_TOKEN.primary}
          strokeOpacity={0.5}
          strokeDasharray="3 3"
        />
        {/* Ensemble first so per-model lines paint over it; legend will
            still list it at the top because Recharts orders the legend
            by render order. */}
        <Line
          type="monotone"
          dataKey={ensembleName}
          stroke={CHART_TOKEN.primary}
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 3, fill: CHART_TOKEN.primary, stroke: "none" }}
          isAnimationActive={false}
          connectNulls
          hide={hidden[ensembleName]}
        />
        {names.map((name, i) => (
          <Line
            key={name}
            type="monotone"
            dataKey={name}
            stroke={chartColor(i)}
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3, fill: chartColor(i), stroke: "none" }}
            isAnimationActive={false}
            connectNulls
            hide={hidden[name]}
          />
        ))}
        <Legend
          verticalAlign="bottom"
          height={28}
          iconType="plainline"
          onClick={onLegendClick}
          formatter={(value) => (
            <span
              className={cn(
                "font-mono text-[10px] tracking-wider uppercase cursor-pointer select-none",
                hidden[String(value)]
                  ? "text-muted-foreground/40 line-through"
                  : "text-foreground",
              )}
            >
              [ {String(value)} ]
            </span>
          )}
          wrapperStyle={{ paddingTop: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
