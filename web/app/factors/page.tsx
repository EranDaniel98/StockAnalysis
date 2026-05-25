import Link from "next/link";
import { ChevronRight, Repeat, Wallet } from "lucide-react";

import { FactorChips } from "@/components/factor-chips";
import { PageHeader } from "@/components/page-header";
import { PaperVsSpyCard } from "@/components/paper-vs-spy-card";
import { SanityVerdictBadge } from "@/components/sanity-verdict-badge";
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
  fetchBriefingServer,
  findLatestPicksDate,
  loadAnalysis,
  loadPaperVsSpy,
  loadPicks,
  loadPreviousPicks,
  loadSanityCheck,
  sectorCounts,
  type SanityPickRow,
} from "@/lib/factors/data";
import { fmtPct, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

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

  // Everything we need lands in a single parallel await so the page
  // doesn't waterfall. Each loader degrades to null on its own.
  const [picks, analysis, paperVsSpy, previousPicks, sanity, briefing] =
    await Promise.all([
      loadPicks(latestDate),
      loadAnalysis(latestDate),
      loadPaperVsSpy(),
      loadPreviousPicks(latestDate),
      loadSanityCheck(latestDate),
      fetchBriefingServer(),
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

  // ── Pre-compute index lookups so each table row is O(1). ────────────────
  const heldSet = new Set(
    briefing?.action_counts?.keep_tickers ?? [],
  );
  const previousTickerSet = new Set(
    (previousPicks?.picks ?? []).map((p) => p.ticker),
  );
  const sanityByTicker = new Map<string, SanityPickRow>();
  for (const row of sanity?.verdict?.per_pick ?? []) {
    sanityByTicker.set(row.ticker, row);
  }

  const sectors = analysis ? sectorCounts(analysis) : [];
  const fsConcentrated = sectors.find((s) => s.pct > 30);
  const expectedMedian = analysis?.expected_per_pick_pct?.median ?? null;
  const expectedP25 = analysis?.expected_per_pick_pct?.p25 ?? null;
  const expectedP75 = analysis?.expected_per_pick_pct?.p75 ?? null;
  const equity = analysis?.equity_usd ?? null;

  // Derived: live concentration percentage from picks.top_n / universe_size.
  // The hero label used to hard-code "top 5%" which went stale after the
  // 2026-05-19 d03 ablation cut top_n from 24 → 15.
  const concentrationPct =
    picks.universe_size > 0
      ? (picks.top_n / picks.universe_size) * 100
      : 0;

  const dateUnderscored = latestDate.replace(/-/g, "_");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Factor strategy"
        description={`Composite m+q+v+pead — top ${picks.top_n} of ${picks.universe_size} (${concentrationPct.toFixed(1)}%). As of ${latestDate}.`}
      />

      {/*
        Edge-uncertainty banner moved to AppShell as a global EdgeCaveatBanner
        — every route gets it. Removed the per-page banner here to avoid
        rendering the same warning twice on /factors.
      */}

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
              {concentrationPct.toFixed(1)}% rank-blend, ~63-day rebalance
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

      {/* AI sanity check verdict — only shown when today's run exists.    */}
      {sanity ? (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-baseline gap-3 flex-wrap">
              <CardTitle className="text-sm">AI sanity check</CardTitle>
              <Badge
                variant={
                  sanity.verdict.overall_verdict === "HOLD" ? "neutral"
                  : sanity.verdict.overall_verdict.startsWith("PROCEED") ? "bullish"
                  : "bearish"
                }
                className="text-[10px] uppercase tracking-wider"
              >
                {sanity.verdict.overall_verdict} · {sanity.verdict.confidence}/100
              </Badge>
              <span className="text-[10px] font-mono text-muted-foreground">
                {sanity.model}
              </span>
            </div>
            <CardDescription className="text-[11px] mt-1">
              Per-pick advisory verdicts shown inline in the picks table.
              Sanity output is logged but does NOT block paper-trade execution.
            </CardDescription>
          </CardHeader>
          {sanity.verdict.key_concerns.length > 0 ? (
            <CardContent>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
                Key concerns
              </p>
              <ul className="space-y-1 text-xs text-muted-foreground">
                {sanity.verdict.key_concerns.map((c, i) => (
                  <li key={i} className="leading-relaxed">
                    • {c}
                  </li>
                ))}
              </ul>
            </CardContent>
          ) : null}
        </Card>
      ) : null}

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
          <CardDescription className="flex items-center gap-3 flex-wrap text-[11px]">
            <span>Equal-weight allocation. Click any ticker for the per-stock plan.</span>
            <span className="flex items-center gap-1 text-muted-foreground">
              <Wallet className="h-3 w-3" /> held
            </span>
            <span className="flex items-center gap-1 text-muted-foreground">
              <Repeat className="h-3 w-3" /> carried over
            </span>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">#</TableHead>
                <TableHead>Ticker</TableHead>
                <TableHead className="text-right">z</TableHead>
                <TableHead>Factor stack</TableHead>
                {sanity ? <TableHead>AI</TableHead> : null}
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
                const a = analysis?.picks.find((x) => x.ticker === p.ticker);
                const held = heldSet.has(p.ticker);
                const carryover = previousTickerSet.has(p.ticker);
                const sv = sanityByTicker.get(p.ticker);
                return (
                  <TableRow key={p.ticker} mono>
                    <TableCell className="text-muted-foreground">
                      {p.rank}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <Link
                          href={`/stocks/${encodeURIComponent(p.ticker)}`}
                          className="font-mono font-semibold hover:text-primary"
                        >
                          {p.ticker}
                        </Link>
                        {held ? (
                          <Wallet
                            className="h-3 w-3 text-primary"
                            aria-label="Currently held in paper account"
                          />
                        ) : null}
                        {carryover ? (
                          <Repeat
                            className="h-3 w-3 text-muted-foreground"
                            aria-label="Carried over from previous basket via hysteresis"
                          />
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-mono tabular-nums",
                        p.z_score >= 2.0 ? "text-bullish" : "text-foreground",
                      )}
                    >
                      {p.z_score.toFixed(2)}
                    </TableCell>
                    <TableCell>
                      <FactorChips
                        mom={p.mom_rank}
                        qual={p.qual_rank}
                        val={p.val_rank}
                        pead={p.pead_rank}
                      />
                    </TableCell>
                    {sanity ? (
                      <TableCell>
                        {sv ? (
                          <SanityVerdictBadge
                            verdict={sv.verdict}
                            reason={sv.reason}
                            evidence={sv.evidence}
                          />
                        ) : (
                          <span className="text-muted-foreground/60 text-[10px]">—</span>
                        )}
                      </TableCell>
                    ) : null}
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
                          {a?.sector ?? p.sector ?? "—"}
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

      {/* Drill-down — real links to sibling sub-routes that render the
          full markdown reports. The previous version listed literal file
          paths in <code> blocks which weren't clickable.            */}
      <Card>
        <CardHeader>
          <CardTitle>Drill-down</CardTitle>
          <CardDescription className="text-[11px]">
            Each link renders the daily-pipeline output for {latestDate}.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="grid gap-1 text-sm sm:grid-cols-2">
            <ReportLink
              href="/factors/briefing"
              label="Morning briefing"
              hint="one-page summary (read first)"
            />
            <ReportLink
              href="/factors/per-stock-plans"
              label="Per-stock plans"
              hint={`portfolio_analysis_${dateUnderscored}.md`}
            />
            <ReportLink
              href="/factors/exit-plan"
              label="Exit plan"
              hint={`exit_plan_${dateUnderscored}.md`}
            />
            <ReportLink
              href="/factors/stress-test"
              label="Stress test"
              hint={`stress_test_${dateUnderscored}.md`}
            />
            <ReportLink
              href="/factors/watchlist"
              label="Watchlist"
              hint="bench candidates near the cut line"
            />
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

function ReportLink({
  href, label, hint,
}: {
  href: string;
  label: string;
  hint: string;
}) {
  return (
    <li>
      <Link
        href={href}
        className="group flex items-baseline gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50 transition-colors"
      >
        <ChevronRight className="h-3 w-3 text-muted-foreground/60 group-hover:text-primary transition-colors" />
        <span className="font-medium">{label}</span>
        <span className="text-[11px] text-muted-foreground">{hint}</span>
      </Link>
    </li>
  );
}
