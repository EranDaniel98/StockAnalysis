"use client";

import { useQuery } from "@tanstack/react-query";
import { Briefcase } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreboardTile } from "@/components/portfolio/scoreboard-tile";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type SectorMetric,
  type TodayActionItem,
} from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtPct, pnlColorClass } from "@/lib/format";
import { cn } from "@/lib/utils";

// Maps the pick.sector strings the analyzer emits to SPDR Select Sector
// ETF tickers. Several sectors share a name with the ETF (Technology,
// Energy, Real Estate, Industrials, Utilities, Consumer Cyclical) and
// fall through the default-ticker map below; only the renames live here.
const SECTOR_NAME_TO_ETF: Record<string, string> = {
  "Basic Materials": "XLB",
  "Materials": "XLB",
  "Financial Services": "XLF",
  "Financial": "XLF",
  "Healthcare": "XLV",
  "Health Care": "XLV",
  "Consumer Cyclical": "XLY",
  "Consumer Discretionary": "XLY",
  "Consumer Defensive": "XLP",
  "Consumer Staples": "XLP",
  "Communication Services": "XLC",
  "Communication": "XLC",
  "Technology": "XLK",
  "Industrials": "XLI",
  "Energy": "XLE",
  "Real Estate": "XLRE",
  "Utilities": "XLU",
};

type BasketPick = { ticker: string; sector: string | null | undefined };

function picksByEtfTicker(
  picks: BasketPick[],
): Map<string, BasketPick[]> {
  const out = new Map<string, BasketPick[]>();
  for (const p of picks) {
    if (!p.sector) continue;
    const etf = SECTOR_NAME_TO_ETF[p.sector];
    if (!etf) continue;
    if (!out.has(etf)) out.set(etf, []);
    out.get(etf)!.push(p);
  }
  return out;
}

// ±5% caps the heatmap saturation so a single melt-up day doesn't wash the grid.
function intensity(pct: number | null | undefined): number {
  if (pct == null) return 0;
  const clamped = Math.max(-5, Math.min(5, pct));
  return Math.abs(clamped) / 5;
}

function tileBg(pct: number | null | undefined): string {
  if (pct == null) return "transparent";
  const token = pct >= 0 ? "var(--bullish)" : "var(--bearish)";
  const alpha = Math.round(intensity(pct) * 40);
  return `color-mix(in oklch, ${token} ${alpha}%, transparent)`;
}

function ReturnRow({
  label,
  pct,
  emphasis = false,
}: {
  label: string;
  pct: number | null | undefined;
  emphasis?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          "font-mono tabular-nums",
          emphasis ? "text-base font-semibold" : "text-sm",
          pnlColorClass(pct),
        )}
      >
        {fmtPct(pct, 2, true)}
      </span>
    </div>
  );
}

const SPARK_WIDTH = 200;
const SPARK_HEIGHT = 32;

function SectorSpark({ history }: { history: number[] }) {
  if (history.length < 5) {
    return (
      <div className="h-8 flex items-center justify-center text-[9px] uppercase tracking-wider text-muted-foreground/50 font-mono">
        no history
      </div>
    );
  }

  const maxAbs = history.reduce((m, v) => Math.max(m, Math.abs(v)), 0);
  if (maxAbs === 0) return null;

  // Symmetric Y so the 0% baseline stays centered across all sectors.
  const scale = (SPARK_HEIGHT / 2) * 0.9;
  const mid = SPARK_HEIGHT / 2;
  const step = SPARK_WIDTH / (history.length - 1);

  const points = history.map((v, i) => {
    const x = i * step;
    const y = mid - (v / maxAbs) * scale;
    return [x, y] as const;
  });

  const last = history[history.length - 1];
  const stroke =
    last > 0 ? "var(--bullish)" : last < 0 ? "var(--bearish)" : "var(--neutral)";

  const linePath = points.map(([x, y]) => `${x},${y}`).join(" ");
  const fillPath = [
    `${points[0][0]},${mid}`,
    ...points.map(([x, y]) => `${x},${y}`),
    `${points[points.length - 1][0]},${mid}`,
  ].join(" ");

  return (
    <svg
      viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
      preserveAspectRatio="none"
      className="block w-full h-8"
      aria-hidden="true"
    >
      <line
        x1={0}
        x2={SPARK_WIDTH}
        y1={mid}
        y2={mid}
        stroke="var(--muted-foreground)"
        strokeDasharray="2 2"
        strokeOpacity={0.4}
        strokeWidth={1}
      />
      <polygon points={fillPath} fill={stroke} fillOpacity={0.1} />
      <polyline
        points={linePath}
        fill="none"
        stroke={stroke}
        strokeWidth={1.2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function SectorTile({
  s, basketPicks,
}: {
  s: SectorMetric;
  basketPicks: BasketPick[];
}) {
  const tone =
    basketPicks.length === 0 ? "muted"
    : (s.return_5d_pct ?? 0) >= 0 ? "aligned"
    : "fighting";
  return (
    <Card
      className="border border-border overflow-hidden"
      style={{ backgroundColor: tileBg(s.return_5d_pct) }}
    >
      <CardContent className="space-y-2 p-4">
        <div className="flex items-baseline justify-between">
          <span className="font-mono text-sm font-semibold tracking-wider">
            {s.ticker}
          </span>
          {s.above_sma50 == null ? null : (
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              SMA50{" "}
              <span
                className={cn(
                  "font-mono",
                  s.above_sma50 ? "text-bullish" : "text-bearish",
                )}
              >
                {s.above_sma50 ? "+" : "−"}
              </span>
            </span>
          )}
        </div>
        <h3 className="text-xs uppercase tracking-wider text-muted-foreground">
          {s.name}
        </h3>
        <div className="px-0 py-1">
          <SectorSpark history={s.history_30d_pct ?? []} />
        </div>
        <div className="space-y-1">
          <ReturnRow label="1d" pct={s.return_1d_pct} />
          <ReturnRow label="5d" pct={s.return_5d_pct} emphasis />
          <ReturnRow label="21d" pct={s.return_21d_pct} />
        </div>
        <BasketBadge picks={basketPicks} tone={tone} />
      </CardContent>
    </Card>
  );
}

/** Inline chip + ticker list — shows how today's basket maps onto this
 *  sector. ``tone='aligned'`` when sector is up and we're long it,
 *  'fighting' when sector is down and we're still long, 'muted' when
 *  the basket has nothing in this sector. */
function BasketBadge({
  picks, tone,
}: {
  picks: BasketPick[];
  tone: "aligned" | "fighting" | "muted";
}) {
  if (picks.length === 0) {
    return (
      <div className="pt-1 mt-1 border-t border-border/40 flex items-center justify-between">
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground/60">
          basket
        </span>
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground/40">
          0 picks
        </span>
      </div>
    );
  }
  return (
    <div className="pt-1 mt-1 border-t border-border/40 space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground/70 flex items-center gap-1">
          <Briefcase className="h-2.5 w-2.5" />
          basket
        </span>
        <Badge
          variant="outline"
          className={cn(
            "text-[9px] font-mono uppercase tracking-wider",
            tone === "aligned" && "border-bullish/40 text-bullish bg-bullish/5",
            tone === "fighting" && "border-bearish/40 text-bearish bg-bearish/5",
          )}
          title={
            tone === "aligned"
              ? "Sector up + basket long here — momentum aligned"
              : tone === "fighting"
              ? "Sector down but basket still long here — drawdown risk"
              : "Basket has no picks in this sector"
          }
        >
          {picks.length} {picks.length === 1 ? "pick" : "picks"}
        </Badge>
      </div>
      <div className="flex flex-wrap gap-1">
        {picks.map((p) => (
          <Link
            key={p.ticker}
            href={`/stocks/${encodeURIComponent(p.ticker)}`}
            className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-border/40 bg-background/60 hover:bg-muted/50 transition-colors"
          >
            {p.ticker}
          </Link>
        ))}
      </div>
    </div>
  );
}

type Summary = {
  total: number;
  nPositive: number;
  positivePct: number;
  avg5d: number | null;
  leader: SectorMetric | null;
  laggard: SectorMetric | null;
};

function summarise(sectors: SectorMetric[]): Summary {
  let nPositive = 0;
  let sum = 0;
  let count = 0;
  let leader: SectorMetric | null = null;
  let laggard: SectorMetric | null = null;
  for (const s of sectors) {
    const r = s.return_5d_pct;
    if (r === null || r === undefined || Number.isNaN(r)) continue;
    if (r > 0) nPositive += 1;
    sum += r;
    count += 1;
    if (leader === null || r > (leader.return_5d_pct ?? -Infinity)) leader = s;
    if (laggard === null || r < (laggard.return_5d_pct ?? Infinity)) laggard = s;
  }
  const total = sectors.length;
  return {
    total,
    nPositive,
    positivePct: total > 0 ? (nPositive / total) * 100 : 0,
    avg5d: count > 0 ? sum / count : null,
    leader,
    laggard,
  };
}

export default function SectorsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["market", "sectors"],
    queryFn: () => api.market.sectors(),
    refetchInterval: 5 * 60_000,
  });

  // Pull today's factor basket so we can overlay per-sector exposure on
  // each ETF tile. Failure is non-fatal — page still works without it.
  const basketQuery = useQuery({
    queryKey: qk.pipeline.todayActions(),
    queryFn: () => api.pipeline.todayActions(),
    refetchInterval: 60_000,
    retry: false,
  });

  const sectors = data?.sectors ?? [];
  const summary = useMemo(() => summarise(sectors), [sectors]);

  // Build full basket (new_buys + keeps) and bucket by ETF ticker.
  // Exits are excluded — they're scheduled to leave, so they no longer
  // count as 'current exposure' for the rotation overlay.
  const basketByEtf = useMemo(() => {
    const b = basketQuery.data;
    if (!b) return new Map<string, BasketPick[]>();
    const all: TodayActionItem[] = [
      ...(b.new_buys ?? []),
      ...(b.keeps ?? []),
    ];
    return picksByEtfTicker(
      all.map((it) => ({ ticker: it.ticker, sector: it.sector })),
    );
  }, [basketQuery.data]);

  const basketTotal = useMemo(() => {
    let n = 0;
    for (const arr of basketByEtf.values()) n += arr.length;
    return n;
  }, [basketByEtf]);
  const basketCovered = basketByEtf.size;

  const breadthTone: "bullish" | "bearish" | "neutral" =
    summary.total === 0
      ? "neutral"
      : summary.positivePct >= 60
        ? "bullish"
        : summary.positivePct <= 40
          ? "bearish"
          : "neutral";

  const avgTone =
    summary.avg5d === null
      ? "muted"
      : summary.avg5d > 0
        ? "bullish"
        : summary.avg5d < 0
          ? "bearish"
          : "neutral";

  return (
    <>
      <PageHeader
        title="Sector rotation"
        description="SPDR Select Sector ETFs. Tile color tracks the 5-day return (bullish ↔ bearish, clamped at ±5%)."
      />

      {error ? <ErrorState error={error} /> : null}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <ScoreboardTile
          label="Breadth (5d)"
          value={
            isLoading || summary.total === 0
              ? "—"
              : `${summary.nPositive}/${summary.total}`
          }
          sub={
            isLoading || summary.total === 0
              ? undefined
              : `${summary.positivePct.toFixed(0)}% positive`
          }
          subTone={breadthTone === "neutral" ? "muted" : breadthTone}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Avg 5d"
          value={
            isLoading || summary.avg5d === null ? (
              "—"
            ) : (
              <span className={pnlColorClass(summary.avg5d)}>
                {fmtPct(summary.avg5d, 2, true)}
              </span>
            )
          }
          sub={
            isLoading || summary.total === 0
              ? undefined
              : `across ${summary.total} sectors`
          }
          subTone="muted"
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Leader"
          value={isLoading || !summary.leader ? "—" : summary.leader.ticker}
          sub={
            isLoading || !summary.leader
              ? undefined
              : fmtPct(summary.leader.return_5d_pct, 2, true)
          }
          subTone={avgTone === "muted" ? "muted" : "bullish"}
          isLoading={isLoading}
        />
        <ScoreboardTile
          label="Laggard"
          value={isLoading || !summary.laggard ? "—" : summary.laggard.ticker}
          sub={
            isLoading || !summary.laggard
              ? undefined
              : fmtPct(summary.laggard.return_5d_pct, 2, true)
          }
          subTone={avgTone === "muted" ? "muted" : "bearish"}
          isLoading={isLoading}
        />
      </div>

      {isLoading ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 11 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      ) : data ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
          {sectors.map((s) => (
            <SectorTile
              key={s.ticker}
              s={s}
              basketPicks={basketByEtf.get(s.ticker) ?? []}
            />
          ))}
        </div>
      ) : null}

      {basketQuery.data ? (
        <p className="mt-4 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
          Basket overlay: {basketTotal} picks across {basketCovered} of{" "}
          {sectors.length} sectors
          {basketQuery.data.picks_date ? (
            <> · picks for {basketQuery.data.picks_date}</>
          ) : null}
        </p>
      ) : null}
    </>
  );
}
