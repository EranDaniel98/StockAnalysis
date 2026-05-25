import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * Edge-uncertainty disclosure shown above the factor-strategy picks.
 *
 * Numbers come from MEMORY.md project notes:
 *   - final-edge-verdict (alpha point estimate vs noise envelope)
 *   - yfinance-nondeterminism (±0.4 Sharpe drift between identical runs)
 *   - factor-composite-edge (3-window walk-forward: COVID fails)
 *
 * Keep this visible. It's the difference between "treating the picks
 * as a signal" and "treating the picks as an answer". The math doesn't
 * yet prove the second.
 */
export function EdgeUncertaintyBanner() {
  return (
    <Alert variant="destructive">
      <AlertTitle className="text-sm">
        Edge magnitude is in the noise envelope — paper-trade first
      </AlertTitle>
      <AlertDescription className="text-xs leading-relaxed">
        Cross-window OOS α averages <strong>+1.88%/yr</strong> across three
        backtest windows, but the COVID window <strong>fails walk-forward</strong>{" "}
        (fold-by-fold breakdown). Independent re-runs of the same backtest
        12 h apart drift by <strong>±0.4 Sharpe</strong> due to yfinance
        adjustment lag — the same magnitude as the α point estimate. The
        picks are a defensible factor signal, not a proven edge. Reconcile
        against SPY weekly before sizing real money.
      </AlertDescription>
    </Alert>
  );
}
