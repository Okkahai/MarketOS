import Link from "next/link";
import { notFound } from "next/navigation";
import { PriceChart } from "@/components/PriceChart";
import { api, type Bar, type Indicator, type Interval } from "@/lib/api";
import { toSeries } from "@/lib/chart";
import { formatDecimalString, formatUtc } from "@/lib/format";

export const dynamic = "force-dynamic";

const INTERVALS: Interval[] = ["1d", "1h", "5m", "1m"];

// Indicator values are ratios unless listed as plain numbers.
const INDICATORS: Record<string, { label: string; percent?: boolean }> = {
  ret_1: { label: "Return, 1 bar", percent: true },
  ret_5: { label: "Return, 5 bars", percent: true },
  ret_20: { label: "Return, 20 bars", percent: true },
  vol_20: { label: "Volatility, 20 bars (per bar)", percent: true },
  sma_20: { label: "SMA 20" },
  sma_50: { label: "SMA 50" },
  sma_200: { label: "SMA 200" },
  ema_12: { label: "EMA 12" },
  ema_26: { label: "EMA 26" },
  rsi_14: { label: "RSI 14" },
  macd: { label: "MACD" },
  macd_signal: { label: "MACD signal" },
  macd_hist: { label: "MACD histogram" },
  atr_14: { label: "ATR 14" },
  atr_14_pct: { label: "ATR 14 / close", percent: true },
  volume_ratio_20: { label: "Volume vs previous 20 bars (x)" },
  drawdown: { label: "Drawdown from peak in window", percent: true },
  rel_strength_20: { label: "Relative strength vs benchmark, 20 bars", percent: true },
  corr_20: { label: "Correlation vs benchmark, 20 bars" },
};

export default async function AssetPage({
  params,
  searchParams,
}: {
  params: Promise<{ symbol: string }>;
  searchParams: Promise<{ interval?: string }>;
}) {
  const { symbol: raw } = await params;
  const symbol = decodeURIComponent(raw).toUpperCase();
  const asset = await api.asset(symbol);
  if (!asset.ok && asset.httpStatus === 404) notFound();

  const available = await api.intervals(symbol);
  const offered = available.ok ? INTERVALS.filter((i) => available.data.includes(i)) : [];
  const requested = (await searchParams).interval as Interval | undefined;
  const interval: Interval =
    requested && offered.includes(requested) ? requested : (offered[0] ?? "1d");

  const [bars, indicators, signals, trades] = await Promise.all([
    offered.length ? api.bars(symbol, interval) : Promise.resolve(null),
    api.indicators(symbol),
    api.signals({ symbol }),
    api.trades(20, symbol),
  ]);

  return (
    <>
      <header className="page-header">
        <p className="muted small">
          <Link href="/market">← Market</Link>
        </p>
        <h1>
          {symbol}
          {asset.ok ? <span className="muted"> {asset.data.name}</span> : null}
          {asset.ok && asset.data.is_benchmark ? (
            <span className="badge badge-bench">BENCHMARK</span>
          ) : null}
        </h1>
        {asset.ok ? (
          <p className="muted">
            {asset.data.asset_class}
            {asset.data.exchange ? ` · ${asset.data.exchange}` : ""}
            {asset.data.sector ? ` · ${asset.data.sector}` : ""}
          </p>
        ) : (
          <p className="error-note" role="alert">
            {asset.error}
          </p>
        )}
      </header>

      <section className="card">
        <div className="chart-head">
          <h2>Price</h2>
          <nav aria-label="Interval" className="tabs">
            {offered.map((i) => (
              <Link
                key={i}
                href={`/asset/${encodeURIComponent(symbol)}?interval=${i}`}
                aria-current={i === interval ? "page" : undefined}
              >
                {i}
              </Link>
            ))}
          </nav>
        </div>
        {bars === null || !bars.ok ? (
          bars === null ? (
            <p className="muted">
              No bars have been collected for this asset yet. Check{" "}
              <Link href="/">System status</Link> for the collection jobs and any provider failures.
            </p>
          ) : (
            <p className="error-note" role="alert">
              {bars.error}
            </p>
          )
        ) : (
          <>
            <PriceChart {...toSeries(bars.data, interval)} intraday={interval !== "1d"} />
            <LastBar bars={bars.data} />
          </>
        )}
      </section>

      <section className="card">
        <h2>Indicators (daily bars)</h2>
        {!indicators.ok ? (
          <p className="error-note" role="alert">
            {indicators.error}
          </p>
        ) : indicators.data.length === 0 ? (
          <p className="muted">No indicators computed yet. They need enough daily bars.</p>
        ) : (
          <IndicatorTable rows={indicators.data} />
        )}
        <p className="muted small">
          Indicators are computed in code from stored bars, never by the AI.
        </p>
      </section>

      <section className="card">
        <h2>Recommendations and trades</h2>
        {signals.ok && signals.data.length > 0 ? (
          <ul>
            {signals.data.slice(0, 8).map((x) => (
              <li key={x.id}>
                {formatUtc(x.generated_at)} · {x.action.replace("_", " ")} · confidence{" "}
                {formatDecimalString(x.confidence, 2, 2)} · <Link href={`/signals/${x.id}`}>trace</Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No recommendations for this asset yet.</p>
        )}
        {trades.ok && trades.data.length > 0 ? (
          <ul>
            {trades.data.map((t) => (
              <li key={t.id}>
                {formatUtc(t.executed_at)} · {t.side} {formatDecimalString(t.quantity, 2, 8)} at{" "}
                {formatDecimalString(t.price, 2, 4)} · <Link href={`/signals/${t.signal_id}`}>why</Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No paper trades in this asset.</p>
        )}
      </section>
    </>
  );
}

function LastBar({ bars }: { bars: Bar[] }) {
  const last = bars[bars.length - 1];
  if (!last) return <p className="muted">The provider returned no bars for this range.</p>;
  return (
    <dl className="kv last-bar">
      <dt>Bar start (UTC)</dt>
      <dd>{formatUtc(last.ts)}</dd>
      <dt>Open / High / Low / Close</dt>
      <dd>
        {[last.open, last.high, last.low, last.close].map((v) => formatDecimalString(v)).join(" / ")}
      </dd>
      <dt>Volume</dt>
      <dd>{formatDecimalString(last.volume, 0, 2)}</dd>
      <dt>Usable since</dt>
      <dd>
        {formatUtc(last.available_at)}
        {last.revision > 0 ? ` (revision ${last.revision})` : ""}
      </dd>
    </dl>
  );
}

function IndicatorTable({ rows }: { rows: Indicator[] }) {
  const order = Object.keys(INDICATORS);
  const rank = (name: string) => (order.includes(name) ? order.indexOf(name) : order.length);
  rows = [...rows].sort((a, b) => rank(a.name) - rank(b.name));
  return (
    <>
      <p className="muted small">As of bar {formatUtc(rows[0]?.ts ?? null)}</p>
      <table>
        <tbody>
          {rows.map((row) => {
            const meta = INDICATORS[row.name];
            const n = Number(row.value);
            return (
              <tr key={row.name}>
                <td>{meta?.label ?? row.name}</td>
                <td className="num">
                  {meta?.percent ? `${(n * 100).toFixed(2)}%` : n.toFixed(4)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}
