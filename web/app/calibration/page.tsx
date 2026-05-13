"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { CalibrationChart } from "@/components/calibration/calibration-chart";
import { computeCalibrationStats } from "@/components/calibration/calibration-stats";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
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
import { api } from "@/lib/api/client";
import { fmtNumber, fmtPct, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

// ─── Min-score filter values (mirrors backend DEFAULT_BANDS lower edges) ────
const MIN_SCORE_OPTIONS = [
  { value: "40", label: ">= 40" },
  { value: "50", label: ">= 50" },
  { value: "60", label: ">= 60" },
  { value: "70", label: ">= 70" },
];

function toneClass(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "text-foreground";
  if (n > 0) return "text-bullish";
  if (n < 0) return "text-bearish";
  return "text-muted-foreground";
}

function toneFor(
  n: number | null | undefined,
): "bullish" | "bearish" | "neutral" | "muted" {
  if (n == null || Number.isNaN(n)) return "muted";
  if (n > 0) return "bullish";
  if (n < 0) return "bearish";
  return "neutral";
}

function icBand(ic: number | null): "strong" | "weak" | "flat" | "negative" {
  if (ic == null || Number.isNaN(ic)) return "flat";
  if (ic >= 0.1) return "strong";
  if (ic > 0) return "weak";
  if (ic < 0) return "negative";
  return "flat";
}

function winRateTone(rate: number | null | undefined): string {
  if (rate == null) return "text-muted-foreground/40";
  if (rate >= 0.55) return "text-bullish";
  if (rate < 0.45) return "text-bearish";
  return "text-foreground";
}

export default function CalibrationPage() {
  const [minScore, setMinScore] = useState<string>("40");
  const { data, isLoading, error } = useQuery({
    queryKey: ["analytics", "calibration", minScore],
    queryFn: () => api.analytics.calibration({ min_score: Number(minScore) }),
  });

  const buckets = useMemo(() => data?.buckets ?? [], [data]);
  const stats = useMemo(() => computeCalibrationStats(buckets), [buckets]);

  const pearsonBand = icBand(stats.pearson);
  const spearmanBand = icBand(stats.spearman);
  const verdict =
    pearsonBand === "strong" && spearmanBand === "strong"
      ? "CALIBRATED"
      : pearsonBand === "negative" || spearmanBand === "negative"
        ? "INVERTED"
        : stats.populatedBins < 2
          ? "INSUFFICIENT DATA"
          : "WEAK";

  return (
    <>
      <PageHeader
        title="Score calibration"
        description="Composite-score vs. realized-return tracking across closed paper trades. Calibrated models climb monotonically left -> right."
        actions={
          data ? (
            <Badge variant="outline" className="font-mono">
              {data.n_total_trades} closed
            </Badge>
          ) : null
        }
      />

      {error ? <ErrorState error={error} /> : null}

      {/* ── Dense filter strip ────────────────────────────────────────── */}
      <div className="border border-border rounded-md bg-card p-3 mb-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_auto] md:items-end">
          <div className="space-y-1 max-w-xs">
            <Label
              htmlFor="min-score"
              className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase"
            >
              Min Composite Score
            </Label>
            <Select
              value={minScore}
              onValueChange={(v) => v && setMinScore(v)}
            >
              <SelectTrigger
                id="min-score"
                className="w-full font-mono text-xs h-8"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MIN_SCORE_OPTIONS.map((opt) => (
                  <SelectItem
                    key={opt.value}
                    value={opt.value}
                    className="font-mono text-xs"
                  >
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground md:pb-2">
            {data
              ? `as of ${new Date(data.as_of).toLocaleString(undefined, { year: "2-digit", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })}`
              : "loading..."}
          </div>
        </div>
      </div>

      {isLoading || !data ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : (
        <div className="space-y-4">
          {/* ── Scoreboard: IC + monotonicity + counts ─────────────────── */}
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            <ScoreboardTile
              label="Pearson IC"
              value={
                <span className={cn(toneClass(stats.pearson))}>
                  {stats.pearson == null
                    ? "—"
                    : fmtNumber(stats.pearson, 3)}
                </span>
              }
              sub={
                stats.pearson == null
                  ? "needs >=2 populated bins"
                  : pearsonBand === "strong"
                    ? "strong positive"
                    : pearsonBand === "weak"
                      ? "weak positive"
                      : pearsonBand === "negative"
                        ? "inverted signal"
                        : "flat"
              }
              subTone={toneFor(stats.pearson)}
            />
            <ScoreboardTile
              label="Spearman IC"
              value={
                <span className={cn(toneClass(stats.spearman))}>
                  {stats.spearman == null
                    ? "—"
                    : fmtNumber(stats.spearman, 3)}
                </span>
              }
              sub={
                stats.spearman == null
                  ? "needs >=2 populated bins"
                  : spearmanBand === "strong"
                    ? "rank-stable"
                    : spearmanBand === "weak"
                      ? "weak rank"
                      : spearmanBand === "negative"
                        ? "rank inverted"
                        : "flat"
              }
              subTone={toneFor(stats.spearman)}
            />
            <ScoreboardTile
              label="Monotonicity"
              value={
                <span
                  className={cn(
                    stats.monotonicityPct == null
                      ? ""
                      : stats.monotonicityPct >= 75
                        ? "text-bullish"
                        : stats.monotonicityPct < 50
                          ? "text-bearish"
                          : "text-foreground",
                  )}
                >
                  {stats.monotonicityPct == null
                    ? "—"
                    : fmtPct(stats.monotonicityPct, 0)}
                </span>
              }
              sub={
                stats.populatedBins > 1
                  ? `${stats.populatedBins} populated bins`
                  : "n/a"
              }
              subTone="muted"
            />
            <ScoreboardTile
              label="Picks Scored"
              value={String(stats.totalScored)}
              sub={`min score ${minScore}`}
              subTone="muted"
            />
          </div>

          {/* ── Verdict strip ─────────────────────────────────────────── */}
          <div className="border-border text-muted-foreground flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 font-mono text-[11px] tracking-wider uppercase">
            <span>CALIBRATION VERDICT</span>
            <span
              className={cn(
                verdict === "CALIBRATED"
                  ? "text-bullish"
                  : verdict === "INVERTED"
                    ? "text-bearish"
                    : "text-foreground",
              )}
            >
              [ {verdict} ]
            </span>
            <span className="ml-auto">
              N {stats.totalScored} | BINS {stats.populatedBins}
            </span>
          </div>

          {/* ── Engine notes (low-N warnings, missing data, etc.) ─────── */}
          {data.notes && data.notes.length > 0 ? (
            <div className="border-border rounded-md border bg-card px-3 py-2 space-y-1">
              {data.notes.map((n, i) => (
                <p
                  key={i}
                  className="font-mono text-[11px] text-muted-foreground"
                >
                  {n}
                </p>
              ))}
            </div>
          ) : null}

          {/* ── Chart panel ───────────────────────────────────────────── */}
          {stats.totalScored > 0 ? (
            <div className="border-border rounded-md border bg-card">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  Avg realized return by score band
                </div>
                <div className="flex items-center gap-3 font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  <LegendSwatch tokenVar="--chart-1" label="Realized" />
                  <LegendSwatch
                    tokenVar="--chart-3"
                    label="Ideal trend"
                    dashed
                  />
                </div>
              </div>
              <div className="p-3">
                <div className="h-64">
                  <CalibrationChart buckets={buckets} />
                </div>
              </div>
            </div>
          ) : (
            <EmptyState />
          )}

          {/* ── Per-bin breakdown table ───────────────────────────────── */}
          {stats.totalScored > 0 ? (
            <div className="border-border rounded-md border bg-card">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  Per-bin breakdown
                </div>
                <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  {buckets.length} bands
                </div>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Score Bin</TableHead>
                    <TableHead className="text-right">N Trades</TableHead>
                    <TableHead className="text-right">Win Rate</TableHead>
                    <TableHead className="text-right">Avg Return</TableHead>
                    <TableHead className="text-right">Median Return</TableHead>
                    <TableHead className="text-right">Share</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {buckets.map((b) => {
                    const share =
                      stats.totalScored > 0
                        ? (b.n_trades / stats.totalScored) * 100
                        : 0;
                    return (
                      <TableRow key={b.label} mono>
                        <TableCell>
                          <span className="text-foreground">{b.label}</span>
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right tabular-nums",
                            b.n_trades === 0
                              ? "text-muted-foreground/40"
                              : "text-foreground",
                          )}
                        >
                          {b.n_trades}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right tabular-nums",
                            winRateTone(b.win_rate),
                          )}
                        >
                          {b.win_rate == null
                            ? "—"
                            : `${fmtNumber((b.win_rate ?? 0) * 100, 0)}%`}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right tabular-nums",
                            pnlColorClass(b.avg_pnl_pct),
                          )}
                        >
                          {b.avg_pnl_pct == null
                            ? "—"
                            : fmtPct(b.avg_pnl_pct, 2, true)}
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right tabular-nums",
                            pnlColorClass(b.median_pnl_pct),
                          )}
                        >
                          {b.median_pnl_pct == null
                            ? "—"
                            : fmtPct(b.median_pnl_pct, 2, true)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">
                          {b.n_trades === 0
                            ? "—"
                            : `${share.toFixed(0)}%`}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          ) : null}
        </div>
      )}
    </>
  );
}

// ─── Inline chart-legend swatch ──────────────────────────────────────────────
function LegendSwatch({
  tokenVar,
  label,
  dashed,
}: {
  tokenVar: string;
  label: string;
  dashed?: boolean;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        aria-hidden
        className={cn("inline-block h-0.5 w-4", dashed && "border-t border-dashed")}
        style={{
          background: dashed ? "transparent" : `var(${tokenVar})`,
          borderColor: dashed ? `var(${tokenVar})` : undefined,
        }}
      />
      <span>{label}</span>
    </span>
  );
}

// ─── Empty state ─────────────────────────────────────────────────────────────
function EmptyState() {
  return (
    <div className="border-border rounded-md border bg-card p-8 text-center">
      <p className="font-mono text-xs text-muted-foreground">
        No calibration data. Score-vs-return tracking requires closed positions.
      </p>
    </div>
  );
}
