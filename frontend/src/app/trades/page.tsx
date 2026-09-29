import Link from "next/link";
import { api, type RiskDecision, type Trade } from "@/lib/api";
import { formatDecimalString, formatUtc } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function TradesPage() {
  const [trades, decisions] = await Promise.all([api.trades(), api.riskDecisions()]);

  return (
    <>
      <header className="page-header">
        <h1>Trades and risk decisions</h1>
        <p className="muted">
          Paper trades are simulated and never edited: a correction is a new opposing trade. Every
          recommendation gets a risk decision, including the ones that did not trade and why.
        </p>
      </header>

      {!trades.ok ? (
        <p className="error-note" role="alert">
          {trades.error}
        </p>
      ) : trades.data.length === 0 ? (
        <div className="card">
          <p>No trades yet.</p>
          <p className="muted">
            Trades appear after a recommendation passes the risk rules and a price arrives to fill
            it. See the decisions below for what happened to each recommendation.
          </p>
        </div>
      ) : (
        <TradeTable trades={trades.data} />
      )}

      {!decisions.ok ? (
        <p className="error-note" role="alert">
          {decisions.error}
        </p>
      ) : (
        <DecisionList decisions={decisions.data} />
      )}
    </>
  );
}

function TradeTable({ trades }: { trades: Trade[] }) {
  return (
    <section className="card table-scroll">
      <h2>Trades</h2>
      <table>
        <thead>
          <tr>
            <th>Executed (UTC)</th>
            <th>Side</th>
            <th>Symbol</th>
            <th>Why</th>
            <th className="num">Quantity</th>
            <th className="num">Price (after slippage)</th>
            <th className="num">Fee</th>
            <th className="num">Realised P&amp;L</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr key={t.id}>
              <td>{formatUtc(t.executed_at)}</td>
              <td>{t.side}</td>
              <td>
                <Link href={`/journal?symbol=${encodeURIComponent(t.symbol)}`}>{t.symbol}</Link>
              </td>
              <td>{t.reason.replace("_", " ")}</td>
              <td className="num">{formatDecimalString(t.quantity, 2, 8)}</td>
              <td className="num" title={`reference ${t.reference_price}, ${t.slippage_bps} bps`}>
                {formatDecimalString(t.price, 2, 4)}
              </td>
              <td className="num">{formatDecimalString(t.fee, 2, 4)}</td>
              <td className="num">{t.side === "SELL" ? formatDecimalString(t.realized_pnl, 2, 2) : "—"}</td>
              <td>
                <Link href={`/signals/${t.signal_id}`}>Trace</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function DecisionList({ decisions }: { decisions: RiskDecision[] }) {
  if (decisions.length === 0) return null;
  return (
    <section>
      <h2>Risk decisions</h2>
      <ul className="news-list">
        {decisions.map((d) => (
          <li key={d.id} className="card news-item">
            <h3>
              {d.decision.toUpperCase()} · {d.action.replace("_", " ")} {d.symbol}{" "}
              <span className="muted">
                · confidence {formatDecimalString(d.confidence, 2, 2)} · {formatUtc(d.decided_at)}
              </span>
            </h3>
            {d.approved_notional ? (
              <p className="muted">
                Budget {formatDecimalString(d.approved_notional, 2, 2)} USD
                {d.requested_notional && d.requested_notional !== d.approved_notional
                  ? ` (asked for ${formatDecimalString(d.requested_notional, 2, 2)})`
                  : ""}
              </p>
            ) : null}
            {d.reasons.length > 0 ? (
              <ul>
                {d.reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            ) : null}
            <p>
              <Link href={`/signals/${d.signal_id}`}>Full trace</Link>
            </p>
            <details>
              <summary>All {d.rules_evaluated.length} rules checked</summary>
              <ul>
                {d.rules_evaluated.map((r, i) => (
                  <li key={i}>
                    {r.passed ? "pass" : "FAIL"} · {r.rule}: {r.detail}
                  </li>
                ))}
              </ul>
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}
