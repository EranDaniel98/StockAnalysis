"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Sparkles, X } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScanProgress } from "@/components/scan-progress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type ScanResultItem } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { useScanStream } from "@/lib/api/use-scan-stream";
import { fmtDate, fmtNumber } from "@/lib/format";

const STRATEGIES = [
  "swing_trading",
  "short_term_momentum",
  "long_term_growth",
  "value_investing",
  "dividend_income",
];

type FormShape = {
  strategy: string;
  budget: string;
  theme: string;
  top: string;
};

export default function ScanPage() {
  const qc = useQueryClient();
  const { state: streamState, start: startStream, abort, reset } = useScanStream();

  const { register, handleSubmit, watch, setValue } = useForm<FormShape>({
    defaultValues: {
      strategy: "swing_trading",
      budget: "",
      theme: "",
      top: "10",
    },
  });

  // Once the stream emits `complete`, refetch the persisted scan by run_id.
  const resultQuery = useQuery({
    queryKey: streamState.complete
      ? qk.scans.detail(streamState.complete.run_id)
      : ["scans", "detail", "_idle"],
    queryFn: () => api.scans.get(streamState.complete!.run_id),
    enabled: streamState.complete !== null,
  });

  useEffect(() => {
    if (streamState.complete) {
      toast.success(`Scan complete — ${streamState.complete.n_results} candidates`);
      qc.invalidateQueries({ queryKey: qk.scans.all });
    }
  }, [streamState.complete, qc]);

  useEffect(() => {
    if (streamState.error) {
      toast.error(streamState.error);
    }
  }, [streamState.error]);

  const historyQuery = useQuery({
    queryKey: qk.scans.list({ limit: 10 }),
    queryFn: () => api.scans.list({ limit: 10 }),
    // Suppress refetch on focus during an active scan to avoid stomping on
    // the progress UI with a re-render of stale data.
    enabled: !streamState.active,
  });

  function onSubmit(values: FormShape) {
    startStream({
      strategy: values.strategy,
      budget: values.budget ? Number(values.budget) : null,
      theme: values.theme || null,
      sector: null,
      top: values.top ? Number(values.top) : null,
      fresh: false,
    });
  }

  const strategy = watch("strategy");
  const showProgress = streamState.active || streamState.complete || streamState.error;

  return (
    <>
      <PageHeader
        title="Scan"
        description="Trigger a market scan. Progress streams from the backend over SSE."
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
        <Card>
          <CardHeader>
            <CardTitle>New scan</CardTitle>
            <CardDescription>
              Pick a strategy and (optionally) narrow to a theme.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
              <div className="space-y-1.5">
                <Label htmlFor="strategy">Strategy</Label>
                <Select
                  value={strategy}
                  onValueChange={(v) => v && setValue("strategy", v)}
                >
                  <SelectTrigger id="strategy">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {STRATEGIES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="theme">
                  Theme <span className="text-muted-foreground">(optional)</span>
                </Label>
                <Input
                  id="theme"
                  placeholder="e.g. artificial_intelligence"
                  {...register("theme")}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="budget">
                    Budget <span className="text-muted-foreground">(USD)</span>
                  </Label>
                  <Input
                    id="budget"
                    type="number"
                    min={0}
                    step={100}
                    placeholder="10000"
                    {...register("budget")}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="top">Top N</Label>
                  <Input
                    id="top"
                    type="number"
                    min={1}
                    max={200}
                    {...register("top")}
                  />
                </div>
              </div>

              <div className="flex gap-2">
                <Button
                  type="submit"
                  disabled={streamState.active}
                  className="flex-1"
                >
                  {streamState.active ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="mr-2 h-4 w-4" />
                  )}
                  {streamState.active ? "Scanning…" : "Run scan"}
                </Button>
                {streamState.active ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={abort}
                    aria-label="Cancel scan"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                ) : showProgress ? (
                  <Button type="button" variant="outline" onClick={reset}>
                    Clear
                  </Button>
                ) : null}
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="space-y-6">
          {showProgress ? <ScanProgress state={streamState} /> : null}

          {streamState.complete ? (
            <Card>
              <CardHeader>
                <CardTitle>Results</CardTitle>
                <CardDescription>
                  Run {streamState.complete.run_id.slice(0, 8)}… ·{" "}
                  {streamState.complete.strategy}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {resultQuery.error ? (
                  <ErrorState error={resultQuery.error} />
                ) : null}
                {resultQuery.isLoading ? (
                  <Skeleton className="h-32 w-full" />
                ) : resultQuery.data ? (
                  <ResultsTable results={resultQuery.data.results} />
                ) : null}
              </CardContent>
            </Card>
          ) : !showProgress ? (
            <Card>
              <CardHeader>
                <CardTitle>Recent scans</CardTitle>
                <CardDescription>
                  Last 10 scan runs from the database.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {historyQuery.isLoading ? (
                  <Skeleton className="h-32 w-full" />
                ) : historyQuery.error ? (
                  <ErrorState error={historyQuery.error} />
                ) : !historyQuery.data || historyQuery.data.length === 0 ? (
                  <p className="text-muted-foreground py-8 text-center text-sm">
                    No scans yet. Trigger one to see results.
                  </p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>When</TableHead>
                        <TableHead>Strategy</TableHead>
                        <TableHead>Top ticker</TableHead>
                        <TableHead className="text-right">Score</TableHead>
                        <TableHead className="text-right">N</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {historyQuery.data.map((s) => (
                        <TableRow key={s.run_id}>
                          <TableCell className="text-muted-foreground text-xs">
                            {fmtDate(s.scan_timestamp)}
                          </TableCell>
                          <TableCell>
                            <Badge variant="secondary">{s.strategy}</Badge>
                          </TableCell>
                          <TableCell className="font-mono">
                            {s.top_ticker ?? "—"}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtNumber(s.top_score, 1)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {s.n_candidates}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </>
  );
}

function ResultsTable({ results }: { results: ScanResultItem[] }) {
  if (results.length === 0) {
    return (
      <p className="text-muted-foreground py-8 text-center text-sm">
        Scan returned no candidates above the strategy threshold.
      </p>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Ticker</TableHead>
          <TableHead>Action</TableHead>
          <TableHead className="text-right">Score</TableHead>
          <TableHead>Sub-scores</TableHead>
          <TableHead>Sector</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {results.map((r) => (
          <TableRow key={r.ticker}>
            <TableCell>
              <Badge variant="outline" className="font-mono">
                {r.ticker}
              </Badge>
            </TableCell>
            <TableCell>
              <ActionBadge action={r.action} />
            </TableCell>
            <TableCell className="text-right tabular-nums">
              {fmtNumber(r.composite_score, 1)}
            </TableCell>
            <TableCell className="min-w-[180px]">
              <SubScoreBars sub={r.sub_scores ?? {}} />
            </TableCell>
            <TableCell className="text-muted-foreground text-xs">
              {r.sector ?? "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function ActionBadge({ action }: { action: string }) {
  const variant =
    action.startsWith("STRONG BUY") || action === "BUY"
      ? "default"
      : action === "HOLD"
        ? "secondary"
        : "destructive";
  return <Badge variant={variant}>{action}</Badge>;
}

function SubScoreBars({ sub }: { sub: Record<string, number | undefined> }) {
  const entries = Object.entries(sub).slice(0, 6);
  return (
    <div className="space-y-1">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-center gap-2">
          <span className="text-muted-foreground w-20 text-[10px] uppercase tracking-wide">
            {k}
          </span>
          <Progress value={v ?? 0} className="h-1.5 flex-1" />
          <span className="text-muted-foreground w-8 text-right text-[10px] tabular-nums">
            {v == null ? "—" : v.toFixed(0)}
          </span>
        </div>
      ))}
    </div>
  );
}
