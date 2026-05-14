"use client";

import { Pencil, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fmtNumber, fmtPct, fmtUSD } from "@/lib/format";
import { cn } from "@/lib/utils";

// ─── localStorage hook ──────────────────────────────────────────────────────

type StoredPosition = { shares: number; avg_cost: number };

const STORAGE_KEY_PREFIX = "stocknew:position:";

function storageKey(ticker: string): string {
  return `${STORAGE_KEY_PREFIX}${ticker.toUpperCase()}`;
}

/**
 * Tiny localStorage hook for the hypothetical position on this ticker.
 *
 * Reads the saved entry on mount inside a useEffect (window is undefined
 * during SSR). Writes are persisted on every set. Returns `null` until
 * the user fills in both shares and avg cost — both fields are required
 * for the math to be meaningful.
 */
function useStoredPosition(
  ticker: string,
): [StoredPosition | null, (next: StoredPosition | null) => void] {
  const [state, setState] = useState<StoredPosition | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = window.localStorage.getItem(storageKey(ticker));
      if (!raw) {
        setState(null);
        return;
      }
      const parsed = JSON.parse(raw);
      if (
        typeof parsed === "object" &&
        parsed !== null &&
        typeof parsed.shares === "number" &&
        typeof parsed.avg_cost === "number" &&
        parsed.shares > 0 &&
        parsed.avg_cost > 0
      ) {
        setState({ shares: parsed.shares, avg_cost: parsed.avg_cost });
      } else {
        setState(null);
      }
    } catch {
      // Corrupt entry — drop it.
      setState(null);
    }
  }, [ticker]);

  const persist = useCallback(
    (next: StoredPosition | null) => {
      setState(next);
      if (typeof window === "undefined") return;
      try {
        if (next === null) {
          window.localStorage.removeItem(storageKey(ticker));
        } else {
          window.localStorage.setItem(storageKey(ticker), JSON.stringify(next));
        }
      } catch {
        // Quota exceeded / private mode — state is still set in memory.
      }
    },
    [ticker],
  );

  return [state, persist];
}

// ─── Position-action heuristic ──────────────────────────────────────────────

type PositionAction = "HOLD" | "ADD" | "TRIM" | "EXIT";

type ActionTone = "bullish" | "bearish" | "neutral";

type Recommendation = {
  action: PositionAction;
  tone: ActionTone;
  headline: string;
  reason: string;
};

/**
 * Map (engine recommendation, current mark, position cost basis) → a
 * concrete position-management action. The branches are deliberately
 * ordered: stop-loss wins over engine action, engine SELL wins over
 * target-hit, target-hit wins over add-DCA, etc.
 *
 * Action semantics:
 *   - EXIT  : close the position (stop hit, or engine flipped bearish)
 *   - TRIM  : take partial profit / scale out (target hit)
 *   - ADD   : average down on a high-conviction setup
 *   - HOLD  : sit tight, thesis intact
 */
function recommendPositionAction({
  engineAction,
  score,
  mark,
  avgCost,
  stop,
  target,
}: {
  engineAction: string | null;
  score: number | null;
  mark: number | null;
  avgCost: number;
  stop: number | null;
  target: number | null;
}): Recommendation {
  const a = engineAction ?? "HOLD";

  if (mark !== null && stop !== null && mark <= stop) {
    return {
      action: "EXIT",
      tone: "bearish",
      headline: "EXIT — stop hit",
      reason: `Mark ${fmtUSD(mark)} is at or below the engine's stop ${fmtUSD(stop)}. Risk discipline says close it; revisit only after a new setup.`,
    };
  }
  if (a === "STRONG SELL" || a === "SELL") {
    return {
      action: "EXIT",
      tone: "bearish",
      headline: `EXIT — engine ${a}`,
      reason: `Thesis flipped. The engine no longer rates this a long. Close the position and recycle the capital.`,
    };
  }
  if (mark !== null && target !== null && mark >= target) {
    return {
      action: "TRIM",
      tone: "bullish",
      headline: "TRIM — target reached",
      reason: `Mark ${fmtUSD(mark)} is at or above the engine's target ${fmtUSD(target)}. Scale out at least partially and let any remainder run with a raised stop.`,
    };
  }
  if (a === "STRONG BUY" && mark !== null && mark < avgCost) {
    return {
      action: "ADD",
      tone: "bullish",
      headline: "ADD — DCA window",
      reason: `Engine STRONG BUY (${score == null ? "—" : fmtNumber(score, 0)}) and the mark is under your average cost. Conviction-on-conviction averaging-down setup; size the add to your risk budget.`,
    };
  }
  return {
    action: "HOLD",
    tone: "neutral",
    headline: "HOLD — thesis intact",
    reason: `Engine ${a}${score == null ? "" : ` (score ${fmtNumber(score, 0)})`}. No action signal yet — let the plan play out.`,
  };
}

// ─── Card ───────────────────────────────────────────────────────────────────

export function MyPositionCard({
  ticker,
  mark,
  entry,
  stop,
  target,
  action,
  score,
  timeStop,
}: {
  ticker: string;
  /** Latest trade-able price (last close, falling back to engine entry). */
  mark: number | null;
  /** Engine's reference entry — shown so the user can compare against
   *  their own avg cost without doing arithmetic. */
  entry: number | null;
  stop: number | null;
  target: number | null;
  action: string | null;
  score: number | null;
  /** Triple-barrier time stop from the engine. Calendar-day budget for
   *  this strategy's alpha half-life — surfaced so the user can see how
   *  long the engine is willing to wait before forcing an exit. */
  timeStop?: { exitDate: string; days: number | null } | null;
}) {
  const [position, setPosition] = useStoredPosition(ticker);
  const [editing, setEditing] = useState(false);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-xs font-medium tracking-wider uppercase text-muted-foreground">
            My Position
          </CardTitle>
          {position && !editing ? (
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setEditing(true)}
                className="h-6 px-1.5"
                aria-label="Edit position"
                title="Edit"
              >
                <Pencil className="h-3 w-3" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setPosition(null)}
                className="h-6 px-1.5 text-bearish hover:text-bearish"
                aria-label="Clear position"
                title="Clear"
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </div>
          ) : null}
        </div>
      </CardHeader>
      <CardContent>
        {position && !editing ? (
          <PositionView
            position={position}
            mark={mark}
            entry={entry}
            stop={stop}
            target={target}
            action={action}
            score={score}
            timeStop={timeStop ?? null}
          />
        ) : (
          <PositionForm
            initial={position}
            onSave={(p) => {
              setPosition(p);
              setEditing(false);
            }}
            onCancel={position ? () => setEditing(false) : undefined}
          />
        )}
      </CardContent>
    </Card>
  );
}

// ─── Form (no position yet, or editing) ─────────────────────────────────────

function PositionForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: StoredPosition | null;
  onSave: (p: StoredPosition) => void;
  onCancel?: () => void;
}) {
  const [shares, setShares] = useState<string>(
    initial ? String(initial.shares) : "",
  );
  const [avgCost, setAvgCost] = useState<string>(
    initial ? String(initial.avg_cost) : "",
  );

  const sharesNum = Number(shares);
  const avgCostNum = Number(avgCost);
  const valid =
    Number.isFinite(sharesNum) &&
    sharesNum > 0 &&
    Number.isFinite(avgCostNum) &&
    avgCostNum > 0;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!valid) return;
        onSave({ shares: sharesNum, avg_cost: avgCostNum });
      }}
      className="space-y-3"
    >
      <p className="text-muted-foreground text-xs font-mono leading-relaxed">
        Already long this ticker? Enter your real (or hypothetical) cost
        basis. The engine&apos;s action + risk levels turn into a
        position-management call: HOLD / ADD / TRIM / EXIT.
      </p>
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label
            htmlFor="position-shares"
            className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase"
          >
            Shares
          </Label>
          <Input
            id="position-shares"
            type="number"
            min={0}
            step="any"
            inputMode="decimal"
            placeholder="100"
            value={shares}
            onChange={(e) => setShares(e.target.value)}
            className="font-mono text-xs tabular-nums"
            autoFocus
          />
        </div>
        <div className="space-y-1">
          <Label
            htmlFor="position-avg"
            className="text-[10px] font-medium tracking-wider text-muted-foreground uppercase"
          >
            Avg cost $
          </Label>
          <Input
            id="position-avg"
            type="number"
            min={0}
            step="any"
            inputMode="decimal"
            placeholder="185.50"
            value={avgCost}
            onChange={(e) => setAvgCost(e.target.value)}
            className="font-mono text-xs tabular-nums"
          />
        </div>
      </div>
      <div className="flex items-center justify-end gap-2">
        {onCancel ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onCancel}
            className="font-mono text-[11px] tracking-wider uppercase h-7"
          >
            Cancel
          </Button>
        ) : null}
        <Button
          type="submit"
          variant="outline"
          size="sm"
          disabled={!valid}
          className="font-mono text-[11px] tracking-wider uppercase h-7"
        >
          Evaluate
        </Button>
      </div>
    </form>
  );
}

// ─── Computed view (position present) ───────────────────────────────────────

function PositionView({
  position,
  mark,
  entry,
  stop,
  target,
  action,
  score,
  timeStop,
}: {
  position: StoredPosition;
  mark: number | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  action: string | null;
  score: number | null;
  timeStop: { exitDate: string; days: number | null } | null;
}) {
  const { shares, avg_cost } = position;
  const value = mark !== null ? mark * shares : null;
  const cost = avg_cost * shares;
  const pl = value !== null ? value - cost : null;
  const plPct = pl !== null && cost > 0 ? (pl / cost) * 100 : null;

  const distanceToStopPct =
    mark !== null && stop !== null && mark > 0 ? ((stop - mark) / mark) * 100 : null;
  const distanceToTargetPct =
    mark !== null && target !== null && mark > 0 ? ((target - mark) / mark) * 100 : null;

  const rec = recommendPositionAction({
    engineAction: action,
    score,
    mark,
    avgCost: avg_cost,
    stop,
    target,
  });

  const toneClass =
    rec.tone === "bullish"
      ? "border-bullish/40 bg-bullish/5 text-bullish"
      : rec.tone === "bearish"
        ? "border-bearish/40 bg-bearish/5 text-bearish"
        : "border-border bg-muted/30 text-foreground";

  return (
    <div className="space-y-3">
      <div className="font-mono text-xs text-muted-foreground">
        <span className="text-foreground">{fmtNumber(shares, shares % 1 === 0 ? 0 : 4)}</span>{" "}
        shares @ <span className="text-foreground">{fmtUSD(avg_cost)}</span> ·
        cost <span className="text-foreground">{fmtUSD(cost)}</span>
      </div>

      <div className="grid grid-cols-2 gap-2 font-mono text-[11px]">
        <Stat label="Position value" value={fmtUSD(value)} />
        <Stat
          label="Unrealized P&L"
          value={
            <span
              className={cn(
                pl == null
                  ? "text-muted-foreground"
                  : pl > 0
                    ? "text-bullish"
                    : pl < 0
                      ? "text-bearish"
                      : "text-foreground",
              )}
            >
              {pl == null ? "—" : `${pl > 0 ? "+" : ""}${fmtUSD(pl)}`}
              {plPct !== null ? (
                <span className="ml-1 text-[10px] opacity-80">
                  ({fmtPct(plPct, 2, true)})
                </span>
              ) : null}
            </span>
          }
        />
      </div>

      <div
        className={cn(
          "rounded-md border px-3 py-2 font-mono",
          toneClass,
        )}
      >
        <div className="text-[10px] tracking-wider uppercase opacity-70 mb-1">
          Recommended action
        </div>
        <div className="text-sm font-semibold tracking-tight">{rec.headline}</div>
        <p className="mt-1 text-[11px] leading-relaxed text-foreground/80">
          {rec.reason}
        </p>
      </div>

      <dl className="space-y-1 text-[11px] font-mono">
        <Row label="Mark" value={fmtUSD(mark)} />
        {stop !== null ? (
          <Row
            label="Stop"
            value={
              <span>
                <span className="text-bearish">{fmtUSD(stop)}</span>
                {distanceToStopPct !== null ? (
                  <span className="ml-1 text-muted-foreground">
                    ({fmtPct(distanceToStopPct, 1, true)})
                  </span>
                ) : null}
              </span>
            }
          />
        ) : null}
        {target !== null ? (
          <Row
            label="Take profit"
            value={
              <span>
                <span className="text-bullish">{fmtUSD(target)}</span>
                {distanceToTargetPct !== null ? (
                  <span className="ml-1 text-muted-foreground">
                    ({fmtPct(distanceToTargetPct, 1, true)})
                  </span>
                ) : null}
              </span>
            }
          />
        ) : null}
        {entry !== null && Math.abs(entry - avg_cost) > 0.01 ? (
          <Row
            label="Engine entry"
            value={
              <span>
                <span className="text-foreground">{fmtUSD(entry)}</span>
                <span className="ml-1 text-muted-foreground">
                  (your avg {avg_cost > entry ? "over" : "under"})
                </span>
              </span>
            }
          />
        ) : null}
        {timeStop ? (
          <Row
            label="Time stop"
            value={
              <span title="Triple-barrier exit: the engine forces an exit if neither stop nor target fires by this date. Calibrated to the strategy's alpha half-life.">
                <span className="text-foreground">{timeStop.exitDate}</span>
                {timeStop.days != null ? (
                  <span className="ml-1 text-muted-foreground">
                    ({timeStop.days}d budget)
                  </span>
                ) : null}
              </span>
            }
          />
        ) : null}
      </dl>
    </div>
  );
}

function Stat({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="border border-border rounded px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-0.5 font-mono text-sm font-semibold tabular-nums truncate">
        {value}
      </div>
    </div>
  );
}

function Row({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className="text-foreground tabular-nums">{value}</span>
    </div>
  );
}
