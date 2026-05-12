"use client";

import { useQuery } from "@tanstack/react-query";
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

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type ModelDriftSnapshot, type ModelVersionRow } from "@/lib/api/client";
import { fmtNumber } from "@/lib/format";

function icBadge(ic: number) {
  // Mean Pearson IC is a small number; widen the color bands so the eye
  // catches sign at a glance.
  if (ic > 0.02) return "bg-emerald-500/20 text-emerald-300";
  if (ic < -0.02) return "bg-red-500/20 text-red-300";
  return "bg-muted text-muted-foreground";
}

function driftBadge(snap: ModelDriftSnapshot) {
  if (snap.is_drifting) {
    return (
      <Badge className="bg-red-500/20 text-red-300">
        Drift z={snap.z_score.toFixed(2)}
      </Badge>
    );
  }
  if (snap.z_score < -0.75) {
    return (
      <Badge className="bg-amber-500/20 text-amber-300">
        Watch z={snap.z_score.toFixed(2)}
      </Badge>
    );
  }
  return (
    <Badge className="bg-emerald-500/20 text-emerald-300">
      OK z={snap.z_score.toFixed(2)}
    </Badge>
  );
}

export default function MLModelsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["ml", "models"],
    queryFn: () => api.ml.models({ limit: 50, window_days: 30 }),
    refetchInterval: 60_000,
  });

  return (
    <>
      <PageHeader
        title="ML models"
        description="Registered model versions, walk-forward fold metrics, and rolling-IC drift detection."
      />

      {error ? <ErrorState error={error} /> : null}

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : data ? (() => {
        const latest = data.latest ?? [];
        const models = data.models ?? [];
        const drift = data.drift ?? [];
        return (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Latest per model</CardTitle>
              <CardDescription>
                The version of each model the ensemble would use right now,
                with rolling-IC drift status (30-day window vs training IC).
              </CardDescription>
            </CardHeader>
            <CardContent>
              {latest.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  No models registered yet. Train one with{" "}
                  <code className="bg-muted rounded px-1 py-0.5">
                    python -m scripts.train_model
                  </code>
                  .
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Model</TableHead>
                      <TableHead className="text-right">Version</TableHead>
                      <TableHead className="text-right">Mean IC</TableHead>
                      <TableHead className="text-right">Rank IC</TableHead>
                      <TableHead className="text-right">Hit rate</TableHead>
                      <TableHead className="text-right">Folds</TableHead>
                      <TableHead>Drift</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {latest.map((m) => {
                      const driftEntry = drift.find(
                        (d) =>
                          d.model_name === m.model_name && d.version === m.version,
                      );
                      return (
                        <TableRow key={`${m.model_name}_${m.version}`}>
                          <TableCell className="font-medium">{m.model_name}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            v{m.version}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            <span
                              className={`rounded px-1.5 py-0.5 ${icBadge(
                                m.summary.mean_ic_pearson,
                              )}`}
                            >
                              {fmtNumber(m.summary.mean_ic_pearson, 4)}
                            </span>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtNumber(m.summary.mean_ic_spearman, 4)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtNumber(m.summary.mean_hit_rate * 100, 1)}%
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {Math.round(m.summary.n_folds)}
                          </TableCell>
                          <TableCell>
                            {driftEntry ? driftBadge(driftEntry) : <span className="text-muted-foreground text-xs">—</span>}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {latest.length > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>Per-fold IC</CardTitle>
                <CardDescription>
                  Pearson IC by walk-forward fold for each model — exposes which
                  regimes a model handled vs missed.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-6 md:grid-cols-2">
                  {latest.map((m) => (
                    <FoldChart key={`${m.model_name}_${m.version}`} model={m} />
                  ))}
                </div>
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>All registered runs</CardTitle>
              <CardDescription>
                {models.length} runs, newest first. Drift gate fires when
                rolling IC drops ≥ 1.5σ below the training-fold mean.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {models.length === 0 ? (
                <p className="text-muted-foreground text-sm">No runs yet.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Trained at</TableHead>
                      <TableHead>Model</TableHead>
                      <TableHead className="text-right">v</TableHead>
                      <TableHead className="text-right">Horizon</TableHead>
                      <TableHead className="text-right">Mean IC</TableHead>
                      <TableHead className="text-right">Folds</TableHead>
                      <TableHead>Window</TableHead>
                      <TableHead>Notes</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {models.map((m) => (
                      <TableRow key={m.id}>
                        <TableCell className="tabular-nums">
                          {new Date(m.trained_at).toLocaleString()}
                        </TableCell>
                        <TableCell className="font-medium">{m.model_name}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          v{m.version}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {m.horizon_days}d
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          <span
                            className={`rounded px-1.5 py-0.5 ${icBadge(m.summary.mean_ic_pearson)}`}
                          >
                            {fmtNumber(m.summary.mean_ic_pearson, 4)}
                          </span>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {Math.round(m.summary.n_folds)}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-xs">
                          {m.train_window_start.slice(0, 10)} →{" "}
                          {m.train_window_end.slice(0, 10)}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-xs">
                          {m.notes ?? ""}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
        );
      })() : null}
    </>
  );
}

function FoldChart({ model }: { model: ModelVersionRow }) {
  // Recharts wants serializable values; map folds → bar entries up front.
  const bars = (model.folds ?? []).map((f) => ({
    label: `${f.test_start.slice(5)}`,
    ic: f.ic_pearson,
  }));
  return (
    <div>
      <p className="mb-2 text-sm font-medium">
        {model.model_name} v{model.version}
      </p>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bars}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
            <XAxis dataKey="label" fontSize={10} />
            <YAxis fontSize={10} tickFormatter={(v: number) => v.toFixed(2)} />
            <Tooltip
              contentStyle={{
                background: "hsl(var(--popover))",
                border: "1px solid hsl(var(--border))",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(value) => {
                if (typeof value === "number") return [value.toFixed(4), "IC"];
                return [String(value ?? ""), "IC"];
              }}
            />
            <Bar dataKey="ic" radius={[3, 3, 0, 0]}>
              {bars.map((b, i) => (
                <Cell key={i} fill={b.ic >= 0 ? "#10b981" : "#ef4444"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
