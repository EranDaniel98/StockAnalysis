import Link from "next/link";

import { MarkdownView } from "@/components/markdown-view";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import {
  findLatestPicksDate,
  loadReportMarkdown,
} from "@/lib/factors/data";

export const dynamic = "force-dynamic";

export default async function PerStockPlansPage() {
  const latestDate = await findLatestPicksDate();
  if (!latestDate) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Per-stock plans"
          description="Per-ticker entry, stop, target, sizing"
        />
        <Card>
          <CardContent className="py-8 text-muted-foreground">
            No analysis yet. Run the daily pipeline.
          </CardContent>
        </Card>
      </div>
    );
  }

  // portfolio_analysis_*.md uses the underscored date convention.
  const dateUnderscored = latestDate.replace(/-/g, "_");
  const md = await loadReportMarkdown(latestDate, "portfolio_analysis");
  if (!md) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Per-stock plans"
          description={`No file for ${latestDate}`}
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
          <CardContent className="py-8 text-muted-foreground">
            Expected at{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
              reports/portfolio_analysis_{dateUnderscored}.md
            </code>
            . Run the daily pipeline.
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Per-stock plans"
        description={`Entry / stop / target / sizing for each pick on ${latestDate}.`}
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
