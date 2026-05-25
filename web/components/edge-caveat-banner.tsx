import { AlertTriangle } from "lucide-react";

export function EdgeCaveatBanner() {
  return (
    <div className="border-border/40 bg-amber-500/10 border-b text-amber-200 dark:text-amber-300">
      <details className="mx-auto max-w-7xl px-6 py-2 text-xs">
        <summary className="flex cursor-pointer list-none items-center gap-2 font-medium">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span>
            Paper-trade only · cross-window OOS α ≈ <strong>+1.88%/yr</strong>,
            inside the ±0.4 Sharpe noise envelope.
          </span>
          <span className="ml-auto opacity-60">why?</span>
        </summary>
        <p className="mt-2 pl-5.5 leading-relaxed opacity-90">
          Cross-window OOS α averages <strong>+1.88%/yr</strong> across three
          backtest windows, but the COVID window fails walk-forward
          (fold-by-fold breakdown). Independent re-runs of the same backtest
          12 h apart drift by ±0.4 Sharpe due to yfinance adjustment lag —
          the same magnitude as the α point estimate. The picks are a
          defensible factor signal, <strong>not a proven edge</strong>.
          Reconcile against SPY weekly before sizing real money.
        </p>
      </details>
    </div>
  );
}
