"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScanProgress } from "@/components/scan-progress";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type ScanResultItem } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { useScanStream } from "@/lib/api/use-scan-stream";
import { fmtDate, fmtNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

const STRATEGIES = [
  "swing_trading",
  "short_term_momentum",
  "long_term_growth",
  "value_investing",
  "dividend_income",
];

type FormShape = {
  strategy: string;
  budget: string;
  theme: string;
  top: string;
};

// ─── Score / action variant mapping ──────────────────────────────────────────
// Bands per the reskin contract: >=75 bullish, >=55 default outline,
// <45 bearish, else neutral. Action variants follow the BUY/SELL/HOLD
// semantics directly.

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

function scoreVariant(score: number): BadgeVariant {
  if (score >= 75) return "bullish";
  if (score >= 55) return "outline";
  if (score < 45) return "bearish";
  return "neutral";
}

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

export default function ScanPage() {
  const qc = useQueryClient();
  const { state: streamState, start: startStream, abort, reset } = useScanStream();

  const { register, handleSubmit, watch, setValue } = useForm<FormShape>({
    defaultValues: {
      strategy: "swing_trading",
      budget: "",
      theme: "",
      top: "10",
    },
  });

  const resultQuery = useQuery({
    queryKey: streamState.complete
      ? qk.scans.detail(streamState.complete.run_id)
      : ["scans", "detail", "_idle"],
    queryFn: () => api.scans.get(streamState.complete!.run_id),
    enabled: streamState.complete !== null,
  });

  useEffect(() => {
    if (streamState.complete) {
      toast.success(`Scan complete — ${streamState.complete.n_results} candidates`);
      qc.invalidateQueries({ queryKey: qk.scans.all });
    }
  }, [streamState.complete, qc]);

  useEffect(() => {
    if (streamState.error) {
      toast.error(streamState.error);
    }
  }, [streamState.error]);

  const historyQuery = useQuery({
    queryKey: qk.scans.list({ limit: 10 }),
    queryFn: () => api.scans.list({ limit: 10 }),
    // Suppress refetch on focus during an active scan to avoid stomping on
    // the progress UI with a re-render of stale data.
    enabled: !streamState.active,
  });

  function onSubmit(values: FormShape) {
    startStream({
      strategy: values.strategy,
      budget: values.budget ? Number(values.budget) : null,
      theme: values.theme || null,
      sector: null,
      top: values.top ? Number(values.top) : null,
      fresh: false,
    });
  }

  const strategy = watch("strategy");
  const showProgress =
    streamState.active || streamState.complete || streamState.error;

  return (
    <>
      <PageHeader
        title="Scan"
        description="Trigger a market scan. Progress streams from the backend over SSE."
      />

      {/* ── Dense control strip (no card padding, single hairline row) ── */}
      <form
        onSubmit={handleSubmit(onSubmit)}
        className="border border-border rounded-md bg-card p-3 mb-4"
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[1.4fr_1.6fr_1fr_0.7fr_auto] md:items-end">
          <div className="space-y-1">
            <Label
              htmlFor="strategy"
              className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase"
            >
              Strategy
            </Label>
            <Select
              value={strategy}
              onValueChange={(v) => v && setValue("strategy", v)}
            >
              <SelectTrigger
                id="strategy"
                className="w-full font-mono text-xs h-8"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STRATEGIES.map((s) => (
                  <SelectItem key={s} value={s} className="font-mono text-xs">
                    {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label
              htmlFor="theme"
              className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase"
            >
              Theme / Universe
            </Label>
            <Input
              id="theme"
              placeholder="all · or e.g. artificial_intelligence"
              className="font-mono text-xs"
              {...register("theme")}
            />
          </div>

          <div className="space-y-1">
            <Label
              htmlFor="budget"
              className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase"
            >
              Budget USD
            </Label>
            <Input
              id="budget"
              type="number"
              min={0}
              step={100}
              placeholder="10000"
              className="font-mono text-xs tabular-nums"
              {...register("budget")}
            />
          </div>

          <div className="space-y-1">
            <Label
              htmlFor="top"
              className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase"
            >
              Top N
            </Label>
            <Input
              id="top"
              type="number"
              min={1}
              max={200}
              className="font-mono text-xs tabular-nums"
              {...register("top")}
            />
          </div>

          <div className="flex gap-2">
            <Button
              type="submit"
              disabled={streamState.active}
              size="sm"
              className="font-mono text-[11px] tracking-wider uppercase h-8"
            >
              {streamState.active ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="mr-1.5 h-3.5 w-3.5" />
              )}
              {streamState.active ? "Scanning" : "Start Scan"}
            </Button>
            {streamState.active ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={abort}
                aria-label="Cancel scan"
                className="h-8"
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            ) : showProgress ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={reset}
                className="font-mono text-[11px] tracking-wider uppercase h-8"
              >
                Clear
              </Button>
            ) : null}
          </div>
        </div>
      </form>

      {/* ── Live progress (during/after scan) ── */}
      {showProgress ? (
        <div className="mb-4">
          <ScanProgress state={streamState} />
        </div>
      ) : null}

      {/* ── Scoreboard + results, or empty state, or history ── */}
      {streamState.complete ? (
        <ResultsSection
          runId={streamState.complete.run_id}
          strategy={streamState.complete.strategy}
          nResults={streamState.complete.n_results}
          query={resultQuery}
        />
      ) : !showProgress ? (
        <RecentScans query={historyQuery} />
      ) : null}
    </>
  );
}

// ─── Results: scoreboard + dense table ───────────────────────────────────────

function ResultsSection({
  runId,
  strategy,
  nResults,
  query,
}: {
  runId: string;
  strategy: string;
  nResults: number;
  query: ReturnType<typeof useQuery<Awaited<ReturnType<typeof api.scans.get>>>>;
}) {
  const results = query.data?.results ?? [];

  const stats = useMemo(() => {
    let strongBuys = 0;
    let buyOrHold = 0;
    for (const r of results) {
      if (r.action === "STRONG BUY") strongBuys += 1;
      if (r.action === "STRONG BUY" || r.action === "BUY" || r.action === "HOLD")
        buyOrHold += 1;
    }
    return { strongBuys, buyOrHold };
  }, [results]);

  return (
    <>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4 mb-4">
        <ScoreboardTile
          label="Total Scanned"
          value={query.data ? String(query.data.n_candidates) : "—"}
          sub={
            query.data ? `${query.data.n_results} above threshold` : undefined
          }
          subTone="muted"
          isLoading={query.isLoading}
        />
        <ScoreboardTile
          label="Strong Buys"
          value={query.isLoading ? "—" : String(stats.strongBuys)}
          sub={
            query.isLoading
              ? undefined
              : stats.strongBuys > 0
                ? "high-conviction signals"
                : "none this run"
          }
          subTone={stats.strongBuys > 0 ? "bullish" : "muted"}
          isLoading={query.isLoading}
        />
        <ScoreboardTile
          label="Buys + Holds"
          value={query.isLoading ? "—" : String(stats.buyOrHold)}
          sub={
            query.isLoading
              ? undefined
              : results.length > 0
                ? `of ${results.length} candidates`
                : undefined
          }
          subTone="muted"
          isLoading={query.isLoading}
        />
        <ScoreboardTile
          label="Strategy"
          value={
            <span className="font-mono text-base tracking-tight">
              {strategy}
            </span>
          }
          sub={`run ${runId.slice(0, 8)} · ${nResults} returned`}
          subTone="muted"
        />
      </div>

      <div className="border border-border rounded-md bg-card">
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
            Candidates
          </div>
          <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
            {results.length} rows
          </div>
        </div>
        <div className="px-1">
          {query.error ? (
            <div className="p-3">
              <ErrorState error={query.error} />
            </div>
          ) : query.isLoading ? (
            <div className="space-y-1 p-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-6 w-full" />
              ))}
            </div>
          ) : (
            <ResultsTable results={results} />
          )}
        </div>
      </div>
    </>
  );
}

function ResultsTable({ results }: { results: ScanResultItem[] }) {
  if (results.length === 0) {
    return (
      <p className="text-muted-foreground py-8 text-center font-mono text-xs tracking-wider uppercase">
        No candidates above the strategy threshold.
      </p>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Ticker</TableHead>
          <TableHead>Action</TableHead>
          <TableHead className="text-right">Score</TableHead>
          <TableHead className="text-right">Conf.</TableHead>
          <TableHead className="text-right">Bull/Bear</TableHead>
          <TableHead>Sub-scores</TableHead>
          <TableHead>Sector</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {results.map((r) => (
          <TableRow key={r.ticker} mono>
            <TableCell>
              <Link href={`/stocks/${r.ticker}`}>
                <span className="font-mono text-foreground hover:text-primary transition-colors">
                  {r.ticker}
                </span>
              </Link>
            </TableCell>
            <TableCell>
              <Badge variant={actionVariant(r.action)}>{r.action}</Badge>
            </TableCell>
            <TableCell className="text-right">
              <Badge variant={scoreVariant(r.composite_score)}>
                {fmtNumber(r.composite_score, 1)}
              </Badge>
            </TableCell>
            <TableCell
              className={cn(
                "text-right font-mono text-[11px] tracking-wider uppercase",
                r.confidence === "high"
                  ? "text-bullish"
                  : r.confidence === "low"
                    ? "text-bearish"
                    : "text-muted-foreground",
              )}
            >
              {r.confidence}
            </TableCell>
            <TableCell className="text-right tabular-nums">
              <span className="text-bullish">{r.bullish_signals}</span>
              <span className="text-muted-foreground/40 mx-0.5">/</span>
              <span className="text-bearish">{r.bearish_signals}</span>
            </TableCell>
            <TableCell className="min-w-[200px]">
              <SubScoreInline sub={r.sub_scores ?? {}} />
            </TableCell>
            <TableCell className="text-muted-foreground text-xs">
              {r.sector}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * Inline ASCII-bar style sub-score row. Each entry rendered as
 * `LABEL [████------] 68` in monospace; bar segments are 10 wide so the
 * column stays compact at text-xs even with 6 entries.
 */
function SubScoreInline({ sub }: { sub: Record<string, number | undefined> }) {
  const entries = Object.entries(sub).slice(0, 6);
  if (entries.length === 0) {
    return <span className="text-muted-foreground/40 font-mono">—</span>;
  }
  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 font-mono text-[10px]">
      {entries.map(([k, v]) => {
        const score = v ?? 0;
        const filled = Math.max(0, Math.min(10, Math.round(score / 10)));
        const bar = "█".repeat(filled) + "░".repeat(10 - filled);
        const tone =
          score >= 70
            ? "text-bullish"
            : score < 40
              ? "text-bearish"
              : "text-muted-foreground";
        return (
          <div key={k} className="flex items-center gap-1.5 tabular-nums">
            <span className="text-muted-foreground/70 w-14 truncate uppercase tracking-wider">
              {k.slice(0, 6)}
            </span>
            <span className={cn("tracking-tighter", tone)}>{bar}</span>
            <span className="text-foreground w-6 text-right">
              {v == null ? "—" : v.toFixed(0)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─── Recent scans (idle / empty state combined) ──────────────────────────────

function RecentScans({
  query,
}: {
  query: ReturnType<typeof useQuery<Awaited<ReturnType<typeof api.scans.list>>>>;
}) {
  if (query.isLoading) {
    return (
      <div className="border border-border rounded-md bg-card p-3 space-y-1">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-6 w-full" />
        ))}
      </div>
    );
  }

  if (query.error) {
    return (
      <div className="border border-border rounded-md bg-card p-3">
        <ErrorState error={query.error} />
      </div>
    );
  }

  if (!query.data || query.data.length === 0) {
    return (
      <div className="border border-border rounded-md bg-card p-8 text-center">
        <p className="font-mono text-xs text-muted-foreground">
          No scan yet. Configure strategy + universe above and press{" "}
          <span className="text-primary">[ Start Scan ]</span>.
        </p>
      </div>
    );
  }

  return (
    <div className="border border-border rounded-md bg-card">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
          Recent scans
        </div>
        <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
          last {query.data.length}
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>When</TableHead>
            <TableHead>Strategy</TableHead>
            <TableHead>Top ticker</TableHead>
            <TableHead className="text-right">Top score</TableHead>
            <TableHead className="text-right">Candidates</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {query.data.map((s) => (
            <TableRow key={s.run_id} mono>
              <TableCell className="text-muted-foreground text-xs">
                {fmtDate(s.scan_timestamp)}
              </TableCell>
              <TableCell>
                <span className="text-foreground">{s.strategy}</span>
              </TableCell>
              <TableCell>
                <span className="text-foreground">{s.top_ticker ?? "—"}</span>
              </TableCell>
              <TableCell className="text-right">
                {s.top_score != null ? (
                  <span className={scoreToneClass(s.top_score)}>
                    {fmtNumber(s.top_score, 1)}
                  </span>
                ) : (
                  <span className="text-muted-foreground/40">—</span>
                )}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {s.n_candidates}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
