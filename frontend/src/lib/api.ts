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
  recentRuns: (limit = 20) => getJson<SystemRun[]>(`/api/v1/system/runs?limit=${limit}`),
};
