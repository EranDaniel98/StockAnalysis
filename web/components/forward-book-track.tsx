"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ForwardBookMark } from "@/lib/research/data";
import { fmtPct } from "@/lib/format";

/**
 * Book return % vs SPY return % since book start. One point per trading-day
 * mark; grows as the forward book is marked daily. Sparse on day one — that's
 * expected, the whole point is to watch it accumulate forward.
 */
export function ForwardBookTrack({ history }: { history: ForwardBookMark[] }) {
  const data = history
    .filter((h) => h.ret_pct != null)
    .map((h) => ({
      date: h.date,
      book: h.ret_pct,
      spy: h.spy_ret_pct,
    }));

  if (data.length < 2) {
    return (
      <p className="text-muted-foreground py-8 text-center text-xs">
        Only {data.length} mark so far — the vs-SPY curve fills in as the book
        is marked each trading day.
      </p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 10 }}
          stroke="var(--muted-foreground)"
        />
        <YAxis
          tick={{ fontSize: 10 }}
          stroke="var(--muted-foreground)"
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip
          contentStyle={{
            background: "var(--popover)",
            border: "1px solid var(--border)",
            borderRadius: 2,
            fontSize: 11,
          }}
          formatter={(value, name) => [
            typeof value === "number" ? fmtPct(value, 2, true) : String(value),
            name === "book" ? "AI book" : "SPY",
          ]}
        />
        <Line
          type="monotone"
          dataKey="book"
          stroke="var(--chart-2)"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="spy"
          stroke="var(--muted-foreground)"
          strokeWidth={1.5}
          strokeDasharray="4 3"
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
