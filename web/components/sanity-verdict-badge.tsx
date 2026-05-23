import { Badge } from "@/components/ui/badge";
import type { SanityVerdict } from "@/lib/factors/data";
import { cn } from "@/lib/utils";

type Props = {
  verdict: SanityVerdict;
  reason?: string;
  evidence?: string;
  className?: string;
};

/**
 * Per-pick KEEP/FLAG/VETO chip from the AI sanity check.
 *
 * The chip is advisory only — sanity-check output is logged but does
 * NOT block paper-trade execution today. Document this in the title
 * tooltip so a reader hovering doesn't assume the chip is a hard gate.
 */
export function SanityVerdictBadge({
  verdict, reason, evidence, className,
}: Props) {
  const variant =
    verdict === "VETO" ? "bearish"
    : verdict === "FLAG" ? "neutral"
    : "bullish";

  const reasonTxt = reason ? ` (${reason})` : "";
  const title = evidence
    ? `${verdict}${reasonTxt} — advisory only, not enforced\n\n${evidence}`
    : `${verdict}${reasonTxt} — advisory only`;

  return (
    <Badge
      variant={variant}
      className={cn(
        "text-[9px] font-mono uppercase tracking-wider px-1.5 cursor-help",
        verdict === "FLAG" && "border-amber-500/40 bg-amber-500/10 text-amber-500",
        className,
      )}
      title={title}
    >
      {verdict}
    </Badge>
  );
}
