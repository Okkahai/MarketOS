import type { Bar, Interval } from "./api";

// Lightweight Charts draws with JS numbers, so this is the one place prices leave decimal
// strings. It is display-only; nothing computed here goes back to the API.

export type Candle = { time: string | number; open: number; high: number; low: number; close: number };
export type VolumePoint = { time: string | number; value: number };

export function chartTime(ts: string, interval: Interval): string | number {
  const ms = Date.parse(ts);
  return interval === "1d"
    ? new Date(ms).toISOString().slice(0, 10)
    : Math.floor(ms / 1000);
}

// The chart requires strictly ascending, unique times. Bars the API returns already are; this
// keeps a malformed response from throwing inside the chart.
export function toSeries(bars: Bar[], interval: Interval): { candles: Candle[]; volume: VolumePoint[] } {
  const byTime = new Map<string | number, Bar>();
  for (const bar of bars) byTime.set(chartTime(bar.ts, interval), bar);
  const times = [...byTime.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const candles: Candle[] = [];
  const volume: VolumePoint[] = [];
  for (const time of times) {
    const bar = byTime.get(time)!;
    candles.push({
      time,
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    });
    volume.push({ time, value: Number(bar.volume) });
  }
  return { candles, volume };
}
