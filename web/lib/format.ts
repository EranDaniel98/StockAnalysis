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

export function pnlColorClass(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "";
  if (n > 0) return "text-emerald-500";
  if (n < 0) return "text-red-500";
  return "text-muted-foreground";
}
