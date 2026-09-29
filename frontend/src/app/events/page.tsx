import Link from "next/link";
import { api, type MarketEvent } from "@/lib/api";
import { formatDecimalString } from "@/lib/format";

export const dynamic = "force-dynamic";

const CATEGORIES = [
  "company",
  "earnings",
  "central_bank",
  "filing",
  "macro",
  "commodities",
  "geopolitics",
  "crypto",
  "other",
];

type Search = { ticker?: string; category?: string; status?: string };

export default async function EventsPage({ searchParams }: { searchParams: Promise<Search> }) {
  const search = await searchParams;
  const ticker = search.ticker?.toUpperCase().replace(/[^A-Z0-9.-]/g, "").slice(0, 20);
  const category = CATEGORIES.includes(search.category ?? "") ? search.category : undefined;
  const status = search.status === "open" || search.status === "closed" ? search.status : undefined;
  const events = await api.events({ ticker, category, status });

  return (
    <>
      <header className="page-header">
        <h1>Events</h1>
        <p className="muted">
          Related articles grouped into one event by fixed rules: same ticker, similar headline,
          close in time. Importance and confidence are a transparent sum (event type, number of
          outlets and articles, source reliability), not a forecast. Direction is not judged yet.
        </p>
      </header>

      <form className="card filters" method="get">
        <label>
          Ticker <input name="ticker" defaultValue={ticker ?? ""} placeholder="AAPL" size={8} />
        </label>
        <label>
          Category{" "}
          <select name="category" defaultValue={category ?? ""}>
            <option value="">All</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c.replace("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status{" "}
          <select name="status" defaultValue={status ?? ""}>
            <option value="">All</option>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </select>
        </label>
        <button type="submit">Filter</button>
      </form>

      {!events.ok ? (
        <p className="error-note" role="alert">
          {events.error}
        </p>
      ) : events.data.length === 0 ? (
        <div className="card">
          <p>No events match.</p>
          <p className="muted">
            Events are built from collected news, so this is empty until the{" "}
            <Link href="/news">News feed</Link> has articles. <Link href="/">System status</Link>{" "}
            shows the clustering job.
          </p>
        </div>
      ) : (
        <ul className="news-list">
          {events.data.map((e) => (
            <EventCard key={e.id} event={e} />
          ))}
        </ul>
      )}
    </>
  );
}

function EventCard({ event }: { event: MarketEvent }) {
  const outlets = new Set(event.articles.map((a) => a.publisher)).size;
  return (
    <li className="card news-item">
      <h3>{event.title}</h3>
      <p className="muted">
        {event.category.replace("_", " ")} · {event.status} · horizon {event.horizon} · importance{" "}
        {formatDecimalString(event.importance, 2, 2)} · confidence{" "}
        {formatDecimalString(event.confidence, 2, 2)} · {event.articles.length} article
        {event.articles.length === 1 ? "" : "s"} from {outlets} outlet{outlets === 1 ? "" : "s"}
        {event.tickers.map((t) => (
          <Link
            key={t.symbol}
            href={`/events?ticker=${encodeURIComponent(t.symbol)}`}
            className="badge badge-bench"
            title={`In ${formatDecimalString(t.relevance, 0, 2)} of this event's articles`}
          >
            {t.symbol}
          </Link>
        ))}
      </p>
      <p className="muted">
        First seen {event.first_seen_at.replace("T", " ").slice(0, 16)} UTC · usable since{" "}
        {event.available_at.replace("T", " ").slice(0, 16)} UTC · last update{" "}
        {event.last_updated_at.replace("T", " ").slice(0, 16)} UTC
      </p>
      <details>
        <summary>Articles</summary>
        <ul>
          {event.articles.map((a) => (
            <li key={a.id}>
              {a.title} <span className="muted">({a.publisher}{a.is_duplicate ? ", copy" : ""})</span>
            </li>
          ))}
        </ul>
      </details>
    </li>
  );
}
