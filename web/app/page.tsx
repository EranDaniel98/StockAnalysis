"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, Sparkles, TrendingUp, X } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FactorChips } from "@/components/factor-chips";
import { MorningBriefingBanner } from "@/components/morning-briefing-banner";
import { PageHeader } from "@/components/page-header";
import { ScanProgress } from "@/components/scan-progress";
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
  type BriefingResponse,
  type DashboardPick,
  type StrategyCard,
  type TopPick,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { useScanStream } from "@/lib/api/use-scan-stream";
import { useMounted } from "@/lib/use-mounted";
import {
  fmtDate,
  fmtNumber,
  fmtPct,
  fmtRelativeTime,
  fmtUSD,
  hoursSince,
} from "@/lib/format";
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

/**
 * Categorize how old a scan is so the card can warn the user the picks
 * may not reflect today's market. ≥7d is "very stale" (red), ≥24h is
 * "stale" (amber/warning). Anything fresher renders no pill at all.
 */
function scanStaleness(
  lastScanAt: string | null | undefined,
): { level: "fresh" | "stale" | "very_stale"; label: string; hours: number } | null {
  const h = hoursSince(lastScanAt);
  if (h === null) return null;
  if (h >= 24 * 7) return { level: "very_stale", label: "stale 7d+", hours: h };
  if (h >= 24) return { level: "stale", label: "stale 24h+", hours: h };
  return { level: "fresh", label: "", hours: h };
}

// ─── Pick row (shared between hero card + per-strategy cards) ────────────────

function PickRow({ pick, showStrategy }: { pick: DashboardPick; showStrategy?: boolean }) {
  // TradingView's /symbols/ route auto-routes to the primary US listing for
  // ambiguous tickers (no exchange prefix needed). New-tab + noopener so the
  // dashboard doesn't lose state and the popup can't reach back via window.opener.
  const tvHref = `https://www.tradingview.com/symbols/${encodeURIComponent(pick.ticker)}/`;
  return (
    <TableRow mono>
      <TableCell>
        <div className="flex items-center gap-1.5">
          <Link
            href={`/stocks/${encodeURIComponent(pick.ticker)}`}
            className="font-mono text-foreground hover:text-primary transition-colors"
          >
            {pick.ticker}
          </Link>
          <a
            href={tvHref}
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted-foreground/60 hover:text-primary transition-colors"
            title={`Open ${pick.ticker} chart on TradingView`}
            aria-label={`Open ${pick.ticker} chart on TradingView (new tab)`}
          >
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
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

function StrategyCardView({
  card,
  isBest,
}: {
  card: StrategyCard;
  isBest?: boolean;
}) {
  const qc = useQueryClient();
  const { state: streamState, start: startStream, abort, reset } = useScanStream();
  const topPicks = card.top_picks ?? [];
  const staleness = scanStaleness(card.last_scan_at);
  const universe = (card.sweep_universe ?? "themes") as
    | "themes"
    | "russell_1000"
    | "value_cohort"
    | "watchlist";

  // On scan completion, pull the refreshed dashboard payload + recent scan
  // list so the card swaps its progress strip for the new picks without a
  // manual reload. Toast lives here (not at click) so the user gets the
  // notification even if they navigate away mid-scan.
  useEffect(() => {
    if (streamState.complete) {
      toast.success(
        `${card.strategy}: ${streamState.complete.n_results} candidates`,
      );
      qc.invalidateQueries({ queryKey: qk.dashboard.get() });
      qc.invalidateQueries({ queryKey: qk.scans.all });
      // Let the progress strip linger ~1.5s so the user sees the green
      // COMPLETE state, then clear back to picks.
      const t = setTimeout(() => reset(), 1500);
      return () => clearTimeout(t);
    }
  }, [streamState.complete, card.strategy, qc, reset]);

  useEffect(() => {
    if (streamState.error) {
      toast.error(`${card.strategy}: ${streamState.error}`);
    }
  }, [streamState.error, card.strategy]);

  const onRefresh = () => {
    startStream({
      strategy: card.strategy,
      universe,
      theme: null,
      sector: null,
      budget: null,
      top: 15,
      fresh: false,
      live_signals: true,
    });
  };

  const isScanning = streamState.active;
  const showProgress = isScanning || streamState.complete || streamState.error;

  return (
    <Card className={cn(isBest && "ring-1 ring-bullish/40")}>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 flex-wrap">
              <CardTitle className="font-mono text-sm tracking-tight truncate">
                {card.strategy}
              </CardTitle>
              {isBest ? (
                <Badge variant="bullish" className="text-[9px] uppercase tracking-wider">
                  Top OOS
                </Badge>
              ) : null}
              {staleness && staleness.level !== "fresh" ? (
                <Badge
                  variant={staleness.level === "very_stale" ? "bearish" : "neutral"}
                  className="text-[9px] uppercase tracking-wider"
                  title={`Last scan ${fmtRelativeTime(card.last_scan_at)} (${Math.round(staleness.hours)}h)`}
                >
                  {staleness.label}
                </Badge>
              ) : null}
            </div>
            <CardDescription className="text-[11px] mt-0.5 line-clamp-2">
              {card.description || card.horizon || "—"}
            </CardDescription>
          </div>
          {isScanning ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={abort}
              className="h-7 px-2 shrink-0"
              title="Cancel scan"
              aria-label={`Cancel ${card.strategy} scan`}
            >
              <X className="h-3 w-3" />
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onRefresh}
              className="h-7 px-2 shrink-0"
              title={`Re-run on ${universe}`}
              aria-label={`Re-run ${card.strategy} scan`}
            >
              <RefreshCw className="h-3 w-3" />
            </Button>
          )}
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

        {/* Live progress takes over the body slot while a scan is in flight. */}
        {showProgress ? (
          <ScanProgress state={streamState} compact />
        ) : topPicks.length === 0 ? (
          <div className="text-muted-foreground text-center text-[11px] py-4 border border-dashed border-border rounded">
            {card.last_scan_at ? "No BUYs in last scan" : "No scan yet"}
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
          <span
            title={
              card.last_scan_at ? fmtDate(card.last_scan_at) : "No scan yet"
            }
          >
            {card.last_scan_at
              ? `Scanned ${fmtRelativeTime(card.last_scan_at)}`
              : "Never scanned"}
          </span>
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

// ─── Factor hero (top-5 picks with rationale chips) ─────────────────────────

function FactorPicksHero({
  briefing, isLoading,
}: {
  briefing: BriefingResponse | undefined;
  isLoading: boolean;
}) {
  const picks = briefing?.top_picks ?? [];
  const picksDate = briefing?.picks_date ?? null;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-bullish" />
            <CardTitle className="text-sm tracking-tight">
              Today&apos;s Factor Picks
            </CardTitle>
            {picksDate ? (
              <Badge variant="outline" className="text-[9px] font-mono">
                {picksDate}
              </Badge>
            ) : null}
          </div>
          <Link
            href="/factors"
            className="text-[11px] text-muted-foreground hover:text-foreground"
          >
            full 15-pick view →
          </Link>
        </div>
        <CardDescription>
          Composite m+q+v(+pead) ranking. Chips mark factors where the pick
          sits in the universe top decile (rank ≤ 50).
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-2 py-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : picks.length === 0 ? (
          <div className="text-center py-8">
            <TrendingUp className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
            <p className="text-muted-foreground text-xs mb-3">
              No factor picks for today. Run the daily pipeline.
            </p>
            <code className="text-[10px] bg-muted px-2 py-1 rounded font-mono">
              uv run python -m scripts.run_daily_pipeline
            </code>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10 text-[10px]">#</TableHead>
                <TableHead className="text-[10px]">Ticker</TableHead>
                <TableHead className="text-[10px] text-right">z</TableHead>
                <TableHead className="text-[10px]">Sector</TableHead>
                <TableHead className="text-[10px]">Factor stack</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {picks.map((p) => (
                <FactorPickRow key={p.ticker} pick={p} />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function FactorPickRow({ pick }: { pick: TopPick }) {
  const tvHref = `https://www.tradingview.com/symbols/${encodeURIComponent(pick.ticker)}/`;
  const z = pick.z_score;
  return (
    <TableRow mono>
      <TableCell className="text-muted-foreground font-mono text-[11px]">
        {pick.rank}
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-1.5">
          <Link
            href={`/stocks/${encodeURIComponent(pick.ticker)}`}
            className="font-mono text-foreground hover:text-primary transition-colors"
          >
            {pick.ticker}
          </Link>
          <a
            href={tvHref}
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted-foreground/60 hover:text-primary transition-colors"
            title={`Open ${pick.ticker} chart on TradingView`}
            aria-label={`Open ${pick.ticker} chart on TradingView (new tab)`}
          >
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </TableCell>
      <TableCell className="text-right font-mono tabular-nums">
        <span
          className={cn(
            z != null && z >= 2.0 && "text-bullish",
            z != null && z < 1.0 && "text-muted-foreground",
          )}
        >
          {z != null ? `+${z.toFixed(2)}` : "—"}
        </span>
      </TableCell>
      <TableCell className="text-muted-foreground text-[11px]">
        {pick.sector || "—"}
      </TableCell>
      <TableCell>
        <FactorChips
          mom={pick.mom_rank}
          qual={pick.qual_rank}
          val={pick.val_rank}
          pead={pick.pead_rank}
        />
      </TableCell>
    </TableRow>
  );
}

// ─── Actions card (NEW BUY / KEEP / EXIT counts) ─────────────────────────────

function ActionsCard({
  briefing, isLoading,
}: {
  briefing: BriefingResponse | undefined;
  isLoading: boolean;
}) {
  const counts = briefing?.action_counts ?? null;
  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (!counts) {
    return (
      <Card>
        <CardContent className="py-4 text-xs text-muted-foreground">
          No rebalance plan yet — needs both today&apos;s picks and current
          paper positions.
        </CardContent>
      </Card>
    );
  }
  const total = counts.n_new_buys + counts.n_keep + counts.n_exit;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm tracking-tight">
          Today&apos;s rebalance shape
        </CardTitle>
        <CardDescription className="text-[11px]">
          Set-diff of today&apos;s picks vs current paper positions. Full
          per-stock orders on <Link href="/portfolio" className="underline">/portfolio</Link>.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-3 text-center">
          <ActionCountCell label="NEW BUY" count={counts.n_new_buys} tone="bullish" />
          <ActionCountCell label="KEEP" count={counts.n_keep} tone="neutral" />
          <ActionCountCell label="EXIT" count={counts.n_exit} tone="bearish" />
        </div>
        {total === 0 ? (
          <p className="text-[11px] text-muted-foreground text-center mt-3">
            Nothing to do — basket is already aligned.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ActionCountCell({
  label, count, tone,
}: {
  label: string;
  count: number;
  tone: "bullish" | "neutral" | "bearish";
}) {
  return (
    <div className="border border-border rounded px-2 py-2">
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "font-mono text-2xl font-semibold tabular-nums mt-1",
          count > 0 && tone === "bullish" && "text-bullish",
          count > 0 && tone === "bearish" && "text-bearish",
          count > 0 && tone === "neutral" && "text-foreground",
          count === 0 && "text-muted-foreground",
        )}
      >
        {count}
      </div>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const qc = useQueryClient();
  const mounted = useMounted();
  const dashboardQ = useQuery({
    queryKey: qk.dashboard.get(),
    queryFn: () => api.dashboard.get(),
    refetchInterval: 5 * 60_000, // 5 min
  });
  const briefingQ = useQuery({
    queryKey: qk.dashboard.briefing(),
    queryFn: () => api.dashboard.briefing(),
    refetchInterval: 5 * 60_000,
  });
  // See use-mounted.ts: isFetching=false on server, true on client mount.
  const fetching = mounted && (dashboardQ.isFetching || briefingQ.isFetching);

  const dashboard = dashboardQ.data;
  const briefing = briefingQ.data;
  const briefingLoading = briefingQ.isLoading;
  const dashboardLoading = dashboardQ.isLoading;

  const strategies = dashboard?.strategies ?? [];
  const bestStrategy = strategies
    .filter((s) => s.oos_sharpe !== null && s.oos_sharpe !== undefined)
    .sort((a, b) => (b.oos_sharpe ?? 0) - (a.oos_sharpe ?? 0))[0];

  const topZ = briefing?.top_picks?.[0]?.z_score ?? null;
  const topTicker = briefing?.top_picks?.[0]?.ticker ?? null;
  const equity = briefing?.paper_equity_usd ?? null;
  const plUsd = briefing?.unrealized_pl_usd ?? null;
  const plPct = briefing?.unrealized_pl_pct ?? null;
  const picksMtime = briefing?.picks_generated_at ?? null;

  return (
    <>
      <PageHeader
        title="Today's Plays"
        description="Daily-pipeline factor picks, rebalance shape, and paper P&L — the one-screen scan before market open."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              dashboardQ.refetch();
              briefingQ.refetch();
              qc.invalidateQueries({ queryKey: qk.dashboard.get() });
              qc.invalidateQueries({ queryKey: qk.dashboard.briefing() });
            }}
            disabled={fetching}
          >
            <RefreshCw
              className={cn("mr-2 h-4 w-4", fetching && "animate-spin")}
            />
            Refresh
          </Button>
        }
      />

      {dashboardQ.error ? <ErrorState error={dashboardQ.error} /> : null}

      {/* ── Morning briefing banner (gate + factor coverage + alerts) ────── */}
      <MorningBriefingBanner />

      {/* ── Scoreboard strip ─────────────────────────────────────────────── */}
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="Today's picks"
          tooltip="Click to drill into /factors for the full 15-pick table, sector mix, and paper-vs-SPY chart."
          value={
            briefingLoading ? (
              "—"
            ) : (
              <Link href="/factors" className="hover:text-primary transition-colors">
                {briefing?.n_picks ?? 0}
              </Link>
            )
          }
          sub={
            briefing && briefing.n_picks > 0
              ? `composite m+q+v${(briefing.factor_coverage ?? []).some((f) => f.factor === "pead") ? "+pead" : ""}`
              : "run the daily pipeline"
          }
          subTone={briefing && briefing.n_picks > 0 ? "bullish" : "muted"}
          isLoading={briefingLoading}
        />
        <ScoreboardTile
          label="Top pick"
          value={
            briefingLoading ? (
              "—"
            ) : topTicker ? (
              <Link
                href={`/stocks/${encodeURIComponent(topTicker)}`}
                className="font-mono text-base tracking-tight hover:text-primary transition-colors"
              >
                {topTicker}
              </Link>
            ) : (
              "—"
            )
          }
          sub={
            topZ != null
              ? `composite z = +${topZ.toFixed(2)}`
              : "no picks today"
          }
          subTone={topZ != null && topZ >= 2.0 ? "bullish" : "muted"}
          isLoading={briefingLoading}
        />
        <ScoreboardTile
          label="Paper P&L"
          tooltip="Unrealized P&L on currently held paper positions. Full breakdown on /portfolio."
          value={
            briefingLoading ? (
              "—"
            ) : equity != null ? (
              <span className="font-mono text-base tracking-tight">
                {fmtUSD(equity)}
              </span>
            ) : (
              "—"
            )
          }
          sub={
            plUsd != null && plPct != null
              ? `${plUsd >= 0 ? "+" : ""}${fmtUSD(plUsd)} (${fmtPct(plPct, 2)})`
              : equity != null
              ? "no positions"
              : "Alpaca unreachable"
          }
          subTone={
            plUsd != null
              ? plUsd > 0
                ? "bullish"
                : plUsd < 0
                ? "bearish"
                : "muted"
              : "muted"
          }
          isLoading={briefingLoading}
        />
        <ScoreboardTile
          label="Pipeline run"
          tooltip="File-system mtime of today's picks JSON. Stale = pipeline hasn't run yet today."
          value={
            briefingLoading ? (
              "—"
            ) : picksMtime ? (
              <span
                className="font-mono text-base tracking-tight"
                title={fmtDate(picksMtime)}
              >
                {fmtRelativeTime(picksMtime)}
              </span>
            ) : (
              <span className="text-bearish text-base">never</span>
            )
          }
          sub={
            picksMtime
              ? `auto-refresh every 5 min`
              : "run scripts.run_daily_pipeline"
          }
          subTone={picksMtime ? "muted" : "bearish"}
          isLoading={briefingLoading}
        />
      </div>

      {/* ── Factor hero + rebalance actions ─────────────────────────────── */}
      <div className="grid gap-4 mt-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <FactorPicksHero briefing={briefing} isLoading={briefingLoading} />
        </div>
        <ActionsCard briefing={briefing} isLoading={briefingLoading} />
      </div>

      {/* ── Legacy 5-engine grid (collapsed by default) ─────────────────── */}
      <details className="mt-6 group">
        <summary className="cursor-pointer list-none flex items-center gap-2 text-xs font-medium tracking-wider uppercase text-muted-foreground hover:text-foreground transition-colors">
          <span className="opacity-60 group-open:rotate-90 inline-block transition-transform">▶</span>
          Other strategies (legacy 5-engine)
          <span className="ml-2 text-[10px] normal-case opacity-60">
            no defensible edge proven — for reference only
          </span>
        </summary>
        <div className="mt-4">
          {dashboardLoading ? (
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
                <StrategyCardView
                  key={card.strategy}
                  card={card}
                  isBest={!!bestStrategy && card.strategy === bestStrategy.strategy}
                />
              ))}
            </div>
          )}
        </div>
      </details>
    </>
  );
}
