"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  PIPELINE_STEPS,
  type PipelineDoneEvent,
  type PipelineStep,
  type PipelineStepCompletedEvent,
  type PipelineStreamRequest,
  startPipelineStream,
} from "./pipeline-stream";

export type StepStatus = "pending" | "running" | "ok" | "failed";

export type StepState = {
  status: StepStatus;
  startedAt?: number; // monotonic ms (Date.now equivalent for UI elapsed)
  elapsedS?: number;
  exitCode?: number;
  tail?: string[];
};

export type PipelineStreamState = {
  active: boolean;
  startedAt: number | null;
  picksDate: string | null;
  topN: number | null;
  /** Map of step name → state. Every step from PIPELINE_STEPS is pre-seeded. */
  steps: Record<PipelineStep, StepState>;
  currentStep: PipelineStep | null;
  done: PipelineDoneEvent | null;
  error: string | null;
};

function initialSteps(): Record<PipelineStep, StepState> {
  const out = {} as Record<PipelineStep, StepState>;
  for (const s of PIPELINE_STEPS) {
    out[s] = { status: "pending" };
  }
  return out;
}

const INITIAL: PipelineStreamState = {
  active: false,
  startedAt: null,
  picksDate: null,
  topN: null,
  steps: initialSteps(),
  currentStep: null,
  done: null,
  error: null,
};

export function usePipelineStream() {
  const [state, setState] = useState<PipelineStreamState>(INITIAL);
  const abortRef = useRef<(() => void) | null>(null);

  const start = useCallback((req: PipelineStreamRequest) => {
    setState({
      ...INITIAL,
      steps: initialSteps(),
      active: true,
      picksDate: req.picksDate ?? null,
      topN: req.topN ?? null,
    });

    abortRef.current = startPipelineStream(req, {
      onReady: (evt) => {
        setState((prev) => ({
          ...prev,
          startedAt: Date.now(),
          picksDate: evt.picks_date,
          topN: evt.top_n,
        }));
      },
      onStepStarted: (evt) => {
        setState((prev) => ({
          ...prev,
          currentStep: evt.step,
          steps: {
            ...prev.steps,
            [evt.step]: { status: "running", startedAt: Date.now() },
          },
        }));
      },
      onStepCompleted: (evt: PipelineStepCompletedEvent) => {
        setState((prev) => ({
          ...prev,
          currentStep:
            prev.currentStep === evt.step ? null : prev.currentStep,
          steps: {
            ...prev.steps,
            [evt.step]: {
              status: evt.exit_code === 0 ? "ok" : "failed",
              startedAt: prev.steps[evt.step]?.startedAt,
              elapsedS: evt.elapsed_s,
              exitCode: evt.exit_code,
              tail: evt.tail,
            },
          },
        }));
      },
      onDone: (evt) => {
        setState((prev) => ({
          ...prev,
          active: false,
          done: evt,
          currentStep: null,
        }));
        abortRef.current = null;
      },
      onError: (evt) => {
        setState((prev) => ({
          ...prev,
          active: false,
          error: evt.detail,
          currentStep: null,
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
    setState({ ...INITIAL, steps: initialSteps() });
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
