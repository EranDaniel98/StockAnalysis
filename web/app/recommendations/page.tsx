"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo } from "react";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
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
import { api, type PaperRecommendationItem } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtDate, fmtNumber, fmtPct, fmtUSD, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

type Outcome = NonNullable<PaperRecommendationItem["outcome"]>;

function scoreToneClass(score: number | null | undefined): string {
  if (score === null || score === undefined || Number.isNaN(score))
    return "text-muted-foreground";
  if (score >= 60) return "text-bullish";
  if (score <= 40) return "text-bearish";
  return "text-neutral";
}

function actionToneClass(action: string): string {
  if (action === "STRONG BUY" || action === "BUY") return "text-bullish";
  if (action === "STRONG SELL" || action === "SELL") return "text-bearish";
  if (action === "HOLD") return "text-neutral";
  return "text-muted-foreground";
}

// Closed-outcome set drives win-rate denominator and the bar.
const CLOSED_OUTCOMES: ReadonlySet<Outcome> = new Set([
  "target_hit",
  "stop_hit",
  "manual",
  "other",
]);

// Visual order for the distribution bar (left → right narrative).
const BAR_ORDER: ReadonlyArray<{
  key: Outcome | "pending" | "skipped";
  label: string;
  swatch: string;
}> = [
  { key: "target_hit", label: "target hit", swatch: "bg-bullish" },
  { key: "manual", label: "manual", swatch: "bg-primary" },
  { key: "open", label: "open", swatch: "bg-primary/50" },
  { key: "stop_hit", label: "stop hit", swatch: "bg-bearish" },
  { key: "pending", label: "pending", swatch: "bg-muted-foreground/30" },
  { key: "skipped", label: "skipped", swatch: "bg-muted-foreground/15" },
  { key: "other", label: "other", swatch: "bg-neutral" },
];

function OutcomeCell({ row }: { row: PaperRecommendationItem }) {
  const o = row.outcome;
  if (!o) {
    return <span className="text-muted-foreground">—</span>;
  }
  const wrapper =
    "inline-flex items-center gap-1.5 font-mono text-xs uppercase tracking-wider";
  switch (o) {
    case "target_hit":
      return (
        <span className={cn(wrapper, "text-bullish")}>
          <span className="h-1.5 w-1.5 rounded-full bg-bullish" aria-hidden />
          target hit
        </span>
      );
    case "stop_hit":
      return (
        <span className={cn(wrapper, "text-bearish")}>
          <span className="h-1.5 w-1.5 rounded-full bg-bearish" aria-hidden />
          stop hit
        </span>
      );
    case "manual":
      return (
        <span className={cn(wrapper, "text-primary")}>
          <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden />
          manual close
        </span>
      );
    case "open":
      return (
        <span className={cn(wrapper, "text-primary")}>
          <span
            className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse"
            aria-hidden
          />
          open
        </span>
      );
    case "pending":
      return (
        <span className={cn(wrapper, "text-muted-foreground")}>
          <span
            className="h-1.5 w-1.5 rounded-full bg-muted-foreground"
            aria-hidden
          />
          pending
        </span>
      );
    case "skipped":
      return (
        <span
          className={cn(wrapper, "text-muted-foreground")}
          title={row.skip_reason ?? undefined}
        >
          <span
            className="h-1.5 w-1.5 rounded-full bg-muted-foreground/50"
            aria-hidden
          />
          skipped
        </span>
      );
    case "other":
      return (
        <span className={cn(wrapper, "text-neutral")}>
          <span className="h-1.5 w-1.5 rounded-full bg-neutral" aria-hidden />
          {/* Backend returns the raw exit_reason here; fall back to "closed". */}
          {"closed"}
        </span>
      );
    default:
      return <span className="text-muted-foreground">—</span>;
  }
}

export default function RecommendationsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.recommendations.list({ limit: 100 }),
    queryFn: () => api.recommendations.list({ limit: 100 }),
  });

  const stats = useMemo(() => {
    if (!data || data.length === 0) {
      return {
        total: 0,
        submitted: 0,
        skipped: 0,
        submittedPct: 0,
        skippedPct: 0,
        latest: null as { ts: string; ticker: string } | null,
        closedTotal: 0,
        closedWinners: 0,
        winRate: 0,
        outcomeCounts: {} as Record<string, number>,
      };
    }
    let submitted = 0;
    let skipped = 0;
    let closedTotal = 0;
    let closedWinners = 0;
    const outcomeCounts: Record<string, number> = {};
    for (const r of data) {
      if (r.submitted) submitted += 1;
      if (r.skip_reason) skipped += 1;
      if (r.outcome) {
        outcomeCounts[r.outcome] = (outcomeCounts[r.outcome] ?? 0) + 1;
        if (CLOSED_OUTCOMES.has(r.outcome)) {
          closedTotal += 1;
          if ((r.realized_pnl_pct ?? 0) > 0) closedWinners += 1;
        }
      }
    }
    const total = data.length;
    const latestRow = data.reduce((acc, r) =>
      new Date(r.scan_timestamp).getTime() > new Date(acc.scan_timestamp).getTime()
        ? r
        : acc,
    );
    return {
      total,
      submitted,
      skipped,
      submittedPct: total > 0 ? (submitted / total) * 100 : 0,
      skippedPct: total > 0 ? (skipped / total) * 100 : 0,
      latest: { ts: latestRow.scan_timestamp, ticker: latestRow.ticker },
      closedTotal,
      closedWinners,
      winRate: closedTotal > 0 ? (closedWinners / closedTotal) * 100 : 0,
      outcomeCounts,
    };
  }, [data]);

  const winRateSubTone: "bullish" | "bearish" | "neutral" =
    stats.closedTotal === 0
      ? "neutral"
      : stats.winRate >= 50
        ? "bullish"
        : stats.winRate < 40
          ? "bearish"
          : "neutral";

  // Build bar segments from non-zero counts in the canonical visual order.
  const barSegments = BAR_ORDER.map((seg) => ({
    ...seg,
    count: stats.outcomeCounts[seg.key] ?? 0,
  })).filter((seg) => seg.count > 0);
  const barTotal = barSegments.reduce((s, x) => s + x.count, 0);

  return (
    <>
      <PageHeader
        title="Recommendations"
        description="Historical paper-trade recommendations from `paper trade` runs."
      />

      {error ? <ErrorState error={error} /> : null}

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <ScoreboardTile
          label="Total"
          value={isLoading ? "—" : String(stats.total)}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Submitted"
          value={isLoading ? "—" : String(stats.submitted)}
          sub={
            isLoading || stats.total === 0
              ? undefined
              : `${stats.submittedPct.toFixed(0)}% of total`
          }
          subTone={stats.submittedPct > 50 ? "bullish" : "neutral"}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Win rate"
          tooltip="Closed-trade winners ÷ total closed. Counts only OUTCOMES that actually exited (target_hit / stop_hit / manual / other). open and pending rows don't contribute."
          value={
            isLoading
              ? "—"
              : stats.closedTotal === 0
                ? "—"
                : (
                  <span className={cn(
                    winRateSubTone === "bullish"
                      ? "text-bullish"
                      : winRateSubTone === "bearish"
                        ? "text-bearish"
                        : "text-foreground",
                  )}>
                    {`${stats.winRate.toFixed(1)}%`}
                  </span>
                )
          }
          sub={
            isLoading
              ? undefined
              : stats.closedTotal === 0
                ? "no closed trades yet"
                : `${stats.closedWinners}/${stats.closedTotal} closed wins`
          }
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Skipped"
          value={isLoading ? "—" : String(stats.skipped)}
          sub={
            isLoading || stats.total === 0
              ? undefined
              : `${stats.skippedPct.toFixed(0)}% of total`
          }
          subTone={stats.skippedPct > 50 ? "bearish" : "neutral"}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Latest"
          value={
            isLoading || !stats.latest ? (
              "—"
            ) : (
              <span className="font-mono text-base tracking-tight">
                {fmtDate(stats.latest.ts)}
              </span>
            )
          }
          sub={stats.latest ? stats.latest.ticker : undefined}
          subTone="muted"
          isLoading={isLoading}
        />
      </div>

      {isLoading || !data || data.length === 0 || barTotal === 0 ? (
        <div className="my-4 h-1.5 rounded border border-border bg-muted/30" />
      ) : (
        <div className="my-4 space-y-1">
          <div className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
            Outcome distribution
          </div>
          <div className="flex h-1.5 w-full overflow-hidden rounded border border-border bg-card">
            {barSegments.map((seg) => (
              <div
                key={seg.key}
                className={seg.swatch}
                style={{ width: `${(seg.count / barTotal) * 100}%` }}
                aria-label={`${seg.label}: ${seg.count}`}
              />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            {barSegments.map((seg) => (
              <span key={seg.key} className="inline-flex items-center gap-1.5">
                <span
                  className={cn("h-1.5 w-1.5 rounded-full", seg.swatch)}
                  aria-hidden
                />
                {seg.label} {seg.count}
              </span>
            ))}
          </div>
        </div>
      )}

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>History</CardTitle>
          <CardDescription>
            {data ? `${data.length} entries` : "Loading…"}
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-2 p-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-7 w-full" />
              ))}
            </div>
          ) : !data || data.length === 0 ? (
            <p className="text-muted-foreground text-sm py-12 text-center font-mono">
              No paper-trade recommendations yet.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground py-2 px-3">
                    When
                  </TableHead>
                  <TableHead className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground py-2 px-3">
                    Ticker
                  </TableHead>
                  <TableHead className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground py-2 px-3">
                    Strategy
                  </TableHead>
                  <TableHead className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground py-2 px-3">
                    Action
                  </TableHead>
                  <TableHead className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground text-right py-2 px-3">
                    Score
                  </TableHead>
                  <TableHead className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground text-right py-2 px-3">
                    Entry
                  </TableHead>
                  <TableHead className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground text-right py-2 px-3">
                    Stop
                  </TableHead>
                  <TableHead className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground text-right py-2 px-3">
                    Target
                  </TableHead>
                  <TableHead className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground py-2 px-3">
                    Outcome
                  </TableHead>
                  <TableHead className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground text-right py-2 px-3">
                    Realized %
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((r) => (
                  <TableRow
                    key={r.id}
                    className="hover:bg-muted/40 border-b border-border last:border-b-0"
                  >
                    <TableCell className="text-muted-foreground text-xs py-2 px-3">
                      {fmtDate(r.scan_timestamp)}
                    </TableCell>
                    <TableCell className="py-2 px-3">
                      <Link
                        href={`/stocks/${r.ticker}`}
                        className="font-mono text-sm font-semibold text-primary hover:underline underline-offset-2"
                        title="View trade plan"
                      >
                        {r.ticker}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs py-2 px-3">
                      {r.strategy}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "font-mono text-xs uppercase tracking-wider py-2 px-3",
                        actionToneClass(r.action),
                      )}
                    >
                      {r.action}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "font-mono tabular-nums text-right py-2 px-3",
                        scoreToneClass(r.composite_score),
                      )}
                    >
                      {fmtNumber(r.composite_score, 1)}
                    </TableCell>
                    <TableCell className="font-mono tabular-nums text-right py-2 px-3">
                      {fmtUSD(r.entry_price)}
                    </TableCell>
                    <TableCell className="font-mono tabular-nums text-right py-2 px-3">
                      {fmtUSD(r.stop_loss)}
                    </TableCell>
                    <TableCell className="font-mono tabular-nums text-right py-2 px-3">
                      {fmtUSD(r.take_profit)}
                    </TableCell>
                    <TableCell className="py-2 px-3 text-xs">
                      <OutcomeCell row={r} />
                    </TableCell>
                    <TableCell
                      className={cn(
                        "font-mono tabular-nums text-right py-2 px-3",
                        r.realized_pnl_pct == null
                          ? "text-muted-foreground"
                          : pnlColorClass(r.realized_pnl_pct),
                      )}
                    >
                      {r.realized_pnl_pct == null
                        ? "—"
                        : fmtPct(r.realized_pnl_pct, 2, true)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}
