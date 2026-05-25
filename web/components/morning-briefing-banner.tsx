"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle, AlertTriangle, CheckCircle2, CircleDot, Target,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type BriefingResponse, type FactorCoverage } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { cn } from "@/lib/utils";

// ─── status -> style mapping ─────────────────────────────────────────

type GateStatus = BriefingResponse["gate_status"];

function gateBorderClass(s: GateStatus): string {
  if (s === "fail") return "border-bearish/60";
  if (s === "warn") return "border-amber-500/60";
  if (s === "ok") return "border-bullish/40";
  return "border-muted-foreground/40";
}

function gateBadgeVariant(
  s: GateStatus,
): "bearish" | "neutral" | "bullish" | "secondary" {
  if (s === "fail") return "bearish";
  if (s === "warn") return "neutral";
  if (s === "ok") return "bullish";
  return "secondary";
}

function gateLabel(s: GateStatus): string {
  if (s === "fail") return "PRE-TRADE GATE: FAIL";
  if (s === "warn") return "PRE-TRADE GATE: WARN";
  if (s === "ok") return "PRE-TRADE GATE: OK";
  return "NO PICKS TODAY";
}

function GateIcon({ status, className }: { status: GateStatus; className?: string }) {
  if (status === "fail") return <AlertCircle className={className} />;
  if (status === "warn") return <AlertTriangle className={className} />;
  if (status === "ok") return <CheckCircle2 className={className} />;
  return <CircleDot className={className} />;
}

// ─── factor coverage bars ────────────────────────────────────────────

function coverageBarClass(status: FactorCoverage["status"]): string {
  if (status === "fail") return "bg-bearish";
  if (status === "warn") return "bg-amber-500";
  return "bg-bullish";
}

function FactorCoverageRow({ rows }: { rows: FactorCoverage[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-[11px] text-muted-foreground">
        No factor-coverage data (no picks today)
      </p>
    );
  }
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {rows.map((f) => (
        <div key={f.factor} className="space-y-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              {f.factor}
            </span>
            <span
              className={cn(
                "font-mono text-xs tabular-nums",
                f.status === "fail" && "text-bearish",
                f.status === "warn" && "text-amber-500",
                f.status === "ok" && "text-foreground",
              )}
              title={`${f.covered} of ${f.total} picks have a ${f.factor} rank`}
            >
              {f.covered}/{f.total}
            </span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all", coverageBarClass(f.status))}
              style={{ width: `${Math.max(2, Math.round(f.pct * 100))}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── alert chips ─────────────────────────────────────────────────────

function AlertChip({
  icon: Icon, count, label, tone,
}: {
  icon: typeof AlertCircle;
  count: number;
  label: string;
  tone: "bearish" | "bullish" | "amber" | "muted";
}) {
  const toneClass = cn(
    "border rounded px-2 py-1 flex items-center gap-1.5",
    tone === "bearish" && "border-bearish/40 bg-bearish/5 text-bearish",
    tone === "bullish" && "border-bullish/40 bg-bullish/5 text-bullish",
    tone === "amber" && "border-amber-500/40 bg-amber-500/5 text-amber-500",
    tone === "muted" && "border-border text-muted-foreground",
  );
  return (
    <div className={toneClass}>
      <Icon className="h-3.5 w-3.5" />
      <span className="font-mono text-xs font-semibold tabular-nums">{count}</span>
      <span className="text-[10px] uppercase tracking-wider">{label}</span>
    </div>
  );
}

// ─── the banner ──────────────────────────────────────────────────────

export function MorningBriefingBanner() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.dashboard.briefing(),
    queryFn: () => api.dashboard.briefing(),
    // Match the dashboard's existing 5-min cadence.
    refetchInterval: 5 * 60_000,
  });

  if (isLoading) {
    return <Skeleton className="h-40 w-full mb-4" />;
  }

  if (error || !data) {
    // The banner is a "nice to know"; if it fails the rest of the
    // dashboard still loads. Fail soft with a small inline note.
    return (
      <Card className="border-muted-foreground/40 mb-4">
        <CardContent className="py-3 text-xs text-muted-foreground">
          Morning briefing unavailable (
          {error instanceof Error ? error.message : "unknown error"})
        </CardContent>
      </Card>
    );
  }

  // FastAPI's default_factory=list renders as optional in JSON Schema,
  // so openapi-typescript types these as possibly-undefined even though
  // the server always emits arrays. Coerce here to keep the JSX terse.
  const factorCoverage = data.factor_coverage ?? [];
  const positionAlerts = data.position_alerts ?? [];
  const tickerList = positionAlerts.map((a) => a.ticker);

  return (
    <Card className={cn("mb-4 border-2", gateBorderClass(data.gate_status))}>
      <CardContent className="p-4 space-y-3">
        {/* Top: gate chip + recommendation */}
        <div className="flex items-start gap-3 flex-wrap">
          <Badge
            variant={gateBadgeVariant(data.gate_status)}
            className="gap-1.5 text-[10px] uppercase tracking-wider px-2 py-1"
          >
            <GateIcon status={data.gate_status} className="h-3 w-3" />
            {gateLabel(data.gate_status)}
          </Badge>
          <p className="text-xs text-muted-foreground leading-relaxed flex-1 min-w-0">
            <span
              className={cn(
                "font-medium",
                data.gate_status === "fail" && "text-bearish",
                data.gate_status === "warn" && "text-amber-500",
                data.gate_status === "ok" && "text-bullish",
              )}
            >
              {data.gate_message}
            </span>
          </p>
        </div>

        {/* Recommendation row -- the headline action */}
        <p className="text-sm font-medium leading-snug">
          {data.recommendation}
        </p>

        {/* Factor coverage bars */}
        {factorCoverage.length > 0 ? (
          <div className="pt-1">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
              Factor coverage ({data.n_picks} picks)
            </p>
            <FactorCoverageRow rows={factorCoverage} />
          </div>
        ) : null}

        {/* Position alerts row */}
        {positionAlerts.length > 0 ? (
          <div className="pt-1">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
              Position alerts
            </p>
            <div className="flex items-center gap-2 flex-wrap">
              {data.n_stops_hit > 0 ? (
                <AlertChip
                  icon={AlertCircle}
                  count={data.n_stops_hit}
                  label="stops fired"
                  tone="bearish"
                />
              ) : null}
              {data.n_targets_hit > 0 ? (
                <AlertChip
                  icon={Target}
                  count={data.n_targets_hit}
                  label="target hit"
                  tone="bullish"
                />
              ) : null}
              {data.n_near_stop > 0 ? (
                <AlertChip
                  icon={AlertTriangle}
                  count={data.n_near_stop}
                  label="near stop"
                  tone="amber"
                />
              ) : null}
              <span className="text-[10px] font-mono text-muted-foreground ml-1">
                {tickerList.join(" · ")}
              </span>
            </div>
          </div>
        ) : (
          <p className="text-[11px] text-muted-foreground">
            No position alerts ({data.n_positions} held).
          </p>
        )}
      </CardContent>
    </Card>
  );
}
