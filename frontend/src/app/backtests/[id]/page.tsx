import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { formatDecimalString, formatUtc } from "@/lib/format";

export const dynamic = "force-dynamic";

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const num = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : v.toFixed(2);

export default async function BacktestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [run, trades] = await Promise.all([api.backtest(id), api.backtestTrades(id)]);
  if (!run.ok && run.httpStatus === 404) notFound();
  if (!run.ok) {
    return (
      <p className="error-note" role="alert">
        {run.error}
      </p>
    );
  }
  const r = run.data;
  const s = r.summary;
  const values = r.snapshots.filter((x) => x.total_value !== null).map((x) => Number(x.total_value));
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const path = values
    .map((v, i) => `${(i / Math.max(values.length - 1, 1)) * 600},${100 - ((v - lo) / (hi - lo || 1)) * 90 - 5}`)
    .join(" ");

  return (
    <>
      <header className="page-header">
        <p className="muted small">
          <Link href="/backtests">← Backtests</Link>
        </p>
        <h1>{r.name}</h1>
        <p className="muted">
          {formatUtc(r.start_at)} to {formatUtc(r.end_at)}, one step every {r.step_hours} hours,
          starting with {formatDecimalString(r.initial_capital, 2, 2)} virtual USD. Status:{" "}
          {r.status}.
        </p>
      </header>
      {r.error ? (
        <p className="error-note" role="alert">
          {r.error}
        </p>
      ) : null}
      {s ? (
        <>
          <section className="card table-scroll">
            <h2>Result</h2>
            <p>
              Return {pct(s.portfolio.return_pct)} · max drawdown {num(s.portfolio.max_drawdown_pct)}% ·
              Sharpe {num(s.portfolio.sharpe)} · Sortino {num(s.portfolio.sortino)}
            </p>
            <table>
              <tbody>
                {s.benchmarks.map((b) => (
                  <tr key={b.symbol}>
                    <td>{b.symbol === "CASH" ? "Holding cash" : `Buy and hold ${b.symbol}`}</td>
                    <td className="num">{pct(b.return_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">
              {s.events_analysed} events analysed, {s.signals_journalled} recommendations,{" "}
              {Object.entries(s.decisions)
                .map(([k, v]) => `${v} ${k}`)
                .join(", ") || "no decisions"}
              , {s.orders_filled} orders filled, {s.orders_expired} expired, {s.trades.closed} closed
              positions.
            </p>
            <p className="muted small">{s.notes}</p>
          </section>
          {values.length >= 2 ? (
            <section className="card">
              <h2>Portfolio value</h2>
              <svg viewBox="0 0 600 100" role="img" aria-label="Backtest portfolio value" width="100%" height="120">
                <polyline points={path} fill="none" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            </section>
          ) : null}
        </>
      ) : null}
      <section className="card table-scroll">
        <h2>Trades</h2>
        {!trades.ok || trades.data.length === 0 ? (
          <p className="muted">No trades in this run.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Executed (UTC)</th>
                <th>Side</th>
                <th>Symbol</th>
                <th>Why</th>
                <th className="num">Quantity</th>
                <th className="num">Price</th>
                <th>Trace</th>
              </tr>
            </thead>
            <tbody>
              {trades.data.map((t) => (
                <tr key={t.id}>
                  <td>{formatUtc(t.executed_at)}</td>
                  <td>{t.side}</td>
                  <td>{t.symbol}</td>
                  <td>{t.reason.replace("_", " ")}</td>
                  <td className="num">{formatDecimalString(t.quantity, 2, 8)}</td>
                  <td className="num">{formatDecimalString(t.price, 2, 4)}</td>
                  <td>
                    <Link href={`/signals/${t.signal_id}`}>Trace</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
