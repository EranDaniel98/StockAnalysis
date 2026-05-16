import Link from "next/link";

import { MarkdownView } from "@/components/markdown-view";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import {
  findLatestPicksDate,
  loadReportMarkdown,
} from "@/lib/factors/data";

export const dynamic = "force-dynamic";

export default async function BriefingPage() {
  const latestDate = await findLatestPicksDate();
  if (!latestDate) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Morning briefing"
          description="Daily one-page summary"
        />
        <Card>
          <CardContent className="py-8 text-muted-foreground">
            No briefing yet. Run the daily pipeline.
          </CardContent>
        </Card>
      </div>
    );
  }
  const md = await loadReportMarkdown(latestDate, "morning_briefing");
  if (!md) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Morning briefing"
          description={`No briefing file for ${latestDate}`}
        />
        <Card>
          <CardContent className="py-8 text-muted-foreground">
            Run the daily pipeline to generate the briefing.
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Morning briefing"
        description={`Single-page summary for ${latestDate}.`}
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
