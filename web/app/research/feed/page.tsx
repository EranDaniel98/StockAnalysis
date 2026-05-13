"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type FilingNotificationItem } from "@/lib/api/client";
import { fmtDate } from "@/lib/format";
import {
  subscribeNotifications,
  toListItem,
} from "@/lib/api/notifications-stream";

function formBadge(form: string) {
  // 8-K is the high-signal form (material events). 10-K/10-Q are routine.
  if (form === "8-K")
    return <Badge variant="default" className="font-mono">{form}</Badge>;
  if (form === "10-K")
    return <Badge variant="neutral" className="font-mono">{form}</Badge>;
  if (form === "10-Q")
    return <Badge variant="neutral" className="font-mono">{form}</Badge>;
  return <Badge variant="secondary" className="font-mono">{form}</Badge>;
}

export default function ResearchFeedPage() {
  const queryClient = useQueryClient();
  const [liveCount, setLiveCount] = useState(0);

  const notifications = useQuery({
    queryKey: ["research", "notifications"],
    queryFn: () => api.research.notifications({ limit: 50 }),
  });

  const status = useQuery({
    queryKey: ["research", "monitor", "status"],
    queryFn: () => api.research.monitorStatus(),
    refetchInterval: 30_000,
  });

  // Subscribe once on mount. EventSource auto-reconnects on transient
  // network errors, so we don't manage retries here.
  const seenIdsRef = useRef<Set<number>>(new Set());
  useEffect(() => {
    const es = subscribeNotifications((payload) => {
      // Optimistic prepend so the page updates without a full refetch —
      // useQuery's cache writer is the source of truth.
      if (seenIdsRef.current.has(payload.id)) return;
      seenIdsRef.current.add(payload.id);
      setLiveCount((c) => c + 1);
      queryClient.setQueryData<FilingNotificationItem[]>(
        ["research", "notifications"],
        (prev) => {
          const next = prev ? [...prev] : [];
          if (next.find((n) => n.id === payload.id)) return next;
          return [toListItem(payload), ...next].slice(0, 100);
        },
      );
    });
    return () => es.close();
  }, [queryClient]);

  const formStats = useMemo(() => {
    const list = notifications.data ?? [];
    const total = list.length;
    const counts = new Map<string, number>();
    for (const n of list) {
      counts.set(n.form, (counts.get(n.form) ?? 0) + 1);
    }
    let topForm: string | null = null;
    let topCount = 0;
    for (const [form, count] of counts) {
      if (count > topCount) {
        topForm = form;
        topCount = count;
      }
    }
    const pct = total > 0 ? (topCount / total) * 100 : 0;
    return { total, topForm, topCount, pct };
  }, [notifications.data]);

  // 8-K's high-signal severity shows via the value color (text-primary);
  // 10-K/10-Q stay foreground-toned.
  const topFormValueClass =
    formStats.topForm === "8-K" ? "text-primary" : "text-foreground";

  const pollMin = status.data
    ? Math.round(status.data.poll_seconds / 60)
    : null;

  const newCountSegment =
    liveCount > 0
      ? `${liveCount} new since page load`
      : "no new filings this session";

  return (
    <>
      <PageHeader
        title="Filing feed"
        description="Background monitor polls EDGAR for new 8-K / 10-K / 10-Q filings on your holdings. New filings get ingested into the RAG corpus automatically."
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <ScoreboardTile
          label="Monitor"
          value={
            status.isLoading
              ? "—"
              : status.data?.running
                ? "ON"
                : "OFF"
          }
          sub={
            status.isLoading
              ? undefined
              : status.data?.running
                ? `polling every ${pollMin}m`
                : "stopped"
          }
          subTone={
            status.isLoading
              ? "muted"
              : status.data?.running
                ? "muted"
                : "bearish"
          }
          isLoading={status.isLoading}
        />
        <ScoreboardTile
          label="Total filings"
          value={notifications.isLoading ? "—" : String(formStats.total)}
          sub={
            notifications.isLoading
              ? undefined
              : formStats.total >= 50
                ? "capped at 50"
                : `last ${formStats.total} filings`
          }
          subTone="muted"
          isLoading={notifications.isLoading}
        />
        <ScoreboardTile
          label="New this session"
          value={
            <span className={liveCount > 0 ? "text-primary" : undefined}>
              {liveCount}
            </span>
          }
          sub="via SSE"
          subTone="muted"
        />
        <ScoreboardTile
          label="By form"
          value={
            notifications.isLoading || !formStats.topForm ? (
              "—"
            ) : (
              <span className={`font-mono ${topFormValueClass}`}>
                {formStats.topForm}
              </span>
            )
          }
          sub={
            notifications.isLoading || !formStats.topForm
              ? undefined
              : `${formStats.topCount} · ${formStats.pct.toFixed(0)}%`
          }
          subTone="muted"
          isLoading={notifications.isLoading}
        />
      </div>

      <div className="mt-4 space-y-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-3">
              <span>Monitor status</span>
              {status.data?.running ? (
                <Badge variant="bullish">running</Badge>
              ) : (
                <Badge variant="secondary">stopped</Badge>
              )}
            </CardTitle>
            <CardDescription className="font-mono text-xs">
              {status.data ? (
                <>
                  polling every {pollMin}m · forms:{" "}
                  {status.data.forms.join(", ")} ·{" "}
                  <span
                    className={
                      liveCount > 0 ? "text-primary" : "text-muted-foreground"
                    }
                  >
                    {newCountSegment}
                  </span>
                </>
              ) : (
                "loading status…"
              )}
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent notifications</CardTitle>
            <CardDescription>
              Newest first. Click{" "}
              <code className="font-mono text-foreground">Summarize</code> to
              spawn an agent run that grounds itself in this filing's chunks.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {notifications.error ? (
              <ErrorState error={notifications.error} />
            ) : null}
            {notifications.isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : notifications.data && notifications.data.length > 0 ? (
              <ul className="space-y-3">
                {notifications.data.map((n) => (
                  <NotificationRow key={n.id} notification={n} />
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground text-sm py-8 text-center font-mono">
                No notifications yet. The monitor fires only for filings that
                appear after first observation per ticker — the first poll sets
                the watermark.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function NotificationRow({ notification }: { notification: FilingNotificationItem }) {
  const queryClient = useQueryClient();
  const [summary, setSummary] = useState<string | null>(notification.summary ?? null);

  const summarize = useMutation({
    mutationFn: () => api.research.summarizeNotification(notification.id),
    onSuccess: (data) => {
      setSummary(data.notification.summary ?? null);
      queryClient.invalidateQueries({ queryKey: ["research"] });
    },
  });

  return (
    <li className="border border-border rounded p-3 hover:bg-muted/40 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold tracking-wider text-foreground">
              {notification.ticker}
            </span>
            {formBadge(notification.form)}
            <span className="font-mono text-xs text-muted-foreground tabular-nums">
              filed {notification.filing_date}
            </span>
          </div>
          <p className="font-mono text-muted-foreground mt-1 text-xs tabular-nums">
            Detected {fmtDate(notification.detected_at)} · accession{" "}
            {notification.accession_no}
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="font-mono text-xs"
          disabled={summarize.isPending}
          onClick={() => summarize.mutate()}
        >
          {summarize.isPending
            ? "Summarizing…"
            : summary
              ? "Re-summarize"
              : "Summarize"}
        </Button>
      </div>
      {summary ? (
        <Card className="mt-3">
          <CardContent className="pt-3 text-sm text-foreground whitespace-pre-wrap">
            {summary}
          </CardContent>
        </Card>
      ) : null}
      {summarize.error ? (
        <p className="text-bearish mt-2 text-sm font-mono">
          {(summarize.error as Error).message}
        </p>
      ) : null}
    </li>
  );
}
