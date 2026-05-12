"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type CompleteEvent,
  type ProgressEvent,
  type ScanStage,
  type ScanStreamRequest,
  startScanStream,
} from "./scan-stream";

export type ScanStageState = {
  stage: ScanStage;
  n?: number;
  at: number;
};

export type TickerProgress = {
  ticker: string;
  i: number;
  n: number;
};

export type ScanStreamState = {
  active: boolean;
  stages: ScanStageState[];
  currentStage: ScanStage | null;
  /** Latest per-ticker analyze event, used to render "Analyzing AAPL (3/15)". */
  currentTicker: TickerProgress | null;
  /** Tickers the analyzer crashed on; surfaced as a warning, not a hard error. */
  failedTickers: string[];
  complete: CompleteEvent | null;
  error: string | null;
};

const INITIAL: ScanStreamState = {
  active: false,
  stages: [],
  currentStage: null,
  currentTicker: null,
  failedTickers: [],
  complete: null,
  error: null,
};

export function useScanStream() {
  const [state, setState] = useState<ScanStreamState>(INITIAL);
  const abortRef = useRef<(() => void) | null>(null);

  const start = useCallback((req: ScanStreamRequest) => {
    setState({ ...INITIAL, active: true });

    abortRef.current = startScanStream(req, {
      onProgress: (event: ProgressEvent) => {
        setState((prev) => {
          // Per-ticker events drive the inner progress display but don't
          // pollute the stage-checkpoint list (it would balloon with 100+
          // entries for a big universe).
          if (
            event.stage === "analyze_ticker_start" ||
            event.stage === "analyze_ticker_done"
          ) {
            if (event.ticker && event.i != null && event.n != null) {
              return {
                ...prev,
                currentTicker: {
                  ticker: event.ticker,
                  i: event.i,
                  n: event.n,
                },
              };
            }
            return prev;
          }
          if (event.stage === "analyze_ticker_failed") {
            return {
              ...prev,
              failedTickers: event.ticker
                ? [...prev.failedTickers, event.ticker]
                : prev.failedTickers,
            };
          }
          return {
            ...prev,
            currentStage: event.stage,
            currentTicker:
              event.stage === "score_start" ||
              event.stage === "recommend_start" ||
              event.stage === "score_done"
                ? null
                : prev.currentTicker,
            stages: [
              ...prev.stages,
              { stage: event.stage, n: event.n, at: Date.now() },
            ],
          };
        });
      },
      onComplete: (event) => {
        setState((prev) => ({
          ...prev,
          active: false,
          complete: event,
          currentStage: "complete",
        }));
        abortRef.current = null;
      },
      onError: (event) => {
        setState((prev) => ({
          ...prev,
          active: false,
          error: event.detail,
        }));
        abortRef.current = null;
      },
    });
  }, []);

  const abort = useCallback(() => {
    if (abortRef.current) {
      abortRef.current();
      abortRef.current = null;
      setState((prev) => ({ ...prev, active: false }));
    }
  }, []);

  const reset = useCallback(() => {
    if (abortRef.current) {
      abortRef.current();
      abortRef.current = null;
    }
    setState(INITIAL);
  }, []);

  // Drop the connection on unmount.
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current();
        abortRef.current = null;
      }
    };
  }, []);

  return { state, start, abort, reset };
}
