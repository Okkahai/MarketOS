import Link from "next/link";
import { api } from "@/lib/api";
import { formatUtc } from "@/lib/format";

export const dynamic = "force-dynamic";

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;

export default async function BacktestsPage() {
  const runs = await api.backtests();
  return (
    <>
      <header className="page-header">
        <h1>Backtests</h1>
        <p className="muted">
          Past windows replayed through the same risk and paper trading code, using only the news
          and prices that had been collected by each moment. They never touch the live portfolio.
          Start one with <code>python -m app.backtest --start 2026-08-01 --end 2026-09-28</code>.
        </p>
      </header>
      {!runs.ok ? (
        <p className="error-note" role="alert">
          {runs.error}
        </p>
      ) : runs.data.length === 0 ? (
        <div className="card">
          <p>No backtests yet.</p>
          <p className="muted">
            A backtest can only replay news that was collected at the time, so it needs some weeks
            of stored history first.
          </p>
        </div>
      ) : (
        <section className="card table-scroll">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Window (UTC)</th>
                <th>Status</th>
                <th className="num">Return</th>
                <th className="num">Max drawdown</th>
                <th className="num">Trades</th>
              </tr>
            </thead>
            <tbody>
              {runs.data.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link href={`/backtests/${r.id}`}>{r.name}</Link>
                  </td>
                  <td>
                    {formatUtc(r.start_at).slice(0, 10)} to {formatUtc(r.end_at).slice(0, 10)}
                  </td>
                  <td>{r.status}</td>
                  <td className="num">{pct(r.summary?.portfolio.return_pct)}</td>
                  <td className="num">
                    {r.summary?.portfolio.max_drawdown_pct == null
                      ? "—"
                      : `${r.summary.portfolio.max_drawdown_pct.toFixed(2)}%`}
                  </td>
                  <td className="num">{r.summary?.trade_count ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
