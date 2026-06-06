import { AlertTriangle, Minus, TrendingDown, TrendingUp } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { TradingViewTechnicals } from "@/components/tradingview-widget";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { fetchOutlook, type Lean, type Tilt } from "@/lib/market/outlook";
import { fmtPct } from "@/lib/format";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

const LEAN_META: Record<Lean, { label: string; cls: string; icon: typeof TrendingUp }> = {
  risk_on: { label: "Risk-on", cls: "text-bullish", icon: TrendingUp },
  risk_off: { label: "Risk-off", cls: "text-bearish", icon: TrendingDown },
  neutral: { label: "Neutral", cls: "text-muted-foreground", icon: Minus },
};

const TILT_CLS: Record<Tilt, string> = {
  bullish: "text-bullish",
  bearish: "text-bearish",
  neutral: "text-muted-foreground",
};

function pctCls(n: number | null): string {
  if (n === null || Number.isNaN(n)) return "text-muted-foreground";
  return n > 0 ? "text-bullish" : n < 0 ? "text-bearish" : "text-muted-foreground";
}

export default async function OutlookPage() {
  const o = await fetchOutlook();

  return (
    <div>
      <PageHeader
        title="Market Outlook"
        description="A blunt tally of objective signals into a risk-on / neutral / risk-off lean, plus the pre/post-market moves behind it. Conditions, not a forecast."
      />

      {!o ? (
        <Card>
          <CardContent className="text-muted-foreground py-12 text-center text-sm">
            Outlook unavailable — is the API up and POLYGON_API_KEY set?
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-6">
          {/* Lean + signal tally */}
          <Card>
            <CardContent className="flex flex-col gap-4 py-5 md:flex-row md:items-center md:gap-8">
              <div className="flex shrink-0 flex-col items-center justify-center gap-1 md:w-44">
                {(() => {
                  const m = LEAN_META[o.lean];
                  const Icon = m.icon;
                  return (
                    <>
                      <Icon className={cn("h-8 w-8", m.cls)} />
                      <span className={cn("text-2xl font-semibold", m.cls)}>
                        {m.label}
                      </span>
                      <span className="text-muted-foreground text-xs">
                        score {o.lean_score >= 0 ? "+" : ""}
                        {o.lean_score} · {o.n_bullish}↑ / {o.n_bearish}↓
                      </span>
                      <span className="text-muted-foreground text-[10px]">
                        session {o.session_date}
                      </span>
                    </>
                  );
                })()}
              </div>
              <div className="flex-1 space-y-2">
                {o.signals.map((s) => (
                  <div
                    key={s.name}
                    className="flex items-center justify-between border-b border-border/40 pb-2 last:border-0"
                  >
                    <div>
                      <div className="text-sm font-medium">{s.name}</div>
                      <div className="text-muted-foreground text-xs">{s.detail}</div>
                    </div>
                    <span
                      className={cn(
                        "text-xs font-medium uppercase",
                        TILT_CLS[s.tilt],
                      )}
                    >
                      {s.tilt}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <div className="border-border/40 bg-amber-500/10 flex items-start gap-2 rounded-md border px-3 py-2 text-xs text-amber-200 dark:text-amber-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{o.caveat}</span>
          </div>

          {/* Pre/post-market moves */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Pre / post-market moves</CardTitle>
              <CardDescription>
                Latest session ({o.session_date}). Pre-market is vs the prior
                close; after-hours is vs that session&apos;s close.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Index</TableHead>
                    <TableHead className="text-right">Close</TableHead>
                    <TableHead className="text-right">Pre-market</TableHead>
                    <TableHead className="text-right">After-hours</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {o.prepost.map((m) => (
                    <TableRow key={m.ticker}>
                      <TableCell className="font-mono font-medium">{m.ticker}</TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {m.last_close ?? "—"}
                      </TableCell>
                      <TableCell
                        className={cn("text-right font-mono tabular-nums", pctCls(m.premarket_pct))}
                      >
                        {fmtPct(m.premarket_pct, 2, true)}
                      </TableCell>
                      <TableCell
                        className={cn("text-right font-mono tabular-nums", pctCls(m.afterhours_pct))}
                      >
                        {fmtPct(m.afterhours_pct, 2, true)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* TradingView technical-analysis gauge as one extra (external) input */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                TradingView technicals — SPY
              </CardTitle>
              <CardDescription>
                TradingView&apos;s own oscillator + moving-average gauge. A
                separate, external read — not part of our signal tally above.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <TradingViewTechnicals symbol="SPY" />
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
