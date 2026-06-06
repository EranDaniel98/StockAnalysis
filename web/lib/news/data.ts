/**
 * Server-side fetcher for /api/news — the aggregated market-moving news feed
 * (Polygon-sourced, deduped across bellwethers + holdings). Read in a server
 * component so the page renders without a client query.
 */

export type NewsSentiment = "positive" | "negative" | "neutral";

export type NewsInsight = {
  ticker: string;
  sentiment: NewsSentiment;
  reasoning: string | null;
};

export type NewsArticle = {
  id: string;
  title: string;
  publisher: string;
  author: string | null;
  published_utc: string;
  url: string;
  image_url: string | null;
  description: string | null;
  tickers: string[];
  sentiment: NewsSentiment | null;
  insights: NewsInsight[];
};

export type MarketNews = {
  generated_at: string;
  lookback_days: number;
  tickers_covered: string[];
  n_articles: number;
  sentiment_counts: Record<string, number>;
  articles: NewsArticle[];
};

export async function fetchMarketNews(
  lookbackDays = 4,
): Promise<MarketNews | null> {
  const base = process.env.NEXT_INTERNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const res = await fetch(
      `${base}/api/news?lookback_days=${lookbackDays}`,
      { cache: "no-store" },
    );
    if (!res.ok) return null;
    return (await res.json()) as MarketNews;
  } catch {
    return null;
  }
}
