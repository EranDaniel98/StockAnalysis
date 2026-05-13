import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Bloomberg-style scoreboard tile: 1px border, no shadow, uppercase
 * tracking-wider label, mono numeric value, optional inline sub-value
 * (e.g. a delta) coloured via the bullish/bearish/neutral tokens.
 *
 * `trailing` is a slot for inline visual content rendered on the right
 * of the tile body (e.g. the equity sparkline next to the equity value).
 */
export function ScoreboardTile({
  label,
  value,
  sub,
  subTone = "neutral",
  trailing,
  isLoading,
  className,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  subTone?: "bullish" | "bearish" | "neutral" | "muted";
  trailing?: ReactNode;
  isLoading?: boolean;
  className?: string;
}) {
  const toneClass =
    subTone === "bullish"
      ? "text-bullish"
      : subTone === "bearish"
        ? "text-bearish"
        : subTone === "muted"
          ? "text-muted-foreground"
          : "text-foreground";

  return (
    <Card size="sm" className={cn("gap-1.5", className)}>
      <div className="px-2 pt-1 text-[10px] font-medium tracking-wider text-muted-foreground uppercase">
        {label}
      </div>
      <div className="flex items-end justify-between gap-3 px-2 pb-1">
        <div className="flex flex-col gap-0.5 min-w-0">
          {isLoading ? (
            <Skeleton className="h-7 w-24" />
          ) : (
            <output className="font-mono text-2xl leading-none font-semibold tabular-nums text-foreground truncate">
              {value}
            </output>
          )}
          {sub ? (
            <span
              className={cn(
                "font-mono text-[11px] tabular-nums",
                toneClass,
              )}
            >
              {sub}
            </span>
          ) : null}
        </div>
        {trailing ? (
          <div className="flex-shrink-0">{trailing}</div>
        ) : null}
      </div>
    </Card>
  );
}
