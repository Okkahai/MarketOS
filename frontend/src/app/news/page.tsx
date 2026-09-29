import Link from "next/link";
import { api, type NewsArticle } from "@/lib/api";
import { safeHttpUrl } from "@/lib/format";

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

type Search = { ticker?: string; category?: string; duplicates?: string };

export default async function NewsPage({ searchParams }: { searchParams: Promise<Search> }) {
  const search = await searchParams;
  const ticker = search.ticker?.toUpperCase().replace(/[^A-Z0-9.-]/g, "").slice(0, 20);
  const category = CATEGORIES.includes(search.category ?? "") ? search.category : undefined;
  const duplicates = search.duplicates === "1";
  const [articles, sources] = await Promise.all([
    api.newsArticles({ ticker, category, duplicates }),
    api.newsSources(),
  ]);

  return (
    <>
      <header className="page-header">
        <h1>News feed</h1>
        <p className="muted">
          Headlines and filings as collected, newest first. Category and tickers come from fixed
          rules, not from an AI, and sentiment or importance are not scored yet. “Usable since” is
          the earliest moment a decision may rely on the item.
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
          <input type="checkbox" name="duplicates" value="1" defaultChecked={duplicates} /> Show
          duplicates
        </label>
        <button type="submit">Filter</button>
      </form>

      {!articles.ok ? (
        <p className="error-note" role="alert">
          {articles.error}
        </p>
      ) : articles.data.length === 0 ? (
        <div className="card">
          <p>No articles match.</p>
          <p className="muted">
            Nothing has been collected, or the filter is too narrow. Stock headlines need{" "}
            <code>TIINGO_API_KEY</code>, filings need <code>SEC_USER_AGENT</code>; Federal Reserve
            feeds need nothing. <Link href="/">System status</Link> shows each run and failure.
          </p>
        </div>
      ) : (
        <ul className="news-list">
          {articles.data.map((a) => (
            <Article key={a.id} article={a} />
          ))}
        </ul>
      )}

      {sources.ok ? (
        <section className="card">
          <h2>Sources</h2>
          <ul>
            {sources.data.map((s) => (
              <li key={s.key}>
                <strong>{s.name}</strong> ({s.kind}, weight {s.reliability_weight}
                {s.is_enabled ? "" : ", disabled"}): <span className="muted">{s.terms_note}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

function Article({ article }: { article: NewsArticle }) {
  const href = safeHttpUrl(article.url);
  return (
    <li className="card news-item">
      <h3>
        {href ? (
          <a href={href} target="_blank" rel="noopener noreferrer nofollow">
            {article.title}
          </a>
        ) : (
          article.title
        )}
      </h3>
      <p className="muted">
        {article.source} · {article.category.replace("_", " ")} · published{" "}
        {article.published_at.replace("T", " ").slice(0, 16)} UTC · usable since{" "}
        {article.available_at.replace("T", " ").slice(0, 16)} UTC
        {article.tickers.map((t) => (
          <Link key={t} href={`/news?ticker=${encodeURIComponent(t)}`} className="badge badge-bench">
            {t}
          </Link>
        ))}
        {article.duplicate_of_id ? (
          <span className="badge badge-bench">duplicate ({article.dedup_reason})</span>
        ) : null}
      </p>
      {article.summary ? <p>{article.summary}</p> : null}
    </li>
  );
}
