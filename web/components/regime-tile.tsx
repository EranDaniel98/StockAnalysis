"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ActivitySquare,
  CircleDot,
  Sun,
  CloudRain,
  HelpCircle,
} from "lucide-react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api/client";
import { qk } from "@/lib/api/keys";
import { fmtNumber, fmtPct } from "@/lib/format";

const LABEL_META: Record<
  string,
  { text: string; classes: string; Icon: typeof Sun }
> = {
  bull: { text: "Bull", classes: "text-emerald-400", Icon: Sun },
  bear: { text: "Bear", classes: "text-red-400", Icon: CloudRain },
  chop: { text: "Chop", classes: "text-amber-400", Icon: ActivitySquare },
  unknown: { text: "Unknown", classes: "text-muted-foreground", Icon: HelpCircle },
};

export function RegimeTile() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["market", "regime"],
    queryFn: () => api.market.regime(),
    // Regime moves slowly — 60s refresh is plenty; backing DataFetcher
    // also caches.
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <Card className="flex items-center gap-3 px-3 py-2">
        <Skeleton className="h-4 w-24" />
      </Card>
    );
  }
  if (error || !data) {
    return (
      <Card className="px-3 py-2 text-xs text-muted-foreground">
        regime unavailable
      </Card>
    );
  }

  const meta = LABEL_META[data.label] ?? LABEL_META.unknown;
  const Icon = meta.Icon;

  const notes = data.notes ?? [];

  return (
    <Tooltip>
      <TooltipTrigger className="rounded-md">
        <Card className="flex items-center gap-3 px-3 py-2 text-xs cursor-help">
          <div className="flex items-center gap-1.5">
            <Icon className={`h-4 w-4 ${meta.classes}`} />
            <span className={`font-medium ${meta.classes}`}>{meta.text}</span>
          </div>
          <div className="text-muted-foreground flex items-center gap-2">
            <span>
              SPY {data.spy_above_sma200 === null ? "—" : data.spy_above_sma200 ? "▲" : "▼"}{" "}
              {data.spy_pct_from_sma200 != null
                ? fmtPct(data.spy_pct_from_sma200, 1, true)
                : "—"}
            </span>
            <CircleDot className="h-2 w-2 opacity-40" />
            <span>VIX {fmtNumber(data.vix_level, 1)}</span>
          </div>
        </Card>
      </TooltipTrigger>
      <TooltipContent>
        {notes.length > 0 ? (
          <ul className="space-y-1 text-xs">
            {notes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        ) : (
          <span>No notes</span>
        )}
      </TooltipContent>
    </Tooltip>
  );
}
