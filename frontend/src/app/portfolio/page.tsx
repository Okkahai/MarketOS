import Link from "next/link";
import { api, type Portfolio } from "@/lib/api";
import { formatDecimalString, formatUtc } from "@/lib/format";

export const dynamic = "force-dynamic";

const signed = (v: string | null) =>
  v === null ? "—" : `${v.startsWith("-") ? "" : "+"}${formatDecimalString(v, 2, 2)}`;

export default async function PortfolioPage() {
  const [portfolio, pending] = await Promise.all([api.portfolio(), api.orders("pending")]);

  return (
    <>
      <header className="page-header">
        <h1>Paper portfolio</h1>
        <p className="muted">
          Virtual money only. Every position traces back to the recommendation that opened it.
          Values use the latest usable closing price; a position with no price makes the total
          unknown instead of guessing it.
        </p>
      </header>

      {!portfolio.ok ? (
        portfolio.httpStatus === 404 ? (
          <div className="card">
            <p>No paper portfolio yet.</p>
            <p className="muted">
              The first paper trading cycle creates it with the starting capital.{" "}
              <Link href="/">System status</Link> shows whether the cycle has run.
            </p>
          </div>
        ) : (
          <p className="error-note" role="alert">
            {portfolio.error}
          </p>
        )
      ) : (
        <Summary p={portfolio.data} />
      )}

      {portfolio.ok ? <Positions p={portfolio.data} /> : null}

      {pending.ok && pending.data.length > 0 ? (
        <section className="card table-scroll">
          <h2>Waiting to fill</h2>
          <p className="muted">
            Orders fill at the open of the first bar after the decision. If no price arrives before
            they expire, they are dropped, never filled at a guess.
          </p>
          <table>
            <thead>
              <tr>
                <th>Decided (UTC)</th>
                <th>Side</th>
                <th>Symbol</th>
                <th className="num">Budget / quantity</th>
                <th>Expires</th>
              </tr>
            </thead>
            <tbody>
              {pending.data.map((o) => (
                <tr key={o.id}>
                  <td>{formatUtc(o.signal_time)}</td>
                  <td>{o.side}</td>
                  <td>{o.symbol}</td>
                  <td className="num">
                    {formatDecimalString(o.notional ?? o.quantity ?? "0", 2, 6)}
                  </td>
                  <td>{formatUtc(o.expires_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </>
  );
}

function Summary({ p }: { p: Portfolio }) {
  return (
    <div className="card">
      <p>
        <strong>Total value:</strong>{" "}
        {p.total_value ? `${formatDecimalString(p.total_value, 2, 2)} USD` : "unknown (a position has no price)"}
        {" · "}
        <strong>Cash:</strong> {formatDecimalString(p.cash, 2, 2)} USD
        {" · "}
        <strong>Started with:</strong> {formatDecimalString(p.starting_capital, 2, 2)} USD
      </p>
      <p className="muted">
        Realised P&amp;L {signed(p.realized_pnl)} USD · peak value {formatDecimalString(p.peak_value, 2, 2)} ·
        {p.drawdown_pct ? `${formatDecimalString(p.drawdown_pct, 2, 2)}% below peak` : "drawdown unknown"}
      </p>
    </div>
  );
}

function Positions({ p }: { p: Portfolio }) {
  if (p.positions.length === 0) {
    return (
      <div className="card">
        <p>No open positions.</p>
      </div>
    );
  }
  return (
    <section className="card table-scroll">
      <h2>Open positions</h2>
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th className="num">Quantity</th>
            <th className="num">Avg cost</th>
            <th className="num">Last price</th>
            <th className="num">Value</th>
            <th className="num">Unrealised</th>
            <th className="num">Stop / target</th>
            <th>Opened (UTC)</th>
          </tr>
        </thead>
        <tbody>
          {p.positions.map((x) => (
            <tr key={x.symbol}>
              <td>
                <Link href={`/journal?symbol=${encodeURIComponent(x.symbol)}`}>{x.symbol}</Link>
              </td>
              <td className="num">{formatDecimalString(x.quantity, 2, 8)}</td>
              <td className="num">{formatDecimalString(x.avg_cost, 2, 4)}</td>
              <td className="num" title={x.price_ts ?? ""}>
                {x.price ? formatDecimalString(x.price, 2, 4) : "no price"}
              </td>
              <td className="num">{x.market_value ? formatDecimalString(x.market_value, 2, 2) : "—"}</td>
              <td className="num">{signed(x.unrealized_pnl)}</td>
              <td className="num">
                {x.stop_price ? formatDecimalString(x.stop_price, 2, 4) : "—"} /{" "}
                {x.target_price ? formatDecimalString(x.target_price, 2, 4) : "—"}
              </td>
              <td>{formatUtc(x.opened_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
