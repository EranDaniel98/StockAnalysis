"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";

import { API_BASE } from "@/lib/api/client";

type TradeUpdate = {
  event: string;
  symbol: string;
  side: string;
  qty: number;
  filled_qty: number;
  filled_price: number | null;
  order_id: string;
  client_order_id: string | null;
  timestamp: string;
};

const SHOWN: Record<
  string,
  { title: (e: TradeUpdate) => string; type: "success" | "error" | "info" }
> = {
  fill: { title: (e) => `Filled ${e.side.toUpperCase()} ${e.symbol}`, type: "success" },
  partial_fill: {
    title: (e) => `Partial fill ${e.side.toUpperCase()} ${e.symbol}`,
    type: "info",
  },
  stop_loss_filled: {
    title: (e) => `Stop hit on ${e.symbol}`,
    type: "error",
  },
  take_profit_filled: {
    title: (e) => `Target hit on ${e.symbol}`,
    type: "success",
  },
  canceled: { title: (e) => `Canceled ${e.symbol}`, type: "info" },
  rejected: { title: (e) => `Rejected ${e.symbol}`, type: "error" },
  expired: { title: (e) => `Expired ${e.symbol}`, type: "info" },
};

function describe(e: TradeUpdate): string {
  const qty = e.filled_qty > 0 ? e.filled_qty : e.qty;
  const price =
    e.filled_price != null
      ? `@ $${e.filled_price.toFixed(2)}`
      : "";
  return `${qty} ${qty === 1 ? "share" : "shares"} ${price}`.trim();
}

/**
 * Mount-once subscriber that turns /api/stream/trade-updates events into
 * sonner toasts. Lives at the root layout level so notifications fire on
 * every page. Auto-deduplicates by order_id+event because Alpaca sometimes
 * re-emits the same fill on reconnect.
 */
export function TradeUpdateNotifier() {
  const seenRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const source = new EventSource(`${API_BASE}/api/stream/trade-updates`);

    source.addEventListener("update", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as TradeUpdate;
        const dedupeKey = `${data.order_id}:${data.event}`;
        if (seenRef.current.has(dedupeKey)) return;
        seenRef.current.add(dedupeKey);

        const mapped = SHOWN[data.event];
        if (!mapped) return; // skip new/replaced/etc.

        const title = mapped.title(data);
        const body = describe(data);
        if (mapped.type === "success") toast.success(title, { description: body });
        else if (mapped.type === "error") toast.error(title, { description: body });
        else toast(title, { description: body });
      } catch {
        // ignore malformed events
      }
    });

    source.addEventListener("error", () => {
      // Browser will reconnect automatically; nothing to do here. We
      // intentionally don't surface a toast — it would spam on every
      // network blip and the badge in /portfolio already shows infra state.
    });

    return () => source.close();
  }, []);

  return null;
}
