import { PageHeader } from "@/components/page-header";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

// In-page TOC; pure anchor links, no scrollspy. Sections set scroll-mt-4
// so the sticky shell header doesn't cover them on jump.
const TOC: ReadonlyArray<{ href: string; label: string }> = [
  { href: "#quick-start", label: "Quick start" },
  { href: "#pages", label: "Pages" },
  { href: "#strategy", label: "The strategy" },
  { href: "#factors", label: "Factors" },
  { href: "#actions", label: "Actions & sanity" },
  { href: "#edge", label: "What's the edge?" },
  { href: "#faq", label: "FAQ" },
];

type QuickStep = { label: string; body: string };
const QUICK_STEPS: ReadonlyArray<QuickStep> = [
  {
    label: "Run the daily pipeline.",
    body: "Go to Run pipeline (left nav). Pick the date + top-N (default today, 15), hit Run. 9 steps stream live: picks → comprehensive analysis → exit plan → position monitor → stress → watchlist → AI sanity check → briefing → paper-vs-SPY snapshot. ~5-10 min total.",
  },
  {
    label: "Read Today's actions.",
    body: "/buy-signals splits the rebalance into NEW BUY / KEEP / EXIT sections with per-row stop, target, AI sanity verdict, days-to-earnings. This is the one page to open before clicking anything at the broker.",
  },
  {
    label: "Cross-check on Home + Portfolio.",
    body: "Home shows the top-5 picks + scoreboard. Portfolio shows what you actually hold + each position's status (HOLDING / NEAR_STOP / STOP_HIT) against the strategy's stop/target levels.",
  },
  {
    label: "Execute on Alpaca.",
    body: "Manually — copy ticker / qty / stop / target from /buy-signals into your broker. Or programmatically: uv run python -m scripts.paper_trade_factor_picks. The execution log lands on /recommendations.",
  },
];

type PageRow = { route: string; description: string };
const PAGES: ReadonlyArray<PageRow> = [
  { route: "/", description: "Home — top-5 factor picks, rebalance shape (NEW BUY / KEEP / EXIT counts), paper P&L, pipeline freshness, briefing banner." },
  { route: "/factors", description: "Full 15-pick basket with factor chips, AI sanity per pick, held / hysteresis-carry indicators, sector exposure. Drill-down links to morning briefing, exit plan, stress test, per-stock plans, watchlist." },
  { route: "/portfolio", description: "Live Alpaca paper account: equity, cash, positions with streaming marks, per-position stop/target/status, equity curve with real SPY overlay (anchored to first funded date)." },
  { route: "/scan", description: "Run the daily pipeline on demand — SSE step ladder with per-step elapsed timing. Replaces the legacy 5-engine scanner." },
  { route: "/buy-signals", description: "Today's actions — NEW BUY / KEEP / EXIT sections with entry / qty / sizing / stop / target / AI sanity / earnings flag per ticker." },
  { route: "/backtests", description: "Factor sweep + A/B results: α vs SPY, walk-forward gate (pass/fail), per-run params + metrics. Click a slug for full detail." },
  { route: "/backtests/[slug]", description: "Per-run detail: scoreboard, parameters card, walk-forward folds with per-fold Sharpe, equity curve with real SPY overlay, rebalance log, trades sample." },
  { route: "/diagnose", description: "On-disk IC report viewer — per-factor × per-horizon information coefficient with Bonferroni-adjusted significance shading. Includes regime-conditional reports (low_vix / high_vix)." },
  { route: "/recommendations", description: "Per-day execution log — submitted / skipped / failed orders, AI sanity-gate decisions per ticker, Alpaca error messages for failures." },
  { route: "/sectors", description: "SPDR sector ETF rotation. Each tile shows 1d/5d/21d return + 30d sparkline + basket overlay (how many picks the basket holds in that sector)." },
  { route: "/stocks/[ticker]", description: "Per-ticker view: NEW BUY/KEEP/EXIT badge, composite z, factor stack chips, position info if held, AI sanity card, price chart with strategy ENTRY/STOP/TARGET overlays." },
  { route: "/help", description: "This page." },
];

type FactorRow = {
  name: string;
  label: string;
  description: string;
};
const FACTORS: ReadonlyArray<FactorRow> = [
  { name: "momentum", label: "MOM", description: "12-1 month price momentum (12-month return excluding the most recent month, to avoid the 1-month reversal effect). Rank #1 = strongest 12-1m return in the universe." },
  { name: "quality", label: "QUAL", description: "Sector-neutralized blend of operating margin, ROE, FCF yield, and other profitability metrics. Sector-neutralized = ranked within sector, then combined, so a strong Tech name and a strong Bank name can both score high." },
  { name: "value", label: "VAL", description: "Earnings yield (1/P/E) + free-cash-flow yield + dividend yield. Negative-EPS names still get a rank from FCF + dividend components rather than being filtered out." },
  { name: "pead", label: "PEAD", description: "Post-earnings announcement drift. Fires for ~30 trading days after an earnings beat (or miss); +rank for positive surprise, -rank for negative. Opt-in factor — added 2026-05-18, default ON since validation showed +2.53pp α." },
];

type ActionRow = {
  action: string;
  meaning: string;
  source: string;
  tone: "bullish" | "neutral" | "bearish";
};
const ACTIONS: ReadonlyArray<ActionRow> = [
  { action: "NEW BUY", meaning: "In today's picks, not currently held. Fresh entry — buy target_shares at entry_price with bracket stop / target.", source: "set-diff: picks − held", tone: "bullish" },
  { action: "KEEP", meaning: "In today's picks AND held. No action — monitor against stop/target.", source: "intersection", tone: "neutral" },
  { action: "EXIT", meaning: "Held but no longer in picks. Sell on next rebalance.", source: "set-diff: held − picks", tone: "bearish" },
  { action: "HOLDING", meaning: "Position between stop and target. Default state.", source: "live price classification", tone: "neutral" },
  { action: "NEAR_STOP", meaning: "Within 2% of the strategy stop. Tightening watch.", source: "live classification", tone: "bearish" },
  { action: "STOP_HIT", meaning: "Current price ≤ stop. Exit immediately.", source: "live classification", tone: "bearish" },
  { action: "NEAR_TARGET", meaning: "Within 2% of the strategy target.", source: "live classification", tone: "bullish" },
  { action: "TARGET_HIT", meaning: "Current price ≥ target. Take profit / let it ride per strategy rules.", source: "live classification", tone: "bullish" },
];

type SanityRow = {
  verdict: string;
  meaning: string;
  effect: string;
  tone: "bullish" | "neutral" | "bearish";
};
const SANITY: ReadonlyArray<SanityRow> = [
  { verdict: "KEEP", meaning: "AI sees no implementation issue, no one-off catalyst distorting the signal.", effect: "Pass through.", tone: "bullish" },
  { verdict: "FLAG", meaning: "AI sees a concern (e.g. earnings within window, weak factor coverage carrying composite, suspect single-factor lift).", effect: "Advisory — does not block. Worth reading the evidence before sizing.", tone: "neutral" },
  { verdict: "VETO", meaning: "AI strongly recommends excluding the pick (rare — used for clear data errors / lookahead concerns).", effect: "Advisory only today. Sanity output is logged but NOT a hard gate yet (will become one once we have ≥1 month of paper data).", tone: "bearish" },
];

type FaqEntry = { q: string; a: string };
const FAQ: ReadonlyArray<FaqEntry> = [
  {
    q: "Why is the system factor-led instead of the 5-engine composite?",
    a: "The original 5-engine composite (technical/fundamental/pattern/statistical/trend + scoring weights per strategy) was extensively tested. Final verdict 2026-05-16: no defensible OOS edge — best variant cross-window α was +0.62%. The factor composite (m+q+v+pead) was found in the Phase 1+3 rebuild to deliver +1.88%/yr cross-window α (3-window check) with PIT S&P 500 universe + EDGAR PIT fundamentals. That's the system the pipeline now runs daily.",
  },
  {
    q: "The Home page says strategy is composite_d05_r63 but top_n is 15 — that's 3%, not 5%?",
    a: "Yes — the label is stale. The d03 concentration ablation (top-N 24 → 15) shipped 2026-05-19 because tighter concentration nearly doubled cross-window α (+5.70% → +10.80%) and flipped the bull window from −6.60% to +2.37%. The strategy ID string in the picks file hasn't been updated to 'composite_d03_r63'. Behavioral truth: top 3% concentration, quarterly rebalance.",
  },
  {
    q: "Why doesn't /scan run on-demand factor picks for a custom universe?",
    a: "The daily pipeline rebuilds the entire S&P 500 universe each run (PIT membership + EDGAR PIT fundamentals + price history + factor ranks). On-demand sub-universe scans were a 5-engine workflow that didn't fit the factor pipeline's snapshot-based approach. Use the pipeline trigger to regenerate today's picks; for ad-hoc what-if analysis, see /backtests.",
  },
  {
    q: "What's the difference between sweep results and A/B results on /backtests?",
    a: "Sweep results (data/factors/sweep/comp_*_*.json) cover a parameter grid — every variant of top-decile × rebalance-days × time-window. A/B results (reports/ab_*.json) are targeted comparisons on a fixed snapshot — e.g. testing hysteresis-bonus values 0.3 / 0.5 / 0.75 / 1.0 / 1.5 against a baseline. Same metrics shape; A/B uses a snapshot_id hash in the filename.",
  },
  {
    q: "Why is the SPY overlay on /portfolio sometimes truncated to less than 30 days?",
    a: "The backend strips leading equity=0 bars from Alpaca's history (account wasn't funded yet). So a 3M-button request returns only the funded portion. The chart header now reads 'Xd requested · Yd shown (truncated)' so the trimming is explicit.",
  },
  {
    q: "AI sanity check flagged a pick. Should I skip it?",
    a: "Probably not yet. Sanity output is currently advisory only — the daily pipeline logs the verdict but doesn't block execution. We need ≥1 month of paper data to validate whether sanity-flagged picks actually underperform. For now: read the evidence (it's on the /buy-signals card and /stocks/[ticker] page), make your own call.",
  },
  {
    q: "Where do backtest artifacts persist?",
    a: "On disk, not in the DB. Sweep results in data/factors/sweep/*.json, A/B results in reports/ab_*.json, IC reports in reports/analyzer_ic_*.json. The legacy DB-backed /api/backtests endpoint still exists for 5-engine runs but the UI no longer uses it.",
  },
  {
    q: "How do I add a new ticker to the universe?",
    a: "The pipeline uses PIT S&P 500 membership — manual additions to that list aren't supported. To analyze a ticker outside the basket, hit /stocks/[ticker] directly (works for any ticker with Parquet history) or add it to config/portfolio.yaml as a watchlist entry.",
  },
];

function gradeToneClass(tone: ActionRow["tone"]): string {
  if (tone === "bullish") return "text-bullish";
  if (tone === "bearish") return "text-bearish";
  return "text-neutral";
}

export default function HelpPage() {
  return (
    <>
      <PageHeader
        title="Help & reference"
        description="Daily workflow, page guide, the factor strategy, what the AI sanity verdicts mean, edge picture, FAQ."
      />

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <nav className="lg:col-span-3 lg:sticky lg:top-4 lg:self-start">
          <ul className="text-[10px] font-medium tracking-wider uppercase text-muted-foreground space-y-2">
            {TOC.map((item) => (
              <li key={item.href}>
                <a
                  href={item.href}
                  className="hover:text-foreground transition-colors"
                >
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="lg:col-span-9 space-y-4">
          <section id="quick-start" className="scroll-mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  Quick start
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ol className="space-y-3">
                  {QUICK_STEPS.map((step, i) => (
                    <li key={i} className="flex gap-3">
                      <span className="inline-flex h-5 w-5 items-center justify-center bg-primary/15 text-primary font-mono text-xs font-semibold tracking-wider shrink-0">
                        {i + 1}
                      </span>
                      <p className="text-sm text-muted-foreground leading-relaxed">
                        <strong className="text-foreground font-medium">
                          {step.label}
                        </strong>{" "}
                        {step.body}
                      </p>
                    </li>
                  ))}
                </ol>
              </CardContent>
            </Card>
          </section>

          <section id="pages" className="scroll-mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  Pages
                </CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Route
                      </th>
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        What it does
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {PAGES.map((p) => (
                      <tr
                        key={p.route}
                        className="border-b border-border last:border-b-0 hover:bg-muted/40"
                      >
                        <td className="px-3 py-1.5 font-mono text-xs text-foreground whitespace-nowrap align-top">
                          {p.route}
                        </td>
                        <td className="px-3 py-1.5 text-xs text-muted-foreground">
                          {p.description}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          </section>

          <section id="strategy" className="scroll-mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  The strategy
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm leading-relaxed text-muted-foreground">
                <p>
                  <strong className="text-foreground">composite_d05_r63</strong>{" "}
                  (live label; behaviorally d03 since 2026-05-19). Daily
                  pipeline against the PIT S&amp;P 500 universe:
                </p>
                <ol className="list-decimal pl-5 space-y-1">
                  <li>
                    Load PIT membership as of the picks date + price history +
                    EDGAR PIT fundamentals.
                  </li>
                  <li>
                    Rank every name on momentum, quality (sector-neutralized),
                    value, and PEAD. Lower rank = stronger.
                  </li>
                  <li>
                    Average the per-factor normalized ranks → composite rank.
                    Z-score across the universe.
                  </li>
                  <li>
                    Apply optional overlays: 200-SMA trend filter with 75-SMA
                    re-entry (asymmetric), VIX-percentile regime gate,
                    hysteresis bonus (+0.75 to prior-basket carry-overs).
                  </li>
                  <li>
                    Take top {15} names ({"~3%"} of the universe) as
                    today&apos;s basket.
                  </li>
                  <li>
                    Rebalance every 63 trading days (quarterly). Hysteresis
                    keeps near-cutoff names from churning.
                  </li>
                </ol>
                <p>
                  Per-pick stop / target / time-exit come from{" "}
                  <code className="text-foreground bg-muted/30 px-1 rounded">
                    scripts.comprehensive_analysis
                  </code>{" "}
                  (ATR-derived stops, configurable target). AI sanity check
                  runs over the basket each day; verdicts logged.
                </p>
                <p>
                  Tunables live in{" "}
                  <code className="text-foreground bg-muted/30 px-1 rounded">
                    scripts/daily_factor_picks.py
                  </code>{" "}
                  — see the {`--top-n / --hysteresis-bonus / --trend-entry-sma
                  / --vix-abs-gate / --include-pead`}{" "}
                  flags.
                </p>
              </CardContent>
            </Card>
          </section>

          <section id="factors" className="scroll-mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  Factors
                </CardTitle>
              </CardHeader>
              <CardContent>
                <dl>
                  {FACTORS.map((f) => (
                    <div
                      key={f.name}
                      className="border-b border-border last:border-b-0 py-2"
                    >
                      <dt className="font-mono text-xs text-primary tracking-wider uppercase flex items-baseline gap-2">
                        {f.label}
                        <span className="text-muted-foreground text-[10px]">
                          {f.name}
                        </span>
                      </dt>
                      <dd className="text-sm text-muted-foreground mt-0.5">
                        {f.description}
                      </dd>
                    </div>
                  ))}
                </dl>
                <p className="text-muted-foreground text-xs mt-3 font-mono">
                  Factor chips throughout the UI light up when a pick lands in
                  the top decile (rank ≤ 50) for that factor — fast visual
                  read of which factors are carrying any given pick.
                </p>
              </CardContent>
            </Card>
          </section>

          <section id="actions" className="scroll-mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  Actions &amp; position status
                </CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Label
                      </th>
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Meaning
                      </th>
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Source
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {ACTIONS.map((a) => (
                      <tr
                        key={a.action}
                        className="border-b border-border last:border-b-0 hover:bg-muted/40"
                      >
                        <td
                          className={cn(
                            "px-3 py-1.5 font-mono text-xs uppercase tracking-wider whitespace-nowrap align-top",
                            gradeToneClass(a.tone),
                          )}
                        >
                          {a.action}
                        </td>
                        <td className="px-3 py-1.5 text-xs text-muted-foreground">
                          {a.meaning}
                        </td>
                        <td className="px-3 py-1.5 text-[11px] font-mono text-muted-foreground/70">
                          {a.source}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <h3 className="text-xs font-medium tracking-wider uppercase text-muted-foreground px-3 pt-4 pb-2">
                  AI sanity verdict
                </h3>
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Verdict
                      </th>
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Meaning
                      </th>
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Effect
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {SANITY.map((s) => (
                      <tr
                        key={s.verdict}
                        className="border-b border-border last:border-b-0 hover:bg-muted/40"
                      >
                        <td
                          className={cn(
                            "px-3 py-1.5 font-mono text-xs uppercase tracking-wider whitespace-nowrap align-top",
                            gradeToneClass(s.tone),
                          )}
                        >
                          {s.verdict}
                        </td>
                        <td className="px-3 py-1.5 text-xs text-muted-foreground">
                          {s.meaning}
                        </td>
                        <td className="px-3 py-1.5 text-xs text-muted-foreground">
                          {s.effect}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          </section>

          <section id="edge" className="scroll-mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  What&apos;s the edge?
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm leading-relaxed text-muted-foreground">
                <p>
                  <strong className="text-foreground">
                    Cross-window OOS α ≈ +1.88%/yr
                  </strong>{" "}
                  across three backtest windows (pre-COVID 2018-2020, 2020-2022
                  COVID, 2022-2024). The d03 concentration ablation
                  (2026-05-19) nearly doubled this; live label is d05_r63 but
                  the actual top-N is 15.
                </p>
                <p className="text-amber-500">
                  <strong>Caveat 1.</strong> The COVID window fails walk-forward
                  (fold-by-fold breakdown). Strategy works in trending windows,
                  struggles in V-shaped recovery.
                </p>
                <p className="text-amber-500">
                  <strong>Caveat 2.</strong> Independent re-runs of the same
                  backtest 12h apart drift by ±0.4 Sharpe due to yfinance
                  adjustment lag. That&apos;s the same magnitude as the α point
                  estimate — every metric here lives inside its own noise
                  envelope.
                </p>
                <p>
                  The picks are a defensible factor signal, not a proven edge.{" "}
                  <strong className="text-foreground">
                    Paper-trade only.
                  </strong>{" "}
                  Reconcile against SPY weekly via /portfolio.
                </p>
                <p className="text-xs">
                  Drill into /backtests for the per-run walk-forward folds and
                  /diagnose for the underlying factor IC research.
                </p>
              </CardContent>
            </Card>
          </section>

          <section id="faq" className="scroll-mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  FAQ
                </CardTitle>
              </CardHeader>
              <CardContent>
                <dl>
                  {FAQ.map((f, i) => (
                    <div
                      key={i}
                      className="border-b border-border last:border-b-0 py-3"
                    >
                      <dt className="text-sm font-medium text-foreground">
                        {f.q}
                      </dt>
                      <dd className="text-sm text-muted-foreground mt-1 leading-relaxed">
                        {f.a}
                      </dd>
                    </div>
                  ))}
                </dl>
              </CardContent>
            </Card>
          </section>
        </div>
      </div>
    </>
  );
}
