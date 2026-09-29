// Typed client for the MarketOS API. Server components call the API over the
// internal network (API_INTERNAL_URL); nothing here ever invents a value when
// the API is unreachable, it returns an explicit error instead.

export type CheckResult = {
  status: "ok" | "error";
  latency_ms: number;
  error: string | null;
};

export type Readiness = {
  status: "ok" | "degraded";
  checks: Record<string, CheckResult>;
};

export type SystemInfo = {
  version: string;
  environment: string;
  trading_mode: "paper";
  base_currency: string;
  paper_initial_capital: string; // decimal string, never parsed to float
  providers_configured: Record<string, boolean>;
};

export type SystemRun = {
  id: string;
  job_name: string;
  status: "running" | "succeeded" | "partial" | "failed" | "skipped";
  provider: string | null;
  started_at: string;
  finished_at: string | null;
  items_fetched: number | null;
  items_written: number | null;
  error_type: string | null;
  error_message: string | null;
};

export type Interval = "1m" | "5m" | "1h" | "1d";

export type Asset = {
  symbol: string;
  name: string;
  asset_class: "stock" | "etf" | "crypto";
  exchange: string | null;
  sector: string | null;
  currency: string;
  is_benchmark: boolean;
  is_active: boolean;
};

// Prices and volumes are decimal strings straight from the API; only the chart converts them.
export type Bar = {
  ts: string;
  open: string;
  high: string;
  low: string;
  close: string;
  adj_close: string | null;
  volume: string;
  available_at: string;
  revision: number;
};

export type WatchlistRow = {
  symbol: string;
  name: string;
  asset_class: string;
  is_benchmark: boolean;
  provider: string;
  last_close: string | null;
  last_bar_ts: string | null;
  last_available_at: string | null;
  change_pct: string | null;
  volume: string | null;
};

export type Indicator = { name: string; ts: string; value: string };

export type NewsArticle = {
  id: string;
  source: string;
  title: string;
  summary: string;
  url: string;
  published_at: string;
  available_at: string;
  category: string;
  tickers: string[];
  countries: string[];
  duplicate_of_id: string | null;
  dedup_reason: string | null;
};

export type NewsSource = {
  key: string;
  name: string;
  kind: string;
  reliability_weight: string;
  is_enabled: boolean;
  terms_note: string;
};

export type EventArticle = {
  id: string;
  title: string;
  publisher: string;
  published_at: string;
  available_at: string;
  is_duplicate: boolean;
};

export type MarketEvent = {
  id: string;
  title: string;
  summary: string;
  category: string;
  importance: string; // decimal string, 0 to 1
  confidence: string;
  horizon: string;
  status: "open" | "closed";
  countries: string[];
  tickers: { symbol: string; relevance: string }[];
  first_seen_at: string;
  last_updated_at: string;
  available_at: string;
  articles: EventArticle[];
  score_details: Record<string, unknown>;
};

export type Signal = {
  id: string;
  analysis_id: string;
  symbol: string;
  generated_at: string;
  action: "STRONG_BUY" | "BUY" | "HOLD" | "REDUCE" | "SELL" | "AVOID";
  direction: "long" | "flat" | "exit";
  confidence: string;
  time_horizon: string;
  reference_price: string;
  reference_price_ts: string;
  thesis: string;
  bull_case: string;
  bear_case: string;
  key_catalysts: string[];
  risks: string[];
  invalidation_conditions: string[];
  evidence: { source_article_id: string; quote_or_fact: string }[];
  suggested_position_size_pct: string | null;
  suggested_stop_loss_pct: string | null;
  suggested_take_profit_pct: string | null;
  event_id: string;
  event_title: string;
};

export type Analysis = {
  id: string;
  event_id: string;
  event_title: string;
  stage: "triage" | "analysis";
  as_of: string;
  model: string;
  model_version: string | null;
  prompt_version: string;
  validation_status: "valid" | "invalid" | "refused" | "error";
  validation_errors: string[] | null;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: string;
  latency_ms: number;
};

export type AiUsage = {
  day: string;
  spent_usd: string;
  budget_usd: string;
  calls: number;
  failed_calls: number;
  input_tokens: number;
  output_tokens: number;
};

export type ApiResult<T> =
  | { ok: true; data: T; httpStatus: number }
  | { ok: false; error: string; httpStatus: number | null };

export function apiBaseUrl(): string {
  return (
    process.env.API_INTERNAL_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    "http://localhost:8000"
  ).replace(/\/+$/, "");
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

// Readiness returns 503 with a valid body when a dependency is down, so callers
// can opt in to reading bodies of specific non-2xx statuses.
export async function getJson<T>(
  path: string,
  options: { acceptStatuses?: number[]; timeoutMs?: number; fetchImpl?: FetchLike } = {},
): Promise<ApiResult<T>> {
  const { acceptStatuses = [], timeoutMs = 3000, fetchImpl = fetch } = options;
  let response: Response;
  try {
    response = await fetchImpl(`${apiBaseUrl()}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
      headers: { accept: "application/json" },
    });
  } catch (err) {
    const reason = err instanceof Error ? err.name : "UnknownError";
    return { ok: false, error: `API unreachable (${reason})`, httpStatus: null };
  }
  if (!response.ok && !acceptStatuses.includes(response.status)) {
    return { ok: false, error: `API returned HTTP ${response.status}`, httpStatus: response.status };
  }
  try {
    return { ok: true, data: (await response.json()) as T, httpStatus: response.status };
  } catch {
    return { ok: false, error: "API returned invalid JSON", httpStatus: response.status };
  }
}

export const api = {
  readiness: () => getJson<Readiness>("/health/ready", { acceptStatuses: [503] }),
  systemInfo: () => getJson<SystemInfo>("/api/v1/system/info"),
  watchlist: () => getJson<WatchlistRow[]>("/api/v1/market/watchlist"),
  asset: (symbol: string) => getJson<Asset>(`/api/v1/assets/${encodeURIComponent(symbol)}`),
  intervals: (symbol: string) =>
    getJson<Interval[]>(`/api/v1/assets/${encodeURIComponent(symbol)}/intervals`),
  bars: (symbol: string, interval: Interval, limit = 300) =>
    getJson<Bar[]>(
      `/api/v1/assets/${encodeURIComponent(symbol)}/bars?interval=${interval}&limit=${limit}`,
    ),
  indicators: (symbol: string) =>
    getJson<Indicator[]>(`/api/v1/assets/${encodeURIComponent(symbol)}/indicators`),
  newsArticles: (params: { ticker?: string; category?: string; duplicates?: boolean } = {}) => {
    const q = new URLSearchParams({ limit: "100" });
    if (params.ticker) q.set("ticker", params.ticker);
    if (params.category) q.set("category", params.category);
    if (params.duplicates) q.set("include_duplicates", "true");
    return getJson<NewsArticle[]>(`/api/v1/news/articles?${q}`);
  },
  newsSources: () => getJson<NewsSource[]>("/api/v1/news/sources"),
  events: (params: { ticker?: string; category?: string; status?: string } = {}) => {
    const q = new URLSearchParams({ limit: "50" });
    if (params.ticker) q.set("ticker", params.ticker);
    if (params.category) q.set("category", params.category);
    if (params.status) q.set("status", params.status);
    return getJson<MarketEvent[]>(`/api/v1/events?${q}`);
  },
  signals: (params: { symbol?: string; action?: string } = {}) => {
    const q = new URLSearchParams({ limit: "50" });
    if (params.symbol) q.set("symbol", params.symbol);
    if (params.action) q.set("action", params.action);
    return getJson<Signal[]>(`/api/v1/signals?${q}`);
  },
  analyses: (limit = 30) => getJson<Analysis[]>(`/api/v1/ai/analyses?limit=${limit}`),
  aiUsage: () => getJson<AiUsage>("/api/v1/ai/usage"),
  recentRuns: (limit = 20) => getJson<SystemRun[]>(`/api/v1/system/runs?limit=${limit}`),
};
