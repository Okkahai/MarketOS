"use client";

import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type IChartApi,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Candle, VolumePoint } from "@/lib/chart";

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function PriceChart({
  candles,
  volume,
  intraday,
}: {
  candles: Candle[];
  volume: VolumePoint[];
  intraday: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const up = cssVar("--ok");
    const down = cssVar("--err");
    const chart: IChartApi = createChart(el, {
      autoSize: true,
      height: 380,
      layout: {
        background: { type: ColorType.Solid, color: cssVar("--surface") },
        textColor: cssVar("--muted"),
      },
      grid: {
        vertLines: { color: cssVar("--border") },
        horzLines: { color: cssVar("--border") },
      },
      timeScale: { timeVisible: intraday, borderColor: cssVar("--border") },
      rightPriceScale: { borderColor: cssVar("--border") },
    });
    // Leave the bottom fifth of the pane to the volume histogram so it never covers candles.
    chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.05, bottom: 0.25 } });
    const price = chart.addSeries(CandlestickSeries, {
      upColor: up,
      downColor: down,
      borderUpColor: up,
      borderDownColor: down,
      wickUpColor: up,
      wickDownColor: down,
    });
    price.setData(candles as never);
    const vol = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: `${cssVar("--muted")}66`, // muted grey at ~40% opacity
    });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    vol.setData(volume as never);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [candles, volume, intraday]);

  return <div ref={container} className="chart" role="img" aria-label="Price chart" />;
}
