"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Sparkles } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

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
import {
  type ScanRequest,
  type ScanResultItem,
  api,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
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

  const { register, handleSubmit, watch, setValue } = useForm<FormShape>({
    defaultValues: { strategy: "swing_trading", budget: "", theme: "", top: "10" },
  });

  const scanMutation = useMutation({
    mutationFn: (body: ScanRequest) => api.scans.trigger(body),
    onSuccess: () => {
      toast.success("Scan complete");
      qc.invalidateQueries({ queryKey: qk.scans.all });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Scan failed");
    },
  });

  const historyQuery = useQuery({
    queryKey: qk.scans.list({ limit: 10 }),
    queryFn: () => api.scans.list({ limit: 10 }),
  });

  function onSubmit(values: FormShape) {
    const body: ScanRequest = {
      strategy: values.strategy,
      budget: values.budget ? Number(values.budget) : null,
      theme: values.theme || null,
      sector: null,
      top: values.top ? Number(values.top) : null,
      fresh: false,
    };
    scanMutation.mutate(body);
  }

  const strategy = watch("strategy");

  return (
    <>
      <PageHeader
        title="Scan"
        description="Trigger a market scan. Blocks until complete — typically 1–3 minutes."
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
            <form
              className="space-y-4"
              onSubmit={handleSubmit(onSubmit)}
            >
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

              <Button
                type="submit"
                disabled={scanMutation.isPending}
                className="w-full"
              >
                {scanMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="mr-2 h-4 w-4" />
                )}
                {scanMutation.isPending ? "Scanning…" : "Run scan"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              {scanMutation.data ? "Latest scan results" : "Recent scans"}
            </CardTitle>
            <CardDescription>
              {scanMutation.data
                ? `${scanMutation.data.n_results} candidates for ${scanMutation.data.strategy}`
                : "Last 10 scan runs from the database."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {scanMutation.error ? (
              <ErrorState error={scanMutation.error} />
            ) : null}

            {scanMutation.data ? (
              <ResultsTable results={scanMutation.data.results} />
            ) : historyQuery.isLoading ? (
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
