import { api, type CheckResult, type SystemRun } from "@/lib/api";
import { formatMoneyString, formatUtc } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function SystemStatusPage() {
  const [readiness, info, runs] = await Promise.all([
    api.readiness(),
    api.systemInfo(),
    api.recentRuns(20),
  ]);

  return (
    <>
      <header className="page-header">
        <h1>System status</h1>
        <p className="muted">Live state of the MarketOS services. Nothing on this page is cached.</p>
      </header>

      <section className="grid">
        <div className="card">
          <h2>Backend readiness</h2>
          {readiness.ok ? (
            <>
              <p>
                <StatusPill status={readiness.data.status === "ok" ? "ok" : "error"}>
                  {readiness.data.status === "ok" ? "Ready" : "Degraded"}
                </StatusPill>
              </p>
              <table>
                <tbody>
                  {Object.entries(readiness.data.checks).map(([name, check]) => (
                    <CheckRow key={name} name={name} check={check} />
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <ErrorNote message={readiness.error} />
          )}
        </div>

        <div className="card">
          <h2>Configuration</h2>
          {info.ok ? (
            <dl className="kv">
              <dt>Trading mode</dt>
              <dd>
                <span className="badge badge-paper">{info.data.trading_mode.toUpperCase()}</span>
              </dd>
              <dt>Initial virtual capital</dt>
              <dd>{formatMoneyString(info.data.paper_initial_capital, info.data.base_currency)}</dd>
              <dt>Environment</dt>
              <dd>{info.data.environment}</dd>
              <dt>API version</dt>
              <dd>{info.data.version}</dd>
            </dl>
          ) : (
            <ErrorNote message={info.error} />
          )}
        </div>

        <div className="card">
          <h2>Data providers</h2>
          {info.ok ? (
            <ul className="providers">
              {Object.entries(info.data.providers_configured).map(([name, configured]) => (
                <li key={name}>
                  <StatusPill status={configured ? "ok" : "neutral"}>
                    {configured ? "configured" : "no key"}
                  </StatusPill>
                  {name}
                </li>
              ))}
            </ul>
          ) : (
            <ErrorNote message={info.error} />
          )}
          <p className="muted small">
            Configured means credentials are present. Connectivity is checked when each provider is
            added in Phases 2 and 3.
          </p>
        </div>
      </section>

      <section className="card">
        <h2>Recent background jobs</h2>
        {!runs.ok ? (
          <ErrorNote message={runs.error} />
        ) : runs.data.length === 0 ? (
          <p className="muted">No job has run yet. Start the worker and beat services.</p>
        ) : (
          <RunsTable runs={runs.data} />
        )}
      </section>
    </>
  );
}

function CheckRow({ name, check }: { name: string; check: CheckResult }) {
  return (
    <tr>
      <td>{name}</td>
      <td>
        <StatusPill status={check.status}>{check.status}</StatusPill>
      </td>
      <td className="num">{check.latency_ms} ms</td>
      <td className="muted">{check.error ?? ""}</td>
    </tr>
  );
}

function RunsTable({ runs }: { runs: SystemRun[] }) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Job</th>
            <th>Status</th>
            <th>Provider</th>
            <th>Started</th>
            <th>Finished</th>
            <th className="num">Fetched</th>
            <th className="num">Written</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>{run.job_name}</td>
              <td>
                <StatusPill status={runTone(run.status)}>
                  {run.status}
                </StatusPill>
              </td>
              <td>{run.provider ?? "—"}</td>
              <td>{formatUtc(run.started_at)}</td>
              <td>{formatUtc(run.finished_at)}</td>
              <td className="num">{run.items_fetched ?? "—"}</td>
              <td className="num">{run.items_written ?? "—"}</td>
              <td className="muted">
                {run.error_type ? `${run.error_type}: ${run.error_message ?? ""}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function runTone(status: SystemRun["status"]): "ok" | "error" | "neutral" {
  if (status === "succeeded") return "ok";
  if (status === "running" || status === "skipped") return "neutral";
  return "error"; // failed and partial both need attention
}

function StatusPill({
  status,
  children,
}: {
  status: "ok" | "error" | "neutral";
  children: React.ReactNode;
}) {
  return <span className={`pill pill-${status}`}>{children}</span>;
}

function ErrorNote({ message }: { message: string }) {
  return (
    <p className="error-note" role="alert">
      {message}
    </p>
  );
}
