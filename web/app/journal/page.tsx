"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api, type PaperTradeItem } from "@/lib/api/client";
import { fmtDate, fmtNumber, fmtPct, fmtUSD, pnlColorClass } from "@/lib/format";

type Filters = {
  ticker: string;
  min_score: string;
  has_notes: "" | "true" | "false";
};

export default function JournalPage() {
  const qc = useQueryClient();
  const [filters, setFilters] = useState<Filters>({
    ticker: "",
    min_score: "",
    has_notes: "",
  });
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<string>("");

  const queryKey = [
    "trades",
    filters.ticker,
    filters.min_score,
    filters.has_notes,
  ] as const;

  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: () =>
      api.trades.list({
        ticker: filters.ticker || undefined,
        min_score: filters.min_score ? Number(filters.min_score) : undefined,
        has_notes: filters.has_notes === "" ? undefined : filters.has_notes === "true",
        limit: 200,
      }),
  });

  const saveNotes = useMutation({
    mutationFn: (vars: { id: number; notes: string | null }) =>
      api.trades.updateNotes(vars.id, { notes: vars.notes }),
    onSuccess: () => {
      toast.success("Notes saved");
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["trades"] });
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Failed to save");
    },
  });

  function startEditing(t: PaperTradeItem) {
    setEditing(t.id);
    setDraft(t.notes ?? "");
  }

  function commit(id: number) {
    saveNotes.mutate({ id, notes: draft.trim() || null });
  }

  return (
    <>
      <PageHeader
        title="Trade journal"
        description="Closed paper trades with editable notes. Search by ticker, score floor, or notes presence."
      />

      <Card className="mb-4">
        <CardContent className="grid gap-3 py-4 md:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="f-ticker">Ticker</Label>
            <Input
              id="f-ticker"
              placeholder="AAPL"
              value={filters.ticker}
              onChange={(e) =>
                setFilters((f) => ({ ...f, ticker: e.target.value.toUpperCase() }))
              }
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="f-score">Min score</Label>
            <Input
              id="f-score"
              type="number"
              min={0}
              max={100}
              placeholder="0"
              value={filters.min_score}
              onChange={(e) =>
                setFilters((f) => ({ ...f, min_score: e.target.value }))
              }
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="f-notes">Notes</Label>
            <select
              id="f-notes"
              className="border-input bg-background h-9 w-full rounded-md border px-3 text-sm"
              value={filters.has_notes}
              onChange={(e) =>
                setFilters((f) => ({
                  ...f,
                  has_notes: e.target.value as Filters["has_notes"],
                }))
              }
            >
              <option value="">Any</option>
              <option value="true">With notes</option>
              <option value="false">Without notes</option>
            </select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Trades</CardTitle>
          <CardDescription>
            {data ? `${data.length} matching trades` : "Loading…"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error ? <ErrorState error={error} /> : null}

          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !data || data.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              No matching trades. Adjust filters or run paper trade + evaluate.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Exit</TableHead>
                  <TableHead>Ticker</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Entry</TableHead>
                  <TableHead className="text-right">Exit</TableHead>
                  <TableHead className="text-right">P&amp;L %</TableHead>
                  <TableHead className="text-right">Hold</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead className="min-w-[240px]">Notes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="text-muted-foreground text-xs">
                      {fmtDate(t.exit_at)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-mono">
                        {t.ticker}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtNumber(t.qty, 0)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtUSD(t.entry_price)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtUSD(t.exit_price)}
                    </TableCell>
                    <TableCell
                      className={`text-right tabular-nums ${pnlColorClass(t.pnl_pct)}`}
                    >
                      {fmtPct(t.pnl_pct, 1, true)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {t.hold_days ?? "—"}d
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtNumber(t.composite_score, 1)}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {t.exit_reason ?? "—"}
                    </TableCell>
                    <TableCell>
                      {editing === t.id ? (
                        <div className="flex items-start gap-1">
                          <Textarea
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            rows={2}
                            autoFocus
                            className="min-h-[60px] flex-1 text-xs"
                            onKeyDown={(e) => {
                              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                                e.preventDefault();
                                commit(t.id);
                              } else if (e.key === "Escape") {
                                setEditing(null);
                              }
                            }}
                          />
                          <div className="flex flex-col gap-1">
                            <Button
                              size="icon"
                              variant="ghost"
                              onClick={() => commit(t.id)}
                              disabled={saveNotes.isPending}
                              aria-label="Save"
                            >
                              <Check className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              onClick={() => setEditing(null)}
                              aria-label="Cancel"
                            >
                              <X className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => startEditing(t)}
                          className="hover:bg-muted/40 group flex w-full items-start justify-between gap-2 rounded p-1 text-left text-xs"
                        >
                          <span
                            className={
                              t.notes
                                ? "text-foreground"
                                : "text-muted-foreground italic"
                            }
                          >
                            {t.notes || "Add note…"}
                          </span>
                          <Pencil className="text-muted-foreground h-3 w-3 opacity-0 group-hover:opacity-70" />
                        </button>
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
