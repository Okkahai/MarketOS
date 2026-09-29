import Link from "next/link";
import { api, type AnalyticsSummary, type Snapshot } from "@/lib/api";
import { formatUtc } from "@/lib/format";

export const dynamic = "force-dynamic";

const num = (v: number | null, digits = 2, suffix = "") =>
  v === null || v === undefined ? "—" : `${v.toFixed(digits)}${suffix}`;
const signed = (v: number | null, suffix = "") =>
  v === null || v === undefined ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}${suffix}`;

export default async function AnalyticsPage() {
  const [summary, evaluations, snapshots] = await Promise.all([
    api.analytics(),
    api.evaluations(),
    api.snapshots(),
  ]);

  return (
    <>
      <header className="page-header">
        <h1>Analytics</h1>
        <p className="muted">
          How the paper portfolio and the AI&apos;s recommendations have done, wins and losses
          alike. Small samples say little: read these numbers as a log, not as evidence of skill.
        </p>
      </header>

      {!summary.ok ? (
        <p className="error-note" role="alert">
          {summary.error}
        </p>
      ) : (
        <>
          <Portfolio s={summary.data} />
          {snapshots.ok ? <EquityCurve points={snapshots.data} /> : null}
          <Trades s={summary.data} />
          <Predictions s={summary.data} />
        </>
      )}

      <section className="card table-scroll">
        <h2>Recommendations judged afterwards</h2>
        {!evaluations.ok ? (
          <p className="error-note" role="alert">
            {evaluations.error}
          </p>
        ) : evaluations.data.length === 0 ? (
          <p className="muted">
            Nothing judged yet. A recommendation is evaluated once its horizon (1, 3, 7 or 30 days)
            has fully passed and daily bars for it exist.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Signal (UTC)</th>
                <th>Action</th>
                <th>Symbol</th>
                <th>Horizon</th>
                <th className="num">Return</th>
                <th className="num">vs benchmark</th>
                <th className="num">Best / worst</th>
                <th>Call</th>
              </tr>
            </thead>
            <tbody>
              {evaluations.data.map((e) => (
                <tr key={`${e.signal_id}-${e.horizon}`}>
                  <td>{formatUtc(e.generated_at)}</td>
                  <td>{e.action.replace("_", " ")}</td>
                  <td>
                    <Link href={`/signals/${e.signal_id}`}>{e.symbol}</Link>
                  </td>
                  <td>{e.horizon}</td>
                  <td className="num">{signed(e.return_pct, "%")}</td>
                  <td className="num">
                    {signed(e.excess_return_pct)} {e.benchmark_symbol ? `(${e.benchmark_symbol})` : ""}
                  </td>
                  <td className="num">
                    {signed(e.mfe_pct)} / {signed(e.mae_pct)}
                  </td>
                  <td>
                    {e.direction_correct === null ? "no view" : e.direction_correct ? "right" : "WRONG"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted small">
          Start price is the last close the model saw; end price is the last daily close inside the
          horizon. A flat result counts as wrong for a directional call.
        </p>
      </section>
    </>
  );
}

function Portfolio({ s }: { s: AnalyticsSummary }) {
  const p = s.portfolio;
  return (
    <section className="card table-scroll">
      <h2>Portfolio versus the alternatives</h2>
      {p.days < 2 ? (
        <p className="muted">
          Needs at least two days of complete value snapshots ({p.days} so far).
        </p>
      ) : (
        <>
          <p>
            Return {signed(p.return_pct, "%")} over {p.days} days · max drawdown{" "}
            {num(p.max_drawdown_pct, 2, "%")} · Sharpe {num(p.sharpe)} · Sortino {num(p.sortino)}
          </p>
          <table>
            <thead>
              <tr>
                <th>Compared with</th>
                <th className="num">Return, same window</th>
              </tr>
            </thead>
            <tbody>
              {s.benchmarks.map((b) => (
                <tr key={b.symbol}>
                  <td>{b.symbol === "CASH" ? "Holding cash" : b.symbol}</td>
                  <td className="num">{signed(b.return_pct, "%")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <p className="muted small">
        {s.notes}
        {p.incomplete_snapshots > 0 ? ` ${p.incomplete_snapshots} snapshots lacked a price.` : ""}
      </p>
    </section>
  );
}

function EquityCurve({ points }: { points: Snapshot[] }) {
  const pts = points.filter((x) => x.total_value !== null).map((x) => Number(x.total_value));
  if (pts.length < 2) return null;
  const lo = Math.min(...pts);
  const hi = Math.max(...pts);
  const span = hi - lo || 1;
  const path = pts
    .map((v, i) => `${(i / (pts.length - 1)) * 600},${100 - ((v - lo) / span) * 90 - 5}`)
    .join(" ");
  return (
    <section className="card">
      <h2>Portfolio value</h2>
      <svg viewBox="0 0 600 100" role="img" aria-label="Portfolio value over time" width="100%" height="120">
        <polyline points={path} fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      <p className="muted small">
        {lo.toFixed(2)} to {hi.toFixed(2)} USD across {pts.length} snapshots.
      </p>
    </section>
  );
}

function Trades({ s }: { s: AnalyticsSummary }) {
  const t = s.trades;
  return (
    <section className="card table-scroll">
      <h2>Closed positions</h2>
      {t.closed === 0 ? (
        <p className="muted">No position has been closed yet.</p>
      ) : (
        <>
          <p>
            {t.closed} closed · win rate {t.win_rate === null ? "—" : `${(t.win_rate * 100).toFixed(0)}%`}{" "}
            · profit factor {t.profit_factor === null ? "— (no losses)" : t.profit_factor.toFixed(2)} ·
            average win {num(t.avg_win)} · average loss {num(t.avg_loss)} · expectancy{" "}
            {num(t.expectancy)} per trade
          </p>
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="num">Realised P&amp;L</th>
                <th>Closed (UTC)</th>
                <th>Why</th>
              </tr>
            </thead>
            <tbody>
              {s.closed_positions.map((c) => (
                <tr key={c.signal_id + c.closed_at}>
                  <td>{c.symbol}</td>
                  <td className="num">{signed(c.realized_pnl)}</td>
                  <td>{formatUtc(c.closed_at)}</td>
                  <td>
                    <Link href={`/signals/${c.signal_id}`}>Trace</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

function Predictions({ s }: { s: AnalyticsSummary }) {
  return (
    <section className="card table-scroll">
      <h2>How often the AI was right</h2>
      <table>
        <thead>
          <tr>
            <th>Horizon</th>
            <th className="num">Judged</th>
            <th className="num">Hit rate</th>
            <th className="num">Avg return</th>
            <th className="num">Avg vs benchmark</th>
          </tr>
        </thead>
        <tbody>
          {s.predictions.map((p) => (
            <tr key={p.horizon}>
              <td>{p.horizon}</td>
              <td className="num">{p.evaluated}</td>
              <td className="num">
                {p.hit_rate === null ? "—" : `${(p.hit_rate * 100).toFixed(0)}% of ${p.directional}`}
              </td>
              <td className="num">{signed(p.avg_return_pct, "%")}</td>
              <td className="num">{signed(p.avg_excess_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
