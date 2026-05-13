"use client";

import { useQuery } from "@tanstack/react-query";
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
import { api } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtDate, fmtNumber, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

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
      };
    }
    let submitted = 0;
    let skipped = 0;
    for (const r of data) {
      if (r.submitted) submitted += 1;
      if (r.skip_reason) skipped += 1;
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
    };
  }, [data]);

  return (
    <>
      <PageHeader
        title="Recommendations"
        description="Historical paper-trade recommendations from `paper trade` runs."
      />

      {error ? <ErrorState error={error} /> : null}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
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
                    Status
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
                      <span className="font-mono text-sm font-semibold">
                        {r.ticker}
                      </span>
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
                      {r.submitted ? (
                        <span className="inline-flex items-center gap-1.5">
                          <span className="h-1.5 w-1.5 rounded-full bg-bullish" />
                          submitted
                        </span>
                      ) : r.skip_reason ? (
                        <span
                          className="inline-flex items-center gap-1.5 text-muted-foreground"
                          title={r.skip_reason}
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-bearish" />
                          skipped
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
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
