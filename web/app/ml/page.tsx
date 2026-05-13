"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { ErrorState } from "@/components/error-state";
import { FoldBarsChart } from "@/components/ml/fold-bars-chart";
import { RollingICChart, type ModelFoldSeries } from "@/components/ml/rolling-ic-chart";
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
import {
  api,
  type ModelDriftSnapshot,
  type ModelVersionRow,
} from "@/lib/api/client";
import { chartColor } from "@/lib/chart-tokens";
import { fmtNumber, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

// ─── Tone helpers (bound to bullish/bearish/neutral tokens) ─────────────
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

// Days-since helper — used to flag stale-trained models.
function daysSince(iso: string): number {
  const ms = Date.now() - new Date(iso).getTime();
  return Math.max(0, Math.floor(ms / 86_400_000));
}

// Compact YYYY-Qx for the train-window column.
function compactWindow(startIso: string, endIso: string): string {
  const fmt = (iso: string) => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
    const y = String(d.getFullYear()).slice(2);
    const q = Math.floor(d.getMonth() / 3) + 1;
    return `${y}Q${q}`;
  };
  return `${fmt(startIso)}->${fmt(endIso)}`;
}

// Model status: active / stale (>30d since train) / deprecated (not in latest).
type ModelStatus = "active" | "stale" | "deprecated";
function statusFor(
  row: ModelVersionRow,
  latestKeys: Set<string>,
  staleAfterDays: number,
): ModelStatus {
  const key = `${row.model_name}_${row.version}`;
  if (!latestKeys.has(key)) return "deprecated";
  if (daysSince(row.trained_at) > staleAfterDays) return "stale";
  return "active";
}

const STALE_AFTER_DAYS = 30;

export default function MLModelsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["ml", "models"],
    queryFn: () => api.ml.models({ limit: 50, window_days: 30 }),
    refetchInterval: 60_000,
  });

  const latest = useMemo(() => data?.latest ?? [], [data]);
  const models = useMemo(() => data?.models ?? [], [data]);
  const drift = useMemo(() => data?.drift ?? [], [data]);

  // Lookup helpers used in render.
  const latestKeys = useMemo(
    () => new Set(latest.map((m) => `${m.model_name}_${m.version}`)),
    [latest],
  );
  const driftByKey = useMemo(() => {
    const map = new Map<string, ModelDriftSnapshot>();
    for (const d of drift) {
      map.set(`${d.model_name}_${d.version}`, d);
    }
    return map;
  }, [drift]);

  // Scoreboard aggregates over the active (latest) set.
  const icValues = latest
    .map((m) => m.summary.mean_ic_pearson)
    .filter((v): v is number => v != null && !Number.isNaN(v));
  const bestIc = icValues.length > 0 ? Math.max(...icValues) : null;
  const worstIc = icValues.length > 0 ? Math.min(...icValues) : null;
  const ensembleIc =
    icValues.length > 0
      ? icValues.reduce((a, b) => a + b, 0) / icValues.length
      : null;
  const lastTrainIso = latest.reduce<string | null>((acc, m) => {
    if (!acc) return m.trained_at;
    return new Date(m.trained_at) > new Date(acc) ? m.trained_at : acc;
  }, null);
  const lastTrainDays = lastTrainIso ? daysSince(lastTrainIso) : null;

  // Health verdict: HEALTHY when ensemble IC > 0 + no drift; DRIFTING when
  // any active model trips its drift gate; DEGRADED when ensemble IC <= 0;
  // UNTRAINED when there's nothing in latest.
  const anyDrifting = drift.some(
    (d) =>
      d.is_drifting &&
      latestKeys.has(`${d.model_name}_${d.version}`),
  );
  const verdict: "HEALTHY" | "DRIFTING" | "DEGRADED" | "UNTRAINED" =
    latest.length === 0
      ? "UNTRAINED"
      : anyDrifting
        ? "DRIFTING"
        : ensembleIc != null && ensembleIc <= 0
          ? "DEGRADED"
          : "HEALTHY";

  // Rolling-IC chart series — one entry per active model, folds carried
  // through unchanged so the chart can union timestamps + overlay them.
  const rollingSeries: ModelFoldSeries[] = useMemo(
    () =>
      latest
        .filter((m) => (m.folds ?? []).length > 0)
        .map((m) => ({
          name: m.model_name.toUpperCase(),
          folds: (m.folds ?? [])
            .map((f) => ({
              test_start: f.test_start,
              ic_pearson: f.ic_pearson,
            }))
            .sort((a, b) => a.test_start.localeCompare(b.test_start)),
        })),
    [latest],
  );

  return (
    <>
      <PageHeader
        title="ML model registry"
        description="Registered model versions, walk-forward IC, and rolling-IC drift gates. The ensemble is rendered as the equal-weight average across the active set."
        actions={
          data ? (
            <Badge variant="outline" className="font-mono">
              {models.length} runs
            </Badge>
          ) : null
        }
      />

      {error ? <ErrorState error={error} /> : null}

      {isLoading || !data ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : latest.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-4">
          {/* ── Scoreboard strip ───────────────────────────────────────── */}
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
            <ScoreboardTile
              label="Active Models"
              value={String(latest.length)}
              sub={`${models.length} total registered`}
              subTone="muted"
            />
            <ScoreboardTile
              label="Ensemble IC"
              value={
                <span className={cn(toneClass(ensembleIc))}>
                  {ensembleIc == null ? "—" : fmtNumber(ensembleIc, 4)}
                </span>
              }
              sub={
                ensembleIc == null
                  ? "no folds"
                  : ensembleIc > 0
                    ? "positive edge"
                    : "no edge"
              }
              subTone={toneFor(ensembleIc)}
            />
            <ScoreboardTile
              label="Best Model IC"
              value={
                <span className={cn(toneClass(bestIc))}>
                  {bestIc == null ? "—" : fmtNumber(bestIc, 4)}
                </span>
              }
              sub={
                bestIc == null
                  ? "n/a"
                  : latest.find(
                      (m) => m.summary.mean_ic_pearson === bestIc,
                    )?.model_name ?? ""
              }
              subTone="muted"
            />
            <ScoreboardTile
              label="Worst Model IC"
              value={
                <span className={cn(toneClass(worstIc))}>
                  {worstIc == null ? "—" : fmtNumber(worstIc, 4)}
                </span>
              }
              sub={
                worstIc == null
                  ? "n/a"
                  : latest.find(
                      (m) => m.summary.mean_ic_pearson === worstIc,
                    )?.model_name ?? ""
              }
              subTone={toneFor(worstIc)}
            />
            <ScoreboardTile
              label="Last Trained"
              value={
                lastTrainDays == null
                  ? "—"
                  : lastTrainDays === 0
                    ? "today"
                    : `${lastTrainDays}d`
              }
              sub={
                lastTrainIso
                  ? new Date(lastTrainIso).toLocaleDateString(undefined, {
                      year: "2-digit",
                      month: "short",
                      day: "2-digit",
                    })
                  : "never"
              }
              subTone={
                lastTrainDays != null && lastTrainDays > STALE_AFTER_DAYS
                  ? "bearish"
                  : "muted"
              }
            />
          </div>

          {/* ── Health verdict strip ───────────────────────────────────── */}
          <div className="border-border text-muted-foreground flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 font-mono text-[11px] tracking-wider uppercase">
            <span>MODEL HEALTH</span>
            <span
              className={cn(
                verdict === "HEALTHY"
                  ? "text-bullish"
                  : verdict === "DEGRADED"
                    ? "text-bearish"
                    : verdict === "DRIFTING"
                      ? "text-bearish"
                      : "text-muted-foreground",
              )}
            >
              [ {verdict} ]
            </span>
            <span className="ml-auto">
              ENS {ensembleIc == null ? "—" : fmtNumber(ensembleIc, 3)} |
              {" "}DRIFT {drift.filter((d) => d.is_drifting).length}/
              {drift.length}
            </span>
          </div>

          {/* ── Ensemble breakdown badge strip ─────────────────────────── */}
          {latest.length > 0 ? (
            <EnsembleBreakdown latest={latest} />
          ) : null}

          {/* ── Rolling-IC headliner chart ─────────────────────────────── */}
          {rollingSeries.length > 0 ? (
            <div className="border-border rounded-md border bg-card">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  Rolling Pearson IC by walk-forward fold
                </div>
                <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  {rollingSeries.length} series + ensemble
                </div>
              </div>
              <div className="p-3">
                <div className="h-72">
                  <RollingICChart series={rollingSeries} />
                </div>
              </div>
            </div>
          ) : null}

          {/* ── Model registry table ───────────────────────────────────── */}
          <div className="border-border rounded-md border bg-card">
            <div className="flex items-center justify-between border-b border-border px-3 py-2">
              <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                Active model registry
              </div>
              <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                {latest.length} active
              </div>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead className="text-right">v</TableHead>
                  <TableHead>Trained</TableHead>
                  <TableHead>Window</TableHead>
                  <TableHead className="text-right">Horizon</TableHead>
                  <TableHead className="text-right">Folds</TableHead>
                  <TableHead className="text-right">Mean IC</TableHead>
                  <TableHead className="text-right">Rank IC</TableHead>
                  <TableHead className="text-right">Hit</TableHead>
                  <TableHead className="text-right">Drift z</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {latest.map((m) => {
                  const d = driftByKey.get(`${m.model_name}_${m.version}`);
                  const status = statusFor(m, latestKeys, STALE_AFTER_DAYS);
                  return (
                    <TableRow key={`${m.model_name}_${m.version}`} mono>
                      <TableCell>
                        <span className="text-foreground">{m.model_name}</span>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-[11px] uppercase tracking-wider">
                        {modelType(m.model_name)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        v{m.version}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-[11px] tabular-nums">
                        {new Date(m.trained_at).toLocaleDateString(undefined, {
                          year: "2-digit",
                          month: "short",
                          day: "2-digit",
                        })}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-[11px] tabular-nums">
                        {compactWindow(m.train_window_start, m.train_window_end)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {m.horizon_days}d
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {Math.round(m.summary.n_folds)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right tabular-nums",
                          pnlColorClass(m.summary.mean_ic_pearson),
                        )}
                      >
                        {fmtNumber(m.summary.mean_ic_pearson, 4)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right tabular-nums",
                          pnlColorClass(m.summary.mean_ic_spearman),
                        )}
                      >
                        {fmtNumber(m.summary.mean_ic_spearman, 4)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-foreground">
                        {fmtNumber(m.summary.mean_hit_rate * 100, 1)}%
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right tabular-nums",
                          d == null
                            ? "text-muted-foreground/40"
                            : d.is_drifting
                              ? "text-bearish"
                              : d.z_score < -0.75
                                ? "text-foreground"
                                : "text-bullish",
                        )}
                      >
                        {d == null ? "—" : fmtNumber(d.z_score, 2)}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            status === "active"
                              ? "bullish"
                              : status === "deprecated"
                                ? "bearish"
                                : "neutral"
                          }
                        >
                          {status.toUpperCase()}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>

          {/* ── Per-model fold detail ──────────────────────────────────── */}
          {latest.length > 0 ? (
            <div className="border-border rounded-md border bg-card">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  Per-fold IC by model
                </div>
                <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  walk-forward
                </div>
              </div>
              <div className="grid gap-px bg-border md:grid-cols-2 lg:grid-cols-3">
                {latest.map((m) => (
                  <div
                    key={`${m.model_name}_${m.version}_fold`}
                    className="bg-card px-3 py-3"
                  >
                    <div className="mb-1 flex items-baseline justify-between font-mono text-[10px] tracking-wider uppercase">
                      <span className="text-foreground">
                        {m.model_name} v{m.version}
                      </span>
                      <span
                        className={cn(
                          "tabular-nums",
                          pnlColorClass(m.summary.mean_ic_pearson),
                        )}
                      >
                        {fmtNumber(m.summary.mean_ic_pearson, 4)}
                      </span>
                    </div>
                    <div className="h-36">
                      <FoldBarsChart folds={m.folds ?? []} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* ── Full registry (all runs incl. deprecated) ──────────────── */}
          {models.length > latest.length ? (
            <div className="border-border rounded-md border bg-card">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  All registered runs
                </div>
                <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
                  {models.length} runs · drift gate fires at &lt;= -1.5 sigma
                </div>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Trained</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead className="text-right">v</TableHead>
                    <TableHead className="text-right">Horizon</TableHead>
                    <TableHead className="text-right">Mean IC</TableHead>
                    <TableHead className="text-right">Folds</TableHead>
                    <TableHead>Window</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {models.map((m) => {
                    const status = statusFor(m, latestKeys, STALE_AFTER_DAYS);
                    return (
                      <TableRow key={m.id} mono>
                        <TableCell className="text-muted-foreground text-[11px] tabular-nums">
                          {new Date(m.trained_at).toLocaleString(undefined, {
                            year: "2-digit",
                            month: "short",
                            day: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </TableCell>
                        <TableCell>
                          <span className="text-foreground">{m.model_name}</span>
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">
                          v{m.version}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">
                          {m.horizon_days}d
                        </TableCell>
                        <TableCell
                          className={cn(
                            "text-right tabular-nums",
                            pnlColorClass(m.summary.mean_ic_pearson),
                          )}
                        >
                          {fmtNumber(m.summary.mean_ic_pearson, 4)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">
                          {Math.round(m.summary.n_folds)}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-[11px] tabular-nums">
                          {compactWindow(
                            m.train_window_start,
                            m.train_window_end,
                          )}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={
                              status === "active"
                                ? "bullish"
                                : status === "deprecated"
                                  ? "bearish"
                                  : "neutral"
                            }
                          >
                            {status.toUpperCase()}
                          </Badge>
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

// ── Empty state ──────────────────────────────────────────────────────────
function EmptyState() {
  return (
    <div className="border-border rounded-md border bg-card p-8 text-center">
      <p className="font-mono text-xs text-muted-foreground">
        No trained models yet. Run{" "}
        <code className="bg-muted rounded px-1 py-0.5">
          python -m src.ml.cli train ...
        </code>{" "}
        to seed.
      </p>
    </div>
  );
}

// ── Ensemble equal-weight breakdown ──────────────────────────────────────
// The current /api/ml/models payload does not surface explicit per-model
// weights. The runtime ensemble averages active models, so we render that
// equal-weight assumption inline as a swatch strip — when the API grows
// real weights this becomes the natural mount point.
function EnsembleBreakdown({ latest }: { latest: ModelVersionRow[] }) {
  const w = 1 / latest.length;
  return (
    <div className="border-border flex flex-wrap items-center gap-2 rounded-md border bg-card px-3 py-2">
      <span className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
        Ensemble · equal-weight
      </span>
      <div className="flex flex-1 flex-wrap items-center gap-1.5">
        {latest.map((m, i) => (
          <span
            key={`${m.model_name}_${m.version}`}
            className="flex items-center gap-1.5 font-mono text-[10px] tracking-wider uppercase text-foreground"
          >
            <span
              aria-hidden
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: chartColor(i) }}
            />
            <span>
              {m.model_name} {w.toFixed(2)}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

// Map registered model names to human-friendly type labels for the table.
function modelType(name: string): string {
  const n = name.toLowerCase();
  if (n.includes("lgbm") || n.includes("lightgbm") || n.includes("gbm"))
    return "LightGBM";
  if (n.includes("ridge")) return "Ridge";
  if (n.includes("ffn") || n.includes("mlp") || n.includes("nn")) return "FFN";
  return name;
}
