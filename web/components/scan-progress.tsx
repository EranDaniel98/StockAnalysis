"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { ScanStage } from "@/lib/api/scan-stream";
import type { ScanStreamState } from "@/lib/api/use-scan-stream";

type StageSpec = {
  /** Short uppercase bracket label, Bloomberg-style. */
  code: string;
  /** Stage event that marks this step as started/active. */
  start: ScanStage;
  /** Stage event that marks this step as completed (carrying a count). */
  done: ScanStage;
};

// Pipeline order matches the SSE event sequence. Codes are kept short so a
// full row of brackets fits on one line on a 1280px viewport.
const PIPELINE: StageSpec[] = [
  { code: "DISCOVER", start: "discover_start", done: "discover_done" },
  { code: "FUNDS", start: "fundamentals_start", done: "fundamentals_done" },
  { code: "FILTER", start: "fundamentals_done", done: "stage2_done" },
  { code: "PRICES", start: "prices_start", done: "prices_done" },
  { code: "ANALYST", start: "analyst_revisions_start", done: "analyst_revisions_done" },
  { code: "OPTIONS", start: "options_chains_start", done: "options_chains_done" },
  { code: "ANALYZE", start: "analyze_start", done: "score_done" },
];

type StageStatus = "pending" | "active" | "done";

function statusForStage(
  spec: StageSpec,
  reached: Set<ScanStage>,
  current: ScanStage | null,
): StageStatus {
  if (reached.has(spec.done)) return "done";
  if (reached.has(spec.start) || current === spec.start) return "active";
  return "pending";
}

function countForStage(
  spec: StageSpec,
  stages: ScanStreamState["stages"],
): number | null {
  const found = [...stages].reverse().find((s) => s.stage === spec.done);
  return found?.n ?? null;
}

/** Last `n` of `total` for the ANALYZE stage, drawn from per-ticker events. */
function analyzeProgress(state: ScanStreamState): { i: number; n: number } | null {
  if (!state.currentTicker) return null;
  if (state.currentTicker.n <= 0) return null;
  return { i: state.currentTicker.i, n: state.currentTicker.n };
}

type LogLine = { at: number; text: string };

/**
 * Append-only buffer of stage transitions + recent tickers. Bounded so the
 * tail stays cheap to render even on a 1000-ticker scan.
 */
function useLogLines(state: ScanStreamState): LogLine[] {
  const [lines, setLines] = useState<LogLine[]>([]);
  const lastStageIdx = useRef(0);
  const lastTicker = useRef<string | null>(null);

  useEffect(() => {
    // New stage checkpoints since last render — emit one log line per stage.
    if (state.stages.length > lastStageIdx.current) {
      const fresh = state.stages.slice(lastStageIdx.current);
      lastStageIdx.current = state.stages.length;
      setLines((prev) => {
        const next = [
          ...prev,
          ...fresh.map((s) => ({
            at: s.at,
            text:
              s.n != null
                ? `${s.stage.toUpperCase()} ${s.n}`
                : s.stage.toUpperCase(),
          })),
        ];
        return next.slice(-12);
      });
    }
  }, [state.stages]);

  useEffect(() => {
    const t = state.currentTicker;
    if (!t) return;
    if (t.ticker === lastTicker.current) return;
    lastTicker.current = t.ticker;
    setLines((prev) => {
      const next = [
        ...prev,
        { at: Date.now(), text: `ANALYZE ${t.ticker} ${t.i}/${t.n}` },
      ];
      return next.slice(-12);
    });
  }, [state.currentTicker]);

  useEffect(() => {
    if (state.complete) {
      setLines((prev) =>
        [...prev, { at: Date.now(), text: `COMPLETE ${state.complete!.n_results} candidates` }].slice(-12),
      );
    }
  }, [state.complete]);

  useEffect(() => {
    if (state.error) {
      setLines((prev) =>
        [...prev, { at: Date.now(), text: `ERROR ${state.error}` }].slice(-12),
      );
    }
  }, [state.error]);

  return lines;
}

export function ScanProgress({ state }: { state: ScanStreamState }) {
  const reached = useMemo(
    () => new Set(state.stages.map((s) => s.stage)),
    [state.stages],
  );
  const analyze = analyzeProgress(state);
  const lines = useLogLines(state);

  const statusWord = state.error
    ? "FAILED"
    : state.complete
      ? "COMPLETE"
      : "RUNNING";
  const statusTone = state.error
    ? "text-bearish"
    : state.complete
      ? "text-bullish"
      : "text-primary";

  return (
    <div className="border border-border rounded-md bg-card">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span
          className={cn(
            "inline-block h-1.5 w-1.5 rounded-full",
            state.error
              ? "bg-bearish"
              : state.complete
                ? "bg-bullish"
                : "bg-primary animate-pulse",
          )}
          aria-hidden
        />
        <span
          className={cn(
            "font-mono text-[10px] tracking-wider uppercase",
            statusTone,
          )}
        >
          {statusWord}
        </span>
        {state.complete ? (
          <span className="font-mono text-[10px] text-muted-foreground tracking-wider uppercase">
            · {state.complete.n_results} candidates · {state.complete.strategy}
          </span>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 font-mono text-[11px]">
        {PIPELINE.map((spec) => {
          const status = statusForStage(spec, reached, state.currentStage);
          const n = countForStage(spec, state.stages);
          const isAnalyze = spec.code === "ANALYZE";
          const tone =
            status === "done"
              ? "text-muted-foreground"
              : status === "active"
                ? "text-primary"
                : "text-muted-foreground/40";

          let body: string;
          if (isAnalyze && status === "active" && analyze) {
            body = `${spec.code} ${analyze.i}/${analyze.n}`;
          } else if (status === "done" && n != null) {
            body = `${spec.code} ${n}`;
          } else if (status === "active") {
            body = spec.code;
          } else {
            body = spec.code;
          }

          return (
            <span key={spec.code} className={cn("tabular-nums", tone)}>
              <span className="text-muted-foreground/40">[ </span>
              <span>{body}</span>
              <span className="text-muted-foreground/40"> ]</span>
            </span>
          );
        })}
        {state.currentTicker && !state.complete ? (
          <span className="text-foreground tabular-nums">
            <span className="text-muted-foreground/40">→ </span>
            {state.currentTicker.ticker}
          </span>
        ) : null}
      </div>

      {lines.length > 0 ? (
        <div className="border-t border-border px-3 py-2 font-mono text-[10px] text-muted-foreground/70 space-y-0.5 max-h-32 overflow-y-auto">
          {lines.map((l, idx) => (
            <div key={`${l.at}-${idx}`} className="tabular-nums">
              <span className="text-muted-foreground/40">
                {new Date(l.at).toLocaleTimeString(undefined, {
                  hour12: false,
                })}
              </span>{" "}
              {l.text}
            </div>
          ))}
        </div>
      ) : null}

      {state.failedTickers.length > 0 ? (
        <div className="border-t border-border px-3 py-2 font-mono text-[10px]">
          <span className="text-bearish tracking-wider uppercase">
            SKIPPED {state.failedTickers.length}
          </span>{" "}
          <span className="text-muted-foreground tabular-nums">
            {state.failedTickers.slice(0, 12).join(" ")}
            {state.failedTickers.length > 12 ? " …" : ""}
          </span>
        </div>
      ) : null}
    </div>
  );
}
