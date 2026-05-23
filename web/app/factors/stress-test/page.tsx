import Link from "next/link";

import { MarkdownView } from "@/components/markdown-view";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import {
  findLatestPicksDate,
  loadReportMarkdown,
} from "@/lib/factors/data";

export const dynamic = "force-dynamic";

export default async function StressTestPage() {
  const latestDate = await findLatestPicksDate();
  if (!latestDate) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Stress test"
          description="Drawdown range across stress scenarios"
        />
        <Card>
          <CardContent className="py-8 text-muted-foreground">
            No stress test yet. Run the daily pipeline.
          </CardContent>
        </Card>
      </div>
    );
  }
  const md = await loadReportMarkdown(latestDate, "stress_test");
  if (!md) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Stress test"
          description={`No file for ${latestDate}`}
          actions={
            <Link href="/factors" className="text-sm text-primary hover:underline">
              ← Back to factors
            </Link>
          }
        />
        <Card>
          <CardContent className="py-8 text-muted-foreground">
            Run the daily pipeline to generate the stress test.
          </CardContent>
        </Card>
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <PageHeader
        title="Stress test"
        description={`Scenario-by-scenario drawdown for ${latestDate}.`}
        actions={
          <Link href="/factors" className="text-sm text-primary hover:underline">
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
