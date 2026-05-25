"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ExternalLink,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { use } from "react";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
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
  api,
  type ExecutionDetail,
  type FailedOrder,
  type SkippedOrder,
  type SubmittedOrder,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtNumber, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

type Params = { params: Promise<{ date: string }> };

export default function ExecutionDetailPage({ params }: Params) {
  const { date } = use(params);
  const { data, isLoading, error } = useQuery({
    queryKey: qk.executions.detail(date),
    queryFn: () => api.executions.get(date),
  });

  return (
    <>
      <PageHeader
        title={data ? `Execution · ${data.date}` : isLoading ? "Loading…" : "Execution"}
        description={
          data
            ? `${data.strategy}${data.long_short_mode ? " · long/short" : " · long-only"} · ${(data.submitted ?? []).length} submitted · ${(data.skipped ?? []).length} skipped · ${(data.failed ?? []).length} failed`
            : "Per-day paper-trade execution"
        }
        actions={
          <Link
            href="/recommendations"
            className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          >
            <ChevronLeft className="h-3 w-3" /> Back to log
          </Link>
        }
      />

      {error ? <ErrorState error={error} /> : null}
      {isLoading || !data ? (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 w-full" />
            ))}
          </div>
          <Skeleton className="h-72 w-full" />
        </div>
      ) : (
        <DetailBody data={data} />
      )}
    </>
  );
}

function DetailBody({ data }: { data: ExecutionDetail }) {
  const submitted = data.submitted ?? [];
  const skipped = data.skipped ?? [];
  const failed = data.failed ?? [];
  const sanity = data.sanity_gate ?? null;

  return (
    <>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="Equity at start"
          value={
            data.equity_at_start != null ? (
              <span className="font-mono">{fmtUSD(data.equity_at_start)}</span>
            ) : "—"
          }
          sub={
            data.long_capital != null && data.short_capital != null
              ? `${fmtUSD(data.long_capital, true)} long / ${fmtUSD(data.short_capital, true)} short`
              : undefined
          }
          subTone="muted"
        />
        <ScoreboardTile
          label="Basket size"
          value={
            <span className="font-mono">
              <span className="text-bullish">{data.n_longs}L</span>
              {data.n_shorts > 0 ? (
                <>
                  <span className="text-muted-foreground/40"> / </span>
                  <span className="text-bearish">{data.n_shorts}S</span>
                </>
              ) : null}
            </span>
          }
          sub={data.order_style ? `${data.order_style} orders` : undefined}
          subTone="muted"
        />
        <ScoreboardTile
          label="Orders"
          value={
            <span className="font-mono">
              <span className="text-bullish">{submitted.length}</span>
              <span className="text-muted-foreground/40 mx-1">·</span>
              <span className="text-muted-foreground">{skipped.length}</span>
              <span className="text-muted-foreground/40 mx-1">·</span>
              <span className={cn(failed.length > 0 ? "text-bearish" : "text-muted-foreground")}>
                {failed.length}
              </span>
            </span>
          }
          sub="submitted · skipped · failed"
          subTone="muted"
        />
        <ScoreboardTile
          label="Sanity gate"
          tooltip="AI sanity check decisions captured at execution time. Kept = passed; Rejected/Cautioned = the AI flagged."
          value={
            sanity?.applied ? (
              <span className="font-mono">
                <span className="text-bullish">{sanity.long_kept?.length ?? 0}</span>
                {(sanity.long_rejected?.length ?? 0) > 0 ? (
                  <>
                    <span className="text-muted-foreground/40 mx-1">/</span>
                    <span className="text-bearish">
                      {sanity.long_rejected?.length ?? 0}
                    </span>
                  </>
                ) : null}
              </span>
            ) : (
              <span className="text-muted-foreground text-base">off</span>
            )
          }
          sub={
            sanity?.applied
              ? `mode: ${sanity.mode ?? "—"} · ${sanity.long_cautioned?.length ?? 0} cautioned`
              : "no sanity check this run"
          }
          subTone={sanity?.applied ? "neutral" : "muted"}
        />
      </div>

      {submitted.length > 0 ? <SubmittedCard orders={submitted} /> : null}
      {failed.length > 0 ? <FailedCard orders={failed} /> : null}
      {skipped.length > 0 ? <SkippedCard orders={skipped} /> : null}
      {sanity && (sanity.long_outcomes && Object.keys(sanity.long_outcomes).length > 0) ? (
        <SanityCard sanity={sanity} />
      ) : null}
    </>
  );
}

// ─── Submitted orders ─────────────────────────────────────────────────────

function SubmittedCard({ orders }: { orders: SubmittedOrder[] }) {
  return (
    <Section
      title="Submitted"
      tone="bullish"
      icon={<CheckCircle2 className="h-4 w-4 text-bullish" />}
      count={orders.length}
      subtitle="Orders that landed at the broker."
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Ticker</TableHead>
            <TableHead>Side</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Stop</TableHead>
            <TableHead className="text-right">Target</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Order id</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {orders.map((o) => (
            <TableRow key={o.order_id ?? o.client_order_id ?? o.ticker} mono>
              <TableCell>
                <TickerLink ticker={o.ticker} />
              </TableCell>
              <TableCell>
                <SideBadge side={o.side ?? null} />
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {o.qty != null ? fmtNumber(o.qty, 0) : "—"}
              </TableCell>
              <TableCell className="text-right text-bearish">
                {o.stop_loss != null ? fmtUSD(o.stop_loss) : "—"}
              </TableCell>
              <TableCell className="text-right text-bullish">
                {o.take_profit != null ? fmtUSD(o.take_profit) : "—"}
              </TableCell>
              <TableCell className="text-[11px]">
                {o.status ? (
                  <span className="font-mono text-muted-foreground tracking-wider">
                    {o.status.replace("OrderStatus.", "")}
                  </span>
                ) : "—"}
              </TableCell>
              <TableCell className="text-[10px] text-muted-foreground/70 font-mono truncate max-w-[180px]"
                title={o.client_order_id ?? o.order_id ?? ""}>
                {o.client_order_id ?? o.order_id ?? "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  );
}

// ─── Failed orders ────────────────────────────────────────────────────────

function FailedCard({ orders }: { orders: FailedOrder[] }) {
  return (
    <Section
      title="Failed"
      tone="bearish"
      icon={<XCircle className="h-4 w-4 text-bearish" />}
      count={orders.length}
      subtitle="Broker rejected these — error details below."
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Ticker</TableHead>
            <TableHead>Side</TableHead>
            <TableHead>Error</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {orders.map((o, i) => (
            <TableRow key={`${o.ticker}-${i}`} mono>
              <TableCell>
                <TickerLink ticker={o.ticker} />
              </TableCell>
              <TableCell>
                <SideBadge side={o.side ?? null} />
              </TableCell>
              <TableCell className="text-[11px] text-muted-foreground font-mono break-all">
                {o.error ?? "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  );
}

// ─── Skipped orders ───────────────────────────────────────────────────────

function SkippedCard({ orders }: { orders: SkippedOrder[] }) {
  return (
    <Section
      title="Skipped"
      tone="neutral"
      icon={<AlertTriangle className="h-4 w-4 text-amber-500" />}
      count={orders.length}
      subtitle="Not submitted — sanity gate or size filter."
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Ticker</TableHead>
            <TableHead>Side</TableHead>
            <TableHead>Reason</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {orders.map((o, i) => (
            <TableRow key={`${o.ticker}-${i}`} mono>
              <TableCell>
                <TickerLink ticker={o.ticker} />
              </TableCell>
              <TableCell>
                <SideBadge side={o.side ?? null} />
              </TableCell>
              <TableCell className="text-[11px] text-muted-foreground">
                {o.reason ?? "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  );
}

// ─── Sanity outcomes ──────────────────────────────────────────────────────

function SanityCard({
  sanity,
}: {
  sanity: NonNullable<ExecutionDetail["sanity_gate"]>;
}) {
  const longRows = Object.entries(sanity.long_outcomes ?? {});
  return (
    <Section
      title="AI sanity verdicts"
      tone="muted"
      icon={<CheckCircle2 className="h-4 w-4 text-muted-foreground" />}
      count={longRows.length}
      subtitle={`Mode: ${sanity.mode ?? "—"} · Long: ${sanity.long_kept?.length ?? 0} kept / ${sanity.long_rejected?.length ?? 0} rejected / ${sanity.long_cautioned?.length ?? 0} cautioned`}
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Ticker</TableHead>
            <TableHead>Verdict</TableHead>
            <TableHead className="text-right">Confidence</TableHead>
            <TableHead>Reason</TableHead>
            <TableHead>Model</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {longRows.map(([ticker, row]) => (
            <TableRow key={ticker} mono>
              <TableCell>
                <TickerLink ticker={ticker} />
              </TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className={cn(
                    "text-[9px] font-mono uppercase tracking-wider",
                    row.verdict === "REJECT" && "border-bearish/40 bg-bearish/10 text-bearish",
                    row.verdict === "CAUTION" && "border-amber-500/40 bg-amber-500/10 text-amber-500",
                    (row.verdict === "OK" || row.verdict === "KEEP") && "border-bullish/40 bg-bullish/10 text-bullish",
                  )}
                >
                  {row.verdict ?? "—"}
                </Badge>
              </TableCell>
              <TableCell className="text-right text-[11px] tabular-nums">
                {row.confidence != null
                  ? `${(row.confidence * 100).toFixed(0)}%`
                  : "—"}
              </TableCell>
              <TableCell className="text-[11px] text-muted-foreground max-w-[40ch]">
                {row.reason ?? "—"}
              </TableCell>
              <TableCell className="text-[10px] text-muted-foreground/70 font-mono">
                {row.model ?? "—"}
                {row.mocked ? <span className="ml-1 opacity-60">(mock)</span> : null}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  );
}

// ─── shared bits ──────────────────────────────────────────────────────────

function Section({
  title, tone, icon, count, subtitle, children,
}: {
  title: string;
  tone: "bullish" | "bearish" | "neutral" | "muted";
  icon: React.ReactNode;
  count: number;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-4 border border-border rounded-md bg-card overflow-hidden">
      <div
        className={cn(
          "flex items-center gap-2 px-3 py-2 border-b border-border",
          tone === "bullish" && "bg-bullish/5",
          tone === "bearish" && "bg-bearish/5",
          tone === "neutral" && "bg-amber-500/5",
        )}
      >
        {icon}
        <h2 className="font-mono text-xs tracking-wider uppercase font-semibold">
          {title}
        </h2>
        <span className="text-muted-foreground text-[10px] font-mono">
          ({count})
        </span>
        <span className="text-muted-foreground text-[11px] ml-3">{subtitle}</span>
      </div>
      <div>{children}</div>
    </div>
  );
}

function TickerLink({ ticker }: { ticker: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <Link
        href={`/stocks/${encodeURIComponent(ticker)}`}
        className="font-mono font-semibold text-foreground hover:text-primary"
      >
        {ticker}
      </Link>
      <a
        href={`https://www.tradingview.com/symbols/${encodeURIComponent(ticker)}/`}
        target="_blank"
        rel="noopener noreferrer"
        className="text-muted-foreground/60 hover:text-primary"
        title={`Open ${ticker} chart on TradingView`}
      >
        <ExternalLink className="h-3 w-3" />
      </a>
    </div>
  );
}

function SideBadge({ side }: { side: string | null }) {
  if (!side) return <span className="text-muted-foreground/40 text-[10px]">—</span>;
  const isLong = side.includes("long");
  const isClose = side === "close";
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-[9px] font-mono uppercase tracking-wider",
        isLong && "border-bullish/40 text-bullish",
        !isLong && !isClose && "border-bearish/40 text-bearish",
        isClose && "border-muted-foreground/40 text-muted-foreground",
      )}
    >
      {side.replace("open_", "").replace("_bracket", "")}
    </Badge>
  );
}
