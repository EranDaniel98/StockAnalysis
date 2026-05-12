"use client";

import { Check, Loader2, X } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { ScanStage } from "@/lib/api/scan-stream";
import type { ScanStreamState } from "@/lib/api/use-scan-stream";

type StageSpec = {
  start: ScanStage;
  done: ScanStage;
  label: string;
  countLabel: (n: number) => string;
};

// Pipeline stages in order. `start` marks the in-progress trigger; `done`
// carries the count once the stage completes.
const PIPELINE: StageSpec[] = [
  {
    start: "discover_start",
    done: "discover_done",
    label: "Discover universe",
    countLabel: (n) => `${n} tickers`,
  },
  {
    start: "fundamentals_start",
    done: "fundamentals_done",
    label: "Fundamentals",
    countLabel: (n) => `${n} fetched`,
  },
  {
    // Stage 2 filter is part of the fundamentals phase visually but emits
    // its own event with the filtered count.
    start: "fundamentals_done",
    done: "stage2_done",
    label: "Fundamentals filter",
    countLabel: (n) => `${n} kept`,
  },
  {
    start: "prices_start",
    done: "prices_done",
    label: "Price history",
    countLabel: (n) => `${n} fetched`,
  },
  {
    start: "analyze_start",
    done: "score_done",
    label: "Analyze + score",
    countLabel: (n) => `${n} candidates`,
  },
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

export function ScanProgress({ state }: { state: ScanStreamState }) {
  const reached = new Set(state.stages.map((s) => s.stage));
  const doneCount = PIPELINE.filter((p) => reached.has(p.done)).length;
  const pct = (doneCount / PIPELINE.length) * 100;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {state.error
            ? "Scan failed"
            : state.complete
              ? "Scan complete"
              : "Scan in progress"}
        </CardTitle>
        <CardDescription>
          {state.complete
            ? `${state.complete.n_results} candidates ready — loading results…`
            : state.error
              ? state.error
              : "Streaming progress from the backend."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Progress value={pct} className="h-2" />

        <ul className="space-y-2">
          {PIPELINE.map((spec) => {
            const status = statusForStage(spec, reached, state.currentStage);
            const n = countForStage(spec, state.stages);
            return (
              <li
                key={spec.start}
                className="flex items-center justify-between text-sm"
              >
                <div className="flex items-center gap-2">
                  <StageIcon status={status} hasError={!!state.error} />
                  <span
                    className={
                      status === "done"
                        ? "text-foreground"
                        : status === "active"
                          ? "text-foreground font-medium"
                          : "text-muted-foreground"
                    }
                  >
                    {spec.label}
                  </span>
                </div>
                {n !== null ? (
                  <span className="text-muted-foreground text-xs tabular-nums">
                    {spec.countLabel(n)}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

function StageIcon({
  status,
  hasError,
}: {
  status: StageStatus;
  hasError: boolean;
}) {
  if (hasError && status === "active") {
    return <X className="h-4 w-4 text-red-500" />;
  }
  if (status === "done") {
    return <Check className="h-4 w-4 text-emerald-500" />;
  }
  if (status === "active") {
    return <Loader2 className="text-primary h-4 w-4 animate-spin" />;
  }
  return <div className="border-muted-foreground/30 h-4 w-4 rounded-full border" />;
}
