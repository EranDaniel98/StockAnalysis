/**
 * Recharts chart-token contract.
 *
 * This file is the single source of truth for chart colors across every
 * Recharts-powered page (/backtests/[id], /backtests/compare, /calibration,
 * /diagnose, /ml, /portfolio sparkline, ...). Pages MUST consume these
 * constants instead of hardcoding hex / rgb / oklch / hsl values.
 *
 * Recharts accepts CSS `var()` strings directly in `stroke` / `fill` props
 * (verified on recharts >= 2.7). When a value is needed as a literal at
 * runtime (e.g. fed into a gradient stop, or to compute a tinted derivative),
 * use `resolveChartColor()` which reads the variable off `document.documentElement`.
 *
 * Naming is semantic, not slot-numbered, so a page reading the file knows
 * *why* it picked a color, not just which slot it lives in. The slot mapping
 * (chart-1..5) is preserved for the colorblind-friendly multi-series ordering
 * documented in STYLE.md.
 */

/** Semantic chart-token map. Use these in JSX. */
export const CHART_TOKEN = {
  info: "var(--chart-1)",      // cyan   — benchmarks, neutral overlay series
  bullish: "var(--chart-2)",   // mint   — equity-up, profit, primary portfolio series
  primary: "var(--chart-3)",   // amber  — highlighted series / IS-OOS split marker
  bearish: "var(--chart-4)",   // coral  — drawdown, loss, downside series
  neutral: "var(--chart-5)",   // graphite — background / reference lines
} as const;

export type ChartTokenName = keyof typeof CHART_TOKEN;

/** Grid + axis tokens — paired with CHART_TOKEN so chart pages don't reach
 *  into raw Tailwind variables for these. */
export const CHART_GRID = "var(--border)";
export const CHART_AXIS = "var(--muted-foreground)";
export const CHART_TOOLTIP_BG = "var(--popover)";
export const CHART_TOOLTIP_BORDER = "var(--border)";

/**
 * Resolve a CSS variable string to its computed color, evaluated against
 * `document.documentElement`. Only call this from useEffect / event handlers —
 * SSR has no document. Returns an empty string on the server so callers can
 * fall back to the `var()` literal.
 *
 * Useful when you need to feed an SVG <linearGradient> with stopColor that
 * Recharts doesn't pre-process, or when constructing a fillOpacity ramp.
 */
export function resolveChartColor(varName: string): string {
  if (typeof document === "undefined") return "";
  const name = varName.startsWith("var(")
    ? varName.slice(4, -1)
    : varName.startsWith("--")
      ? varName
      : `--${varName}`;
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
}

/**
 * Convenience for multi-series charts: `chartColor(0)` -> chart-1 (info),
 * `chartColor(1)` -> chart-2 (bullish), ... wrapping after 5.
 */
export function chartColor(index: number): string {
  const ordered: string[] = [
    CHART_TOKEN.info,
    CHART_TOKEN.bullish,
    CHART_TOKEN.primary,
    CHART_TOKEN.bearish,
    CHART_TOKEN.neutral,
  ];
  return ordered[((index % ordered.length) + ordered.length) % ordered.length];
}
