// Formatting only. Money arrives as decimal strings and is displayed without
// passing through floating-point arithmetic.

export function formatMoneyString(value: string, currency: string): string {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!match) return `${value} ${currency}`;
  const [, sign, whole = "0", fraction = ""] = match;
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const cents = (fraction + "00").slice(0, 2);
  // Truncation, not rounding, is intentional for a display-only helper: it
  // never shows more money than the backend reported.
  return `${sign}${grouped}.${cents} ${currency}`;
}

export function formatUtc(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "invalid time";
  return date.toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
}
