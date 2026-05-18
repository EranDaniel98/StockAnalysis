import { PageHeader } from "@/components/page-header";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

// In-page TOC; pure anchor links, no scrollspy. Sections below set
// `scroll-mt-4` so the sticky shell header doesn't cover them on jump.
const TOC: ReadonlyArray<{ href: string; label: string }> = [
  { href: "#quick-start", label: "Quick start" },
  { href: "#pages", label: "Pages" },
  { href: "#strategies", label: "Strategies" },
  { href: "#sub-scores", label: "Sub-scores" },
  { href: "#grades", label: "Grades" },
  { href: "#faq", label: "FAQ" },
];

type QuickStep = { label: string; body: string };
const QUICK_STEPS: ReadonlyArray<QuickStep> = [
  {
    label: "Run a scan.",
    body: "Go to /scan, pick a strategy (default: swing_trading), hit Run. Wait for the pipeline to finish — typically 30-90s for the themes universe.",
  },
  {
    label: "Read the recommendations.",
    body: "Top of the results table is the highest-conviction pick. Each row links to /stocks/[ticker] for the full trade plan, sub-score breakdown, and entry/stop/target chart.",
  },
  {
    label: "(Optional) Submit to paper.",
    body: "From the CLI: uv run python -m src.cli.main paper trade --strategy swing_trading. Bracket orders go to your Alpaca paper account.",
  },
  {
    label: "Check /portfolio for live positions.",
    body: "Equity/cash come directly from Alpaca. Position marks stream from Alpaca's IEX feed.",
  },
];

type PageRow = { route: string; description: string };
const PAGES: ReadonlyArray<PageRow> = [
  { route: "/portfolio", description: "Live Alpaca account: equity, cash, open positions with streaming marks." },
  { route: "/scan", description: "Run a new market scan. Pipeline view + live progress + ranked results." },
  { route: "/stocks/[ticker]", description: "Per-ticker trade plan: composite score, sub-scores, entry/stop/target overlay on price chart, reasoning, risk plan." },
  { route: "/recommendations", description: "Append-only log of every paper-trade recommendation (submitted + skipped)." },
  { route: "/sectors", description: "SPDR sector ETF rotation heatmap. Tile color = 5-day return." },
  { route: "/backtests", description: "List of completed backtest runs across strategies." },
  { route: "/backtests/[id]", description: "Per-run tearsheet: equity curve, drawdown, trade log, MAR/Sortino, return distribution." },
  { route: "/backtests/compare", description: "Overlay N backtest equity curves on one chart." },
  { route: "/diagnose", description: "Alphalens IC sweep — quantile-spread, IC decay, factor-grouped Sharpe." },
  { route: "/help", description: "This page." },
];

type StrategyRow = {
  name: string;
  horizon: string;
  minScore: number;
  emphasis: string;
};
const STRATEGIES: ReadonlyArray<StrategyRow> = [
  { name: "long_term_growth", horizon: "6-24 months", minScore: 70, emphasis: "Revenue growth, earnings growth, ROE, 12m momentum" },
  { name: "short_term_momentum", horizon: "1-30 days", minScore: 65, emphasis: "RSI, MACD, volume spikes, 3m momentum, Clenow momentum" },
  { name: "value_investing", horizon: "12-36 months", minScore: 70, emphasis: "P/E, P/B, P/S, EV/EBITDA, margins" },
  { name: "swing_trading", horizon: "5-30 days", minScore: 50, emphasis: "Patterns, technicals, breakouts" },
  { name: "mean_reversion", horizon: "3-15 days", minScore: 50, emphasis: "Oversold RSI, distance from MA, statistical Z-scores" },
  { name: "dividend_income", horizon: "24+ months", minScore: 65, emphasis: "Yield, payout ratio, dividend growth, stability" },
];

type SubScore = { name: string; description: string };
const SUB_SCORES: ReadonlyArray<SubScore> = [
  { name: "technical", description: "Trend, RSI, MACD, MA cross signals from src/scoring/analyzers/technical.py." },
  { name: "fundamental", description: "Revenue & earnings growth, margins, ROE, P/E, debt ratios. Point-in-time from EDGAR XBRL when available, yfinance snapshot otherwise." },
  { name: "pattern", description: "Chart patterns: breakouts, consolidations, head-and-shoulders, cup-and-handle." },
  { name: "statistical", description: "Z-scores, mean-reversion signals, correlation to SPY, volatility-adjusted returns." },
  { name: "trend", description: "Long-term trend detection: 50/200 MA structure, ADX, slope." },
  { name: "alpha158", description: "Qlib-style 158-factor library compressed to a 0-100 score." },
  { name: "pead", description: "Post-earnings announcement drift signal. Fires for ±7 trading days after earnings." },
  { name: "insider_flow", description: "Open-market buys/sells by company insiders from SEC Form 4 filings." },
  { name: "catalyst", description: "Proactive event detection from insider clusters + 8-K filings. Disabled by default after a null A/B result." },
  { name: "sector_flows", description: "SPDR sector ETF momentum vs SPY — capital rotation signal." },
  { name: "short_interest", description: "FINRA daily short-volume ratio." },
  { name: "analyst_revisions", description: "yfinance upgrades/downgrades. LIVE-ONLY (no backtest data)." },
  { name: "options_skew", description: "IV-derived put/call sentiment from yfinance option chains. LIVE-ONLY." },
];

type GradeRow = {
  grade: string;
  range: string;
  confidence: string;
  action: string;
  tone: "bullish" | "neutral" | "bearish";
};
const GRADES: ReadonlyArray<GradeRow> = [
  { grade: "STRONG BUY", range: "80-100", confidence: "High", action: "Take full position size", tone: "bullish" },
  { grade: "BUY", range: "70-80", confidence: "High", action: "Take position; consider scaling in", tone: "bullish" },
  { grade: "HOLD", range: "50-70", confidence: "Medium", action: "Wait for better setup", tone: "neutral" },
  { grade: "SELL", range: "30-50", confidence: "Medium", action: "Reduce / close existing position", tone: "bearish" },
  { grade: "STRONG SELL", range: "0-30", confidence: "High", action: "Close immediately; consider short", tone: "bearish" },
];

type FaqEntry = { q: string; a: string };
const FAQ: ReadonlyArray<FaqEntry> = [
  {
    q: "The dev server fell back to port 3003 instead of 3000. Why?",
    a: "A zombie Next.js process is holding port 3000. Kill it with Stop-Process -Id <pid> -Force (PID is in the launcher output) and re-run the dev launcher.",
  },
  {
    q: "My /portfolio equity doesn't match Alpaca's dashboard.",
    a: "Fixed in commit 53dcd91 — the page now shows Alpaca's authoritative equity field instead of a client-side recompute. If you still see drift, hard-refresh the tab (Ctrl+Shift+R).",
  },
  {
    q: "The /scan page is missing the ANALYST and OPTIONS pipeline brackets.",
    a: "Rebuild the Next.js bundle: npm run build or restart the dev launcher. The four new SSE stages (analyst_revisions_start/done, options_chains_start/done) shipped in commit bd89d84.",
  },
  {
    q: "A page is unstyled / “broken CSS”.",
    a: "Most common cause: a production build was running (npm run start) and got hash-rotated underneath the browser. Either hard-refresh or restart the dev launcher (uv run python -m scripts.dev).",
  },
  {
    q: "Sub-scores analyst_revisions and options_skew are always missing.",
    a: "Those are LIVE-ONLY signals — they only fire when the API runner fetches yfinance data, which it does on every /api/scans call (toggleable via live_signals kwarg). They never appear in backtests because historical analyst/options data isn't free.",
  },
  {
    q: "How do I add a new strategy?",
    a: "Edit config/strategies.yaml, restart the API. The strategy will appear in /scan's strategy dropdown automatically.",
  },
  {
    q: "Where do scan/backtest/recommendation rows persist?",
    a: "Postgres. The dev docker-compose.yml runs Postgres 16 on localhost. Schema is managed by Alembic — alembic upgrade head brings a fresh DB up.",
  },
];

function gradeToneClass(tone: GradeRow["tone"]): string {
  if (tone === "bullish") return "text-bullish";
  if (tone === "bearish") return "text-bearish";
  return "text-neutral";
}

export default function HelpPage() {
  return (
    <>
      <PageHeader
        title="Help & reference"
        description="Quick start, pages overview, strategies, sub-scores, recommendation grades, and FAQ."
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
                        Page
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

          <section id="strategies" className="scroll-mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  Strategies
                </CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Strategy
                      </th>
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Horizon
                      </th>
                      <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Min score
                      </th>
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Emphasis
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {STRATEGIES.map((s) => (
                      <tr
                        key={s.name}
                        className="border-b border-border last:border-b-0 hover:bg-muted/40"
                      >
                        <td className="px-3 py-1.5 font-mono text-xs text-foreground whitespace-nowrap">
                          {s.name}
                        </td>
                        <td className="px-3 py-1.5 text-xs text-muted-foreground whitespace-nowrap">
                          {s.horizon}
                        </td>
                        <td
                          className={cn(
                            "px-3 py-1.5 font-mono tabular-nums text-xs text-right",
                            s.minScore >= 65
                              ? "text-primary"
                              : "text-muted-foreground",
                          )}
                        >
                          {s.minScore}
                        </td>
                        <td className="px-3 py-1.5 text-xs text-muted-foreground">
                          {s.emphasis}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-muted-foreground text-xs font-mono mt-3 px-3">
                  Strategy weights, thresholds, and analyzer toggles live in{" "}
                  <code className="text-foreground bg-muted/30 px-1 rounded">
                    config/strategies.yaml
                  </code>
                  .
                </p>
              </CardContent>
            </Card>
          </section>

          <section id="sub-scores" className="scroll-mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  Sub-scores
                </CardTitle>
              </CardHeader>
              <CardContent>
                <dl>
                  {SUB_SCORES.map((s) => (
                    <div
                      key={s.name}
                      className="border-b border-border last:border-b-0 py-2"
                    >
                      <dt className="font-mono text-xs text-primary tracking-wider uppercase">
                        {s.name}
                      </dt>
                      <dd className="text-sm text-muted-foreground mt-0.5">
                        {s.description}
                      </dd>
                    </div>
                  ))}
                </dl>
              </CardContent>
            </Card>
          </section>

          <section id="grades" className="scroll-mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
                  Recommendation grades
                </CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Grade
                      </th>
                      <th className="text-right px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Composite score
                      </th>
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Confidence
                      </th>
                      <th className="text-left px-3 py-1.5 text-[10px] font-medium tracking-wider uppercase text-muted-foreground">
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {GRADES.map((g) => (
                      <tr
                        key={g.grade}
                        className="border-b border-border last:border-b-0 hover:bg-muted/40"
                      >
                        <td
                          className={cn(
                            "px-3 py-1.5 font-mono text-xs uppercase tracking-wider whitespace-nowrap",
                            gradeToneClass(g.tone),
                          )}
                        >
                          {g.grade}
                        </td>
                        <td className="px-3 py-1.5 font-mono tabular-nums text-xs text-right text-muted-foreground">
                          {g.range}
                        </td>
                        <td className="px-3 py-1.5 text-xs text-muted-foreground">
                          {g.confidence}
                        </td>
                        <td className="px-3 py-1.5 text-xs text-muted-foreground">
                          {g.action}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-muted-foreground text-xs font-mono mt-3 px-3">
                  Thresholds are configured per-strategy in{" "}
                  <code className="text-foreground bg-muted/30 px-1 rounded">
                    config/strategies.yaml
                  </code>{" "}
                  under{" "}
                  <code className="text-foreground bg-muted/30 px-1 rounded">
                    thresholds.{"{"}strong_buy,buy,hold_upper,hold_lower,sell{"}"}
                  </code>
                  .
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
                      <dd className="text-sm text-muted-foreground mt-1">
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

