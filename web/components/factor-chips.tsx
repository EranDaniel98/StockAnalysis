import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// Rank threshold for "this factor is doing meaningful work for the pick"
// — top decile of a ~500-name universe. Below this we don't bother
// rendering a chip; the picks-file rank is still in the tooltip.
const TOP_DECILE = 50;

type Props = {
  mom?: number | null;
  qual?: number | null;
  val?: number | null;
  pead?: number | null;
  className?: string;
};

function ChipFor({
  label, rank, color,
}: {
  label: string;
  rank: number | null | undefined;
  color: string;
}) {
  if (rank == null || rank > TOP_DECILE) return null;
  return (
    <Badge
      variant="outline"
      className={cn(
        "h-4 px-1 text-[9px] font-mono tracking-wider tabular-nums",
        color,
      )}
      title={`${label} rank #${rank} of ~500 (top decile)`}
    >
      {label}·{rank}
    </Badge>
  );
}

/**
 * Compact row of factor-strength chips (MOM/QUAL/VAL/PEAD). Renders
 * one chip per factor where the pick lands in the universe top decile;
 * picks with no top-decile factor render nothing (composite carries them).
 */
export function FactorChips(props: Props) {
  return (
    <div className={cn("flex flex-wrap items-center gap-1", props.className)}>
      <ChipFor label="MOM" rank={props.mom} color="border-bullish/40 text-bullish" />
      <ChipFor label="QUAL" rank={props.qual} color="border-primary/40 text-primary" />
      <ChipFor label="VAL" rank={props.val} color="border-amber-500/40 text-amber-500" />
      <ChipFor label="PEAD" rank={props.pead} color="border-blue-500/40 text-blue-400" />
    </div>
  );
}
