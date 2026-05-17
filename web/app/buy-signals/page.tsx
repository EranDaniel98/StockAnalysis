"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Calendar } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type BuySignal } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

type GradeFilter = "ALL" | "STRONG_ONLY";

function scoreToneClass(score: number): string {
  if (score >= 70) return "text-bullish";
  if (score >= 55) return "text-bullish/80";
  return "text-foreground";
}

function actionBadgeClass(action: BuySignal["action"]): string {
  return action === "STRONG BUY"
    ? "bg-bullish/20 text-bullish border-bullish/40"
    : "bg-bullish/10 text-bullish/90 border-bullish/30";
}

/**
 * Earnings urgency hint. Anything <= 14 calendar days out gets a flag so
 * the user knows the trade may straddle a binary event. Returns null when
 * the next event is unknown or further out.
 */
function earningsHint(rec: BuySignal): { label: string; tone: string } | null {
  const ts = rec.earnings_announcement_ts ?? rec.earnings_call_ts;
  if (!ts) return null;
  const days = Math.round((ts * 1000 - Date.now()) / 86_400_000);
  if (days < 0 || days > 14) return null;
  if (days === 0) return { label: "Reports today", tone: "text-bearish" };
  if (days === 1) return { label: "Reports tomorrow", tone: "text-bearish" };
  if (days <= 5) return { label: `Reports in ${days}d`, tone: "text-bearish" };
  return { label: `Reports in ${days}d`, tone: "text-neutral" };
}

function formatScanAge(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso.slice(0, 10);
  const days = Math.floor((Date.now() - t) / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  return `${days}d ago`;
}

export default function BuySignalsPage() {
  const [grade, setGrade] = useState<GradeFilter>("ALL");
  // Per-sub-score minimum thresholds. Empty = no filter on that key.
  // The UI lists every sub-score the latest scans emit; the user types
  // a number (0-100) into the field to require that sub-score >= N.
  const [subMinima, setSubMinima] = useState<Record<string, string>>({});

  const { data, isLoading, error } = useQuery({
    queryKey: qk.scans.latestBuys({ strongOnly: grade === "STRONG_ONLY" }),
    queryFn: () =>
      api.scans.latestBuys({ strongOnly: grade === "STRONG_ONLY" }),
  });

  const rawRows = data ?? [];

  // Union of every sub-score key any returned row exposes. Used to
  // populate the filter UI even when only one strategy's row carries
  // that sub-score (e.g. alpha158 only fires for some strategies).
  const subScoreKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const r of rawRows) {
      if (r.sub_scores) {
        for (const k of Object.keys(r.sub_scores)) keys.add(k);
      }
    }
    return Array.from(keys).sort();
  }, [rawRows]);

  // Apply sub-score minima. A row passes if for every active filter
  // its sub_scores[key] exists AND meets the minimum. Missing keys are
  // treated as failures — "I want alpha158 ≥ 70" means "ticker must
  // have a measured alpha158 of at least 70", not "no info is fine".
  const rows = useMemo(() => {
    const activeFilters = Object.entries(subMinima)
      .map(([k, v]) => [k, parseFloat(v)] as const)
      .filter(([, v]) => Number.isFinite(v) && v > 0);
    if (activeFilters.length === 0) return rawRows;
    return rawRows.filter((r) => {
      const subs = r.sub_scores ?? {};
      return activeFilters.every(([k, min]) => {
        const v = subs[k];
        return typeof v === "number" && Number.isFinite(v) && v >= min;
      });
    });
  }, [rawRows, subMinima]);

  const stats = useMemo(() => {
    const strong = rows.filter((r) => r.action === "STRONG BUY").length;
    const buy = rows.filter((r) => r.action === "BUY").length;
    const topScore = rows.length > 0 ? rows[0] : null;
    const maxConsensus = rows.reduce<BuySignal | null>(
      (best, r) =>
        best === null || r.consensus_count > best.consensus_count ? r : best,
      null,
    );
    return { strong, buy, topScore, maxConsensus };
  }, [rows]);

  const activeSubFilterCount = Object.entries(subMinima).filter(
    ([, v]) => Number.isFinite(parseFloat(v)) && parseFloat(v) > 0,
  ).length;

  return (
    <>
      <PageHeader
        title="BUY signals · right now"
        description="Tickers currently flagged BUY+ in the latest scan per strategy. Cross-strategy consensus is the strongest tell — when multiple strategies agree, that's a stack."
      />

      {error ? <ErrorState error={error} /> : null}

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="STRONG BUY"
          tooltip="Tickers with action=STRONG BUY in the latest scan per strategy. STRONG BUY requires composite score ≥ 70."
          value={
            <span className="text-bullish">{stats.strong}</span>
          }
        />
        <ScoreboardTile
          label="BUY"
          tooltip="Tickers with action=BUY (composite score 50-69) in the latest scan per strategy."
          value={
            <span className="text-bullish/80">{stats.buy}</span>
          }
        />
        <ScoreboardTile
          label="Top score"
          tooltip="The single highest composite_score across all BUY+ rows."
          value={
            stats.topScore ? (
              <Link
                href={`/stocks/${encodeURIComponent(stats.topScore.ticker)}`}
                className="font-mono hover:underline"
              >
                {stats.topScore.ticker}
              </Link>
            ) : (
              "—"
            )
          }
          sub={
            stats.topScore
              ? `${stats.topScore.composite_score.toFixed(1)} · ${stats.topScore.strategy}`
              : undefined
          }
          subTone="muted"
        />
        <ScoreboardTile
          label="Strongest consensus"
          tooltip="Ticker flagged BUY+ by the most strategies. Multiple-strategy agreement = stronger conviction."
          value={
            stats.maxConsensus ? (
              <Link
                href={`/stocks/${encodeURIComponent(stats.maxConsensus.ticker)}`}
                className="font-mono hover:underline"
              >
                {stats.maxConsensus.ticker}
              </Link>
            ) : (
              "—"
            )
          }
          sub={
            stats.maxConsensus
              ? `${stats.maxConsensus.consensus_count} strategies`
              : undefined
          }
          subTone="muted"
        />
      </div>

      <div className="mt-4 flex items-center gap-2">
        <span className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
          Filter
        </span>
        <button
          type="button"
          onClick={() => setGrade("ALL")}
          className={cn(
            "px-2 py-1 text-xs font-mono uppercase tracking-wider rounded border transition-colors",
            grade === "ALL"
              ? "border-bullish text-bullish bg-bullish/10"
              : "border-border text-muted-foreground hover:text-foreground",
          )}
        >
          All BUY+
        </button>
        <button
          type="button"
          onClick={() => setGrade("STRONG_ONLY")}
          className={cn(
            "px-2 py-1 text-xs font-mono uppercase tracking-wider rounded border transition-colors",
            grade === "STRONG_ONLY"
              ? "border-bullish text-bullish bg-bullish/10"
              : "border-border text-muted-foreground hover:text-foreground",
          )}
        >
          STRONG BUY only
        </button>
        {!isLoading ? (
          <span className="ml-auto font-mono text-xs text-muted-foreground">
            {rows.length}
            {rawRows.length !== rows.length ? (
              <span className="text-muted-foreground/60"> / {rawRows.length}</span>
            ) : null}{" "}
            {rows.length === 1 ? "signal" : "signals"}
          </span>
        ) : null}
      </div>

      {subScoreKeys.length > 0 ? (
        <div className="mt-3 rounded border border-border bg-muted/10 px-3 py-2">
          <div className="flex items-center justify-between mb-2">
            <span className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
              Sub-score minimum filters
              {activeSubFilterCount > 0 ? (
                <span className="ml-2 text-bullish">
                  · {activeSubFilterCount} active
                </span>
              ) : null}
            </span>
            {activeSubFilterCount > 0 ? (
              <button
                type="button"
                onClick={() => setSubMinima({})}
                className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground hover:text-foreground"
              >
                clear all
              </button>
            ) : null}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-x-3 gap-y-2">
            {subScoreKeys.map((key) => (
              <SubScoreMinInput
                key={key}
                label={key}
                value={subMinima[key] ?? ""}
                onChange={(v) =>
                  setSubMinima((prev) => ({ ...prev, [key]: v }))
                }
              />
            ))}
          </div>
          <p className="mt-2 font-mono text-[10px] text-muted-foreground/70">
            Each filter requires the ticker&apos;s sub-score to be ≥ the number.
            Tickers missing the sub-score are filtered out.
          </p>
        </div>
      ) : null}

      <Card className="mt-3">
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-4 space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <EmptyState grade={grade} />
          ) : (
            <BuySignalTable rows={rows} />
          )}
        </CardContent>
      </Card>
    </>
  );
}

function BuySignalTable({ rows }: { rows: BuySignal[] }) {
  // Sub-score keys present anywhere in the rows. Used to render a
  // consistent set of columns even when some rows are missing certain
  // sub-scores (those cells show "—").
  const subScoreKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const r of rows) {
      if (r.sub_scores) {
        for (const k of Object.keys(r.sub_scores)) keys.add(k);
      }
    }
    return Array.from(keys).sort();
  }, [rows]);

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-24">Ticker</TableHead>
          <TableHead>Name · sector</TableHead>
          <TableHead className="text-right w-20">Score</TableHead>
          <TableHead className="w-28">Action</TableHead>
          <TableHead className="w-40">Best strategy</TableHead>
          {subScoreKeys.map((k) => (
            <TableHead
              key={k}
              className="text-right w-20 font-mono text-[10px] tracking-wider uppercase"
              title={k}
            >
              {k.slice(0, 6)}
            </TableHead>
          ))}
          <TableHead className="text-right w-32">Consensus</TableHead>
          <TableHead className="w-28">Last scan</TableHead>
          <TableHead className="w-36">Earnings</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => {
          const earn = earningsHint(r);
          return (
            <TableRow key={r.ticker} className="group">
              <TableCell>
                <Link
                  href={`/stocks/${encodeURIComponent(r.ticker)}`}
                  className="font-mono font-semibold text-foreground hover:text-primary hover:underline inline-flex items-center gap-1"
                >
                  {r.ticker}
                  <ArrowUpRight className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                </Link>
              </TableCell>
              <TableCell>
                <div className="flex flex-col gap-0.5">
                  <span className="text-foreground text-sm truncate max-w-[24rem]">
                    {r.name || r.ticker}
                  </span>
                  <span className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                    {r.sector}
                    {r.industry && r.industry !== "Unknown"
                      ? ` · ${r.industry}`
                      : ""}
                    {r.market_cap
                      ? ` · ${fmtUSD(r.market_cap, true)}`
                      : ""}
                  </span>
                </div>
              </TableCell>
              <TableCell className="text-right">
                <span
                  className={cn(
                    "font-mono font-semibold tabular-nums",
                    scoreToneClass(r.composite_score),
                  )}
                >
                  {r.composite_score.toFixed(1)}
                </span>
              </TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className={cn(
                    "font-mono text-[10px] tracking-wider",
                    actionBadgeClass(r.action),
                  )}
                >
                  {r.action}
                </Badge>
              </TableCell>
              <TableCell>
                <span className="font-mono text-xs text-foreground">
                  {r.strategy}
                </span>
              </TableCell>
              {subScoreKeys.map((k) => {
                const v = r.sub_scores?.[k];
                const shown =
                  typeof v === "number" && Number.isFinite(v) ? v : null;
                return (
                  <TableCell key={k} className="text-right">
                    <span
                      className={cn(
                        "font-mono tabular-nums text-xs",
                        shown === null
                          ? "text-muted-foreground/40"
                          : shown >= 70
                            ? "text-bullish"
                            : shown >= 50
                              ? "text-foreground"
                              : "text-bearish/70",
                      )}
                    >
                      {shown === null ? "—" : shown.toFixed(0)}
                    </span>
                  </TableCell>
                );
              })}
              <TableCell className="text-right">
                <ConsensusDots
                  count={r.consensus_count}
                  strategies={r.consensus_strategies ?? []}
                />
              </TableCell>
              <TableCell>
                <span
                  className="font-mono text-xs text-muted-foreground"
                  title={r.scan_timestamp}
                >
                  {formatScanAge(r.scan_timestamp)}
                </span>
              </TableCell>
              <TableCell>
                {earn ? (
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 font-mono text-xs",
                      earn.tone,
                    )}
                  >
                    <Calendar className="h-3 w-3" />
                    {earn.label}
                  </span>
                ) : (
                  <span className="text-muted-foreground/40 font-mono text-xs">
                    —
                  </span>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function ConsensusDots({
  count,
  strategies,
}: {
  count: number;
  strategies: string[];
}) {
  // Render N filled dots up to 5. Beyond 5 we collapse to numeric.
  const max = 5;
  const filled = Math.min(count, max);
  return (
    <span
      className="inline-flex items-center gap-1 font-mono text-xs text-foreground"
      title={`Flagged BUY+ by: ${strategies.join(", ")}`}
    >
      <span className="flex gap-0.5">
        {Array.from({ length: max }).map((_, i) => (
          <span
            key={i}
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              i < filled ? "bg-bullish" : "bg-muted-foreground/20",
            )}
            aria-hidden
          />
        ))}
      </span>
      <span className="tabular-nums">
        {count}
        <span className="text-muted-foreground">/strat</span>
      </span>
    </span>
  );
}

function SubScoreMinInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const active =
    value !== "" && Number.isFinite(parseFloat(value)) && parseFloat(value) > 0;
  return (
    <label className="flex items-center gap-2 font-mono text-xs">
      <span
        className={cn(
          "tracking-wider uppercase truncate w-20",
          active ? "text-bullish" : "text-muted-foreground",
        )}
        title={label}
      >
        {label}
      </span>
      <span className="text-muted-foreground/60">≥</span>
      <input
        type="number"
        inputMode="numeric"
        min={0}
        max={100}
        step={5}
        placeholder="0"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "w-14 rounded border bg-background px-1.5 py-0.5 tabular-nums",
          "focus:outline-none focus:ring-1 focus:ring-primary",
          active ? "border-bullish text-bullish" : "border-border",
        )}
        aria-label={`Minimum ${label} score`}
      />
    </label>
  );
}

function EmptyState({ grade }: { grade: GradeFilter }) {
  return (
    <div className="p-12 text-center space-y-3">
      <p className="font-mono text-xs tracking-wider uppercase text-muted-foreground">
        {grade === "STRONG_ONLY" ? "No STRONG BUY signals" : "No BUY+ signals"}{" "}
        in the latest scan per strategy
      </p>
      <p className="text-sm text-muted-foreground">
        The system isn&apos;t ringing the bell right now.
        {grade === "STRONG_ONLY"
          ? " Try the All BUY+ filter, or "
          : " Try "}
        <Link href="/scan" className="text-primary hover:underline">
          run a fresh scan
        </Link>
        .
      </p>
    </div>
  );
}
