import Link from "next/link";
import { api, type WatchlistRow } from "@/lib/api";
import {
  changeDirection,
  formatDecimalString,
  formatSignedPercent,
  formatUtcDate,
} from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function MarketPage() {
  const watchlist = await api.watchlist();

  return (
    <>
      <header className="page-header">
        <h1>Market</h1>
        <p className="muted">
          Latest daily bar per asset. Change is measured against the previous daily bar (adjusted
          closes when available, so splits are not shown as crashes). Signals and analysis columns
          arrive with the AI phases.
        </p>
      </header>

      {!watchlist.ok ? (
        <p className="error-note" role="alert">
          {watchlist.error}
        </p>
      ) : watchlist.data.every((row) => row.last_close === null) ? (
        <div className="card">
          <p>No market data has been collected yet.</p>
          <p className="muted">
            Collection runs on a schedule and needs provider credentials for stocks (
            <code>TIINGO_API_KEY</code>). Check <Link href="/">System status</Link> for job runs and
            failures.
          </p>
        </div>
      ) : null}

      {watchlist.ok ? (
        <div className="card table-scroll">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Name</th>
                <th>Class</th>
                <th className="num">Last close</th>
                <th className="num">Change</th>
                <th className="num">Volume</th>
                <th>Bar date</th>
                <th>Usable since (UTC)</th>
              </tr>
            </thead>
            <tbody>
              {watchlist.data.map((row) => (
                <Row key={row.symbol} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}

function Row({ row }: { row: WatchlistRow }) {
  const direction = changeDirection(row.change_pct);
  return (
    <tr>
      <td>
        <Link href={`/asset/${encodeURIComponent(row.symbol)}`}>{row.symbol}</Link>
        {row.is_benchmark ? <span className="badge badge-bench">BENCHMARK</span> : null}
      </td>
      <td>{row.name}</td>
      <td>{row.asset_class}</td>
      <td className="num">{row.last_close ? formatDecimalString(row.last_close) : "—"}</td>
      <td className={`num change-${direction}`}>
        {row.change_pct
          ? `${direction === "up" ? "▲ " : direction === "down" ? "▼ " : ""}${formatSignedPercent(row.change_pct)}`
          : "—"}
      </td>
      <td className="num">{row.volume ? formatDecimalString(row.volume, 0, 2) : "—"}</td>
      <td>{formatUtcDate(row.last_bar_ts)}</td>
      <td>{row.last_available_at ? row.last_available_at.replace("T", " ").slice(0, 16) : "—"}</td>
    </tr>
  );
}
