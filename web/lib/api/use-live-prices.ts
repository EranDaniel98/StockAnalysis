"use client";

import { useEffect, useState } from "react";

import { API_BASE } from "./client";

export type LivePrice = {
  price: number;
  timestamp: string;
};

export type LivePriceMap = Record<string, LivePrice | undefined>;

/**
 * Subscribe to /api/stream/prices for the given symbols. Returns a map of
 * symbol → latest trade. Reconnects automatically when EventSource emits
 * its native error (the browser handles backoff internally).
 *
 * `symbols` is intentionally a string[] — the hook joins + sorts internally
 * so callers can pass the raw list from positions without memoizing.
 */
export function useLivePrices(symbols: string[]): {
  prices: LivePriceMap;
  connected: boolean;
  error: string | null;
} {
  const [prices, setPrices] = useState<LivePriceMap>({});
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sorted-comma key so symbol-set churn doesn't restart on every render.
  const subscribeKey = [...new Set(symbols.map((s) => s.toUpperCase()))]
    .sort()
    .join(",");

  useEffect(() => {
    if (!subscribeKey) {
      setPrices({});
      setConnected(false);
      return;
    }

    const url = `${API_BASE}/api/stream/prices?symbols=${encodeURIComponent(subscribeKey)}`;
    const source = new EventSource(url);

    source.addEventListener("open", () => {
      setConnected(true);
      setError(null);
    });

    source.addEventListener("trade", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as {
          symbol: string;
          price: number;
          timestamp: string;
        };
        setPrices((prev) => ({
          ...prev,
          [data.symbol]: { price: data.price, timestamp: data.timestamp },
        }));
      } catch {
        // Bad payload — ignore; the next trade will be cleaner.
      }
    });

    source.addEventListener("error", (e) => {
      const data = (e as MessageEvent).data;
      if (typeof data === "string" && data.length > 0) {
        try {
          const parsed = JSON.parse(data) as { detail?: string };
          if (parsed.detail) {
            setError(parsed.detail);
            source.close();
            return;
          }
        } catch {
          // fall through to the generic disconnected state
        }
      }
      // Default browser-reported error — EventSource will reconnect itself.
      setConnected(false);
    });

    return () => {
      source.close();
      setConnected(false);
    };
  }, [subscribeKey]);

  return { prices, connected, error };
}
