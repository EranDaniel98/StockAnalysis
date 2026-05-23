"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownRight,
  ArrowUpRight,
  ChevronRight,
  CircleAlert,
} from "lucide-react";
import Link from "next/link";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type ExecutionSummary } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtRelativeTime, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function ExecutionsListPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.executions.list(50),
    queryFn: () => api.executions.list(50),
  });

  const totals = (data ?? []).reduce(
    (acc, row) => {
      acc.submitted += row.n_submitted;
      acc.skipped += row.n_skipped;
      acc.failed += row.n_failed;
      return acc;
    },
    { submitted: 0, skipped: 0, failed: 0 },
  );

  return (
    <>
      <PageHeader
        title="Execution log"
        description="Per-day paper-trade results from scripts.paper_trade_factor_picks. Each row records what landed at the broker, what got skipped by the AI sanity gate, and what failed."
      />

      {error ? <ErrorState error={error} /> : null}

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="Trading days"
          value={isLoading ? "—" : String((data ?? []).length)}
          sub={
            (data ?? []).length > 0
              ? `latest ${fmtRelativeTime((data ?? [])[0]?.date ?? "")}`
              : "no logs yet"
          }
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Submitted orders"
          tooltip="Sum across every execution day visible in the list. Includes longs + shorts in long_short mode."
          value={isLoading ? "—" : (
            <span className="text-bullish">{totals.submitted}</span>
          )}
          sub="across all days"
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Skipped"
          tooltip="Orders the sanity gate refused, or that paper_trade decided not to submit (size too small, etc.)."
          value={isLoading ? "—" : String(totals.skipped)}
          sub={totals.skipped > 0 ? "review reasons" : "none"}
          subTone={totals.skipped > 0 ? "neutral" : "muted"}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Failed"
          tooltip="Orders Alpaca rejected (insufficient qty, market closed, etc.). Each row carries the broker's error string."
          value={
            isLoading ? "—" : (
              <span className={cn(totals.failed > 0 ? "text-bearish" : "text-foreground")}>
                {totals.failed}
              </span>
            )
          }
          sub={totals.failed > 0 ? "drill into a day to investigate" : "none"}
          subTone={totals.failed > 0 ? "bearish" : "muted"}
          isLoading={isLoading}
        />
      </div>

      {isLoading ? (
        <div className="mt-4 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : (data ?? []).length === 0 ? (
        <EmptyState />
      ) : (
        <div className="mt-4 border border-border rounded-md bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead>Strategy</TableHead>
                <TableHead className="text-right">Equity</TableHead>
                <TableHead className="text-right">Basket</TableHead>
                <TableHead className="text-right">Submitted</TableHead>
                <TableHead className="text-right">Skipped</TableHead>
                <TableHead className="text-right">Failed</TableHead>
                <TableHead>Sanity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data ?? []).map((row) => (
                <ExecutionRow key={row.date} row={row} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}

function ExecutionRow({ row }: { row: ExecutionSummary }) {
  return (
    <TableRow mono className="group">
      <TableCell>
        <Link
          href={`/recommendations/${encodeURIComponent(row.date)}`}
          className="flex items-center gap-1 font-mono text-foreground hover:text-primary"
        >
          {row.date}
          <ChevronRight className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" />
        </Link>
      </TableCell>
      <TableCell className="text-[11px] text-muted-foreground">
        {row.strategy}
        {row.long_short_mode ? (
          <Badge
            variant="outline"
            className="ml-1.5 text-[9px] font-mono uppercase tracking-wider"
          >
            L/S
          </Badge>
        ) : null}
      </TableCell>
      <TableCell className="text-right font-mono tabular-nums">
        {row.equity_at_start != null ? fmtUSD(row.equity_at_start, true) : "—"}
      </TableCell>
      <TableCell className="text-right font-mono tabular-nums text-[11px]">
        <span className="text-bullish">{row.n_longs}L</span>
        {row.n_shorts > 0 ? (
          <>
            <span className="text-muted-foreground/40 mx-0.5">/</span>
            <span className="text-bearish">{row.n_shorts}S</span>
          </>
        ) : null}
      </TableCell>
      <TableCell className={cn(
        "text-right font-mono tabular-nums",
        row.n_submitted > 0 ? "text-bullish" : "text-muted-foreground",
      )}>
        {row.n_submitted}
      </TableCell>
      <TableCell className="text-right font-mono tabular-nums text-muted-foreground">
        {row.n_skipped}
      </TableCell>
      <TableCell className={cn(
        "text-right font-mono tabular-nums",
        row.n_failed > 0 ? "text-bearish" : "text-muted-foreground",
      )}>
        {row.n_failed}
      </TableCell>
      <TableCell>
        {row.sanity_applied ? (
          <Badge
            variant="outline"
            className="text-[9px] font-mono uppercase tracking-wider gap-1 border-bullish/40 bg-bullish/5 text-bullish"
            title={`AI sanity gate applied (mode: ${row.sanity_long_rejected} rejected, ${row.sanity_long_cautioned} cautioned)`}
          >
            applied
            {row.sanity_long_rejected + row.sanity_long_cautioned > 0 ? (
              <span className="opacity-70">
                {row.sanity_long_rejected + row.sanity_long_cautioned}
              </span>
            ) : null}
          </Badge>
        ) : (
          <span className="text-[10px] font-mono text-muted-foreground/50 uppercase tracking-wider">
            off
          </span>
        )}
      </TableCell>
    </TableRow>
  );
}

function EmptyState() {
  return (
    <div className="mt-4 border border-border rounded-md bg-card p-12 text-center">
      <CircleAlert className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
        No execution logs on disk
      </p>
      <p className="mt-2 text-sm text-muted-foreground">
        Logs live at{" "}
        <code className="bg-muted px-1 py-0.5 rounded text-xs">
          data/daily_picks/execution_log/*.json
        </code>
        . Run{" "}
        <code className="bg-muted px-1 py-0.5 rounded text-xs">
          uv run python -m scripts.paper_trade_factor_picks
        </code>
        {" "}to create one.
      </p>
      <Link
        href="/scan"
        className="mt-3 inline-flex items-center gap-1 text-primary text-sm hover:underline"
      >
        Run the daily pipeline <ArrowUpRight className="h-3 w-3" />
      </Link>
      <Link
        href="/buy-signals"
        className="ml-4 mt-3 inline-flex items-center gap-1 text-primary text-sm hover:underline"
      >
        Today&apos;s actions <ArrowDownRight className="h-3 w-3" />
      </Link>
    </div>
  );
}
