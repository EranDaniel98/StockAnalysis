import { AlertTriangle, Rocket } from "lucide-react";

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
import { fetchMomvalPicks } from "@/lib/research/momval";
import { fmtNumber } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function MomvalBookPage() {
  const book = await fetchMomvalPicks();

  if (!book) {
    return (
      <div>
        <PageHeader
          title="Momentum-Value Book"
          description="Biggest-risers book — momentum 0.6 / value 0.4"
        />
        <Card>
          <CardContent className="py-10 text-center">
            <p className="text-muted-foreground text-sm">
              No picks yet. Generate them with:
            </p>
            <pre className="bg-muted/40 mt-3 inline-block rounded px-3 py-2 text-left font-mono text-xs">
              uv run python -m scripts.momval_picks
            </pre>
          </CardContent>
        </Card>
      </div>
    );
  }

  const w = book.weights;

  return (
    <div>
      <PageHeader
        title="Momentum-Value Book"
        description={`Biggest-risers book · momentum ${w.momentum ?? "?"} / value ${w.value ?? "?"} (quality + PEAD dropped) · PIT S&P 500 (${book.universe_size}) · as-of ${book.as_of}`}
        actions={
          <Badge variant="outline" className="gap-1.5">
            <Rocket className="h-3.5 w-3.5" />
            top {book.top_n}
          </Badge>
        }
      />

      {/* The defining risk caveat, kept next to the picks. */}
      <div className="border-border/40 bg-amber-500/10 mb-6 flex items-start gap-2 rounded-md border px-3 py-2 text-xs text-amber-200 dark:text-amber-300">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{book.horizon_note}</span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Today&apos;s biggest-riser candidates</CardTitle>
          <CardDescription>
            Ranked by the momentum-tilted composite z. Research lift ~2× vs
            random at catching top-decile risers (best at 3-6 months) — a tilt,
            not an oracle. Higher drawdown than the production blend.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <TableHead>Ticker</TableHead>
                <TableHead className="text-right">Composite z</TableHead>
                <TableHead className="text-right">Momentum rank</TableHead>
                <TableHead className="text-right">Value rank</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {book.picks.map((p) => (
                <TableRow key={p.ticker}>
                  <TableCell className="text-muted-foreground font-mono">
                    {p.rank ?? "—"}
                  </TableCell>
                  <TableCell className="font-mono font-medium">{p.ticker}</TableCell>
                  <TableCell className="text-right font-mono tabular-nums text-bullish">
                    {p.composite_z != null ? `+${fmtNumber(p.composite_z, 2)}` : "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-right font-mono tabular-nums">
                    {p.mom_rank ?? "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-right font-mono tabular-nums">
                    {p.val_rank ?? "—"}
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
