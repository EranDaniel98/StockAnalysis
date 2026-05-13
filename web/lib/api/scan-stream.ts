/**
 * EventSource client for /api/stream/scan.
 *
 * SSE because progress arrives across minutes and EventSource gives us
 * native reconnection + named events for free. POST /api/scans is still the
 * blocking fallback for callers that don't need progress.
 */

import { API_BASE } from "./client";

export type ScanStage =
  | "discover_start"
  | "discover_done"
  | "fundamentals_start"
  | "fundamentals_done"
  | "stage2_done"
  | "prices_start"
  | "prices_done"
  | "analyst_revisions_start"
  | "analyst_revisions_done"
  | "options_chains_start"
  | "options_chains_done"
  | "analyze_start"
  | "analyze_ticker_start"
  | "analyze_ticker_done"
  | "analyze_ticker_failed"
  | "score_start"
  | "recommend_start"
  | "score_done"
  | "complete";

export type ProgressEvent = {
  stage: ScanStage;
  n?: number;
  /** Per-ticker analyze events also carry these. */
  ticker?: string;
  i?: number;
  error?: string;
};

export type CompleteEvent = {
  stage: "complete";
  run_id: string;
  n_results: number;
  strategy: string;
};

export type ErrorEvent = {
  stage: "error";
  detail: string;
};

export type ScanStreamRequest = {
  strategy: string;
  budget?: number | null;
  universe?: "themes" | "russell_1000" | "value_cohort" | "watchlist" | null;
  theme?: string | null;
  sector?: string | null;
  top?: number | null;
  fresh?: boolean;
  live_signals?: boolean;
};

export type ScanStreamHandlers = {
  onProgress: (event: ProgressEvent) => void;
  onComplete: (event: CompleteEvent) => void;
  onError: (event: ErrorEvent) => void;
};

/**
 * Open an SSE connection to /api/stream/scan. Returns an `abort` function
 * the caller can invoke (component unmount, cancel button) to drop the
 * connection — the server-side worker task is cancelled when the request
 * disconnects.
 */
export function startScanStream(
  req: ScanStreamRequest,
  handlers: ScanStreamHandlers,
): () => void {
  const params = new URLSearchParams();
  params.set("strategy", req.strategy);
  if (req.budget != null) params.set("budget", String(req.budget));
  if (req.universe) params.set("universe", req.universe);
  if (req.theme) params.set("theme", req.theme);
  if (req.sector) params.set("sector", req.sector);
  if (req.top != null) params.set("top", String(req.top));
  if (req.fresh) params.set("fresh", "true");
  if (req.live_signals === false) params.set("live_signals", "false");

  const url = `${API_BASE}/api/stream/scan?${params.toString()}`;
  const source = new EventSource(url);

  source.addEventListener("progress", (e) => {
    try {
      handlers.onProgress(JSON.parse((e as MessageEvent).data));
    } catch {
      // ignore malformed event payloads — the server controls this format
    }
  });

  source.addEventListener("complete", (e) => {
    try {
      handlers.onComplete(JSON.parse((e as MessageEvent).data));
    } finally {
      source.close();
    }
  });

  source.addEventListener("error", (e) => {
    // The browser fires a bare `error` event on disconnect with no data —
    // distinguish from our payload-carrying server-side error event.
    const data = (e as MessageEvent).data;
    if (typeof data === "string" && data.length > 0) {
      try {
        handlers.onError(JSON.parse(data));
      } catch {
        handlers.onError({ stage: "error", detail: "stream parse error" });
      }
    } else if (source.readyState === EventSource.CLOSED) {
      // Connection ended without a `complete` event — treat as error.
      handlers.onError({
        stage: "error",
        detail: "scan stream closed unexpectedly",
      });
    }
    source.close();
  });

  return () => source.close();
}
