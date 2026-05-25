"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { use, useMemo, useState } from "react";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type IcCellMetrics,
  type IcFactorRow,
  type IcReportDetail,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtNumber, fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

type Params = { params: Promise<{ slug: string }> };

export default function IcReportDetailPage({ params }: Params) {
  const { slug } = use(params);
  const { data, isLoading, error } = useQuery({
    queryKey: qk.icReports.detail(slug),
    queryFn: () => api.icReports.get(slug),
  });

  return (
    <>
      <PageHeader
        title={data ? data.slug.replace(/^analyzer_ic_/, "") : isLoading ? "Loading…" : "IC report"}
        description={
          data
            ? `${data.strategy} · ${data.universe} · ${data.window_start} → ${data.window_end} · ${data.panel_rows.toLocaleString()} panel rows`
            : "Factor IC report detail"
        }
        actions={
          <Link
            href="/diagnose"
            className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          >
            <ChevronLeft className="h-3 w-3" /> Back to reports
          </Link>
        }
      />

      {error ? <ErrorState error={error} /> : null}
      {isLoading || !data ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
          <Skeleton className="h-72 w-full" />
        </div>
      ) : (
        <DetailBody data={data} />
      )}
    </>
  );
}

function DetailBody({ data }: { data: IcReportDetail }) {
  // openapi-typescript marks default_factory lists/dicts as nullable;
  // coalesce up-front so the rest of the component treats them as
  // concrete shapes.
  const regimes: string[] = data.regimes ?? [];
  const horizons: string[] = data.horizons ?? [];
  const perFactor: IcFactorRow[] = data.per_factor ?? [];
  const perRegime = data.per_regime ?? {};
  const isRegime = data.regime_split != null && regimes.length > 0;
  const [regime, setRegime] = useState<string>(
    isRegime ? regimes[0] : "",
  );

  const factorRows: IcFactorRow[] = isRegime
    ? perRegime[regime] ?? []
    : perFactor;

  return (
    <>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="Window"
          value={
            <span className="font-mono text-sm">
              {data.window_start} → {data.window_end}
            </span>
          }
          sub={`${data.panel_rows.toLocaleString()} panel rows`}
          subTone="muted"
        />
        <ScoreboardTile
          label="Factors × horizons"
          value={
            <span className="font-mono text-base">
              {data.n_factors} × {horizons.length}
            </span>
          }
          sub={horizons.join(" · ") || "—"}
          subTone="muted"
        />
        <ScoreboardTile
          label="Bonferroni K"
          tooltip="Number of independent tests for multiple-comparison correction. Adjusted p-value = raw p × K."
          value={
            <span className="font-mono text-base tabular-nums">
              {data.bonferroni_k}
            </span>
          }
          sub={`Q${data.quantiles}`}
          subTone="muted"
        />
        <ScoreboardTile
          label="Regime split"
          value={
            data.regime_split ? (
              <span className="font-mono text-base">{data.regime_split}</span>
            ) : (
              <span className="text-muted-foreground text-base">none</span>
            )
          }
          sub={
            isRegime
              ? `${regimes.length} buckets`
              : "unconditional report"
          }
          subTone="muted"
        />
      </div>

      {isRegime ? (
        <div className="mt-4 flex items-center gap-1.5 flex-wrap">
          <span className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
            Regime
          </span>
          {regimes.map((r) => (
            <button
              key={r}
              type="button"
              onClick={() => setRegime(r)}
              className={cn(
                "px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider rounded border transition-colors",
                regime === r
                  ? "border-primary text-primary bg-primary/10"
                  : "border-border text-muted-foreground hover:text-foreground hover:bg-muted/30",
              )}
            >
              {r}
            </button>
          ))}
        </div>
      ) : null}

      <IcMatrixCard
        horizons={horizons}
        rows={factorRows}
        bonferroniK={data.bonferroni_k}
        regimeLabel={isRegime ? regime : null}
      />

      <SignificanceLegend bonferroniK={data.bonferroni_k} />
    </>
  );
}

// ─── Matrix ────────────────────────────────────────────────────────────────

function IcMatrixCard({
  horizons, rows, bonferroniK, regimeLabel,
}: {
  horizons: string[];
  rows: IcFactorRow[];
  bonferroniK: number;
  regimeLabel: string | null;
}) {
  return (
    <div className="mt-4 border border-border rounded-md bg-card">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
          IC mean by factor × horizon
          {regimeLabel ? (
            <span className="ml-2 text-primary">[{regimeLabel}]</span>
          ) : null}
        </div>
        <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
          {rows.length} factors · {horizons.length} horizons
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="p-8 text-center text-xs text-muted-foreground">
          No factor data in this slice.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-xs">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left px-3 py-2 text-[10px] tracking-wider uppercase text-muted-foreground">
                  Factor
                </th>
                <th className="text-right px-2 py-2 text-[10px] tracking-wider uppercase text-muted-foreground">
                  n obs
                </th>
                {horizons.map((h) => (
                  <th
                    key={h}
                    className="text-right px-2 py-2 text-[10px] tracking-wider uppercase text-muted-foreground"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.factor} className="border-b border-border/40">
                  <td className="px-3 py-1 font-medium text-foreground">
                    {row.factor}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">
                    {row.n_observations.toLocaleString()}
                  </td>
                  {horizons.map((h) => (
                    <td key={h} className="px-1 py-1">
                      <IcCellView
                        cell={(row.by_horizon ?? {})[h] ?? null}
                        bonferroniK={bonferroniK}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function IcCellView({
  cell, bonferroniK,
}: {
  cell: IcCellMetrics | null;
  bonferroniK: number;
}) {
  if (cell == null) {
    return (
      <div className="text-center text-muted-foreground/40">—</div>
    );
  }
  const adjustedP = Math.min(1, cell.p_value * Math.max(1, bonferroniK));
  const tone =
    adjustedP < 0.05
      ? cell.ic_mean > 0 ? "bg-bullish/15 text-bullish border-bullish/30"
      : "bg-bearish/15 text-bearish border-bearish/30"
      : "border-transparent text-foreground";
  const stars =
    adjustedP < 0.001 ? "***"
    : adjustedP < 0.01 ? "**"
    : adjustedP < 0.05 ? "*"
    : "";
  const title = [
    `IC mean: ${fmtNumber(cell.ic_mean, 4)}`,
    `IC std:  ${fmtNumber(cell.ic_std, 4)}`,
    `IC IR:   ${fmtNumber(cell.ic_ir, 3)}`,
    `t-stat:  ${fmtNumber(cell.t_stat, 2)}`,
    `p (raw): ${cell.p_value < 0.0001 ? "<0.0001" : fmtNumber(cell.p_value, 4)}`,
    `p × K:   ${adjustedP < 0.0001 ? "<0.0001" : fmtNumber(adjustedP, 4)}  (K=${bonferroniK})`,
    `n_periods: ${cell.n_periods}`,
    `top−bottom: ${fmtPct(cell.top_minus_bottom_pct, 2, true)}`,
  ].join("\n");
  return (
    <div
      className={cn(
        "rounded px-2 py-1 text-right border tabular-nums cursor-help",
        tone,
      )}
      title={title}
    >
      <div className="text-xs">
        {fmtNumber(cell.ic_mean, 3)}
        {stars ? (
          <span className="ml-0.5 text-[9px] font-semibold">{stars}</span>
        ) : null}
      </div>
      <div className="text-[9px] opacity-70">
        t={fmtNumber(cell.t_stat, 2)}
      </div>
    </div>
  );
}

function SignificanceLegend({ bonferroniK }: { bonferroniK: number }) {
  return (
    <div className="mt-3 text-[10px] font-mono text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1">
      <span className="uppercase tracking-wider">Significance (Bonferroni adj, K={bonferroniK}):</span>
      <span>
        <span className="text-bullish font-semibold">*</span> p &lt; 0.05
      </span>
      <span>
        <span className="text-bullish font-semibold">**</span> p &lt; 0.01
      </span>
      <span>
        <span className="text-bullish font-semibold">***</span> p &lt; 0.001
      </span>
      <span className="opacity-70">
        · positive IC = green tint, negative = red tint, |ic| ≥ 0.03 typical edge gate
      </span>
    </div>
  );
}
