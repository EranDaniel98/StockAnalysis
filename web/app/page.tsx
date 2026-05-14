"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Sparkles, TrendingUp, Zap } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  api,
  type DashboardPick,
  type StrategyCard,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtDate, fmtNumber, fmtPct, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

// ─── Variant + tone helpers ──────────────────────────────────────────────────

type BadgeVariant =
  | "default"
  | "secondary"
  | "destructive"
  | "outline"
  | "ghost"
  | "link"
  | "bullish"
  | "bearish"
  | "neutral";

function actionVariant(action: string): BadgeVariant {
  if (action === "STRONG BUY" || action === "BUY") return "bullish";
  if (action === "STRONG SELL" || action === "SELL") return "bearish";
  return "neutral";
}

function scoreToneClass(score: number): string {
  if (score >= 75) return "text-bullish";
  if (score < 45) return "text-bearish";
  if (score >= 55) return "text-foreground";
  return "text-muted-foreground";
}

function sharpeToneClass(s: number | null | undefined): string {
  if (s === null || s === undefined || Number.isNaN(s)) return "text-muted-foreground";
  if (s >= 1.0) return "text-bullish";
  if (s <= 0) return "text-bearish";
  return "text-foreground";
}

// ─── Pick row (shared between hero card + per-strategy cards) ────────────────

function PickRow({ pick, showStrategy }: { pick: DashboardPick; showStrategy?: boolean }) {
  return (
    <TableRow mono>
      <TableCell>
        <Link
          href={`/stocks/${encodeURIComponent(pick.ticker)}`}
          className="font-mono text-foreground hover:text-primary transition-colors"
        >
          {pick.ticker}
        </Link>
      </TableCell>
      <TableCell className="text-muted-foreground truncate max-w-[160px]">
        {pick.name || "—"}
      </TableCell>
      <TableCell className="text-right">
        <span className={cn("font-mono tabular-nums", scoreToneClass(pick.composite_score))}>
          {fmtNumber(pick.composite_score, 1)}
        </span>
      </TableCell>
      <TableCell>
        <Badge variant={actionVariant(pick.action)} className="text-[10px]">
          {pick.action}
        </Badge>
      </TableCell>
      {showStrategy ? (
        <TableCell className="text-muted-foreground text-[11px]">
          {pick.strategy}
        </TableCell>
      ) : null}
      <TableCell className="text-right text-muted-foreground">
        {fmtUSD(pick.entry_price)}
      </TableCell>
    </TableRow>
  );
}

// ─── Per-strategy card ───────────────────────────────────────────────────────

function StrategyCardView({ card }: { card: StrategyCard }) {
  const qc = useQueryClient();
  const [hint, setHint] = useState<string | null>(null);
  const topPicks = card.top_picks ?? [];

  const refreshMutation = useMutation({
    mutationFn: async () => {
      // Re-run the strategy on whichever universe last produced a sweep
      // result; falling back to themes (fastest) when no sweep exists.
      const universe = (card.sweep_universe ?? "themes") as
        | "themes"
        | "russell_1000"
        | "value_cohort"
        | "watchlist";
      return api.scans.trigger({
        strategy: card.strategy,
        universe,
        theme: null,
        sector: null,
        budget: null,
        top: 15,
        fresh: false,
        live_signals: true,
      });
    },
    onMutate: () => setHint(`Refreshing ${card.strategy}…`),
    onSuccess: () => {
      toast.success(`${card.strategy}: scan complete`);
      qc.invalidateQueries({ queryKey: qk.dashboard.get() });
      qc.invalidateQueries({ queryKey: qk.scans.all });
      setHint(null);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Scan failed");
      setHint(null);
    },
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="font-mono text-sm tracking-tight truncate">
              {card.strategy}
            </CardTitle>
            <CardDescription className="text-[11px] mt-0.5 line-clamp-2">
              {card.description || card.horizon || "—"}
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => refreshMutation.mutate()}
            disabled={refreshMutation.isPending}
            className="h-7 px-2 shrink-0"
            title={`Re-run on ${card.sweep_universe ?? "themes"}`}
          >
            <RefreshCw
              className={cn(
                "h-3 w-3",
                refreshMutation.isPending && "animate-spin",
              )}
            />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Performance strip — OOS Sharpe / Win % / # BUYs */}
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="border border-border rounded px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
              OOS Sharpe
            </div>
            <div
              className={cn(
                "font-mono text-sm font-semibold tabular-nums mt-0.5",
                sharpeToneClass(card.oos_sharpe),
              )}
              title={
                card.sweep_universe
                  ? `From sweep_${card.sweep_universe}_${card.strategy}_2y.json`
                  : "No sweep result on disk"
              }
            >
              {card.oos_sharpe !== null && card.oos_sharpe !== undefined
                ? fmtNumber(card.oos_sharpe, 2)
                : "—"}
            </div>
          </div>
          <div className="border border-border rounded px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
              Win %
            </div>
            <div className="font-mono text-sm font-semibold tabular-nums mt-0.5 text-foreground">
              {card.win_rate_pct !== null && card.win_rate_pct !== undefined
                ? fmtPct(card.win_rate_pct, 1)
                : "—"}
            </div>
          </div>
          <div className="border border-border rounded px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
              # BUYs
            </div>
            <div
              className={cn(
                "font-mono text-sm font-semibold tabular-nums mt-0.5",
                card.n_buys > 0 ? "text-bullish" : "text-muted-foreground",
              )}
            >
              {card.n_buys}
            </div>
          </div>
        </div>

        {/* Top picks for this strategy */}
        {topPicks.length === 0 ? (
          <div className="text-muted-foreground text-center text-[11px] py-4 border border-dashed border-border rounded">
            {hint ?? (card.last_scan_at ? "No BUYs in last scan" : "No scan yet")}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="h-7 text-[10px]">Ticker</TableHead>
                <TableHead className="h-7 text-[10px]">Name</TableHead>
                <TableHead className="h-7 text-[10px] text-right">Score</TableHead>
                <TableHead className="h-7 text-[10px]">Action</TableHead>
                <TableHead className="h-7 text-[10px] text-right">Entry</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {topPicks.map((p) => (
                <PickRow key={`${card.strategy}-${p.ticker}`} pick={p} />
              ))}
            </TableBody>
          </Table>
        )}

        <div className="flex items-center justify-between text-[10px] font-mono uppercase tracking-wider text-muted-foreground pt-1">
          <span>{card.last_scan_at ? `Scanned ${fmtDate(card.last_scan_at)}` : "Never scanned"}</span>
          <Link
            href={`/scan?strategy=${encodeURIComponent(card.strategy)}`}
            className="hover:text-foreground transition-colors"
          >
            open scan →
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const qc = useQueryClient();
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: qk.dashboard.get(),
    queryFn: () => api.dashboard.get(),
    refetchInterval: 5 * 60_000, // 5 min
  });

  const topPicks = data?.top_picks ?? [];
  const strategies = data?.strategies ?? [];

  const totalBuys = strategies.reduce((sum, s) => sum + s.n_buys, 0);
  const bestStrategy = strategies
    .filter((s) => s.oos_sharpe !== null && s.oos_sharpe !== undefined)
    .sort((a, b) => (b.oos_sharpe ?? 0) - (a.oos_sharpe ?? 0))[0];
  const strategiesWithScan = strategies.filter((s) => s.last_scan_at).length;

  return (
    <>
      <PageHeader
        title="Today's Best Plays"
        description="Top buys across every strategy. One snapshot of what the system thinks you should act on right now."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              refetch();
              qc.invalidateQueries({ queryKey: qk.dashboard.get() });
            }}
            disabled={isFetching}
          >
            <RefreshCw
              className={cn("mr-2 h-4 w-4", isFetching && "animate-spin")}
            />
            Refresh
          </Button>
        }
      />

      {error ? <ErrorState error={error} /> : null}

      {/* ── Scoreboard strip ─────────────────────────────────────────────── */}
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="Cross-Strategy BUYs"
          value={isLoading ? "—" : String(topPicks.length)}
          sub={isLoading ? undefined : "highest-conviction across all strategies"}
          subTone={topPicks.length > 0 ? "bullish" : "muted"}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Total BUY Signals"
          value={isLoading ? "—" : String(totalBuys)}
          sub={
            isLoading
              ? undefined
              : `${strategiesWithScan} / ${strategies.length} strategies scanned`
          }
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Best Strategy (OOS Sharpe)"
          tooltip="Out-of-sample Sharpe from the most-recent A/B sweep (insider-off baseline). Higher = better risk-adjusted return on data the strategy didn't see during fitting."
          value={
            bestStrategy ? (
              <span className="font-mono text-base tracking-tight">
                {bestStrategy.strategy}
              </span>
            ) : (
              "—"
            )
          }
          sub={
            bestStrategy
              ? `Sharpe ${fmtNumber(bestStrategy.oos_sharpe, 2)} · ${fmtPct(bestStrategy.win_rate_pct, 1)} win`
              : "no sweep results yet"
          }
          subTone={bestStrategy ? "bullish" : "muted"}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Generated"
          value={
            data ? (
              <span className="font-mono text-base tracking-tight">
                {fmtDate(data.generated_at)}
              </span>
            ) : (
              "—"
            )
          }
          sub="auto-refresh every 5 min"
          subTone="muted"
          isLoading={isLoading}
        />
      </div>

      {/* ── Cross-strategy hero card ─────────────────────────────────────── */}
      <Card className="mt-4">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-bullish" />
            <CardTitle className="text-sm tracking-tight">
              Top Picks — Across All Strategies
            </CardTitle>
          </div>
          <CardDescription>
            Highest composite score per ticker (deduplicated when a ticker shows
            up in multiple strategies — strongest signal wins).
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2 py-1">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          ) : topPicks.length === 0 ? (
            <div className="text-center py-8">
              <TrendingUp className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
              <p className="text-muted-foreground text-xs mb-3">
                No BUY/STRONG BUY candidates across any strategy yet.
              </p>
              <Link href="/scan">
                <Button variant="outline" size="sm">
                  <Zap className="mr-2 h-3.5 w-3.5" />
                  Run a scan
                </Button>
              </Link>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Strategy</TableHead>
                  <TableHead className="text-right">Entry</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {topPicks.map((p) => (
                  <PickRow key={p.ticker} pick={p} showStrategy />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* ── Per-strategy grid ────────────────────────────────────────────── */}
      <div className="mt-6 mb-2">
        <h2 className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
          By Strategy
        </h2>
      </div>
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-72 w-full" />
          ))}
        </div>
      ) : strategies.length === 0 ? (
        <p className="text-muted-foreground text-center text-xs py-12">
          No strategies configured.
        </p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {strategies.map((card) => (
            <StrategyCardView key={card.strategy} card={card} />
          ))}
        </div>
      )}
    </>
  );
}
