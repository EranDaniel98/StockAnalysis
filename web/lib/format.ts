/** Number + date formatting helpers shared across pages. */

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

const usdCompactFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

export function fmtUSD(n: number | null | undefined, compact = false) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return compact ? usdCompactFmt.format(n) : usdFmt.format(n);
}

export function fmtPct(
  n: number | null | undefined,
  fractionDigits = 2,
  withSign = false,
) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = withSign && n > 0 ? "+" : "";
  return `${sign}${n.toFixed(fractionDigits)}%`;
}

export function fmtNumber(
  n: number | null | undefined,
  fractionDigits = 2,
): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(fractionDigits);
}

export function fmtDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Bloomberg-style relative timestamp: "just now", "12m ago", "3h ago",
 * "2d ago". Falls back to fmtDate for anything older than 14 days so a
 * date doesn't become "428d ago".
 */
export function fmtRelativeTime(
  value: string | Date | null | undefined,
  now: Date = new Date(),
): string {
  if (!value) return "—";
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  const diffMs = now.getTime() - d.getTime();
  const absSec = Math.round(Math.abs(diffMs) / 1000);
  const future = diffMs < 0;
  const suffix = future ? "from now" : "ago";
  if (absSec < 45) return future ? "in a moment" : "just now";
  const absMin = Math.round(absSec / 60);
  if (absMin < 60) return `${absMin}m ${suffix}`;
  const absHr = Math.round(absMin / 60);
  if (absHr < 24) return `${absHr}h ${suffix}`;
  const absDay = Math.round(absHr / 24);
  if (absDay <= 14) return `${absDay}d ${suffix}`;
  return fmtDate(d);
}

/** Hours between `value` and now (positive when `value` is in the past). */
export function hoursSince(value: string | Date | null | undefined): number | null {
  if (!value) return null;
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return (Date.now() - d.getTime()) / (1000 * 60 * 60);
}

export function pnlColorClass(n: number | null | undefined): string {
  // Routes positive P&L → bullish token, negative → bearish token. The
  // tokens are defined in web/app/globals.css and themed in STYLE.md;
  // updating them recolors every page that imports this helper without
  // page-level edits.
  if (n === null || n === undefined || Number.isNaN(n)) return "";
  if (n > 0) return "text-bullish";
  if (n < 0) return "text-bearish";
  return "text-muted-foreground";
}
