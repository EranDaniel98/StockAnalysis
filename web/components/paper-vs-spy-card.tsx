import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { PaperVsSpyFile } from "@/lib/factors/data";
import { fmtPct, fmtRelativeTime, fmtUSD, pnlColorClass } from "@/lib/format";

/**
 * Live paper-vs-SPY P&L comparison. Written by
 * ``scripts/paper_vs_spy_snapshot.py`` and read from
 * ``reports/paper_vs_spy.json``.
 *
 * Renders four states cleanly:
 *   1. no file at all → "run the snapshot script"
 *   2. status="not_configured" → "configure paper credentials"
 *   3. status="no_history" → "account connected, no trades yet"
 *   4. status="ok" → the comparison grid + α
 *
 * The α number is intentionally prominent. Whether the strategy is
 * actually adding value over a free index ETF is the single most
 * important question this UI can answer, and the audit found that
 * question was previously buried.
 */
export function PaperVsSpyCard({ data }: { data: PaperVsSpyFile | null }) {
  if (data === null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Paper vs SPY</CardTitle>
          <CardDescription>
            No snapshot file yet — run{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              uv run python -m scripts.paper_vs_spy_snapshot
            </code>{" "}
            to generate one.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (data.status === "not_configured") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Paper vs SPY</CardTitle>
          <CardDescription className="text-muted-foreground">
            {data.message ??
              "Set ALPACA_API_KEY and ALPACA_API_SECRET in .env, then re-run the snapshot script."}
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (data.status === "no_history") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Paper vs SPY</CardTitle>
          <CardDescription>
            Alpaca account connected but portfolio history is empty —
            submit a few paper bracket orders first
            (
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              uv run python -m src.cli.main paper trade --strategy swing_trading --dry-run
            </code>
            ).
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (data.status === "error" || !data.paper || !data.spy) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Paper vs SPY</CardTitle>
          <CardDescription className="text-bearish">
            {data.message ?? "Snapshot generation reported an error."}
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const paper = data.paper;
  const spy = data.spy;
  const alpha = data.alpha_pct ?? paper.return_pct - spy.return_pct;
  const alphaColor = pnlColorClass(alpha);
  const verdict = alpha >= 2
    ? "Outperforming SPY — keep the run going"
    : alpha >= -2
      ? "Roughly tracking SPY — within noise"
      : "Underperforming SPY — consider whether the strategy is adding value";

  return (
    <Card>
      <CardHeader>
        <CardTitle>Paper vs SPY ({data.window_days}d)</CardTitle>
        <CardDescription>
          {verdict}. Updated {fmtRelativeTime(data.generated_at_utc)}.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs text-muted-foreground">Paper account</p>
            <p className="font-mono text-lg">
              {fmtUSD(paper.current_equity_usd)}
            </p>
            <p className={`font-mono text-xs ${pnlColorClass(paper.pnl_usd)}`}>
              {fmtUSD(paper.pnl_usd)} ({fmtPct(paper.return_pct, 2, true)})
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">SPY benchmark</p>
            <p className="font-mono text-lg">
              {fmtUSD(spy.current_price)}
            </p>
            <p className={`font-mono text-xs ${pnlColorClass(spy.return_pct)}`}>
              {fmtPct(spy.return_pct, 2, true)} over the same window
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Alpha</p>
            <p className={`font-mono text-lg ${alphaColor}`}>
              {fmtPct(alpha, 2, true)}
            </p>
            <p className="text-xs text-muted-foreground">
              paper return − SPY return
            </p>
          </div>
        </div>
        <p className="mt-4 text-xs text-muted-foreground">
          Run{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-xs">
            uv run python -m scripts.paper_vs_spy_snapshot
          </code>{" "}
          to refresh this comparison.
        </p>
      </CardContent>
    </Card>
  );
}
