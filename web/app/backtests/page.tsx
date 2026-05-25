"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

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
import { api, type FactorBacktestSummary } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtNumber, fmtPct, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

// ─── helpers ────────────────────────────────────────────────────────────────

type KindFilter = "all" | "sweep" | "ab";
type WfFilter = "all" | "passed" | "failed";

function alphaTone(a: number | null | undefined): string {
  if (a == null) return "text-foreground";
  if (a >= 2) return "text-bullish";
  if (a <= -2) return "text-bearish";
  return "text-foreground";
}

function shortWindow(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  if (!start || !end) return "—";
  const fmt = (s: string) => {
    const d = new Date(s);
    return Number.isNaN(d.getTime())
      ? s.slice(0, 7)
      : d.toLocaleDateString(undefined, { year: "2-digit", month: "short" });
  };
  return `${fmt(start)} → ${fmt(end)}`;
}

function paramSummary(row: FactorBacktestSummary): string {
  // Compact "d05·r63·regime_off" tag so the table fits more rows.
  const parts: string[] = [];
  if (row.top_decile != null) parts.push(`d${(row.top_decile * 100).toFixed(0).padStart(2, "0")}`);
  if (row.rebalance_days != null) parts.push(`r${row.rebalance_days}`);
  if (row.regime_filter_enabled === true) parts.push("regime");
  return parts.join("·") || "—";
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function BacktestsPage() {
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [wfFilter, setWfFilter] = useState<WfFilter>("all");

  const { data, isLoading, error } = useQuery({
    queryKey: qk.factorBacktests.list({
      kind: kindFilter === "all" ? undefined : kindFilter,
      limit: 200,
    }),
    queryFn: () =>
      api.factorBacktests.list({
        kind: kindFilter === "all" ? undefined : kindFilter,
        limit: 200,
      }),
  });

  const rows = useMemo(() => {
    const all = data ?? [];
    if (wfFilter === "all") return all;
    if (wfFilter === "passed") return all.filter((r) => r.wf_passed === true);
    return all.filter((r) => r.wf_passed === false);
  }, [data, wfFilter]);

  const stats = useMemo(() => {
    const all = data ?? [];
    let bestAlpha: number | null = null;
    let bestAlphaSlug: string | null = null;
    let passed = 0;
    let failed = 0;
    const strategies = new Set<string>();
    for (const r of all) {
      strategies.add(r.strategy);
      if (r.alpha_vs_spy_pct != null) {
        if (bestAlpha == null || r.alpha_vs_spy_pct > bestAlpha) {
          bestAlpha = r.alpha_vs_spy_pct;
          bestAlphaSlug = r.slug;
        }
      }
      if (r.wf_passed === true) passed += 1;
      if (r.wf_passed === false) failed += 1;
    }
    return {
      total: all.length,
      bestAlpha,
      bestAlphaSlug,
      passed,
      failed,
      strategies: strategies.size,
    };
  }, [data]);

  return (
    <>
      <PageHeader
        title="Factor backtests"
        description="On-disk sweep + A/B results from scripts.run_factor_backtest. Click a row for walk-forward folds, equity curve, and SPY overlay."
      />

      {error ? <ErrorState error={error} /> : null}

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="Total runs"
          value={isLoading ? "—" : String(stats.total)}
          sub={`${stats.strategies} distinct variants`}
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Best α vs SPY"
          tooltip="Highest alpha_vs_spy_pct across all on-disk results. Click the slug to drill in."
          value={
            isLoading ? "—" : stats.bestAlpha == null ? (
              "—"
            ) : (
              <span className={cn("font-mono", alphaTone(stats.bestAlpha))}>
                {fmtPct(stats.bestAlpha, 2, true)}
              </span>
            )
          }
          sub={
            stats.bestAlphaSlug ? (
              <Link
                href={`/backtests/${encodeURIComponent(stats.bestAlphaSlug)}`}
                className="font-mono text-[10px] hover:text-foreground transition-colors"
              >
                {stats.bestAlphaSlug}
              </Link>
            ) : "no signed alpha"
          }
          subTone={(stats.bestAlpha ?? 0) >= 2 ? "bullish" : "muted"}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Walk-forward"
          tooltip="walk_forward.passed flag per run: every fold's Sharpe > 0 (or whatever the script's gate is). Failed = at least one fold flunked."
          value={
            isLoading ? "—" : (
              <span className="font-mono text-base">
                <span className="text-bullish">{stats.passed}</span>
                <span className="text-muted-foreground/60"> / </span>
                <span className="text-bearish">{stats.failed}</span>
              </span>
            )
          }
          sub="passed / failed"
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Sweep | A/B"
          tooltip="Runs by source directory. sweep = data/factors/sweep/, ab = reports/ab_*.json"
          value={
            isLoading ? "—" : (
              <span className="font-mono text-base">
                <span>{(data ?? []).filter((r) => r.kind === "sweep").length}</span>
                <span className="text-muted-foreground/60"> | </span>
                <span>{(data ?? []).filter((r) => r.kind === "ab").length}</span>
              </span>
            )
          }
          sub="parameter / experiment"
          subTone="muted"
          isLoading={isLoading}
        />
      </div>

      {/* Filter chips */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
          Source
        </span>
        <FilterChip
          label="ALL"
          active={kindFilter === "all"}
          onClick={() => setKindFilter("all")}
        />
        <FilterChip
          label="sweep"
          active={kindFilter === "sweep"}
          onClick={() => setKindFilter("sweep")}
        />
        <FilterChip
          label="A/B"
          active={kindFilter === "ab"}
          onClick={() => setKindFilter("ab")}
        />

        <span className="ml-3 font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
          Walk-forward
        </span>
        <FilterChip
          label="ALL"
          active={wfFilter === "all"}
          onClick={() => setWfFilter("all")}
        />
        <FilterChip
          label="passed"
          tone="bullish"
          active={wfFilter === "passed"}
          onClick={() => setWfFilter("passed")}
        />
        <FilterChip
          label="failed"
          tone="bearish"
          active={wfFilter === "failed"}
          onClick={() => setWfFilter("failed")}
        />

        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {rows.length}
          {rows.length !== (data?.length ?? 0) ? (
            <span className="text-muted-foreground/60">
              {" "}/ {data?.length ?? 0}
            </span>
          ) : null}{" "}
          {rows.length === 1 ? "run" : "runs"}
        </span>
      </div>

      {/* Runs table */}
      {isLoading ? (
        <div className="mt-4 space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-7 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState totalCount={data?.length ?? 0} />
      ) : (
        <div className="mt-4 border border-border rounded-md bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Slug</TableHead>
                <TableHead>Strategy</TableHead>
                <TableHead>Window</TableHead>
                <TableHead>Params</TableHead>
                <TableHead className="text-right">Sharpe</TableHead>
                <TableHead className="text-right">α vs SPY</TableHead>
                <TableHead className="text-right">Max DD</TableHead>
                <TableHead className="text-right">WF</TableHead>
                <TableHead className="text-right">Trades</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.slug} mono className="group">
                  <TableCell>
                    <Link
                      href={`/backtests/${encodeURIComponent(r.slug)}`}
                      className="flex items-center gap-1 font-mono text-foreground hover:text-primary"
                    >
                      {r.slug}
                      <ChevronRight className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                    </Link>
                  </TableCell>
                  <TableCell className="text-muted-foreground text-[11px]">
                    {r.strategy}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-[11px]">
                    {shortWindow(r.window_start, r.window_end)}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-[11px]">
                    {paramSummary(r)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-mono tabular-nums",
                      pnlColorClass(r.ann_sharpe),
                    )}
                  >
                    {fmtNumber(r.ann_sharpe, 2)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-mono tabular-nums",
                      alphaTone(r.alpha_vs_spy_pct),
                    )}
                  >
                    {fmtPct(r.alpha_vs_spy_pct, 2, true)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-mono tabular-nums",
                      pnlColorClass(-(r.max_drawdown_pct ?? 0)),
                    )}
                  >
                    {fmtPct(r.max_drawdown_pct, 1)}
                  </TableCell>
                  <TableCell className="text-right">
                    <WfChip passed={r.wf_passed} />
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums text-muted-foreground text-[11px]">
                    {r.n_trades ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}

// ─── small components ──────────────────────────────────────────────────────

function FilterChip({
  label, active, onClick, tone,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  tone?: "bullish" | "bearish";
}) {
  const activeClass =
    tone === "bullish" ? "border-bullish text-bullish bg-bullish/10"
    : tone === "bearish" ? "border-bearish text-bearish bg-bearish/10"
    : "border-border text-foreground bg-muted/40";
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider rounded border transition-colors",
        active
          ? activeClass
          : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/30",
      )}
    >
      {label}
    </button>
  );
}

function WfChip({ passed }: { passed: boolean | null | undefined }) {
  if (passed == null) {
    return (
      <Badge variant="outline" className="text-[9px] font-mono uppercase tracking-wider opacity-50">
        —
      </Badge>
    );
  }
  if (passed) {
    return (
      <Badge
        variant="bullish"
        className="text-[9px] font-mono uppercase tracking-wider gap-1"
      >
        <CheckCircle2 className="h-2.5 w-2.5" />
        pass
      </Badge>
    );
  }
  return (
    <Badge
      variant="bearish"
      className="text-[9px] font-mono uppercase tracking-wider gap-1"
    >
      <XCircle className="h-2.5 w-2.5" />
      fail
    </Badge>
  );
}

function EmptyState({ totalCount }: { totalCount: number }) {
  return (
    <div className="mt-4 border border-border rounded-md bg-card p-12 text-center">
      <AlertTriangle className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
        {totalCount === 0 ? "No backtest artifacts" : "Nothing matches the filter"}
      </p>
      <p className="mt-2 text-sm text-muted-foreground">
        Sweep results live in{" "}
        <code className="bg-muted px-1 py-0.5 rounded text-xs">data/factors/sweep/</code>{" "}
        and A/B results in{" "}
        <code className="bg-muted px-1 py-0.5 rounded text-xs">reports/ab_*.json</code>.
        Run{" "}
        <code className="bg-muted px-1 py-0.5 rounded text-xs">
          uv run python -m scripts.run_factor_backtest
        </code>{" "}
        to generate one.
      </p>
    </div>
  );
}
