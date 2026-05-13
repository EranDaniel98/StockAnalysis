"use client";

import { useQuery } from "@tanstack/react-query";
import { Radio, RefreshCw } from "lucide-react";

import { EquitySparkline } from "@/components/equity-sparkline";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type Position } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { useLivePrices, type LivePriceMap } from "@/lib/api/use-live-prices";
import { fmtNumber, fmtPct, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Local tone helper bound to the new bullish/bearish tokens. */
function toneClass(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "text-foreground";
  if (n > 0) return "text-bullish";
  if (n < 0) return "text-bearish";
  return "text-muted-foreground";
}

function toneFor(
  n: number | null | undefined,
): "bullish" | "bearish" | "neutral" | "muted" {
  if (n === null || n === undefined || Number.isNaN(n)) return "muted";
  if (n > 0) return "bullish";
  if (n < 0) return "bearish";
  return "neutral";
}

function applyLivePrice(p: Position, live: LivePriceMap): Position {
  const tick = live[p.ticker];
  if (!tick || !p.shares) return p;
  const market_value = tick.price * p.shares;
  const cost_basis = p.avg_price * p.shares;
  const unrealized_pnl = market_value - cost_basis;
  const unrealized_pnl_pct = cost_basis > 0 ? (unrealized_pnl / cost_basis) * 100 : 0;
  return {
    ...p,
    current_price: tick.price,
    market_value,
    unrealized_pnl,
    unrealized_pnl_pct,
  };
}

export default function PortfolioPage() {
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: qk.portfolio.status(),
    queryFn: () => api.portfolio.status(),
    refetchInterval: 60_000,
  });

  const symbols = data?.positions.map((p) => p.ticker) ?? [];
  const { prices, connected, error: liveError } = useLivePrices(symbols);

  const livePositions = (data?.positions ?? []).map((p) => applyLivePrice(p, prices));
  const liveLongMarketValue = livePositions.reduce(
    (sum, p) => sum + (p.market_value ?? 0),
    0,
  );
  const liveCostBasis = livePositions.reduce(
    (sum, p) => sum + p.avg_price * p.shares,
    0,
  );
  const liveUnrealizedPnl = liveLongMarketValue - liveCostBasis;
  const liveUnrealizedPnlPct =
    liveCostBasis > 0 ? (liveUnrealizedPnl / liveCostBasis) * 100 : 0;
  const liveEquity = data ? data.account.cash + liveLongMarketValue : null;

  return (
    <>
      <PageHeader
        title="Portfolio"
        description="Live Alpaca paper account. Position prices stream from Alpaca's IEX feed."
        actions={
          <div className="flex items-center gap-2">
            <Badge
              variant={connected ? "bullish" : "neutral"}
              className="gap-1.5"
              title={liveError ?? (connected ? "Streaming" : "Connecting…")}
            >
              <Radio
                className={`h-3 w-3 ${connected ? "animate-pulse" : "opacity-50"}`}
              />
              {connected ? "LIVE" : "OFFLINE"}
            </Badge>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              disabled={isFetching}
            >
              <RefreshCw
                className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`}
              />
              Refresh
            </Button>
          </div>
        }
      />

      {error ? <ErrorState error={error} /> : null}

      {/* Bloomberg scoreboard strip: 4 tiles, equity has an inline sparkline. */}
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <ScoreboardTile
          label="Total Equity"
          value={fmtUSD(liveEquity ?? data?.account.equity)}
          isLoading={isLoading}
          trailing={
            <EquitySparkline
              equity={liveEquity ?? data?.account.equity ?? null}
              variant="inline"
            />
          }
        />
        <ScoreboardTile
          label="Unrealized P&L"
          value={
            <span className={cn(toneClass(liveUnrealizedPnl))}>
              {fmtUSD(liveUnrealizedPnl)}
            </span>
          }
          sub={
            data
              ? `${liveUnrealizedPnlPct >= 0 ? "+" : ""}${liveUnrealizedPnlPct.toFixed(2)}% on ${fmtUSD(liveCostBasis)} cost`
              : undefined
          }
          subTone={toneFor(liveUnrealizedPnl)}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Open Positions"
          value={data ? String(data.n_positions) : "—"}
          sub={
            data
              ? `${fmtUSD(liveLongMarketValue, true)} long market value`
              : undefined
          }
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Cash / Buying Power"
          value={fmtUSD(data?.account.cash)}
          sub={
            data ? `${fmtUSD(data.account.buying_power)} buying power` : undefined
          }
          subTone="muted"
          isLoading={isLoading}
        />
      </div>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>Positions</CardTitle>
          <CardDescription>
            {data
              ? `${data.n_positions} open ${data.n_positions === 1 ? "position" : "positions"} ${connected ? "· streaming" : "· last poll"}`
              : "Loading positions…"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2 py-1">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-7 w-full" />
              ))}
            </div>
          ) : !data || livePositions.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-xs">
              No open positions.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead className="text-right">Shares</TableHead>
                  <TableHead className="text-right">Avg Cost</TableHead>
                  <TableHead className="text-right">Mark</TableHead>
                  <TableHead className="text-right">Mkt Value</TableHead>
                  <TableHead className="text-right">Unrl P&amp;L $</TableHead>
                  <TableHead className="text-right">Unrl P&amp;L %</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {livePositions.map((p) => {
                  const isLive = prices[p.ticker] !== undefined;
                  return (
                    <TableRow key={p.ticker} mono>
                      <TableCell>
                        <span className="font-mono text-foreground">
                          {p.ticker}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        {fmtNumber(p.shares, 0)}
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground">
                        {fmtUSD(p.avg_price)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right",
                          isLive ? "text-bullish" : "text-foreground",
                        )}
                        title={isLive ? "Live tick" : "Last poll"}
                      >
                        {fmtUSD(p.current_price)}
                      </TableCell>
                      <TableCell className="text-right">
                        {fmtUSD(p.market_value)}
                      </TableCell>
                      <TableCell
                        className={cn("text-right", toneClass(p.unrealized_pnl))}
                      >
                        {fmtUSD(p.unrealized_pnl)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "text-right",
                          toneClass(p.unrealized_pnl_pct),
                        )}
                      >
                        {fmtPct(p.unrealized_pnl_pct, 2, true)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}
