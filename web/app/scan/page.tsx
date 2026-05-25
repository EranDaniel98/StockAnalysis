"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Circle,
  ExternalLink,
  Loader2,
  Play,
  RefreshCw,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type PipelineRecentRun } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import {
  PIPELINE_STEPS,
  type PipelineStep,
} from "@/lib/api/pipeline-stream";
import {
  usePipelineStream,
  type StepState,
} from "@/lib/api/use-pipeline-stream";
import { fmtRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

// ─── helpers ─────────────────────────────────────────────────────────────────

function todayUtcIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatElapsed(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds - m * 60);
  return `${m}m${s.toString().padStart(2, "0")}s`;
}

function useTickEverySecond(active: boolean): number {
  // Returns Date.now() ticking once per second while ``active``. Used to
  // re-render the running step's live elapsed counter without rebuilding
  // the whole table on every state update.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function ScanPage() {
  const qc = useQueryClient();
  const { state, start, abort, reset } = usePipelineStream();
  const [picksDate, setPicksDate] = useState<string>(todayUtcIso());
  const [topN, setTopN] = useState<number>(15);

  const recentQ = useQuery({
    queryKey: qk.pipeline.recent(5),
    queryFn: () => api.pipeline.recent(5),
    refetchInterval: state.active ? false : 30_000,
  });

  // After a successful run, invalidate everything that depends on picks/
  // briefing files so the rest of the UI catches up.
  useEffect(() => {
    if (state.done && state.done.exit_code === 0) {
      toast.success("Daily pipeline completed");
      qc.invalidateQueries({ queryKey: qk.pipeline.all });
      qc.invalidateQueries({ queryKey: qk.dashboard.briefing() });
      qc.invalidateQueries({ queryKey: qk.portfolio.recommendations() });
      qc.invalidateQueries({ queryKey: qk.portfolio.spySnapshot() });
    } else if (state.done && state.done.exit_code !== 0) {
      toast.error("Pipeline finished with failures — see step ladder");
    }
  }, [state.done, qc]);

  useEffect(() => {
    if (state.error) toast.error(state.error);
  }, [state.error]);

  const tickNow = useTickEverySecond(state.active);

  const onRun = () => {
    start({
      picksDate: picksDate || null,
      topN: topN > 0 ? topN : 15,
    });
  };

  return (
    <>
      <PageHeader
        title="Daily pipeline"
        description="Re-run the full pipeline (picks → analysis → exit plan → briefing → AI sanity → paper-vs-SPY). One run at a time."
      />

      {/* Control strip — date / top-N / Run button */}
      <form
        onSubmit={(e) => { e.preventDefault(); onRun(); }}
        className="border border-border rounded-md bg-card p-3 mb-4"
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[1.4fr_0.7fr_auto] md:items-end">
          <div className="space-y-1">
            <Label
              htmlFor="picks-date"
              className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase"
            >
              Picks date
            </Label>
            <Input
              id="picks-date"
              type="date"
              value={picksDate}
              onChange={(e) => setPicksDate(e.target.value)}
              className="font-mono text-xs tabular-nums h-8"
              disabled={state.active}
            />
          </div>

          <div className="space-y-1">
            <Label
              htmlFor="top-n"
              className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase"
            >
              Top N
            </Label>
            <Input
              id="top-n"
              type="number"
              min={1}
              max={50}
              value={topN}
              onChange={(e) => setTopN(Number(e.target.value) || 15)}
              className="font-mono text-xs tabular-nums h-8"
              disabled={state.active}
            />
          </div>

          <div className="flex gap-2">
            <Button
              type="submit"
              disabled={state.active}
              size="sm"
              className="font-mono text-[11px] tracking-wider uppercase h-8"
            >
              {state.active ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="mr-1.5 h-3.5 w-3.5" />
              )}
              {state.active ? "Running" : "Run pipeline"}
            </Button>
            {state.active ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={abort}
                aria-label="Cancel pipeline"
                className="h-8"
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            ) : state.done || state.error ? (
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
        <p className="mt-2 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
          {state.active
            ? `running ${state.currentStep ?? "…"} · started ${state.startedAt ? fmtRelativeTime(new Date(state.startedAt).toISOString()) : "just now"}`
            : "pipeline runs scripts.run_daily_pipeline server-side · 9 steps · ~5-10 min"}
        </p>
      </form>

      {/* Active run state: step ladder. Otherwise: recent runs. */}
      {state.active || state.done || state.error ? (
        <StepLadderCard
          state={state}
          tickNow={tickNow}
          picksDate={picksDate}
        />
      ) : (
        <RecentRunsCard query={recentQ} />
      )}
    </>
  );
}

// ─── Step ladder (active + done states) ─────────────────────────────────────

function StepLadderCard({
  state, tickNow, picksDate,
}: {
  state: ReturnType<typeof usePipelineStream>["state"];
  tickNow: number;
  picksDate: string;
}) {
  const nOk = Object.values(state.steps).filter((s) => s.status === "ok").length;
  const nFailed = Object.values(state.steps).filter((s) => s.status === "failed").length;
  const totalElapsed = state.done?.total_elapsed_s
    ?? (state.startedAt ? (tickNow - state.startedAt) / 1000 : 0);

  const summary = state.done
    ? state.done.exit_code === 0
      ? `${nOk}/${PIPELINE_STEPS.length} steps OK in ${formatElapsed(totalElapsed)}`
      : `Pipeline finished with ${nFailed} failed step${nFailed === 1 ? "" : "s"} in ${formatElapsed(totalElapsed)}`
    : state.error
      ? `Error: ${state.error}`
      : `Running step ${state.currentStep ?? "…"} · ${formatElapsed(totalElapsed)} elapsed`;

  const summaryTone = state.done
    ? state.done.exit_code === 0 ? "text-bullish" : "text-bearish"
    : state.error
      ? "text-bearish"
      : "text-foreground";

  return (
    <div className="border border-border rounded-md bg-card">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
          Pipeline run
        </div>
        <div className={cn("font-mono text-[10px] tracking-wider uppercase", summaryTone)}>
          {summary}
        </div>
      </div>

      <ol className="divide-y divide-border">
        {PIPELINE_STEPS.map((step) => (
          <StepRow
            key={step}
            step={step}
            stepState={state.steps[step]}
            isCurrent={state.currentStep === step}
            tickNow={tickNow}
          />
        ))}
      </ol>

      {/* Post-run: quick jumps */}
      {state.done && state.done.exit_code === 0 ? (
        <div className="border-t border-border px-3 py-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground mr-2">Jump to:</span>
          <Link
            href="/factors"
            className="inline-flex items-center gap-1 px-2 py-1 rounded border border-border hover:bg-muted/50 transition-colors"
          >
            <ChevronRight className="h-3 w-3" /> /factors
          </Link>
          <Link
            href="/factors/briefing"
            className="inline-flex items-center gap-1 px-2 py-1 rounded border border-border hover:bg-muted/50 transition-colors"
          >
            <ChevronRight className="h-3 w-3" /> /factors/briefing
          </Link>
          <Link
            href="/portfolio"
            className="inline-flex items-center gap-1 px-2 py-1 rounded border border-border hover:bg-muted/50 transition-colors"
          >
            <ChevronRight className="h-3 w-3" /> /portfolio
          </Link>
          <span className="text-muted-foreground/60 ml-auto text-[11px]">
            picks for {picksDate}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function StepRow({
  step, stepState, isCurrent, tickNow,
}: {
  step: PipelineStep;
  stepState: StepState;
  isCurrent: boolean;
  tickNow: number;
}) {
  const liveElapsedS = useMemo(() => {
    if (stepState.elapsedS != null) return stepState.elapsedS;
    if (stepState.status === "running" && stepState.startedAt) {
      return (tickNow - stepState.startedAt) / 1000;
    }
    return null;
  }, [stepState.elapsedS, stepState.status, stepState.startedAt, tickNow]);

  return (
    <li className="px-3 py-2 grid grid-cols-[auto_1fr_auto_auto] items-center gap-3 text-sm">
      <StepIcon status={stepState.status} />
      <span
        className={cn(
          "font-mono",
          isCurrent && "text-foreground font-medium",
          !isCurrent && stepState.status === "pending" && "text-muted-foreground/70",
          stepState.status === "failed" && "text-bearish",
          stepState.status === "ok" && "text-foreground",
        )}
      >
        {step}
      </span>
      {stepState.status === "failed" && stepState.tail?.length ? (
        <details className="text-[10px] text-muted-foreground">
          <summary className="cursor-pointer hover:text-foreground transition-colors">
            tail ({stepState.tail.length})
          </summary>
          <pre className="mt-1 max-h-40 overflow-auto bg-muted/30 p-2 rounded text-[10px] leading-tight">
            {stepState.tail.join("\n")}
          </pre>
        </details>
      ) : (
        <span />
      )}
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground min-w-[60px] text-right">
        {liveElapsedS != null ? formatElapsed(liveElapsedS) : "—"}
        {stepState.exitCode != null && stepState.exitCode !== 0 ? (
          <span className="ml-1 text-bearish">[{stepState.exitCode}]</span>
        ) : null}
      </span>
    </li>
  );
}

function StepIcon({ status }: { status: StepState["status"] }) {
  if (status === "ok") return <CheckCircle2 className="h-4 w-4 text-bullish" />;
  if (status === "failed") return <AlertCircle className="h-4 w-4 text-bearish" />;
  if (status === "running")
    return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
  return <Circle className="h-4 w-4 text-muted-foreground/40" />;
}

// ─── Recent runs (idle state) ───────────────────────────────────────────────

function RecentRunsCard({
  query,
}: {
  query: ReturnType<typeof useQuery<Awaited<ReturnType<typeof api.pipeline.recent>>>>;
}) {
  if (query.isLoading) {
    return (
      <div className="border border-border rounded-md bg-card p-3 space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
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
  const runs = query.data?.runs ?? [];
  if (!query.data || runs.length === 0) {
    return (
      <div className="border border-border rounded-md bg-card p-8 text-center">
        <p className="font-mono text-xs text-muted-foreground">
          No prior runs found. Press{" "}
          <span className="text-primary">[ Run pipeline ]</span> to create one.
        </p>
      </div>
    );
  }

  return (
    <div className="border border-border rounded-md bg-card">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="font-mono text-[10px] tracking-wider uppercase text-muted-foreground">
          Recent runs
        </div>
        <button
          type="button"
          onClick={() => query.refetch()}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Refresh recent runs"
          title="Refresh"
        >
          <RefreshCw className={cn("h-3 w-3", query.isFetching && "animate-spin")} />
        </button>
      </div>
      <ul className="divide-y divide-border">
        {runs.map((run) => (
          <RecentRunRow key={run.picks_date} run={run} />
        ))}
      </ul>
    </div>
  );
}

function RecentRunRow({ run }: { run: PipelineRecentRun }) {
  // Each row maps the per-artifact booleans to dim/coloured checks.
  // A missing artifact = step never ran or failed — surface so the user
  // can re-run for that date.
  return (
    <li className="px-3 py-2 grid grid-cols-[auto_1fr_auto_auto] items-center gap-3 text-sm">
      <span className="font-mono tabular-nums text-foreground">
        {run.picks_date}
      </span>
      <div className="flex items-center gap-1.5 flex-wrap">
        <ArtifactChip label="picks" ok={run.n_picks > 0} detail={`${run.n_picks} names`} />
        <ArtifactChip label="analysis" ok={run.has_analysis} />
        <ArtifactChip label="exit" ok={run.has_exit_plan} />
        <ArtifactChip label="briefing" ok={run.has_briefing} />
        <ArtifactChip label="sanity" ok={run.has_sanity_check} />
      </div>
      <span
        className="text-[10px] font-mono text-muted-foreground"
        title={run.picks_generated_at}
      >
        {fmtRelativeTime(run.picks_generated_at)}
      </span>
      {run.has_briefing ? (
        <Link
          href="/factors/briefing"
          className="text-[11px] text-primary hover:underline inline-flex items-center gap-1"
        >
          open <ExternalLink className="h-3 w-3" />
        </Link>
      ) : (
        <span />
      )}
    </li>
  );
}

function ArtifactChip({
  label, ok, detail,
}: {
  label: string;
  ok: boolean;
  detail?: string;
}) {
  return (
    <Badge
      variant={ok ? "bullish" : "neutral"}
      className={cn(
        "text-[9px] font-mono uppercase tracking-wider px-1.5",
        !ok && "opacity-50",
      )}
      title={ok ? `${label} produced${detail ? ` (${detail})` : ""}` : `${label} missing`}
    >
      {ok ? "✓" : "·"} {label}
    </Badge>
  );
}
