"use client";

import { useQuery } from "@tanstack/react-query";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
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
import { api } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtDate, fmtNumber, fmtUSD } from "@/lib/format";

export default function RecommendationsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.recommendations.list({ limit: 100 }),
    queryFn: () => api.recommendations.list({ limit: 100 }),
  });

  return (
    <>
      <PageHeader
        title="Recommendations"
        description="Historical paper-trade recommendations from `paper trade` runs."
      />

      <Card>
        <CardHeader>
          <CardTitle>History</CardTitle>
          <CardDescription>
            {data ? `${data.length} entries` : "Loading…"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error ? <ErrorState error={error} /> : null}

          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !data || data.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              No paper-trade recommendations yet.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Strategy</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                  <TableHead className="text-right">Entry</TableHead>
                  <TableHead className="text-right">Stop</TableHead>
                  <TableHead className="text-right">Target</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="text-muted-foreground text-xs">
                      {fmtDate(r.scan_timestamp)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-mono">
                        {r.ticker}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {r.strategy}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          r.action === "BUY" || r.action === "STRONG BUY"
                            ? "default"
                            : "secondary"
                        }
                      >
                        {r.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtNumber(r.composite_score, 1)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtUSD(r.entry_price)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtUSD(r.stop_loss)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtUSD(r.take_profit)}
                    </TableCell>
                    <TableCell>
                      {r.submitted ? (
                        <Badge variant="default">submitted</Badge>
                      ) : r.skip_reason ? (
                        <span
                          className="text-muted-foreground text-xs"
                          title={r.skip_reason}
                        >
                          skipped
                        </span>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}
