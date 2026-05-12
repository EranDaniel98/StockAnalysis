/**
 * Native EventSource consumer for /api/research/notifications/stream.
 *
 * Unlike the research POST endpoint (which needs a body so we use
 * fetch), this stream is GET-only and idempotent — perfect for the
 * built-in EventSource API. Browsers handle reconnect automatically.
 */

import type { FilingNotificationItem } from "./client";
import { API_BASE } from "./client";

export type NotificationStreamEvent =
  | { event: "notification"; payload: NotificationPayload }
  | { event: "heartbeat" };

export interface NotificationPayload {
  id: number;
  ticker: string;
  form: string;
  accession_no: string;
  filing_date: string;
  primary_document: string | null;
  detected_at: string;
}

/**
 * Subscribe to the live notification feed. Returns the EventSource so
 * the caller can call ``.close()`` on unmount.
 */
export function subscribeNotifications(
  onNotification: (n: NotificationPayload) => void,
  onError?: (err: Event) => void,
): EventSource {
  const es = new EventSource(`${API_BASE}/api/research/notifications/stream`);

  es.addEventListener("notification", (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data) as NotificationPayload;
      onNotification(data);
    } catch {
      // Malformed payload — drop silently; server logs the raw form.
    }
  });

  if (onError) {
    es.addEventListener("error", onError);
  }

  return es;
}

export function toListItem(p: NotificationPayload): FilingNotificationItem {
  return {
    id: p.id,
    ticker: p.ticker,
    form: p.form,
    accession_no: p.accession_no,
    filing_date: p.filing_date,
    primary_document: p.primary_document,
    detected_at: p.detected_at,
    research_run_id: null,
    summary: null,
  };
}
