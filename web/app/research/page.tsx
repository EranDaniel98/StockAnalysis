"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
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

function statusBadge(status: string) {
  if (status === "complete")
    return <Badge className="bg-emerald-500/20 text-emerald-300">complete</Badge>;
  if (status === "running")
    return <Badge className="bg-sky-500/20 text-sky-300">running</Badge>;
  if (status === "budget_exceeded")
    return (
      <Badge className="bg-amber-500/20 text-amber-300">budget exceeded</Badge>
    );
  if (status === "failed")
    return <Badge className="bg-red-500/20 text-red-300">failed</Badge>;
  return <Badge className="bg-muted text-muted-foreground">{status}</Badge>;
}

export default function ResearchPage() {
  const [question, setQuestion] = useState("");
  const queryClient = useQueryClient();

  const runs = useQuery({
    queryKey: ["research", "runs"],
    queryFn: () => api.research.list({ limit: 20 }),
    refetchInterval: 5_000,
  });

  const ask = useMutation({
    mutationFn: (body: { question: string }) =>
      api.research.ask({
        question: body.question,
        model: null,
        max_turns: 8,
        notes: null,
      }),
    onSuccess: () => {
      setQuestion("");
      queryClient.invalidateQueries({ queryKey: ["research"] });
    },
  });

  return (
    <>
      <PageHeader
        title="Research agent"
        description="Anthropic-backed analyst with tool access to your scanner, backtester, paper book, and ML feature store. Hard budget caps per run."
      />

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Ask</CardTitle>
            <CardDescription>
              The agent decomposes your question, calls tools, and synthesizes
              an answer. Costs ~$0.01–$0.10 per run depending on tool depth.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (!question.trim() || ask.isPending) return;
                ask.mutate({ question: question.trim() });
              }}
            >
              <Textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g. Which open positions have the lowest current composite score?"
                rows={3}
                disabled={ask.isPending}
              />
              <div className="flex items-center justify-between">
                <p className="text-muted-foreground text-xs">
                  Default model: Claude Sonnet 4.6 · max 8 tool-use turns.
                </p>
                <Button
                  type="submit"
                  disabled={!question.trim() || ask.isPending}
                >
                  {ask.isPending ? "Researching…" : "Ask"}
                </Button>
              </div>
            </form>

            {ask.error ? <ErrorState error={ask.error} /> : null}

            {ask.data ? (
              <div className="mt-6 space-y-3">
                <div className="flex items-center gap-2">
                  {statusBadge(ask.data.status)}
                  <span className="text-muted-foreground text-xs">
                    {ask.data.n_turns} turns · $
                    {fmtNumber(ask.data.estimated_cost_usd, 4)} ·{" "}
                    {ask.data.input_tokens} in / {ask.data.output_tokens} out
                  </span>
                </div>
                <Card>
                  <CardContent className="prose prose-invert max-w-none pt-4 text-sm whitespace-pre-wrap">
                    {ask.data.final_answer ?? "(no answer — see error)"}
                  </CardContent>
                </Card>
                {ask.data.tool_calls && ask.data.tool_calls.length > 0 ? (
                  <details className="text-xs">
                    <summary className="text-muted-foreground cursor-pointer">
                      Tool trail ({ask.data.tool_calls.length})
                    </summary>
                    <div className="mt-2 space-y-2">
                      {ask.data.tool_calls.map((c, i) => (
                        <div
                          key={i}
                          className="bg-muted/40 rounded p-2 font-mono text-[11px]"
                        >
                          <div className="flex items-center gap-2">
                            <span className="font-semibold">{c.tool}</span>
                            {c.is_error ? (
                              <Badge className="bg-red-500/20 text-red-300">
                                error
                              </Badge>
                            ) : null}
                          </div>
                          <pre className="mt-1 text-muted-foreground whitespace-pre-wrap">
                            {JSON.stringify(c.input, null, 2)}
                          </pre>
                          <pre className="mt-1 whitespace-pre-wrap">
                            {c.result_summary}
                          </pre>
                        </div>
                      ))}
                    </div>
                  </details>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent runs</CardTitle>
            <CardDescription>
              Newest first. Click a row to see the full answer + tool trail.
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
              <p className="text-muted-foreground text-sm">No runs yet.</p>
            )}
            {runs.error ? <ErrorState error={runs.error} /> : null}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function RunRow({ run }: { run: ResearchRunSummary }) {
  const [open, setOpen] = useState(false);
  const detail = useQuery({
    queryKey: ["research", "runs", run.id],
    queryFn: () => api.research.get(run.id),
    enabled: open,
  });

  return (
    <li className="border-border/40 rounded border p-3">
      <button
        className="flex w-full items-start justify-between gap-3 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-sm font-medium">{run.question}</p>
          <p className="text-muted-foreground mt-1 text-xs">
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
                <CardContent className="prose prose-invert max-w-none pt-3 text-sm whitespace-pre-wrap">
                  {detail.data.final_answer ?? "(no answer)"}
                </CardContent>
              </Card>
              {detail.data.tool_calls && detail.data.tool_calls.length > 0 ? (
                <details>
                  <summary className="text-muted-foreground cursor-pointer">
                    Tool trail ({detail.data.tool_calls.length})
                  </summary>
                  <div className="mt-2 space-y-2 font-mono text-[11px]">
                    {detail.data.tool_calls.map((c, i) => (
                      <div key={i} className="bg-muted/40 rounded p-2">
                        <span className="font-semibold">{c.tool}</span>
                        <pre className="mt-1 whitespace-pre-wrap">
                          {c.result_summary}
                        </pre>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
              {run.error ? (
                <p className="text-red-300">{run.error}</p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
