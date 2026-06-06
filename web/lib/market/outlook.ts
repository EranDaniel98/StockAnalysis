/**
 * Server-side fetcher for /api/market/outlook — the directional "lean" read
 * (trend + VIX + news sentiment + after-hours) plus the pre/post-market moves
 * behind it. Conditions, not a forecast (the caveat ships in the payload).
 */

export type Tilt = "bullish" | "bearish" | "neutral";
export type Lean = "risk_on" | "neutral" | "risk_off";

export type OutlookSignal = {
  name: string;
  detail: string;
  tilt: Tilt;
};

export type PrePostMove = {
  ticker: string;
  session_date: string;
  last_close: number | null;
  premarket_pct: number | null;
  afterhours_pct: number | null;
};

export type MarketOutlook = {
  as_of: string;
  session_date: string;
  lean: Lean;
  lean_score: number;
  n_bullish: number;
  n_bearish: number;
  signals: OutlookSignal[];
  prepost: PrePostMove[];
  news_sentiment: Record<string, number>;
  caveat: string;
};

export async function fetchOutlook(): Promise<MarketOutlook | null> {
  const base = process.env.NEXT_INTERNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const res = await fetch(`${base}/api/market/outlook`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as MarketOutlook;
  } catch {
    return null;
  }
}
