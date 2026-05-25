"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Calendar,
  CheckCircle2,
  ExternalLink,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  type TodayActionItem,
  type TodayActionsResponse,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtNumber, fmtPct, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

// ─── helpers ────────────────────────────────────────────────────────────────

function pnlTone(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "text-foreground";
  if (n > 0) return "text-bullish";
  if (n < 0) return "text-bearish";
  return "text-muted-foreground";
}

function sanityClass(v: TodayActionItem["sanity_verdict"]): string {
  if (v === "VETO") return "border-bearish/40 bg-bearish/10 text-bearish";
  if (v === "FLAG") return "border-amber-500/40 bg-amber-500/10 text-amber-500";
  if (v === "KEEP") return "border-bullish/40 bg-bullish/10 text-bullish";
  return "border-border text-muted-foreground";
}

function statusClass(s: TodayActionItem["position_status"]): string {
  if (s === "STOP_HIT") return "border-bearish/40 bg-bearish/10 text-bearish";
  if (s === "NEAR_STOP") return "border-amber-500/40 bg-amber-500/10 text-amber-500";
  if (s === "TARGET_HIT") return "border-bullish/40 bg-bullish/10 text-bullish";
  if (s === "NEAR_TARGET") return "border-emerald-500/40 bg-emerald-500/10 text-emerald-500";
  return "border-border text-muted-foreground";
}

function earningsBadge(days: number | null | undefined) {
  if (days == null || days < 0 || days > 14) return null;
  const tone =
    days <= 5 ? "border-bearish/40 bg-bearish/10 text-bearish"
    : "border-amber-500/40 bg-amber-500/10 text-amber-500";
  const label =
    days === 0 ? "earnings today"
    : days === 1 ? "earnings tomorrow"
    : `earnings in ${days}d`;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wider",
        tone,
      )}
    >
      <Calendar className="h-3 w-3" />
      {label}
    </span>
  );
}

function TickerLink({ ticker }: { ticker: string }) {
  const tvHref = `https://www.tradingview.com/symbols/${encodeURIComponent(ticker)}/`;
  return (
    <div className="flex items-center gap-1.5">
      <Link
        href={`/stocks/${encodeURIComponent(ticker)}`}
        className="font-mono font-semibold text-foreground hover:text-primary"
      >
        {ticker}
      </Link>
      <a
        href={tvHref}
        target="_blank"
        rel="noopener noreferrer"
        className="text-muted-foreground/60 hover:text-primary transition-colors"
        title={`Open ${ticker} chart on TradingView`}
      >
        <ExternalLink className="h-3 w-3" />
      </a>
    </div>
  );
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function BuySignalsPage() {
  const qc = useQueryClient();
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: qk.pipeline.todayActions(),
    queryFn: () => api.pipeline.todayActions(),
    refetchInterval: 60_000,
  });

  return (
    <>
      <PageHeader
        title="Today's actions"
        description="What to actually click in Alpaca right now. Sourced from today's picks + portfolio_analysis + AI sanity check + live positions."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              refetch();
              qc.invalidateQueries({ queryKey: qk.pipeline.all });
            }}
            disabled={isFetching}
          >
            <RefreshCw
              className={cn("mr-2 h-4 w-4", isFetching && "animate-spin")}
            />
            Refresh
          </Button>
        }
      />

      {error ? <ErrorState error={error} /> : null}

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="EXIT"
          value={isLoading ? "—" : String(data?.exits?.length ?? 0)}
          sub={
            (data?.exits?.length ?? 0) > 0
              ? "sells to execute"
              : "nothing to sell"
          }
          subTone={(data?.exits?.length ?? 0) > 0 ? "bearish" : "muted"}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="NEW BUY"
          value={isLoading ? "—" : String(data?.new_buys?.length ?? 0)}
          sub={
            (data?.new_buys?.length ?? 0) > 0
              ? "buys to execute"
              : "no new entries"
          }
          subTone={(data?.new_buys?.length ?? 0) > 0 ? "bullish" : "muted"}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="KEEP"
          tooltip="Currently held AND in today's basket — no action needed, just monitor stops/targets."
          value={isLoading ? "—" : String(data?.keeps?.length ?? 0)}
          sub={
            (data?.keeps?.length ?? 0) > 0
              ? "held & still in basket"
              : "—"
          }
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Sanity flagged"
          tooltip="Picks the AI sanity check returned FLAG or VETO for. Advisory only — does not block execution."
          value={
            isLoading ? "—" : (
              <span className={cn(
                (data?.n_sanity_flagged ?? 0) > 0 ? "text-amber-500" : "text-foreground",
              )}>
                {data?.n_sanity_flagged ?? 0}
              </span>
            )
          }
          sub={
            data?.sources?.sanity
              ? `from ${data.sources.sanity}`
              : "no sanity check run today"
          }
          subTone={(data?.n_sanity_flagged ?? 0) > 0 ? "neutral" : "muted"}
          isLoading={isLoading}
        />
      </div>

      {data && data.n_at_risk > 0 ? (
        <AtRiskCallout
          items={[...(data.keeps ?? []), ...(data.exits ?? [])].filter(
            (r) => r.position_status && r.position_status !== "HOLDING",
          )}
        />
      ) : null}

      {/* Source line — tells the user exactly what files were consulted. */}
      {data ? (
        <p className="mt-3 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
          picks: {data.sources?.picks ?? "(none)"} ·
          analysis: {data.sources?.analysis ?? "(none)"} ·
          sanity: {data.sources?.sanity ?? "(none)"}
        </p>
      ) : null}

      {isLoading ? (
        <div className="mt-4 space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      ) : data ? (() => {
        // openapi-typescript marks default_factory lists nullable;
        // coalesce here so the rest of the JSX treats them as concrete
        // arrays without a sprinkle of `?? []` at every callsite.
        const exits = data.exits ?? [];
        const newBuys = data.new_buys ?? [];
        const keeps = data.keeps ?? [];
        const empty = exits.length === 0 && newBuys.length === 0 && keeps.length === 0;
        return (
          <>
            {exits.length > 0 ? <ExitsCard items={exits} /> : null}
            {newBuys.length > 0 ? <NewBuysCard items={newBuys} /> : null}
            {keeps.length > 0 ? <KeepsCard items={keeps} /> : null}
            {empty ? <EmptyState response={data} /> : null}
          </>
        );
      })() : null}
    </>
  );
}

// ─── At-risk callout ───────────────────────────────────────────────────────

function AtRiskCallout({ items }: { items: TodayActionItem[] }) {
  return (
    <div className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="h-4 w-4 text-amber-500" />
        <p className="text-sm font-medium text-amber-500">
          {items.length} {items.length === 1 ? "position" : "positions"} need
          attention
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {items.map((it) => (
          <div
            key={it.ticker}
            className="flex items-center gap-1.5 rounded border border-border bg-background/60 px-2 py-1"
          >
            <span className="font-mono text-sm font-semibold">{it.ticker}</span>
            <Badge
              variant="outline"
              className={cn(
                "text-[9px] font-mono uppercase tracking-wider px-1.5",
                statusClass(it.position_status),
              )}
            >
              {it.position_status}
            </Badge>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── EXITS card ────────────────────────────────────────────────────────────

function ExitsCard({ items }: { items: TodayActionItem[] }) {
  return (
    <SectionCard
      title="EXIT"
      subtitle="Held positions that dropped out of today's basket — sell to rebalance."
      tone="bearish"
      icon={<ArrowDownRight className="h-4 w-4 text-bearish" />}
      count={items.length}
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Ticker</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Shares to sell</TableHead>
            <TableHead className="text-right">Current</TableHead>
            <TableHead className="text-right">Mkt value</TableHead>
            <TableHead className="text-right">Unrl P&amp;L</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((it) => (
            <TableRow key={it.ticker} mono>
              <TableCell>
                <TickerLink ticker={it.ticker} />
              </TableCell>
              <TableCell>
                {it.position_status ? (
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-[10px] font-mono uppercase tracking-wider",
                      statusClass(it.position_status),
                    )}
                  >
                    {it.position_status}
                  </Badge>
                ) : (
                  <span className="text-muted-foreground/60 text-[10px]">—</span>
                )}
              </TableCell>
              <TableCell className="text-right font-mono tabular-nums">
                {it.current_shares != null ? fmtNumber(it.current_shares, 0) : "—"}
              </TableCell>
              <TableCell className="text-right">
                {it.current_price != null ? fmtUSD(it.current_price) : "—"}
              </TableCell>
              <TableCell className="text-right">
                {it.market_value != null ? fmtUSD(it.market_value) : "—"}
              </TableCell>
              <TableCell className={cn("text-right", pnlTone(it.unrealized_pnl_usd))}>
                {it.unrealized_pnl_usd != null ? (
                  <>
                    {fmtUSD(it.unrealized_pnl_usd)}{" "}
                    <span className="text-[10px] opacity-70">
                      ({fmtPct(it.unrealized_pnl_pct, 2, true)})
                    </span>
                  </>
                ) : "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </SectionCard>
  );
}

// ─── NEW BUYS card ─────────────────────────────────────────────────────────

function NewBuysCard({ items }: { items: TodayActionItem[] }) {
  return (
    <SectionCard
      title="NEW BUY"
      subtitle="In today's basket, not currently held — fresh entries."
      tone="bullish"
      icon={<ArrowUpRight className="h-4 w-4 text-bullish" />}
      count={items.length}
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Ticker</TableHead>
            <TableHead className="text-right">z</TableHead>
            <TableHead className="text-right">Entry</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Sizing</TableHead>
            <TableHead className="text-right">Stop</TableHead>
            <TableHead className="text-right">Target</TableHead>
            <TableHead className="text-right">Exp ret</TableHead>
            <TableHead>AI</TableHead>
            <TableHead>Flags</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((it) => (
            <TableRow key={it.ticker} mono>
              <TableCell>
                <TickerLink ticker={it.ticker} />
                {it.rationale ? (
                  <details className="mt-1 text-[10px] text-muted-foreground">
                    <summary className="cursor-pointer hover:text-foreground">
                      rationale
                    </summary>
                    <p className="mt-1 max-w-[40ch] leading-relaxed">
                      {it.rationale}
                    </p>
                  </details>
                ) : null}
              </TableCell>
              <TableCell
                className={cn(
                  "text-right font-mono tabular-nums",
                  (it.composite_z ?? 0) >= 2.0 && "text-bullish",
                )}
              >
                {it.composite_z != null ? `+${it.composite_z.toFixed(2)}` : "—"}
              </TableCell>
              <TableCell className="text-right">
                {it.entry_price != null ? fmtUSD(it.entry_price) : "—"}
              </TableCell>
              <TableCell className="text-right font-mono tabular-nums">
                {it.target_shares ?? "—"}
              </TableCell>
              <TableCell className="text-right">
                {it.position_size_usd != null ? fmtUSD(it.position_size_usd, true) : "—"}
              </TableCell>
              <TableCell className="text-right text-bearish">
                {it.stop_loss != null ? fmtUSD(it.stop_loss) : "—"}
              </TableCell>
              <TableCell className="text-right text-bullish">
                {it.target != null ? fmtUSD(it.target) : "—"}
              </TableCell>
              <TableCell className="text-right">
                {it.expected_return_pct != null ? fmtPct(it.expected_return_pct, 1, true) : "—"}
              </TableCell>
              <TableCell>
                <SanityBadgeInline item={it} />
              </TableCell>
              <TableCell>
                {earningsBadge(it.days_to_earnings)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </SectionCard>
  );
}

// ─── KEEPS card ────────────────────────────────────────────────────────────

function KeepsCard({ items }: { items: TodayActionItem[] }) {
  return (
    <SectionCard
      title="KEEP"
      subtitle="Held AND in today's basket — no action, just monitor."
      tone="muted"
      icon={<CheckCircle2 className="h-4 w-4 text-muted-foreground" />}
      count={items.length}
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Ticker</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Shares</TableHead>
            <TableHead className="text-right">Current</TableHead>
            <TableHead className="text-right">Stop</TableHead>
            <TableHead className="text-right">Target</TableHead>
            <TableHead className="text-right">Unrl P&amp;L</TableHead>
            <TableHead>AI</TableHead>
            <TableHead>Flags</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((it) => (
            <TableRow key={it.ticker} mono>
              <TableCell>
                <TickerLink ticker={it.ticker} />
              </TableCell>
              <TableCell>
                {it.position_status ? (
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-[10px] font-mono uppercase tracking-wider",
                      statusClass(it.position_status),
                    )}
                  >
                    {it.position_status}
                  </Badge>
                ) : (
                  <span className="text-muted-foreground/60 text-[10px]">—</span>
                )}
              </TableCell>
              <TableCell className="text-right font-mono tabular-nums">
                {it.current_shares != null ? fmtNumber(it.current_shares, 0) : "—"}
              </TableCell>
              <TableCell className="text-right">
                {it.current_price != null ? fmtUSD(it.current_price) : "—"}
              </TableCell>
              <TableCell className="text-right text-bearish">
                {it.stop_loss != null ? fmtUSD(it.stop_loss) : "—"}
              </TableCell>
              <TableCell className="text-right text-bullish">
                {it.target != null ? fmtUSD(it.target) : "—"}
              </TableCell>
              <TableCell className={cn("text-right", pnlTone(it.unrealized_pnl_usd))}>
                {it.unrealized_pnl_usd != null ? (
                  <>
                    {fmtUSD(it.unrealized_pnl_usd)}{" "}
                    <span className="text-[10px] opacity-70">
                      ({fmtPct(it.unrealized_pnl_pct, 2, true)})
                    </span>
                  </>
                ) : "—"}
              </TableCell>
              <TableCell>
                <SanityBadgeInline item={it} />
              </TableCell>
              <TableCell>
                {earningsBadge(it.days_to_earnings)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </SectionCard>
  );
}

// ─── Section card wrapper ──────────────────────────────────────────────────

function SectionCard({
  title, subtitle, tone, icon, count, children,
}: {
  title: string;
  subtitle: string;
  tone: "bullish" | "bearish" | "muted";
  icon: React.ReactNode;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-4 border border-border rounded-md bg-card overflow-hidden">
      <div
        className={cn(
          "flex items-center gap-2 px-3 py-2 border-b border-border",
          tone === "bearish" && "bg-bearish/5",
          tone === "bullish" && "bg-bullish/5",
        )}
      >
        {icon}
        <h2 className="font-mono text-xs tracking-wider uppercase font-semibold">
          {title}
        </h2>
        <span className="text-muted-foreground text-[10px] font-mono">
          ({count})
        </span>
        <span className="text-muted-foreground text-[11px] ml-3">
          {subtitle}
        </span>
      </div>
      <div>{children}</div>
    </div>
  );
}

function SanityBadgeInline({ item }: { item: TodayActionItem }) {
  if (!item.sanity_verdict) {
    return <span className="text-muted-foreground/40 text-[10px]">—</span>;
  }
  const title = [
    `${item.sanity_verdict} (${item.sanity_reason ?? "—"})`,
    item.sanity_evidence ?? "",
  ].filter(Boolean).join("\n\n");
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-[9px] font-mono uppercase tracking-wider cursor-help",
        sanityClass(item.sanity_verdict),
      )}
      title={title}
    >
      {item.sanity_verdict}
    </Badge>
  );
}

function EmptyState({ response }: { response: TodayActionsResponse }) {
  return (
    <div className="mt-4 border border-border rounded-md bg-card p-8 text-center">
      <AlertCircle className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
      <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
        No actions today
      </p>
      <p className="mt-2 text-sm text-muted-foreground">
        Basket fully aligned with current positions, or the daily pipeline
        hasn&apos;t run yet ({response.n_picks_today} picks ·{" "}
        {response.n_positions} positions).
      </p>
      <Link
        href="/scan"
        className="mt-3 inline-block text-primary text-sm hover:underline"
      >
        Run the daily pipeline →
      </Link>
    </div>
  );
}
