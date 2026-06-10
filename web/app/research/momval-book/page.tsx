import { AlertTriangle, Rocket } from "lucide-react";

import { ForwardBookTrack } from "@/components/forward-book-track";
import { PageHeader } from "@/components/page-header";
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
import { fetchForwardBook, fetchMomvalPicks } from "@/lib/research/data";
import { fmtNumber, fmtPct, fmtUSD, pnlColorClass } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function MomvalBookPage() {
  const [book, candidates] = await Promise.all([
    fetchForwardBook("momval"),
    fetchMomvalPicks(),
  ]);

  if (!book) {
    return (
      <div>
        <PageHeader
          title="Momentum-Value Book"
          description="Forward-paper biggest-risers book — momentum 0.6 / value 0.4"
        />
        <Card>
          <CardContent className="py-10 text-center">
            <p className="text-muted-foreground text-sm">
              No book state yet. Initialize it with:
            </p>
            <pre className="bg-muted/40 mt-3 inline-block rounded px-3 py-2 text-left font-mono text-xs">
              uv run python -m scripts.research.momval_forward_paper
            </pre>
          </CardContent>
        </Card>
      </div>
    );
  }

  const excess = book.excess_vs_spy_pct;

  return (
    <div>
      <PageHeader
        title="Momentum-Value Book"
        description={`Forward-paper biggest-risers book · momentum 0.6 / value 0.4 (quality + PEAD dropped) · PIT S&P 500 (${book.universe_n}) · top-${book.top_n}, rebalance every ${book.rebalance_days}td · local paper, no broker`}
        actions={
          <Badge variant="outline" className="gap-1.5">
            <Rocket className="h-3.5 w-3.5" />
            since {book.start_date}
          </Badge>
        }
      />

      <div className="border-border/40 bg-amber-500/10 mb-6 flex items-start gap-2 rounded-md border px-3 py-2 text-xs text-amber-200 dark:text-amber-300">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{book.risk_note}</span>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Book equity</CardDescription>
            <CardTitle className="font-mono text-2xl tabular-nums">
              {fmtUSD(book.equity)}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-muted-foreground text-xs">
            from {fmtUSD(book.baseline_equity)} ·{" "}
            <span className={pnlColorClass(book.ret_pct)}>
              {fmtPct(book.ret_pct, 2, true)}
            </span>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Excess vs SPY</CardDescription>
            <CardTitle
              className={`font-mono text-2xl tabular-nums ${pnlColorClass(excess)}`}
            >
              {fmtPct(excess, 2, true)}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-muted-foreground text-xs">
            book {fmtPct(book.ret_pct, 2, true)} · SPY {fmtPct(book.spy_ret_pct, 2, true)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Holdings</CardDescription>
            <CardTitle className="font-mono text-2xl tabular-nums">
              {book.n_holdings}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-muted-foreground text-xs">
            equal-weight · cash {fmtUSD(book.cash)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Track</CardDescription>
            <CardTitle className="font-mono text-2xl tabular-nums">
              {book.start_date}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-muted-foreground text-xs">
            last rebalance {book.last_rebalance ?? "—"} · marked {book.last_marked ?? "—"}
          </CardContent>
        </Card>
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">Book vs SPY since start</CardTitle>
          <CardDescription>
            Equal-weight book return vs SPY, marked each trading day.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ForwardBookTrack history={book.history} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Holdings</CardTitle>
          <CardDescription>
            Sorted by momentum-value composite rank. Research lift ~2× vs random
            at catching top-decile risers (best at 3-6 months) — a tilt, not an
            oracle, with higher drawdown than the production blend.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <TableHead>Ticker</TableHead>
                <TableHead className="text-right">Composite z</TableHead>
                <TableHead className="text-right">Since entry</TableHead>
                <TableHead className="text-right">Weight</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {book.holdings.map((h) => (
                <TableRow key={h.ticker}>
                  <TableCell className="text-muted-foreground font-mono">
                    {h.mom_rank ?? "—"}
                  </TableCell>
                  <TableCell className="font-mono font-medium">{h.ticker}</TableCell>
                  <TableCell className="text-bullish text-right font-mono tabular-nums">
                    {h.mom_z != null ? `+${fmtNumber(h.mom_z, 2)}` : "—"}
                  </TableCell>
                  <TableCell
                    className={`text-right font-mono tabular-nums ${pnlColorClass(h.since_entry_pct)}`}
                  >
                    {fmtPct(h.since_entry_pct, 2, true)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {fmtPct(h.weight_pct, 1)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {candidates && candidates.picks.length > 0 ? (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle className="text-base">
              Today&apos;s top-ranked candidates — why each ranks
            </CardTitle>
            <CardDescription>
              The mom-val composite re-ranked on {candidates.as_of} (drifts daily
              as prices/fundamentals move). <span className="text-bullish">held</span>{" "}
              = already in the book; <span className="text-muted-foreground">new</span>{" "}
              = ranks in today&apos;s top but not yet held (comes in at the next
              63-day rebalance). Each &ldquo;why&rdquo; is grounded ONLY in the
              factor ranks + EDGAR point-in-time fundamentals shown
              {candidates.ai_model ? ` (${candidates.ai_model})` : ""} — not advice,
              and never invented. EDGAR carries no price-derived ratios (P/E etc.),
              so they are intentionally absent.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {candidates.dispersion_guard ? (
              candidates.dispersion_guard.caution ? (
                <div className="border-border/40 bg-amber-500/10 flex items-start gap-2 rounded-md border px-3 py-2 text-xs text-amber-200 dark:text-amber-300">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    <span className="font-medium">Low-confidence regime.</span>{" "}
                    {candidates.dispersion_guard.note} Momentum dispersion{" "}
                    {fmtNumber(candidates.dispersion_guard.mom_dispersion_iqr, 3)} = percentile{" "}
                    {Math.round(candidates.dispersion_guard.percentile_2018_2026 * 100)}{" "}
                    of 2018-2026.
                  </span>
                </div>
              ) : (
                <p className="text-muted-foreground text-xs">
                  Dispersion guard: momentum dispersion{" "}
                  {fmtNumber(candidates.dispersion_guard.mom_dispersion_iqr, 3)} (percentile{" "}
                  {Math.round(candidates.dispersion_guard.percentile_2018_2026 * 100)}{" "}
                  of 2018-2026) — regime in which the selection edge was
                  historically present.
                </p>
              )
            ) : null}
            {(() => {
              const held = new Set(book.holdings.map((h) => h.ticker));
              const fundChips = (p: (typeof candidates.picks)[number]) =>
                (
                  [
                    ["12-1 ret", p.trailing_12_1],
                    ["rev gr", p.revenue_growth_yoy],
                    ["EPS gr", p.earnings_growth_yoy],
                    ["margin", p.profit_margin],
                    ["op margin", p.operating_margin],
                    ["div yld", p.dividend_yield],
                  ] as const
                )
                  .filter(([, v]) => v != null)
                  .map(([label, v]) => (
                    <span
                      key={label}
                      className="bg-muted/40 rounded px-1.5 py-0.5 font-mono text-[11px]"
                    >
                      <span className="text-muted-foreground">{label} </span>
                      <span className={pnlColorClass((v as number))}>
                        {fmtPct((v as number) * 100, 0, true)}
                      </span>
                    </span>
                  ));
              return candidates.picks.map((p) => {
                const isHeld = held.has(p.ticker);
                const chips = fundChips(p);
                return (
                  <div
                    key={p.ticker}
                    className="border-border/40 rounded-md border px-3 py-2.5"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <div className="flex items-baseline gap-2">
                        <span className="text-muted-foreground font-mono text-xs">
                          #{p.rank ?? "—"}
                        </span>
                        <span className="font-mono font-medium">{p.ticker}</span>
                        {p.name ? (
                          <span className="text-muted-foreground truncate text-xs">
                            {p.name}
                          </span>
                        ) : null}
                        {isHeld ? (
                          <span className="text-bullish text-xs font-medium">held</span>
                        ) : (
                          <span className="text-muted-foreground text-xs">new</span>
                        )}
                      </div>
                      <div className="text-muted-foreground shrink-0 font-mono text-xs tabular-nums">
                        z{" "}
                        <span className="text-bullish">
                          {p.composite_z != null ? `+${fmtNumber(p.composite_z, 2)}` : "—"}
                        </span>{" "}
                        · mom {p.mom_rank ?? "—"} · val {p.val_rank ?? "—"}
                      </div>
                    </div>
                    {p.why ? (
                      <p className="text-foreground/90 mt-1.5 text-sm">{p.why}</p>
                    ) : null}
                    {chips.length > 0 ? (
                      <div className="mt-1.5 flex flex-wrap gap-1">{chips}</div>
                    ) : null}
                  </div>
                );
              });
            })()}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
