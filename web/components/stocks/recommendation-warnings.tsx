import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import type { ScanResultItem } from "@/lib/api/client";

/**
 * Recommendation integrity banner.
 *
 * Renders a destructive alert above the action badge whenever the
 * backend's data-quality gates have refused to emit a confident
 * recommendation. Three reasons:
 *
 *   1. ``instrument_warning="leveraged_or_inverse_etf"`` —
 *      ProShares/Direxion/Tradr daily-leveraged/inverse ETFs. The
 *      composite scoring is calibrated for buy-and-hold equities and
 *      these decay under volatility.
 *   2. ``instrument_warning="non_stock_instrument"`` — an ETF / fund /
 *      trust with no sector + market cap. Scoring still runs but the
 *      values aren't directly comparable to the equity universe.
 *   3. ``insufficient_history=True`` — fewer than ~252 daily bars.
 *      Technical / statistical / alpha158 analyzers couldn't produce
 *      reliable sub-scores; the composite is built from a degraded
 *      analyzer chain.
 *   4. ``score_valid=False`` — engine refused to emit a valid composite
 *      because no required analyzer fired (placeholder 50.0 score).
 *
 * Returns null for ordinary recommendations.
 */
export function RecommendationWarnings({ rec }: { rec: ScanResultItem }) {
  const instrumentWarning = rec.instrument_warning;
  const insufficientHistory = rec.insufficient_history === true;
  const scoreInvalid = rec.score_valid === false;

  if (!instrumentWarning && !insufficientHistory && !scoreInvalid) {
    return null;
  }

  const items: { title: string; description: string }[] = [];

  if (instrumentWarning === "leveraged_or_inverse_etf") {
    items.push({
      title: "Leveraged or inverse ETF — recommendation refused",
      description:
        rec.instrument_warning_reason ??
        "Daily-leveraged or inverse ETFs decay under volatility. They aren't suitable for the quarterly-rebalance factor strategy.",
    });
  } else if (instrumentWarning === "non_stock_instrument") {
    items.push({
      title: "Non-stock instrument — score not comparable",
      description:
        rec.instrument_warning_reason ??
        "This appears to be an ETF / fund / trust. Composite scoring is calibrated for individual equities; the result isn't directly comparable to the stock universe.",
    });
  } else if (instrumentWarning) {
    items.push({
      title: `Instrument flagged: ${instrumentWarning}`,
      description:
        rec.instrument_warning_reason ??
        "The instrument classifier flagged this ticker.",
    });
  }

  if (insufficientHistory) {
    const bars = rec.history_bars_available ?? 0;
    const required = rec.history_bars_required ?? 252;
    items.push({
      title: "Insufficient price history",
      description: `Only ${bars} daily bars available (need ~${required} for the technical / statistical / alpha158 analyzers). Recent IPO or low-coverage ticker — the composite is built from a degraded analyzer chain.`,
    });
  }

  if (scoreInvalid) {
    const errs = rec.error_count ?? 0;
    const slots = (rec.error_slots ?? []) as string[];
    items.push({
      title: "Composite score invalid",
      description: `No required analyzer fired (${errs} analyzers errored${slots.length ? `: ${slots.join(", ")}` : ""}). The displayed score is a 50.0 placeholder; the action has been forced to HOLD.`,
    });
  }

  return (
    <Alert variant="destructive">
      <AlertTitle className="text-sm">
        Data quality warning — recommendation has been refused
      </AlertTitle>
      <AlertDescription className="text-xs leading-relaxed space-y-2">
        {items.map((item, i) => (
          <div key={i}>
            <strong className="block">{item.title}</strong>
            <span>{item.description}</span>
          </div>
        ))}
      </AlertDescription>
    </Alert>
  );
}


/**
 * Action badge — swaps "HOLD/None" → "REFUSED" when the data-quality
 * gates fired, so the operator sees the refusal verbatim instead of a
 * confusing neutral-looking HOLD.
 */
export function actionLabelForGate(rec: ScanResultItem): string {
  const hasGate =
    !!rec.instrument_warning ||
    rec.insufficient_history === true ||
    rec.score_valid === false;
  if (hasGate) {
    return "REFUSED";
  }
  return rec.action;
}
