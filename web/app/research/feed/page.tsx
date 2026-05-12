"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

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
import { Skeleton } from "@/components/ui/skeleton";
import { api, type FilingNotificationItem } from "@/lib/api/client";
import {
  subscribeNotifications,
  toListItem,
} from "@/lib/api/notifications-stream";

function formBadge(form: string) {
  // 8-K is the high-signal form (material events). 10-K/10-Q are routine.
  if (form === "8-K")
    return <Badge className="bg-amber-500/20 text-amber-300">{form}</Badge>;
  if (form === "10-K")
    return <Badge className="bg-sky-500/20 text-sky-300">{form}</Badge>;
  if (form === "10-Q")
    return <Badge className="bg-emerald-500/20 text-emerald-300">{form}</Badge>;
  return <Badge className="bg-muted text-muted-foreground">{form}</Badge>;
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

  return (
    <>
      <PageHeader
        title="Filing feed"
        description="Background monitor polls EDGAR for new 8-K / 10-K / 10-Q filings on your holdings. New filings get ingested into the RAG corpus automatically."
      />

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-3">
              <span>Monitor status</span>
              {status.data?.running ? (
                <Badge className="bg-emerald-500/20 text-emerald-300">
                  running
                </Badge>
              ) : (
                <Badge className="bg-muted text-muted-foreground">
                  stopped
                </Badge>
              )}
            </CardTitle>
            <CardDescription>
              {status.data ? (
                <>
                  Polling every {Math.round(status.data.poll_seconds / 60)}{" "}
                  min · forms: {status.data.forms.join(", ")} ·{" "}
                  {liveCount > 0
                    ? `${liveCount} new since page load`
                    : "no new filings this session"}
                </>
              ) : (
                "Loading status…"
              )}
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent notifications</CardTitle>
            <CardDescription>
              Newest first. Click <em>Summarize</em> to spawn an agent run
              that grounds itself in this filing's chunks.
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
              <p className="text-muted-foreground text-sm">
                No notifications yet. The monitor only fires for filings
                that appear <em>after</em> first observation per ticker —
                so the very first poll just sets the watermark.
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
    <li className="border-border/40 rounded border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold">{notification.ticker}</span>
            {formBadge(notification.form)}
            <span className="text-muted-foreground text-xs">
              filed {notification.filing_date}
            </span>
          </div>
          <p className="text-muted-foreground mt-1 text-xs">
            Detected {new Date(notification.detected_at).toLocaleString()} ·
            accession {notification.accession_no}
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
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
          <CardContent className="prose prose-invert max-w-none pt-3 text-sm whitespace-pre-wrap">
            {summary}
          </CardContent>
        </Card>
      ) : null}
      {summarize.error ? (
        <p className="text-red-300 mt-2 text-sm">
          {(summarize.error as Error).message}
        </p>
      ) : null}
    </li>
  );
}
