"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { GitCompare } from "lucide-react";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtDate, fmtNumber, fmtPct, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

const COMPARE_MIN = 2;
const COMPARE_MAX = 5;

function sharpeBadgeVariant(
  sharpe: number | null | undefined,
): "bullish" | "bearish" | "neutral" {
  if (sharpe == null || Number.isNaN(sharpe)) return "neutral";
  if (sharpe >= 1) return "bullish";
  if (sharpe < 0) return "bearish";
  return "neutral";
}

function shortWindow(start: string, end: string): string {
  const s = new Date(start);
  const e = new Date(end);
  if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) {
    return `${start} -> ${end}`;
  }
  const fmt = (d: Date) =>
    d.toLocaleDateString(undefined, { year: "2-digit", month: "short" });
  return `${fmt(s)} -> ${fmt(e)}`;
}

export default function BacktestsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.backtests.list({ limit: 30 }),
    queryFn: () => api.backtests.list({ limit: 30 }),
  });

  const [selected, setSelected] = useState<Set<number>>(new Set());

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        return next;
      }
      if (next.size >= COMPARE_MAX) return prev;
      next.add(id);
      return next;
    });
  }

  const stats = useMemo(() => {
    if (!data || data.length === 0) {
      return {
        total: 0,
        latest: null as string | null,
        bestSharpe: null as number | null,
        strategies: 0,
      };
    }
    let latest: string | null = null;
    let bestSharpe: number | null = null;
    const strategies = new Set<string>();
    for (const bt of data) {
      strategies.add(bt.strategy);
      if (
        bt.oos_sharpe != null &&
        (bestSharpe == null || bt.oos_sharpe > bestSharpe)
      ) {
        bestSharpe = bt.oos_sharpe;
      }
      if (
        bt.created_at &&
        (latest == null ||
          new Date(bt.created_at).getTime() > new Date(latest).getTime())
      ) {
        latest = bt.created_at;
      }
    }
    return {
      total: data.length,
      latest,
      bestSharpe,
      strategies: strategies.size,
    };
  }, [data]);

  const compareReady = selected.size >= COMPARE_MIN;
  const compareHref = compareReady
    ? `/backtests/compare?ids=${[...selected].join(",")}`
    : null;

  return (
    <>
      <PageHeader
        title="Backtests"
        description="Walk-forward simulation index. Trigger new runs from the CLI; select 2-5 rows and press [ Compare ] to overlay equity curves."
        actions={
          data ? (
            <Badge variant="outline" className="font-mono">
              {data.length} runs
            </Badge>
          ) : null
        }
      />

      {error ? <ErrorState error={error} /> : null}

      {isLoading || !data ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
          <Skeleton className="h-72 w-full" />
        </div>
      ) : (
        <div className="space-y-4">
          {/* ── Scoreboard strip ───────────────────────────────────────── */}
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            <ScoreboardTile
              label="Total Runs"
              value={String(stats.total)}
              sub={stats.total === 0 ? "none yet" : "last 30 retained"}
              subTone="muted"
            />
            <ScoreboardTile
              label="Latest Run"
              value={
                stats.latest
                  ? new Date(stats.latest).toLocaleDateString(undefined, {
                      year: "2-digit",
                      month: "short",
                      day: "2-digit",
                    })
                  : "—"
              }
              sub={
                stats.latest
                  ? new Date(stats.latest).toLocaleTimeString(undefined, {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : undefined
              }
              subTone="muted"
            />
            <ScoreboardTile
              label="Best OOS Sharpe"
              value={
                <span
                  className={cn(
                    stats.bestSharpe == null
                      ? ""
                      : stats.bestSharpe >= 1
                        ? "text-bullish"
                        : stats.bestSharpe < 0
                          ? "text-bearish"
                          : "text-foreground",
                  )}
                >
                  {stats.bestSharpe == null
                    ? "—"
                    : fmtNumber(stats.bestSharpe, 2)}
                </span>
              }
              sub={
                stats.bestSharpe == null
                  ? "no signed runs"
                  : stats.bestSharpe >= 1
                    ? "edge confirmed"
                    : stats.bestSharpe >= 0
                      ? "marginal"
                      : "no edge"
              }
              subTone={
                stats.bestSharpe == null
                  ? "muted"
                  : stats.bestSharpe >= 1
                    ? "bullish"
                    : stats.bestSharpe < 0
                      ? "bearish"
                      : "neutral"
              }
            />
            <ScoreboardTile
              label="Strategies Tested"
              value={String(stats.strategies)}
              sub={
                stats.strategies > 0
                  ? `across ${stats.total} runs`
                  : "no runs"
              }
              subTone="muted"
            />
          </div>

          {/* ── Runs table ────────────────────────────────────────────── */}
          {data.length === 0 ? (
            <div className="border-border rounded-md border bg-card px-3 py-12 text-center">
              <p className="font-mono text-xs tracking-wider text-muted-foreground uppercase">
                No backtest runs yet. Start one with{" "}
                <code className="bg-muted rounded-sm px-1.5 py-0.5">
                  python -m src.cli.main backtest --strategy swing_trading --years 3
                </code>
                .
              </p>
            </div>
          ) : (
            <div className="border-border rounded-md border bg-card">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  Recent runs
                </div>
                <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  {data.length} rows | select {COMPARE_MIN}-{COMPARE_MAX} to compare
                </div>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8"></TableHead>
                    <TableHead>ID</TableHead>
                    <TableHead>Strategy</TableHead>
                    <TableHead>Universe</TableHead>
                    <TableHead>Window</TableHead>
                    <TableHead className="text-right">Trades</TableHead>
                    <TableHead className="text-right">OOS Sharpe</TableHead>
                    <TableHead className="text-right">OOS Return</TableHead>
                    <TableHead className="text-right">Max DD</TableHead>
                    <TableHead className="text-right">Created</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.map((bt) => {
                    const isSelected = selected.has(bt.id);
                    const capReached =
                      !isSelected && selected.size >= COMPARE_MAX;
                    return (
                      <TableRow
                        key={bt.id}
                        mono
                        className={cn(
                          "transition-colors hover:bg-muted/30",
                          isSelected && "bg-muted/40",
                        )}
                      >
                        <TableCell>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggle(bt.id)}
                            disabled={capReached}
                            aria-label={`Select backtest ${bt.id} for comparison`}
                            className="accent-primary disabled:cursor-not-allowed disabled:opacity-40"
                          />
                        </TableCell>
                        <TableCell>
                          <Link
                            href={`/backtests/${bt.id}`}
                            className="text-foreground hover:underline"
                          >
                            #{bt.id}
                          </Link>
                        </TableCell>
                        <TableCell className="font-sans">
                          <Link
                            href={`/backtests/${bt.id}`}
                            className="hover:underline"
                          >
                            <Badge
                              variant={sharpeBadgeVariant(bt.oos_sharpe)}
                              className="font-mono"
                            >
                              {bt.strategy}
                            </Badge>
                          </Link>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-[11px]">
                          {bt.universe_label}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-[11px]">
                          {shortWindow(bt.window_start, bt.window_end)}
                        </TableCell>
                        <TableCell className="text-right">
                          {bt.n_trades ?? "—"}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right",
                            pnlColorClass(bt.oos_sharpe),
                          )}
                        >
                          {fmtNumber(bt.oos_sharpe, 2)}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right",
                            pnlColorClass(bt.oos_total_return_pct),
                          )}
                        >
                          {fmtPct(bt.oos_total_return_pct, 1, true)}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right",
                            pnlColorClass(-(bt.oos_max_drawdown_pct ?? 0)),
                          )}
                        >
                          {fmtPct(bt.oos_max_drawdown_pct, 1)}
                        </TableCell>
                        <TableCell className="text-right text-muted-foreground text-[11px]">
                          {fmtDate(bt.created_at)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}

      {/* ── Sticky compare bar ──────────────────────────────────────────── */}
      {selected.size > 0 ? (
        <div className="sticky bottom-3 mt-4 flex items-center justify-between gap-3 rounded-md border border-border bg-card/95 px-3 py-2 backdrop-blur">
          <span className="font-mono text-[11px] tracking-wider uppercase text-muted-foreground">
            Selected{" "}
            <span
              className={cn(
                "text-foreground",
                compareReady ? "text-bullish" : "",
              )}
            >
              {selected.size}
            </span>{" "}
            / {COMPARE_MIN}-{COMPARE_MAX}
            {selected.size >= COMPARE_MAX ? (
              <span className="ml-2 text-bearish">cap reached</span>
            ) : !compareReady ? (
              <span className="ml-2">
                pick {COMPARE_MIN - selected.size} more
              </span>
            ) : null}
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              className="font-mono text-[11px] tracking-wider uppercase"
              onClick={() => setSelected(new Set())}
            >
              Clear
            </Button>
            {compareHref ? (
              <Link href={compareHref}>
                <Button
                  size="sm"
                  className="font-mono text-[11px] tracking-wider uppercase"
                >
                  <GitCompare className="mr-1.5 h-3.5 w-3.5" />
                  [ Compare {selected.size} ]
                </Button>
              </Link>
            ) : (
              <Button
                size="sm"
                disabled
                className="font-mono text-[11px] tracking-wider uppercase"
              >
                [ Compare ]
              </Button>
            )}
          </div>
        </div>
      ) : null}
    </>
  );
}
