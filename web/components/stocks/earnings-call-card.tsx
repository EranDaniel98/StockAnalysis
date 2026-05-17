import { Calendar } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { ScanResultItem } from "@/lib/api/client";

/**
 * Next earnings-event card.
 *
 * Sources both timestamps from yfinance .info:
 *   - earnings_announcement_ts → typically 16:00 ET, after-close release
 *     of EPS + revenue numbers.
 *   - earnings_call_ts → typically 17:00 ET, management conference call
 *     with Q&A and forward guidance. This is the call that moves the
 *     stock; the user asked for it specifically.
 *
 * When yfinance has only an approximate window (sometimes for
 * upcoming-quarter dates that haven't been confirmed yet), shows
 * the window instead of a single timestamp.
 *
 * Renders nothing when no timestamp is known (returns null).
 */
/** Guard against the yfinance "NaN" string surviving _coerce_numeric.
 *  A NaN timestamp would render as the literal "Invalid Date" — that's
 *  worse than rendering nothing. */
function finiteOrNull(ts: number | null | undefined): number | null {
  return typeof ts === "number" && Number.isFinite(ts) ? ts : null;
}

export function EarningsCallCard({ rec }: { rec: ScanResultItem }) {
  const announcementTs = finiteOrNull(rec.earnings_announcement_ts);
  const callTs = finiteOrNull(rec.earnings_call_ts);
  const winStart = finiteOrNull(rec.earnings_window_start);
  const winEnd = finiteOrNull(rec.earnings_window_end);

  if (announcementTs == null && callTs == null && winStart == null) {
    return null;
  }

  const hasApproximateWindow =
    winStart != null && winEnd != null && winStart !== winEnd;

  const now = Date.now() / 1000;
  const eventTs = announcementTs ?? callTs ?? winStart;
  const isPast = eventTs != null && eventTs < now;
  const daysOut =
    eventTs != null ? Math.round((eventTs - now) / 86400) : null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-sm flex items-center gap-2">
              <Calendar className="h-4 w-4" />
              Next earnings event
            </CardTitle>
            <CardDescription className="text-xs mt-1">
              {isPast
                ? "Most recent report (next event not yet scheduled)"
                : daysOut != null
                  ? daysOut === 0
                    ? "Reports today"
                    : daysOut === 1
                      ? "Reports tomorrow"
                      : `In ${daysOut} days`
                  : "Upcoming"}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {hasApproximateWindow ? (
          <ApproximateWindow startTs={winStart!} endTs={winEnd!} />
        ) : (
          <>
            <Row
              label="Earnings release"
              ts={announcementTs}
              hint="EPS + revenue numbers drop, typically after market close."
            />
            <Row
              label="Conference call"
              ts={callTs}
              hint="Management Q&A + forward guidance. This is the call that moves the stock."
              emphasize
            />
          </>
        )}
      </CardContent>
    </Card>
  );
}


function Row({
  label,
  ts,
  hint,
  emphasize = false,
}: {
  label: string;
  ts: number | null | undefined;
  hint: string;
  emphasize?: boolean;
}) {
  if (ts == null) {
    return (
      <div>
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="text-muted-foreground">—</div>
      </div>
    );
  }
  const d = new Date(ts * 1000);
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={emphasize ? "font-mono font-semibold" : "font-mono"}>
        {formatLocal(d)}
        <span className="ml-2 text-xs text-muted-foreground">
          ({formatET(d)})
        </span>
      </div>
      <div className="text-xs text-muted-foreground mt-0.5">{hint}</div>
    </div>
  );
}


function ApproximateWindow({
  startTs,
  endTs,
}: {
  startTs: number;
  endTs: number;
}) {
  const start = new Date(startTs * 1000);
  const end = new Date(endTs * 1000);
  return (
    <div>
      <div className="text-xs text-muted-foreground">Approximate window</div>
      <div className="font-mono">
        {start.toLocaleDateString(undefined, {
          year: "numeric",
          month: "short",
          day: "2-digit",
        })}{" "}
        –{" "}
        {end.toLocaleDateString(undefined, {
          year: "numeric",
          month: "short",
          day: "2-digit",
        })}
      </div>
      <div className="text-xs text-muted-foreground mt-0.5">
        yfinance hasn&apos;t confirmed an exact date yet. The window
        narrows ~2 weeks before the call.
      </div>
    </div>
  );
}


/** "Mon, Jun 3, 2026 · 5:00 PM" in the user's locale + timezone. */
function formatLocal(d: Date): string {
  return d.toLocaleString(undefined, {
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
  });
}


/** "5:00 PM ET" — earnings times are always announced in ET, so we
 *  show the ET equivalent alongside the user's local time. */
function formatET(d: Date): string {
  return (
    d.toLocaleString("en-US", {
      timeZone: "America/New_York",
      hour: "numeric",
      minute: "2-digit",
    }) + " ET"
  );
}
