"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api, type ResearchRunSummary } from "@/lib/api/client";
import { fmtNumber } from "@/lib/format";
import {
  streamResearch,
  type ResearchEvent,
} from "@/lib/api/research-stream";

interface RunState {
  runId: number | null;
  status: "idle" | "streaming" | "complete" | "error";
  finalAnswer: string | null;
  events: ResearchEvent[];
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  error: string | null;
}

const EMPTY_RUN: RunState = {
  runId: null,
  status: "idle",
  finalAnswer: null,
  events: [],
  inputTokens: 0,
  outputTokens: 0,
  costUsd: 0,
  error: null,
};

const SECTION_LABEL =
  "text-[10px] font-medium tracking-wider uppercase text-muted-foreground";

function statusBadge(status: string) {
  if (status === "complete")
    return <Badge variant="bullish">complete</Badge>;
  if (status === "running" || status === "streaming")
    return <Badge variant="default">running</Badge>;
  if (status === "budget_exceeded")
    return <Badge variant="neutral">budget exceeded</Badge>;
  if (status === "failed" || status === "error")
    return <Badge variant="bearish">failed</Badge>;
  return <Badge variant="secondary">{status}</Badge>;
}

export default function ResearchPage() {
  const [question, setQuestion] = useState("");
  const [run, setRun] = useState<RunState>(EMPTY_RUN);
  const ctrlRef = useRef<AbortController | null>(null);
  const queryClient = useQueryClient();

  const runs = useQuery({
    queryKey: ["research", "runs"],
    queryFn: () => api.research.list({ limit: 20 }),
    refetchInterval: 10_000,
  });

  // Cancel any in-flight stream on unmount so the worker task cleans up.
  useEffect(() => () => ctrlRef.current?.abort(), []);

  const stats = useMemo(() => {
    const list = runs.data ?? [];
    const total = list.length;
    let completed = 0;
    let costSum = 0;
    for (const r of list) {
      if (r.status === "complete") completed += 1;
      if (typeof r.estimated_cost_usd === "number") costSum += r.estimated_cost_usd;
    }
    const successPct = total > 0 ? (completed / total) * 100 : 0;
    const avgCost = total > 0 ? costSum / total : 0;
    return { total, completed, successPct, avgCost, costSum };
  }, [runs.data]);

  const successTone: "bullish" | "muted" =
    stats.total > 0 && stats.successPct >= 80 ? "bullish" : "muted";

  const start = () => {
    if (!question.trim() || run.status === "streaming") return;
    ctrlRef.current?.abort();

    setRun({
      ...EMPTY_RUN,
      status: "streaming",
    });

    ctrlRef.current = streamResearch(
      { question: question.trim() },
      (event) =>
        setRun((prev) => {
          const next: RunState = {
            ...prev,
            events: [...prev.events, event],
          };
          switch (event.event) {
            case "started":
              next.runId = event.run_id;
              break;
            case "usage":
              next.inputTokens = event.input_tokens;
              next.outputTokens = event.output_tokens;
              next.costUsd = event.cost_usd;
              break;
            case "final_answer":
              next.finalAnswer = event.text;
              break;
            case "complete":
              next.status = "complete";
              break;
            case "error":
              next.status = "error";
              next.error = event.detail;
              break;
          }
          return next;
        }),
      (reason) => {
        if (reason !== "abort") {
          queryClient.invalidateQueries({ queryKey: ["research", "runs"] });
        }
        setRun((prev) =>
          prev.status === "streaming"
            ? { ...prev, status: reason === "complete" ? "complete" : "error" }
            : prev,
        );
        setQuestion("");
      },
    );
  };

  return (
    <>
      <PageHeader
        title="Research agent"
        description="Anthropic-backed analyst with tool access to your scanner, backtester, paper book, ML feature store, and EDGAR RAG corpus. Streams its thinking live."
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <ScoreboardTile
          label="Total runs"
          value={runs.isLoading ? "—" : String(stats.total)}
          sub={runs.isLoading ? undefined : `last ${stats.total} runs`}
          subTone="muted"
          isLoading={runs.isLoading}
        />
        <ScoreboardTile
          label="Completed"
          value={runs.isLoading ? "—" : String(stats.completed)}
          sub={
            runs.isLoading || stats.total === 0
              ? undefined
              : `${stats.successPct.toFixed(0)}% success`
          }
          subTone={successTone}
          isLoading={runs.isLoading}
        />
        <ScoreboardTile
          label="Avg cost"
          value={
            runs.isLoading || stats.total === 0
              ? "—"
              : `$${fmtNumber(stats.avgCost, 4)}`
          }
          sub={
            runs.isLoading || stats.total === 0
              ? undefined
              : `over ${stats.total} runs`
          }
          subTone="muted"
          isLoading={runs.isLoading}
        />
        <ScoreboardTile
          label="Total spend"
          value={
            runs.isLoading
              ? "—"
              : `$${fmtNumber(stats.costSum, 2)}`
          }
          sub={runs.isLoading ? undefined : "lifetime"}
          subTone="muted"
          isLoading={runs.isLoading}
        />
      </div>

      <div className="mt-4 space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Ask</CardTitle>
            <CardDescription>
              The agent decomposes your question, calls tools (including
              semantic search over 10-K / 10-Q / 8-K filings), and synthesizes
              an answer. Hard cap of 8 tool-use turns per run.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                start();
              }}
            >
              <Textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g. What risks did Apple flag in its most recent 10-K?"
                rows={3}
                disabled={run.status === "streaming"}
              />
              <div className="flex items-center justify-between">
                <p className="text-muted-foreground text-xs font-mono">
                  Claude Sonnet 4.6 · max 8 tool-use turns · streams live.
                </p>
                <Button
                  type="submit"
                  disabled={!question.trim() || run.status === "streaming"}
                >
                  {run.status === "streaming" ? "Streaming…" : "Ask"}
                </Button>
              </div>
            </form>

            {run.status !== "idle" ? (
              <div className="mt-6 space-y-3">
                <div className="flex items-center gap-2">
                  {statusBadge(run.status)}
                  <span className="font-mono text-xs text-muted-foreground tabular-nums">
                    {run.events.length} events · ${fmtNumber(run.costUsd, 4)} ·{" "}
                    {run.inputTokens} in / {run.outputTokens} out
                  </span>
                </div>

                <Timeline events={run.events} />

                {run.finalAnswer ? (
                  <Card>
                    <CardHeader>
                      <CardTitle className={SECTION_LABEL}>
                        Final answer
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="text-sm text-foreground whitespace-pre-wrap">
                      {run.finalAnswer}
                    </CardContent>
                  </Card>
                ) : null}

                {run.error ? (
                  <p className="text-bearish text-sm font-mono">{run.error}</p>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent runs</CardTitle>
            <CardDescription>
              Newest first. Click a row to expand the answer + tool trail.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {runs.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : runs.data && runs.data.length > 0 ? (
              <ul className="space-y-3">
                {runs.data.map((r) => (
                  <RunRow key={r.id} run={r} />
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground text-sm py-8 text-center font-mono">
                No runs yet.
              </p>
            )}
            {runs.error ? <ErrorState error={runs.error} /> : null}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function Timeline({ events }: { events: ResearchEvent[] }) {
  // Heartbeats are noise; filter them out.
  const visible = events.filter((e) => e.event !== "heartbeat");
  if (visible.length === 0) return null;
  return (
    <details open>
      <summary className={`${SECTION_LABEL} cursor-pointer`}>
        Live trail ({visible.length} events)
      </summary>
      <ul className="mt-2 space-y-1 font-mono text-[11px]">
        {visible.map((e, i) => (
          <li
            key={i}
            className="bg-muted/30 border-l-2 border-border rounded px-2 py-1"
          >
            <EventLine event={e} />
          </li>
        ))}
      </ul>
    </details>
  );
}

function EventLine({ event }: { event: ResearchEvent }) {
  switch (event.event) {
    case "started":
      return (
        <span>
          <span className="text-primary">▸ started</span> run #{event.run_id}
        </span>
      );
    case "turn_start":
      return <span className="text-muted-foreground">— turn {event.turn}</span>;
    case "assistant_text":
      return (
        <span>
          <span className="text-bullish">✎ thinking</span>{" "}
          <span className="whitespace-pre-wrap">{event.text}</span>
        </span>
      );
    case "tool_call":
      return (
        <span>
          <span className="text-primary">→ {event.tool}</span>{" "}
          <span className="text-muted-foreground">
            {JSON.stringify(event.input)}
          </span>
        </span>
      );
    case "tool_result":
      return (
        <span>
          <span className={event.is_error ? "text-bearish" : "text-bullish"}>
            ← {event.tool}
          </span>{" "}
          <span className="text-muted-foreground">{event.summary}</span>
        </span>
      );
    case "usage":
      return (
        <span className="text-muted-foreground">
          usage: {event.input_tokens} in / {event.output_tokens} out · $
          {event.cost_usd.toFixed(4)}
        </span>
      );
    case "final_answer":
      return <span className="text-bullish">✓ final answer</span>;
    case "complete":
      return (
        <span className="text-bullish">
          ✓ complete (run #{event.run_id} · {event.status})
        </span>
      );
    case "error":
      return <span className="text-bearish">✗ {event.detail}</span>;
    default:
      return <span className="text-muted-foreground">…</span>;
  }
}

function RunRow({ run }: { run: ResearchRunSummary }) {
  const [open, setOpen] = useState(false);
  const detail = useQuery({
    queryKey: ["research", "runs", run.id],
    queryFn: () => api.research.get(run.id),
    enabled: open,
  });

  return (
    <li className="rounded border border-border p-3 hover:bg-muted/40 transition-colors">
      <button
        className="flex w-full items-start justify-between gap-3 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-sm font-medium text-foreground">
            {run.question}
          </p>
          <p className="text-muted-foreground mt-1 text-xs font-mono tabular-nums">
            {new Date(run.started_at).toLocaleString()} · {run.n_turns} turns ·
            ${fmtNumber(run.estimated_cost_usd, 4)}
          </p>
        </div>
        {statusBadge(run.status)}
      </button>
      {open ? (
        <div className="mt-3">
          {detail.isLoading ? (
            <Skeleton className="h-16 w-full" />
          ) : detail.data ? (
            <div className="space-y-2 text-xs">
              <Card>
                <CardContent className="text-sm text-foreground whitespace-pre-wrap pt-3">
                  {detail.data.final_answer ?? "(no answer)"}
                </CardContent>
              </Card>
              {detail.data.tool_calls && detail.data.tool_calls.length > 0 ? (
                <details>
                  <summary className={`${SECTION_LABEL} cursor-pointer`}>
                    Tool trail ({detail.data.tool_calls.length})
                  </summary>
                  <div className="mt-2 space-y-2 font-mono text-[11px]">
                    {detail.data.tool_calls.map((c, i) => (
                      <div
                        key={i}
                        className="border border-border rounded p-2 bg-card"
                      >
                        <span className="font-mono text-xs font-semibold text-primary">
                          {c.tool}
                        </span>
                        <pre className="mt-1 whitespace-pre-wrap">
                          {c.result_summary}
                        </pre>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
              {run.error ? (
                <p className="text-bearish font-mono">{run.error}</p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
