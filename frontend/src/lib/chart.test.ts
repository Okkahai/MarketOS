import { describe, expect, it } from "vitest";
import type { Bar } from "./api";
import { chartTime, toSeries } from "./chart";

const bar = (ts: string, close: string): Bar => ({
  ts,
  open: close,
  high: close,
  low: close,
  close,
  adj_close: null,
  volume: "10",
  available_at: ts,
  revision: 0,
});

describe("chartTime", () => {
  it("uses the UTC date for daily bars and unix seconds for intraday", () => {
    expect(chartTime("2026-09-25T00:00:00Z", "1d")).toBe("2026-09-25");
    expect(chartTime("2026-09-25T00:01:00Z", "1m")).toBe(Date.UTC(2026, 8, 25, 0, 1) / 1000);
  });
});

describe("toSeries", () => {
  it("sorts ascending and drops duplicate times", () => {
    const { candles, volume } = toSeries(
      [bar("2026-09-26T00:00:00Z", "3"), bar("2026-09-25T00:00:00Z", "1"), bar("2026-09-25T00:00:00Z", "2")],
      "1d",
    );
    expect(candles.map((c) => c.time)).toEqual(["2026-09-25", "2026-09-26"]);
    expect(candles.map((c) => c.close)).toEqual([2, 3]);
    expect(volume).toHaveLength(2);
  });

  it("returns nothing for no bars instead of inventing a series", () => {
    expect(toSeries([], "1d")).toEqual({ candles: [], volume: [] });
  });
});
