import { fmtNumber, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Compact trade-mechanics strip. Replaces the verbose Risk-management
 * table that used to sit in the right rail. Surfaces only the fields a
 * trader actually reads off this page before placing the order:
 *
 *   stop  · target  · R/R  · time-stop  · position
 *
 * Each "method" string (e.g. "ATR 2.0x", "chart resistance",
 * "3:1 R-R multiple") comes from the engine — see
 * src/scoring/recommender.py:_calculate_stop_loss / _calculate_take_profit.
 *
 * Renders nothing when no risk fields are populated (returns null).
 */

type RiskMgmt = Record<string, unknown>;

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function priceOf(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (isPlainObject(v) && typeof v.price === "number" && Number.isFinite(v.price)) {
    return v.price;
  }
  return null;
}

function pctOf(v: unknown): number | null {
  if (isPlainObject(v) && typeof v.pct_from_current === "number") {
    return v.pct_from_current;
  }
  return null;
}

function methodLabel(v: unknown): string | null {
  if (!isPlainObject(v) || typeof v.method !== "string") return null;
  const m = v.method.toLowerCase();
  if (m === "atr") {
    const detail = typeof v.detail === "string" ? v.detail : "";
    const mult = detail.match(/ATR\(([\d.]+)x\)/i)?.[1];
    return mult ? `ATR ${mult}x` : "ATR";
  }
  if (m === "percentage") return "Flat %";
  if (m === "support") return "Support";
  if (m === "resistance") return "Chart resistance";
  if (m === "risk_reward") return "R-R multiple";
  if (m === "calendar") return "Calendar";
  return v.method;
}

export function RiskStrip({ risk }: { risk: RiskMgmt }) {
  const entry = num(risk.entry_price) ?? num(risk.current_price);

  const stop = risk.stop_loss;
  const stopPx = priceOf(stop);
  const stopPct = pctOf(stop);
  const stopMethod = methodLabel(stop);

  const tp = risk.take_profit;
  const tpPx = priceOf(tp);
  const tpPct = pctOf(tp);
  const tpMethod = methodLabel(tp);

  const rr =
    num(risk.risk_reward_ratio) ??
    (entry !== null && stopPx !== null && tpPx !== null && entry !== stopPx
      ? (tpPx - entry) / (entry - stopPx)
      : null);

  const ts = isPlainObject(risk.time_stop) ? risk.time_stop : null;
  const tsDays = ts && typeof ts.days === "number" ? (ts.days as number) : null;
  const tsExit = ts && typeof ts.exit_date === "string" ? (ts.exit_date as string) : null;

  const position = isPlainObject(risk.position) ? risk.position : null;
  const shares =
    position && typeof position.recommended_shares === "number"
      ? (position.recommended_shares as number)
      : null;
  const dollars =
    position && typeof position.dollar_amount === "number"
      ? (position.dollar_amount as number)
      : null;
  const pctPort =
    position && typeof position.pct_of_portfolio === "number"
      ? (position.pct_of_portfolio as number)
      : null;

  const cells: Array<{ label: string; value: React.ReactNode; tone?: string }> = [];

  if (stopPx !== null) {
    cells.push({
      label: "Stop",
      tone: "text-bearish",
      value: (
        <>
          <span className="font-semibold tabular-nums">{fmtUSD(stopPx)}</span>
          {stopPct !== null ? (
            <span className="text-muted-foreground">
              {" "}
              · {stopPct > 0 ? "+" : ""}
              {fmtNumber(stopPct, 1)}%
            </span>
          ) : null}
          {stopMethod ? (
            <span className="text-muted-foreground"> · {stopMethod}</span>
          ) : null}
        </>
      ),
    });
  }

  if (tpPx !== null) {
    cells.push({
      label: "Target",
      tone: "text-bullish",
      value: (
        <>
          <span className="font-semibold tabular-nums">{fmtUSD(tpPx)}</span>
          {tpPct !== null ? (
            <span className="text-muted-foreground">
              {" "}
              · {tpPct > 0 ? "+" : ""}
              {fmtNumber(tpPct, 1)}%
            </span>
          ) : null}
          {tpMethod ? (
            <span className="text-muted-foreground"> · {tpMethod}</span>
          ) : null}
        </>
      ),
    });
  }

  if (rr !== null) {
    cells.push({
      label: "R/R",
      value: <span className="tabular-nums">{rr.toFixed(2)}:1</span>,
    });
  }

  if (tsDays !== null || tsExit) {
    cells.push({
      label: "Time stop",
      value: (
        <span className="tabular-nums">
          {tsDays !== null ? `${tsDays}d` : ""}
          {tsDays !== null && tsExit ? (
            <span className="text-muted-foreground"> → {tsExit}</span>
          ) : tsExit ? (
            tsExit
          ) : null}
        </span>
      ),
    });
  }

  if (shares !== null && dollars !== null) {
    cells.push({
      label: "Position",
      value: (
        <>
          <span className="tabular-nums">{shares.toLocaleString()} sh</span>
          <span className="text-muted-foreground">
            {" "}
            · {fmtUSD(dollars, true)}
            {pctPort !== null ? ` · ${fmtNumber(pctPort, 1)}% port` : ""}
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
