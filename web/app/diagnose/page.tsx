"use client";

import { useQuery } from "@tanstack/react-query";
import { Calendar, ChevronRight, Microscope, Tag } from "lucide-react";
import Link from "next/link";

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
import { api, type IcReportSummary } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtRelativeTime } from "@/lib/format";

export default function DiagnosePage() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.icReports.list(50),
    queryFn: () => api.icReports.list(50),
  });

  return (
    <>
      <PageHeader
        title="IC reports"
        description="Per-factor information-coefficient sweeps from scripts.analyzer_ic_report. Each cell = forward-return correlation at one horizon; click a report to inspect the factor×horizon matrix."
      />

      {error ? <ErrorState error={error} /> : null}

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-48 w-full" />
          ))}
        </div>
      ) : (data ?? []).length === 0 ? (
        <EmptyState />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {(data ?? []).map((r) => (
            <ReportCard key={r.slug} report={r} />
          ))}
        </div>
      )}
    </>
  );
}

function ReportCard({ report }: { report: IcReportSummary }) {
  const isRegime = report.regime_split != null;
  return (
    <Link href={`/diagnose/${encodeURIComponent(report.slug)}`}>
      <Card className="hover:border-primary/60 transition-colors h-full">
        <CardHeader className="pb-2">
          <div className="flex items-start gap-2">
            <Microscope className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1">
              <CardTitle className="font-mono text-sm tracking-tight truncate">
                {report.slug.replace(/^analyzer_ic_/, "")}
              </CardTitle>
              <CardDescription className="text-[11px] mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="flex items-center gap-1">
                  <Calendar className="h-3 w-3" />
                  {report.window_start} → {report.window_end}
                </span>
                <span className="flex items-center gap-1">
                  <Tag className="h-3 w-3" />
                  {report.universe}
                </span>
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-3 gap-x-2 gap-y-1 font-mono text-[11px]">
            <dt className="text-muted-foreground">factors</dt>
            <dd className="col-span-2 tabular-nums">{report.n_factors}</dd>
            <dt className="text-muted-foreground">horizons</dt>
            <dd className="col-span-2 text-foreground">
              {(report.horizons ?? []).join(" · ") || "—"}
            </dd>
            <dt className="text-muted-foreground">strategy</dt>
            <dd className="col-span-2 truncate">{report.strategy}</dd>
            <dt className="text-muted-foreground">panel</dt>
            <dd className="col-span-2 tabular-nums">
              {report.panel_rows.toLocaleString()} rows
            </dd>
            <dt className="text-muted-foreground">bonferroni k</dt>
            <dd className="col-span-2 tabular-nums">{report.bonferroni_k}</dd>
          </dl>
          <div className="mt-3 flex items-center justify-between text-[10px] font-mono uppercase tracking-wider">
            {isRegime ? (
              <Badge variant="neutral" className="text-[9px]">
                regime: {report.regime_split} ({(report.regimes ?? []).length})
              </Badge>
            ) : (
              <span />
            )}
            <span className="text-muted-foreground">
              ran {fmtRelativeTime(report.ran_at)}
            </span>
          </div>
          <div className="mt-2 flex items-center gap-1 text-[11px] text-primary">
            open
            <ChevronRight className="h-3 w-3" />
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

function EmptyState() {
  return (
    <div className="border border-border rounded-md bg-card p-12 text-center">
      <Microscope className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
        No IC reports on disk
      </p>
      <p className="mt-2 text-sm text-muted-foreground">
        Reports live at{" "}
        <code className="bg-muted px-1 py-0.5 rounded text-xs">
          reports/analyzer_ic_*.json
        </code>
        . Generate one with{" "}
        <code className="bg-muted px-1 py-0.5 rounded text-xs">
          uv run python -m scripts.analyzer_ic_report
        </code>
        .
      </p>
    </div>
  );
}
