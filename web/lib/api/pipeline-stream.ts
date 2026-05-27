/**
 * EventSource client for /api/pipeline/stream.
 *
 * Triggers `scripts.run_daily_pipeline` server-side and streams per-step
 * progress events. Mirrors the shape of `scan-stream.ts` — same SSE
 * pattern, different event semantics (steps, not scan stages).
 */

import { API_BASE } from "./client";

export const PIPELINE_STEPS = [
  "daily_factor_picks",
  "comprehensive_analysis",
  "exit_analysis",
  "position_monitor",
  "stress_test",
  "generate_watchlist",
  "ai_sanity_check",
  "morning_briefing",
  "paper_vs_spy_snapshot",
  "kill_switch_check",
] as const;

export type PipelineStep = typeof PIPELINE_STEPS[number];

export type PipelineReadyEvent = {
  steps: PipelineStep[];
  started_at: string;
  picks_date: string | null;
  top_n: number;
};

export type PipelineStepStartedEvent = {
  step: PipelineStep;
  ts: string;
};

export type PipelineStepCompletedEvent = {
  step: PipelineStep;
  exit_code: number;
  elapsed_s: number;
  /** Last N lines of merged stdout/stderr for the step — handy on failure. */
  tail: string[];
  synthetic?: boolean;
};

export type PipelineDoneEvent = {
  exit_code: number;
  total_elapsed_s: number;
  /** Per-step exit codes captured from the script's log markers. */
  steps: Partial<Record<PipelineStep, number>>;
};

export type PipelineErrorEvent = {
  detail: string;
  /** Set on the 409 "already running" branch. */
  started_at?: string | null;
};

export type PipelineStreamRequest = {
  picksDate?: string | null;
  topN?: number;
};

export type PipelineStreamHandlers = {
  onReady: (event: PipelineReadyEvent) => void;
  onStepStarted: (event: PipelineStepStartedEvent) => void;
  onStepCompleted: (event: PipelineStepCompletedEvent) => void;
  onDone: (event: PipelineDoneEvent) => void;
  onError: (event: PipelineErrorEvent) => void;
};

/**
 * Open an SSE connection. Returns an `abort` function the caller can
 * invoke (component unmount, Cancel button) — disconnect on the server
 * side kills the subprocess.
 */
export function startPipelineStream(
  req: PipelineStreamRequest,
  handlers: PipelineStreamHandlers,
): () => void {
  const params = new URLSearchParams();
  if (req.picksDate) params.set("picks_date", req.picksDate);
  if (req.topN != null) params.set("top_n", String(req.topN));
  const qs = params.toString();

  const url = `${API_BASE}/api/pipeline/stream${qs ? `?${qs}` : ""}`;
  const source = new EventSource(url);

  source.addEventListener("ready", (e) => {
    try {
      handlers.onReady(JSON.parse((e as MessageEvent).data));
    } catch {
      // malformed payload from a server we control — swallow rather
      // than killing the stream.
    }
  });

  source.addEventListener("step_started", (e) => {
    try {
      handlers.onStepStarted(JSON.parse((e as MessageEvent).data));
    } catch {
      // ignore
    }
  });

  source.addEventListener("step_completed", (e) => {
    try {
      handlers.onStepCompleted(JSON.parse((e as MessageEvent).data));
    } catch {
      // ignore
    }
  });

  source.addEventListener("done", (e) => {
    try {
      handlers.onDone(JSON.parse((e as MessageEvent).data));
    } finally {
      source.close();
    }
  });

  source.addEventListener("error", (e) => {
    const data = (e as MessageEvent).data;
    if (typeof data === "string" && data.length > 0) {
      try {
        handlers.onError(JSON.parse(data));
      } catch {
        handlers.onError({ detail: "pipeline stream parse error" });
      }
    } else if (source.readyState === EventSource.CLOSED) {
      handlers.onError({ detail: "pipeline stream closed unexpectedly" });
    }
    source.close();
  });

  // The server emits periodic heartbeats; EventSource swallows unnamed
  // events, but the named "heartbeat" event needs no handler — its only
  // purpose is to keep the connection warm during long quiet steps.

  return () => source.close();
}
