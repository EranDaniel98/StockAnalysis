"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Microscope } from "lucide-react";
import { useMemo } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { IcBarChart } from "@/components/diagnose/ic-bar-chart";
import { SpreadBarChart } from "@/components/diagnose/spread-bar-chart";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
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
import {
  type DiagnosticRequest,
  type DiagnosticResponse,
  api,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtNumber, fmtPct, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

const FACTORS = [
  "composite",
  "technical",
  "fundamental",
  "pattern",
  "statistical",
  "trend",
  "alpha158",
];

// Engine gate: a factor "passes" if |IC| >= IC_GATE on at least one horizon.
const IC_GATE = 0.03;

type FormShape = {
  strategy: string;
  factor: string;
  years: string;
  quantiles: string;
};

// ─── Helpers ────────────────────────────────────────────────────────────────

/** Sort horizon keys "1d","5d","21d" numerically by trailing digits. */
function sortPeriods(periods: string[]): string[] {
  return [...periods].sort((a, b) => {
    const na = parseInt(a.replace(/\D/g, ""), 10);
    const nb = parseInt(b.replace(/\D/g, ""), 10);
    if (Number.isNaN(na) && Number.isNaN(nb)) return a.localeCompare(b);
    if (Number.isNaN(na)) return 1;
    if (Number.isNaN(nb)) return -1;
    return na - nb;
  });
}

type DiagRow = {
  period: string;
  ic: number;
  std: number;
  ir: number;
  spread: number;
};

function buildRows(d: DiagnosticResponse): DiagRow[] {
  const periods = sortPeriods(Object.keys(d.ic_mean));
  return periods.map((p) => ({
    period: p,
    ic: d.ic_mean[p] ?? 0,
    std: d.ic_std[p] ?? 0,
    ir: d.ic_ir[p] ?? 0,
    spread: d.top_minus_bottom_pct[p] ?? 0,
  }));
}

/** Pick the horizon with largest |IC| as the "headline" row. */
function bestRow(rows: DiagRow[]): DiagRow | null {
  if (rows.length === 0) return null;
  let best = rows[0];
  for (const r of rows) {
    if (Math.abs(r.ic) > Math.abs(best.ic)) best = r;
  }
  return best;
}

function irBand(ir: number): "STRONG" | "DECENT" | "WEAK" | "NONE" {
  const a = Math.abs(ir);
  if (a > 0.5) return "STRONG";
  if (a > 0.3) return "DECENT";
  if (a > 0.1) return "WEAK";
  return "NONE";
}

function bandSubTone(
  band: "STRONG" | "DECENT" | "WEAK" | "NONE",
  signed: number,
): "bullish" | "bearish" | "neutral" | "muted" {
  if (band === "NONE") return "muted";
  if (signed > 0) return "bullish";
  if (signed < 0) return "bearish";
  return "neutral";
}

function icTone(ic: number): string {
  if (Math.abs(ic) < IC_GATE) return "text-muted-foreground";
  if (ic > 0) return "text-bullish";
  if (ic < 0) return "text-bearish";
  return "text-foreground";
}

function fmtCreated(s: string | null | undefined): string {
  if (!s) return "—";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    year: "2-digit",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function DiagnosePage() {
  const qc = useQueryClient();

  const { register, handleSubmit, watch, setValue } = useForm<FormShape>({
    defaultValues: {
      strategy: "swing_trading",
      factor: "composite",
      years: "2",
      quantiles: "5",
    },
  });

  const diagMutation = useMutation({
    mutationFn: (body: DiagnosticRequest) => api.diagnostics.trigger(body),
    onSuccess: () => {
      toast.success("Diagnostic complete");
      qc.invalidateQueries({ queryKey: qk.diagnostics.all });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Diagnostic failed");
    },
  });

  const historyQuery = useQuery({
    queryKey: qk.diagnostics.list({ limit: 10 }),
    queryFn: () => api.diagnostics.list({ limit: 10 }),
  });

  function onSubmit(values: FormShape) {
    const body: DiagnosticRequest = {
      strategy: values.strategy,
      universe: "themes",
      tickers: null,
      factor: values.factor as DiagnosticRequest["factor"],
      years: Number(values.years),
      quantiles: Number(values.quantiles),
      periods: [1, 5, 21],
      accept_lookahead: false,
      fresh: false,
    };
    diagMutation.mutate(body);
  }

  const factor = watch("factor");
  const result = diagMutation.data;

  return (
    <>
      <PageHeader
        title="Diagnose"
        description="Alphalens-style IC sweep — does the factor predict forward returns? Gate: |IC| >= 0.03 on some horizon."
        actions={
          result ? (
            <Badge variant="outline" className="font-mono">
              n={result.n_observations}
            </Badge>
          ) : null
        }
      />

      {/* ── Dense form-strip ─────────────────────────────────────────── */}
      <div className="border-border bg-card mb-4 rounded-md border p-3">
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr_120px_120px_auto] md:items-end"
        >
          <div className="space-y-1">
            <Label
              htmlFor="strategy"
              className="text-muted-foreground text-[10px] font-medium tracking-wider uppercase"
            >
              Strategy
            </Label>
            <Input
              id="strategy"
              className="h-8 font-mono text-xs"
              {...register("strategy")}
            />
          </div>

          <div className="space-y-1">
            <Label
              htmlFor="factor"
              className="text-muted-foreground text-[10px] font-medium tracking-wider uppercase"
            >
              Factor
            </Label>
            <Select
              value={factor}
              onValueChange={(v) => v && setValue("factor", v)}
            >
              <SelectTrigger id="factor" className="h-8 font-mono text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FACTORS.map((f) => (
                  <SelectItem key={f} value={f} className="font-mono text-xs">
                    {f}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label
              htmlFor="years"
              className="text-muted-foreground text-[10px] font-medium tracking-wider uppercase"
            >
              Years
            </Label>
            <Input
              id="years"
              type="number"
              min={0.5}
              max={10}
              step={0.5}
              className="h-8 font-mono text-xs"
              {...register("years")}
            />
          </div>

          <div className="space-y-1">
            <Label
              htmlFor="quantiles"
              className="text-muted-foreground text-[10px] font-medium tracking-wider uppercase"
            >
              Quantiles
            </Label>
            <Input
              id="quantiles"
              type="number"
              min={2}
              max={10}
              className="h-8 font-mono text-xs"
              {...register("quantiles")}
            />
          </div>

          <Button
            type="submit"
            size="sm"
            className="h-8 font-mono text-xs tracking-wider uppercase"
            disabled={diagMutation.isPending}
          >
            {diagMutation.isPending ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Microscope className="mr-1.5 h-3.5 w-3.5" />
            )}
            {diagMutation.isPending ? "Running" : "Run"}
          </Button>
        </form>
      </div>

      {diagMutation.error ? <ErrorState error={diagMutation.error} /> : null}

      {result ? (
        <DiagnosticDetail data={result} />
      ) : diagMutation.isPending ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <DiagnosticHistory
          rows={historyQuery.data ?? []}
          isLoading={historyQuery.isLoading}
          error={historyQuery.error}
        />
      )}
    </>
  );
}

// ─── Detail panel ────────────────────────────────────────────────────────────

function DiagnosticDetail({ data }: { data: DiagnosticResponse }) {
  const rows = useMemo(() => buildRows(data), [data]);
  const best = useMemo(() => bestRow(rows), [rows]);
  const passingCount = useMemo(
    () => rows.filter((r) => Math.abs(r.ic) >= IC_GATE).length,
    [rows],
  );
  const bestSpread = useMemo(() => {
    if (rows.length === 0) return 0;
    let s = rows[0].spread;
    for (const r of rows) {
      if (Math.abs(r.spread) > Math.abs(s)) s = r.spread;
    }
    return s;
  }, [rows]);

  const ir = best?.ir ?? 0;
  const band = irBand(ir);
  const verdict =
    rows.length === 0
      ? "INSUFFICIENT DATA"
      : passingCount === 0
        ? "NONE"
        : band;

  return (
    <div className="space-y-4">
      {/* ── Scoreboard ──────────────────────────────────────────────── */}
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
        <ScoreboardTile
          label="Best IC Mean"
          value={
            <span className={cn(icTone(best?.ic ?? 0))}>
              {best ? fmtNumber(best.ic, 4) : "—"}
            </span>
          }
          sub={best ? `@ ${best.period}` : "no data"}
          subTone="muted"
        />
        <ScoreboardTile
          label="IC Std"
          value={
            <span className="text-foreground">
              {best ? fmtNumber(best.std, 4) : "—"}
            </span>
          }
          sub={best ? `@ ${best.period}` : "no data"}
          subTone="muted"
        />
        <ScoreboardTile
          label="IC IR"
          value={
            <span
              className={cn(
                band === "NONE"
                  ? "text-muted-foreground"
                  : ir > 0
                    ? "text-bullish"
                    : ir < 0
                      ? "text-bearish"
                      : "text-foreground",
              )}
            >
              {best ? fmtNumber(ir, 3) : "—"}
            </span>
          }
          sub={`[ ${band} ]`}
          subTone={bandSubTone(band, ir)}
        />
        <ScoreboardTile
          label="Top - Bottom"
          value={
            <span className={cn(pnlColorClass(bestSpread))}>
              {rows.length > 0 ? fmtPct(bestSpread, 2, true) : "—"}
            </span>
          }
          sub="best horizon spread"
          subTone="muted"
        />
        <ScoreboardTile
          label="Observations"
          value={
            <span className="text-foreground">
              {data.n_observations.toLocaleString()}
            </span>
          }
          sub={`${passingCount}/${rows.length} pass gate`}
          subTone={
            passingCount === 0
              ? "muted"
              : passingCount === rows.length
                ? "bullish"
                : "neutral"
          }
        />
      </div>

      {/* ── Verdict strip ──────────────────────────────────────────── */}
      <div className="border-border bg-card text-muted-foreground flex items-center gap-2 rounded-md border px-3 py-1.5 font-mono text-[11px] tracking-wider uppercase">
        <span>IC HEALTH</span>
        <span
          className={cn(
            verdict === "STRONG"
              ? "text-bullish"
              : verdict === "DECENT"
                ? "text-foreground"
                : verdict === "WEAK"
                  ? "text-foreground"
                  : "text-muted-foreground",
          )}
        >
          [ {verdict} ]
        </span>
        <span className="text-muted-foreground/70 ml-2">
          {data.factor.toUpperCase()} | {data.universe_label.toUpperCase()} | Q
          {data.quantiles}
        </span>
        {data.verdict ? (
          <span className="text-muted-foreground/70 ml-2 normal-case tracking-normal">
            {data.verdict}
          </span>
        ) : null}
        <span className="ml-auto">
          {fmtCreated(data.created_at)} | GATE +/-{IC_GATE.toFixed(2)}
        </span>
      </div>

      {/* ── Chart panels ───────────────────────────────────────────── */}
      <div className="grid gap-3 lg:grid-cols-2">
        <ChartPanel
          title="IC mean by horizon"
          legend={
            <>
              <LegendSwatch tokenVar="--chart-3" label="Gate +/-" dashed />
            </>
          }
        >
          <div className="h-64">
            <IcBarChart rows={rows} gate={IC_GATE} />
          </div>
        </ChartPanel>

        <ChartPanel
          title="Top - bottom quantile spread"
          legend={
            <>
              <LegendSwatch tokenVar="--chart-2" label="Positive" />
              <LegendSwatch tokenVar="--chart-4" label="Negative" />
            </>
          }
        >
          <div className="h-64">
            <SpreadBarChart rows={rows} />
          </div>
        </ChartPanel>
      </div>

      {/* ── Rank-IC / per-horizon table ────────────────────────────── */}
      <div className="border-border bg-card rounded-md border">
        <div className="border-border flex items-center justify-between border-b px-3 py-2">
          <div className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
            Per-horizon breakdown
          </div>
          <div className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
            {rows.length} horizons
          </div>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Horizon</TableHead>
              <TableHead className="text-right">IC Mean</TableHead>
              <TableHead className="text-right">IC Std</TableHead>
              <TableHead className="text-right">IC IR</TableHead>
              <TableHead className="text-right">Top - Bottom %</TableHead>
              <TableHead className="text-right">Gate</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const pass = Math.abs(r.ic) >= IC_GATE;
              const isBest = best && r.period === best.period;
              return (
                <TableRow key={r.period} mono>
                  <TableCell>
                    <span
                      className={cn(
                        isBest ? "text-foreground font-semibold" : "text-foreground",
                      )}
                    >
                      {r.period}
                    </span>
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      icTone(r.ic),
                      isBest && "font-semibold",
                    )}
                  >
                    {fmtNumber(r.ic, 4)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {fmtNumber(r.std, 4)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      r.ir > 0
                        ? "text-bullish"
                        : r.ir < 0
                          ? "text-bearish"
                          : "text-muted-foreground",
                    )}
                  >
                    {fmtNumber(r.ir, 3)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right tabular-nums",
                      pnlColorClass(r.spread),
                    )}
                  >
                    {fmtPct(r.spread, 2, true)}
                  </TableCell>
                  <TableCell className="text-right">
                    <span
                      className={cn(
                        "font-mono text-[10px] tracking-wider uppercase",
                        pass ? "text-bullish" : "text-muted-foreground",
                      )}
                    >
                      [ {pass ? "PASS" : "FAIL"} ]
                    </span>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// ─── History panel (no live result yet) ──────────────────────────────────────

type HistoryRow = {
  id: number;
  factor: string;
  universe_label: string;
  created_at: string;
  n_observations: number;
  verdict: string;
};

function DiagnosticHistory({
  rows,
  isLoading,
  error,
}: {
  rows: HistoryRow[];
  isLoading: boolean;
  error: unknown;
}) {
  if (error) return <ErrorState error={error} />;
  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="border-border bg-card rounded-md border p-8 text-center">
        <p className="text-muted-foreground font-mono text-xs">
          No diagnostic data. Run `python -m src.cli.main diagnose ...` or use
          the form above.
        </p>
      </div>
    );
  }

  return (
    <div className="border-border bg-card rounded-md border">
      <div className="border-border flex items-center justify-between border-b px-3 py-2">
        <div className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
          Recent diagnostics
        </div>
        <div className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
          last {rows.length}
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>When</TableHead>
            <TableHead>Factor</TableHead>
            <TableHead>Universe</TableHead>
            <TableHead className="text-right">N Obs</TableHead>
            <TableHead>Verdict</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((d) => (
            <TableRow key={d.id} mono>
              <TableCell className="text-muted-foreground text-xs">
                {fmtCreated(d.created_at)}
              </TableCell>
              <TableCell>
                <span className="text-foreground">{d.factor}</span>
              </TableCell>
              <TableCell className="text-muted-foreground text-xs">
                {d.universe_label}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {d.n_observations.toLocaleString()}
              </TableCell>
              <TableCell className="text-xs">
                <span className="text-muted-foreground font-mono tracking-wider uppercase">
                  {d.verdict || "—"}
                </span>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ─── Inline chart-legend swatch ──────────────────────────────────────────────

function ChartPanel({
  title,
  legend,
  children,
}: {
  title: string;
  legend?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="border-border bg-card rounded-md border">
      <div className="border-border flex items-center justify-between border-b px-3 py-2">
        <div className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
          {title}
        </div>
        {legend ? (
          <div className="text-muted-foreground flex items-center gap-3 font-mono text-[10px] tracking-wider uppercase">
            {legend}
          </div>
        ) : null}
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

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
        className={cn(
          "inline-block h-0.5 w-4",
          dashed && "border-t border-dashed",
        )}
        style={{
          background: dashed ? "transparent" : `var(${tokenVar})`,
          borderColor: dashed ? `var(${tokenVar})` : undefined,
        }}
      />
      <span>{label}</span>
    </span>
  );
}
