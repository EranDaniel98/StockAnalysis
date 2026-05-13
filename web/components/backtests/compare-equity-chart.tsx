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
import { fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

export type CompareEquitySeries = {
  /** Stable key per run (e.g. `run_${id}`). */
  key: string;
  /** Display label shown in legend + tooltip. */
  name: string;
  /** Equity samples sorted oldest -> newest. */
  points: { date: string; equity: number }[];
  /** Optional per-run IS->OOS split, drawn as one shared range when supplied. */
  splitDate?: string | null;
};

type Row = {
  date: string;
  [key: string]: number | string | null | undefined;
};

/**
 * Multi-run equity overlay. One line per selected run via `chartColor(i)`,
 * 1.5px each — all runs are peers, there is no "ensemble" to elevate
 * (unlike the rolling-IC chart on /ml).
 *
 * If every run shares a split date, draws a single dashed amber
 * ReferenceLine. If splits diverge, the caller is responsible for showing
 * a bracketed range header instead of multiple lines (see /backtests/compare
 * page header).
 *
 * Legend chips are click-to-toggle, matching the rolling-IC pattern.
 */
export function CompareEquityChart({
  series,
}: {
  series: CompareEquitySeries[];
}) {
  const { rows, sharedSplit } = useMemo(() => {
    const index = new Map<string, Row>();
    for (const s of series) {
      for (const p of s.points) {
        if (!p.date || p.equity == null || Number.isNaN(p.equity)) continue;
        const row = index.get(p.date) ?? { date: p.date };
        row[s.key] = p.equity;
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
        No equity samples in this cohort.
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
          tickFormatter={(v) => fmtUSD(v as number, true)}
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
            return [
              typeof value === "number" ? fmtUSD(value) : String(value),
              String(name).toUpperCase(),
            ];
          }}
        />
        {sharedSplit ? (
          <ReferenceLine
            x={sharedSplit}
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
        {series.map((s, i) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.name}
            stroke={chartColor(i)}
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3, fill: chartColor(i), stroke: "none" }}
            isAnimationActive={false}
            connectNulls
            hide={hidden[s.key]}
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
      </LineChart>
    </ResponsiveContainer>
  );
}
