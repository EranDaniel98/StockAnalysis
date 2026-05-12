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

export type ScanStreamState = {
  active: boolean;
  stages: ScanStageState[];
  currentStage: ScanStage | null;
  complete: CompleteEvent | null;
  error: string | null;
};

const INITIAL: ScanStreamState = {
  active: false,
  stages: [],
  currentStage: null,
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
        setState((prev) => ({
          ...prev,
          currentStage: event.stage,
          stages: [
            ...prev.stages,
            { stage: event.stage, n: event.n, at: Date.now() },
          ],
        }));
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
