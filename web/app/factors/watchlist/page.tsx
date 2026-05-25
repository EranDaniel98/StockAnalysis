import Link from "next/link";

import { MarkdownView } from "@/components/markdown-view";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import {
  findLatestPicksDate,
  loadReportMarkdown,
} from "@/lib/factors/data";

export const dynamic = "force-dynamic";

export default async function WatchlistPage() {
  const latestDate = await findLatestPicksDate();
  if (!latestDate) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Watchlist"
          description="Names on deck for next quarter's rebalance"
        />
        <Card>
          <CardContent className="py-8 text-muted-foreground">
            No watchlist yet. Run the daily pipeline.
          </CardContent>
        </Card>
      </div>
    );
  }

  const md = await loadReportMarkdown(latestDate, "watchlist");
  if (!md) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Watchlist"
          description={`No watchlist file for ${latestDate}`}
        />
        <Card>
          <CardContent className="py-8 text-muted-foreground">
            Run the daily pipeline to generate the watchlist.
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Watchlist"
        description={`Bench candidates near the cut line for ${latestDate}.`}
        actions={
          <Link
            href="/factors"
            className="text-sm text-primary hover:underline"
          >
            ← Back to factors
          </Link>
        }
      />
      <Card>
        <CardContent className="py-6">
          <MarkdownView markdown={md} />
        </CardContent>
      </Card>
    </div>
  );
}
