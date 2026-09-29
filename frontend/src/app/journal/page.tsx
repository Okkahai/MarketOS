import Link from "next/link";
import { api, type Analysis, type Signal } from "@/lib/api";
import { formatDecimalString } from "@/lib/format";

export const dynamic = "force-dynamic";

const ACTIONS = ["STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL", "AVOID"];

type Search = { symbol?: string; action?: string };

export default async function JournalPage({ searchParams }: { searchParams: Promise<Search> }) {
  const search = await searchParams;
  const symbol = search.symbol?.toUpperCase().replace(/[^A-Z0-9.-]/g, "").slice(0, 32);
  const action = ACTIONS.includes(search.action ?? "") ? search.action : undefined;
  const [signals, analyses, usage] = await Promise.all([
    api.signals({ symbol, action }),
    api.analyses(),
    api.aiUsage(),
  ]);

  return (
    <>
      <header className="page-header">
        <h1>AI journal</h1>
        <p className="muted">
          Every recommendation the AI has made, whether or not it was traded, with the reasoning it
          gave and the price it saw. Recommendations are advisory: paper trades only follow after
          the risk rules. Nothing here is a forecast of returns.
        </p>
      </header>

      {usage.ok ? (
        <div className="card">
          <strong>Today (UTC {usage.data.day})</strong>: {usage.data.calls} model calls (
          {usage.data.failed_calls} not valid), estimated spend{" "}
          {formatDecimalString(usage.data.spent_usd, 2, 4)} of{" "}
          {formatDecimalString(usage.data.budget_usd, 2, 2)} USD, {usage.data.input_tokens} input and{" "}
          {usage.data.output_tokens} output tokens.
        </div>
      ) : null}

      <form className="card filters" method="get">
        <label>
          Symbol <input name="symbol" defaultValue={symbol ?? ""} placeholder="AAPL" size={8} />
        </label>
        <label>
          Action{" "}
          <select name="action" defaultValue={action ?? ""}>
            <option value="">All</option>
            {ACTIONS.map((a) => (
              <option key={a} value={a}>
                {a.replace("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Filter</button>
      </form>

      {!signals.ok ? (
        <p className="error-note" role="alert">
          {signals.error}
        </p>
      ) : signals.data.length === 0 ? (
        <div className="card">
          <p>No recommendations yet.</p>
          <p className="muted">
            The analysis job needs <code>ANTHROPIC_API_KEY</code> and a price for each model in{" "}
            <code>AI_MODEL_PRICES</code>, and only looks at events with importance above the
            configured minimum. <Link href="/">System status</Link> shows why a run was skipped.
          </p>
        </div>
      ) : (
        <ul className="news-list">
          {signals.data.map((s) => (
            <SignalCard key={s.id} signal={s} />
          ))}
        </ul>
      )}

      {analyses.ok ? <Calls analyses={analyses.data} /> : null}
    </>
  );
}

function SignalCard({ signal: s }: { signal: Signal }) {
  return (
    <li className="card news-item">
      <h3>
        {s.action.replace("_", " ")} {s.symbol}{" "}
        <span className="muted">
          · confidence {formatDecimalString(s.confidence, 2, 2)} · horizon {s.time_horizon}
        </span>
      </h3>
      <p className="muted">
        For event: {s.event_title} · at {s.generated_at.replace("T", " ").slice(0, 16)} UTC · price
        seen {formatDecimalString(s.reference_price)} (bar {s.reference_price_ts.slice(0, 10)})
      </p>
      {s.thesis ? <p>{s.thesis}</p> : null}
      <details>
        <summary>Reasoning, risks and evidence</summary>
        {s.bull_case ? <p><strong>Bull case:</strong> {s.bull_case}</p> : null}
        {s.bear_case ? <p><strong>Bear case:</strong> {s.bear_case}</p> : null}
        <List title="Catalysts" items={s.key_catalysts} />
        <List title="Risks" items={s.risks} />
        <List title="Invalidated if" items={s.invalidation_conditions} />
        <List title="Evidence" items={s.evidence.map((e) => e.quote_or_fact)} />
        <p className="muted">
          Suggested (advisory): size {s.suggested_position_size_pct ?? "—"}%, stop{" "}
          {s.suggested_stop_loss_pct ?? "—"}%, take profit {s.suggested_take_profit_pct ?? "—"}%.
        </p>
      </details>
    </li>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <>
      <strong>{title}:</strong>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </>
  );
}

function Calls({ analyses }: { analyses: Analysis[] }) {
  return (
    <section className="card table-scroll">
      <h2>Recent model calls</h2>
      <table>
        <thead>
          <tr>
            <th>When (UTC)</th>
            <th>Stage</th>
            <th>Event</th>
            <th>Model</th>
            <th>Result</th>
            <th className="num">Tokens in/out</th>
            <th className="num">Est. cost</th>
          </tr>
        </thead>
        <tbody>
          {analyses.map((a) => (
            <tr key={a.id}>
              <td>{a.as_of.replace("T", " ").slice(0, 16)}</td>
              <td>{a.stage}</td>
              <td>{a.event_title}</td>
              <td>{a.model_version ?? a.model}</td>
              <td title={a.validation_errors?.join("; ") ?? ""}>{a.validation_status}</td>
              <td className="num">
                {a.input_tokens}/{a.output_tokens}
              </td>
              <td className="num">{formatDecimalString(a.estimated_cost_usd, 2, 6)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
