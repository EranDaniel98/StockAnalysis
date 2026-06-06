/**
 * Server-side fetchers for /api/research forward-paper books.
 *
 * These are the LOCAL virtual momentum books (trend_forward_paper and its
 * --book variants), marked to live Polygon prices and isolated from the
 * live Alpaca run. Server components read them over HTTP so a page renders
 * with no client-side query.
 */

export type ForwardBookHolding = {
  ticker: string;
  mom_rank: number | null;
  mom_raw: number | null;
  mom_z: number | null;
  entry_px: number;
  last_px: number;
  entry_date: string | null;
  since_entry_pct: number | null;
  weight_pct: number | null;
};

export type ForwardBookMark = {
  date: string;
  equity: number;
  ret_pct: number | null;
  spy_ret_pct: number | null;
  excess_vs_spy_pct: number | null;
};

export type ForwardBook = {
  book: string;
  strategy: string;
  universe_file: string;
  universe_n: number;
  top_n: number;
  rebalance_days: number;
  cost_bps: number;
  start_date: string;
  baseline_equity: number;
  last_rebalance: string | null;
  last_marked: string | null;
  equity: number;
  cash: number;
  ret_pct: number | null;
  spy_ret_pct: number | null;
  excess_vs_spy_pct: number | null;
  n_holdings: number;
  holdings: ForwardBookHolding[];
  history: ForwardBookMark[];
  risk_note: string;
};

/**
 * Fetch one forward book by --book name ("ai", "default", …). Returns null
 * on any failure (API down, 404 = book not initialized, parse error) so the
 * page can render an empty state instead of throwing.
 */
export async function fetchForwardBook(book: string): Promise<ForwardBook | null> {
  const base = process.env.NEXT_INTERNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const res = await fetch(`${base}/api/research/${encodeURIComponent(book)}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as ForwardBook;
  } catch {
    return null;
  }
}
