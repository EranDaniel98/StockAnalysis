"use client";

import { useQuery } from "@tanstack/react-query";
import { Radio, RefreshCw } from "lucide-react";

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
import { fmtNumber, fmtPct, fmtUSD, pnlColorClass } from "@/lib/format";

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
  const liveEquity = data ? data.account.cash + liveLongMarketValue : null;

  return (
    <>
      <PageHeader
        title="Portfolio"
        description="Live Alpaca paper account. Position prices stream from Alpaca's IEX feed."
        actions={
          <div className="flex items-center gap-2">
            <Badge
              variant={connected ? "default" : "secondary"}
              className="gap-1.5"
              title={liveError ?? (connected ? "Streaming" : "Connecting…")}
            >
              <Radio
                className={`h-3 w-3 ${connected ? "animate-pulse" : "opacity-50"}`}
              />
              {connected ? "Live" : "Offline"}
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

      <div className="grid gap-4 md:grid-cols-4">
        <SummaryCard
          label="Equity"
          value={fmtUSD(liveEquity ?? data?.account.equity)}
          isLoading={isLoading}
        />
        <SummaryCard
          label="Cash"
          value={fmtUSD(data?.account.cash)}
          isLoading={isLoading}
        />
        <SummaryCard
          label="Buying power"
          value={fmtUSD(data?.account.buying_power)}
          isLoading={isLoading}
        />
        <SummaryCard
          label="Long market value"
          value={fmtUSD(
            data ? liveLongMarketValue : null,
          )}
          isLoading={isLoading}
        />
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Positions</CardTitle>
          <CardDescription>
            {data
              ? `${data.n_positions} open ${data.n_positions === 1 ? "position" : "positions"}`
              : "Loading positions…"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !data || livePositions.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              No open positions.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead className="text-right">Shares</TableHead>
                  <TableHead className="text-right">Avg cost</TableHead>
                  <TableHead className="text-right">Current</TableHead>
                  <TableHead className="text-right">Market value</TableHead>
                  <TableHead className="text-right">P&amp;L</TableHead>
                  <TableHead className="text-right">P&amp;L %</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {livePositions.map((p) => {
                  const isLive = prices[p.ticker] !== undefined;
                  return (
                    <TableRow key={p.ticker}>
                      <TableCell>
                        <Badge variant="outline" className="font-mono">
                          {p.ticker}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtNumber(p.shares, 0)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtUSD(p.avg_price)}
                      </TableCell>
                      <TableCell
                        className={`text-right tabular-nums ${isLive ? "text-emerald-400" : ""}`}
                        title={isLive ? "Live tick" : "Last poll"}
                      >
                        {fmtUSD(p.current_price)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtUSD(p.market_value)}
                      </TableCell>
                      <TableCell
                        className={`text-right tabular-nums ${pnlColorClass(p.unrealized_pnl)}`}
                      >
                        {fmtUSD(p.unrealized_pnl)}
                      </TableCell>
                      <TableCell
                        className={`text-right tabular-nums ${pnlColorClass(p.unrealized_pnl_pct)}`}
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

function SummaryCard({
  label,
  value,
  isLoading,
}: {
  label: string;
  value: string;
  isLoading: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <div className="text-2xl font-semibold tabular-nums">{value}</div>
        )}
      </CardContent>
    </Card>
  );
}
