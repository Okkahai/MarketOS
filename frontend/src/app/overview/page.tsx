import Link from "next/link";
import { api } from "@/lib/api";
import { formatDecimalString, formatUtc } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const [portfolio, signals, trades, decisions, events, usage] = await Promise.all([
    api.portfolio(),
    api.signals({}),
    api.trades(5),
    api.riskDecisions(),
    api.events({ status: "open" }),
    api.aiUsage(),
  ]);

  return (
    <>
      <header className="page-header">
        <h1>Overview</h1>
        <p className="muted">Paper trading only. Nothing here is real money or financial advice.</p>
      </header>

      <section className="grid">
        <div className="card">
          <h2>Portfolio</h2>
          {portfolio.ok ? (
            <>
              <p>
                Total{" "}
                {portfolio.data.total_value
                  ? `${formatDecimalString(portfolio.data.total_value, 2, 2)} USD`
                  : "unknown (a position has no price)"}
              </p>
              <p className="muted">
                Cash {formatDecimalString(portfolio.data.cash, 2, 2)} · {portfolio.data.positions.length}{" "}
                open positions · started with {formatDecimalString(portfolio.data.starting_capital, 2, 2)}
              </p>
              <Link href="/portfolio">Positions</Link>
            </>
          ) : (
            <p className="muted">No paper portfolio yet ({portfolio.error}).</p>
          )}
        </div>
        <div className="card">
          <h2>AI today</h2>
          {usage.ok ? (
            <p>
              {usage.data.calls} model calls, {formatDecimalString(usage.data.spent_usd, 2, 4)} of{" "}
              {formatDecimalString(usage.data.budget_usd, 2, 2)} USD estimated
            </p>
          ) : (
            <p className="muted">{usage.error}</p>
          )}
          <p className="muted">
            {events.ok ? `${events.data.length} open events` : "events unavailable"}
          </p>
        </div>
      </section>

      <section className="card">
        <h2>Latest recommendations</h2>
        {signals.ok && signals.data.length > 0 ? (
          <ul>
            {signals.data.slice(0, 6).map((s) => (
              <li key={s.id}>
                {formatUtc(s.generated_at)} · {s.action.replace("_", " ")}{" "}
                <Link href={`/asset/${encodeURIComponent(s.symbol)}`}>{s.symbol}</Link> ·{" "}
                {formatDecimalString(s.confidence, 2, 2)} · <Link href={`/signals/${s.id}`}>trace</Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">None yet. See <Link href="/journal">the AI journal</Link>.</p>
        )}
      </section>

      <section className="card">
        <h2>Latest risk decisions and trades</h2>
        {decisions.ok && decisions.data.length > 0 ? (
          <ul>
            {decisions.data.slice(0, 5).map((d) => (
              <li key={d.id}>
                {d.decision.toUpperCase()} · {d.action.replace("_", " ")} {d.symbol}
                {d.reasons[0] ? ` · ${d.reasons[0]}` : ""} · <Link href={`/signals/${d.signal_id}`}>trace</Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No decisions yet.</p>
        )}
        {trades.ok && trades.data.length > 0 ? (
          <ul>
            {trades.data.map((t) => (
              <li key={t.id}>
                {formatUtc(t.executed_at)} · {t.side} {t.symbol} at {formatDecimalString(t.price, 2, 4)} ·{" "}
                <Link href={`/signals/${t.signal_id}`}>why</Link>
              </li>
            ))}
          </ul>
        ) : null}
        <p><Link href="/trades">All trades and decisions</Link></p>
      </section>
    </>
  );
}
