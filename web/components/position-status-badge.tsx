import { AlertCircle, AlertTriangle, CheckCircle2, Target } from "lucide-react";
import type { ComponentType } from "react";

import { Badge } from "@/components/ui/badge";
import type { PositionStatus } from "@/lib/api/client";
import { cn } from "@/lib/utils";

type IconComponent = ComponentType<{ className?: string }>;

const STATUS_VARIANT: Record<
  PositionStatus,
  {
    icon: IconComponent;
    label: string;
    variant: "bullish" | "bearish" | "neutral";
    className?: string;
  }
> = {
  STOP_HIT: { icon: AlertCircle, label: "STOP HIT", variant: "bearish" },
  NEAR_STOP: {
    icon: AlertTriangle, label: "NEAR STOP", variant: "neutral",
    className: "border-amber-500/40 bg-amber-500/10 text-amber-500",
  },
  TARGET_HIT: { icon: Target, label: "TARGET HIT", variant: "bullish" },
  NEAR_TARGET: {
    icon: Target, label: "NEAR TARGET", variant: "neutral",
    className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-500",
  },
  HOLDING: { icon: CheckCircle2, label: "HOLDING", variant: "neutral" },
};

/**
 * Status chip for a held position. Inputs come straight from the
 * /api/portfolio/recommendations endpoint so the same classification
 * logic is used here, on Home (briefing banner), and in
 * scripts.position_monitor.
 */
export function PositionStatusBadge({
  status, className,
}: {
  status: PositionStatus;
  className?: string;
}) {
  const cfg = STATUS_VARIANT[status];
  const Icon = cfg.icon;
  return (
    <Badge
      variant={cfg.variant}
      className={cn(
        "gap-1 text-[10px] uppercase tracking-wider",
        cfg.className,
        className,
      )}
    >
      <Icon className="h-3 w-3" />
      {cfg.label}
    </Badge>
  );
}

/**
 * Tiny KEEP/EXIT chip showing whether the basket's next rebalance will
 * retain this position (it's still in today's picks) or sell it (it
 * dropped out). Compact enough to sit next to the ticker.
 */
export function BasketActionBadge({
  inBasket, className,
}: {
  inBasket: boolean;
  className?: string;
}) {
  return (
    <Badge
      variant={inBasket ? "bullish" : "bearish"}
      className={cn(
        "text-[9px] font-mono uppercase tracking-wider px-1.5",
        className,
      )}
      title={
        inBasket
          ? "In today's factor picks — will be kept on rebalance"
          : "Not in today's factor picks — scheduled to EXIT on next rebalance"
      }
    >
      {inBasket ? "KEEP" : "EXIT"}
    </Badge>
  );
}
