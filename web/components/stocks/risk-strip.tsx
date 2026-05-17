import type {
  RiskManagement,
  StopLoss,
  TakeProfit,
} from "@/lib/api/client";
import { fmtNumber, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Compact trade-mechanics strip. Replaces the verbose Risk-management
 * table that used to sit in the right rail. Surfaces only the fields a
 * trader actually reads off this page before placing the order:
 *
 *   stop  · target  · R/R  · time-stop  · position
 *
 * Each method string maps to a human label via STOP_METHOD_LABEL /
 * TP_METHOD_LABEL — the engine emits the post-fallback method (a
 * "support" request that failed becomes "percentage"), so the FE just
 * reads what's there and trusts it.
 *
 * Renders nothing when every cell would be empty (returns null).
 */

const STOP_METHOD_LABEL: Record<StopLoss["method"], string> = {
  atr: "ATR",
  percentage: "Flat %",
  support: "Support",
};

const TP_METHOD_LABEL: Record<TakeProfit["method"], string> = {
  risk_reward: "R-R multiple",
  atr: "ATR",
  resistance: "Chart resistance",
};

function stopLabel(stop: StopLoss): string {
  if (stop.method === "atr" && stop.atr_multiplier != null) {
    return `ATR ${stop.atr_multiplier.toFixed(1)}x`;
  }
  return STOP_METHOD_LABEL[stop.method];
}

function tpLabel(tp: TakeProfit): string {
  if (tp.method === "atr" && tp.atr_multiplier != null) {
    return `ATR ${tp.atr_multiplier.toFixed(1)}x`;
  }
  return TP_METHOD_LABEL[tp.method];
}

function fmtSignedPct(pct: number): string {
  return `${pct > 0 ? "+" : ""}${fmtNumber(pct, 1)}%`;
}

export function RiskStrip({ risk }: { risk: RiskManagement | null | undefined }) {
  if (risk == null) return null;

  const entry = risk.entry_price ?? risk.current_price;
  const stop = risk.stop_loss;
  const tp = risk.take_profit;
  const ts = risk.time_stop;
  const pos = risk.position;

  // Prefer the engine's risk_reward_ratio when present — it has the
  // right sign handling for SELL recommendations. Fall back to a
  // computed value only when both prices straddle entry correctly
  // (otherwise the strip would render a misleading negative).
  let rr: number | null = risk.risk_reward_ratio ?? null;
  if (
    rr == null &&
    entry != null &&
    stop?.price != null &&
    tp?.price != null &&
    tp.price > entry &&
    entry > stop.price
  ) {
    rr = (tp.price - entry) / (entry - stop.price);
  }

  const cells: Array<{ label: string; value: React.ReactNode; tone?: string }> = [];

  if (stop != null) {
    cells.push({
      label: "Stop",
      tone: "text-bearish",
      value: (
        <>
          <span className="font-semibold tabular-nums">{fmtUSD(stop.price)}</span>
          <span className="text-muted-foreground">
            {" "}
            · {fmtSignedPct(stop.pct_from_current)}
          </span>
          <span className="text-muted-foreground"> · {stopLabel(stop)}</span>
        </>
      ),
    });
  }

  if (tp != null) {
    cells.push({
      label: "Target",
      tone: "text-bullish",
      value: (
        <>
          <span className="font-semibold tabular-nums">{fmtUSD(tp.price)}</span>
          <span className="text-muted-foreground">
            {" "}
            · {fmtSignedPct(tp.pct_from_current)}
          </span>
          <span className="text-muted-foreground"> · {tpLabel(tp)}</span>
        </>
      ),
    });
  }

  if (rr != null) {
    cells.push({
      label: "R/R",
      value: <span className="tabular-nums">{rr.toFixed(2)}:1</span>,
    });
  }

  if (ts != null) {
    cells.push({
      label: "Time stop",
      value: (
        <span className="tabular-nums">
          {ts.days}d
          <span className="text-muted-foreground"> → {ts.exit_date}</span>
        </span>
      ),
    });
  }

  if (pos != null && pos.recommended_shares > 0) {
    cells.push({
      label: "Position",
      value: (
        <>
          <span className="tabular-nums">
            {pos.recommended_shares.toLocaleString()} sh
          </span>
          <span className="text-muted-foreground">
            {" "}
            · {fmtUSD(pos.dollar_amount, true)}
            {` · ${fmtNumber(pos.pct_of_portfolio, 1)}% port`}
          </span>
        </>
      ),
    });
  }

  if (cells.length === 0) return null;

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-2",
        "px-3 py-2 rounded border border-border bg-muted/20",
        "font-mono text-xs",
      )}
    >
      {cells.map(({ label, value, tone }, i) => (
        <div key={label} className="flex items-baseline gap-1.5">
          <span className="text-[10px] tracking-wider uppercase text-muted-foreground">
            {label}
          </span>
          <span className={tone ?? "text-foreground"}>{value}</span>
          {i < cells.length - 1 ? (
            <span className="text-muted-foreground/40 ml-1.5 select-none">·</span>
          ) : null}
        </div>
      ))}
    </div>
  );
}
