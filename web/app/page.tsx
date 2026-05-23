"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, Sparkles, TrendingUp } from "lucide-react";
import Link from "next/link";

import { ErrorState } from "@/components/error-state";
import { FactorChips } from "@/components/factor-chips";
import { MorningBriefingBanner } from "@/components/morning-briefing-banner";
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
  type BriefingResponse,
  type TopPick,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { useMounted } from "@/lib/use-mounted";
import { fmtDate, fmtPct, fmtRelativeTime, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

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
  const briefingQ = useQuery({
    queryKey: qk.dashboard.briefing(),
    queryFn: () => api.dashboard.briefing(),
    refetchInterval: 5 * 60_000,
  });
  // See use-mounted.ts: isFetching=false on server, true on client mount.
  const fetching = mounted && briefingQ.isFetching;

  const briefing = briefingQ.data;
  const briefingLoading = briefingQ.isLoading;

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
              briefingQ.refetch();
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

      {briefingQ.error ? <ErrorState error={briefingQ.error} /> : null}

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
    </>
  );
}
