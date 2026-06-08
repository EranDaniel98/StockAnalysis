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
import { fetchForwardBook } from "@/lib/research/data";
import { fmtNumber, fmtPct, fmtUSD, pnlColorClass } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function MomvalBookPage() {
  const book = await fetchForwardBook("momval");

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
    </div>
  );
}
