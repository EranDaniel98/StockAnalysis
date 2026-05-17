import Link from "next/link";

import { EdgeUncertaintyBanner } from "@/components/edge-uncertainty-banner";
import { PageHeader } from "@/components/page-header";
import { PaperVsSpyCard } from "@/components/paper-vs-spy-card";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  findLatestPicksDate,
  loadAnalysis,
  loadPaperVsSpy,
  loadPicks,
  sectorCounts,
} from "@/lib/factors/data";
import { fmtPct, fmtUSD } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function FactorsPage() {
  const latestDate = await findLatestPicksDate();
  if (!latestDate) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Factor strategy"
          description="Daily picks from the composite momentum + quality + value factor."
        />
        <Card>
          <CardContent className="py-8">
            <p className="text-muted-foreground">
              No picks generated yet. Run{" "}
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                uv run python -m scripts.run_daily_pipeline
              </code>{" "}
              to create today&apos;s picks.
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const [picks, analysis, paperVsSpy] = await Promise.all([
    loadPicks(latestDate),
    loadAnalysis(latestDate),
    loadPaperVsSpy(),
  ]);

  if (!picks) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Factor strategy"
          description="Daily picks from the composite factor."
        />
        <Card>
          <CardContent className="py-8 text-muted-foreground">
            Picks file for {latestDate} is unreadable.
          </CardContent>
        </Card>
      </div>
    );
  }

  const sectors = analysis ? sectorCounts(analysis) : [];
  const fsConcentrated = sectors.find((s) => s.pct > 30);
  const expectedMedian =
    analysis?.expected_per_pick_pct?.median ?? null;
  const expectedP25 = analysis?.expected_per_pick_pct?.p25 ?? null;
  const expectedP75 = analysis?.expected_per_pick_pct?.p75 ?? null;
  const equity = analysis?.equity_usd ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Factor strategy"
        description={`Composite (momentum + quality + value) — top ${picks.top_n} of ${picks.universe_size}. As of ${latestDate}.`}
      />

      <EdgeUncertaintyBanner />

      <PaperVsSpyCard data={paperVsSpy} />

      {/* Hero stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Strategy</CardDescription>
            <CardTitle className="text-base font-mono">
              {picks.strategy}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground">
              top 5% rank-blend; quarterly rebalance
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Universe</CardDescription>
            <CardTitle>{picks.universe_size}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground">
              PIT S&amp;P 500 constituents as of {latestDate}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Equity (paper)</CardDescription>
            <CardTitle>
              {equity !== null ? fmtUSD(equity) : "—"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground">
              {analysis ? `${analysis.n_positions} positions, equal-weight` : "no analysis"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Expected (63d, median)</CardDescription>
            <CardTitle
              className={
                expectedMedian !== null && expectedMedian > 0
                  ? "text-bullish"
                  : "text-foreground"
              }
            >
              {expectedMedian !== null ? fmtPct(expectedMedian) : "—"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground">
              {expectedP25 !== null && expectedP75 !== null
                ? `p25 ${fmtPct(expectedP25)}  ·  p75 ${fmtPct(expectedP75)}`
                : "from backtest trade log"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Sector breakdown */}
      {sectors.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Sector exposure</CardTitle>
            <CardDescription>
              {fsConcentrated ? (
                <span className="text-bearish">
                  ⚠️ {fsConcentrated.sector} concentration{" "}
                  {fsConcentrated.pct.toFixed(0)}% — single-sector drawdown
                  hits harder than SPY
                </span>
              ) : (
                "Diversified across sectors."
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {sectors.map((s) => (
                <Badge
                  key={s.sector}
                  variant={s.pct > 30 ? "bearish" : "neutral"}
                  className="font-mono"
                >
                  {s.sector}: {s.count} ({s.pct.toFixed(0)}%)
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* Picks table */}
      <Card>
        <CardHeader>
          <CardTitle>Today&apos;s picks</CardTitle>
          <CardDescription>
            Equal-weight allocation. Click any ticker for the per-stock plan.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">#</TableHead>
                <TableHead>Ticker</TableHead>
                <TableHead className="text-right">z</TableHead>
                <TableHead className="text-right">Mom</TableHead>
                <TableHead className="text-right">Qual</TableHead>
                <TableHead className="text-right">Val</TableHead>
                <TableHead>Strongest</TableHead>
                {analysis ? (
                  <>
                    <TableHead className="text-right">Entry</TableHead>
                    <TableHead className="text-right">Stop</TableHead>
                    <TableHead className="text-right">Target</TableHead>
                    <TableHead>Sector</TableHead>
                  </>
                ) : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {picks.picks.map((p) => {
                const a = analysis?.picks.find(
                  (x) => x.ticker === p.ticker,
                );
                const strongest = pickStrongestFactor(p);
                return (
                  <TableRow key={p.ticker} mono>
                    <TableCell className="text-muted-foreground">
                      {p.rank}
                    </TableCell>
                    <TableCell>
                      <Link
                        href={`/stocks/${encodeURIComponent(p.ticker)}`}
                        className="font-mono font-semibold hover:text-primary"
                      >
                        {p.ticker}
                      </Link>
                    </TableCell>
                    <TableCell className="text-right text-bullish font-mono">
                      {p.z_score.toFixed(2)}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">
                      {p.mom_rank ?? "—"}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">
                      {p.qual_rank ?? "—"}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground">
                      {p.val_rank ?? "—"}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{strongest}</Badge>
                    </TableCell>
                    {analysis ? (
                      <>
                        <TableCell className="text-right font-mono">
                          {a ? fmtUSD(a.entry_price) : "—"}
                        </TableCell>
                        <TableCell className="text-right font-mono text-bearish">
                          {a ? fmtUSD(a.stop_loss) : "—"}
                        </TableCell>
                        <TableCell className="text-right font-mono text-bullish">
                          {a ? fmtUSD(a.target) : "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground truncate max-w-[140px]">
                          {a?.sector ?? "—"}
                        </TableCell>
                      </>
                    ) : null}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Drill-down links */}
      <Card>
        <CardHeader>
          <CardTitle>Drill-down</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="grid gap-2 text-sm sm:grid-cols-2">
            <li>
              <span className="text-muted-foreground">Strategy verdict:</span>{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                reports/factor_strategy_report_2026_05_16.md
              </code>
            </li>
            <li>
              <span className="text-muted-foreground">Per-stock plans:</span>{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                reports/portfolio_analysis_{latestDate.replace(/-/g, "_")}.md
              </code>
            </li>
            <li>
              <span className="text-muted-foreground">Exit plan:</span>{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                reports/exit_plan_{latestDate.replace(/-/g, "_")}.md
              </code>
            </li>
            <li>
              <span className="text-muted-foreground">Stress test:</span>{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                reports/stress_test_{latestDate.replace(/-/g, "_")}.md
              </code>
            </li>
            <li>
              <span className="text-muted-foreground">Morning briefing:</span>{" "}
              <Link
                href="/factors/briefing"
                className="text-primary hover:underline"
              >
                /factors/briefing
              </Link>
            </li>
            <li>
              <span className="text-muted-foreground">Watchlist (next quarter):</span>{" "}
              <Link
                href="/factors/watchlist"
                className="text-primary hover:underline"
              >
                /factors/watchlist
              </Link>
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

function pickStrongestFactor(p: {
  mom_rank?: number | null;
  qual_rank?: number | null;
  val_rank?: number | null;
}): string {
  const candidates: [string, number][] = [];
  if (p.mom_rank != null) candidates.push(["MOM", p.mom_rank]);
  if (p.qual_rank != null) candidates.push(["QUAL", p.qual_rank]);
  if (p.val_rank != null) candidates.push(["VAL", p.val_rank]);
  if (!candidates.length) return "—";
  candidates.sort((a, b) => a[1] - b[1]);
  return candidates[0][0];
}
