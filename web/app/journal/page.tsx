"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, X } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { cn } from "@/lib/utils";

type Filters = {
  ticker: string;
  min_score: string;
  has_notes: "" | "true" | "false";
};

const LABEL_CLASS =
  "text-[10px] font-medium tracking-wider uppercase text-muted-foreground";
const HEAD_CLASS =
  "text-[10px] font-medium tracking-wider uppercase text-muted-foreground py-2 px-3";

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

  const stats = useMemo(() => {
    const trades = data ?? [];
    const total = trades.length;
    let wins = 0;
    let losses = 0;
    let pnlSum = 0;
    let pnlCount = 0;
    let best: number | null = null;
    let worst: number | null = null;
    let withNotes = 0;
    for (const t of trades) {
      const p = t.pnl_pct;
      if (p !== null && p !== undefined && !Number.isNaN(p)) {
        if (p > 0) wins += 1;
        else if (p < 0) losses += 1;
        pnlSum += p;
        pnlCount += 1;
        if (best === null || p > best) best = p;
        if (worst === null || p < worst) worst = p;
      }
      if (t.notes && t.notes.trim().length > 0) withNotes += 1;
    }
    const winRate = wins + losses > 0 ? (wins / (wins + losses)) * 100 : 0;
    const avgPnl = pnlCount > 0 ? pnlSum / pnlCount : null;
    const notesPct = total > 0 ? (withNotes / total) * 100 : 0;
    return { total, wins, losses, winRate, avgPnl, best, worst, withNotes, notesPct };
  }, [data]);

  const winRateTone: "bullish" | "bearish" | "neutral" =
    stats.wins + stats.losses === 0
      ? "neutral"
      : stats.winRate >= 50
        ? "bullish"
        : stats.winRate < 40
          ? "bearish"
          : "neutral";

  const avgPnlTone = pnlColorClass(stats.avgPnl);

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

      {error ? <ErrorState error={error} /> : null}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <ScoreboardTile
          label="Closed trades"
          value={isLoading ? "—" : String(stats.total)}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Win rate"
          value={
            isLoading ? (
              "—"
            ) : (
              <span className={cn(winRateTone === "bullish" && "text-bullish", winRateTone === "bearish" && "text-bearish")}>
                {stats.wins + stats.losses === 0
                  ? "—"
                  : `${stats.winRate.toFixed(1)}%`}
              </span>
            )
          }
          sub={
            isLoading
              ? undefined
              : `${stats.wins}W / ${stats.losses}L`
          }
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Avg P&L"
          value={
            isLoading ? (
              "—"
            ) : (
              <span className={avgPnlTone}>
                {stats.avgPnl === null ? "—" : fmtPct(stats.avgPnl, 1, true)}
              </span>
            )
          }
          sub={
            isLoading || stats.best === null || stats.worst === null
              ? undefined
              : `${fmtPct(stats.best, 1, true)} / ${fmtPct(stats.worst, 1, true)}`
          }
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="With notes"
          value={isLoading ? "—" : String(stats.withNotes)}
          sub={
            isLoading || stats.total === 0
              ? undefined
              : `${stats.notesPct.toFixed(0)}% coverage`
          }
          subTone="muted"
          isLoading={isLoading}
        />
      </div>

      <Card className="mt-4 mb-4">
        <CardContent className="grid gap-3 py-3 md:grid-cols-4">
          <div className="space-y-1.5">
            <label htmlFor="f-ticker" className={LABEL_CLASS}>
              Ticker
            </label>
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
            <label htmlFor="f-score" className={LABEL_CLASS}>
              Min score
            </label>
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
            <label htmlFor="f-notes" className={LABEL_CLASS}>
              Notes
            </label>
            <Select
              value={filters.has_notes}
              onValueChange={(v) =>
                setFilters((f) => ({
                  ...f,
                  has_notes: (v ?? "") as Filters["has_notes"],
                }))
              }
            >
              <SelectTrigger id="f-notes" className="w-full">
                <SelectValue placeholder="Any" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">Any</SelectItem>
                <SelectItem value="true">With notes</SelectItem>
                <SelectItem value="false">Without notes</SelectItem>
              </SelectContent>
            </Select>
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
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-2 p-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-7 w-full" />
              ))}
            </div>
          ) : !data || data.length === 0 ? (
            <p className="text-muted-foreground text-sm py-12 text-center font-mono">
              No matching trades. Adjust filters or run paper trade + evaluate.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className={HEAD_CLASS}>Exit</TableHead>
                  <TableHead className={HEAD_CLASS}>Ticker</TableHead>
                  <TableHead className={cn(HEAD_CLASS, "text-right")}>Qty</TableHead>
                  <TableHead className={cn(HEAD_CLASS, "text-right")}>Entry</TableHead>
                  <TableHead className={cn(HEAD_CLASS, "text-right")}>Exit</TableHead>
                  <TableHead className={cn(HEAD_CLASS, "text-right")}>P&amp;L %</TableHead>
                  <TableHead className={cn(HEAD_CLASS, "text-right")}>Hold</TableHead>
                  <TableHead className={cn(HEAD_CLASS, "text-right")}>Score</TableHead>
                  <TableHead className={HEAD_CLASS}>Reason</TableHead>
                  <TableHead className={cn(HEAD_CLASS, "min-w-[240px]")}>Notes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((t) => {
                  const score = t.composite_score;
                  const scoreTone =
                    score === null || score === undefined || Number.isNaN(score)
                      ? "text-muted-foreground"
                      : score >= 60
                        ? "text-bullish"
                        : score <= 40
                          ? "text-bearish"
                          : "text-neutral";
                  return (
                    <TableRow
                      key={t.id}
                      className="hover:bg-muted/40 border-b border-border last:border-b-0"
                    >
                      <TableCell className="text-muted-foreground text-xs py-2 px-3">
                        {fmtDate(t.exit_at)}
                      </TableCell>
                      <TableCell className="py-2 px-3">
                        <span className="font-mono text-sm font-semibold">
                          {t.ticker}
                        </span>
                      </TableCell>
                      <TableCell className="font-mono tabular-nums text-right py-2 px-3">
                        {fmtNumber(t.qty, 0)}
                      </TableCell>
                      <TableCell className="font-mono tabular-nums text-right py-2 px-3">
                        {fmtUSD(t.entry_price)}
                      </TableCell>
                      <TableCell className="font-mono tabular-nums text-right py-2 px-3">
                        {fmtUSD(t.exit_price)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          "font-mono tabular-nums text-right py-2 px-3",
                          pnlColorClass(t.pnl_pct),
                        )}
                      >
                        {fmtPct(t.pnl_pct, 1, true)}
                      </TableCell>
                      <TableCell className="font-mono tabular-nums text-right py-2 px-3">
                        {t.hold_days ?? "—"}d
                      </TableCell>
                      <TableCell
                        className={cn(
                          "font-mono tabular-nums text-right py-2 px-3",
                          scoreTone,
                        )}
                      >
                        {fmtNumber(t.composite_score, 1)}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs uppercase tracking-wider py-2 px-3">
                        {t.exit_reason ?? "—"}
                      </TableCell>
                      <TableCell className="py-2 px-3 min-w-[240px]">
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
                                className="text-bullish"
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
                            className="hover:bg-muted/40 group flex w-full items-start justify-between gap-2 rounded p-1 text-left"
                          >
                            <span
                              className={
                                t.notes
                                  ? "text-foreground text-xs"
                                  : "text-muted-foreground/60 italic text-xs"
                              }
                            >
                              {t.notes || "Add note…"}
                            </span>
                            <Pencil className="text-muted-foreground h-3 w-3 opacity-0 group-hover:opacity-70" />
                          </button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}
