import { describe, expect, it } from "vitest";
import { formatMoneyString, formatUtc } from "./format";

describe("formatMoneyString", () => {
  it("groups thousands and keeps exact cents", () => {
    expect(formatMoneyString("10000", "USD")).toBe("10,000.00 USD");
    expect(formatMoneyString("1234567.891", "USD")).toBe("1,234,567.89 USD");
    expect(formatMoneyString("-0.5", "USD")).toBe("-0.50 USD");
  });

  it("does not lose precision the way floats would", () => {
    expect(formatMoneyString("9007199254740993.10", "USD")).toBe("9,007,199,254,740,993.10 USD");
  });

  it("shows unparseable input as-is rather than guessing", () => {
    expect(formatMoneyString("n/a", "USD")).toBe("n/a USD");
  });
});

describe("formatUtc", () => {
  it("formats ISO timestamps in UTC", () => {
    expect(formatUtc("2026-09-28T15:04:05.123+03:00")).toBe("2026-09-28 12:04:05 UTC");
  });

  it("handles missing and invalid values", () => {
    expect(formatUtc(null)).toBe("—");
    expect(formatUtc("nope")).toBe("invalid time");
  });
});

import { changeDirection, formatDecimalString, formatSignedPercent, formatUtcDate } from "./format";

describe("formatDecimalString", () => {
  it("trims padding zeros but keeps at least two decimals", () => {
    expect(formatDecimalString("103.3000000000")).toBe("103.30");
    expect(formatDecimalString("65000")).toBe("65,000.00");
    expect(formatDecimalString("1234567.891")).toBe("1,234,567.891");
  });

  it("keeps small crypto prices readable and never rounds up", () => {
    expect(formatDecimalString("0.0000123000")).toBe("0.0000123");
    expect(formatDecimalString("0.999999999", 2, 4)).toBe("0.9999");
  });

  it("passes through what it cannot parse", () => {
    expect(formatDecimalString("n/a")).toBe("n/a");
  });
});

describe("percent and direction", () => {
  it("always shows a sign", () => {
    expect(formatSignedPercent("3.3000")).toBe("+3.30%");
    expect(formatSignedPercent("-0.5000")).toBe("-0.50%");
    expect(formatSignedPercent("0.0000")).toBe("+0.00%");
  });

  it("classifies direction and treats missing as unknown", () => {
    expect(changeDirection("1.2")).toBe("up");
    expect(changeDirection("-1.2")).toBe("down");
    expect(changeDirection("0.0000")).toBe("flat");
    expect(changeDirection(null)).toBe("unknown");
  });

  it("formats dates in UTC", () => {
    expect(formatUtcDate("2026-09-25T23:30:00-05:00")).toBe("2026-09-26");
    expect(formatUtcDate(null)).toBe("—");
  });
});
