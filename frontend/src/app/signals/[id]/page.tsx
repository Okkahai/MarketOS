import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { formatDecimalString, formatUtc } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function TracePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const result = await api.trace(id);
  if (!result.ok && result.httpStatus === 404) notFound();
  if (!result.ok) {
    return (
      <p className="error-note" role="alert">
        {result.error}
      </p>
    );
  }
  const t = result.data;
  const s = t.signal;

  return (
    <>
      <header className="page-header">
        <h1>
          {s.action.replace("_", " ")} <Link href={`/asset/${encodeURIComponent(s.symbol)}`}>{s.symbol}</Link>
        </h1>
        <p className="muted">
          The full chain behind this recommendation: what the model saw, what it said, what the risk
          rules decided, and what was traded. Each step is a stored record that is never edited.
        </p>
      </header>

      <section className="card">
        <h2>1. The event</h2>
        <p>
          <strong>{t.event.title}</strong> ({t.event.category}, importance{" "}
          {formatDecimalString(t.event.importance, 2, 2)}) first seen {formatUtc(t.event.first_seen_at)}
        </p>
        <ul>
          {t.articles.map((a) => (
            <li key={a.id}>
              {a.source} · {formatUtc(a.published_at)} · {a.title}
              {a.is_copy ? " (copy)" : ""}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h2>2. What the AI said</h2>
        <p className="muted">
          {formatUtc(s.generated_at)} · confidence {formatDecimalString(s.confidence, 2, 2)} · horizon{" "}
          {s.time_horizon} · price seen {formatDecimalString(s.reference_price)} (bar{" "}
          {s.reference_price_ts.slice(0, 10)}) · model {t.analysis.model_version ?? t.analysis.model},
          prompt {t.analysis.prompt_version}
        </p>
        {s.thesis ? <p>{s.thesis}</p> : null}
        {s.bear_case ? <p><strong>Bear case:</strong> {s.bear_case}</p> : null}
        {s.invalidation_conditions.length > 0 ? (
          <p><strong>Invalidated if:</strong> {s.invalidation_conditions.join("; ")}</p>
        ) : null}
        <p className="muted small">Input fingerprint (SHA-256): {t.analysis.context_sha256}</p>
      </section>

      <section className="card">
        <h2>3. Risk verdict</h2>
        {t.decision ? (
          <>
            <p>
              <strong>{t.decision.decision.toUpperCase()}</strong>
              {t.decision.approved_notional
                ? ` · budget ${formatDecimalString(t.decision.approved_notional, 2, 2)} USD`
                : ""}
            </p>
            <ul>
              {t.decision.rules_evaluated.map((r, i) => (
                <li key={i}>
                  {r.passed ? "pass" : "FAIL"} · {r.rule}: {r.detail}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="muted">Not judged yet: the paper trading cycle has not reached this signal.</p>
        )}
      </section>

      <section className="card">
        <h2>4. Orders and trades</h2>
        {t.orders.length === 0 && t.trades.length === 0 ? (
          <p className="muted">No order was placed for this recommendation.</p>
        ) : null}
        <ul>
          {t.orders.map((o) => (
            <li key={o.id}>
              Order {o.side} ({o.reason.replace("_", " ")}) · {o.status} · decided{" "}
              {formatUtc(o.signal_time)}
            </li>
          ))}
          {t.trades.map((x) => (
            <li key={x.id}>
              Trade {x.side} {formatDecimalString(x.quantity, 2, 8)} at {formatDecimalString(x.price, 2, 4)}{" "}
              (reference {formatDecimalString(x.reference_price, 2, 4)}, fee{" "}
              {formatDecimalString(x.fee, 2, 4)}) · {formatUtc(x.executed_at)}
              {x.side === "SELL" ? ` · realised ${formatDecimalString(x.realized_pnl, 2, 2)}` : ""}
            </li>
          ))}
        </ul>
        {t.position ? (
          <p className="muted">
            Position opened {formatUtc(t.position.opened_at)}, stop{" "}
            {t.position.stop_price ? formatDecimalString(t.position.stop_price, 2, 4) : "none"}, target{" "}
            {t.position.target_price ? formatDecimalString(t.position.target_price, 2, 4) : "none"}.
          </p>
        ) : null}
      </section>
    </>
  );
}
