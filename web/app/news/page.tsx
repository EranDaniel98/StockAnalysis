import { ArrowUpRight, Newspaper, TrendingDown, TrendingUp } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { fetchMarketNews, type NewsArticle } from "@/lib/news/data";
import { fmtRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

const SENTIMENT_STYLE: Record<string, string> = {
  positive: "text-bullish border-bullish/40",
  negative: "text-bearish border-bearish/40",
  neutral: "text-muted-foreground border-border",
};

function SentimentBadge({ sentiment }: { sentiment: string | null }) {
  if (!sentiment) return null;
  return (
    <Badge
      variant="outline"
      className={cn("text-[10px] uppercase", SENTIMENT_STYLE[sentiment])}
    >
      {sentiment}
    </Badge>
  );
}

function ArticleCard({ article }: { article: NewsArticle }) {
  return (
    <Card className="hover:border-border/80 transition-colors">
      <CardContent className="flex gap-4 py-4">
        {article.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={article.image_url}
            alt=""
            className="hidden h-20 w-28 shrink-0 rounded object-cover sm:block"
          />
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="text-muted-foreground mb-1 flex items-center gap-2 text-xs">
            <span className="font-medium">{article.publisher}</span>
            <span>·</span>
            <span>{fmtRelativeTime(article.published_utc)}</span>
            <SentimentBadge sentiment={article.sentiment} />
          </div>
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-start gap-1 font-medium leading-snug hover:underline"
          >
            {article.title}
            <ArrowUpRight className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-60" />
          </a>
          {article.description ? (
            <p className="text-muted-foreground mt-1 line-clamp-2 text-xs">
              {article.description}
            </p>
          ) : null}
          {article.tickers.length ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {article.tickers.slice(0, 8).map((t) => {
                const ins = article.insights.find((i) => i.ticker === t);
                return (
                  <span
                    key={t}
                    className={cn(
                      "rounded bg-muted/50 px-1.5 py-0.5 font-mono text-[10px]",
                      ins?.sentiment === "positive" && "text-bullish",
                      ins?.sentiment === "negative" && "text-bearish",
                    )}
                  >
                    {t}
                  </span>
                );
              })}
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export default async function NewsPage() {
  const news = await fetchMarketNews();

  return (
    <div>
      <PageHeader
        title="Market News"
        description="Market-moving headlines across index ETFs, mega-cap movers, and our holdings — Polygon-sourced, with per-ticker sentiment. Candidate drivers, not verified cause."
        actions={
          news ? (
            <div className="flex items-center gap-3 text-xs">
              <span className="text-bullish flex items-center gap-1">
                <TrendingUp className="h-3.5 w-3.5" />
                {news.sentiment_counts.positive ?? 0}
              </span>
              <span className="text-bearish flex items-center gap-1">
                <TrendingDown className="h-3.5 w-3.5" />
                {news.sentiment_counts.negative ?? 0}
              </span>
              <span className="text-muted-foreground">
                {news.n_articles} articles · {news.lookback_days}d
              </span>
            </div>
          ) : null
        }
      />

      {!news || news.articles.length === 0 ? (
        <Card>
          <CardContent className="text-muted-foreground flex flex-col items-center gap-2 py-12 text-sm">
            <Newspaper className="h-6 w-6 opacity-50" />
            {news ? "No recent articles in the window." : "News feed unavailable — is the API up and POLYGON_API_KEY set?"}
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {news.articles.map((a) => (
            <ArticleCard key={a.id} article={a} />
          ))}
        </div>
      )}
    </div>
  );
}
