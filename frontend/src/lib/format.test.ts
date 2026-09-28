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
