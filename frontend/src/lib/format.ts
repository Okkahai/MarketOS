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

// Trims a decimal string to at least `min` and at most `max` fraction digits, without rounding
// through a float. Digits beyond `max` are cut, never rounded up.
export function formatDecimalString(value: string, min = 2, max = 8): string {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!match) return value;
  const [, sign, whole = "0", fraction = ""] = match;
  let frac = fraction.slice(0, max).replace(/0+$/, "");
  frac = frac.padEnd(min, "0");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return frac ? `${sign}${grouped}.${frac}` : `${sign}${grouped}`;
}

// "3.3000" -> "+3.30%". The sign is always shown so direction never depends on colour alone.
export function formatSignedPercent(value: string): string {
  const text = formatDecimalString(value, 2, 2);
  if (text === value) return value;
  return text.startsWith("-") ? `${text}%` : `+${text}%`;
}

export function changeDirection(value: string | null): "up" | "down" | "flat" | "unknown" {
  if (value === null) return "unknown";
  const n = Number(value);
  if (Number.isNaN(n)) return "unknown";
  return n > 0 ? "up" : n < 0 ? "down" : "flat";
}

export function formatUtcDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "invalid time" : date.toISOString().slice(0, 10);
}

// Article links come from third-party feeds. The API only stores http(s) URLs; this is the
// second check before a link is rendered.
export function safeHttpUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}
