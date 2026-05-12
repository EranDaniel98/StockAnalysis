"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Microscope } from "lucide-react";
import { useForm } from "react-hook-form";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
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
import { type DiagnosticRequest, api } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtDate, fmtNumber } from "@/lib/format";

const FACTORS = [
  "composite",
  "technical",
  "fundamental",
  "pattern",
  "statistical",
  "trend",
  "alpha158",
];

const IC_GATE = 0.03;

type FormShape = {
  strategy: string;
  factor: string;
  years: string;
  quantiles: string;
};

export default function DiagnosePage() {
  const qc = useQueryClient();

  const { register, handleSubmit, watch, setValue } = useForm<FormShape>({
    defaultValues: {
      strategy: "swing_trading",
      factor: "composite",
      years: "2",
      quantiles: "5",
    },
  });

  const diagMutation = useMutation({
    mutationFn: (body: DiagnosticRequest) => api.diagnostics.trigger(body),
    onSuccess: () => {
      toast.success("Diagnostic complete");
      qc.invalidateQueries({ queryKey: qk.diagnostics.all });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Diagnostic failed");
    },
  });

  const historyQuery = useQuery({
    queryKey: qk.diagnostics.list({ limit: 10 }),
    queryFn: () => api.diagnostics.list({ limit: 10 }),
  });

  function onSubmit(values: FormShape) {
    const body: DiagnosticRequest = {
      strategy: values.strategy,
      universe: "themes",
      tickers: null,
      factor: values.factor as DiagnosticRequest["factor"],
      years: Number(values.years),
      quantiles: Number(values.quantiles),
      periods: [1, 5, 21],
      accept_lookahead: false,
      fresh: false,
    };
    diagMutation.mutate(body);
  }

  const strategy = watch("strategy");
  const factor = watch("factor");

  return (
    <>
      <PageHeader
        title="Diagnose"
        description="Alphalens IC — does the factor predict forward returns? Gate: IC ≥ 0.03 on some horizon."
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
        <Card>
          <CardHeader>
            <CardTitle>Run diagnostic</CardTitle>
            <CardDescription>
              Heavy compute — typically 3-10 minutes depending on years/universe.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
              <div className="space-y-1.5">
                <Label htmlFor="strategy">Strategy</Label>
                <Input id="strategy" {...register("strategy")} />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="factor">Factor</Label>
                <Select
                  value={factor}
                  onValueChange={(v) => v && setValue("factor", v)}
                >
                  <SelectTrigger id="factor">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FACTORS.map((f) => (
                      <SelectItem key={f} value={f}>
                        {f}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="years">Years</Label>
                  <Input
                    id="years"
                    type="number"
                    min={0.5}
                    max={10}
                    step={0.5}
                    {...register("years")}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="quantiles">Quantiles</Label>
                  <Input
                    id="quantiles"
                    type="number"
                    min={2}
                    max={10}
                    {...register("quantiles")}
                  />
                </div>
              </div>

              <Button
                type="submit"
                className="w-full"
                disabled={diagMutation.isPending}
              >
                {diagMutation.isPending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Microscope className="mr-2 h-4 w-4" />
                )}
                {diagMutation.isPending ? "Running…" : "Run"}
              </Button>
              {/* avoid unused-var warning if strategy ends up driven only by register */}
              <input type="hidden" value={strategy} readOnly />
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              {diagMutation.data ? "Latest IC" : "Recent diagnostics"}
            </CardTitle>
            <CardDescription>
              {diagMutation.data
                ? `${diagMutation.data.factor} · n=${diagMutation.data.n_observations}`
                : "Last 10 diagnostic runs."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {diagMutation.error ? (
              <ErrorState error={diagMutation.error} />
            ) : null}

            {diagMutation.data ? (
              <DiagnosticDetail data={diagMutation.data} />
            ) : historyQuery.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : historyQuery.error ? (
              <ErrorState error={historyQuery.error} />
            ) : !historyQuery.data || historyQuery.data.length === 0 ? (
              <p className="text-muted-foreground py-8 text-center text-sm">
                No diagnostic runs yet.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Factor</TableHead>
                    <TableHead>Universe</TableHead>
                    <TableHead className="text-right">n obs</TableHead>
                    <TableHead>Verdict</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {historyQuery.data.map((d) => (
                    <TableRow key={d.id}>
                      <TableCell className="text-muted-foreground text-xs">
                        {fmtDate(d.created_at)}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{d.factor}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {d.universe_label}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {d.n_observations}
                      </TableCell>
                      <TableCell className="text-xs">{d.verdict}</TableCell>
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

function DiagnosticDetail({
  data,
}: {
  data: {
    ic_mean: Record<string, number>;
    ic_ir: Record<string, number>;
    top_minus_bottom_pct: Record<string, number>;
    verdict: string;
  };
}) {
  const icRows = Object.entries(data.ic_mean).map(([period, ic]) => ({
    period,
    ic,
    ir: data.ic_ir[period] ?? 0,
    spread: data.top_minus_bottom_pct[period] ?? 0,
  }));
  return (
    <div className="space-y-6">
      <div className="text-sm">
        <span className="text-muted-foreground">Verdict: </span>
        <span className="font-medium">{data.verdict}</span>
      </div>

      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={icRows}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
            <XAxis dataKey="period" fontSize={11} />
            <YAxis fontSize={11} tickFormatter={(v) => v.toFixed(3)} />
            <Tooltip
              contentStyle={{
                background: "hsl(var(--popover))",
                border: "1px solid hsl(var(--border))",
                borderRadius: 8,
              }}
            />
            <Bar dataKey="ic" radius={[4, 4, 0, 0]}>
              {icRows.map((r, i) => (
                <Cell
                  key={i}
                  fill={Math.abs(r.ic) >= IC_GATE ? "#10b981" : "#71717a"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Horizon</TableHead>
            <TableHead className="text-right">IC mean</TableHead>
            <TableHead className="text-right">IC IR</TableHead>
            <TableHead className="text-right">Top–Bottom %</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {icRows.map((r) => (
            <TableRow key={r.period}>
              <TableCell>{r.period}</TableCell>
              <TableCell
                className={`text-right tabular-nums ${Math.abs(r.ic) >= IC_GATE ? "text-emerald-500" : "text-muted-foreground"}`}
              >
                {fmtNumber(r.ic, 4)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {fmtNumber(r.ir, 3)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {fmtNumber(r.spread, 2)}%
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
